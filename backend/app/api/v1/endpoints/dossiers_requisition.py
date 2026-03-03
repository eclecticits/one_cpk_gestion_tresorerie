from __future__ import annotations

import uuid
from datetime import datetime, timezone
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, has_permission
from app.models.dossier_requisition import DossierRequisition
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.user import User
from app.models.rbac import Permission, role_permissions, Role
from app.schemas.dossier_requisition import (
    DossierRequisitionAdd,
    DossierRequisitionCreate,
    DossierRequisitionOut,
    DossierRequisitionRemove,
    DossierRequisitionUpdate,
)
from app.api.v1.endpoints.requisitions import (
    _annexe_fs_path,
    _requisition_out,
    _requisition_pdf_fs_path,
    _schedule_bureau_notifications,
)
from app.services.mailer import send_dossier_notification, send_requisition_workflow_email
from app.models.system_settings import SystemSettings
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


async def _schedule_dossier_notifications(
    *,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    dossier: DossierRequisition,
    requisitions: list[Requisition],
    action_user: User,
) -> None:
    try:
        settings_res = await db.execute(select(SystemSettings).limit(1))
        ns = settings_res.scalar_one_or_none()
        if not ns or not ns.email_expediteur:
            return

        smtp_password = (ns.smtp_password or "").strip()
        if not smtp_password:
            return

        created_by_name = " ".join(filter(None, [action_user.prenom, action_user.nom])) or action_user.email or "Systeme"

        requisition_nums = [req.numero_requisition for req in requisitions if req.numero_requisition]
        total_amount = sum(float(req.montant_total or 0) for req in requisitions)

        attachment_paths: list[str] = []
        for req in requisitions:
            if req.pdf_path:
                pdf_path = _requisition_pdf_fs_path(req.pdf_path)
                if pdf_path and os.path.exists(pdf_path):
                    attachment_paths.append(pdf_path)

        if requisitions:
            ann_res = await db.execute(
                select(RequisitionAnnexe)
                .where(RequisitionAnnexe.requisition_id.in_([r.id for r in requisitions]))
                .order_by(RequisitionAnnexe.upload_date.asc())
            )
            annexes = ann_res.scalars().all()
            attachment_paths.extend([_annexe_fs_path(a.file_path) for a in annexes])

        if ns.email_validation_1:
            background_tasks.add_task(
                send_requisition_workflow_email,
                smtp_host=ns.smtp_host or "smtp.gmail.com",
                smtp_port=int(ns.smtp_port or 465),
                smtp_user=ns.email_expediteur,
                smtp_password=smtp_password,
                sender=ns.email_expediteur,
                recipient=ns.email_validation_1,
                subject=f"🗂️ Groupe de réquisitions à valider - {dossier.reference}",
                title="Avis technique requis",
                body_lines=[
                    "Chers Membres du Bureau,",
                    "Un groupe de réquisitions a été créé et attend votre avis technique.",
                    f"Groupe : {dossier.reference}",
                    f"Nombre : {len(requisition_nums)}",
                    f"Total : {total_amount:,.2f} $",
                    "Réquisitions :",
                    *[f"- {num}" for num in requisition_nums],
                ],
            )

        if ns.email_president:
            background_tasks.add_task(
                send_dossier_notification,
                smtp_host=ns.smtp_host or "smtp.gmail.com",
                smtp_port=int(ns.smtp_port or 465),
                smtp_user=ns.email_expediteur,
                smtp_password=smtp_password,
                sender=ns.email_expediteur,
                president_email=ns.email_president,
                cc_emails=ns.emails_bureau_cc,
                dossier_reference=dossier.reference,
                requisition_nums=requisition_nums,
                montant_total=total_amount,
                created_by=created_by_name,
                attachment_paths=attachment_paths,
            )
    except Exception:
        logger.exception("Failed to schedule dossier notifications for %s", dossier.reference)


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
        status="BROUILLON",
        created_by=user.id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(dossier)
    await db.flush()

    for req in requisitions:
        req.dossier_id = dossier.id
        req.examen_status = "NON_EXAMINE"
        req.updated_at = _utcnow()

    await db.commit()
    await db.refresh(dossier)
    return _dossier_out(dossier, requisitions)


@router.get("/drafts", response_model=list[DossierRequisitionOut])
async def list_draft_dossiers(
    order: str | None = Query(default="created_at.desc"),
    limit: int | None = Query(default=200),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DossierRequisitionOut]:
    query = select(DossierRequisition).where(DossierRequisition.status == "BROUILLON")
    if (user.role or "").lower() != "admin":
        query = query.where(DossierRequisition.created_by == user.id)
    if order and order.endswith(".asc"):
        query = query.order_by(DossierRequisition.created_at.asc())
    else:
        query = query.order_by(DossierRequisition.created_at.desc())
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    res = await db.execute(query)
    dossiers = res.scalars().all()
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


