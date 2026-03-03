from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, has_permission
from app.models.dossier_requisition import DossierRequisition
from app.models.requisition import Requisition
from app.models.user import User
from app.models.rbac import Permission, role_permissions, Role
from app.schemas.dossier_requisition import (
    DossierRequisitionCreate,
    DossierRequisitionOut,
    DossierRequisitionUpdate,
)
from app.api.v1.endpoints.requisitions import _requisition_out, _schedule_bureau_notifications
from app.services.document_sequences import generate_document_number


router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dossier_out(dossier: DossierRequisition, requisitions: list[Requisition]) -> DossierRequisitionOut:
    return DossierRequisitionOut(
        id=str(dossier.id),
        reference=dossier.reference,
        description=dossier.description,
        status=dossier.status,
        commentaires_examen=dossier.commentaires_examen,
        created_by=str(dossier.created_by) if dossier.created_by else None,
        created_at=dossier.created_at,
        updated_at=dossier.updated_at,
        requisitions=[_requisition_out(r) for r in requisitions],
    )


async def _ensure_validation_access(user: User, db: AsyncSession) -> None:
    if (user.role or "").lower() == "admin":
        return
    if not user.role_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions requises")
    perm_query = (
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
    )
    res = await db.execute(perm_query)
    perm_codes = {row[0] for row in res.all()}
    if perm_codes.intersection({"can_verify_technical", "can_validate_final"}):
        return
    role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
    role_code = (role_res.scalar_one_or_none() or "").lower()
    if role_code == "admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Privilèges insuffisants")


@router.post("", response_model=DossierRequisitionOut)
async def create_dossier_requisition(
    payload: DossierRequisitionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("requisitions")),
) -> DossierRequisitionOut:
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        try:
            ids.append(uuid.UUID(rid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(select(Requisition).where(Requisition.id.in_(ids), Requisition.is_deleted.is_(False)))
    requisitions = res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
    for req in requisitions:
        if req.dossier_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Réquisition déjà rattachée à un dossier: {req.numero_requisition}",
            )

    reference = await generate_document_number(db, "DG")
    dossier = DossierRequisition(
        reference=reference,
        description=payload.description,
        status="EN_EXAMEN",
        created_by=user.id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(dossier)
    await db.flush()

    for req in requisitions:
        req.dossier_id = dossier.id
        req.examen_status = "EN_EXAMEN"
        req.examen_commentaire = None
        req.examen_par = None
        req.examen_le = None
        req.updated_at = _utcnow()

    await db.commit()
    await db.refresh(dossier)
    return _dossier_out(dossier, requisitions)


@router.get("/{dossier_id}", response_model=DossierRequisitionOut)
async def get_dossier_requisition(
    dossier_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    return _dossier_out(dossier, requisitions)


@router.get("", response_model=list[DossierRequisitionOut])
async def list_dossiers_requisition(
    status: str | None = Query(default=None),
    include_requisitions: bool = Query(default=False),
    order: str | None = Query(default="created_at.desc"),
    limit: int | None = Query(default=100),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DossierRequisitionOut]:
    await _ensure_validation_access(user, db)
    query = select(DossierRequisition)
    if status:
        query = query.where(DossierRequisition.status == status)
    if order and order.endswith(".asc"):
        query = query.order_by(DossierRequisition.created_at.asc())
    else:
        query = query.order_by(DossierRequisition.created_at.desc())
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    res = await db.execute(query)
    dossiers = res.scalars().all()
    if not include_requisitions:
        return [
            DossierRequisitionOut(
                id=str(d.id),
                reference=d.reference,
                description=d.description,
                status=d.status,
                commentaires_examen=d.commentaires_examen,
                created_by=str(d.created_by) if d.created_by else None,
                created_at=d.created_at,
                updated_at=d.updated_at,
                requisitions=[],
            )
            for d in dossiers
        ]

    dossier_ids = [d.id for d in dossiers]
    req_map: dict[uuid.UUID, list[Requisition]] = {d.id: [] for d in dossiers}
    if dossier_ids:
        req_res = await db.execute(select(Requisition).where(Requisition.dossier_id.in_(dossier_ids)))
        for req in req_res.scalars().all():
            if req.dossier_id in req_map:
                req_map[req.dossier_id].append(req)

    return [_dossier_out(d, req_map.get(d.id, [])) for d in dossiers]


@router.patch("/{dossier_id}", response_model=DossierRequisitionOut)
async def update_dossier_requisition(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("requisitions")),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    if payload.description is not None:
        dossier.description = payload.description
    if payload.commentaires_examen is not None:
        dossier.commentaires_examen = payload.commentaires_examen
    dossier.updated_at = _utcnow()

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    await db.commit()
    return _dossier_out(dossier, requisitions)


@router.post("/{dossier_id}/validate-examen", response_model=DossierRequisitionOut)
async def validate_examen_dossier(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    if not requisitions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier sans réquisitions")

    dossier.status = "EXAMINE"
    if payload.commentaires_examen is not None:
        dossier.commentaires_examen = payload.commentaires_examen
    dossier.updated_at = _utcnow()

    for req in requisitions:
        req.examen_status = "EXAMINE"
        req.examen_commentaire = payload.commentaires_examen
        req.examen_par = user.id
        req.examen_le = _utcnow()
        req.updated_at = _utcnow()

    await db.commit()
    await db.refresh(dossier)

    for req in requisitions:
        await _schedule_bureau_notifications(db=db, background_tasks=background_tasks, req=req, action_user=user)

    return _dossier_out(dossier, requisitions)


@router.post("/{dossier_id}/reject-examen", response_model=DossierRequisitionOut)
async def reject_examen_dossier(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()

    dossier.status = "REJETE"
    if payload.commentaires_examen is not None:
        dossier.commentaires_examen = payload.commentaires_examen
    dossier.updated_at = _utcnow()

    for req in requisitions:
        req.examen_status = "REJETE"
        req.examen_commentaire = payload.commentaires_examen
        req.examen_par = user.id
        req.examen_le = _utcnow()
        req.updated_at = _utcnow()

    await db.commit()
    await db.refresh(dossier)
    return _dossier_out(dossier, requisitions)
