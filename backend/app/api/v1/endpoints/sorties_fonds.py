from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
import logging
import os
import re
from typing import Any
import uuid as uuid_lib

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles, has_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.cloture_caisse import ClotureCaisse
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.requisition import RequisitionOut
from app.schemas.sortie_fonds import (
    SortieFondsCreate,
    SortieFondsOut,
    SortiesFondsListResponse,
    SortieFondsStatusUpdate,
)
from app.services.document_sequences import generate_document_number
from app.services.mailer import send_sortie_notification
from app.services.audit_service import get_request_ip, log_action

router = APIRouter()


async def _can_force_budget_overrun(db: AsyncSession, user: User) -> bool:
    res = await db.execute(select(PrintSettings).limit(1))
    settings = res.scalar_one_or_none()
    if settings is None:
        return False
    if not settings.budget_block_overrun:
        return True
    roles = {r.strip().lower() for r in (settings.budget_force_roles or "").split(",") if r.strip()}
    return bool(user.role) and user.role.lower() in roles
logger = logging.getLogger("onec_cpk_api.sorties_fonds")

REQUISITION_STATUTS_VALIDES = ("VALIDEE", "APPROUVEE", "PAYEE", "payee", "approuvee")
MAX_ANNEXE_SIZE = 3 * 1024 * 1024
ANNEXE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ANNEXE_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
DEFAULT_SORTIE_PDF_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads", "sorties-fonds")
)
SORTIE_PDF_DIR = (
    os.path.abspath(os.path.join(settings.upload_dir, "sorties-fonds"))
    if settings.upload_dir
    else DEFAULT_SORTIE_PDF_DIR
)
DEFAULT_SORTIE_ANNEXE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads", "sorties-fonds", "annexes")
)
SORTIE_ANNEXE_DIR = (
    os.path.abspath(os.path.join(settings.upload_dir, "sorties-fonds", "annexes"))
    if settings.upload_dir
    else DEFAULT_SORTIE_ANNEXE_DIR
)


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


def _ensure_sortie_pdf_dir() -> None:
    os.makedirs(SORTIE_PDF_DIR, exist_ok=True)


def _ensure_sortie_annexe_dir() -> None:
    os.makedirs(SORTIE_ANNEXE_DIR, exist_ok=True)


def _sortie_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    filename = os.path.basename(file_path)
    return os.path.abspath(os.path.join(SORTIE_PDF_DIR, filename))


def _safe_ref(value: str) -> str:
    if not value:
        return "SORTIE"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return safe.strip("._-") or "SORTIE"


async def _save_sortie_annexes(attachments: list[UploadFile], safe_ref: str) -> list[str]:
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
        _ensure_sortie_annexe_dir()
        filename = f"{safe_ref}-annex-{uuid_lib.uuid4().hex}{ext or '.pdf'}"
        dest_path = os.path.join(SORTIE_ANNEXE_DIR, filename)
        with open(dest_path, "wb") as f:
            f.write(contents)
        filenames.append(filename)
    return filenames


