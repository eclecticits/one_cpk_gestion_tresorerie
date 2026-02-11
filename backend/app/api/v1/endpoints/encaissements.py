from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.budget import BudgetLigne
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.user import User
from app.schemas.payment import EncaissementCreate, EncaissementResponse, EncaissementsListResponse

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.encaissements")


TYPE_CLIENTS = {
    "expert_comptable",
    "client_externe",
    "banque_institution",
    "partenaire",
    "organisation",
    "autre",
}
STATUT_PAIEMENT = {"non_paye", "partiel", "complet", "avance"}
MODE_PAIEMENT = {"cash", "mobile_money", "virement"}


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


def _encaissement_to_response(enc: Encaissement, expert: ExpertComptable | None = None) -> dict[str, Any]:
    return {
        "id": str(enc.id),
        "numero_recu": enc.numero_recu,
        "type_client": enc.type_client,
        "expert_comptable_id": str(enc.expert_comptable_id) if enc.expert_comptable_id else None,
        "client_nom": enc.client_nom,
        "type_operation": enc.type_operation,
        "description": enc.description,
        "montant": enc.montant,
        "montant_total": enc.montant_total,
        "montant_paye": enc.montant_paye,
        "budget_ligne_id": enc.budget_ligne_id,
        "statut_paiement": enc.statut_paiement,
        "mode_paiement": enc.mode_paiement,
        "reference": enc.reference,
        "date_encaissement": enc.date_encaissement,
        "created_by": str(enc.created_by) if enc.created_by else None,
        "created_at": enc.created_at,
        "expert_comptable": None
        if expert is None
        else {
            "id": str(expert.id),
            "numero_ordre": expert.numero_ordre,
            "nom_denomination": expert.nom_denomination,
            "type_ec": expert.type_ec,
            "active": expert.active,
        },
    }


def _parse_order(order: str | None):
    if not order:
        return Encaissement.date_encaissement.desc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "date_encaissement": Encaissement.date_encaissement,
        "created_at": Encaissement.created_at,
        "numero_recu": Encaissement.numero_recu,
        "montant_total": Encaissement.montant_total,
        "montant_paye": Encaissement.montant_paye,
    }
    col = column_map.get(field)
    if col is None:
        return Encaissement.date_encaissement.desc()
    return col.desc() if direction.lower() == "desc" else col.asc()


