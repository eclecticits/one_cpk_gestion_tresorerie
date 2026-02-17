from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.sortie_fonds import SortieFonds
from app.schemas.reports import (
    PeriodInfo,
    ReportAvailability,
    ReportBreakdownCount,
    ReportBreakdownCountTotal,
    ReportBreakdowns,
    ReportClotureResponse,
    ReportDailyStats,
    ReportModePaiementBreakdown,
    ReportRequisitionsSummary,
    ReportSummaryResponse,
    ReportSummaryStats,
    ReportTotals,
)
from app.schemas.sortie_fonds import SortieFondsOut

router = APIRouter()
logger = logging.getLogger("onec_cpk_reports")

STATUT_PAIEMENT_INCLUS = ("complet", "partiel", "avance")
REQUISITION_STATUT_EN_ATTENTE = ("EN_ATTENTE", "AUTORISEE", "VALIDEE", "PENDING_VALIDATION_IMPORT")
REQUISITION_STATUT_APPROUVEE = ("APPROUVEE", "approuvee", "VALIDEE")


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


def _sortie_out(sortie: SortieFonds) -> SortieFondsOut:
    return SortieFondsOut(
        id=str(sortie.id),
        type_sortie=sortie.type_sortie,
        requisition_id=str(sortie.requisition_id) if sortie.requisition_id else None,
        rubrique_code=sortie.rubrique_code,
        budget_ligne_id=sortie.budget_ligne_id,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        reference_numero=sortie.reference_numero,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
        created_by=str(sortie.created_by) if sortie.created_by else None,
        created_at=sortie.created_at,
        requisition=None,
    )


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

    totals = ReportTotals(
        encaissements_total=Decimal("0"),
        sorties_total=Decimal("0"),
        solde_initial=Decimal("0"),
        solde=Decimal("0"),
        solde_final=Decimal("0"),
    )
    par_jour: list[ReportDailyStats] = []
    par_statut_paiement: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_enc: list[ReportBreakdownCountTotal] = []
    par_mode_paiement_sorties: list[ReportBreakdownCountTotal] = []
    par_type_operation: list[ReportBreakdownCountTotal] = []
    par_statut_requisition: list[ReportBreakdownCount] = []
    requisitions_summary = ReportRequisitionsSummary(total=0, en_attente=0, approuvees=0)

    initial_balance = Decimal("0")
    if date_start:
        try:
            q_init = await db.execute(
                text(
                    """
                    SELECT 
                        (SELECT COALESCE(SUM(montant_paye), 0) FROM public.encaissements
                         WHERE LOWER(statut_paiement) = ANY(:statuts) AND CAST(date_encaissement AS date) < CAST(:date_start AS date)) -
                        (SELECT COALESCE(SUM(montant_paye), 0) FROM public.sorties_fonds
                         WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                           AND CAST(date_paiement AS date) < CAST(:date_start AS date))
                    AS solde_initial
                    """
                ),
                {"statuts": list(STATUT_PAIEMENT_INCLUS), "date_start": date_start},
            )
            initial_balance = Decimal(str(q_init.scalar() or 0))
        except Exception:
            await db.rollback()
            availability.encaissements = False
            availability.sorties = False
            initial_balance = Decimal("0")

    try:
        enc_total = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
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
        await db.rollback()
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
                WHERE (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
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
        await db.rollback()
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
                WHERE LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
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
        await db.rollback()
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
                WHERE LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
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
        await db.rollback()
        availability.encaissements = False
        par_type_operation = []

    sorties_daily_map: dict[str, Decimal] = {}
    enc_daily_map: dict[str, Decimal] = {}

    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT CAST(date_encaissement AS date) AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE LOWER(statut_paiement) = ANY(:statuts)
                  AND CAST(date_encaissement AS date) >= CAST(:daily_start AS date)
                  AND CAST(date_encaissement AS date) <= CAST(:daily_end AS date)
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
        await db.rollback()
        availability.encaissements = False
        enc_daily_map = {}

    try:
        sorties_total = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_paiement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_paiement AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        totals.sorties_total = Decimal(sorties_total.scalar_one() or 0)
    except Exception:
        await db.rollback()
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
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_paiement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_paiement AS date) < CAST(:date_end_excl AS date))
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
        await db.rollback()
        availability.sorties = False
        par_mode_paiement_sorties = []

    try:
        sorties_daily = await db.execute(
            text(
                """
                SELECT CAST(date_paiement AS date) AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND CAST(date_paiement AS date) >= CAST(:daily_start AS date)
                  AND CAST(date_paiement AS date) <= CAST(:daily_end AS date)
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
        await db.rollback()
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
                WHERE (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {"date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.total = int(req_total.scalar_one() or 0)
    except Exception:
        await db.rollback()
        availability.requisitions = False
        requisitions_summary.total = 0

    try:
        req_pending = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE status = ANY(:status_list)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {"status_list": list(REQUISITION_STATUT_EN_ATTENTE), "date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.en_attente = int(req_pending.scalar_one() or 0)
    except Exception:
        await db.rollback()
        availability.requisitions = False
        requisitions_summary.en_attente = 0

    try:
        req_approved = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.requisitions
                WHERE status = ANY(:status_list)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {"status_list": list(REQUISITION_STATUT_APPROUVEE), "date_start": date_start, "date_end": date_end},
        )
        requisitions_summary.approuvees = int(req_approved.scalar_one() or 0)
    except Exception:
        await db.rollback()
        availability.requisitions = False
        requisitions_summary.approuvees = 0

    try:
        req_by_status = await db.execute(
            text(
                """
                SELECT status AS statut, COUNT(*) AS count
                FROM public.requisitions
                WHERE (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
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
        await db.rollback()
        availability.requisitions = False
        par_statut_requisition = []

    totals.solde_initial = initial_balance
    totals.solde = totals.solde_initial + (totals.encaissements_total - totals.sorties_total)
    totals.solde_final = totals.solde

    try:
        sorties_period_count = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count
                FROM public.sorties_fonds
                WHERE (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_paiement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_paiement AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"date_start": date_start, "date_end_excl": date_end_excl},
        )
        logger.info("sorties period count=%s", int(sorties_period_count.scalar_one() or 0))
    except Exception:
        await db.rollback()
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


@router.get("/rapport-cloture", response_model=ReportClotureResponse)
async def rapport_cloture(
    date_jour: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportClotureResponse:
    parsed_date = _parse_date_value(date_jour)
    target_date = parsed_date or datetime.now(timezone.utc).date()
    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    res = await db.execute(
        select(SortieFonds)
        .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
        .where(paiement_ts >= start_dt)
        .where(paiement_ts < end_dt)
        .order_by(paiement_ts.asc())
    )
    sorties = res.scalars().all()
    total_decaisse = sum((s.montant_paye or 0) for s in sorties)

    return ReportClotureResponse(
        date=target_date,
        total=total_decaisse,
        nombre_transactions=len(sorties),
        details=[_sortie_out(s) for s in sorties],
    )
