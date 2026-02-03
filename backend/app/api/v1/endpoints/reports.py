from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

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

STATUT_PAIEMENT_INCLUS = ("COMPLET", "PARTIEL")
REQUISITION_STATUT_EN_ATTENTE = ("EN_ATTENTE", "A_VALIDER", "PENDING")
REQUISITION_STATUT_APPROUVEE = ("VALIDEE", "APPROUVEE", "VALIDATED", "APPROVED")
REQUISITION_STATUT_REJETEE = ("REJETEE", "REJECTED")
REQUISITION_STATUT_ANNULEE = ("ANNULEE", "CANCELED", "CANCELLED")


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _daily_range(date_start: date | None, date_end: date | None) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    end = date_end or today
    start = date_start or (end - timedelta(days=6))
    return (start, end) if start <= end else (end, start)


def _end_exclusive(day: date | None) -> date | None:
    if not day:
        return None
    return day + timedelta(days=1)


def _to_decimal(value: object | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


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

    totals = ReportTotals()
    availability = ReportAvailability(encaissements=True, sorties=True, requisitions=True)
    req_summary = ReportRequisitionsSummary(
        total=0,
        en_attente=0,
        approuvees=0,
        rejetees=0,
        annulees=0,
    )
    par_statut_requisition: list[ReportBreakdownCount] = []
    par_statut_paiement: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_enc: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_sorties: list[ReportBreakdownCountTotal] = []
    par_type_operation: list[ReportBreakdownCountTotal] = []
    par_jour: list[ReportDailyStats] = []

    try:
        if date_start:
            q_init = await db.execute(
                text(
                    """
                    SELECT
                        (SELECT COALESCE(SUM(montant_paye), 0)
                         FROM public.encaissements
                         WHERE UPPER(statut_paiement) = ANY(:statuts)
                           AND date_encaissement::date < :date_start)
                      -
                        (SELECT COALESCE(SUM(montant_paye), 0)
                         FROM public.sorties_fonds
                         WHERE date_paiement::date < :date_start)
                    AS solde_initial
                    """
                ),
                {"statuts": list(STATUT_PAIEMENT_INCLUS), "date_start": date_start},
            )
            totals.solde_initial = _to_decimal(q_init.scalar_one())
    except Exception as exc:
        logger.error("Solde initial error: %s", exc)

    try:
        enc_res = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye), 0) AS encaissements_total
                FROM public.encaissements
                WHERE UPPER(statut_paiement) = ANY(:statuts)
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
        totals.encaissements_total = _to_decimal(enc_res.scalar_one())

        sor_res = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye), 0) AS sorties_total
                FROM public.sorties_fonds
                WHERE (:date_start IS NULL OR date_paiement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_paiement::date < :date_end_excl)
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        totals.sorties_total = _to_decimal(sor_res.scalar_one())
    except Exception as exc:
        availability.encaissements = False
        availability.sorties = False
        logger.error("Flux financiers error: %s", exc)

    totals.flux_periode = totals.encaissements_total - totals.sorties_total
    totals.solde_final = totals.solde_initial + totals.flux_periode

    try:
        enc_statut = await db.execute(
            text(
                """
                SELECT UPPER(statut_paiement) AS statut,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE (:date_start IS NULL OR date_encaissement::date >= :date_start)
                  AND (:date_end_excl IS NULL OR date_encaissement::date < :date_end_excl)
                GROUP BY UPPER(statut_paiement)
                ORDER BY UPPER(statut_paiement)
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        par_statut_paiement = [
            ReportBreakdownCountTotal(
                key=row.statut,
                count=int(row.count or 0),
                total=_to_decimal(row.total),
            )
            for row in enc_statut
        ]
    except Exception as exc:
        availability.encaissements = False
        par_statut_paiement = []
        logger.error("Encaissements par statut error: %s", exc)

    try:
        enc_modes = await db.execute(
            text(
                """
                SELECT mode_paiement AS mode,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE UPPER(statut_paiement) = ANY(:statuts)
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
                total=_to_decimal(row.total),
            )
            for row in enc_modes
        ]
    except Exception as exc:
        availability.encaissements = False
        par_mode_paiement_enc = []
        logger.error("Encaissements par mode error: %s", exc)

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
                total=_to_decimal(row.total),
            )
            for row in sorties_modes
        ]
    except Exception as exc:
        availability.sorties = False
        par_mode_paiement_sorties = []
        logger.error("Sorties par mode error: %s", exc)

    try:
        enc_types = await db.execute(
            text(
                """
                SELECT type_operation AS type,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE UPPER(statut_paiement) = ANY(:statuts)
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
                total=_to_decimal(row.total),
            )
            for row in enc_types
        ]
    except Exception as exc:
        availability.encaissements = False
        par_type_operation = []
        logger.error("Encaissements par type error: %s", exc)

    enc_daily_map: dict[str, Decimal] = {}
    sorties_daily_map: dict[str, Decimal] = {}
    daily_end_excl = _end_exclusive(daily_end)

    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT date_encaissement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE UPPER(statut_paiement) = ANY(:statuts)
                  AND date_encaissement::date >= :daily_start
                  AND date_encaissement::date < :daily_end_excl
                GROUP BY day
                ORDER BY day
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "daily_start": daily_start,
                "daily_end_excl": daily_end_excl,
            },
        )
        for row in enc_daily:
            if row.day:
                enc_daily_map[row.day.isoformat()] = _to_decimal(row.total)
    except Exception as exc:
        availability.encaissements = False
        enc_daily_map = {}
        logger.error("Encaissements daily error: %s", exc)

    try:
        sorties_daily = await db.execute(
            text(
                """
                SELECT date_paiement::date AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE date_paiement::date >= :daily_start
                  AND date_paiement::date < :daily_end_excl
                GROUP BY day
                ORDER BY day
                """
            ),
            {"daily_start": daily_start, "daily_end_excl": daily_end_excl},
        )
        for row in sorties_daily:
            if row.day:
                sorties_daily_map[row.day.isoformat()] = _to_decimal(row.total)
    except Exception as exc:
        availability.sorties = False
        sorties_daily_map = {}
        logger.error("Sorties daily error: %s", exc)

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
                solde_journalier=enc_v - sor_v,
            )
        )
        current += timedelta(days=1)

    try:
        q_req_stats = await db.execute(
            text(
                """
                SELECT UPPER(status) AS statut, COUNT(*) AS count
                FROM public.requisitions
                WHERE (:date_start IS NULL OR created_at::date >= :date_start)
                  AND (:date_end_excl IS NULL OR created_at::date < :date_end_excl)
                GROUP BY UPPER(status)
                ORDER BY UPPER(status)
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        for row in q_req_stats:
            statut = row.statut or "INCONNU"
            count_val = int(row.count or 0)
            par_statut_requisition.append(ReportBreakdownCount(key=statut, count=count_val))
            req_summary.total += count_val
            if statut in REQUISITION_STATUT_EN_ATTENTE:
                req_summary.en_attente += count_val
            elif statut in REQUISITION_STATUT_APPROUVEE:
                req_summary.approuvees += count_val
            elif statut in REQUISITION_STATUT_REJETEE:
                req_summary.rejetees += count_val
            elif statut in REQUISITION_STATUT_ANNULEE:
                req_summary.annulees += count_val
    except Exception as exc:
        logger.error("Erreur lors de la récupération des réquisitions : %s", exc)
        availability.requisitions = False

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
            requisitions=req_summary,
        ),
        availability=availability,
    )

    logger.info(
        "reports totals encaissements=%s sorties=%s solde_initial=%s flux_periode=%s solde_final=%s",
        totals.encaissements_total,
        totals.sorties_total,
        totals.solde_initial,
        totals.flux_periode,
        totals.solde_final,
    )

    return ReportSummaryResponse(
        stats=stats,
        daily_stats=par_jour,
        period=PeriodInfo(start=daily_start, end=daily_end, label="custom"),
    )
