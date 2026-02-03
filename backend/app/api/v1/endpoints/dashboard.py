from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    DashboardDailyStats,
    DashboardStats,
    DashboardStatsResponse,
    PeriodInfo,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_dashboard")


STATUT_PAIEMENT_INCLUS = ("complet", "partiel")
REQUISITION_STATUT_EN_ATTENTE = ("EN_ATTENTE",)


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.date()


def _end_exclusive(day: date | None) -> date | None:
    if not day:
        return None
    return day + timedelta(days=1)


@router.get("/stats", response_model=DashboardStatsResponse)
async def stats(
    period_type: str = "month",
    date_debut: str | None = None,
    date_fin: str | None = None,
    include_all_status: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardStatsResponse:
    """Return dashboard aggregates.

    This endpoint is designed to be resilient during migration:
    - If business tables are not present yet, it returns zeros.
    - Once the DB is imported, it will start returning real data.

    NOTE: Authorization will be refined once RBAC rules are fully implemented.
    """

    # Defaults
    stats_out = DashboardStats(
        total_encaissements_period=0,
        total_encaissements_jour=0,
        total_sorties_period=0,
        total_sorties_jour=0,
        solde_period=0,
        solde_actuel=0,
        solde_jour=0,
        requisitions_en_attente=0,
        note="Migration mode: returns zeros if tables are missing",
    )

    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    date_end_excl = _end_exclusive(date_end)

    logger.info("dashboard period start=%s end=%s", date_start, date_end)

    # Best-effort real stats (works only after the DB schema/data is imported)
    try:
        enc_all = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "include_all_status": include_all_status},
        )
        enc_all_v = float(enc_all.scalar_one() or 0)
    except Exception:
        return DashboardStatsResponse(
            stats=stats_out,
            daily_stats=[],
            period=PeriodInfo(start=date_start, end=date_end, label=period_type),
        )

    enc_period_total_v = 0.0
    enc_period_count_v = 0
    try:
        enc_period = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total, COUNT(*) AS count
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "date_start": date_start,
                "date_end_excl": date_end_excl,
                "include_all_status": include_all_status,
            },
        )
        row = enc_period.first()
        if row:
            enc_period_total_v = float(row.total or 0)
            enc_period_count_v = int(row.count or 0)
    except Exception:
        enc_period_total_v = 0.0
        enc_period_count_v = 0

    logger.info("ENC COUNT=%s", enc_period_count_v)
    logger.info("ENC SUM=%s", enc_period_total_v)

    sorties_all_v = 0.0
    sorties_period_total_v = 0.0
    sorties_day_total_v = 0.0
    sorties_daily_map: dict[str, float] = {}
    requisitions_en_attente_v = 0

    try:
        sorties_all = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                """
            )
        )
        sorties_all_v = float(sorties_all.scalar_one() or 0)
    except Exception:
        sorties_all_v = 0.0

    stats_out.solde_actuel = enc_all_v - sorties_all_v

    try:
        sorties_period = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE (:date_start IS NULL OR date_paiement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_paiement::date < :date_end_excl)
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        sorties_period_total_v = float(sorties_period.scalar_one() or 0)
    except Exception:
        sorties_period_total_v = 0.0

    stats_out.total_encaissements_period = enc_period_total_v
    stats_out.total_sorties_period = sorties_period_total_v
    stats_out.solde_period = enc_period_total_v - sorties_period_total_v

    try:
        sorties_period_count = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.sorties_fonds
                WHERE (:date_start IS NULL OR date_paiement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_paiement::date < :date_end_excl)
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        logger.info("sorties period count=%s", int(sorties_period_count.scalar_one() or 0))
    except Exception:
        logger.info("sorties period count=error")

    enc_day_total_v = 0.0
    enc_day_count_v = 0
    try:
        enc_day = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total, COUNT(*) AS count
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND date_encaissement::date = CURRENT_DATE
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "include_all_status": include_all_status},
        )
        row = enc_day.first()
        if row:
            enc_day_total_v = float(row.total or 0)
            enc_day_count_v = int(row.count or 0)
    except Exception:
        enc_day_total_v = 0.0
        enc_day_count_v = 0

    logger.info("ENC COUNT=%s", enc_day_count_v)
    logger.info("ENC SUM=%s", enc_day_total_v)

    try:
        sorties_day = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE date_paiement::date = CURRENT_DATE
                """
            )
        )
        sorties_day_total_v = float(sorties_day.scalar_one() or 0)
    except Exception:
        sorties_day_total_v = 0.0

    stats_out.total_encaissements_jour = enc_day_total_v
    stats_out.total_sorties_jour = sorties_day_total_v
    stats_out.solde_jour = enc_day_total_v - sorties_day_total_v

    # Daily stats for last 7 days (inclusive)
    enc_daily_map: dict[str, float] = {}
    sorties_daily_map: dict[str, float] = {}
    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT date_encaissement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND date_encaissement::date >= CURRENT_DATE - INTERVAL '6 days'
                GROUP BY day
                ORDER BY day DESC
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "include_all_status": include_all_status},
        )
        for row in enc_daily:
            day = row.day
            if day is None:
                continue
            enc_daily_map[day.isoformat()] = float(row.total or 0)
    except Exception:
        enc_daily_map = {}

    try:
        sorties_daily = await db.execute(
            text(
                """
                SELECT date_paiement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE date_paiement::date >= CURRENT_DATE - INTERVAL '6 days'
                GROUP BY day
                ORDER BY day DESC
                """
            )
        )
        for row in sorties_daily:
            day = row.day
            if day is None:
                continue
            sorties_daily_map[day.isoformat()] = float(row.total or 0)
    except Exception:
        sorties_daily_map = {}

    now = datetime.now(timezone.utc)
    daily_stats: list[DashboardDailyStats] = []
    for i in range(0, 7):
        day = (now - timedelta(days=i)).date().isoformat()
        enc_v = enc_daily_map.get(day, 0.0)
        sor_v = sorties_daily_map.get(day, 0.0)
        daily_stats.append(
            DashboardDailyStats(
                date=date.fromisoformat(day),
                encaissements=enc_v,
                sorties=sor_v,
                solde=enc_v - sor_v,
            )
        )

    try:
        req_pending = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE status = ANY(:status_list)
                """
            ),
            {"status_list": list(REQUISITION_STATUT_EN_ATTENTE)},
        )
        requisitions_en_attente_v = int(req_pending.scalar_one() or 0)
    except Exception:
        requisitions_en_attente_v = 0

    stats_out.requisitions_en_attente = requisitions_en_attente_v

    return DashboardStatsResponse(
        stats=stats_out,
        daily_stats=daily_stats,
        period=PeriodInfo(start=date_start, end=date_end, label=period_type),
    )
