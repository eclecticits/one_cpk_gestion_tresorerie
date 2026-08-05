from __future__ import annotations

import uuid
from datetime import datetime, timezone
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, get_db, has_permission
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
from app.services.email_config import resolve_smtp_config
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.services.document_sequences import generate_document_number
from app.services.service_access import can_view_all_services, get_user_service_ids


router = APIRouter()
logger = logging.getLogger("onec_cpk_api.dossiers_requisition")

DOSSIER_WORKFLOW_PERMISSIONS = {"requisitions", "can_create_requisition", "menu_requisitions"}
DOSSIER_EXAMEN_PERMISSIONS = {"can_verify_technical", "can_validate_final", "menu_validation_examens"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_requisition_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")


def _dossier_out(
    dossier: DossierRequisition,
    requisitions: list[Requisition],
    *,
    users_map: dict[uuid.UUID, User] | None = None,
    include_parts: set[str] | None = None,
    annexes_map: dict[uuid.UUID, RequisitionAnnexe] | None = None,
) -> DossierRequisitionOut:
    return DossierRequisitionOut(
        id=str(dossier.id),
        reference=dossier.reference,
        description=dossier.description,
        status=dossier.status,
        commentaires_examen=dossier.commentaires_examen,
        created_by=str(dossier.created_by) if dossier.created_by else None,
        created_at=dossier.created_at,
        updated_at=dossier.updated_at,
        requisitions=[
            _requisition_out(
                r,
                demandeur=users_map.get(r.created_by) if users_map and include_parts and "demandeur" in include_parts else None,
                validateur=users_map.get(r.validee_par) if users_map and include_parts and "validateur" in include_parts else None,
                approbateur=users_map.get(r.approuvee_par) if users_map and include_parts and "approbateur" in include_parts else None,
                examinateur=users_map.get(r.examen_par) if users_map and include_parts and "examinateur" in include_parts else None,
                annexe=annexes_map.get(r.id) if annexes_map else None,
            )
            for r in requisitions
        ],
    )


async def _load_annexes_map(
    db: AsyncSession,
    requisitions: list[Requisition],
) -> dict[uuid.UUID, RequisitionAnnexe]:
    if not requisitions:
        return {}

    requisition_ids = [req.id for req in requisitions]
    res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id.in_(requisition_ids))
        .order_by(RequisitionAnnexe.requisition_id, RequisitionAnnexe.upload_date.desc())
    )
    annexes_map: dict[uuid.UUID, RequisitionAnnexe] = {}
    for annexe in res.scalars().all():
        if annexe.requisition_id not in annexes_map:
            annexes_map[annexe.requisition_id] = annexe
    return annexes_map


async def _build_dossier_out(
    db: AsyncSession,
    dossier: DossierRequisition,
    requisitions: list[Requisition],
    *,
    users_map: dict[uuid.UUID, User] | None = None,
    include_parts: set[str] | None = None,
) -> DossierRequisitionOut:
    annexes_map = await _load_annexes_map(db, requisitions)
    return _dossier_out(
        dossier,
        requisitions,
        users_map=users_map,
        include_parts=include_parts,
        annexes_map=annexes_map,
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
        settings_res = await db.execute(
            select(SystemSettings)
            .where(SystemSettings.organisation_id == action_user.organisation_id)
            .limit(1)
        )
        ns = settings_res.scalar_one_or_none()
        smtp_cfg = resolve_smtp_config(ns)
        if smtp_cfg is None:
            return

        created_by_name = " ".join(filter(None, [action_user.prenom, action_user.nom])) or action_user.email or "Systeme"
        org_res = await db.execute(
            select(Organisation.nom).where(Organisation.id == action_user.organisation_id).limit(1)
        )
        org_name = org_res.scalar_one_or_none()

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
                smtp_host=smtp_cfg.host,
                smtp_port=smtp_cfg.port,
                smtp_user=smtp_cfg.user,
                smtp_password=smtp_cfg.password,
                sender=smtp_cfg.sender,
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
                brand_name="ONEC",
                organisation_name=org_name,
                attachment_paths=attachment_paths,
            )

        if ns.email_president:
            background_tasks.add_task(
                send_dossier_notification,
                smtp_host=smtp_cfg.host,
                smtp_port=smtp_cfg.port,
                smtp_user=smtp_cfg.user,
                smtp_password=smtp_cfg.password,
                sender=smtp_cfg.sender,
                president_email=ns.email_president,
                cc_emails=ns.emails_bureau_cc,
                dossier_reference=dossier.reference,
                requisition_nums=requisition_nums,
                montant_total=total_amount,
                created_by=created_by_name,
                attachment_paths=attachment_paths,
                brand_name="ONEC",
                organisation_name=org_name,
            )
    except Exception:
        logger.exception("Failed to schedule dossier notifications for %s", dossier.reference)