@router.post("/{dossier_id}/submit-examen", response_model=DossierRequisitionOut)
async def submit_examen_dossier(
    dossier_id: str,
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

    if (dossier.status or "").upper() == "EN_EXAMEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier déjà soumis à l'examen")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    if not requisitions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier sans réquisitions")

    dossier.status = "EN_EXAMEN"
    dossier.updated_at = _utcnow()

    for req in requisitions:
        req.status = "EN_ATTENTE_COMMISSION" if req.service_id is not None else "EN_ATTENTE"
        req.examen_status = "EN_EXAMEN"
        req.examen_commentaire = None
        req.examen_par = None
        req.examen_le = None
        req.updated_at = _utcnow()

    await db.commit()
    await db.refresh(dossier)
    return _dossier_out(dossier, requisitions)


@router.post("/{dossier_id}/add-requisitions", response_model=DossierRequisitionOut)
async def add_requisitions_to_dossier(
    dossier_id: str,
    payload: DossierRequisitionAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("requisitions")),
) -> DossierRequisitionOut:
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        try:
            ids.append(uuid.UUID(rid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(select(Requisition).where(Requisition.id.in_(ids), Requisition.is_deleted.is_(False)))
    requisitions = req_res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")

    for req in requisitions:
        if req.dossier_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Réquisition déjà rattachée à un dossier: {req.numero_requisition}",
            )

    for req in requisitions:
        req.dossier_id = dossier.id
        req.examen_status = "NON_EXAMINE"
        req.updated_at = _utcnow()

    dossier.updated_at = _utcnow()
    await db.commit()
    await db.refresh(dossier)

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    dossier_reqs = req_res.scalars().all()
    return _dossier_out(dossier, dossier_reqs)


@router.post("/{dossier_id}/remove-requisitions", response_model=DossierRequisitionOut)
async def remove_requisitions_from_dossier(
    dossier_id: str,
    payload: DossierRequisitionRemove,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("requisitions")),
) -> DossierRequisitionOut:
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        try:
            ids.append(uuid.UUID(rid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id.in_(ids), Requisition.dossier_id == did)
    )
    requisitions = req_res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable dans ce dossier")

    for req in requisitions:
        req.dossier_id = None
        req.examen_status = "NON_EXAMINE"
        req.examen_commentaire = None
        req.examen_par = None
        req.examen_le = None
        req.status = "BROUILLON"
        req.updated_at = _utcnow()

    dossier.updated_at = _utcnow()
    await db.flush()

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    dossier_reqs = req_res.scalars().all()
    if len(dossier_reqs) == 1:
        lone = dossier_reqs[0]
        lone.dossier_id = None
        lone.status = "BROUILLON"
        lone.examen_status = "NON_EXAMINE"
        lone.examen_commentaire = None
        lone.examen_par = None
        lone.examen_le = None
        lone.updated_at = _utcnow()
        dossier_reqs = []

    await db.commit()
    await db.refresh(dossier)
    return _dossier_out(dossier, dossier_reqs)


@router.delete("/{dossier_id}", response_model=dict)
async def delete_dossier_requisition(
    dossier_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("requisitions")),
) -> dict:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == did))
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    for req in requisitions:
        req.dossier_id = None
        req.examen_status = "NON_EXAMINE"
        req.examen_commentaire = None
        req.examen_par = None
        req.examen_le = None
        req.updated_at = _utcnow()

    await db.delete(dossier)
    await db.commit()
    return {"ok": True}


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

    if len(requisitions) == 1:
        lone = requisitions[0]
        lone.dossier_id = None
        lone.examen_status = "EXAMINE"
        lone.examen_commentaire = payload.commentaires_examen
        lone.examen_par = user.id
        lone.examen_le = _utcnow()
        lone.updated_at = _utcnow()
        dossier.status = "BROUILLON"
        dossier.updated_at = _utcnow()
        await db.commit()
        await db.refresh(dossier)
        await _schedule_bureau_notifications(db=db, background_tasks=background_tasks, req=lone, action_user=user)
        return _dossier_out(dossier, [])

    dossier.status = "TRAITEMENT"
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

    await _schedule_dossier_notifications(
        db=db,
        background_tasks=background_tasks,
        dossier=dossier,
        requisitions=requisitions,
        action_user=user,
    )

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
