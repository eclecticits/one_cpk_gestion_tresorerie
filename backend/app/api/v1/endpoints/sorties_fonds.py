from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
import logging
import os
import re
from typing import Any
import uuid as uuid_lib
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status, Request
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_tenant_id,
    get_current_tenant_uuid,
    require_roles,
    has_permission,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.cloture_caisse import ClotureCaisse
from app.models.caisse_centrale import CaisseCentrale
from app.models.print_settings import PrintSettings
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.compte_bancaire import CompteBancaire
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.user import User
from app.models.service import Service
from app.models.remboursement_transport import RemboursementTransport
from app.models.rbac import Permission, role_permissions
from app.schemas.requisition import RequisitionOut, RequisitionWithUserOut
from app.schemas.sortie_fonds import (
    SortieFondsCreate,
    SortieFondsOut,
    SortiesFondsListResponse,
    SortieFondsStatusUpdate,
    SortieFondsPaymentRejectPayload,
)
from app.services.document_sequences import generate_document_number
from app.services.mailer import send_sortie_notification
from app.services.email_config import resolve_smtp_config
from app.services.system_settings_service import get_system_settings
from app.services.audit_service import get_request_ip, log_action
from app.services.requisition_service import record_status_history, reject_requisition_at_payment_logic

router = APIRouter()


async def _can_force_budget_overrun(db: AsyncSession, user: User, tenant_id: int) -> bool:
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        return False
    if not settings.budget_block_overrun:
        return True
    roles = {r.strip().lower() for r in (settings.budget_force_roles or "").split(",") if r.strip()}
    return bool(user.role) and user.role.lower() in roles
logger = logging.getLogger("onec_cpk_api.sorties_fonds")

REQUISITION_STATUTS_VALIDES = ("APPROUVEE", "EN_DECAISSEMENT")
MAX_ANNEXE_SIZE = 3 * 1024 * 1024
ANNEXE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ANNEXE_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT
CANAL_PAIEMENT = {"CAISSE", "BANQUE"}


async def _user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    if not user.role_id:
        return False
    res = await db.execute(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
        .where(Permission.code == permission_code)
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


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


def _tenant_sortie_dir(tenant_uuid: str, year: int, month: int) -> str:
    return os.path.abspath(
        os.path.join(UPLOAD_ROOT, "tenants", str(tenant_uuid), "sorties-fonds", f"{year:04d}", f"{month:02d}")
    )


def _sortie_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    return os.path.abspath(os.path.join(UPLOAD_ROOT, "sorties-fonds", os.path.basename(file_path)))


def _sortie_annexe_fs_path(path_value: str | None) -> str:
    if not path_value:
        return ""
    if path_value.startswith("/uploads/"):
        rel_path = path_value.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    return os.path.abspath(os.path.join(UPLOAD_ROOT, "sorties-fonds", "annexes", path_value))


def _safe_ref(value: str) -> str:
    if not value:
        return "SORTIE"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return safe.strip("._-") or "SORTIE"


async def _save_sortie_annexes(
    attachments: list[UploadFile],
    safe_ref: str,
    *,
    tenant_uuid: str,
) -> list[str]:
    filenames: list[str] = []
    for attachment in attachments:
        content_type = (attachment.content_type or "").lower()
        if content_type and content_type not in ANNEXE_ALLOWED_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")
        original_name = attachment.filename or "annexe"
        ext = os.path.splitext(original_name)[1].lower()
        if ext and ext not in ANNEXE_ALLOWED_EXT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")
        contents = await attachment.read()
        if len(contents) > MAX_ANNEXE_SIZE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier trop volumineux (max 3 Mo)")
        upload_dt = datetime.now(timezone.utc)
        target_dir = _tenant_sortie_dir(tenant_uuid, upload_dt.year, upload_dt.month)
        os.makedirs(target_dir, exist_ok=True)
        filename = f"{safe_ref}-annex-{uuid_lib.uuid4().hex}{ext or '.pdf'}"
        dest_path = os.path.join(target_dir, filename)
        with open(dest_path, "wb") as f:
            f.write(contents)
        filenames.append(
            f"/uploads/tenants/{tenant_uuid}/sorties-fonds/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
        )
    return filenames


def _user_info(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "prenom": user.prenom,
        "nom": user.nom,
        "email": user.email,
    }


def _requisition_out(
    req: Requisition,
    *,
    validateur: User | None = None,
    approbateur: User | None = None,
    remboursement_transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "reference_numero": req.reference_numero,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": req.montant_total or 0,
        "service_id": req.service_id,
        "compte_bancaire_id": req.compte_bancaire_id,
        "status": req.status,
        "statut": req.status,
        "created_by": str(req.created_by) if req.created_by else None,
        "validee_par": str(req.validee_par) if req.validee_par else None,
        "validee_le": req.validee_le,
        "approuvee_par": str(req.approuvee_par) if req.approuvee_par else None,
        "approuvee_le": req.approuvee_le,
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
        "remboursement_transport": remboursement_transport,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
    }
    if validateur:
        base["validateur"] = _user_info(validateur)
    if approbateur:
        base["approbateur"] = _user_info(approbateur)
    return base


def _sortie_out(
    sortie: SortieFonds,
    requisition: Requisition | None = None,
    *,
    creator: User | None = None,
    canceller: User | None = None,
    programme_par: User | None = None,
    validateur: User | None = None,
    approbateur: User | None = None,
    remboursement_transport: dict[str, Any] | None = None,
) -> SortieFondsOut:
    return SortieFondsOut(
        id=str(sortie.id),
        type_sortie=sortie.type_sortie,
        requisition_id=str(sortie.requisition_id) if sortie.requisition_id else None,
        rubrique_code=sortie.rubrique_code,
        budget_poste_id=sortie.budget_poste_id,
        budget_poste_code=sortie.budget_poste_code,
        budget_poste_libelle=sortie.budget_poste_libelle,
        service_id=sortie.service_id,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        devise=sortie.devise,
        canal=sortie.canal,
        compte_bancaire_id=sortie.compte_bancaire_id,
        reference_numero=sortie.reference_numero,
        pdf_path=sortie.pdf_path,
        statut=sortie.statut or "VALIDE",
        motif_annulation=sortie.motif_annulation,
        annulee_le=sortie.annulee_le,
        annulee_par_id=str(sortie.annulee_par_id) if sortie.annulee_par_id else None,
        annulation_ip=sortie.annulation_ip,
        ancien_statut=sortie.ancien_statut,
        exchange_rate_snapshot=sortie.exchange_rate_snapshot,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
        annexes=sortie.annexes,
        created_by=str(sortie.created_by) if sortie.created_by else None,
        created_by_user=_user_info(creator),
        programme_par_id=str(sortie.programme_par_id) if sortie.programme_par_id else None,
        programme_par_user=_user_info(programme_par),
        annulee_par_user=_user_info(canceller),
        created_at=sortie.created_at,
        is_reconciled=sortie.is_reconciled,
        reconciled_at=sortie.reconciled_at,
        reconciled_by_id=str(sortie.reconciled_by_id) if sortie.reconciled_by_id else None,
        bank_statement_ref=sortie.bank_statement_ref,
        requisition=_requisition_out(
            requisition,
            validateur=validateur,
            approbateur=approbateur,
            remboursement_transport=remboursement_transport,
        ) if requisition else None,
    )


def _remboursement_transport_payload(remboursement: RemboursementTransport | None) -> dict[str, Any] | None:
    if remboursement is None:
        return None
    return {
        "id": str(remboursement.id),
        "numero_remboursement": remboursement.numero_remboursement,
        "reference_numero": remboursement.reference_numero,
        "instance": remboursement.instance,
        "date_reunion": remboursement.date_reunion.isoformat() if remboursement.date_reunion else None,
        "lieu": remboursement.lieu,
    }


async def _resolve_service(service_id: int, db: AsyncSession) -> Service:
    res = await db.execute(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id invalide")
    return service


def _parse_order(order: str | None):
    if not order:
        return SortieFonds.date_paiement.desc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "date_paiement": SortieFonds.date_paiement,
        "created_at": SortieFonds.created_at,
        "montant_paye": SortieFonds.montant_paye,
    }
    col = column_map.get(field)
    if col is None:
        return SortieFonds.date_paiement.desc()
    return col.desc() if direction.lower() == "desc" else col.asc()


async def _get_or_create_caisse(db: AsyncSession, tenant_id: int) -> CaisseCentrale:
    res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
    caisse = res.scalar_one_or_none()
    if caisse is None:
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
        caisse = res.scalar_one()
    return caisse


async def _get_last_cloture_date(db: AsyncSession) -> datetime | None:
    res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1)
    )
    last = res.scalar_one_or_none()
    if not last or not last.date_cloture:
        return None
    last_dt = last.date_cloture
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return last_dt


