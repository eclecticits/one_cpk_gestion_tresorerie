from __future__ import annotations

import uuid
from datetime import datetime, timezone
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.config import settings
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.requisition import Requisition
from app.models.print_settings import PrintSettings
from app.models.remboursement_transport import RemboursementTransport
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.services.document_sequences import generate_document_number
from app.schemas.requisition import (
    RequisitionAnnexeOut,
    RequisitionCreate,
    RequisitionOut,
    RequisitionUpdate,
    RequisitionWithUserOut,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.requisitions")
MAX_ANNEXE_SIZE = 3 * 1024 * 1024
ANNEXE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ANNEXE_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
DEFAULT_ANNEXE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads", "annexes")
)
ANNEXE_DIR = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_ANNEXE_DIR


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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




def _ensure_annexe_dir() -> None:
    os.makedirs(ANNEXE_DIR, exist_ok=True)


def _annexe_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/static/"):
        rel_path = file_path.replace("/static/", "", 1)
        return os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "static", rel_path)
        )
    filename = os.path.basename(file_path)
    return os.path.abspath(os.path.join(ANNEXE_DIR, filename))


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "")
    if not base:
        return "annexe"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return safe.strip("._") or "annexe"


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
    caissier: User | None = None,
    annexe: RequisitionAnnexe | None = None,
    montant_deja_paye: Any | None = None,
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
        "annexe": _annexe_payload(annexe) if annexe else None,
    }
    if demandeur:
        base["demandeur"] = _user_info(demandeur)
    if validateur:
        base["validateur"] = _user_info(validateur)
    if approbateur:
        base["approbateur"] = _user_info(approbateur)
    if caissier:
        base["caissier"] = _user_info(caissier)
    return base


def _should_snapshot(status_value: str | None) -> bool:
    if not status_value:
        return False
    return status_value.strip().lower() in {"approuvee", "payee"}


async def _apply_snapshot_if_needed(req: Requisition, db: AsyncSession) -> None:
    if req.req_label_gauche_hist or req.req_label_droite_hist or req.req_titre_officiel_hist:
        return
    res = await db.execute(select(PrintSettings).limit(1))
    settings = res.scalar_one_or_none()
    if not settings:
        return
    req.req_titre_officiel_hist = settings.req_titre_officiel or None
    req.req_label_gauche_hist = settings.req_label_gauche or None
    req.req_nom_gauche_hist = settings.req_nom_gauche or None
    req.req_label_droite_hist = settings.req_label_droite or None
    req.req_nom_droite_hist = settings.req_nom_droite or None
    req.signataire_g_label = settings.req_label_gauche or None
    req.signataire_g_nom = settings.req_nom_gauche or None
    req.signataire_d_label = settings.req_label_droite or None
    req.signataire_d_nom = settings.req_nom_droite or None

    if req.type_requisition == "remboursement_transport":
        rt_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id)
        )
        remboursement = rt_res.scalar_one_or_none()
        if remboursement and not (
            remboursement.trans_label_gauche_hist
            or remboursement.trans_label_droite_hist
            or remboursement.trans_titre_officiel_hist
        ):
            remboursement.trans_titre_officiel_hist = settings.trans_titre_officiel or None
            remboursement.trans_label_gauche_hist = settings.trans_label_gauche or None
            remboursement.trans_nom_gauche_hist = settings.trans_nom_gauche or None
            remboursement.trans_label_droite_hist = settings.trans_label_droite or None
            remboursement.trans_nom_droite_hist = settings.trans_nom_droite or None
            remboursement.signataire_g_label = settings.trans_label_gauche or None
            remboursement.signataire_g_nom = settings.trans_nom_gauche or None
            remboursement.signataire_d_label = settings.trans_label_droite or None
            remboursement.signataire_d_nom = settings.trans_nom_droite or None


