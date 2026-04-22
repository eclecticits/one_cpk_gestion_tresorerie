from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_current_tenant_id
from app.models.encaissement import Encaissement
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds


@dataclass(slots=True)
class CashForecast:
    solde_actuel: float
    lookback_days: int
    horizon_days: int
    reserve_threshold: float
    encaissements_total: float
    sorties_total: float
    net_total: float
    baseline_projection: float
    stress_projection: float
    pending_total: float
    pressure_ratio: float
    autonomy_days: int | None


PENDING_REQUISITION_STATUSES = (
    "EN_ATTENTE_COMMISSION",
    "EN_ATTENTE",
    "AUTORISEE",
    "APPROUVEE",
    "PENDING_VALIDATION_IMPORT",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


async def compute_cash_forecast(
    db: AsyncSession,
    lookback_days: int = 30,
    horizon_days: int = 30,
    reserve_threshold: float = 1000.0,
    tenant_id: int | None = None,
) -> CashForecast:
    now = _utcnow()
    since = now - timedelta(days=lookback_days)
    scoped_tenant_id = tenant_id if tenant_id is not None else get_current_tenant_id()

    enc_conditions = [Encaissement.est_proforma.is_(False)]
    sorties_conditions = [(SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE")]
    pending_conditions = [func.upper(Requisition.status).in_(PENDING_REQUISITION_STATUSES)]
    if scoped_tenant_id is not None:
        enc_conditions.append(Encaissement.organisation_id == scoped_tenant_id)
        sorties_conditions.append(SortieFonds.organisation_id == scoped_tenant_id)
        pending_conditions.append(Requisition.organisation_id == scoped_tenant_id)

    enc_sum_stmt = select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_percu, 0)), 0)).where(
        Encaissement.date_encaissement >= since,
        *enc_conditions,
    )
    enc_sum_res = await db.execute(enc_sum_stmt)
    enc_sum = _to_float(enc_sum_res.scalar_one() or 0)

    sorties_sum_stmt = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).where(
        and_(
            *sorties_conditions,
            func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at) >= since,
        )
    )
    sorties_sum_res = await db.execute(sorties_sum_stmt)
    sorties_sum = _to_float(sorties_sum_res.scalar_one() or 0)

    enc_all_stmt = select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_percu, 0)), 0)).where(
        *enc_conditions
    )
    enc_all_res = await db.execute(enc_all_stmt)
    enc_all = _to_float(enc_all_res.scalar_one() or 0)

    sorties_all_stmt = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).where(
        *sorties_conditions
    )
    sorties_all_res = await db.execute(sorties_all_stmt)
    sorties_all = _to_float(sorties_all_res.scalar_one() or 0)

    solde_actuel = enc_all - sorties_all

    pending_stmt = select(func.coalesce(func.sum(func.coalesce(Requisition.montant_total, 0)), 0)).where(
        *pending_conditions
    )
    pending_res = await db.execute(pending_stmt)
    pending_total = _to_float(pending_res.scalar_one() or 0)

    net_total = enc_sum - sorties_sum
    horizon_factor = float(horizon_days) / float(lookback_days or 1)
    baseline_projection = solde_actuel + (net_total * horizon_factor)
    stress_projection = baseline_projection - pending_total

    pressure_ratio = 0.0
    if baseline_projection > 0:
        pressure_ratio = min(1.0, pending_total / baseline_projection)

    daily_net = net_total / float(lookback_days or 1)
    autonomy_days: int | None = None
    if daily_net < 0:
        cushion = max(0.0, stress_projection - reserve_threshold)
        autonomy_days = int(cushion / abs(daily_net)) if abs(daily_net) > 0 else 0

    return CashForecast(
        solde_actuel=solde_actuel,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        reserve_threshold=reserve_threshold,
        encaissements_total=enc_sum,
        sorties_total=sorties_sum,
        net_total=net_total,
        baseline_projection=baseline_projection,
        stress_projection=stress_projection,
        pending_total=pending_total,
        pressure_ratio=pressure_ratio,
        autonomy_days=autonomy_days,
    )
