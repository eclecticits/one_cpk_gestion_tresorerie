from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, has_permission
from app.db.session import get_db
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    RequisitionScoreBatchRequest,
    RequisitionScoreRequest,
    RequisitionScoreResponse,
    CashForecastResponse,
)
from app.services.anomaly_scoring import compute_requisition_score
from app.services.ai_chat import ask_openai
from app.services.forecasting import compute_cash_forecast

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


async def _fetch_requisition(
    db: AsyncSession,
    requisition_id: uuid.UUID,
) -> Requisition | None:
    res = await db.execute(select(Requisition).where(Requisition.id == requisition_id))
    return res.scalar_one_or_none()


async def _fetch_history_amounts(
    db: AsyncSession,
    rubrique: str,
    created_by: uuid.UUID | None,
    since: datetime,
) -> list[float]:
    stmt = (
        select(LigneRequisition.montant_total)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.created_at >= since,
                LigneRequisition.rubrique == rubrique,
            )
        )
    )
    if created_by:
        stmt = stmt.where(Requisition.created_by == created_by)
    res = await db.execute(stmt)
    return [_to_float(row[0]) for row in res.all()]


async def _count_duplicate_candidates(
    db: AsyncSession,
    requisition_id: uuid.UUID,
    amount: float,
    tolerance_pct: float = 0.03,
) -> int:
    if amount <= 0:
        return 0
    tolerance = amount * tolerance_pct
    stmt = (
        select(LigneRequisition.id)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.id != requisition_id,
                LigneRequisition.montant_total.between(amount - tolerance, amount + tolerance),
            )
        )
    )
    res = await db.execute(stmt)
    return len(res.all())


@router.post(
    "/score-requisition",
    response_model=RequisitionScoreResponse,
    dependencies=[Depends(has_permission("requisitions"))],
)
async def score_requisition(
    payload: RequisitionScoreRequest,
    db: AsyncSession = Depends(get_db),
) -> RequisitionScoreResponse:
    requisition = await _fetch_requisition(db, payload.requisition_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="Requisition not found")

    since = _utcnow() - timedelta(days=payload.lookback_days)
    # Use rubrique as category signal; take most frequent line rubrique.
    rubriques_stmt = (
        select(LigneRequisition.rubrique)
        .where(LigneRequisition.requisition_id == requisition.id)
    )
    rubriques_res = await db.execute(rubriques_stmt)
    rubriques = [row[0] for row in rubriques_res.all() if row[0]]
    rubrique = rubriques[0] if rubriques else "GENERAL"

    history_amounts = await _fetch_history_amounts(
        db=db,
        rubrique=rubrique,
        created_by=requisition.created_by,
        since=since,
    )
    duplicate_candidates = await _count_duplicate_candidates(
        db=db,
        requisition_id=requisition.id,
        amount=_to_float(requisition.montant_total),
    )
    result = compute_requisition_score(
        amount=_to_float(requisition.montant_total),
        history_amounts=history_amounts,
        duplicate_candidates=duplicate_candidates,
        min_history=payload.min_history,
    )

    segment = f"{rubrique}|{str(requisition.created_by) if requisition.created_by else 'unknown'}"
    return RequisitionScoreResponse(
        requisition_id=requisition.id,
        risk_score=result.risk_score,
        confidence_score=result.confidence_score,
        level=result.level,
        explanation=result.explanation,
        reasons=result.reasons,
        segment=segment,
        sample_size=result.sample_size,
        mean_amount=result.mean_amount,
        std_amount=result.std_amount,
        z_score=result.z_score,
        duplicate_candidates=result.duplicate_candidates,
    )


@router.post(
    "/score-requisitions",
    response_model=list[RequisitionScoreResponse],
    dependencies=[Depends(has_permission("requisitions"))],
)
async def score_requisitions(
    payload: RequisitionScoreBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> list[RequisitionScoreResponse]:
    if not payload.requisition_ids:
        return []

    results: list[RequisitionScoreResponse] = []
    for rid in payload.requisition_ids:
        response = await score_requisition(
            RequisitionScoreRequest(
                requisition_id=rid,
                lookback_days=payload.lookback_days,
                min_history=payload.min_history,
            ),
            db,
        )
        results.append(response)
    return results


@router.get(
    "/cash-forecast",
    response_model=CashForecastResponse,
)
async def cash_forecast(
    lookback_days: int = 30,
    horizon_days: int = 30,
    reserve_threshold: float = 1000.0,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CashForecastResponse:
    forecast = await compute_cash_forecast(
        db=db,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        reserve_threshold=reserve_threshold,
    )

    risk_level = "LOW"
    risk_message = "Trésorerie saine sur l'horizon projeté."
    if forecast.stress_projection <= reserve_threshold:
        risk_level = "CRITICAL"
        risk_message = "Alerte: la projection de stress passe sous le seuil de réserve."
    elif forecast.stress_projection <= reserve_threshold * 2:
        risk_level = "HIGH"
        risk_message = "Risque élevé: la marge de réserve se réduit fortement."
    elif forecast.stress_projection <= reserve_threshold * 3:
        risk_level = "MEDIUM"
        risk_message = "Surveillance recommandée: la réserve peut devenir tendue."

    return CashForecastResponse(
        solde_actuel=forecast.solde_actuel,
        lookback_days=forecast.lookback_days,
        horizon_days=forecast.horizon_days,
        reserve_threshold=forecast.reserve_threshold,
        encaissements_total=forecast.encaissements_total,
        sorties_total=forecast.sorties_total,
        net_total=forecast.net_total,
        baseline_projection=forecast.baseline_projection,
        stress_projection=forecast.stress_projection,
        pending_total=forecast.pending_total,
        pressure_ratio=forecast.pressure_ratio,
        autonomy_days=forecast.autonomy_days,
        risk_level=risk_level,
        risk_message=risk_message,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    try:
        result = await ask_openai(
            question=payload.message,
            history=[m.model_dump() for m in payload.history],
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI chat failure: {exc}") from exc

    return ChatResponse(
        answer=str(result.get("answer", "")),
        widget=result.get("widget"),
        suggestions=result.get("suggestions"),
    )
