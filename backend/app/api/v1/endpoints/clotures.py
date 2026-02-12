from __future__ import annotations

from datetime import datetime, timezone
import uuid
import os
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from openpyxl import Workbook

from app.api.deps import get_current_user, has_permission
from app.db.session import get_db
from app.models.cloture_caisse import ClotureCaisse
from app.models.encaissement import Encaissement
from app.models.print_settings import PrintSettings
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.cloture import ClotureBalanceResponse, ClotureCreateRequest, ClotureOut, CloturePdfData, CloturePdfDetail
from app.core.config import settings
from app.services.audit_service import get_request_ip, log_action
from app.services.document_sequences import generate_document_number

router = APIRouter()

PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
CLTURE_PDF_DIR = os.path.abspath(os.path.join(settings.upload_dir, "clotures"))


def _decimal(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


async def _compute_balance(db: AsyncSession) -> ClotureBalanceResponse:
    last_res = await db.execute(select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1))
    last = last_res.scalar_one_or_none()

    date_debut = last.date_cloture if last else None
    date_fin = datetime.now(timezone.utc)

    solde_initial_usd = _decimal(last.solde_physique_usd if last else 0)
    solde_initial_cdf = _decimal(last.solde_physique_cdf if last else 0)

    settings_res = await db.execute(select(PrintSettings).limit(1))
    ps = settings_res.scalar_one_or_none()
    try:
        taux_change = Decimal(ps.exchange_rate or 1) if ps else Decimal("1")
    except Exception:
        taux_change = Decimal("1")

    enc_query = select(func.coalesce(func.sum(Encaissement.montant_paye), 0))
    if date_debut:
        enc_query = enc_query.where(Encaissement.date_encaissement >= date_debut)
    enc_query = enc_query.where(Encaissement.date_encaissement <= date_fin)
    enc_total_usd = _decimal((await db.execute(enc_query)).scalar_one() or 0)

    enc_cdf_query = select(func.coalesce(func.sum(Encaissement.montant_percu), 0)).where(
        Encaissement.devise_perception == "CDF"
    )
    if date_debut:
        enc_cdf_query = enc_cdf_query.where(Encaissement.date_encaissement >= date_debut)
    enc_cdf_query = enc_cdf_query.where(Encaissement.date_encaissement <= date_fin)
    enc_total_cdf = _decimal((await db.execute(enc_cdf_query)).scalar_one() or 0)

    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    sort_query = select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
        (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
    )
    if date_debut:
        sort_query = sort_query.where(paiement_ts >= date_debut)
    sort_query = sort_query.where(paiement_ts <= date_fin)
    sort_total_usd = _decimal((await db.execute(sort_query)).scalar_one() or 0)

    total_entrees_cdf = enc_total_cdf
    total_sorties_cdf = Decimal("0")

    solde_theorique_usd = _decimal(solde_initial_usd + enc_total_usd - sort_total_usd)
    solde_theorique_cdf = _decimal(solde_initial_cdf + total_entrees_cdf - total_sorties_cdf)

    return ClotureBalanceResponse(
        date_debut=date_debut,
        date_fin=date_fin,
        taux_change=taux_change,
        solde_initial_usd=solde_initial_usd,
        solde_initial_cdf=solde_initial_cdf,
        total_entrees_usd=enc_total_usd,
        total_entrees_cdf=total_entrees_cdf,
        total_sorties_usd=sort_total_usd,
        total_sorties_cdf=total_sorties_cdf,
        solde_theorique_usd=solde_theorique_usd,
        solde_theorique_cdf=solde_theorique_cdf,
    )


def _cloture_out(c: ClotureCaisse) -> ClotureOut:
    return ClotureOut(
        id=c.id,
        reference_numero=c.reference_numero,
        date_cloture=c.date_cloture,
        date_debut=c.date_debut,
        caissier_id=str(c.caissier_id) if c.caissier_id else None,
        solde_initial_usd=c.solde_initial_usd,
        solde_initial_cdf=c.solde_initial_cdf,
        total_entrees_usd=c.total_entrees_usd,
        total_entrees_cdf=c.total_entrees_cdf,
        total_sorties_usd=c.total_sorties_usd,
        total_sorties_cdf=c.total_sorties_cdf,
        solde_theorique_usd=c.solde_theorique_usd,
        solde_theorique_cdf=c.solde_theorique_cdf,
        solde_physique_usd=c.solde_physique_usd,
        solde_physique_cdf=c.solde_physique_cdf,
        ecart_usd=c.ecart_usd,
        ecart_cdf=c.ecart_cdf,
        taux_change_applique=c.taux_change_applique,
        billetage_usd=c.billetage_usd,
        billetage_cdf=c.billetage_cdf,
        observation=c.observation,
        pdf_path=c.pdf_path,
        statut=c.statut,
    )