@router.get("/verify")
async def verify_requisition(
    ref: str = Query(..., description="Numéro de réquisition ou UUID"),
    amount: float = Query(..., description="Montant attendu (USD)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    requisition: Requisition | None = None
    try:
        rid = uuid.UUID(ref)
        res = await db.execute(select(Requisition).where(Requisition.id == rid))
        requisition = res.scalar_one_or_none()
    except ValueError:
        res = await db.execute(select(Requisition).where(Requisition.numero_requisition == ref))
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    start = _parse_datetime(date_debut)
    end = _parse_datetime(date_fin, end_of_day=True)
    if start is None or end is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")

    query = select(Requisition).where(Requisition.created_at.between(start, end))
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
    type_requisition: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    created_by: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    include: str | None = Query(default=None),
    order: str | None = Query(default=None),
    limit: int | None = Query(default=200),
    offset: int | None = Query(default=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Requisition)
    if status:
        query = query.where(Requisition.status == status)
    if status_in:
        statuses = [s for s in status_in.split(",") if s]
        if statuses:
            query = query.where(Requisition.status.in_(statuses))
    if type_requisition:
        query = query.where(Requisition.type_requisition == type_requisition)
    if mode_paiement:
        query = query.where(Requisition.mode_paiement == mode_paiement)
    if created_by:
        try:
            query = query.where(Requisition.created_by == uuid.UUID(created_by))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")

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
    needs_users = include_parts.intersection({"demandeur", "validateur", "approbateur", "caissier"})
    users_map: dict[uuid.UUID, User] = {}
    if needs_users:
        user_ids: set[uuid.UUID] = set()
        if "demandeur" in include_parts:
            user_ids.update({r.created_by for r in requisitions if r.created_by})
        if "validateur" in include_parts:
            user_ids.update({r.validee_par for r in requisitions if r.validee_par})
        if "approbateur" in include_parts:
            user_ids.update({r.approuvee_par for r in requisitions if r.approuvee_par})
        if "caissier" in include_parts:
            user_ids.update({r.payee_par for r in requisitions if r.payee_par})

        if user_ids:
            users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
            users_map = {u.id: u for u in users_res.scalars().all()}

    annexes_map: dict[uuid.UUID, RequisitionAnnexe] = {}
    if requisitions:
        ann_res = await db.execute(
            select(RequisitionAnnexe).where(RequisitionAnnexe.requisition_id.in_([r.id for r in requisitions]))
        )
        annexes_map = {a.requisition_id: a for a in ann_res.scalars().all()}

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

    return [
        _requisition_out(
            r,
            demandeur=users_map.get(r.created_by) if "demandeur" in include_parts else None,
            validateur=users_map.get(r.validee_par) if "validateur" in include_parts else None,
            approbateur=users_map.get(r.approuvee_par) if "approbateur" in include_parts else None,
            caissier=users_map.get(r.payee_par) if "caissier" in include_parts else None,
            annexe=annexes_map.get(r.id),
            montant_deja_paye=montant_paye_map.get(r.id, 0),
        )
        for r in requisitions
    ]


@router.get("/{requisition_id}/annexe", response_model=RequisitionAnnexeOut)
async def get_requisition_annexe(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionAnnexeOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(select(RequisitionAnnexe).where(RequisitionAnnexe.requisition_id == rid))
    annexe = res.scalar_one_or_none()
    if not annexe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe not found")
    return RequisitionAnnexeOut(**_annexe_payload(annexe))


@router.get("/annexe/{annexe_id}")
async def download_requisition_annexe(
    annexe_id: str,
    db: AsyncSession = Depends(get_db),
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

    fs_path = _annexe_fs_path(annexe.file_path)
    if not fs_path or not os.path.exists(fs_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annexe file missing")

    return FileResponse(
        fs_path,
        media_type=annexe.file_type or "application/octet-stream",
        filename=annexe.filename,
    )


@router.post("/{requisition_id}/annexe", response_model=RequisitionAnnexeOut, status_code=status.HTTP_201_CREATED)
async def upload_requisition_annexe(
    requisition_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionAnnexeOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    req_res = await db.execute(select(Requisition).where(Requisition.id == rid))
    if req_res.scalar_one_or_none() is None:
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

    _ensure_annexe_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_name = _safe_filename(original_name)
    filename = f"REQ_{rid}_{timestamp}_{safe_name}"
    dest_path = os.path.join(ANNEXE_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    file_key = filename

    ann_res = await db.execute(select(RequisitionAnnexe).where(RequisitionAnnexe.requisition_id == rid))
    annexe = ann_res.scalar_one_or_none()
    if annexe:
        old_fs_path = _annexe_fs_path(annexe.file_path)
        if old_fs_path and os.path.exists(old_fs_path):
            try:
                os.remove(old_fs_path)
            except OSError:
                logger.warning("Impossible de supprimer l'ancienne annexe %s", old_fs_path)
        annexe.file_path = file_key
        annexe.filename = original_name
        annexe.file_type = content_type
        annexe.file_size = len(contents)
        annexe.upload_date = _utcnow()
    else:
        annexe = RequisitionAnnexe(
            requisition_id=rid,
            file_path=file_key,
            filename=original_name,
            file_type=content_type,
            file_size=len(contents),
            upload_date=_utcnow(),
        )
        db.add(annexe)

    await db.commit()
    await db.refresh(annexe)
    return RequisitionAnnexeOut(**_annexe_payload(annexe))


@router.get("/{requisition_id}/annexe/debug")
async def debug_requisition_annexe(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionOut:
    status_value = _status_from_payload(payload) or "EN_ATTENTE"
    created_by = None
    if payload.created_by:
        try:
            created_by = uuid.UUID(payload.created_by)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")

    numero_requisition = payload.numero_requisition or await generate_document_number(db, "REQ")
    req = Requisition(
        numero_requisition=numero_requisition,
        objet=payload.objet,
        mode_paiement=payload.mode_paiement,
        type_requisition=payload.type_requisition,
        montant_total=payload.montant_total,
        status=status_value,
        created_by=created_by,
        a_valoir=bool(payload.a_valoir),
        instance_beneficiaire=payload.instance_beneficiaire,
        notes_a_valoir=payload.notes_a_valoir,
        reference_numero=numero_requisition,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)


@router.put("/{requisition_id}", response_model=RequisitionOut)
async def update_requisition(
    requisition_id: str,
    payload: RequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(select(Requisition).where(Requisition.id == rid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    if payload.objet is not None:
        req.objet = payload.objet
    if payload.mode_paiement is not None:
        req.mode_paiement = payload.mode_paiement
    if payload.type_requisition is not None:
        req.type_requisition = payload.type_requisition
    if payload.montant_total is not None:
        req.montant_total = payload.montant_total

    status_value = _status_from_payload(payload)
    if status_value is not None:
        req.status = status_value

    for attr in ("validee_par", "approuvee_par", "payee_par", "created_by"):
        value = getattr(payload, attr)
        if value is not None:
            try:
                setattr(req, attr, uuid.UUID(value))
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {attr}")

    for attr in ("validee_le", "approuvee_le", "payee_le"):
        value = getattr(payload, attr)
        if value is not None:
            setattr(req, attr, value)

    if payload.motif_rejet is not None:
        req.motif_rejet = payload.motif_rejet
    if payload.a_valoir is not None:
        req.a_valoir = payload.a_valoir
    if payload.instance_beneficiaire is not None:
        req.instance_beneficiaire = payload.instance_beneficiaire
    if payload.notes_a_valoir is not None:
        req.notes_a_valoir = payload.notes_a_valoir

    if _should_snapshot(status_value):
        await _apply_snapshot_if_needed(req, db)

    req.updated_at = payload.updated_at or _utcnow()

    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)


@router.post("/{requisition_id}/validate", response_model=RequisitionOut)
async def validate_requisition(
    requisition_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(select(Requisition).where(Requisition.id == rid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    req.status = "VALIDEE"
    req.validee_par = user.id
    req.validee_le = _utcnow()
    req.updated_at = _utcnow()
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)


@router.post("/{requisition_id}/reject", response_model=RequisitionOut)
async def reject_requisition(
    requisition_id: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequisitionOut:
    try:
        rid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    res = await db.execute(select(Requisition).where(Requisition.id == rid))
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    req.status = "REJETEE"
    req.motif_rejet = payload.get("motif_rejet")
    req.validee_par = user.id
    req.validee_le = _utcnow()
    req.updated_at = _utcnow()
    await db.commit()
    await db.refresh(req)
    return _requisition_out(req)
