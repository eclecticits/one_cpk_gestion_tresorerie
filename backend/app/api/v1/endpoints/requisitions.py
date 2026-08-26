from __future__ import annotations

import uuid
from datetime import datetime, timezone
import logging
import os
import re
from typing import Any
import io

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status, Response, Request
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id, get_current_tenant_uuid, has_permission, has_any_permission
from app.db.session import get_db
from app.core.config import settings
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.requisition import Requisition
from app.models.requisition_status_history import RequisitionStatusHistory
from app.models.dossier_requisition import DossierRequisition
from app.models.commission_member import CommissionMember
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.remboursement_transport import RemboursementTransport
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.requisition import RequisitionExamenPayload
from app.models.service import Service
from app.services.document_sequences import generate_document_number
from app.services.audit_service import get_request_ip, log_action
from app.services.budget_engagement import resynchroniser_engagement_requisition
from app.services.mailer import normalize_email_list, send_requisition_notification, send_requisition_workflow_email
from app.services.email_config import resolve_smtp_config
from app.services.system_settings_service import get_system_settings
from app.services.forecasting import compute_cash_forecast
from app.services.service_access import get_user_service_ids, can_view_all_services, user_has_permission, has_module_menu_access
from app.services.notifications import (
    REQUISITION_APPROVED,
    build_settings as build_whatsapp_settings,
    notify_whatsapp,
    resolve_outflow_recipients,
)
from app.schemas.requisition import (
    RequisitionAnnexeOut,
    RequisitionCreate,
    RequisitionOut,
    RequisitionUpdate,
    RequisitionWithUserOut,
)
from app.schemas.pdf_requisition import (
    PdfRequisitionParseResponse,
    PdfRequisitionImportRequest,
    PdfRequisitionImportResponse,
)
# parse_requisition_pdf est importé dans la vue : il tire pdfplumber (10 Mo de
# RSS par worker) pour un seul endpoint d'OCR. Même motif que treasury.py.
from app.services.official_pdf import ensure_remboursement_official_pdf
from app.services.reglement import calculer_volets
from app.services.requisition_service import (
    update_requisition_logic,
    create_requisition_logic,
    submit_requisition_examen_logic,
    validate_requisition_examen_logic,
    reject_requisition_examen_logic,
    sign_commission_requisition_logic,
    validate_requisition_logic,
    vise_requisition_logic,
    reject_requisition_logic,
    soft_delete_requisition_logic,
    restore_requisition_logic,
    apply_snapshot_if_needed,
    require_requisition_lines,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.requisitions")
MAX_ANNEXE_SIZE = 3 * 1024 * 1024
ANNEXE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ANNEXE_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT


#: `entity_type` porté par les lignes de `notification_logs` de ce module.
NOTIF_ENTITY_REQUISITION = "requisition"


def _status_values_for_filter(value: str) -> list[str]:
    normalized = value.strip().upper()
    return {
        "AUTORISEE": ["AUTORISEE", "VALIDEE", "VALIDEE_TRESORERIE", "VALIDE_TECHNIQUE"],
        "PAYEE": ["PAYEE", "DECAISSE"],
        "REJETEE": ["REJETEE", "REJETTE"],
    }.get(normalized, [normalized])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_montant(value: Any) -> str:
    """Montant lisible dans un message : « 1 234.50 ». Sans devise (variable à part)."""
    try:
        return f"{float(value or 0):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0.00"


def _nom_utilisateur(user: User | None) -> str:
    if user is None:
        return ""
    nom = " ".join(filter(None, [getattr(user, "prenom", ""), getattr(user, "nom", "")])).strip()
    return nom or (getattr(user, "email", "") or "")


async def _notify_requisition_approuvee_whatsapp(
    db: AsyncSession,
    background_tasks,
    *,
    req: Requisition,
    tenant_id: int,
    validateur: User | None,
) -> None:
    """Annonce le visa final d'une réquisition au Bureau, par WhatsApp.

    Remplace le bloc artisanal qui vivait dans `vise_requisition`. Deux écarts
    voulus :

    * Le gabarit passe de `FUND_OUTFLOW` à `REQUISITION_APPROVED`. L'ancien
      message annonçait une « réquisition validée » avec le vocabulaire d'une
      sortie de fonds ; le nouveau dit « en attente de paiement — aucun fonds
      n'a encore été décaissé », ce qui est la réalité : le visa ne déplace
      aucun argent.
    * Les destinataires viennent du Bureau (`commission_members` ayant coché la
      réception), avec repli sur la liste libre `whatsapp_agents` — l'ancien
      comportement — tant que les téléphones du Bureau ne sont pas renseignés.

    Ne lève jamais : à appeler après le `commit()`, qui est fait par
    `vise_requisition_logic`.
    """
    try:
        ns = await get_system_settings(db, tenant_id)
        if ns is None:
            return
        org_name = (
            await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
        ).scalar_one_or_none() or ""
        settings_obj = build_whatsapp_settings(ns, org_name)
        if not settings_obj.accepts(REQUISITION_APPROVED):
            # Canal fermé pour ce tenant : ni requête de destinataires, ni ligne
            # de journal. On sort avant d'interroger le Bureau.
            return

        recipients = await resolve_outflow_recipients(
            db, tenant_id, fallback_numbers=getattr(ns, "whatsapp_agents", "")
        )
        if not recipients:
            logger.info("WhatsApp : aucun destinataire pour la réquisition %s", req.id)
            return

        date_visa = getattr(req, "approuvee_le", None) or getattr(req, "date_requisition", None)

        await notify_whatsapp(
            db,
            background_tasks,
            organisation_id=tenant_id,
            event_type=REQUISITION_APPROVED,
            entity_type=NOTIF_ENTITY_REQUISITION,
            entity_id=str(req.id),
            recipients=recipients,
            variables={
                "reference": req.numero_requisition or "",
                "date": date_visa.strftime("%d/%m/%Y") if date_visa else "",
                "beneficiaire": getattr(req, "instance_beneficiaire", "") or "",
                "motif": req.objet or "",
                "montant": _fmt_montant(req.montant_total),
                "devise": req.devise or "USD",
                "validateur": _nom_utilisateur(validateur),
            },
            settings=settings_obj,
        )
    except Exception:
        logger.exception(
            "Échec de préparation de la notification WhatsApp (réquisition %s)",
            getattr(req, "id", None),
        )


def _record_status_history(
    *,
    db: AsyncSession,
    requisition: Requisition,
    old_status: str | None,
    new_status: str | None,
    user: User | None,
    comment: str | None = None,
) -> None:
    if not new_status or old_status == new_status:
        return
    db.add(
        RequisitionStatusHistory(
            organisation_id=requisition.organisation_id,
            requisition_id=requisition.id,
            old_status=old_status,
            new_status=new_status,
            comment=comment,
            changed_by=user.id if user else None,
            changed_at=_utcnow(),
        )
    )


async def _check_cash_watchdog(
    *,
    db: AsyncSession,
    user: User | None,
    request: Request | None,
    requisition_id: str,
) -> None:
    try:
        forecast = await compute_cash_forecast(
            db=db,
            lookback_days=30,
            horizon_days=30,
            reserve_threshold=1000.0,
            tenant_id=getattr(user, "organisation_id", None),
        )
        if forecast.stress_projection <= forecast.reserve_threshold:
            await log_action(
                db,
                user_id=user.id if user else None,
                action="CASH_STRESS_ALERT",
                target_table="requisitions",
                target_id=requisition_id,
                new_value={
                    "stress_projection": forecast.stress_projection,
                    "reserve_threshold": forecast.reserve_threshold,
                    "pending_total": forecast.pending_total,
                },
                ip_address=get_request_ip(request),
            )
            await db.commit()
    except Exception:
        logger.exception("Cash watchdog check failed")


def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _status_from_payload(payload: RequisitionCreate | RequisitionUpdate) -> str | None:
    if payload.status:
        return payload.status
    if payload.statut:
        return payload.statut
    return None


def _user_info(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "prenom": user.prenom,
        "nom": user.nom,
        "email": user.email,
    }


async def _resolve_service(service_id: int, db: AsyncSession) -> Service:
    res = await db.execute(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id invalide")
    return service


def _annexe_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/static/"):
        rel_path = file_path.replace("/static/", "", 1)
        return os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "static", rel_path)
        )
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    legacy_dir = os.path.abspath(os.path.join(UPLOAD_ROOT, "annexes"))
    return os.path.abspath(os.path.join(legacy_dir, os.path.basename(file_path)))


