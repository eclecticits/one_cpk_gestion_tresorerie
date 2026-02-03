from __future__ import annotations

import uuid
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.user import User
from app.schemas.requisition import RequisitionCreate, RequisitionOut, RequisitionUpdate, RequisitionWithUserOut

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.requisitions")


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


def _requisition_out(
    req: Requisition,
    *,
    demandeur: User | None = None,
    validateur: User | None = None,
    approbateur: User | None = None,
    caissier: User | None = None,
) -> dict[str, Any]:
    base = {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": float(req.montant_total or 0),
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
        "created_at": req.created_at,
        "updated_at": req.updated_at,
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
    today = datetime.now(timezone.utc).date()
    prefix = f"REQ-{today:%Y%m%d}-"
    result = await db.execute(
        select(func.max(Requisition.numero_requisition)).where(Requisition.numero_requisition.like(f"{prefix}%"))
    )
    max_num = result.scalar_one_or_none()
    next_index = 1
    if max_num:
        try:
            next_index = int(str(max_num).split("-")[-1]) + 1
        except (ValueError, IndexError):
            next_index = 1
    return f"{prefix}{next_index:04d}"


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

    return [
        _requisition_out(
            r,
            demandeur=users_map.get(r.created_by) if "demandeur" in include_parts else None,
            validateur=users_map.get(r.validee_par) if "validateur" in include_parts else None,
            approbateur=users_map.get(r.approuvee_par) if "approbateur" in include_parts else None,
            caissier=users_map.get(r.payee_par) if "caissier" in include_parts else None,
        )
        for r in requisitions
    ]


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

    req = Requisition(
        numero_requisition=payload.numero_requisition,
        objet=payload.objet,
        mode_paiement=payload.mode_paiement,
        type_requisition=payload.type_requisition,
        montant_total=payload.montant_total,
        status=status_value,
        created_by=created_by,
        a_valoir=bool(payload.a_valoir),
        instance_beneficiaire=payload.instance_beneficiaire,
        notes_a_valoir=payload.notes_a_valoir,
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
