from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_tenant_uuid, get_current_user, has_any_permission
from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.remboursement_transport import ParticipantTransport, RemboursementTransport
from app.models.service import Service
from app.models.user import User
from app.schemas.remboursement_transport import (
    ParticipantTransportCreate,
    ParticipantTransportResponse,
    RemboursementTransportCreate,
    RemboursementTransportResponse,
)
from app.services.document_sequences import generate_document_number
from app.services.service_access import get_user_service_ids, can_view_all_services
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT


def _coerce_uuid(value: uuid.UUID | str | None, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field_name}")


def _tenant_remboursement_dir(tenant_uuid: str, year: int, month: int) -> str:
    return os.path.join(
        UPLOAD_ROOT,
        "tenants",
        str(tenant_uuid),
        "remboursements-transport",
        f"{year:04d}",
        f"{month:02d}",
    )


def _safe_ref(value: str) -> str:
    if not value:
        return "REM"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return safe.strip("._-") or "REM"


def _remboursement_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    legacy_dir = os.path.abspath(os.path.join(UPLOAD_ROOT, "remboursements-transport"))
    return os.path.abspath(os.path.join(legacy_dir, os.path.basename(file_path)))


def _user_info(user: User | None) -> dict[str, str | None] | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "prenom": user.prenom,
        "nom": user.nom,
        "email": user.email,
    }


def _annexe_payload(annexe: RequisitionAnnexe) -> dict[str, Any]:
    return {
        "id": str(annexe.id),
        "requisition_id": str(annexe.requisition_id),
        "file_path": annexe.file_path,
        "filename": annexe.filename,
        "file_type": annexe.file_type,
        "file_size": annexe.file_size,
        "upload_date": annexe.upload_date,
    }


def _requisition_payload(req: Requisition, users_map: dict[uuid.UUID, User], annexe: RequisitionAnnexe | None = None) -> dict[str, object]:
    return {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "reference_numero": req.reference_numero,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": req.montant_total or 0,
        "service_id": req.service_id,
        "status": req.status,
        "statut": req.status,
        "dossier_id": str(req.dossier_id) if req.dossier_id else None,
        "examen_status": req.examen_status,
        "examen_commentaire": req.examen_commentaire,
        "examen_par": str(req.examen_par) if req.examen_par else None,
        "examen_le": req.examen_le,
        "created_by": str(req.created_by) if req.created_by else None,
        "validee_par": str(req.validee_par) if req.validee_par else None,
        "validee_le": req.validee_le,
        "approuvee_par": str(req.approuvee_par) if req.approuvee_par else None,
        "approuvee_le": req.approuvee_le,
        "signed_by_id": str(req.signed_by_id) if req.signed_by_id else None,
        "signed_at": req.signed_at,
        "payee_par": str(req.payee_par) if req.payee_par else None,
        "payee_le": req.payee_le,
        "motif_rejet": req.motif_rejet,
        "a_valoir": req.a_valoir,
        "instance_beneficiaire": req.instance_beneficiaire,
        "notes_a_valoir": req.notes_a_valoir,
        "req_titre_officiel_hist": req.req_titre_officiel_hist,
        "req_label_gauche_hist": req.req_label_gauche_hist,
        "req_nom_gauche_hist": req.req_nom_gauche_hist,
        "req_label_droite_hist": req.req_label_droite_hist,
        "req_nom_droite_hist": req.req_nom_droite_hist,
        "signataire_g_label": req.signataire_g_label,
        "signataire_g_nom": req.signataire_g_nom,
        "signataire_d_label": req.signataire_d_label,
        "signataire_d_nom": req.signataire_d_nom,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "demandeur": _user_info(users_map.get(req.created_by)) if req.created_by else None,
        "validateur": _user_info(users_map.get(req.validee_par)) if req.validee_par else None,
        "approbateur": _user_info(users_map.get(req.approuvee_par)) if req.approuvee_par else None,
        "caissier": _user_info(users_map.get(req.payee_par)) if req.payee_par else None,
        "annexe": _annexe_payload(annexe) if annexe else None,
    }


