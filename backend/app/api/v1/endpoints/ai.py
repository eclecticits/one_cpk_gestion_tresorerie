from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission, require_ai_enabled
from app.db.session import get_db
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ExpenseBatchClassifyRequest,
    ExpenseBatchClassifyResult,
    ExpenseClassifyRequest,
    ExpenseClassifyResponse,
    RequisitionScoreBatchRequest,
    RequisitionScoreRequest,
    RequisitionScoreResponse,
    CashForecastResponse,
)
from app.services.anomaly_batch import (
    fetch_duplicate_candidates,
    fetch_history_candidates,
    fetch_requisition_lines,
)
from app.services.anomaly_scoring import compute_requisition_score
from app.services.ai_chat import ask_ai
from app.services.ai_batch_service import AIBatchProcessor
from app.services.ai_syscebnl import classify_expense_with_gemma
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
    tenant_id: int,
) -> Requisition | None:
    res = await db.execute(
        select(Requisition).where(
            and_(
                Requisition.id == requisition_id,
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
    )
    return res.scalar_one_or_none()


# Chargements groupés partagés avec l'assistant conversationnel : voir
# app/services/anomaly_batch.py (le chat ne peut pas importer cet endpoint,
# qui importe déjà ask_ai).
_fetch_requisition_lines = fetch_requisition_lines
_fetch_history_candidates = fetch_history_candidates
_fetch_duplicate_candidates = fetch_duplicate_candidates


def _build_score_response(
    requisition: Requisition,
    rubrique: str,
    history_amounts: list[float],
    duplicate_candidates: int,
    min_history: int,
) -> RequisitionScoreResponse:
    result = compute_requisition_score(
        amount=_to_float(requisition.montant_total),
        history_amounts=history_amounts,
        duplicate_candidates=duplicate_candidates,
        min_history=min_history,
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


async def _score_requisitions_batch(
    db: AsyncSession,
    requisitions: list[Requisition],
    lookback_days: int,
    min_history: int,
    tenant_id: int,
) -> list[RequisitionScoreResponse]:
    if not requisitions:
        return []

    requisition_ids = [requisition.id for requisition in requisitions]
    lines_map = await _fetch_requisition_lines(db, requisition_ids)
    rubriques = [values[0] for values in lines_map.values() if values]
    since = _utcnow() - timedelta(days=lookback_days)
    history_map = await _fetch_history_candidates(db, rubriques, since, tenant_id)
    duplicate_counts = await _fetch_duplicate_candidates(db, requisitions, tenant_id)

    responses: list[RequisitionScoreResponse] = []
    for requisition in requisitions:
        rubriques_for_req = lines_map.get(requisition.id) or []
        rubrique = rubriques_for_req[0] if rubriques_for_req else "GENERAL"
        history_amounts = history_map.get((rubrique, requisition.created_by))
        if history_amounts is None:
            history_amounts = history_map.get((rubrique, None), [])
        responses.append(
            _build_score_response(
                requisition=requisition,
                rubrique=rubrique,
                history_amounts=history_amounts,
                duplicate_candidates=duplicate_counts.get(requisition.id, 0),
                min_history=min_history,
            )
        )
    return responses


@router.post(
    "/score-requisition",
    response_model=RequisitionScoreResponse,
    dependencies=[Depends(has_permission("requisitions")), Depends(require_ai_enabled)],
)
async def score_requisition(
    payload: RequisitionScoreRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> RequisitionScoreResponse:
    requisition = await _fetch_requisition(db, payload.requisition_id, tenant_id)
    if not requisition:
        raise HTTPException(status_code=404, detail="Requisition not found")
    responses = await _score_requisitions_batch(
        db=db,
        requisitions=[requisition],
        lookback_days=payload.lookback_days,
        min_history=payload.min_history,
        tenant_id=tenant_id,
    )
    return responses[0]


@router.post(
    "/score-requisitions",
    response_model=list[RequisitionScoreResponse],
    dependencies=[Depends(has_permission("requisitions")), Depends(require_ai_enabled)],
)
async def score_requisitions(
    payload: RequisitionScoreBatchRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[RequisitionScoreResponse]:
    if not payload.requisition_ids:
        return []

    unique_ids = list(dict.fromkeys(payload.requisition_ids))
    requisitions_res = await db.execute(
        select(Requisition)
        .where(
            and_(
                Requisition.id.in_(unique_ids),
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
            )
        )
    )
    requisitions = requisitions_res.scalars().all()
    requisitions_by_id = {requisition.id: requisition for requisition in requisitions}

    missing_ids = [requisition_id for requisition_id in unique_ids if requisition_id not in requisitions_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{len(missing_ids)} requisition(s) introuvable(s) pour ce tenant",
        )

    ordered_requisitions = [requisitions_by_id[requisition_id] for requisition_id in unique_ids]
    return await _score_requisitions_batch(
        db=db,
        requisitions=ordered_requisitions,
        lookback_days=payload.lookback_days,
        min_history=payload.min_history,
        tenant_id=tenant_id,
    )


@router.get(
    "/cash-forecast",
    response_model=CashForecastResponse,
    dependencies=[Depends(has_any_permission(["dashboard", "reports", "sorties_fonds", "encaissements"]))],
)
async def cash_forecast(
    lookback_days: int = 30,
    horizon_days: int = 30,
    reserve_threshold: float = 1000.0,
    user=Depends(require_ai_enabled),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CashForecastResponse:
    forecast = await compute_cash_forecast(
        db=db,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        reserve_threshold=reserve_threshold,
        tenant_id=tenant_id,
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


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(has_any_permission(["dashboard", "reports", "sorties_fonds", "encaissements"]))],
)
async def chat(
    payload: ChatRequest,
    user=Depends(require_ai_enabled),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ChatResponse:
    try:
        result = await ask_ai(
            question=payload.message,
            history=[m.model_dump() for m in payload.history],
            db=db,
            tenant_id=tenant_id,
            user_id=getattr(user, "id", None),
            # L'utilisateur complet, et pas seulement son id : le contexte est
            # cloisonné selon ses permissions de menu.
            user=user,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI chat failure: {exc}") from exc

    return ChatResponse(
        answer=str(result.get("answer", "")),
        widget=result.get("widget"),
        suggestions=result.get("suggestions"),
    )


@router.post(
    "/classify-expense",
    response_model=ExpenseClassifyResponse,
    dependencies=[
        Depends(
            has_any_permission(
                ["dashboard", "reports", "sorties_fonds", "encaissements", "requisitions", "budget"]
            )
        ),
        Depends(require_ai_enabled),
    ],
)
async def classify_expense(
    payload: ExpenseClassifyRequest,
) -> ExpenseClassifyResponse:
    result = await classify_expense_with_gemma(payload.description)
    return ExpenseClassifyResponse(**result)


@router.post(
    "/classify-expense-batch",
    response_model=list[ExpenseBatchClassifyResult],
    dependencies=[
        Depends(
            has_any_permission(
                ["dashboard", "reports", "sorties_fonds", "encaissements", "requisitions", "budget"]
            )
        ),
        Depends(require_ai_enabled),
    ],
)
async def classify_expense_batch(
    payload: ExpenseBatchClassifyRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseBatchClassifyResult]:
    if not payload.transactions:
        return []
    results = await AIBatchProcessor.process_batch(
        [t.model_dump() for t in payload.transactions],
        db=db,
        org_id=user.organisation_id,
    )
    return [ExpenseBatchClassifyResult(**item) for item in results]
