from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_tenant_uuid, get_current_user, has_any_permission
from app.db.session import get_db
from app.models.commission_member import CommissionMember
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.remboursement_transport import (
    ParticipantTransport,
    RemboursementTransport,
    RemboursementTransportBrouillon,
)
from app.models.service import Service
from app.models.user import User
from app.schemas.remboursement_transport import (
    ConvocationDestinataire,
    ConvocationEchec,
    ConvocationEnvoi,
    ConvocationResultat,
    PiecesReunionAnnexer,
    ParticipantTransportCreate,
    ParticipantTransportResponse,
    ParticipantsTransportOrdre,
    RemboursementTransportBrouillonResponse,
    RemboursementTransportBrouillonSave,
    RemboursementTransportCreate,
    RemboursementTransportResponse,
)
from app.schemas.requisition import RequisitionAnnexeOut
from app.services.convocation_reunion import envoyer_convocations, reunion_depuis_brouillon
from app.services.document_sequences import generate_document_number
from app.services.email_config import resolve_smtp_config
from app.services.mailer import send_in_thread
from app.services.official_pdf import ensure_remboursement_official_pdf
from app.services.service_access import get_user_service_ids, can_view_all_services
from app.services.system_settings_service import get_system_settings
from app.core.config import settings
from app.utils.hierarchie_fonctions import trier_participants
from app.utils.upload_validation import matches_declared_type, read_upload_limited

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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
    """Résout un chemin stocké sans jamais sortir du répertoire d'uploads."""
    if not isinstance(file_path, str) or not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        candidate = os.path.realpath(os.path.join(UPLOAD_ROOT, rel_path))
    else:
        legacy_dir = os.path.realpath(os.path.join(UPLOAD_ROOT, "remboursements-transport"))
        candidate = os.path.realpath(os.path.join(legacy_dir, os.path.basename(file_path)))
    root = os.path.realpath(UPLOAD_ROOT)
    try:
        if os.path.commonpath([root, candidate]) != root:
            return ""
    except ValueError:
        return ""
    return candidate


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
            participants = trier_participants(p_res.scalars().all())
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
                        ordre=p.ordre,
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
    await db.flush()
    await ensure_remboursement_official_pdf(db, r, regenerate=True)
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
    participants = trier_participants(res.scalars().all())
    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            ordre=p.ordre,
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
            ordre=item.ordre,
        )
        db.add(p)
        created.append(p)

    await db.commit()
    remboursement_ids = {p.remboursement_id for p in created}
    if remboursement_ids:
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.id.in_(list(remboursement_ids)))
        )
        for remboursement in remb_res.scalars().all():
            await ensure_remboursement_official_pdf(db, remboursement, regenerate=True)
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
            ordre=p.ordre,
            created_at=p.created_at,
        )
        for p in created
    ]


@router.put("/{remboursement_id}/participants/ordre", response_model=list[ParticipantTransportResponse])
async def reorder_participants_transport(
    remboursement_id: str,
    payload: ParticipantsTransportOrdre,
    user: User = Depends(has_any_permission(["remboursement_transport", "menu_services"])),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantTransportResponse]:
    """Fixe l'ordre d'impression des participants, puis régénère le PDF."""
    rid = _coerce_uuid(remboursement_id, "remboursement_id")
    remb_res = await db.execute(
        select(RemboursementTransport).where(
            RemboursementTransport.id == rid,
            RemboursementTransport.organisation_id == tenant_id,
        )
    )
    remboursement = remb_res.scalar_one_or_none()
    if remboursement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remboursement introuvable")

    p_res = await db.execute(select(ParticipantTransport).where(ParticipantTransport.remboursement_id == rid))
    par_id = {p.id: p for p in p_res.scalars().all()}
    if len(payload.participant_ids) != len(set(payload.participant_ids)) or set(payload.participant_ids) != set(par_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La liste doit reprendre chaque participant du remboursement, une seule fois.",
        )
    for rang, pid in enumerate(payload.participant_ids, start=1):
        par_id[pid].ordre = rang
    await db.commit()
    await ensure_remboursement_official_pdf(db, remboursement, regenerate=True)
    await db.commit()

    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            ordre=p.ordre,
            created_at=p.created_at,
        )
        for p in trier_participants(par_id.values())
    ]


