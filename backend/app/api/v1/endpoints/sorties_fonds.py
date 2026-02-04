from __future__ import annotations

import uuid
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.requisition import RequisitionOut
from app.schemas.sortie_fonds import SortieFondsCreate, SortieFondsOut, SortiesFondsListResponse

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.sorties_fonds")

REQUISITION_STATUTS_VALIDES = ("VALIDEE", "PAYEE", "payee", "approuvee", "validee_tresorerie")


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


def _requisition_out(req: Requisition) -> RequisitionOut:
    return RequisitionOut(
        id=str(req.id),
        numero_requisition=req.numero_requisition,
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
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


def _sortie_out(sortie: SortieFonds, requisition: Requisition | None = None) -> SortieFondsOut:
    return SortieFondsOut(
        id=str(sortie.id),
        type_sortie=sortie.type_sortie,
        requisition_id=str(sortie.requisition_id) if sortie.requisition_id else None,
        rubrique_code=sortie.rubrique_code,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
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
    total_montant_paye = (await db.execute(sum_query)).scalar_one() or 0

    return SortiesFondsListResponse(
        items=items,
        total=total_count,
        total_montant_paye=total_montant_paye,
    )


@router.post("", response_model=SortieFondsOut, status_code=status.HTTP_201_CREATED)
async def create_sortie_fonds(
    payload: SortieFondsCreate,
    user: User = Depends(get_current_user),
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

    sortie = SortieFonds(
        type_sortie=payload.type_sortie,
        requisition_id=requisition_uid,
        rubrique_code=payload.rubrique_code,
        montant_paye=payload.montant_paye,
        date_paiement=date_paiement,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        motif=payload.motif,
        beneficiaire=payload.beneficiaire,
        piece_justificative=payload.piece_justificative,
        commentaire=payload.commentaire,
        created_by=user.id,
    )
    db.add(sortie)
    await db.commit()
    await db.refresh(sortie)

    requisition: Requisition | None = None
    if sortie.requisition_id:
        req_res = await db.execute(select(Requisition).where(Requisition.id == sortie.requisition_id))
        requisition = req_res.scalar_one_or_none()

    return _sortie_out(sortie, requisition)