@router.post("/generate-numero-recu")
async def generate_numero_recu(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    result = await db.execute(select(func.generate_recu_numero()))
    return result.scalar_one()


@router.get("", response_model=list[EncaissementResponse] | EncaissementsListResponse)
async def list_encaissements(
    include: str | None = Query(default=None, description="Relations à inclure (expert_comptable)"),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    statut_paiement: str | None = Query(default=None),
    numero_recu: str | None = Query(default=None),
    client: str | None = Query(default=None),
    type_operation: str | None = Query(default=None),
    type_client: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    expert_comptable_id: str | None = Query(default=None),
    order: str | None = Query(default=None, description="Ex: date_encaissement.desc"),
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    include_summary: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_expert = "expert_comptable" in include_parts or bool(client)
    needs_expert_join = include_expert or bool(client)

    conditions = []

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        conditions.append(Encaissement.date_encaissement >= start_dt)
    if end_dt:
        conditions.append(Encaissement.date_encaissement <= end_dt)

    if statut_paiement:
        conditions.append(Encaissement.statut_paiement == statut_paiement)
    if numero_recu:
        conditions.append(Encaissement.numero_recu.ilike(f"%{numero_recu}%"))
    if type_operation:
        conditions.append(Encaissement.type_operation == type_operation)
    if type_client:
        conditions.append(Encaissement.type_client == type_client)
    if mode_paiement:
        conditions.append(Encaissement.mode_paiement == mode_paiement)
    if expert_comptable_id:
        try:
            exp_uid = uuid.UUID(expert_comptable_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expert_comptable_id UUID")
        conditions.append(Encaissement.expert_comptable_id == exp_uid)

    if client:
        conditions.append(
            or_(
                Encaissement.client_nom.ilike(f"%{client}%"),
                ExpertComptable.nom_denomination.ilike(f"%{client}%"),
                ExpertComptable.numero_ordre.ilike(f"%{client}%"),
            )
        )

    if include_expert:
        query = select(Encaissement, ExpertComptable).outerjoin(
            ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id
        )
    else:
        query = select(Encaissement)

    if conditions:
        query = query.where(*conditions)

    query = query.order_by(_parse_order(order)).offset(offset).limit(limit)

    result = await db.execute(query)
    if include_expert:
        rows = result.all()
        logger.info(
            "encaissements list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(rows),
        )
        items = [_encaissement_to_response(enc, expert) for enc, expert in rows]
    else:
        encaissements = result.scalars().all()
        logger.info(
            "encaissements list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(encaissements),
        )
        items = [_encaissement_to_response(enc) for enc in encaissements]

    if not include_summary:
        return items

    count_query = select(func.count()).select_from(Encaissement)
    sum_query = select(
        func.coalesce(func.sum(func.coalesce(Encaissement.montant_total, Encaissement.montant, 0)), 0),
        func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0),
    ).select_from(Encaissement)
    if needs_expert_join:
        count_query = count_query.outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
        sum_query = sum_query.outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
    if conditions:
        count_query = count_query.where(*conditions)
        sum_query = sum_query.where(*conditions)

    total_count = int((await db.execute(count_query)).scalar_one() or 0)
    totals_row = (await db.execute(sum_query)).first()
    total_montant_facture = Decimal(totals_row[0] or 0) if totals_row else Decimal("0")
    total_montant_paye = Decimal(totals_row[1] or 0) if totals_row else Decimal("0")

    return EncaissementsListResponse(
        items=items,
        total=total_count,
        total_montant_facture=total_montant_facture,
        total_montant_paye=total_montant_paye,
    )


@router.post("", response_model=EncaissementResponse, status_code=status.HTTP_201_CREATED)
async def create_encaissement(
    payload: EncaissementCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if payload.type_client not in TYPE_CLIENTS:
        raise HTTPException(status_code=400, detail="type_client invalide")
    if payload.statut_paiement not in STATUT_PAIEMENT:
        raise HTTPException(status_code=400, detail="statut_paiement invalide")
    if payload.mode_paiement not in MODE_PAIEMENT:
        raise HTTPException(status_code=400, detail="mode_paiement invalide")

    montant_total = Decimal(payload.montant_total or 0)
    montant = Decimal(payload.montant or 0)
    if montant_total == 0 and montant > 0:
        montant_total = montant

    montant_paye = Decimal(payload.montant_paye or 0)
    statut_paiement = payload.statut_paiement
    if montant_paye > montant_total and statut_paiement != "avance":
        statut_paiement = "avance"
    elif montant_paye >= montant_total and montant_total > 0:
        statut_paiement = "complet"
    elif montant_paye > 0:
        statut_paiement = "partiel"
    else:
        statut_paiement = "non_paye"

    expert_uid: uuid.UUID | None = None
    if payload.type_client == "expert_comptable":
        if not payload.expert_comptable_id:
            raise HTTPException(status_code=400, detail="expert_comptable_id requis")
        try:
            expert_uid = uuid.UUID(payload.expert_comptable_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expert_comptable_id UUID")
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Expert-comptable non trouvé")
    else:
        if not payload.client_nom or not payload.client_nom.strip():
            raise HTTPException(status_code=400, detail="client_nom requis pour ce type_client")

    budget_line = None
    if payload.budget_ligne_id is None:
        raise HTTPException(status_code=400, detail="budget_ligne_id requis pour un encaissement")
    budget_res = await db.execute(select(BudgetLigne).where(BudgetLigne.id == payload.budget_ligne_id))
    budget_line = budget_res.scalar_one_or_none()
    if budget_line is None or (budget_line.type or "").upper() != "RECETTE":
        raise HTTPException(status_code=400, detail="budget_ligne_id invalide (type RECETTE requis)")
    if budget_line.active is False:
        raise HTTPException(status_code=400, detail="Rubrique budgétaire inactive")

    date_encaissement = payload.date_encaissement or datetime.now(timezone.utc)
    if isinstance(date_encaissement, str):
        parsed = _parse_datetime(date_encaissement)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_encaissement invalide")
        date_encaissement = parsed
    provided_recu = payload.numero_recu.strip() if payload.numero_recu else ""
    should_regenerate = not provided_recu
    last_error: Exception | None = None

    for attempt in range(5):
        numero_recu = provided_recu or await generate_numero_recu(user=user, db=db)
        encaissement = Encaissement(
            numero_recu=numero_recu,
            type_client=payload.type_client,
            expert_comptable_id=expert_uid,
            client_nom=None if payload.type_client == "expert_comptable" else payload.client_nom,
            type_operation=payload.type_operation,
            description=payload.description,
            montant=montant,
            montant_total=montant_total,
            montant_paye=montant_paye,
            budget_ligne_id=payload.budget_ligne_id,
            statut_paiement=statut_paiement,
            mode_paiement=payload.mode_paiement,
            reference=payload.reference,
            date_encaissement=date_encaissement,
            created_by=user.id,
        )
        db.add(encaissement)
        try:
            await db.commit()
            await db.refresh(encaissement)
            last_error = None
            break
        except IntegrityError as exc:
            last_error = exc
            await db.rollback()
            if not should_regenerate:
                break
            provided_recu = ""
            continue

    if last_error is not None:
        raise HTTPException(status_code=409, detail="numero_recu déjà utilisé")

    expert = None
    if expert_uid:
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        expert = res.scalar_one_or_none()

    return _encaissement_to_response(encaissement, expert)


@router.get("/{encaissement_id}", response_model=EncaissementResponse)
async def get_encaissement(
    encaissement_id: str,
    include: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_expert = "expert_comptable" in include_parts

    if include_expert:
        result = await db.execute(
            select(Encaissement, ExpertComptable)
            .outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
            .where(Encaissement.id == uid)
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
        enc, expert = row
        return _encaissement_to_response(enc, expert)

    result = await db.execute(select(Encaissement).where(Encaissement.id == uid))
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    return _encaissement_to_response(encaissement)