def _requisition_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    legacy_dir = os.path.abspath(os.path.join(UPLOAD_ROOT, "requisitions"))
    return os.path.abspath(os.path.join(legacy_dir, os.path.basename(file_path)))


def _remboursement_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    legacy_dir = os.path.abspath(os.path.join(UPLOAD_ROOT, "remboursements-transport"))
    return os.path.abspath(os.path.join(legacy_dir, os.path.basename(file_path)))


async def _collect_requisition_email_attachments(
    db: AsyncSession,
    req: Requisition,
) -> tuple[str | None, list[str]]:
    attachment_paths: list[str] = []

    annexes_res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id == req.id)
        .order_by(RequisitionAnnexe.upload_date.asc())
    )
    annexes = annexes_res.scalars().all()
    attachment_paths.extend(_annexe_fs_path(a.file_path) for a in annexes)

    official_pdf_path = None
    if req.type_requisition == "remboursement_transport":
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id)
        )
        remboursement = remb_res.scalar_one_or_none()
        if remboursement and remboursement.pdf_path:
            remboursement_pdf_path = _remboursement_pdf_fs_path(remboursement.pdf_path)
            if remboursement_pdf_path and os.path.exists(remboursement_pdf_path):
                official_pdf_path = remboursement_pdf_path
    if not official_pdf_path:
        requisition_pdf_path = _requisition_pdf_fs_path(req.pdf_path)
        if requisition_pdf_path and os.path.exists(requisition_pdf_path):
            official_pdf_path = requisition_pdf_path

    return official_pdf_path, attachment_paths


async def _log_requisition_email_preflight(
    db: AsyncSession,
    req: Requisition,
    official_pdf_path: str | None,
    attachment_paths: list[str],
) -> None:
    annexes_res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id == req.id)
        .order_by(RequisitionAnnexe.upload_date.asc())
    )
    annexes = annexes_res.scalars().all()

    annexes_debug: list[dict[str, Any]] = []
    for annexe in annexes:
        resolved_path = _annexe_fs_path(annexe.file_path)
        exists = bool(resolved_path) and os.path.exists(resolved_path)
        item = {
            "annexe_id": str(annexe.id),
            "file_path_db": annexe.file_path,
            "filename": annexe.filename,
            "resolved_path": resolved_path,
            "exists": exists,
        }
        annexes_debug.append(item)
        if not exists:
            logger.error(
                "Requisition email annexe missing on disk requisition_id=%s numero_requisition=%s annexe_id=%s file_path_db=%s resolved_path=%s",
                req.id,
                req.numero_requisition,
                annexe.id,
                annexe.file_path,
                resolved_path,
            )

    pdf_path_db = req.pdf_path
    resolved_pdf_path = _requisition_pdf_fs_path(pdf_path_db)
    pdf_exists = bool(resolved_pdf_path) and os.path.exists(resolved_pdf_path)
    total_files_attached = (1 if official_pdf_path else 0) + sum(
        1 for path in attachment_paths if path and os.path.exists(path)
    )
    logger.info(
        "Requisition email preflight requisition_id=%s numero_requisition=%s pdf_path_db=%s resolved_pdf_path=%s pdf_exists=%s annexes=%s attachment_paths=%s total_mime_attachments=%s",
        req.id,
        req.numero_requisition,
        pdf_path_db,
        resolved_pdf_path,
        pdf_exists,
        annexes_debug,
        [
            {
                "resolved_path": path,
                "exists": bool(path) and os.path.exists(path),
            }
            for path in attachment_paths
        ],
        total_files_attached,
    )


def _pdf_icon_path() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "static", "icons", "pdf-icon.svg")
    )


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "")
    if not base:
        return "annexe"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return safe.strip("._") or "annexe"


def _safe_ref(value: str) -> str:
    if not value:
        return "REQ"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return safe.strip("._-") or "REQ"


def _tenant_requisition_dir(tenant_uuid: str, year: int, month: int) -> str:
    return os.path.join(
        UPLOAD_ROOT,
        "tenants",
        str(tenant_uuid),
        "requisitions",
        f"{year:04d}",
        f"{month:02d}",
    )


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


def _requisition_out(
    req: Requisition,
    *,
    demandeur: User | None = None,
    validateur: User | None = None,
    approbateur: User | None = None,
    examinateur: User | None = None,
    caissier: User | None = None,
    annexe: RequisitionAnnexe | None = None,
    montant_deja_paye: Any | None = None,
    lignes_count: int | None = None,
    remboursement_transport: Any | None = None,
    volets_reglement: list[Any] | None = None,
) -> dict[str, Any]:
    base = {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "reference_numero": req.reference_numero,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": req.montant_total or 0,
        "montant_deja_paye": montant_deja_paye,
        "lignes_count": lignes_count,
        "service_id": req.service_id,
        "compte_bancaire_id": req.compte_bancaire_id,
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
        "decaissement_progressif": bool(getattr(req, "decaissement_progressif", False)),
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
        "print_settings_snapshot": req.print_settings_snapshot,
        "organisation_snapshot": req.organisation_snapshot,
        "bank_account_snapshot": req.bank_account_snapshot,
        "signatories_snapshot": req.signatories_snapshot,
        "historical_snapshot_status": req.historical_snapshot_status,
        "snapshot_created_at": req.snapshot_created_at,
        "snapshot_version": req.snapshot_version,
        "row_version": req.row_version,
        "exchange_rate_snapshot": req.exchange_rate_snapshot,
        "exchange_rate_source": req.exchange_rate_source,
        "exchange_rate_date": req.exchange_rate_date,
        "base_amount_snapshot": req.base_amount_snapshot,
        "converted_amount_snapshot": req.converted_amount_snapshot,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "annexe": _annexe_payload(annexe) if annexe else None,
        "remboursement_transport": remboursement_transport,
        # Découpage du règlement, dérivé des lignes. Absent quand l'appelant ne
        # l'a pas demandé : le calculer suppose de charger les lignes, ce qui
        # n'a pas sa place dans les listes.
        "volets_reglement": (
            [volet.to_payload() for volet in volets_reglement]
            if volets_reglement is not None
            else None
        ),
    }
    if demandeur:
        base["demandeur"] = _user_info(demandeur)
    if validateur:
        base["validateur"] = _user_info(validateur)
    if approbateur:
        base["approbateur"] = _user_info(approbateur)
    if examinateur:
        base["examinateur"] = _user_info(examinateur)
    if caissier:
        base["caissier"] = _user_info(caissier)
    return base