@router.get("", response_model=list[RemboursementTransportResponse])
async def list_remboursements_transport(
    include: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(
        has_any_permission(
            [
                "remboursement_transport",
                "menu_services",
                "menu_validation_examens",
                "can_verify_technical",
                "can_validate_final",
            ]
        )
    ),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RemboursementTransportResponse]:
    query = (
        select(RemboursementTransport)
        .join(Requisition, Requisition.id == RemboursementTransport.requisition_id)
        .where(
            RemboursementTransport.organisation_id == tenant_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
        .order_by(RemboursementTransport.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if requisition_id:
        try:
            rid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        query = query.where(RemboursementTransport.requisition_id == rid)
    if not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")
        query = query.where(Requisition.service_id.in_(service_ids))

    res = await db.execute(query)
    remboursements = res.scalars().all()

    include_parts = {p.strip() for p in include.split(",")} if include else set()
    participants_map: dict[str, list[ParticipantTransportResponse]] = {}
    if "participants" in include_parts:
        ids = [r.id for r in remboursements]
        if ids:
            p_res = await db.execute(select(ParticipantTransport).where(ParticipantTransport.remboursement_id.in_(ids)))
            participants = p_res.scalars().all()
            for p in participants:
                participants_map.setdefault(str(p.remboursement_id), []).append(
                    ParticipantTransportResponse(
                        id=str(p.id),
                        remboursement_id=str(p.remboursement_id),
                        nom=p.nom,
                        titre_fonction=p.titre_fonction,
                        montant=p.montant,
                        type_participant=p.type_participant,
                        expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
                        created_at=p.created_at,
                    )
                )

    requisitions_map: dict[uuid.UUID, Requisition] = {}
    services_map: dict[int, Service] = {}
    users_map: dict[uuid.UUID, User] = {}
    req_ids = [r.requisition_id for r in remboursements if r.requisition_id]
    if req_ids:
        req_res = await db.execute(select(Requisition).where(Requisition.id.in_(req_ids)))
        requisitions = req_res.scalars().all()
        requisitions_map = {r.id: r for r in requisitions}

        service_ids = {r.service_id for r in requisitions if r.service_id is not None}
        if service_ids:
            services_res = await db.execute(select(Service).where(Service.id.in_(service_ids)))
            services_map = {s.id: s for s in services_res.scalars().all()}

        if "requisition" in include_parts:
            user_ids: set[uuid.UUID] = set()
            for r in requisitions:
                if r.created_by:
                    user_ids.add(r.created_by)
                if r.validee_par:
                    user_ids.add(r.validee_par)
                if r.approuvee_par:
                    user_ids.add(r.approuvee_par)
                if r.payee_par:
                    user_ids.add(r.payee_par)
            if user_ids:
                users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
                users_map = {u.id: u for u in users_res.scalars().all()}

            annexes_map: dict[uuid.UUID, RequisitionAnnexe] = {}
            ann_res = await db.execute(
                select(RequisitionAnnexe)
                .where(RequisitionAnnexe.requisition_id.in_(req_ids))
                .order_by(RequisitionAnnexe.requisition_id, RequisitionAnnexe.upload_date.desc())
            )
            for ann in ann_res.scalars().all():
                if ann.requisition_id not in annexes_map:
                    annexes_map[ann.requisition_id] = ann

    responses: list[RemboursementTransportResponse] = []
    for r in remboursements:
        requisition_payload = None
        service = None
        req = requisitions_map.get(r.requisition_id) if r.requisition_id else None
        if req and req.service_id is not None:
            service = services_map.get(req.service_id)
        if "requisition" in include_parts and r.requisition_id:
            if req:
                requisition_payload = _requisition_payload(req, users_map, annexes_map.get(req.id))
        responses.append(
            RemboursementTransportResponse(
                id=str(r.id),
                numero_remboursement=r.numero_remboursement,
                reference_numero=r.reference_numero,
                pdf_path=r.pdf_path,
                instance=r.instance,
                type_reunion=r.type_reunion,
                nature_reunion=r.nature_reunion,
                nature_travail=r.nature_travail or [],
                lieu=r.lieu,
                date_reunion=r.date_reunion,
                heure_debut=r.heure_debut,
                heure_fin=r.heure_fin,
                montant_total=r.montant_total or Decimal(0),
                requisition_id=str(r.requisition_id) if r.requisition_id else None,
                service_id=req.service_id if req else None,
                service_code=service.code if service else None,
                service_libelle=service.libelle if service else None,
                created_at=r.created_at,
                created_by=str(r.created_by) if r.created_by else None,
                trans_titre_officiel_hist=r.trans_titre_officiel_hist,
                trans_label_gauche_hist=r.trans_label_gauche_hist,
                trans_nom_gauche_hist=r.trans_nom_gauche_hist,
                trans_label_droite_hist=r.trans_label_droite_hist,
                trans_nom_droite_hist=r.trans_nom_droite_hist,
                signataire_g_label=r.signataire_g_label,
                signataire_g_nom=r.signataire_g_nom,
                signataire_d_label=r.signataire_d_label,
                signataire_d_nom=r.signataire_d_nom,
                participants=participants_map.get(str(r.id)),
                requisition=requisition_payload,
            )
        )

    return responses


@router.post("", response_model=RemboursementTransportResponse, status_code=status.HTTP_201_CREATED)
async def create_remboursement_transport(
    payload: RemboursementTransportCreate,
    user: User = Depends(has_any_permission(["remboursement_transport", "menu_services"])),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RemboursementTransportResponse:
    requisition_id = None
    if payload.requisition_id:
        if isinstance(payload.requisition_id, uuid.UUID):
            requisition_id = payload.requisition_id
        else:
            try:
                requisition_id = uuid.UUID(payload.requisition_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    created_by = None
    if payload.created_by:
        if isinstance(payload.created_by, uuid.UUID):
            created_by = payload.created_by
        else:
            try:
                created_by = uuid.UUID(payload.created_by)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")

    service_id = None
    service = None
    requisition = None
    if requisition_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.id == requisition_id,
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
        requisition = req_res.scalar_one_or_none()
        if requisition is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
        service_id = requisition.service_id
        if service_id is not None:
            service_res = await db.execute(
                select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
            )
            service = service_res.scalar_one_or_none()

    numero_remboursement = await generate_document_number(db, "REM", tenant_id, service_id=service_id)
    r = RemboursementTransport(
        organisation_id=tenant_id,
        numero_remboursement=numero_remboursement,
        reference_numero=numero_remboursement,
        instance=payload.instance,
        type_reunion=payload.type_reunion,
        nature_reunion=payload.nature_reunion,
        nature_travail=payload.nature_travail,
        lieu=payload.lieu,
        date_reunion=payload.date_reunion,
        heure_debut=payload.heure_debut,
        heure_fin=payload.heure_fin,
        montant_total=payload.montant_total or Decimal(0),
        requisition_id=requisition_id,
        created_by=created_by or user.id,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    return RemboursementTransportResponse(
        id=str(r.id),
        numero_remboursement=r.numero_remboursement,
        instance=r.instance,
        type_reunion=r.type_reunion,
        nature_reunion=r.nature_reunion,
        nature_travail=r.nature_travail or [],
        lieu=r.lieu,
        date_reunion=r.date_reunion,
        heure_debut=r.heure_debut,
        heure_fin=r.heure_fin,
        montant_total=r.montant_total or Decimal(0),
        requisition_id=str(r.requisition_id) if r.requisition_id else None,
        service_id=service_id,
        service_code=service.code if service else None,
        service_libelle=service.libelle if service else None,
        created_at=r.created_at,
        created_by=str(r.created_by) if r.created_by else None,
        reference_numero=r.reference_numero,
        pdf_path=r.pdf_path,
        trans_titre_officiel_hist=r.trans_titre_officiel_hist,
        trans_label_gauche_hist=r.trans_label_gauche_hist,
        trans_nom_gauche_hist=r.trans_nom_gauche_hist,
        trans_label_droite_hist=r.trans_label_droite_hist,
        trans_nom_droite_hist=r.trans_nom_droite_hist,
        signataire_g_label=r.signataire_g_label,
        signataire_g_nom=r.signataire_g_nom,
        signataire_d_label=r.signataire_d_label,
        signataire_d_nom=r.signataire_d_nom,
        participants=None,
    )


@router.post("/{remboursement_id}/pdf")
async def upload_remboursement_pdf(
    remboursement_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(remboursement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid remboursement_id")

    res = await db.execute(
        select(RemboursementTransport)
        .where(
            RemboursementTransport.id == rid,
            RemboursementTransport.organisation_id == tenant_id,
        )
    )
    remboursement = res.scalar_one_or_none()
    if remboursement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remboursement not found")

    content_type = (file.content_type or "").lower()
    if content_type not in PDF_ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")

    original_name = file.filename or "remboursement.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in PDF_ALLOWED_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide")

    ref_base = remboursement.reference_numero or remboursement.numero_remboursement or f"REM-{rid}"
    safe_ref = _safe_ref(ref_base)
    filename = f"{safe_ref}.pdf"
    upload_dt = datetime.now(timezone.utc)
    target_dir = _tenant_remboursement_dir(tenant_uuid, upload_dt.year, upload_dt.month)
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as handle:
        handle.write(contents)

    remboursement.pdf_path = (
        f"/uploads/tenants/{tenant_uuid}/remboursements-transport/"
        f"{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
    )
    await db.commit()

    return {"ok": True, "pdf_path": remboursement.pdf_path}


@router.get("/{remboursement_id}/pdf")
async def download_remboursement_pdf(
    remboursement_id: str,
    user: User = Depends(
        has_any_permission(
            [
                "remboursement_transport",
                "menu_services",
                "menu_validation_examens",
                "can_verify_technical",
                "can_validate_final",
            ]
        )
    ),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        rid = uuid.UUID(remboursement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid remboursement_id")

    res = await db.execute(
        select(RemboursementTransport, Requisition)
        .join(Requisition, Requisition.id == RemboursementTransport.requisition_id, isouter=True)
        .where(RemboursementTransport.id == rid, RemboursementTransport.organisation_id == tenant_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remboursement introuvable")

    remboursement, requisition = row

    if not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")
        requisition_service_id = getattr(requisition, "service_id", None)
        if requisition_service_id is not None and requisition_service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")

    fs_path = _remboursement_pdf_fs_path(remboursement.pdf_path)
    if not fs_path or not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF introuvable")

    filename = os.path.basename(fs_path)
    return FileResponse(
        fs_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/participants", response_model=list[ParticipantTransportResponse])
async def list_participants_transport(
    remboursement_id: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantTransportResponse]:
    query = (
        select(ParticipantTransport)
        .where(ParticipantTransport.organisation_id == tenant_id)
        .offset(offset)
        .limit(limit)
    )
    if remboursement_id:
        try:
            rid = uuid.UUID(remboursement_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid remboursement_id")
        query = query.where(ParticipantTransport.remboursement_id == rid)

    res = await db.execute(query)
    participants = res.scalars().all()
    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            created_at=p.created_at,
        )
        for p in participants
    ]


@router.post("/participants", response_model=list[ParticipantTransportResponse])
async def create_participants_transport(
    payload: list[ParticipantTransportCreate],
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantTransportResponse]:
    created: list[ParticipantTransport] = []
    logger.info("Payload participants transport: %s", [item.model_dump(mode="json") for item in payload])
    for item in payload:
        rid = _coerce_uuid(item.remboursement_id, "remboursement_id")
        remb_res = await db.execute(
            select(RemboursementTransport).where(
                RemboursementTransport.id == rid,
                RemboursementTransport.organisation_id == tenant_id,
            )
        )
        remboursement = remb_res.scalar_one_or_none()
        if remboursement is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remboursement introuvable")

        expert_id = None
        if item.expert_comptable_id:
            expert_id = _coerce_uuid(item.expert_comptable_id, "expert_comptable_id")

        logger.info(
            "participant transport remboursement_id=%s expert_comptable_id=%s",
            rid,
            expert_id,
        )

        p = ParticipantTransport(
            organisation_id=tenant_id,
            remboursement_id=rid,
            nom=item.nom,
            titre_fonction=item.titre_fonction,
            montant=item.montant or Decimal(0),
            type_participant=item.type_participant,
            expert_comptable_id=expert_id,
        )
        db.add(p)
        created.append(p)

    await db.commit()
    for p in created:
        await db.refresh(p)

    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            created_at=p.created_at,
        )
        for p in created
    ]
