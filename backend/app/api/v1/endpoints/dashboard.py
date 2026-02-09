from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
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
REQUISITION_STATUT_EN_ATTENTE = ("EN_ATTENTE", "A_VALIDER", "AUTORISEE")


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
        total_encaissements_period=Decimal("0"),
        total_encaissements_jour=Decimal("0"),
        total_sorties_period=Decimal("0"),
        total_sorties_jour=Decimal("0"),
        solde_period=Decimal("0"),
        solde_actuel=Decimal("0"),
        solde_jour=Decimal("0"),
        requisitions_en_attente=0,
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
                SELECT COALESCE(SUM(COALESCE(montant_paye, montant, 0)),0) AS total
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "include_all_status": include_all_status},
        )
        enc_all_v = Decimal(enc_all.scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Encaissements global): %s", exc, exc_info=True)
        return DashboardStatsResponse(
            stats=stats_out,
            daily_stats=[],
            period=PeriodInfo(start=date_start, end=date_end, label=period_type),
        )

    enc_period_total_v = Decimal("0")
    enc_period_count_v = 0
    try:
        enc_period = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(COALESCE(montant_paye, montant, 0)),0) AS total, COUNT(*) AS count
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
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
            enc_period_total_v = Decimal(row.total or 0)
            enc_period_count_v = int(row.count or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Encaissements période): %s", exc, exc_info=True)
        enc_period_total_v = Decimal("0")
        enc_period_count_v = 0

    logger.info("ENC_ALL=%s", enc_all_v)
    logger.info(
        "ENC_PERIOD=%s COUNT=%s start=%s end_excl=%s",
        enc_period_total_v,
        enc_period_count_v,
        date_start,
        date_end_excl,
    )

    sorties_all_v = Decimal("0")
    sorties_period_total_v = Decimal("0")
    sorties_day_total_v = Decimal("0")
    sorties_daily_map: dict[str, Decimal] = {}
    requisitions_en_attente_v = 0

    try:
        sorties_all = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(COALESCE(montant_paye, 0)),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                """
            )
        )
        sorties_all_v = Decimal(sorties_all.scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties global): %s", exc, exc_info=True)
        sorties_all_v = Decimal("0")

    stats_out.solde_actuel = enc_all_v - sorties_all_v
    logger.info("SORTIES_ALL=%s", sorties_all_v)

    try:
        sorties_period = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(COALESCE(montant_paye, 0)),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:date_start AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        sorties_period_total_v = Decimal(sorties_period.scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties période): %s", exc, exc_info=True)
        sorties_period_total_v = Decimal("0")

    logger.info("SORTIES_PERIOD=%s", sorties_period_total_v)

    stats_out.total_encaissements_period = enc_period_total_v
    stats_out.total_sorties_period = sorties_period_total_v
    stats_out.solde_period = enc_period_total_v - sorties_period_total_v

    try:
        sorties_period_count = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:date_start AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        logger.info("sorties period count=%s", int(sorties_period_count.scalar_one() or 0))
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties période count): %s", exc, exc_info=True)

    enc_day_total_v = Decimal("0")
    enc_day_count_v = 0
    try:
        enc_day = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(COALESCE(montant_paye, montant, 0)),0) AS total, COUNT(*) AS count
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND CAST(date_encaissement AS date) = CURRENT_DATE
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "include_all_status": include_all_status},
        )
        row = enc_day.first()
        if row:
            enc_day_total_v = Decimal(row.total or 0)
            enc_day_count_v = int(row.count or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Encaissements jour): %s", exc, exc_info=True)
        enc_day_total_v = Decimal("0")
        enc_day_count_v = 0

    logger.info("ENC DAY COUNT=%s", enc_day_count_v)
    logger.info("ENC DAY SUM=%s", enc_day_total_v)

    try:
        sorties_day = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(COALESCE(montant_paye, 0)),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND CAST(COALESCE(date_paiement, created_at) AS date) = CURRENT_DATE
                """
            )
        )
        sorties_day_total_v = Decimal(sorties_day.scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties jour): %s", exc, exc_info=True)
        sorties_day_total_v = Decimal("0")

    stats_out.total_encaissements_jour = enc_day_total_v
    stats_out.total_sorties_jour = sorties_day_total_v
    stats_out.solde_jour = enc_day_total_v - sorties_day_total_v

    logger.info("SOLDE_ACTUEL=%s SOLDE_PERIOD=%s", stats_out.solde_actuel, stats_out.solde_period)

    # Daily stats for last 7 days (inclusive)
    enc_daily_map: dict[str, Decimal] = {}
    sorties_daily_map: dict[str, Decimal] = {}
    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT CAST(date_encaissement AS date) AS day, COALESCE(SUM(COALESCE(montant_paye, montant, 0)),0) AS total
                FROM public.encaissements
                WHERE (:include_all_status OR statut_paiement = ANY(:statuts))
                  AND CAST(date_encaissement AS date) >= CURRENT_DATE - INTERVAL '6 days'
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
            enc_daily_map[day.isoformat()] = Decimal(row.total or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Encaissements 7 jours): %s", exc, exc_info=True)
        enc_daily_map = {}

    try:
        sorties_daily = await db.execute(
            text(
                """
                SELECT CAST(COALESCE(date_paiement, created_at) AS date) AS day, COALESCE(SUM(COALESCE(montant_paye, 0)),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND CAST(COALESCE(date_paiement, created_at) AS date) >= CURRENT_DATE - INTERVAL '6 days'
                GROUP BY day
                ORDER BY day DESC
                """
            )
        )
        for row in sorties_daily:
            day = row.day
            if day is None:
                continue
            sorties_daily_map[day.isoformat()] = Decimal(row.total or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties 7 jours): %s", exc, exc_info=True)
        sorties_daily_map = {}

    now = datetime.now(timezone.utc)
    daily_stats: list[DashboardDailyStats] = []
    for i in range(0, 7):
        day = (now - timedelta(days=i)).date().isoformat()
        enc_v = enc_daily_map.get(day, Decimal("0"))
        sor_v = sorties_daily_map.get(day, Decimal("0"))
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
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Réquisitions en attente): %s", exc, exc_info=True)
        requisitions_en_attente_v = 0

    stats_out.requisitions_en_attente = requisitions_en_attente_v

    return DashboardStatsResponse(
        stats=stats_out,
        daily_stats=daily_stats,
        period=PeriodInfo(start=date_start, end=date_end, label=period_type),
    )