async def _get_requisition_with_users(
    db: AsyncSession,
    req: Requisition,
    tenant_id: int,
) -> dict[str, Any]:
    user_ids = {
        req.created_by,
        req.validee_par,
        req.approuvee_par,
        req.examen_par,
        req.payee_par,
    }
    user_ids = {uid for uid in user_ids if uid}
    users_map = {}
    if user_ids:
        users_res = await db.execute(
            select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id)
        )
        users_map = {u.id: u for u in users_res.scalars().all()}

    # Fetch annexe
    ann_res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id == req.id)
        .order_by(RequisitionAnnexe.upload_date.desc())
        .limit(1)
    )
    ann = ann_res.scalar_one_or_none()

    # Fetch montant deja paye
    sortie_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0))
        .where(SortieFonds.requisition_id == req.id)
        .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
    )
    montant_paye = sortie_res.scalar_one() or 0

    # Fetch transport info if applicable
    remboursement_transport = None
    if req.type_requisition == "remboursement_transport":
        t_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id)
        )
        t = t_res.scalar_one_or_none()
        if t:
            remboursement_transport = {
                "id": str(t.id),
                "numero_remboursement": t.numero_remboursement,
                "reference_numero": t.reference_numero,
                "instance": t.instance,
                "date_reunion": t.date_reunion.isoformat() if t.date_reunion else None,
                "lieu": t.lieu,
            }

    lignes_res = await db.execute(
        select(LigneRequisition)
        .where(LigneRequisition.requisition_id == req.id)
        .order_by(LigneRequisition.id.asc())
    )
    volets = calculer_volets(lignes_res.scalars().all(), mode_defaut=req.mode_paiement or "cash")

    return _requisition_out(
        req,
        demandeur=users_map.get(req.created_by),
        validateur=users_map.get(req.validee_par),
        approbateur=users_map.get(req.approuvee_par),
        examinateur=users_map.get(req.examen_par),
        caissier=users_map.get(req.payee_par),
        annexe=ann,
        montant_deja_paye=montant_paye,
        remboursement_transport=remboursement_transport,
        volets_reglement=volets,
    )


async def _schedule_bureau_notifications(
    *,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    req: Requisition,
    action_user: User,
) -> None:
    ns = await get_system_settings(db, req.organisation_id)
    smtp_cfg = resolve_smtp_config(ns)
    if smtp_cfg is None:
        return

    if req.type_requisition == "remboursement_transport":
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id).limit(1)
        )
        remboursement = remb_res.scalar_one_or_none()
        if remboursement is not None:
            await ensure_remboursement_official_pdf(db, remboursement, regenerate=not remboursement.pdf_path)
    await db.commit()

    org_res = await db.execute(
        select(Organisation.nom, Organisation.slug).where(Organisation.id == req.organisation_id).limit(1)
    )
    org_row = org_res.one_or_none()
    org_name = org_row[0] if org_row else None
    org_slug = org_row[1] if org_row else None

    examinateur_name = None
    created_by_name = " ".join(filter(None, [action_user.prenom, action_user.nom])) or action_user.email or "Systeme"
    if req.created_by:
        creator_res = await db.execute(select(User).where(User.id == req.created_by))
        creator = creator_res.scalar_one_or_none()
        if creator:
            created_by_name = " ".join(filter(None, [creator.prenom, creator.nom])) or creator.email or created_by_name
    if req.examen_par:
        examinateur_res = await db.execute(select(User).where(User.id == req.examen_par))
        examinateur = examinateur_res.scalar_one_or_none()
        if examinateur:
            examinateur_name = " ".join(filter(None, [examinateur.prenom, examinateur.nom])) or examinateur.email

    official_pdf_path, attachment_paths = await _collect_requisition_email_attachments(db, req)
    await _log_requisition_email_preflight(db, req, official_pdf_path, attachment_paths)
    if not official_pdf_path:
        raise RuntimeError(f"PDF officiel introuvable pour la réquisition {req.numero_requisition}")

    if ns.email_validation_1:
        body_lines = [
            "Chers Membres du Bureau,",
            "Une réquisition a passé l'examen et attend votre avis technique.",
            f"Référence : {req.numero_requisition}",
            f"Objet : {req.objet or '-'}",
            f"Montant : {float(req.montant_total or 0):,.2f} $",
            f"Demandeur : {created_by_name}",
        ]
        if examinateur_name:
            body_lines.append(f"Examinée par : {examinateur_name}")
        body_lines.append("Merci de vous connecter pour donner votre avis.")
        background_tasks.add_task(
            send_requisition_workflow_email,
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            recipient=ns.email_validation_1,
            subject=f"📝 Réquisition à vérifier - {req.numero_requisition}",
            title="Avis technique requis",
            body_lines=body_lines,
            brand_name="ONEC",
            organisation_name=org_name,
            organisation_slug=org_slug,
            official_pdf_path=official_pdf_path,
            attachment_paths=attachment_paths,
        )

    if ns.email_president:
        logger.info(
            "Scheduling bureau notification requisition=%s type=%s president_email=%s bureau_cc_raw=%s bureau_cc_normalized=%s examinateur=%s",
            req.numero_requisition,
            req.type_requisition,
            ns.email_president,
            ns.emails_bureau_cc,
            normalize_email_list(ns.emails_bureau_cc),
            examinateur_name,
        )

        background_tasks.add_task(
            send_requisition_notification,
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            president_email=ns.email_president,
            cc_emails=ns.emails_bureau_cc,
            requisition_num=req.numero_requisition,
            montant_total=float(req.montant_total or 0),
            objet=req.objet or "",
            created_by=created_by_name,
            examinateur=examinateur_name,
            official_pdf_path=official_pdf_path,
            attachment_paths=attachment_paths,
            brand_name="ONEC",
            organisation_name=org_name,
            organisation_slug=org_slug,
            type_requisition=req.type_requisition,
        )


async def _schedule_examen_submission_notification(
    *,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    req: Requisition,
    action_user: User,
) -> None:
    ns = await get_system_settings(db, req.organisation_id)
    smtp_cfg = resolve_smtp_config(ns)
    if smtp_cfg is None or not ns.email_validation_1:
        return

    org_res = await db.execute(
        select(Organisation.nom, Organisation.slug).where(Organisation.id == req.organisation_id).limit(1)
    )
    org_row = org_res.one_or_none()
    org_name = org_row[0] if org_row else None
    org_slug = org_row[1] if org_row else None

    created_by_name = " ".join(filter(None, [action_user.prenom, action_user.nom])) or action_user.email or "Systeme"
    if req.created_by:
        creator_res = await db.execute(select(User).where(User.id == req.created_by))
        creator = creator_res.scalar_one_or_none()
        if creator:
            created_by_name = " ".join(filter(None, [creator.prenom, creator.nom])) or creator.email or created_by_name

    reference = req.numero_requisition
    subject_label = "Réquisition"
    subject_action = "soumise"
    title = "Réquisition soumise à l'examen"
    dossier_label = "réquisition"
    if req.type_requisition == "remboursement_transport":
        subject_label = "Remboursement transport"
        subject_action = "soumis"
        title = "Remboursement transport soumis à l'examen"
        dossier_label = "demande de remboursement de transport"
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id).limit(1)
        )
        remboursement = remb_res.scalar_one_or_none()
        if remboursement and remboursement.numero_remboursement:
            reference = remboursement.numero_remboursement

    official_pdf_path, attachment_paths = await _collect_requisition_email_attachments(db, req)
    await _log_requisition_email_preflight(db, req, official_pdf_path, attachment_paths)

    body_lines = [
        "Bonjour,",
        f"Une {dossier_label} vient d'être soumise à l'examen dans ONEC Smart.",
        f"Référence : {reference}",
        f"Objet : {req.objet or '-'}",
        f"Montant : {float(req.montant_total or 0):,.2f} $",
        f"Demandeur : {created_by_name}",
        "Merci de vous connecter pour procéder à l'examen.",
    ]
    if req.type_requisition == "remboursement_transport":
        body_lines.insert(3, f"Réquisition liée : {req.numero_requisition}")

    background_tasks.add_task(
        send_requisition_workflow_email,
        smtp_host=smtp_cfg.host,
        smtp_port=smtp_cfg.port,
        smtp_user=smtp_cfg.user,
        smtp_password=smtp_cfg.password,
        sender=smtp_cfg.sender,
        recipient=ns.email_validation_1,
        subject=f"{subject_label} {subject_action} à l'examen - {reference}",
        title=title,
        body_lines=body_lines,
        brand_name="ONEC",
        organisation_name=org_name,
        organisation_slug=org_slug,
        official_pdf_path=official_pdf_path,
        attachment_paths=attachment_paths,
    )