@router.get("", response_model=list[SortieFondsOut] | SortiesFondsListResponse)
async def list_sorties_fonds(
    include: str | None = Query(default=None, description="Relations à inclure (requisition)"),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    type_sortie: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    canal: str | None = Query(default=None),
    compte_bancaire_id: int | None = Query(default=None),
    statut: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    requisition_numero: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    order: str | None = Query(default=None, description="Ex: date_paiement.desc"),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    include_summary: bool = Query(default=False),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SortieFondsOut] | SortiesFondsListResponse:
    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_requisition = "requisition" in include_parts or bool(requisition_numero)
    conditions = [
        SortieFonds.organisation_id == tenant_id,
        or_(
            SortieFonds.requisition_id.is_(None),
            Requisition.status.in_(REQUISITION_STATUTS_VALIDES),
        )
    ]
    can_view_cancelled = await _user_has_permission(db, user, "view_cancelled_financial_operations")

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        conditions.append(SortieFonds.date_paiement >= start_dt)
    if end_dt:
        conditions.append(SortieFonds.date_paiement <= end_dt)

    if type_sortie:
        conditions.append(SortieFonds.type_sortie == type_sortie)
    if mode_paiement:
        conditions.append(SortieFonds.mode_paiement == mode_paiement)
    if canal:
        conditions.append(SortieFonds.canal == canal.upper())
    if compte_bancaire_id:
        conditions.append(SortieFonds.compte_bancaire_id == compte_bancaire_id)
    if statut:
        statut_value = statut.strip().upper()
        if statut_value == "ALL":
            if not can_view_cancelled:
                raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
        elif statut_value == "VALIDE":
            conditions.append(
                (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
            )
        else:
            if statut_value == "ANNULEE" and not can_view_cancelled:
                raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
            conditions.append(SortieFonds.statut == statut_value)
    else:
        conditions.append((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
    if reference:
        conditions.append(SortieFonds.reference.ilike(f"%{reference}%"))
    if requisition_id:
        try:
            req_uid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")
        conditions.append(SortieFonds.requisition_id == req_uid)

    if requisition_numero:
        conditions.append(Requisition.numero_requisition.ilike(f"%{requisition_numero}%"))
        conditions.append(Requisition.organisation_id == tenant_id)

    if include_requisition:
        query = select(SortieFonds, Requisition).outerjoin(
            Requisition, SortieFonds.requisition_id == Requisition.id
        )
    else:
        query = select(SortieFonds).outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)

    if conditions:
        query = query.where(*conditions)

    query = query.order_by(_parse_order(order)).offset(offset).limit(limit)

    result = await db.execute(query)
    rows = result.all() if include_requisition else result.scalars().all()
    
    users_map: dict[uuid.UUID, User] = {}
    if include_requisition:
        user_ids: set[uuid.UUID] = set()
        requisition_ids: set[uuid.UUID] = set()
        for row in rows:
            sortie = row[0]
            req = row[1]
            if sortie and sortie.created_by:
                user_ids.add(sortie.created_by)
            if sortie and sortie.annulee_par_id:
                user_ids.add(sortie.annulee_par_id)
            if sortie and sortie.programme_par_id:
                user_ids.add(sortie.programme_par_id)
            if req:
                requisition_ids.add(req.id)
                if req.validee_par: user_ids.add(req.validee_par)
                if req.approuvee_par: user_ids.add(req.approuvee_par)
    else:
        user_ids = {
            user_id
            for sortie in rows
            for user_id in (sortie.created_by, sortie.annulee_par_id, sortie.programme_par_id)
            if user_id
        }
        requisition_ids = set()
        
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id))
        users_map = {u.id: u for u in u_res.scalars().all()}

    remboursements_map: dict[uuid.UUID, dict[str, Any]] = {}
    if requisition_ids:
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id.in_(list(requisition_ids)))
        )
        remboursements_map = {
            remb.requisition_id: _remboursement_transport_payload(remb)
            for remb in remb_res.scalars().all()
            if remb.requisition_id
        }

    if include_requisition:
        items = [
            _sortie_out(
                sortie, 
                req, 
                creator=users_map.get(sortie.created_by) if sortie and sortie.created_by else None,
                canceller=users_map.get(sortie.annulee_par_id) if sortie and sortie.annulee_par_id else None,
                programme_par=users_map.get(sortie.programme_par_id) if sortie and sortie.programme_par_id else None,
                validateur=users_map.get(req.validee_par) if req and req.validee_par else None,
                approbateur=users_map.get(req.approuvee_par) if req and req.approuvee_par else None,
                remboursement_transport=remboursements_map.get(req.id) if req else None,
            ) 
            for sortie, req in rows
        ]
    else:
        items = [
            _sortie_out(
                sortie,
                creator=users_map.get(sortie.created_by) if sortie.created_by else None,
                canceller=users_map.get(sortie.annulee_par_id) if sortie.annulee_par_id else None,
                programme_par=users_map.get(sortie.programme_par_id) if sortie.programme_par_id else None,
            )
            for sortie in rows
        ]

    if not include_summary:
        return items

    count_query = select(func.count()).select_from(SortieFonds)
    count_query = count_query.outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
    if conditions:
        count_query = count_query.where(*conditions)
    total_count = int((await db.execute(count_query)).scalar_one() or 0)

    # Condition de statut appliquée aux totaux (uniquement les opérations valides
    # sauf demande explicite d'un autre statut).
    if statut and statut.strip().upper() not in ("ALL", "VALIDE"):
        statut_cond = SortieFonds.statut == statut.strip().upper()
    else:
        statut_cond = (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")

    # Transferts internes caisse <-> banque (versement, approvisionnement) : à
    # distinguer des vraies dépenses dans les totaux.
    transfert_types = ("versement_banque", "approvisionnement_caisse")

    def _sum_query(extra=None):
        q = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).select_from(
            SortieFonds
        ).outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
        if conditions:
            q = q.where(*conditions)
        q = q.where(statut_cond)
        if extra is not None:
            q = q.where(extra)
        return q

    total_montant_paye = (await db.execute(_sum_query())).scalar_one() or 0
    total_transferts_internes = (
        await db.execute(_sum_query(SortieFonds.type_sortie.in_(transfert_types)))
    ).scalar_one() or 0
    total_depenses_reelles = (
        await db.execute(_sum_query(SortieFonds.type_sortie.notin_(transfert_types)))
    ).scalar_one() or 0

    return SortiesFondsListResponse(
        items=items,
        total=total_count,
        total_montant_paye=total_montant_paye,
        total_depenses_reelles=total_depenses_reelles,
        total_transferts_internes=total_transferts_internes,
    )