def _requisition_out(req: Requisition) -> RequisitionOut:
    return RequisitionOut(
        id=str(req.id),
        numero_requisition=req.numero_requisition,
        reference_numero=req.reference_numero,
        objet=req.objet,
        mode_paiement=req.mode_paiement,
        type_requisition=req.type_requisition,
        montant_total=req.montant_total or 0,
        status=req.status,
        statut=req.status,
        created_by=str(req.created_by) if req.created_by else None,
        validee_par=str(req.validee_par) if req.validee_par else None,
        validee_le=req.validee_le,
        approuvee_par=str(req.approuvee_par) if req.approuvee_par else None,
        approuvee_le=req.approuvee_le,
        payee_par=str(req.payee_par) if req.payee_par else None,
        payee_le=req.payee_le,
        motif_rejet=req.motif_rejet,
        a_valoir=req.a_valoir,
        instance_beneficiaire=req.instance_beneficiaire,
        notes_a_valoir=req.notes_a_valoir,
        req_titre_officiel_hist=req.req_titre_officiel_hist,
        req_label_gauche_hist=req.req_label_gauche_hist,
        req_nom_gauche_hist=req.req_nom_gauche_hist,
        req_label_droite_hist=req.req_label_droite_hist,
        req_nom_droite_hist=req.req_nom_droite_hist,
        signataire_g_label=req.signataire_g_label,
        signataire_g_nom=req.signataire_g_nom,
        signataire_d_label=req.signataire_d_label,
        signataire_d_nom=req.signataire_d_nom,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


def _sortie_out(sortie: SortieFonds, requisition: Requisition | None = None) -> SortieFondsOut:
    return SortieFondsOut(
        id=str(sortie.id),
        type_sortie=sortie.type_sortie,
        requisition_id=str(sortie.requisition_id) if sortie.requisition_id else None,
        rubrique_code=sortie.rubrique_code,
        budget_poste_id=sortie.budget_poste_id,
        budget_poste_code=sortie.budget_poste_code,
        budget_poste_libelle=sortie.budget_poste_libelle,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        reference_numero=sortie.reference_numero,
        pdf_path=sortie.pdf_path,
        statut=sortie.statut or "VALIDE",
        motif_annulation=sortie.motif_annulation,
        exchange_rate_snapshot=sortie.exchange_rate_snapshot,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
        annexes=sortie.annexes,
        created_by=str(sortie.created_by) if sortie.created_by else None,
        created_at=sortie.created_at,
        requisition=_requisition_out(requisition) if requisition else None,
    )


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


@router.get("", response_model=list[SortieFondsOut] | SortiesFondsListResponse)
async def list_sorties_fonds(
    include: str | None = Query(default=None, description="Relations à inclure (requisition)"),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    type_sortie: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    requisition_numero: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    order: str | None = Query(default=None, description="Ex: date_paiement.desc"),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    include_summary: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SortieFondsOut] | SortiesFondsListResponse:
    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_requisition = "requisition" in include_parts or bool(requisition_numero)
    conditions = [
        or_(
            SortieFonds.requisition_id.is_(None),
            Requisition.status.in_(REQUISITION_STATUTS_VALIDES),
        )
    ]

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
    if include_requisition:
        rows = result.all()
        logger.info(
            "sorties_fonds list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(rows),
        )
        items = [_sortie_out(sortie, req) for sortie, req in rows]
    else:
        sorties = result.scalars().all()
        logger.info(
            "sorties_fonds list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(sorties),
        )
        items = [_sortie_out(sortie) for sortie in sorties]

    if not include_summary:
        return items

    count_query = select(func.count()).select_from(SortieFonds)
    sum_query = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).select_from(SortieFonds)
    count_query = count_query.outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
    sum_query = sum_query.outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
    if conditions:
        count_query = count_query.where(*conditions)
        sum_query = sum_query.where(*conditions)

    total_count = int((await db.execute(count_query)).scalar_one() or 0)
    sum_query = sum_query.where(
        (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
    )
    total_montant_paye = (await db.execute(sum_query)).scalar_one() or 0

    return SortiesFondsListResponse(
        items=items,
        total=total_count,
        total_montant_paye=total_montant_paye,
    )


@router.post("", response_model=SortieFondsOut, status_code=status.HTTP_201_CREATED)
async def create_sortie_fonds(
    payload: SortieFondsCreate,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    requisition_uid: uuid.UUID | None = None
    if payload.requisition_id:
        try:
            requisition_uid = uuid.UUID(payload.requisition_id)
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

    last_cloture_res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1)
    )
    last_cloture = last_cloture_res.scalar_one_or_none()
    last_cloture_dt = last_cloture.date_cloture if last_cloture else None
    if isinstance(last_cloture_dt, datetime) and last_cloture_dt.tzinfo is None:
        last_cloture_dt = last_cloture_dt.replace(tzinfo=timezone.utc)
    if last_cloture_dt and date_paiement.date() < last_cloture_dt.date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Période clôturée: sortie interdite avant la dernière clôture",
        )

    montant_paye = payload.montant_paye
    if requisition_uid:
        req_res = await db.execute(select(Requisition).where(Requisition.id == requisition_uid))
        req = req_res.scalar_one_or_none()
        if req is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        allowed_statuses = {"APPROUVEE", "approuvee", "PAYEE", "payee"}
        if req.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La réquisition doit être visée (2/2) avant la sortie de fonds",
            )
        montant_paye = req.montant_total or 0

        lignes_res = await db.execute(
            select(LigneRequisition.budget_poste_id).where(LigneRequisition.requisition_id == requisition_uid)
        )
        lignes = [row[0] for row in lignes_res.all() if row[0] is not None]
        unique_lignes = sorted({int(v) for v in lignes})
        if not unique_lignes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Réquisition sans rubrique budgétaire",
            )
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

    if payload.budget_poste_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id requis")
    budget_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == payload.budget_poste_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    budget_line = budget_res.scalar_one_or_none()
    if budget_line is None or (budget_line.type or "").upper() != "DEPENSE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id invalide (type DEPENSE requis)")
    if budget_line.active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique budgétaire inactive")

    plafond = (budget_line.montant_prevu or 0)
    deja_paye = (budget_line.montant_paye or 0)
    if montant_paye > 0 and deja_paye + montant_paye > plafond:
        can_force = await _can_force_budget_overrun(db, user)
        if not can_force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dépassement budgétaire: plafond {plafond}, déjà payé {deja_paye}, demandé {montant_paye}",
            )

    reference_numero = await generate_document_number(db, "PAY")
    settings_res = await db.execute(select(PrintSettings).limit(1))
    print_settings = settings_res.scalar_one_or_none()
    exchange_rate_snapshot = None
    if print_settings is not None:
        try:
            exchange_rate_snapshot = float(print_settings.exchange_rate or 0)
        except (TypeError, ValueError):
            exchange_rate_snapshot = None
        sortie = SortieFonds(
            type_sortie=payload.type_sortie,
            requisition_id=requisition_uid,
            rubrique_code=payload.rubrique_code,
            budget_poste_id=payload.budget_poste_id,
            budget_poste_code=budget_line.code if budget_line else None,
            budget_poste_libelle=budget_line.libelle if budget_line else None,
            montant_paye=montant_paye,
        date_paiement=date_paiement,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        reference_numero=reference_numero,
        exchange_rate_snapshot=exchange_rate_snapshot,
        statut=payload.statut or "VALIDE",
        motif=payload.motif,
        beneficiaire=payload.beneficiaire,
        piece_justificative=payload.piece_justificative,
        commentaire=payload.commentaire,
        created_by=user.id,
    )
    db.add(sortie)
    budget_line.montant_paye = (budget_line.montant_paye or 0) + montant_paye
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
    if sortie.requisition_id:
        req_res = await db.execute(select(Requisition).where(Requisition.id == sortie.requisition_id))
        requisition = req_res.scalar_one_or_none()

    return _sortie_out(sortie, requisition)