def _ensure_cloture_pdf_dir() -> None:
    os.makedirs(CLTURE_PDF_DIR, exist_ok=True)


def _safe_ref(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in ("-", "_"))
    return cleaned or "CLOTURE"


@router.get("/balance-check", response_model=ClotureBalanceResponse, dependencies=[Depends(has_permission("can_view_reports"))])
async def get_balance_check(db: AsyncSession = Depends(get_db)) -> ClotureBalanceResponse:
    return await _compute_balance(db)


@router.get("", response_model=list[ClotureOut], dependencies=[Depends(has_permission("can_view_reports"))])
async def list_clotures(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    caissier_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ClotureOut]:
    stmt = select(ClotureCaisse)
    if date_debut:
        try:
            start_dt = datetime.fromisoformat(date_debut)
        except ValueError:
            start_dt = None
        if start_dt:
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            stmt = stmt.where(ClotureCaisse.date_cloture >= start_dt)
    if date_fin:
        try:
            end_dt = datetime.fromisoformat(date_fin)
        except ValueError:
            end_dt = None
        if end_dt:
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            stmt = stmt.where(ClotureCaisse.date_cloture <= end_dt)
    if caissier_id:
        try:
            caissier_uid = uuid.UUID(caissier_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="caissier_id invalide")
        stmt = stmt.where(ClotureCaisse.caissier_id == caissier_uid)

    res = await db.execute(
        stmt.order_by(ClotureCaisse.date_cloture.desc()).limit(limit).offset(offset)
    )
    return [_cloture_out(c) for c in res.scalars().all()]


@router.get("/caissiers", dependencies=[Depends(has_permission("can_view_reports"))])
async def list_cloture_caissiers(db: AsyncSession = Depends(get_db)) -> list[dict]:
    stmt = (
        select(User.id, User.email, User.nom, User.prenom)
        .join(ClotureCaisse, ClotureCaisse.caissier_id == User.id)
        .distinct()
        .order_by(User.email.asc())
    )
    res = await db.execute(stmt)
    users = []
    for uid, email, nom, prenom in res.all():
        label = " ".join(filter(None, [prenom, nom])) or email or str(uid)
        users.append({"id": str(uid), "label": label, "email": email})
    return users