async def _to_budget_currency(
    db: AsyncSession,
    tenant_id: int,
    montant: Decimal | float | None,
    devise: str | None,
    *,
    exchange_rate_snapshot: Decimal | float | None = None,
) -> Decimal:
    """Convertit un montant depuis sa devise vers la DEVISE DE BASE du budget
    (USD : les postes budgétaires n'ont pas de devise propre). Évite de mélanger
    du CDF avec des plafonds/cumuls exprimés en USD.

    Taux exprimés en « unités de devise pour 1 USD » (comme le frontend). Si le
    taux nécessaire est manquant, renvoie le montant tel quel (best-effort,
    comportement historique).
    """
    m = Decimal(montant or 0)
    d = (devise or "USD").upper()
    if d == "USD" or m == 0:
        return m
    if exchange_rate_snapshot is not None:
        try:
            snapshot_rate = Decimal(str(exchange_rate_snapshot or 0))
        except Exception:
            snapshot_rate = Decimal(0)
        if snapshot_rate > 0:
            return m / snapshot_rate
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    ps = res.scalar_one_or_none()
    rate_raw = {
        "CDF": getattr(ps, "exchange_rate_cdf", 0),
        "EUR": getattr(ps, "exchange_rate_eur", 0),
        "XOF": getattr(ps, "exchange_rate_xof", 0),
    }.get(d, 0) if ps is not None else 0
    try:
        rate = Decimal(str(rate_raw or 0))
    except Exception:
        rate = Decimal(0)
    return (m / rate) if rate > 0 else m


async def _assert_budget_rate(db: AsyncSession, tenant_id: int, devise: str | None) -> None:
    """Bloque l'imputation budgétaire d'une sortie en devise étrangère si aucun
    taux de change n'est configuré (sinon la conversion vers l'USD serait fausse).
    """
    d = (devise or "USD").upper()
    if d == "USD":
        return
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    ps = res.scalar_one_or_none()
    rate_raw = {
        "CDF": getattr(ps, "exchange_rate_cdf", 0),
        "EUR": getattr(ps, "exchange_rate_eur", 0),
        "XOF": getattr(ps, "exchange_rate_xof", 0),
    }.get(d, 0) if ps is not None else 0
    try:
        rate = float(rate_raw or 0)
    except (TypeError, ValueError):
        rate = 0
    if rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Taux de change requis pour imputer une sortie en {d} sur un poste "
                "budgétaire. Configurez-le dans les réglages avant de valider."
            ),
        )


