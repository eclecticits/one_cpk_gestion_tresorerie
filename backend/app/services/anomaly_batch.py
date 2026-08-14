"""Chargements groupés pour le calcul de score d'anomalie des réquisitions.

Ces requêtes servent deux appelants : l'endpoint /ai/score-requisitions et le
contexte financier de l'assistant conversationnel. Elles vivaient dans
l'endpoint, où le chat ne pouvait pas les importer (l'endpoint importe déjà
`ask_ai`, l'import inverse serait circulaire) — d'où ce module partagé.

Toutes prennent l'ensemble des réquisitions d'un coup : la version « une requête
par réquisition » enchaînait une trentaine d'allers-retours séquentiels avant
même d'interroger le modèle.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


async def fetch_requisition_lines(
    db: AsyncSession,
    requisition_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[str]]:
    if not requisition_ids:
        return {}
    stmt = select(LigneRequisition.requisition_id, LigneRequisition.rubrique).where(
        LigneRequisition.requisition_id.in_(requisition_ids)
    )
    res = await db.execute(stmt)
    lines: dict[uuid.UUID, list[str]] = defaultdict(list)
    for requisition_id, rubrique in res.all():
        if rubrique:
            lines[requisition_id].append(rubrique)
    return lines


async def fetch_history_candidates(
    db: AsyncSession,
    rubriques: list[str],
    since: datetime,
    tenant_id: int,
) -> dict[tuple[str, uuid.UUID | None], list[float]]:
    if not rubriques:
        return {}
    stmt = (
        select(LigneRequisition.rubrique, Requisition.created_by, LigneRequisition.montant_total)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
                Requisition.created_at >= since,
                LigneRequisition.rubrique.in_(rubriques),
            )
        )
    )
    res = await db.execute(stmt)
    history_map: dict[tuple[str, uuid.UUID | None], list[float]] = defaultdict(list)
    for rubrique, created_by, amount in res.all():
        amount_value = _to_float(amount)
        history_map[(rubrique, None)].append(amount_value)
        history_map[(rubrique, created_by)].append(amount_value)
    return history_map


async def fetch_duplicate_candidates(
    db: AsyncSession,
    requisitions: list[Requisition],
    tenant_id: int,
    tolerance_pct: float = 0.03,
) -> dict[uuid.UUID, int]:
    if not requisitions:
        return {}

    amounts_by_requisition = {
        requisition.id: _to_float(requisition.montant_total)
        for requisition in requisitions
        if _to_float(requisition.montant_total) > 0
    }
    if not amounts_by_requisition:
        return {requisition.id: 0 for requisition in requisitions}

    min_amount = min(amounts_by_requisition.values())
    max_amount = max(amounts_by_requisition.values())
    lower_bound = min_amount * (1 - tolerance_pct)
    upper_bound = max_amount * (1 + tolerance_pct)

    stmt = (
        select(Requisition.id, LigneRequisition.montant_total)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.organisation_id == tenant_id,
                Requisition.is_deleted.is_(False),
                LigneRequisition.montant_total.between(lower_bound, upper_bound),
            )
        )
    )
    res = await db.execute(stmt)
    candidates = [(requisition_id, _to_float(amount)) for requisition_id, amount in res.all()]

    counts: dict[uuid.UUID, int] = {}
    for requisition_id, amount in amounts_by_requisition.items():
        tolerance = amount * tolerance_pct
        counts[requisition_id] = sum(
            1
            for candidate_requisition_id, candidate_amount in candidates
            if candidate_requisition_id != requisition_id
            and amount - tolerance <= candidate_amount <= amount + tolerance
        )
    return counts