@router.get("/export-xlsx", dependencies=[Depends(has_permission("can_view_reports"))])
async def export_clotures_xlsx(
    limit: int = Query(default=5000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(limit).offset(offset)
    )
    clotures = res.scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Clotures"
    ws.append(
        [
            "id",
            "reference_numero",
            "date_cloture",
            "date_debut",
            "caissier_id",
            "solde_initial_usd",
            "total_entrees_usd",
            "total_sorties_usd",
            "solde_theorique_usd",
            "solde_physique_usd",
            "ecart_usd",
            "solde_initial_cdf",
            "total_entrees_cdf",
            "total_sorties_cdf",
            "solde_theorique_cdf",
            "solde_physique_cdf",
            "ecart_cdf",
            "statut",
            "observation",
        ]
    )
    for c in clotures:
        ws.append(
            [
                c.id,
                c.reference_numero,
                c.date_cloture.isoformat() if c.date_cloture else "",
                c.date_debut.isoformat() if c.date_debut else "",
                str(c.caissier_id) if c.caissier_id else "",
                float(c.solde_initial_usd or 0),
                float(c.total_entrees_usd or 0),
                float(c.total_sorties_usd or 0),
                float(c.solde_theorique_usd or 0),
                float(c.solde_physique_usd or 0),
                float(c.ecart_usd or 0),
                float(c.solde_initial_cdf or 0),
                float(c.total_entrees_cdf or 0),
                float(c.total_sorties_cdf or 0),
                float(c.solde_theorique_cdf or 0),
                float(c.solde_physique_cdf or 0),
                float(c.ecart_cdf or 0),
                c.statut,
                c.observation or "",
            ]
        )
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"clotures_{datetime.now(timezone.utc).date().isoformat()}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.post("", response_model=ClotureOut, dependencies=[Depends(has_permission("can_execute_payment"))])
async def create_cloture(
    payload: ClotureCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClotureOut:
    balance = await _compute_balance(db)

    solde_physique_usd = _decimal(payload.solde_physique_usd)
    solde_physique_cdf = _decimal(payload.solde_physique_cdf)
    taux_change = _decimal(balance.taux_change or 1)
    if taux_change <= 0:
        taux_change = Decimal("1")
    total_physique_usd = _decimal(solde_physique_usd + (solde_physique_cdf / taux_change))
    ecart_usd = _decimal(total_physique_usd - balance.solde_theorique_usd)
    ecart_cdf = _decimal(solde_physique_cdf - balance.solde_theorique_cdf)

    reference_numero = await generate_document_number(db, "CLO")
    cloture = ClotureCaisse(
        reference_numero=reference_numero,
        date_cloture=balance.date_fin,
        date_debut=balance.date_debut,
        caissier_id=user.id,
        solde_initial_usd=balance.solde_initial_usd,
        solde_initial_cdf=balance.solde_initial_cdf,
        total_entrees_usd=balance.total_entrees_usd,
        total_entrees_cdf=balance.total_entrees_cdf,
        total_sorties_usd=balance.total_sorties_usd,
        total_sorties_cdf=balance.total_sorties_cdf,
        solde_theorique_usd=balance.solde_theorique_usd,
        solde_theorique_cdf=balance.solde_theorique_cdf,
        solde_physique_usd=solde_physique_usd,
        solde_physique_cdf=solde_physique_cdf,
        ecart_usd=ecart_usd,
        ecart_cdf=ecart_cdf,
        taux_change_applique=taux_change,
        billetage_usd=payload.billetage_usd,
        billetage_cdf=payload.billetage_cdf,
        observation=(payload.observation or "").strip() or None,
        statut="VALIDEE",
    )
    db.add(cloture)
    await log_action(
        db,
        user_id=user.id,
        action="CAISSE_CLOTURE_JOURNALIERE",
        target_table="clotures",
        target_id=reference_numero,
        new_value={
            "solde_theorique_usd": str(balance.solde_theorique_usd),
            "solde_physique_usd": str(solde_physique_usd),
            "ecart_usd": str(ecart_usd),
            "solde_theorique_cdf": str(balance.solde_theorique_cdf),
            "solde_physique_cdf": str(solde_physique_cdf),
            "ecart_cdf": str(ecart_cdf),
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(cloture)
    return _cloture_out(cloture)


@router.post("/{cloture_id}/pdf", dependencies=[Depends(has_permission("can_view_reports"))])
async def upload_cloture_pdf(
    cloture_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(ClotureCaisse).where(ClotureCaisse.id == cloture_id))
    cloture = res.scalar_one_or_none()
    if cloture is None:
        raise HTTPException(status_code=404, detail="Clôture introuvable")

    content_type = (file.content_type or "").lower()
    if content_type not in PDF_ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Format de fichier non autorisé")

    original_name = file.filename or "cloture.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in PDF_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Fichier vide")

    _ensure_cloture_pdf_dir()
    safe_ref = _safe_ref(cloture.reference_numero or f"CLOTURE-{cloture.id}")
    filename = f"{safe_ref}-pv.pdf"
    dest_path = os.path.join(CLTURE_PDF_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    cloture.pdf_path = filename
    await db.commit()
    return {"ok": True, "pdf_path": filename}


@router.get("/{cloture_id}/pdf", dependencies=[Depends(has_permission("can_view_reports"))])
async def download_cloture_pdf(
    cloture_id: int,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(ClotureCaisse).where(ClotureCaisse.id == cloture_id))
    cloture = res.scalar_one_or_none()
    if cloture is None:
        raise HTTPException(status_code=404, detail="Clôture introuvable")
    if not cloture.pdf_path:
        raise HTTPException(status_code=404, detail="PV non archivé")
    file_path = os.path.join(CLTURE_PDF_DIR, cloture.pdf_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier PV introuvable")
    return FileResponse(file_path, media_type="application/pdf", filename=cloture.pdf_path)


@router.get("/{cloture_id}/pdf-data", response_model=CloturePdfData, dependencies=[Depends(has_permission("can_view_reports"))])
async def get_cloture_pdf_data(
    cloture_id: int,
    db: AsyncSession = Depends(get_db),
) -> CloturePdfData:
    res = await db.execute(select(ClotureCaisse).where(ClotureCaisse.id == cloture_id))
    cloture = res.scalar_one_or_none()
    if cloture is None:
        raise HTTPException(status_code=404, detail="Clôture introuvable")

    start_dt = cloture.date_debut
    end_dt = cloture.date_cloture
    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    query = select(SortieFonds).where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
    if start_dt:
        query = query.where(paiement_ts >= start_dt)
    query = query.where(paiement_ts <= end_dt).order_by(paiement_ts.asc())
    sort_res = await db.execute(query)
    sorties = sort_res.scalars().all()

    details = [
        CloturePdfDetail(
            reference_numero=s.reference_numero or s.reference,
            beneficiaire=s.beneficiaire,
            motif=s.motif,
            montant_paye=s.montant_paye,
        )
        for s in sorties
    ]
    return CloturePdfData(cloture=_cloture_out(cloture), details=details)