@router.post("", response_model=SortieFondsOut, status_code=status.HTTP_201_CREATED)
async def create_sortie_fonds(
    payload: SortieFondsCreate,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    requisition_uid: uuid.UUID | None = None
    if payload.requisition_id:
        try:
            requisition_uid = payload.requisition_id
            if not isinstance(requisition_uid, uuid.UUID):
                requisition_uid = uuid.UUID(str(requisition_uid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")

    date_paiement: datetime | None = None
    if payload.date_paiement:
        if isinstance(payload.date_paiement, datetime):
            date_paiement = payload.date_paiement
        else:
            parsed = _parse_datetime(str(payload.date_paiement))
            if parsed is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date_paiement")
            date_paiement = parsed
    if date_paiement is None:
        date_paiement = datetime.now(timezone.utc)

    canal = (payload.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")
    devise = (payload.devise or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    # --- Versement à la banque : transfert interne caisse -> banque.
    # Ce n'est PAS une dépense : pas de service, pas de bénéficiaire externe,
    # pas d'imputation budgétaire. La caisse est débitée, la banque créditée.
    is_versement_banque = (payload.type_sortie or "").lower() == "versement_banque"
    # --- Approvisionnement de la caisse : transfert inverse banque -> caisse.
    # Retrait d'espèces du compte bancaire pour alimenter la caisse (petites
    # dépenses). Pas une dépense : pas de service ni d'imputation budgétaire.
    is_appro_caisse = (payload.type_sortie or "").lower() == "approvisionnement_caisse"
    if is_appro_caisse:
        canal = "BANQUE"  # l'argent sort du compte bancaire
        if payload.compte_bancaire_id is None:
            raise HTTPException(
                status_code=400,
                detail="Compte bancaire source requis pour approvisionner la caisse",
            )
        if not (payload.beneficiaire or "").strip():
            payload.beneficiaire = "Caisse centrale"
    compte_bancaire = None
    compte_destination = None
    if is_versement_banque:
        canal = "CAISSE"  # l'argent sort physiquement de la caisse
        if payload.compte_bancaire_id is None:
            raise HTTPException(
                status_code=400,
                detail="Compte bancaire de destination requis pour un versement à la banque",
            )
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte_destination = res.scalar_one_or_none()
        if compte_destination is None or compte_destination.is_active is False:
            raise HTTPException(status_code=400, detail="Compte de destination invalide")
        if (compte_destination.account_type or "BANK").upper() != "BANK":
            raise HTTPException(
                status_code=400,
                detail="La destination d'un versement doit être un compte bancaire (pas une caisse)",
            )
        if (compte_destination.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="Devise incompatible avec le compte de destination")
        if not (payload.beneficiaire or "").strip():
            banque_nom = getattr(getattr(compte_destination, "banque", None), "nom", None)
            payload.beneficiaire = banque_nom or compte_destination.intitule or "Banque"
    elif payload.compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None or compte_bancaire.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
        if canal == "BANQUE" and (compte_bancaire.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if canal == "CAISSE" and (compte_bancaire.account_type or "").upper() != "CASH":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if not is_versement_banque and canal == "BANQUE" and payload.compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")


    montant_paye = payload.montant_paye
    # Garde-fou : un montant nul ou négatif créditerait la trésorerie au lieu
    # de la débiter (défense en profondeur, en plus de la contrainte du schéma).
    if montant_paye is None or Decimal(montant_paye) <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant doit être strictement positif")
    service_id: int | None = None
    ordre: OrdreDecaissement | None = None
    # Répartition multi-postes portée par l'ordre de décaissement (le cas échéant).
    ordre_postes: list[tuple[int, Decimal]] = []
    multi_poste = False
    req: Requisition | None = None

    # --- Sortie directe (sans réquisition) : la caisse ne fait qu'exécuter un
    # ordre programmé au préalable par un utilisateur disposant de
    # can_direct_disbursement (plafond 100 USD contrôlé à la programmation).
    if (payload.type_sortie or "").lower() == "sortie_directe":
        if payload.requisition_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Une sortie directe ne peut pas référencer une réquisition",
            )
        if payload.ordre_decaissement_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Sortie directe : la caisse exécute uniquement un ordre programmé "
                    "par un utilisateur habilité (can_direct_disbursement)"
                ),
            )
        ordre_res = await db.execute(
            select(OrdreDecaissement)
            .where(
                OrdreDecaissement.id == payload.ordre_decaissement_id,
                OrdreDecaissement.organisation_id == tenant_id,
                OrdreDecaissement.requisition_id.is_(None),
            )
            .with_for_update()
        )
        ordre = ordre_res.scalar_one_or_none()
        if ordre is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ordre de sortie directe introuvable",
            )
        if ordre.statut != "AUTORISE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet ordre de sortie directe a déjà été payé ou annulé",
            )
        # Verrouillage : montant, bénéficiaire et devise proviennent de l'ordre
        if payload.montant_paye is not None and Decimal(payload.montant_paye) != Decimal(ordre.montant or 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Montant différent de l'ordre de sortie directe autorisé",
            )
        payload.beneficiaire = ordre.beneficiaire
        devise = (ordre.devise or "USD").upper()
        if compte_bancaire is not None and (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Devise de l'ordre incompatible avec le compte sélectionné",
            )
        montant_paye = ordre.montant
        # Service et poste budgétaire définis à la programmation : ils sont
        # verrouillés côté caisse (comme pour une réquisition mono-poste).
        if ordre.service_id is not None:
            if payload.service_id is not None and int(payload.service_id) != int(ordre.service_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Service différent de la sortie directe programmée",
                )
            payload.service_id = ordre.service_id
        lignes_ordre = ordre.lignes or []
        postes_ordre = sorted({
            int(ligne["budget_poste_id"])
            for ligne in lignes_ordre
            if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
        })
        if len(postes_ordre) == 1:
            if payload.budget_poste_id is not None and int(payload.budget_poste_id) != postes_ordre[0]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Poste budgétaire verrouillé par la sortie directe programmée",
                )
            payload.budget_poste_id = postes_ordre[0]
        ordre_postes = [
            (int(ligne["budget_poste_id"]), Decimal(str(ligne.get("montant", ligne.get("montant_total")) or 0)))
            for ligne in (ordre.lignes or [])
            if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
        ]
        multi_poste = len({pid for pid, _ in ordre_postes}) > 1
    if requisition_uid:
        req_res = await db.execute(
            select(Requisition)
            .where(
                Requisition.id == requisition_uid,
                Requisition.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        req = req_res.scalar_one_or_none()
        if req is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        allowed_statuses = {"APPROUVEE", "EN_DECAISSEMENT"}
        if req.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "La réquisition doit être validée techniquement avant la sortie de fonds "
                    "et ne doit pas être déjà payée"
                ),
            )
        if req.status == "EN_DECAISSEMENT" and not bool(getattr(req, "decaissement_progressif", False)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Réquisition classique déjà en cours de paiement",
            )

        # --- Réquisition à décaissement progressif : la sortie passe
        # obligatoirement par un ordre de décaissement autorisé par le demandeur.
        if bool(getattr(req, "decaissement_progressif", False)):
            if payload.ordre_decaissement_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Réquisition à décaissement progressif : la sortie de fonds requiert "
                        "un ordre de décaissement autorisé par le demandeur"
                    ),
                )
            ordre_res = await db.execute(
                select(OrdreDecaissement)
                .where(
                    OrdreDecaissement.id == payload.ordre_decaissement_id,
                    OrdreDecaissement.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            ordre = ordre_res.scalar_one_or_none()
            if ordre is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ordre de décaissement introuvable")
            if ordre.requisition_id != req.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="L'ordre de décaissement ne correspond pas à cette réquisition",
                )
            if ordre.statut != "AUTORISE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cet ordre de décaissement a déjà été payé ou annulé",
                )
            # Verrouillage : montant, bénéficiaire et devise proviennent de l'ordre
            if payload.montant_paye is not None and Decimal(payload.montant_paye) != Decimal(ordre.montant or 0):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Montant différent de l'ordre de décaissement autorisé",
                )
            payload.beneficiaire = ordre.beneficiaire
            devise = (ordre.devise or "USD").upper()
            if compte_bancaire is not None and (compte_bancaire.devise or "").upper() != devise:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Devise de l'ordre incompatible avec le compte bancaire",
                )
            ordre_postes = [
                (int(ligne["budget_poste_id"]), Decimal(str(ligne.get("montant", ligne.get("montant_total")) or 0)))
                for ligne in (ordre.lignes or [])
                if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
            ]
            multi_poste = len({pid for pid, _ in ordre_postes}) > 1
        elif payload.ordre_decaissement_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ordre_decaissement_id fourni pour une réquisition sans décaissement progressif",
            )
        if req.mode_paiement and payload.mode_paiement:
            if str(req.mode_paiement).lower() != str(payload.mode_paiement).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mode de paiement différent de la réquisition approuvée",
                )
        if req.mode_paiement:
            expected_canal = "CAISSE" if str(req.mode_paiement).lower() == "cash" else "BANQUE"
            if payload.canal and str(payload.canal).upper() != expected_canal:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Canal de paiement différent de la réquisition approuvée",
                )
        if ordre is None and req.montant_total is not None and payload.montant_paye is not None:
            if Decimal(payload.montant_paye) != Decimal(req.montant_total):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Montant différent de la réquisition approuvée",
                )
        if payload.service_id is not None and req.service_id is not None:
            if int(payload.service_id) != int(req.service_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Service différent de la réquisition approuvée",
                )
        montant_paye = ordre.montant if ordre is not None else (req.montant_total or 0)

        lignes_res = await db.execute(
            select(LigneRequisition.budget_poste_id).where(LigneRequisition.requisition_id == requisition_uid)
        )
        lignes = [row[0] for row in lignes_res.all() if row[0] is not None]
        unique_lignes = sorted({int(v) for v in lignes})
        if not unique_lignes:
            if payload.budget_poste_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Réquisition sans rubrique budgétaire",
                )
            service_id = req.service_id
        elif multi_poste:
            # Décaissement progressif réparti sur plusieurs postes : l'imputation
            # est portée par les lignes de l'ordre, aucun poste unique à verrouiller.
            service_id = req.service_id
        else:
            if len(unique_lignes) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Réquisition multi-rubriques: sélection impossible",
                )
            locked_budget_id = unique_lignes[0]
            if payload.budget_poste_id and int(payload.budget_poste_id) != locked_budget_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Rubrique verrouillée par la réquisition",
                )
            payload.budget_poste_id = locked_budget_id
            service_id = req.service_id
    elif payload.service_id is not None:
        await _resolve_service(payload.service_id, db)
        service_id = payload.service_id

    # Imputation budgétaire : liste (poste, montant converti en devise budget).
    # Un seul élément dans le cas classique, plusieurs pour un décaissement réparti.
    imputations: list[tuple[BudgetPoste, Decimal]] = []
    if is_versement_banque or is_appro_caisse:
        # Un transfert interne (caisse <-> banque) n'est pas une dépense :
        # aucune imputation budgétaire.
        budget_line = None
        montant_paye_budget = Decimal("0")
    elif multi_poste:
        # Décaissement progressif réparti : on impute CHAQUE poste selon les
        # lignes de l'ordre (la somme = le montant de la tranche).
        budget_line = None
        montant_paye_budget = Decimal("0")
        await _assert_budget_rate(db, tenant_id, devise)
        for pid, montant_ligne in ordre_postes:
            res_bp = await db.execute(
                select(BudgetPoste)
                .where(BudgetPoste.id == pid, BudgetPoste.is_deleted.is_(False))
                .with_for_update()
            )
            bl = res_bp.scalar_one_or_none()
            if bl is None or (bl.type or "").upper() != "DEPENSE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Poste budgétaire invalide dans la répartition (id {pid})",
                )
            m_budget = await _to_budget_currency(db, tenant_id, montant_ligne, devise)
            if m_budget > 0 and (bl.montant_paye or 0) + m_budget > (bl.montant_prevu or 0):
                if not await _can_force_budget_overrun(db, user, tenant_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Dépassement budgétaire (poste {bl.code}): plafond "
                            f"{bl.montant_prevu}, déjà payé {bl.montant_paye}, demandé {m_budget}"
                        ),
                    )
            imputations.append((bl, m_budget))
    else:
        if payload.budget_poste_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id requis")
        budget_res = await db.execute(
            select(BudgetPoste)
            .where(
                BudgetPoste.id == payload.budget_poste_id,
                BudgetPoste.is_deleted.is_(False),
            )
            .with_for_update()
        )
        budget_line = budget_res.scalar_one_or_none()
        if budget_line is None or (budget_line.type or "").upper() != "DEPENSE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id invalide (type DEPENSE requis)")
        if budget_line.active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique budgétaire inactive")

        # Garde-fou : pas d'imputation budgétaire en devise étrangère sans taux.
        await _assert_budget_rate(db, tenant_id, devise)
        plafond = (budget_line.montant_prevu or 0)
        deja_paye = (budget_line.montant_paye or 0)
        # Montant converti dans la devise de base du budget (USD) : on ne compare et
        # n'additionne jamais des devises différentes sur un poste budgétaire.
        montant_paye_budget = await _to_budget_currency(db, tenant_id, montant_paye, devise)
        if montant_paye_budget > 0 and deja_paye + montant_paye_budget > plafond:
            can_force = await _can_force_budget_overrun(db, user, tenant_id)
            if not can_force:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dépassement budgétaire: plafond {plafond}, déjà payé {deja_paye}, demandé {montant_paye_budget}",
                )
        imputations = [(budget_line, montant_paye_budget)]

    solde_disponible = None
    if canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse = res.scalar_one()
        if not caisse.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant d'enregistrer une sortie.",
            )
        solde_disponible = caisse.solde_usd if devise == "USD" else caisse.solde_cdf
        if montant_paye > solde_disponible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fonds insuffisants en caisse ({solde_disponible} {devise})",
            )
    else:
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte_bancaire = res.scalar_one()
        solde_disponible = compte_bancaire.solde_actuel or 0
        if montant_paye > solde_disponible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fonds insuffisants sur le compte ({solde_disponible} {devise})",
            )

    # Get service_id for numbering
    service_id = payload.service_id
    if not service_id and payload.requisition_id:
        req_res = await db.execute(select(Requisition.service_id).where(Requisition.id == payload.requisition_id))
        service_id = req_res.scalar_one_or_none()

    reference_numero = await generate_document_number(db, "PAY", tenant_id, service_id=service_id)
    settings_res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    print_settings = settings_res.scalar_one_or_none()
    exchange_rate_snapshot = None
    if print_settings is not None:
        try:
            if print_settings.exchange_rate_cdf:
                exchange_rate_snapshot = float(print_settings.exchange_rate_cdf or 0)
            else:
                exchange_rate_snapshot = float(print_settings.exchange_rate or 0)
        except (TypeError, ValueError):
            exchange_rate_snapshot = None
    # La création de la sortie ne doit PAS dépendre de l'existence de
    # PrintSettings : une organisation sans réglages d'impression doit pouvoir
    # enregistrer une sortie de fonds (le snapshot de taux reste optionnel).
    sortie = SortieFonds(
        type_sortie=payload.type_sortie,
        organisation_id=tenant_id,
        requisition_id=requisition_uid,
        rubrique_code=payload.rubrique_code,
        budget_poste_id=(None if multi_poste else payload.budget_poste_id),
        budget_poste_code=(None if multi_poste else (budget_line.code if budget_line else None)),
        budget_poste_libelle=(
            f"Réparti sur {len(imputations)} postes"
            if multi_poste
            else (budget_line.libelle if budget_line else None)
        ),
        service_id=service_id,
        montant_paye=montant_paye,
        date_paiement=date_paiement,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        devise=devise,
        canal=canal,
        compte_bancaire_id=payload.compte_bancaire_id,
        reference_numero=reference_numero,
        exchange_rate_snapshot=exchange_rate_snapshot,
        statut=payload.statut or "VALIDE",
        motif=payload.motif,
        beneficiaire=payload.beneficiaire,
        piece_justificative=payload.piece_justificative,
        commentaire=payload.commentaire,
        created_by=user.id,
        # Programmeur (demandeur) : repris de l'ordre pour les sorties directes.
        programme_par_id=(ordre.autorise_par if ordre is not None else None),
    )
    db.add(sortie)
    if canal == "CAISSE":
        if devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or 0) - montant_paye
        else:
            caisse.solde_cdf = (caisse.solde_cdf or 0) - montant_paye
        caisse.derniere_maj = datetime.now(timezone.utc)
    else:
        compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) - montant_paye
    # Versement à la banque : créditer le compte bancaire de destination.
    if is_versement_banque and compte_destination is not None:
        compte_destination.solde_actuel = (compte_destination.solde_actuel or 0) + montant_paye
    # Approvisionnement de la caisse : créditer la caisse (banque déjà débitée).
    if is_appro_caisse:
        caisse_appro = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse_appro.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse_appro = res.scalar_one()
        if not caisse_appro.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant de l'approvisionner.",
            )
        if devise == "USD":
            caisse_appro.solde_usd = (caisse_appro.solde_usd or 0) + montant_paye
        else:
            caisse_appro.solde_cdf = (caisse_appro.solde_cdf or 0) + montant_paye
        caisse_appro.derniere_maj = datetime.now(timezone.utc)
    for poste_impute, montant_impute in imputations:
        poste_impute.montant_paye = (poste_impute.montant_paye or 0) + montant_impute

    if req is not None and ordre is None:
        now_req = datetime.now(timezone.utc)
        old_req_status = req.status
        req.status = "PAYEE"
        req.payee_par = user.id
        req.payee_le = now_req
        req.updated_at = now_req
        record_status_history(
            db=db,
            requisition=req,
            old_status=old_req_status,
            new_status=req.status,
            user=user,
            comment=f"Réquisition payée via la sortie de fonds {reference_numero}",
        )

    # --- Règlement d'un ordre de décaissement (progressif ou sortie directe)
    if ordre is not None:
        await db.flush()  # garantit sortie.id
        now_od = datetime.now(timezone.utc)
        ordre.statut = "PAYE"
        ordre.paye_par = user.id
        ordre.paye_le = now_od
        ordre.sortie_fonds_id = sortie.id
        ordre.updated_at = now_od

    if ordre is not None and ordre.requisition_id is not None:
        total_paye_od = (
            await db.execute(
                select(func.coalesce(func.sum(OrdreDecaissement.montant), 0)).where(
                    OrdreDecaissement.requisition_id == req.id,
                    OrdreDecaissement.statut == "PAYE",
                )
            )
        ).scalar_one() or 0

        old_req_status = req.status
        if Decimal(total_paye_od) >= Decimal(req.montant_total or 0):
            req.status = "PAYEE"
            req.payee_par = req.payee_par or user.id
            req.payee_le = req.payee_le or now_od
        else:
            req.status = "EN_DECAISSEMENT"
        req.updated_at = now_od
        record_status_history(
            db=db,
            requisition=req,
            old_status=old_req_status,
            new_status=req.status,
            user=user,
            comment=f"Ordre de décaissement {ordre.numero_ordre} payé ({ordre.montant} {ordre.devise})",
        )

    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_CREATED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        new_value={
            "reference_numero": sortie.reference_numero,
            "montant_paye": float(sortie.montant_paye or 0),
            "statut": sortie.statut,
            "beneficiaire": sortie.beneficiaire,
            "requisition_id": str(sortie.requisition_id) if sortie.requisition_id else None,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(sortie)

    requisition: Requisition | None = None
    creator: User | None = user
    validateur: User | None = None
    approbateur: User | None = None
    remboursement_transport: dict[str, Any] | None = None
    if sortie.requisition_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.id == sortie.requisition_id,
                Requisition.organisation_id == tenant_id,
            )
        )
        requisition = req_res.scalar_one_or_none()
        if requisition:
            u_ids = []
            if requisition.validee_par: u_ids.append(requisition.validee_par)
            if requisition.approuvee_par: u_ids.append(requisition.approuvee_par)
            if u_ids:
                u_res = await db.execute(select(User).where(User.id.in_(u_ids)))
                u_map = {u.id: u for u in u_res.scalars().all()}
                validateur = u_map.get(requisition.validee_par)
                approbateur = u_map.get(requisition.approuvee_par)
            remb_res = await db.execute(
                select(RemboursementTransport).where(RemboursementTransport.requisition_id == requisition.id)
            )
            remboursement_transport = _remboursement_transport_payload(remb_res.scalar_one_or_none())

    return _sortie_out(
        sortie,
        requisition,
        creator=creator,
        validateur=validateur,
        approbateur=approbateur,
        remboursement_transport=remboursement_transport,
    )