def _is_admin_user(user: User) -> bool:
    return (user.role or "").lower() in {"admin", "super_admin"}


def _ensure_dossier_examen_action_allowed(
    dossier: DossierRequisition,
    requisitions: list[Requisition],
) -> None:
    if (dossier.status or "").upper() != "EN_EXAMEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le dossier doit être en examen",
        )
    if not requisitions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier sans réquisitions")
    invalid_requisitions = [
        req.numero_requisition or str(req.id)
        for req in requisitions
        if (req.examen_status or "").upper() != "EN_EXAMEN"
    ]
    if invalid_requisitions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Toutes les réquisitions du dossier doivent être en examen",
        )


async def _get_user_permission_codes(user: User, db: AsyncSession) -> set[str]:
    if _is_admin_user(user):
        return {"*"}
    if not user.role_id:
        return set()
    perm_query = (
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
    )
    res = await db.execute(perm_query)
    return {row[0] for row in res.all()}


async def _get_dossier_access_context(user: User, db: AsyncSession) -> tuple[set[str], set[int], bool]:
    perm_codes = await _get_user_permission_codes(user, db)
    service_ids = set(await get_user_service_ids(db, user))
    all_services = _is_admin_user(user) or await can_view_all_services(db, user)
    return perm_codes, service_ids, all_services


async def _ensure_validation_access(user: User, db: AsyncSession) -> None:
    if _is_admin_user(user):
        return
    perm_codes = await _get_user_permission_codes(user, db)
    if perm_codes.intersection({"can_verify_technical", "can_validate_final"}):
        return
    role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
    role_code = (role_res.scalar_one_or_none() or "").lower()
    if role_code == "admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Privilèges insuffisants")


async def _ensure_dossier_page_access(user: User, db: AsyncSession) -> None:
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if all_services or perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS | DOSSIER_EXAMEN_PERMISSIONS):
        return
    if service_ids:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Privilèges insuffisants")


async def _ensure_dossier_workflow_access(user: User, db: AsyncSession) -> None:
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if all_services or perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS):
        return
    if service_ids:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions requises")


async def _ensure_requisition_scope(user: User, db: AsyncSession, requisitions: list[Requisition]) -> None:
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if all_services or perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS | DOSSIER_EXAMEN_PERMISSIONS):
        return
    if not service_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Privilèges insuffisants")
    inaccessible = [
        req.numero_requisition or str(req.id)
        for req in requisitions
        if req.service_id is None or req.service_id not in service_ids
    ]
    if inaccessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce dossier contient des réquisitions hors de vos commissions",
        )


async def _ensure_dossier_scope(
    user: User,
    db: AsyncSession,
    dossier: DossierRequisition,
    requisitions: list[Requisition],
    *,
    require_all_requisitions: bool = False,
) -> None:
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if all_services or perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS | DOSSIER_EXAMEN_PERMISSIONS):
        return
    if dossier.created_by == user.id and not requisitions:
        return
    if not service_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Privilèges insuffisants")
    matching = [req for req in requisitions if req.service_id in service_ids]
    if require_all_requisitions:
        if requisitions and len(matching) == len(requisitions):
            return
    elif matching:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dossier hors de vos commissions")