@router.get("/verify")
async def verify_requisition(
    ref: str = Query(..., description="Numéro de réquisition ou UUID"),
    amount: float = Query(..., description="Montant attendu (USD)"),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    requisition: Requisition | None = None
    try:
        rid = uuid.UUID(ref)
        res = await db.execute(
            select(Requisition).where(
                Requisition.id == rid,
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
        requisition = res.scalar_one_or_none()
    except ValueError:
        res = await db.execute(
            select(Requisition).where(
                Requisition.numero_requisition == ref,
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
        requisition = res.scalar_one_or_none()

    if requisition is None:
        return {"ok": False, "reason": "not_found", "ref": ref, "amount": amount}

    montant = float(requisition.montant_total or 0)
    ok = abs(montant - float(amount)) <= 0.01
    return {
        "ok": ok,
        "ref": requisition.numero_requisition or str(requisition.id),
        "amount": amount,
        "montant_total": montant,
        "statut": requisition.status,
        "created_at": requisition.created_at,
    }


@router.get("/verify-report")
async def verify_requisition_report(
    date_debut: str = Query(...),
    date_fin: str = Query(...),
    total: float = Query(...),
    count: int = Query(...),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    start = _parse_datetime(date_debut)
    end = _parse_datetime(date_fin, end_of_day=True)
    if start is None or end is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")

    query = select(Requisition).where(
        Requisition.organisation_id == tenant_id,
        Requisition.created_at.between(start, end),
        Requisition.is_deleted.is_(False),
    )
    res = await db.execute(query)
    requisitions = res.scalars().all()
    calc_total = sum(float(r.montant_total or 0) for r in requisitions)
    calc_count = len(requisitions)
    ok = abs(calc_total - float(total)) <= 0.01 and calc_count == int(count)
    return {
        "ok": ok,
        "period": {"date_debut": date_debut, "date_fin": date_fin},
        "expected": {"total": total, "count": count},
        "actual": {"total": calc_total, "count": calc_count},
    }


def _parse_order(order: str | None):
    if not order:
        return Requisition.created_at.desc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "created_at": Requisition.created_at,
        "updated_at": Requisition.updated_at,
        "numero_requisition": Requisition.numero_requisition,
        "montant_total": Requisition.montant_total,
        "status": Requisition.status,
    }
    col = column_map.get(field)
    if col is None:
        return Requisition.created_at.desc()
    return col.desc() if direction.lower() == "desc" else col.asc()


@router.post("/generate-numero")
async def generate_numero_requisition(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Endpoint désactivé: le numéro est généré automatiquement à la création.",
    )


@router.get("", response_model=list[RequisitionOut] | list[RequisitionWithUserOut])
async def list_requisitions(
    status: str | None = Query(default=None),
    status_in: str | None = Query(default=None),
    examen_status: str | None = Query(default=None),
    dossier_id: str | None = Query(default=None),
    dossier_is_null: bool | None = Query(default=None),
    service_id: int | None = Query(default=None),
    budget_poste_id: int | None = Query(default=None),
    type_requisition: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    created_by: str | None = Query(default=None),
    search: str | None = Query(default=None),
    objet: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    include: str | None = Query(default=None),
    order: str | None = Query(default=None),
    limit: int | None = Query(default=200),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_any_permission(["requisitions", "can_create_requisition", "menu_services"])),
    tenant_id: int = Depends(get_current_tenant_id),
):
    query = select(Requisition).where(
        Requisition.organisation_id == tenant_id,
        Requisition.is_deleted.is_(False),
    )
    # Le droit d'accès au menu Réquisitions donne une vue organisationnelle
    # complète. Les utilisateurs qui disposent uniquement d'un droit de
    # création ou d'un accès à un autre module restent limités à leurs services.
    has_requisitions_menu = await has_module_menu_access(db, user, "menu_requisitions")
    if not has_requisitions_menu:
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")
        query = query.where(Requisition.service_id.in_(service_ids))
        if service_id is not None and service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="service_id non autorisé")
    if service_id is not None:
        query = query.where(Requisition.service_id == service_id)
    if status:
        query = query.where(Requisition.status.in_(_status_values_for_filter(status)))
    if status_in:
        statuses = [s for s in status_in.split(",") if s]
        if statuses:
            expanded_statuses = [value for item in statuses for value in _status_values_for_filter(item)]
            query = query.where(Requisition.status.in_(expanded_statuses))
    if examen_status:
        query = query.where(Requisition.examen_status == examen_status)
    if dossier_id:
        try:
            query = query.where(Requisition.dossier_id == uuid.UUID(dossier_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid dossier_id")
    if dossier_is_null is True:
        query = query.where(Requisition.dossier_id.is_(None))
    if type_requisition:
        query = query.where(Requisition.type_requisition == type_requisition)
    if mode_paiement:
        query = query.where(Requisition.mode_paiement == mode_paiement)
    if budget_poste_id is not None:
        query = query.where(
            Requisition.id.in_(
                select(LigneRequisition.requisition_id).where(
                    LigneRequisition.budget_poste_id == budget_poste_id,
                    LigneRequisition.organisation_id == tenant_id,
                )
            )
        )
    if created_by:
        try:
            query = query.where(Requisition.created_by == uuid.UUID(created_by))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Requisition.numero_requisition.ilike(search_pattern),
                Requisition.objet.ilike(search_pattern),
                Requisition.created_by.in_(
                    select(User.id).where(
                        or_(User.prenom.ilike(search_pattern), User.nom.ilike(search_pattern)),
                        User.organisation_id == tenant_id,
                    )
                ),
            )
        )
    if objet:
        query = query.where(Requisition.objet.ilike(f"%{objet.strip()}%"))

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        query = query.where(Requisition.created_at >= start_dt)
    if end_dt:
        query = query.where(Requisition.created_at <= end_dt)

    query = query.order_by(_parse_order(order)).offset(offset)
    if limit is not None:
        query = query.limit(limit)

    res = await db.execute(query)
    requisitions = res.scalars().all()
    logger.info(
        "requisitions list date_debut=%s date_fin=%s count=%s",
        date_debut,
        date_fin,
        len(requisitions),
    )

    include_parts = {p.strip() for p in include.split(",")} if include else set()
    include_all = "all" in include_parts
    needs_users = include_parts.intersection({"demandeur", "validateur", "approbateur", "examinateur", "caissier"})
    needs_annexe = include_all or "annexe" in include_parts
    needs_montant_paye = include_all or "montant_paye" in include_parts
    needs_lignes_count = include_all or "lignes_count" in include_parts
    needs_transport = include_all or "remboursement_transport" in include_parts
    users_map: dict[uuid.UUID, User] = {}
    if needs_users:
        user_ids: set[uuid.UUID] = set()
        if "demandeur" in include_parts:
            user_ids.update({r.created_by for r in requisitions if r.created_by})
        if "validateur" in include_parts:
            user_ids.update({r.validee_par for r in requisitions if r.validee_par})
        if "approbateur" in include_parts:
            user_ids.update({r.approuvee_par for r in requisitions if r.approuvee_par})
        if "examinateur" in include_parts:
            user_ids.update({r.examen_par for r in requisitions if r.examen_par})
        if "caissier" in include_parts:
            user_ids.update({r.payee_par for r in requisitions if r.payee_par})

        if user_ids:
            users_res = await db.execute(
                select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id)
            )
            users_map = {u.id: u for u in users_res.scalars().all()}

    annexes_map: dict[uuid.UUID, RequisitionAnnexe] = {}
    if needs_annexe and requisitions:
        ann_res = await db.execute(
            select(RequisitionAnnexe)
            .where(RequisitionAnnexe.requisition_id.in_([r.id for r in requisitions]))
            .order_by(RequisitionAnnexe.requisition_id, RequisitionAnnexe.upload_date.desc())
        )
        for ann in ann_res.scalars().all():
            if ann.requisition_id not in annexes_map:
                annexes_map[ann.requisition_id] = ann

    montant_paye_map: dict[uuid.UUID, Any] = {}
    if needs_montant_paye and requisitions:
        sortie_res = await db.execute(
            select(
                SortieFonds.requisition_id,
                func.coalesce(func.sum(SortieFonds.montant_paye), 0),
            )
            .where(SortieFonds.requisition_id.in_([r.id for r in requisitions]))
            .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
            .group_by(SortieFonds.requisition_id)
        )
        montant_paye_map = {row[0]: row[1] for row in sortie_res.all()}

    lignes_count_map: dict[uuid.UUID, int] = {}
    if needs_lignes_count and requisitions:
        lignes_res = await db.execute(
            select(
                LigneRequisition.requisition_id,
                func.count(LigneRequisition.id),
            )
            .where(LigneRequisition.requisition_id.in_([r.id for r in requisitions]))
            .group_by(LigneRequisition.requisition_id)
        )
        lignes_count_map = {row[0]: int(row[1] or 0) for row in lignes_res.all()}

    transports_map: dict[uuid.UUID, dict[str, Any]] = {}
    if needs_transport and requisitions:
        transport_ids = [r.id for r in requisitions if r.type_requisition == "remboursement_transport"]
        if transport_ids:
            t_res = await db.execute(
                select(RemboursementTransport).where(RemboursementTransport.requisition_id.in_(transport_ids))
            )
            for t in t_res.scalars().all():
                transports_map[t.requisition_id] = {
                    "id": str(t.id),
                    "numero_remboursement": t.numero_remboursement,
                    "reference_numero": t.reference_numero,
                    "instance": t.instance,
                    "date_reunion": t.date_reunion.isoformat() if t.date_reunion else None,
                    "lieu": t.lieu,
                }

    return [
        _requisition_out(
            r,
            demandeur=users_map.get(r.created_by) if "demandeur" in include_parts else None,
            validateur=users_map.get(r.validee_par) if "validateur" in include_parts else None,
            approbateur=users_map.get(r.approuvee_par) if "approbateur" in include_parts else None,
            examinateur=users_map.get(r.examen_par) if "examinateur" in include_parts else None,
            caissier=users_map.get(r.payee_par) if "caissier" in include_parts else None,
            annexe=annexes_map.get(r.id),
            montant_deja_paye=montant_paye_map.get(r.id) if needs_montant_paye else None,
            lignes_count=lignes_count_map.get(r.id) if needs_lignes_count else None,
            remboursement_transport=transports_map.get(r.id),
        )
        for r in requisitions
    ]


@router.get("/mine", response_model=list[RequisitionOut])
async def list_my_requisitions(
    service_id: int | None = None,
    include: str | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RequisitionOut]:
    if not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")

        if service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")

    res = await db.execute(
        select(Requisition)
        .where(
            Requisition.service_id == service_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
        .order_by(Requisition.created_at.desc())
    )
    requisitions = list(res.scalars().all())

    include_parts = {p.strip() for p in include.split(",")} if include else set()
    users_map: dict[uuid.UUID, User] = {}
    if include_parts:
        user_ids: set[uuid.UUID] = set()
        if "demandeur" in include_parts:
            user_ids.update({r.created_by for r in requisitions if r.created_by})
        if "validateur" in include_parts:
            user_ids.update({r.validee_par for r in requisitions if r.validee_par})
        if "approbateur" in include_parts:
            user_ids.update({r.approuvee_par for r in requisitions if r.approuvee_par})
        if "examinateur" in include_parts:
            user_ids.update({r.examen_par for r in requisitions if r.examen_par})
        if "caissier" in include_parts:
            user_ids.update({r.payee_par for r in requisitions if r.payee_par})
        if user_ids:
            users_res = await db.execute(
                select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id
            ))
            users_map = {u.id: u for u in users_res.scalars().all()}

    annexes_map: dict[uuid.UUID, RequisitionAnnexe] = {}
    if requisitions:
        ann_res = await db.execute(
            select(RequisitionAnnexe)
            .where(RequisitionAnnexe.requisition_id.in_([r.id for r in requisitions]))
            .order_by(RequisitionAnnexe.requisition_id, RequisitionAnnexe.upload_date.desc())
        )
        for ann in ann_res.scalars().all():
            if ann.requisition_id not in annexes_map:
                annexes_map[ann.requisition_id] = ann

    montant_paye_map: dict[uuid.UUID, Any] = {}
    if requisitions:
        sortie_res = await db.execute(
            select(
                SortieFonds.requisition_id,
                func.coalesce(func.sum(SortieFonds.montant_paye), 0),
            )
            .where(SortieFonds.requisition_id.in_([r.id for r in requisitions]))
            .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
            .group_by(SortieFonds.requisition_id)
        )
        montant_paye_map = {row[0]: row[1] for row in sortie_res.all()}

    lignes_count_map: dict[uuid.UUID, int] = {}
    if requisitions:
        lignes_res = await db.execute(
            select(
                LigneRequisition.requisition_id,
                func.count(LigneRequisition.id),
            )
            .where(LigneRequisition.requisition_id.in_([r.id for r in requisitions]))
            .group_by(LigneRequisition.requisition_id)
        )
        lignes_count_map = {row[0]: int(row[1] or 0) for row in lignes_res.all()}

    transports_map: dict[uuid.UUID, dict[str, Any]] = {}
    if requisitions:
        transport_ids = [r.id for r in requisitions if r.type_requisition == "remboursement_transport"]
        if transport_ids:
            t_res = await db.execute(
                select(RemboursementTransport).where(RemboursementTransport.requisition_id.in_(transport_ids))
            )
            for t in t_res.scalars().all():
                transports_map[t.requisition_id] = {
                    "id": str(t.id),
                    "numero_remboursement": t.numero_remboursement,
                    "reference_numero": t.reference_numero,
                    "instance": t.instance,
                    "date_reunion": t.date_reunion.isoformat() if t.date_reunion else None,
                    "lieu": t.lieu,
                }

    return [
        _requisition_out(
            r,
            demandeur=users_map.get(r.created_by) if "demandeur" in include_parts else None,
            validateur=users_map.get(r.validee_par) if "validateur" in include_parts else None,
            approbateur=users_map.get(r.approuvee_par) if "approbateur" in include_parts else None,
            examinateur=users_map.get(r.examen_par) if "examinateur" in include_parts else None,
            caissier=users_map.get(r.payee_par) if "caissier" in include_parts else None,
            annexe=annexes_map.get(r.id),
            montant_deja_paye=montant_paye_map.get(r.id, 0),
            lignes_count=lignes_count_map.get(r.id, 0),
            remboursement_transport=transports_map.get(r.id),
        )
        for r in requisitions
    ]


@router.get("/{requisition_id}/annexe", response_model=RequisitionAnnexeOut)
async def get_requisition_annexe(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionAnnexeOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    if req_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id == rid)
        .order_by(RequisitionAnnexe.upload_date.desc())
    )
    annexe = res.scalars().first()
    if not annexe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")
    return RequisitionAnnexeOut(**_annexe_payload(annexe))


@router.get("/{requisition_id}/annexes", response_model=list[RequisitionAnnexeOut])
async def list_requisition_annexes(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[RequisitionAnnexeOut]:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    if req_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    res = await db.execute(
        select(RequisitionAnnexe)
        .where(RequisitionAnnexe.requisition_id == rid)
        .order_by(RequisitionAnnexe.upload_date.desc())
    )
    annexes = res.scalars().all()
    return [RequisitionAnnexeOut(**_annexe_payload(a)) for a in annexes]


@router.get("/annexe/{annexe_id}")
async def download_requisition_annexe(
    annexe_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        aid = uuid.UUID(annexe_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid annexe_id")

    res = await db.execute(select(RequisitionAnnexe).where(RequisitionAnnexe.id == aid))
    annexe = res.scalar_one_or_none()
    if not annexe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")
    req_res = await db.execute(
        select(Requisition).where(
            Requisition.id == annexe.requisition_id,
            Requisition.organisation_id == tenant_id,
        )
    )
    if req_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")

    fs_path = _annexe_fs_path(annexe.file_path)
    if not fs_path or not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe file missing")

    return FileResponse(
        fs_path,
        media_type=annexe.file_type or "application/octet-stream",
        filename=annexe.filename,
        headers={"Content-Disposition": f'inline; filename="{annexe.filename}"'},
    )


@router.get("/annexe/{annexe_id}/thumbnail")
async def get_requisition_annexe_thumbnail(
    annexe_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        aid = uuid.UUID(annexe_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid annexe_id")

    res = await db.execute(select(RequisitionAnnexe).where(RequisitionAnnexe.id == aid))
    annexe = res.scalar_one_or_none()
    if not annexe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")
    req_res = await db.execute(
        select(Requisition).where(
            Requisition.id == annexe.requisition_id,
            Requisition.organisation_id == tenant_id,
        )
    )
    if req_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")

    fs_path = _annexe_fs_path(annexe.file_path)
    if not fs_path or not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe file missing")

    name = (annexe.filename or annexe.file_path or "").lower()
    is_image = name.endswith((".png", ".jpg", ".jpeg", ".webp"))
    if is_image:
        try:
            with Image.open(fs_path) as img:
                img.thumbnail((60, 60))
                out = io.BytesIO()
                img.save(out, format="WEBP")
                return Response(content=out.getvalue(), media_type="image/webp")
        except Exception:
            pass

    icon_path = _pdf_icon_path()
    if os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not available")


@router.post("/{requisition_id}/annexe", response_model=RequisitionAnnexeOut, status_code=status.HTTP_201_CREATED)
async def upload_requisition_annexe(
    requisition_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notify: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> RequisitionAnnexeOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    req = req_res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    content_type = (file.content_type or "").lower()
    if content_type not in ANNEXE_ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")

    original_name = file.filename or "annexe"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ANNEXE_ALLOWED_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if len(contents) > MAX_ANNEXE_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier trop volumineux (max 3 Mo)")

    count_res = await db.execute(
        select(func.count(RequisitionAnnexe.id)).where(RequisitionAnnexe.requisition_id == rid)
    )
    existing_count = int(count_res.scalar_one() or 0)
    ref_base = req.reference_numero or f"REQ-{rid}"
    safe_ref = _safe_ref(ref_base)
    index = existing_count + 1
    filename = f"{safe_ref}-annex-{index}{ext}"
    upload_dt = _utcnow()
    target_dir = _tenant_requisition_dir(tenant_uuid, upload_dt.year, upload_dt.month)
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    file_key = f"/uploads/tenants/{tenant_uuid}/requisitions/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"

    annexe = RequisitionAnnexe(
        organisation_id=tenant_id,
        requisition_id=rid,
        file_path=file_key,
        filename=original_name,
        file_type=content_type,
        file_size=len(contents),
        upload_date=upload_dt,
    )
    db.add(annexe)

    await db.commit()
    await db.refresh(annexe)

    try:
        if notify and (req.examen_status or "").upper() == "EXAMINE":
            await _schedule_bureau_notifications(
                db=db,
                background_tasks=background_tasks,
                req=req,
                action_user=user,
            )
    except Exception:
        logger.exception("Failed to schedule requisition notification after annexe upload")

    return RequisitionAnnexeOut(**_annexe_payload(annexe))


@router.post("/{requisition_id}/pdf")
async def upload_requisition_pdf(
    requisition_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notify: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    req = req_res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    content_type = (file.content_type or "").lower()
    if content_type not in PDF_ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")

    original_name = file.filename or "requisition.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in PDF_ALLOWED_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide")

    ref_base = req.reference_numero or req.numero_requisition or f"REQ-{rid}"
    safe_ref = _safe_ref(ref_base)
    filename = f"{safe_ref}-bon.pdf"
    upload_dt = _utcnow()
    target_dir = _tenant_requisition_dir(tenant_uuid, upload_dt.year, upload_dt.month)
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    req.pdf_path = f"/uploads/tenants/{tenant_uuid}/requisitions/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
    req.updated_at = _utcnow()
    await db.commit()
    resolved_pdf_path = _requisition_pdf_fs_path(req.pdf_path)
    logger.info(
        "Requisition official PDF saved requisition_id=%s numero_requisition=%s pdf_path=%s resolved_pdf_path=%s exists=%s",
        req.id,
        req.numero_requisition,
        req.pdf_path,
        resolved_pdf_path,
        bool(resolved_pdf_path) and os.path.exists(resolved_pdf_path),
    )

    if notify:
        try:
            if (req.examen_status or "").upper() != "EXAMINE":
                logger.info("Skipping requisition notification: examen not validated for %s", req.numero_requisition)
                return {"ok": True, "pdf_path": filename, "warning": "Examen non validé pour notification"}

            await _schedule_bureau_notifications(
                db=db,
                background_tasks=background_tasks,
                req=req,
                action_user=user,
            )
        except Exception:
            logger.exception("Failed to schedule requisition notification after pdf upload")

    return {"ok": True, "pdf_path": filename}


@router.post("/parse-pdf", response_model=PdfRequisitionParseResponse, dependencies=[Depends(has_permission("requisitions_ocr"))])
async def parse_requisition_pdf_endpoint(
    file: UploadFile = File(...),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PdfRequisitionParseResponse:
    from app.services.pdf_requisition_parser import parse_requisition_pdf

    content = await file.read()
    parsed = parse_requisition_pdf(content)
    items = parsed["items"]

    numeros = [item["numero_requisition"] for item in items if item.get("numero_requisition")]
    db_map = {}
    if numeros:
        res = await db.execute(
            select(Requisition).where(
                Requisition.numero_requisition.in_(numeros),
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
        db_map = {r.numero_requisition: r for r in res.scalars().all()}

    matched = 0
    conflicts = 0
    missing = 0
    enriched = []
    for item in items:
        numero = item.get("numero_requisition")
        req = db_map.get(numero) if numero else None
        if req is None:
            item["match_status"] = "missing" if numero else "unmatched"
            if numero:
                missing += 1
        else:
            item["db_id"] = str(req.id)
            item["db_montant"] = req.montant_total
            item["db_status"] = req.status
            if item.get("montant") is not None and abs(float(req.montant_total or 0) - float(item["montant"])) > 0.01:
                item["match_status"] = "conflict"
                conflicts += 1
            else:
                item["match_status"] = "found"
                matched += 1
        enriched.append(item)

    return PdfRequisitionParseResponse(
        items=enriched,
        raw_text_excerpt=parsed["raw_text_excerpt"],
        warnings=parsed["warnings"],
        total_items=len(enriched),
        matched=matched,
        conflicts=conflicts,
        missing=missing,
    )


@router.post("/import-pdf", response_model=PdfRequisitionImportResponse, dependencies=[Depends(has_permission("requisitions_ocr"))])
async def import_requisitions_from_pdf(
    payload: PdfRequisitionImportRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PdfRequisitionImportResponse:
    items = payload.items
    if not items:
        return PdfRequisitionImportResponse()

    numeros = [item.numero_requisition for item in items if item.numero_requisition]
    existing_map: dict[str, Requisition] = {}
    if numeros:
        res = await db.execute(
            select(Requisition).where(
                Requisition.numero_requisition.in_(numeros),
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
        existing_map = {r.numero_requisition: r for r in res.scalars().all()}

    codes = set()
    for item in items:
        if item.rubrique:
            match = re.match(r"(\\d+(?:\\.\\d+)*)", item.rubrique.strip())
            if match:
                codes.add(match.group(1))
    budget_map = {}
    if codes:
        res = await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.code.in_(list(codes)),
                BudgetPoste.is_deleted.is_(False),
            )
        )
        budget_map = {b.code: b for b in res.scalars().all()}

    imported = 0
    skipped_existing = 0
    skipped_invalid = 0
    created_ids: list[str] = []

    for item in items:
        if not item.numero_requisition:
            skipped_invalid += 1
            continue
        if item.numero_requisition in existing_map:
            skipped_existing += 1
            continue
        if item.montant is None or item.montant <= 0:
            skipped_invalid += 1
            continue

        req = Requisition(
            numero_requisition=item.numero_requisition,
            organisation_id=tenant_id,
            objet=item.objet or "Import PDF",
            mode_paiement="cash",
            type_requisition="classique",
            status="PENDING_VALIDATION_IMPORT",
            montant_total=item.montant,
            created_by=user.id,
            created_at=_utcnow(),
            updated_at=_utcnow(),
            import_source="PDF_IMPORT_SMART",
        )
        db.add(req)
        await db.flush()

        rubrique = item.rubrique or ""
        code_match = re.match(r"(\\d+(?:\\.\\d+)*)", rubrique.strip())
        budget_line = budget_map.get(code_match.group(1)) if code_match else None
        ligne = LigneRequisition(
            requisition_id=req.id,
            budget_poste_id=budget_line.id if budget_line else None,
            rubrique=rubrique or "Non classé",
            description=item.objet or "Import PDF",
            quantite=1,
            montant_unitaire=item.montant,
            montant_total=item.montant,
            devise="USD",
        )
        db.add(ligne)

        await log_action(
            db,
            user_id=user.id,
            action="REQUISITION_IMPORTED_PDF",
            target_table="requisitions",
            target_id=str(req.id),
            old_value=None,
            new_value={"source": "PDF_IMPORT_SMART"},
            ip_address=get_request_ip(request),
        )

        imported += 1
        created_ids.append(str(req.id))

    await db.commit()
    return PdfRequisitionImportResponse(
        imported=imported,
        skipped_existing=skipped_existing,
        skipped_invalid=skipped_invalid,
        created_ids=created_ids,
    )


@router.post("/{requisition_id}/validate-import", response_model=RequisitionOut)
async def validate_imported_requisition(
    requisition_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(
        select(Requisition).where(
            Requisition.id == rid,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    await require_requisition_lines(db, req)
    if (req.examen_status or "").upper() != "EXAMINE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Examen requis avant validation")

    old_status = req.status
    if old_status != "PENDING_VALIDATION_IMPORT":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Requisition not pending import validation")

    req.status = "EN_ATTENTE_COMMISSION"
    req.updated_at = _utcnow()
    _record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
    )
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_IMPORT_VALIDATED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={"status": req.status},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)


@router.get("/{requisition_id}/annexe/debug")
async def debug_requisition_annexe(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    if req_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    res = await db.execute(select(RequisitionAnnexe).where(RequisitionAnnexe.requisition_id == rid))
    annexe = res.scalar_one_or_none()
    if not annexe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")

    fs_path = _annexe_fs_path(annexe.file_path)
    exists = bool(fs_path) and os.path.exists(fs_path)
    size = None
    if exists:
        try:
            size = os.path.getsize(fs_path)
        except OSError:
            size = None

    return {
        "requisition_id": str(annexe.requisition_id),
        "file_path": annexe.file_path,
        "filename": annexe.filename,
        "file_type": annexe.file_type,
        "file_size_db": annexe.file_size,
        "filesystem_path": fs_path,
        "exists": exists,
        "filesystem_size": size,
    }


@router.post("", response_model=RequisitionOut)
async def create_requisition(
    payload: RequisitionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_any_permission(["can_create_requisition", "menu_services"])),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    # Delegate creation logic to service
    req = await create_requisition_logic(
        db=db,
        payload=payload,
        user=user,
        tenant_id=tenant_id,
        request=request,
    )

    return _requisition_out(req)


@router.put("/{requisition_id}", response_model=RequisitionOut)
async def update_requisition(
    requisition_id: str,
    payload: RequisitionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    try:
        req = await update_requisition_logic(
            db=db,
            requisition_id=rid,
            payload=payload,
            user=user,
            tenant_id=tenant_id,
            request=request,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erreur lors de l'enregistrement de la sortie de fonds pour la réquisition %s", rid)
        raise

    return _requisition_out(req)


@router.patch("/{requisition_id}/sign", response_model=RequisitionOut)
async def sign_commission_requisition(
    requisition_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req = await sign_commission_requisition_logic(
        db=db,
        requisition_id=rid,
        user=user,
        tenant_id=tenant_id,
    )
    return _requisition_out(req)


@router.post("/{requisition_id}/submit-examen", response_model=RequisitionOut)
async def submit_requisition_examen(
    requisition_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(
        select(Requisition).where(
            Requisition.id == rid,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = req_res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    has_requisition_permission = (
        await user_has_permission(db, user, "requisitions")
        or await user_has_permission(db, user, "can_create_requisition")
        or await user_has_permission(db, user, "menu_requisitions")
    )
    if not has_requisition_permission and not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if req.service_id is None or req.service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réquisition hors de vos commissions")

    req = await submit_requisition_examen_logic(
        db=db,
        requisition_id=rid,
        tenant_id=tenant_id,
    )
    try:
        await _schedule_examen_submission_notification(
            db=db,
            background_tasks=background_tasks,
            req=req,
            action_user=user,
        )
    except Exception:
        logger.exception("Failed to schedule examen submission notification for requisition %s", req.numero_requisition)

    return _requisition_out(req)


@router.post("/{requisition_id}/validate-examen", response_model=RequisitionWithUserOut)
async def validate_requisition_examen(
    requisition_id: str,
    payload: RequisitionExamenPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Any:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req = await validate_requisition_examen_logic(
        db=db,
        requisition_id=rid,
        payload=payload,
        user=user,
        tenant_id=tenant_id,
    )

    try:
        await _schedule_bureau_notifications(db=db, background_tasks=background_tasks, req=req, action_user=user)
    except Exception as exc:
        logger.exception("Failed to prepare bureau notifications for requisition %s", req.numero_requisition)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Impossible de preparer le PDF officiel pour l'envoi email: {exc}",
        ) from exc
    return await _get_requisition_with_users(db, req, tenant_id)


@router.post("/{requisition_id}/reject-examen", response_model=RequisitionWithUserOut)
async def reject_requisition_examen(
    requisition_id: str,
    payload: RequisitionExamenPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Any:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req = await reject_requisition_examen_logic(
        db=db,
        requisition_id=rid,
        payload=payload,
        user=user,
        tenant_id=tenant_id,
    )
    return await _get_requisition_with_users(db, req, tenant_id)


@router.post("/{requisition_id}/validate", response_model=RequisitionOut)
async def validate_requisition(
    requisition_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_verify_technical")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req = await validate_requisition_logic(
        db=db,
        requisition_id=rid,
        user=user,
        tenant_id=tenant_id,
        request=request,
    )

    # Trigger notifications after DB commit (handled by service)
    try:
        ns = await get_system_settings(db, tenant_id)
        smtp_cfg = resolve_smtp_config(ns)
        if smtp_cfg and ns and ns.email_validation_final:
                official_pdf_path, attachment_paths = await _collect_requisition_email_attachments(db, req)
                org_res = await db.execute(
                    select(Organisation.nom, Organisation.slug).where(Organisation.id == tenant_id).limit(1)
                )
                org_row = org_res.one_or_none()
                org_name = org_row[0] if org_row else None
                org_slug = org_row[1] if org_row else None
                background_tasks.add_task(
                    send_requisition_workflow_email,
                    smtp_host=smtp_cfg.host,
                    smtp_port=smtp_cfg.port,
                    smtp_user=smtp_cfg.user,
                    smtp_password=smtp_cfg.password,
                    sender=smtp_cfg.sender,
                    recipient=ns.email_validation_final,
                    subject=f"✅ Réquisition à valider - {req.numero_requisition}",
                    title="Validation finale requise",
                    body_lines=[
                        "Chers Membres du Bureau,",
                        "Une réquisition a reçu l'avis technique et attend votre validation finale.",
                        f"Référence : {req.numero_requisition}",
                        f"Objet : {req.objet or '-'}",
                        f"Montant : {float(req.montant_total or 0):,.2f} $",
                        "Merci de vous connecter pour valider.",
                    ],
                    brand_name="ONEC",
                    organisation_name=org_name,
                    organisation_slug=org_slug,
                    official_pdf_path=official_pdf_path,
                    attachment_paths=attachment_paths,
                )
    except Exception:
        logger.exception("Failed to send workflow email after requisition technical validation")

    return _requisition_out(req)


@router.post("/{requisition_id}/vise", response_model=RequisitionOut)
async def vise_requisition(
    requisition_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(has_permission("can_validate_final")),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req = await vise_requisition_logic(
        db=db,
        requisition_id=rid,
        user=user,
        tenant_id=tenant_id,
        request=request,
    )

    # Trigger notifications after DB commit (handled by service)
    try:
        ns = await get_system_settings(db, tenant_id)
        smtp_cfg = resolve_smtp_config(ns)
        if ns:
            official_pdf_path, attachment_paths = await _collect_requisition_email_attachments(db, req)
            org_name = None
            if (
                (smtp_cfg and ns.email_tresorier)
                or (ns.whatsapp_api_url and ns.whatsapp_agents)
            ):
                org_res = await db.execute(
                    select(Organisation.nom, Organisation.slug).where(Organisation.id == tenant_id).limit(1)
                )
                org_row = org_res.one_or_none()
                org_name = org_row[0] if org_row else None
                org_slug = org_row[1] if org_row else None
            if smtp_cfg and ns.email_tresorier:
                background_tasks.add_task(
                    send_requisition_workflow_email,
                    smtp_host=smtp_cfg.host,
                    smtp_port=smtp_cfg.port,
                    smtp_user=smtp_cfg.user,
                    smtp_password=smtp_cfg.password,
                    sender=smtp_cfg.sender,
                    recipient=ns.email_tresorier,
                    subject=f"💰 Réquisition validée - {req.numero_requisition}",
                    title="Mise en paiement",
                    body_lines=[
                        "Chers Membres du Bureau,",
                        "Une réquisition a été validée et peut être mise en paiement.",
                        f"Référence : {req.numero_requisition}",
                        f"Objet : {req.objet or '-'}",
                        f"Montant : {float(req.montant_total or 0):,.2f} $",
                        "Veuillez procéder au décaissement selon le workflow.",
                    ],
                    brand_name="ONEC",
                    organisation_name=org_name,
                    organisation_slug=org_slug,
                    official_pdf_path=official_pdf_path,
                    attachment_paths=attachment_paths,
                )
    except Exception:
        logger.exception("Failed to send workflow notifications after final validation")

    # WhatsApp : délibérément HORS du `try` ci-dessus. La préparation de l'email
    # génère et joint des PDF ; si elle échoue, le Bureau doit quand même être
    # prévenu. Les deux canaux sont désormais indépendants l'un de l'autre, et
    # aucun des deux ne peut faire échouer le visa, déjà committé par
    # `vise_requisition_logic`.
    await _notify_requisition_approuvee_whatsapp(
        db,
        background_tasks,
        req=req,
        tenant_id=tenant_id,
        validateur=user,
    )

    return _requisition_out(req)

@router.post("/{requisition_id}/reject", response_model=RequisitionOut)
async def reject_requisition(
    requisition_id: str,
    payload: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(
        select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    old_status = req.status
    motif_rejet = (payload.get("motif_rejet") or "").strip()
    if not motif_rejet:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Motif de rejet requis")
    req.status = "REJETEE"
    req.motif_rejet = motif_rejet
    _record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
        comment=req.motif_rejet,
    )
    req.validee_par = user.id
    req.validee_le = _utcnow()
    req.approuvee_par = None
    req.approuvee_le = None
    req.payee_par = None
    req.payee_le = None
    req.updated_at = _utcnow()
    # Une réquisition rejetée ne gèle plus de budget : le crédit retourne au
    # poste (cf. app/services/budget_engagement.py).
    await resynchroniser_engagement_requisition(db, req)
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_REJECTED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={"status": req.status, "motif_rejet": req.motif_rejet},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(req)
    await _check_cash_watchdog(db=db, user=user, request=request, requisition_id=str(req.id))
    return _requisition_out(req)


@router.post("/{requisition_id}/soft-delete", response_model=RequisitionOut)
async def soft_delete_requisition(
    requisition_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(
        select(Requisition).where(
            Requisition.id == rid,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    if (req.examen_status or "").upper() != "NON_EXAMINE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suppression impossible après soumission à l'examen",
        )

    dossier: DossierRequisition | None = None
    if req.dossier_id:
        dossier_res = await db.execute(select(DossierRequisition).where(DossierRequisition.id == req.dossier_id))
        dossier = dossier_res.scalar_one_or_none()
        if dossier and (dossier.status or "").upper() != "BROUILLON":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Suppression impossible : le dossier a déjà été soumis à l'examen",
            )

    req.is_deleted = True
    req.deleted_at = _utcnow()
    req.deleted_by = user.id
    req.updated_at = _utcnow()
    deleted_dossier_id = req.dossier_id
    req.dossier_id = None

    if deleted_dossier_id:
        remaining_res = await db.execute(
            select(Requisition).where(
                Requisition.dossier_id == deleted_dossier_id,
                Requisition.id != req.id,
                Requisition.is_deleted.is_(False),
            )
        )
        remaining = remaining_res.scalars().all()
        if len(remaining) == 1:
            lone = remaining[0]
            lone.dossier_id = None
            lone.examen_status = "NON_EXAMINE"
            if dossier:
                await db.delete(dossier)
        elif len(remaining) == 0 and dossier:
            await db.delete(dossier)

    # Réquisition supprimée : elle sort du calcul de l'engagement.
    await resynchroniser_engagement_requisition(db, req)

    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_SOFT_DELETED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"is_deleted": False},
        new_value={"is_deleted": True},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)


@router.post("/{requisition_id}/restore", response_model=RequisitionOut)
async def restore_requisition(
    requisition_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(
        select(Requisition).where(
            Requisition.id == rid,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(True),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    req.is_deleted = False
    req.deleted_at = None
    req.deleted_by = None
    req.updated_at = _utcnow()
    # Restaurée, elle réintègre le calcul de l'engagement si son état d'examen
    # l'y ramène.
    await resynchroniser_engagement_requisition(db, req)
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_RESTORED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"is_deleted": True},
        new_value={"is_deleted": False},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)