@router.post("/requisitions/{requisition_id}/reject", response_model=RequisitionOut)
async def reject_requisition_at_payment(
    requisition_id: str,
    payload: SortieFondsPaymentRejectPayload,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RequisitionOut:
    try:
        requisition_uid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")

    req = await reject_requisition_at_payment_logic(
        db=db,
        requisition_id=requisition_uid,
        user=user,
        tenant_id=tenant_id,
        motif_rejet=payload.motif_rejet,
        request=request,
    )
    return _requisition_out(req)


@router.post("/{sortie_id}/pdf")
async def upload_sortie_pdf(
    sortie_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notify: bool = True,
    attachments: list[UploadFile] | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id")

    res = await db.execute(
        select(SortieFonds).where(SortieFonds.id == sid, SortieFonds.organisation_id == tenant_id)
    )
    sortie = res.scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")

    content_type = (file.content_type or "").lower()
    if content_type not in PDF_ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")

    original_name = file.filename or "sortie.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in PDF_ALLOWED_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide")

    ref_base = sortie.reference_numero or sortie.reference or f"SORTIE-{sid}"
    safe_ref = _safe_ref(ref_base)
    filename = f"{safe_ref}-bon.pdf"
    upload_dt = datetime.now(timezone.utc)
    target_dir = _tenant_sortie_dir(tenant_uuid, upload_dt.year, upload_dt.month)
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    sortie.pdf_path = f"/uploads/tenants/{tenant_uuid}/sorties-fonds/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
    await db.commit()

    attachment_paths: list[str] = []
    attachment_fs_paths: list[str] = []
    if attachments:
        attachment_paths = await _save_sortie_annexes(attachments, safe_ref, tenant_uuid=tenant_uuid)
        current = list(sortie.annexes or [])
        for path in attachment_paths:
            if path not in current:
                current.append(path)
        sortie.annexes = current
        await db.commit()
        attachment_fs_paths = [_sortie_annexe_fs_path(name) for name in attachment_paths]

    if notify:
        try:
            ns = await get_system_settings(db, tenant_id)
            smtp_cfg = resolve_smtp_config(ns)
            if smtp_cfg and ns and ns.email_tresorier:
                    org_res = await db.execute(
                        select(Organisation.nom).where(Organisation.id == tenant_id).limit(1)
                    )
                    org_name = org_res.scalar_one_or_none()
                    caissier_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email or "Systeme"
                    if sortie.created_by and sortie.created_by != user.id:
                        creator_res = await db.execute(select(User).where(User.id == sortie.created_by))
                        creator = creator_res.scalar_one_or_none()
                        if creator:
                            caissier_name = (
                                " ".join(filter(None, [creator.prenom, creator.nom])) or creator.email or caissier_name
                            )

                    requisition_num = None
                    if sortie.requisition_id:
                        req_res = await db.execute(
                            select(Requisition).where(
                                Requisition.id == sortie.requisition_id,
                                Requisition.organisation_id == tenant_id,
                            )
                        )
                        req = req_res.scalar_one_or_none()
                        if req:
                            requisition_num = req.numero_requisition or req.reference_numero

                    official_pdf_path = _sortie_pdf_fs_path(sortie.pdf_path)
                    background_tasks.add_task(
                        send_sortie_notification,
                        smtp_host=smtp_cfg.host,
                        smtp_port=smtp_cfg.port,
                        smtp_user=smtp_cfg.user,
                        smtp_password=smtp_cfg.password,
                        sender=smtp_cfg.sender,
                        tresorier_email=ns.email_tresorier,
                        cc_emails=ns.emails_bureau_sortie_cc,
                        num_transaction=sortie.reference_numero or sortie.reference or str(sortie.id),
                        num_bon_requisition=requisition_num,
                        montant=float(sortie.montant_paye or 0),
                        beneficiaire=sortie.beneficiaire,
                        caissier_nom=caissier_name,
                        brand_name="ONEC",
                        organisation_name=org_name,
                        official_pdf_path=official_pdf_path,
                        attachment_paths=attachment_fs_paths,
                    )
        except Exception:
            logger.exception("Failed to schedule sortie notification after PDF upload")

    return {"ok": True, "pdf_path": filename}


@router.patch(
    "/{sortie_id}/statut",
    response_model=SortieFondsOut,
    dependencies=[Depends(require_roles(["admin", "tresorerie", "comptabilite"]))],
)
async def update_sortie_statut(
    sortie_id: str,
    payload: SortieFondsStatusUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    if not await _user_has_permission(db, user, "cancel_sortie_fonds"):
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (cancel_sortie_fonds)")
    try:
        sortie_uid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id UUID")

    res = await db.execute(
        select(SortieFonds).where(SortieFonds.id == sortie_uid, SortieFonds.organisation_id == tenant_id)
    )
    sortie = res.scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")

    previous_statut = (sortie.statut or "VALIDE").strip().upper()
    statut = (payload.statut or "").strip().upper()
    allowed = {"ANNULEE"}
    if statut not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statut invalide (ANNULEE uniquement)",
        )

    now = datetime.now(timezone.utc)
    if statut == "ANNULEE":
        reference_time = sortie.created_at or sortie.date_paiement
        if reference_time is not None:
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            if now - reference_time > timedelta(minutes=30):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Annulation impossible après 30 minutes",
                )
        if previous_statut == "ANNULEE" and sortie.annulee_le:
            annulee_le = sortie.annulee_le
            if annulee_le.tzinfo is None:
                annulee_le = annulee_le.replace(tzinfo=timezone.utc)
            if now - annulee_le > timedelta(minutes=5):
                incoming_motif = (payload.motif_annulation or "").strip()
                existing_motif = (sortie.motif_annulation or "").strip()
                if incoming_motif and incoming_motif != existing_motif:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Motif d'annulation non modifiable après 5 minutes",
                    )

    if sortie.budget_poste_id:
        budget_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id == sortie.budget_poste_id))
        budget_line = budget_res.scalar_one_or_none()
        if budget_line:
            was_valid = previous_statut == "VALIDE"
            will_valid = statut == "VALIDE"
            if was_valid and not will_valid:
                montant_budget = await _to_budget_currency(
                    db,
                    tenant_id,
                    sortie.montant_paye,
                    sortie.devise,
                    exchange_rate_snapshot=sortie.exchange_rate_snapshot,
                )
                budget_line.montant_paye = max(0, (budget_line.montant_paye or 0) - montant_budget)

    if previous_statut == "VALIDE" and statut == "ANNULEE":
        if sortie.canal == "CAISSE":
            caisse = await _get_or_create_caisse(db, tenant_id)
            res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
            )
            caisse = res.scalar_one()
            if sortie.devise == "USD":
                caisse.solde_usd = (caisse.solde_usd or 0) + (sortie.montant_paye or 0)
            else:
                caisse.solde_cdf = (caisse.solde_cdf or 0) + (sortie.montant_paye or 0)
            caisse.derniere_maj = now
        elif sortie.compte_bancaire_id is not None:
            res = await db.execute(
                select(CompteBancaire)
                .where(
                    CompteBancaire.id == sortie.compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            compte_bancaire = res.scalar_one_or_none()
            if compte_bancaire is None:
                raise HTTPException(status_code=400, detail="Compte de décaissement introuvable pour annuler cette sortie")
            compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) + (sortie.montant_paye or 0)
        # Annulation d'un versement caisse -> banque : re-débiter le compte
        # bancaire de destination (la caisse a déjà été re-créditée ci-dessus).
        if (
            (sortie.type_sortie or "").lower() == "versement_banque"
            and sortie.canal == "CAISSE"
            and sortie.compte_bancaire_id is not None
        ):
            res = await db.execute(
                select(CompteBancaire)
                .where(
                    CompteBancaire.id == sortie.compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            compte_dest = res.scalar_one_or_none()
            if compte_dest is not None:
                # M3 : borne à 0 + journalisation si le solde bancaire est déjà
                # inférieur au montant à re-débiter (mouvements intermédiaires).
                montant = sortie.montant_paye or 0
                solde_courant = compte_dest.solde_actuel or 0
                if montant > solde_courant:
                    logger.warning(
                        "Annulation versement %s : solde banque %s insuffisant pour re-débiter %s (manque %s). Tronqué à 0.",
                        sortie.reference_numero,
                        solde_courant,
                        montant,
                        montant - solde_courant,
                    )
                compte_dest.solde_actuel = max(0, solde_courant - montant)
        # Annulation d'un approvisionnement banque -> caisse : re-débiter la
        # caisse (le compte bancaire source a déjà été re-crédité ci-dessus).
        if (sortie.type_sortie or "").lower() == "approvisionnement_caisse":
            caisse_appro = await _get_or_create_caisse(db, tenant_id)
            res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse_appro.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
            )
            caisse_appro = res.scalar_one()
            montant = sortie.montant_paye or 0
            solde_courant = (caisse_appro.solde_usd if sortie.devise == "USD" else caisse_appro.solde_cdf) or 0
            if montant > solde_courant:
                logger.warning(
                    "Annulation approvisionnement %s : solde caisse %s insuffisant pour re-débiter %s (manque %s). Tronqué à 0.",
                    sortie.reference_numero,
                    solde_courant,
                    montant,
                    montant - solde_courant,
                )
            if sortie.devise == "USD":
                caisse_appro.solde_usd = max(0, solde_courant - montant)
            else:
                caisse_appro.solde_cdf = max(0, solde_courant - montant)
            caisse_appro.derniere_maj = now

    # --- Annulation d'une sortie liée à un ordre de décaissement :
    # l'ordre redevient AUTORISE (l'autorisation du demandeur reste valable)
    # et le statut de la réquisition est recalculé.
    if previous_statut == "VALIDE" and statut == "ANNULEE":
        ordre_res = await db.execute(
            select(OrdreDecaissement)
            .where(
                OrdreDecaissement.sortie_fonds_id == sortie.id,
                OrdreDecaissement.organisation_id == tenant_id,
                OrdreDecaissement.statut == "PAYE",
            )
            .with_for_update()
        )
        ordre_lie = ordre_res.scalar_one_or_none()
        if ordre_lie is not None:
            ordre_lie.statut = "AUTORISE"
            ordre_lie.paye_par = None
            ordre_lie.paye_le = None
            ordre_lie.sortie_fonds_id = None
            ordre_lie.updated_at = now

            req_od_res = await db.execute(
                select(Requisition)
                .where(
                    Requisition.id == ordre_lie.requisition_id,
                    Requisition.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            req_od = req_od_res.scalar_one_or_none()
            if req_od is not None and bool(getattr(req_od, "decaissement_progressif", False)):
                reste_paye = (
                    await db.execute(
                        select(func.coalesce(func.sum(OrdreDecaissement.montant), 0)).where(
                            OrdreDecaissement.requisition_id == req_od.id,
                            OrdreDecaissement.statut == "PAYE",
                        )
                    )
                ).scalar_one() or 0
                old_req_status = req_od.status
                if Decimal(reste_paye) >= Decimal(req_od.montant_total or 0):
                    new_req_status = "PAYEE"
                elif Decimal(reste_paye) > 0:
                    new_req_status = "EN_DECAISSEMENT"
                else:
                    new_req_status = "APPROUVEE"
                    req_od.payee_par = None
                    req_od.payee_le = None
                if new_req_status != old_req_status:
                    req_od.status = new_req_status
                    req_od.updated_at = now
                    record_status_history(
                        db=db,
                        requisition=req_od,
                        old_status=old_req_status,
                        new_status=new_req_status,
                        user=user,
                        comment=f"Annulation de la sortie liée à l'ordre {ordre_lie.numero_ordre}",
                    )

    sortie.statut = statut
    if statut == "ANNULEE":
        sortie.motif_annulation = (payload.motif_annulation or "").strip() or None
        if sortie.annulee_le is None:
            sortie.annulee_le = now
        sortie.annulee_par_id = user.id
        sortie.annulation_ip = get_request_ip(request)
        sortie.ancien_statut = previous_statut
    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_CANCELLED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        old_value={"statut": previous_statut},
        new_value={
            "statut": sortie.statut,
            "motif_annulation": sortie.motif_annulation,
            "annulee_par_id": str(sortie.annulee_par_id) if sortie.annulee_par_id else None,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(sortie)
    
    requisition: Requisition | None = None
    validateur: User | None = None
    approbateur: User | None = None
    if sortie.requisition_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.id == sortie.requisition_id,
                Requisition.organisation_id == tenant_id,
            )
        )
        requisition = req_res.scalar_one_or_none()
        if requisition:
            u_ids = []
            if requisition.validee_par: u_ids.append(requisition.validee_par)
            if requisition.approuvee_par: u_ids.append(requisition.approuvee_par)
            if u_ids:
                u_res = await db.execute(select(User).where(User.id.in_(u_ids)))
                u_map = {u.id: u for u in u_res.scalars().all()}
                validateur = u_map.get(requisition.validee_par)
                approbateur = u_map.get(requisition.approuvee_par)

    return _sortie_out(sortie, requisition, validateur=validateur, approbateur=approbateur)