@router.post("/{sortie_id}/pdf")
async def upload_sortie_pdf(
    sortie_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notify: bool = True,
    attachments: list[UploadFile] | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id")

    res = await db.execute(select(SortieFonds).where(SortieFonds.id == sid))
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

    _ensure_sortie_pdf_dir()
    ref_base = sortie.reference_numero or sortie.reference or f"SORTIE-{sid}"
    safe_ref = _safe_ref(ref_base)
    filename = f"{safe_ref}-bon.pdf"
    dest_path = os.path.join(SORTIE_PDF_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    sortie.pdf_path = filename
    await db.commit()

    attachment_paths: list[str] = []
    attachment_fs_paths: list[str] = []
    if attachments:
        attachment_paths = await _save_sortie_annexes(attachments, safe_ref)
        current = [os.path.basename(p) for p in list(sortie.annexes or [])]
        for path in attachment_paths:
            if path not in current:
                current.append(path)
        sortie.annexes = current
        await db.commit()
        attachment_fs_paths = [os.path.join(SORTIE_ANNEXE_DIR, name) for name in attachment_paths]

    if notify:
        try:
            settings_res = await db.execute(select(SystemSettings).limit(1))
            ns = settings_res.scalar_one_or_none()
            if ns and ns.email_expediteur and ns.email_tresorier:
                smtp_password = (ns.smtp_password or "").strip()
                if smtp_password:
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
                        req_res = await db.execute(select(Requisition).where(Requisition.id == sortie.requisition_id))
                        req = req_res.scalar_one_or_none()
                        if req:
                            requisition_num = req.numero_requisition or req.reference_numero

                    official_pdf_path = _sortie_pdf_fs_path(sortie.pdf_path)
                    background_tasks.add_task(
                        send_sortie_notification,
                        smtp_host=ns.smtp_host or "smtp.gmail.com",
                        smtp_port=int(ns.smtp_port or 465),
                        smtp_user=ns.email_expediteur,
                        smtp_password=smtp_password,
                        sender=ns.email_expediteur,
                        tresorier_email=ns.email_tresorier,
                        cc_emails=ns.emails_bureau_sortie_cc,
                        num_transaction=sortie.reference_numero or sortie.reference or str(sortie.id),
                        num_bon_requisition=requisition_num,
                        montant=float(sortie.montant_paye or 0),
                        beneficiaire=sortie.beneficiaire,
                        caissier_nom=caissier_name,
                        official_pdf_path=official_pdf_path,
                        attachment_paths=attachment_fs_paths,
                    )
                else:
                    logger.warning("SMTP password is missing; skipping sortie notification")
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
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    try:
        sortie_uid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id UUID")

    res = await db.execute(select(SortieFonds).where(SortieFonds.id == sortie_uid))
    sortie = res.scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")

    previous_statut = (sortie.statut or "VALIDE").strip().upper()
    statut = (payload.statut or "").strip().upper()
    allowed = {"VALIDE", "ANNULEE"}
    if statut not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statut invalide (VALIDE, ANNULEE)",
        )

    if statut == "ANNULEE":
        reference_time = sortie.created_at or sortie.date_paiement
        if reference_time is not None:
            now = datetime.now(timezone.utc)
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            if now - reference_time > timedelta(minutes=30):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Annulation impossible après 30 minutes",
                )

    if sortie.budget_poste_id:
        budget_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id == sortie.budget_poste_id))
        budget_line = budget_res.scalar_one_or_none()
        if budget_line:
            was_valid = previous_statut == "VALIDE"
            will_valid = statut == "VALIDE"
            if was_valid and not will_valid:
                budget_line.montant_paye = max(0, (budget_line.montant_paye or 0) - (sortie.montant_paye or 0))
            elif not was_valid and will_valid:
                budget_line.montant_paye = (budget_line.montant_paye or 0) + (sortie.montant_paye or 0)

    sortie.statut = statut
    if statut == "ANNULEE":
        sortie.motif_annulation = (payload.motif_annulation or "").strip() or None
    else:
        sortie.motif_annulation = None
    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_STATUS_UPDATED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        old_value={"statut": previous_statut},
        new_value={"statut": sortie.statut, "motif_annulation": sortie.motif_annulation},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(sortie)
    return _sortie_out(sortie)
