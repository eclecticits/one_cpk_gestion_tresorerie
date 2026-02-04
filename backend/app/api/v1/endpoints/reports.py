from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.reports import (
    PeriodInfo,
    ReportAvailability,
    ReportBreakdownCount,
    ReportBreakdownCountTotal,
    ReportBreakdowns,
    ReportDailyStats,
    ReportModePaiementBreakdown,
    ReportRequisitionsSummary,
    ReportSummaryResponse,
    ReportSummaryStats,
    ReportTotals,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_reports")

STATUT_PAIEMENT_INCLUS = ("complet", "partiel")
REQUISITION_STATUT_EN_ATTENTE = ("EN_ATTENTE", "A_VALIDER")
REQUISITION_STATUT_APPROUVEE = ("VALIDEE",)


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.date()


def _daily_range(date_start: date | None, date_end: date | None) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    end = date_end or today
    start = date_start or (end - timedelta(days=6))
    if start > end:
        start, end = end, start
    return start, end


def _end_exclusive(day: date | None) -> date | None:
    if not day:
        return None
    return day + timedelta(days=1)


@router.get("/summary", response_model=ReportSummaryResponse)
async def summary(
    date_debut: str | None = None,
    date_fin: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportSummaryResponse:
    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    date_end_excl = _end_exclusive(date_end)
    daily_start, daily_end = _daily_range(date_start, date_end)

    availability = ReportAvailability(encaissements=True, sorties=True, requisitions=True)

    logger.info("reports period start=%s end=%s", date_start, date_end)

    totals = ReportTotals(encaissements_total=Decimal("0"), sorties_total=Decimal("0"), solde=Decimal("0"))
    par_jour: list[ReportDailyStats] = []
    par_statut_paiement: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_enc: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_sorties: list[ReportBreakdownCountTotal] = []
    par_type_operation: list[ReportBreakdownCountTotal] = []
    par_statut_requisition: list[ReportBreakdownCount] = []
    requisitions_summary = ReportRequisitionsSummary(total=0, en_attente=0, approuvees=0)

    try:
        enc_total = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE statut_paiement = ANY(:statuts)
                  AND (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "date_start": date_start,
                "date_end_excl": date_end_excl,
            },
        )
        totals.encaissements_total = Decimal(enc_total.scalar_one() or 0)
    except Exception:
        availability.encaissements = False
        totals.encaissements_total = Decimal("0")

    try:
        enc_statut = await db.execute(
            text(
                """
                SELECT statut_paiement AS statut,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                GROUP BY statut_paiement
                ORDER BY statut_paiement
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        par_statut_paiement = [
            ReportBreakdownCountTotal(
                key=row.statut,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_statut
        ]
    except Exception:
        availability.encaissements = False
        par_statut_paiement = []

    try:
        enc_modes = await db.execute(
            text(
                """
                SELECT mode_paiement AS mode,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE statut_paiement = ANY(:statuts)
                  AND (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                GROUP BY mode_paiement
                ORDER BY mode_paiement
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "date_start": date_start,
                "date_end_excl": date_end_excl,
            },
        )
        par_mode_paiement_enc = [
            ReportBreakdownCountTotal(
                key=row.mode,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_modes
        ]
    except Exception:
        availability.encaissements = False
        par_mode_paiement_enc = []

    try:
        enc_types = await db.execute(
            text(
                """
                SELECT type_operation AS type,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE statut_paiement = ANY(:statuts)
                  AND (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                GROUP BY type_operation
                ORDER BY type_operation
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "date_start": date_start,
                "date_end_excl": date_end_excl,
            },
        )
        par_type_operation = [
            ReportBreakdownCountTotal(
                key=row.type,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_types
        ]
    except Exception:
        availability.encaissements = False
        par_type_operation = []

    sorties_daily_map: dict[str, Decimal] = {}
    enc_daily_map: dict[str, Decimal] = {}

    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT date_encaissement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE statut_paiement = ANY(:statuts)
                  AND date_encaissement::date >= :daily_start
                  AND date_encaissement::date <= :daily_end
                GROUP BY day
                ORDER BY day
                """
            ),
            {"statuts": list(STATUT_PAIEMENT_INCLUS), "daily_start": daily_start, "daily_end": daily_end},
        )
        for row in enc_daily:
            if row.day:
                enc_daily_map[row.day.isoformat()] = Decimal(row.total or 0)
    except Exception:
        availability.encaissements = False
        enc_daily_map = {}

    try:
        sorties_total = await db.execute(
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
        totals.sorties_total = Decimal(sorties_total.scalar_one() or 0)
    except Exception:
        availability.sorties = False
        totals.sorties_total = Decimal("0")

    try:
        sorties_modes = await db.execute(
            text(
                """
                SELECT mode_paiement AS mode,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE (:date_start IS NULL OR date_paiement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_paiement::date < :date_end_excl)
                GROUP BY mode_paiement
                ORDER BY mode_paiement
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        par_mode_paiement_sorties = [
            ReportBreakdownCountTotal(
                key=row.mode,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in sorties_modes
        ]
    except Exception:
        availability.sorties = False
        par_mode_paiement_sorties = []

    try:
        sorties_daily = await db.execute(
            text(
                """
                SELECT date_paiement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE date_paiement::date >= :daily_start
                  AND date_paiement::date <= :daily_end
                GROUP BY day
                ORDER BY day
                """
            ),
            {"daily_start": daily_start, "daily_end": daily_end},
        )
        for row in sorties_daily:
            if row.day:
                sorties_daily_map[row.day.isoformat()] = Decimal(row.total or 0)
    except Exception:
        availability.sorties = False
        sorties_daily_map = {}

    current = daily_start
    while current <= daily_end:
        key = current.isoformat()
        enc_v = enc_daily_map.get(key, Decimal("0"))
        sor_v = sorties_daily_map.get(key, Decimal("0"))
        par_jour.append(
            ReportDailyStats(
                date=current,
                encaissements=enc_v,
                sorties=sor_v,
                solde=enc_v - sor_v,
            )
        )
        current += timedelta(days=1)

    try:
        req_total = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE (:date_start IS NULL OR created_at::date >= :date_start)
                  AND (:date_end IS NULL OR created_at::date <= :date_end)
                """
            ),
            {"date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.total = int(req_total.scalar_one() or 0)
    except Exception:
        availability.requisitions = False
        requisitions_summary.total = 0

    try:
        req_pending = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE status = ANY(:status_list)
                  AND (:date_start IS NULL OR created_at::date >= :date_start)
                  AND (:date_end IS NULL OR created_at::date <= :date_end)
                """
            ),
            {"status_list": list(REQUISITION_STATUT_EN_ATTENTE), "date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.en_attente = int(req_pending.scalar_one() or 0)
    except Exception:
        availability.requisitions = False
        requisitions_summary.en_attente = 0

    try:
        req_approved = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE status = ANY(:status_list)
                  AND (:date_start IS NULL OR created_at::date >= :date_start)
                  AND (:date_end IS NULL OR created_at::date <= :date_end)
                """
            ),
            {"status_list": list(REQUISITION_STATUT_APPROUVEE), "date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.approuvees = int(req_approved.scalar_one() or 0)
    except Exception:
        availability.requisitions = False
        requisitions_summary.approuvees = 0

    try:
        req_by_status = await db.execute(
            text(
                """
                SELECT status AS statut, COUNT(*) AS count
                FROM public.requisitions
                WHERE (:date_start IS NULL OR created_at::date >= :date_start)
                  AND (:date_end IS NULL OR created_at::date <= :date_end)
                GROUP BY status
                ORDER BY status
                """
            ),
            {"date_start": date_start, "date_end": date_end},
        )
        par_statut_requisition = [
            ReportBreakdownCount(key=row.statut, count=int(row.count or 0))
            for row in req_by_status
        ]
    except Exception:
        availability.requisitions = False
        par_statut_requisition = []

    totals.solde = totals.encaissements_total - totals.sorties_total

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

    stats = ReportSummaryStats(
        totals=totals,
        breakdowns=ReportBreakdowns(
            par_statut_paiement=par_statut_paiement,
            par_mode_paiement=ReportModePaiementBreakdown(
                encaissements=par_mode_paiement_enc,
                sorties=par_mode_paiement_sorties,
            ),
            par_type_operation=par_type_operation,
            par_statut_requisition=par_statut_requisition,
            requisitions=requisitions_summary,
        ),
        availability=availability,
    )

    return ReportSummaryResponse(
        stats=stats,
        daily_stats=par_jour,
        period=PeriodInfo(start=daily_start, end=daily_end, label="custom"),
    )