async def _filter_dossiers_for_user(
    db: AsyncSession,
    user: User,
    dossiers: list[DossierRequisition],
) -> list[DossierRequisition]:
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if all_services or perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS | DOSSIER_EXAMEN_PERMISSIONS):
        return dossiers
    if not service_ids:
        return []

    dossier_ids = [d.id for d in dossiers]
    allowed_ids = {d.id for d in dossiers if d.created_by == user.id}
    if dossier_ids:
        req_res = await db.execute(select(Requisition).where(Requisition.dossier_id.in_(dossier_ids)))
        for req in req_res.scalars().all():
            if req.service_id in service_ids and req.dossier_id:
                allowed_ids.add(req.dossier_id)

    return [d for d in dossiers if d.id in allowed_ids]


@router.post("", response_model=DossierRequisitionOut)
async def create_dossier_requisition(
    payload: DossierRequisitionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    await _ensure_dossier_workflow_access(user, db)
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        ids.append(_coerce_requisition_uuid(rid))

    res = await db.execute(
        select(Requisition).where(
            Requisition.id.in_(ids),
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    requisitions = res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
    await _ensure_requisition_scope(user, db, requisitions)
    for req in requisitions:
        if req.dossier_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Réquisition déjà rattachée à un dossier: {req.numero_requisition}",
            )

    reference = await generate_document_number(db, "DG", tenant_id)
    dossier = DossierRequisition(
        organisation_id=tenant_id,
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
    return await _build_dossier_out(db, dossier, requisitions)


@router.get("/drafts", response_model=list[DossierRequisitionOut])
async def list_draft_dossiers(
    order: str | None = Query(default="created_at.desc"),
    limit: int | None = Query(default=200),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[DossierRequisitionOut]:
    await _ensure_dossier_workflow_access(user, db)
    query = select(DossierRequisition).where(
        DossierRequisition.organisation_id == tenant_id,
        DossierRequisition.status == "BROUILLON",
    )
    perm_codes, service_ids, all_services = await _get_dossier_access_context(user, db)
    if not all_services and not perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS) and not service_ids:
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
    if service_ids and not all_services and not perm_codes.intersection(DOSSIER_WORKFLOW_PERMISSIONS):
        dossiers = await _filter_dossiers_for_user(db, user, dossiers)
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
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    await _ensure_dossier_workflow_access(user, db)
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    if (dossier.status or "").upper() == "EN_EXAMEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier déjà soumis à l'examen")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    if not requisitions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dossier sans réquisitions")
    await _ensure_dossier_scope(user, db, dossier, requisitions, require_all_requisitions=True)

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

    # Schedule notification
    try:
        await _schedule_dossier_notifications(
            db=db,
            background_tasks=background_tasks,
            dossier=dossier,
            requisitions=requisitions,
            action_user=user
        )
    except Exception:
        logger.exception("Failed to schedule notifications for dossier exam submission")

    return await _build_dossier_out(db, dossier, requisitions)


@router.post("/{dossier_id}/add-requisitions", response_model=DossierRequisitionOut)
async def add_requisitions_to_dossier(
    dossier_id: str,
    payload: DossierRequisitionAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    await _ensure_dossier_workflow_access(user, db)
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")
    existing_req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    existing_requisitions = existing_req_res.scalars().all()
    await _ensure_dossier_scope(user, db, dossier, existing_requisitions, require_all_requisitions=True)

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        ids.append(_coerce_requisition_uuid(rid))

    req_res = await db.execute(
        select(Requisition).where(
            Requisition.id.in_(ids),
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    requisitions = req_res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
    await _ensure_requisition_scope(user, db, requisitions)

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
    return await _build_dossier_out(db, dossier, dossier_reqs)


@router.post("/{dossier_id}/remove-requisitions", response_model=DossierRequisitionOut)
async def remove_requisitions_from_dossier(
    dossier_id: str,
    payload: DossierRequisitionRemove,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    await _ensure_dossier_workflow_access(user, db)
    if not payload.requisition_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune réquisition sélectionnée")

    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")

    ids: list[uuid.UUID] = []
    for rid in payload.requisition_ids:
        ids.append(_coerce_requisition_uuid(rid))

    req_res = await db.execute(
        select(Requisition).where(Requisition.id.in_(ids), Requisition.dossier_id == did)
    )
    requisitions = req_res.scalars().all()
    if len(requisitions) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable dans ce dossier")
    await _ensure_dossier_scope(user, db, dossier, requisitions, require_all_requisitions=True)

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
    return await _build_dossier_out(db, dossier, dossier_reqs)


@router.delete("/{dossier_id}", response_model=dict)
async def delete_dossier_requisition(
    dossier_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    await _ensure_dossier_workflow_access(user, db)
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    if (dossier.status or "").upper() != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le dossier doit être en brouillon")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    await _ensure_dossier_scope(user, db, dossier, requisitions, require_all_requisitions=True)
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    await _ensure_dossier_scope(user, db, dossier, requisitions)
    return await _build_dossier_out(db, dossier, requisitions)


@router.get("", response_model=list[DossierRequisitionOut])
async def list_dossiers_requisition(
    status: str | None = Query(default=None),
    include_requisitions: bool = Query(default=False),
    include_users: str | None = Query(default=None),
    order: str | None = Query(default="created_at.desc"),
    limit: int | None = Query(default=100),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[DossierRequisitionOut]:
    await _ensure_dossier_page_access(user, db)
    query = select(DossierRequisition).where(DossierRequisition.organisation_id == tenant_id)
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
    dossiers = await _filter_dossiers_for_user(db, user, dossiers)
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

    include_parts = {p.strip() for p in include_users.split(",")} if include_users else set()
    users_map: dict[uuid.UUID, User] | None = None
    if include_parts:
        user_ids: set[uuid.UUID] = set()
        for reqs in req_map.values():
            for req in reqs:
                if "demandeur" in include_parts and req.created_by:
                    user_ids.add(req.created_by)
                if "validateur" in include_parts and req.validee_par:
                    user_ids.add(req.validee_par)
                if "approbateur" in include_parts and req.approuvee_par:
                    user_ids.add(req.approuvee_par)
                if "examinateur" in include_parts and req.examen_par:
                    user_ids.add(req.examen_par)
        if user_ids:
            users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
            users_map = {u.id: u for u in users_res.scalars().all()}
        else:
            users_map = {}

    return [
        await _build_dossier_out(db, d, req_map.get(d.id, []), users_map=users_map, include_parts=include_parts)
        for d in dossiers
    ]


@router.patch("/{dossier_id}", response_model=DossierRequisitionOut)
async def update_dossier_requisition(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    await _ensure_dossier_workflow_access(user, db)
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
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
    await _ensure_dossier_scope(user, db, dossier, requisitions, require_all_requisitions=True)
    await db.commit()
    return await _build_dossier_out(db, dossier, requisitions)


@router.post("/{dossier_id}/validate-examen", response_model=DossierRequisitionOut)
async def validate_examen_dossier(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    _ensure_dossier_examen_action_allowed(dossier, requisitions)

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
        try:
            await _schedule_bureau_notifications(db=db, background_tasks=background_tasks, req=lone, action_user=user)
        except Exception as exc:
            logger.exception("Failed to prepare bureau notifications for requisition %s", lone.numero_requisition)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Impossible de preparer le PDF officiel pour l'envoi email: {exc}",
            ) from exc
        return await _build_dossier_out(db, dossier, [])

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

    return await _build_dossier_out(db, dossier, requisitions)


@router.post("/{dossier_id}/reject-examen", response_model=DossierRequisitionOut)
async def reject_examen_dossier(
    dossier_id: str,
    payload: DossierRequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> DossierRequisitionOut:
    try:
        did = uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")

    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.id == did,
            DossierRequisition.organisation_id == tenant_id,
        )
    )
    dossier = res.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    req_res = await db.execute(select(Requisition).where(Requisition.dossier_id == did))
    requisitions = req_res.scalars().all()
    _ensure_dossier_examen_action_allowed(dossier, requisitions)

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
    return await _build_dossier_out(db, dossier, requisitions)