# ----------------------------------------------------------------------
# Brouillons : un remboursement se prépare avant la réunion (liste de présence
# à imprimer), puis se complète après (présences, montants). Tant qu'il est
# brouillon, il n'a ni numéro REM ni réquisition.
# ----------------------------------------------------------------------

BROUILLON_PERMISSIONS = ["remboursement_transport", "menu_services"]
BROUILLON_SERVER_KEYS = frozenset({"convocation", "pieces"})


def _contenu_brouillon_client(contenu: dict, precedent: dict | None = None) -> dict:
    """Écarte les métadonnées que seuls les endpoints serveur peuvent écrire."""
    nettoye = {cle: valeur for cle, valeur in dict(contenu).items() if cle not in BROUILLON_SERVER_KEYS}
    for cle in BROUILLON_SERVER_KEYS:
        if cle in (precedent or {}):
            nettoye[cle] = precedent[cle]
    return nettoye


async def _ensure_service_access(db: AsyncSession, user: User, tenant_id: int, service_id: int) -> Service:
    service_res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
    service = service_res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service introuvable")
    if not await can_view_all_services(db, user):
        if service_id not in await get_user_service_ids(db, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce service ne vous est pas assigné.")
    return service


async def _get_brouillon(
    db: AsyncSession, user: User, tenant_id: int, brouillon_id: str
) -> RemboursementTransportBrouillon:
    bid = _coerce_uuid(brouillon_id, "brouillon_id")
    res = await db.execute(
        select(RemboursementTransportBrouillon).where(
            RemboursementTransportBrouillon.id == bid,
            RemboursementTransportBrouillon.organisation_id == tenant_id,
        )
    )
    brouillon = res.scalar_one_or_none()
    if brouillon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brouillon introuvable")
    await _ensure_service_access(db, user, tenant_id, brouillon.service_id)
    return brouillon


def _user_label(u: User | None) -> str | None:
    if u is None:
        return None
    return f"{u.prenom or ''} {u.nom or ''}".strip() or None


async def _brouillon_responses(
    db: AsyncSession, brouillons: list[RemboursementTransportBrouillon]
) -> list[RemboursementTransportBrouillonResponse]:
    service_ids = {b.service_id for b in brouillons}
    user_ids = {u for b in brouillons for u in (b.created_by, b.updated_by) if u}
    services_map: dict[int, Service] = {}
    users_map: dict[uuid.UUID, User] = {}
    if service_ids:
        res = await db.execute(select(Service).where(Service.id.in_(service_ids)))
        services_map = {s.id: s for s in res.scalars().all()}
    if user_ids:
        res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
        users_map = {u.id: u for u in res.scalars().all()}
    out = []
    for b in brouillons:
        service = services_map.get(b.service_id)
        out.append(
            RemboursementTransportBrouillonResponse(
                id=b.id,
                service_id=b.service_id,
                service_code=service.code if service else None,
                service_libelle=service.libelle if service else None,
                contenu=b.contenu or {},
                created_by=b.created_by,
                created_by_nom=_user_label(users_map.get(b.created_by)) if b.created_by else None,
                updated_by_nom=_user_label(users_map.get(b.updated_by)) if b.updated_by else None,
                created_at=b.created_at,
                updated_at=b.updated_at,
            )
        )
    return out


@router.get("/brouillons", response_model=list[RemboursementTransportBrouillonResponse])
async def list_brouillons(
    service_id: int | None = Query(default=None),
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RemboursementTransportBrouillonResponse]:
    query = (
        select(RemboursementTransportBrouillon)
        .where(RemboursementTransportBrouillon.organisation_id == tenant_id)
        .order_by(RemboursementTransportBrouillon.updated_at.desc())
        .limit(200)
    )
    if service_id is not None:
        query = query.where(RemboursementTransportBrouillon.service_id == service_id)
    if not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return []
        query = query.where(RemboursementTransportBrouillon.service_id.in_(service_ids))
    res = await db.execute(query)
    return await _brouillon_responses(db, list(res.scalars().all()))


@router.post(
    "/brouillons",
    response_model=RemboursementTransportBrouillonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_brouillon(
    payload: RemboursementTransportBrouillonSave,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RemboursementTransportBrouillonResponse:
    await _ensure_service_access(db, user, tenant_id, payload.service_id)
    brouillon = RemboursementTransportBrouillon(
        organisation_id=tenant_id,
        service_id=payload.service_id,
        contenu=_contenu_brouillon_client(payload.contenu),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(brouillon)
    await db.commit()
    await db.refresh(brouillon)
    return (await _brouillon_responses(db, [brouillon]))[0]


@router.put("/brouillons/{brouillon_id}", response_model=RemboursementTransportBrouillonResponse)
async def update_brouillon(
    brouillon_id: str,
    payload: RemboursementTransportBrouillonSave,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RemboursementTransportBrouillonResponse:
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    if payload.service_id != brouillon.service_id:
        await _ensure_service_access(db, user, tenant_id, payload.service_id)
        brouillon.service_id = payload.service_id
    # La convocation et les pièces sont écrites par le serveur. Le formulaire
    # ne peut ni les fabriquer ni les remplacer, mais ne les efface pas.
    brouillon.contenu = _contenu_brouillon_client(payload.contenu, brouillon.contenu or {})
    brouillon.updated_by = user.id
    brouillon.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(brouillon)
    return (await _brouillon_responses(db, [brouillon]))[0]


@router.delete("/brouillons/{brouillon_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_brouillon(
    brouillon_id: str,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    pieces_brutes = (brouillon.contenu or {}).get("pieces") or {}
    pieces = list(pieces_brutes.values()) if isinstance(pieces_brutes, dict) else []
    await db.delete(brouillon)
    await db.commit()
    # La base est la source de vérité : on ne détruit les fichiers qu'après
    # confirmation de la suppression du brouillon.
    for piece in pieces:
        _supprimer_fichier_piece(piece if isinstance(piece, dict) else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Convocation : la réunion en préparation est le brouillon. On convoque
# depuis lui, par e-mail avec une invitation agenda (.ics).
# ----------------------------------------------------------------------

def _nom_cle(nom: str | None) -> str:
    return " ".join(str(nom or "").lower().split())


def _personnes_brouillon(contenu: dict) -> list[dict]:
    participants = contenu.get("participants") or []
    assistants = contenu.get("assistants") or []
    personnes = [
        *(participants if isinstance(participants, list) else []),
        *(assistants if isinstance(assistants, list) else []),
    ]
    return [p for p in personnes if isinstance(p, dict) and str(p.get("nom") or "").strip()]


@router.get("/brouillons/{brouillon_id}/destinataires", response_model=list[ConvocationDestinataire])
async def list_destinataires_convocation(
    brouillon_id: str,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ConvocationDestinataire]:
    """Les personnes attendues, avec l'adresse que l'on peut leur proposer."""
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    contenu = brouillon.contenu or {}
    personnes = _personnes_brouillon(contenu)

    convocation_brute = contenu.get("convocation") or {}
    convocation = convocation_brute if isinstance(convocation_brute, dict) else {}
    destinataires_bruts = convocation.get("destinataires") or []
    deja = {
        _nom_cle(d.get("nom")): d.get("email")
        for d in (destinataires_bruts if isinstance(destinataires_bruts, list) else [])
        if isinstance(d, dict) and d.get("email")
    }
    expert_ids = set()
    for p in personnes:
        try:
            expert_ids.add(uuid.UUID(str(p.get("expert_comptable_id"))))
        except (TypeError, ValueError):
            continue
    experts: dict[str, str] = {}
    if expert_ids:
        res = await db.execute(
            select(ExpertComptable.id, ExpertComptable.email).where(ExpertComptable.id.in_(expert_ids))
        )
        experts = {str(i): e for i, e in res.all() if e}
    res = await db.execute(
        select(CommissionMember.full_name, CommissionMember.email).where(
            CommissionMember.service_id == brouillon.service_id,
            CommissionMember.email.is_not(None),
        )
    )
    membres = {_nom_cle(n): e for n, e in res.all() if e}

    out: list[ConvocationDestinataire] = []
    for p in personnes:
        cle = _nom_cle(p.get("nom"))
        email, source = None, None
        if deja.get(cle):
            email, source = deja[cle], "convocation"
        elif experts.get(str(p.get("expert_comptable_id"))):
            email, source = experts[str(p.get("expert_comptable_id"))], "expert"
        elif membres.get(cle):
            email, source = membres[cle], "membre"
        out.append(
            ConvocationDestinataire(
                nom=str(p.get("nom")).strip(),
                titre_fonction=str(p.get("titre_fonction") or "").strip(),
                email=email,
                source=source,
            )
        )
    return out


@router.post("/brouillons/{brouillon_id}/convocation", response_model=ConvocationResultat)
async def envoyer_convocation(
    brouillon_id: str,
    payload: ConvocationEnvoi,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ConvocationResultat:
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    service = await _ensure_service_access(db, user, tenant_id, brouillon.service_id)
    contenu = dict(brouillon.contenu or {})

    personnes = {
        _nom_cle(p.get("nom")): str(p.get("nom") or "").strip()
        for p in _personnes_brouillon(contenu)
    }
    destinataires: list[tuple[str, str]] = []
    vus: set[str] = set()
    for d in payload.destinataires:
        email = (d.email or "").strip()
        if not email:
            continue
        nom_cle = _nom_cle(d.nom)
        if not nom_cle or nom_cle not in personnes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Le destinataire « {d.nom.strip()} » n'est pas inscrit à cette réunion.",
            )
        if not _EMAIL_RE.match(email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Adresse e-mail invalide : {email}")
        if email.lower() in vus:
            continue
        vus.add(email.lower())
        destinataires.append((personnes[nom_cle], email))
    if not destinataires:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune adresse e-mail à convoquer.")

    service_label = " - ".join(x for x in (service.code, service.libelle) if x)
    try:
        reunion = reunion_depuis_brouillon(contenu, service_label)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    smtp_cfg = resolve_smtp_config(await get_system_settings(db, tenant_id))
    if smtp_cfg is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="L'envoi d'e-mails n'est pas configuré (paramètres SMTP).",
        )
    org_nom = (
        await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
    ).scalar_one_or_none() or ""

    precedente_brute = contenu.get("convocation") or {}
    precedente = precedente_brute if isinstance(precedente_brute, dict) else {}
    uid = precedente.get("uid") or f"{brouillon.id}@onec"
    try:
        sequence = max(0, int(precedente.get("sequence") or 0)) + 1
    except (TypeError, ValueError):
        sequence = 1
    echecs = await send_in_thread(
        envoyer_convocations,
        reunion,
        destinataires,
        smtp=smtp_cfg,
        message=payload.message,
        organisation=org_nom,
        uid=uid,
        sequence=sequence,
    )
    en_echec = {e for e, _ in echecs}
    envoyes = [(n, e) for n, e in destinataires if e not in en_echec]

    if envoyes:
        # Les adresses déjà connues restent : un renvoi partiel n'oublie pas
        # ceux qui avaient été convoqués la première fois.
        connus = {
            _nom_cle(d.get("nom")): d
            for d in (precedente.get("destinataires") or [])
            if isinstance(d, dict)
        }
        for n, e in envoyes:
            connus[_nom_cle(n)] = {"nom": n, "email": e}
        contenu["convocation"] = {
            "uid": uid,
            "sequence": sequence,
            "envoyee_le": datetime.now(timezone.utc).isoformat(),
            "envoyee_par": _user_label(user),
            "destinataires": list(connus.values()),
        }
        brouillon.contenu = contenu
        await db.commit()
        await db.refresh(brouillon)

    return ConvocationResultat(
        envoyes=len(envoyes),
        echecs=[ConvocationEchec(email=e, raison=r) for e, r in echecs],
        contenu=brouillon.contenu or {},
    )


# ----------------------------------------------------------------------
# Pièces de la réunion : la liste de présence, imprimée, signée en séance
# puis scannée, et le PV. Elles se déposent sur le brouillon dès qu'on les a,
# et deviennent des annexes de la réquisition à la création du remboursement.
# ----------------------------------------------------------------------

PIECES_REUNION = {"liste_presence": "Liste de présence signée", "pv": "Procès-verbal"}
PIECE_ALLOWED_TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}
# Même plafond que les annexes de réquisition : elles partent en pièces jointes
# des e-mails du Bureau.
MAX_PIECE_SIZE = 3 * 1024 * 1024


def _piece_kind(kind: str) -> str:
    if kind not in PIECES_REUNION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce inconnue")
    return kind


def _supprimer_fichier_piece(piece: dict | None) -> None:
    """Retire du disque une pièce qui n'a pas (encore) été annexée."""
    if not piece or piece.get("annexee"):
        return
    path = _remboursement_pdf_fs_path(piece.get("file_path"))
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.warning("Pièce de réunion non supprimée : %s", path)


@router.post("/brouillons/{brouillon_id}/pieces/{kind}", response_model=RemboursementTransportBrouillonResponse)
async def deposer_piece_reunion(
    brouillon_id: str,
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
    db: AsyncSession = Depends(get_db),
) -> RemboursementTransportBrouillonResponse:
    kind = _piece_kind(kind)
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)

    content_type = (file.content_type or "").lower()
    ext = PIECE_ALLOWED_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format accepté : PDF, JPG ou PNG.")
    contents = await read_upload_limited(
        file,
        MAX_PIECE_SIZE,
        error_detail="Fichier trop volumineux (max 3 Mo)",
    )
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide")
    if not matches_declared_type(contents, content_type):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le contenu du fichier ne correspond pas au format annoncé.")

    now = datetime.now(timezone.utc)
    rel_dir = f"tenants/{tenant_uuid}/reunions/{now.year:04d}/{now.month:02d}"
    target_dir = os.path.join(UPLOAD_ROOT, *rel_dir.split("/"))
    os.makedirs(target_dir, exist_ok=True)
    # Nom aléatoire : la liste porte des noms et des signatures.
    stored = f"{kind}-{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(target_dir, stored)
    with open(dest_path, "wb") as handle:
        handle.write(contents)

    contenu = dict(brouillon.contenu or {})
    pieces = dict(contenu.get("pieces") or {})
    ancienne_piece = pieces.get(kind)
    pieces[kind] = {
        "file_path": f"/uploads/{rel_dir}/{stored}",
        "filename": file.filename or f"{PIECES_REUNION[kind]}{ext}",
        "file_type": content_type,
        "file_size": len(contents),
        "deposee_le": now.isoformat(),
        "deposee_par": _user_label(user),
    }
    contenu["pieces"] = pieces
    brouillon.contenu = contenu
    brouillon.updated_by = user.id
    brouillon.updated_at = now
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            os.remove(dest_path)
        except OSError:
            logger.warning("Nouvelle pièce de réunion non nettoyée après échec : %s", dest_path)
        raise
    # En cas d'échec de la base, l'ancienne pièce reste donc intacte. Après le
    # commit seulement, elle peut être retirée sans casser les métadonnées.
    _supprimer_fichier_piece(ancienne_piece if isinstance(ancienne_piece, dict) else None)
    await db.refresh(brouillon)
    return (await _brouillon_responses(db, [brouillon]))[0]


@router.get("/brouillons/{brouillon_id}/pieces/{kind}")
async def voir_piece_reunion(
    brouillon_id: str,
    kind: str,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    kind = _piece_kind(kind)
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    pieces = (brouillon.contenu or {}).get("pieces") or {}
    piece = pieces.get(kind) if isinstance(pieces, dict) else None
    path = _remboursement_pdf_fs_path((piece or {}).get("file_path"))
    if not piece or not path or not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pièce introuvable")
    return FileResponse(path, media_type=piece.get("file_type") or "application/octet-stream")


@router.delete("/brouillons/{brouillon_id}/pieces/{kind}", response_model=RemboursementTransportBrouillonResponse)
async def retirer_piece_reunion(
    brouillon_id: str,
    kind: str,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RemboursementTransportBrouillonResponse:
    kind = _piece_kind(kind)
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    contenu = dict(brouillon.contenu or {})
    pieces = dict(contenu.get("pieces") or {})
    piece_retiree = pieces.pop(kind, None)
    contenu["pieces"] = pieces
    brouillon.contenu = contenu
    await db.commit()
    _supprimer_fichier_piece(piece_retiree if isinstance(piece_retiree, dict) else None)
    await db.refresh(brouillon)
    return (await _brouillon_responses(db, [brouillon]))[0]


@router.post("/brouillons/{brouillon_id}/annexer", response_model=list[RequisitionAnnexeOut])
async def annexer_pieces_reunion(
    brouillon_id: str,
    payload: PiecesReunionAnnexer,
    user: User = Depends(has_any_permission(BROUILLON_PERMISSIONS)),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RequisitionAnnexeOut]:
    """Joint les pièces du brouillon à la réquisition du remboursement créé.

    Le fichier ne bouge pas : l'annexe pointe sur lui. Une pièce déjà annexée
    ne l'est pas deux fois si l'appel est rejoué.
    """
    brouillon = await _get_brouillon(db, user, tenant_id, brouillon_id)
    req = (
        await db.execute(
            select(Requisition).where(
                Requisition.id == payload.requisition_id,
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
    if req.service_id != brouillon.service_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La réquisition n'est pas celle de ce service.")
    if req.type_requisition != "remboursement_transport":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Les pièces de réunion ne peuvent être jointes qu'à une réquisition de remboursement de transport.",
        )

    contenu = dict(brouillon.contenu or {})
    pieces_brutes = contenu.get("pieces") or {}
    pieces = {
        k: dict(v)
        for k, v in (pieces_brutes.items() if isinstance(pieces_brutes, dict) else [])
        if isinstance(v, dict)
    }
    # Valider tout le lot avant d'ajouter la première annexe : pas de résultat
    # partiel si une pièce est absente ou déjà rattachée ailleurs.
    for kind in PIECES_REUNION:
        piece = pieces.get(kind)
        if not piece:
            continue
        annexee = piece.get("annexee")
        if annexee and annexee != str(req.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette pièce est déjà annexée à une autre réquisition.")
        path = _remboursement_pdf_fs_path(piece.get("file_path"))
        if not path or not os.path.isfile(path):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Le fichier « {PIECES_REUNION[kind]} » est introuvable.")

    chemins = [p.get("file_path") for p in pieces.values() if p.get("file_path")]
    existantes: set[str] = set()
    if chemins:
        result = await db.execute(
            select(RequisitionAnnexe.file_path).where(
                RequisitionAnnexe.requisition_id == req.id,
                RequisitionAnnexe.file_path.in_(chemins),
            )
        )
        existantes = set(result.scalars().all())
    creees: list[RequisitionAnnexe] = []
    for kind in PIECES_REUNION:
        piece = pieces.get(kind)
        if not piece:
            continue
        if piece.get("annexee") == str(req.id) or piece.get("file_path") in existantes:
            piece["annexee"] = str(req.id)
            continue
        annexe = RequisitionAnnexe(
            organisation_id=tenant_id,
            requisition_id=req.id,
            file_path=piece["file_path"],
            # Nommée d'après ce qu'elle est, pas d'après le fichier du scanner.
            filename=f"{PIECES_REUNION[kind]}{os.path.splitext(piece['file_path'])[1]}",
            file_type=piece.get("file_type") or "application/pdf",
            file_size=int(piece.get("file_size") or 0),
            upload_date=datetime.now(timezone.utc),
        )
        db.add(annexe)
        creees.append(annexe)
        piece["annexee"] = str(req.id)
    contenu["pieces"] = pieces
    brouillon.contenu = contenu
    await db.commit()
    for a in creees:
        await db.refresh(a)
    return [RequisitionAnnexeOut.model_validate(_annexe_payload(a)) for a in creees]
