from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds

router = APIRouter()


@router.get("/audit/sortie", response_model=None)
async def audit_sortie(
    request: Request,
    ref: str | None = Query(default=None),
    id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    accept_header = (request.headers.get("accept") if request else "") or ""
    wants_html = "text/html" in accept_header and "application/json" not in accept_header
    if wants_html:
        if ref:
            return RedirectResponse(url=f"/audit/sortie?ref={ref}")
        if id:
            return RedirectResponse(url=f"/audit/sortie?id={id}")
        return RedirectResponse(url="/audit/sortie", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    sortie = None
    if ref:
        res = await db.execute(select(SortieFonds).where(SortieFonds.reference_numero == ref))
        sortie = res.scalar_one_or_none()
    elif id:
        res = await db.execute(select(SortieFonds).where(SortieFonds.id == id))
        sortie = res.scalar_one_or_none()

    if not sortie:
        return {
            "status": "NOT_FOUND",
            "message": "La référence fournie ne correspond à aucune sortie de fonds.",
        }

    requisition_numero = "-"
    if sortie.requisition_id:
        req_res = await db.execute(select(Requisition).where(Requisition.id == sortie.requisition_id))
        req = req_res.scalar_one_or_none()
        if req:
            requisition_numero = req.numero_requisition

    date_paiement = sortie.date_paiement.astimezone(timezone.utc).strftime("%Y-%m-%d") if sortie.date_paiement else None
    montant = float(sortie.montant_paye or 0)
    raw_statut = (sortie.statut or "VALIDE").strip()
    normalized = raw_statut.lower()
    audit_status = "VALID"
    if "annul" in normalized:
        audit_status = "CANCELLED"

    return {
        "status": audit_status,
        "statut_sortie": raw_statut,
        "reference_numero": sortie.reference_numero,
        "requisition_numero": requisition_numero,
        "beneficiaire": sortie.beneficiaire,
        "montant_paye": montant,
        "date_paiement": date_paiement,
        "motif_annulation": sortie.motif_annulation,
    }
