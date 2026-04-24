from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id
from app.db.session import get_db
from app.models.user import User
from app.models.encaissement import Encaissement
from app.models.compte_bancaire import CompteBancaire
from app.models.banque import Banque
from app.models.transfert_interne import TransfertInterne
from app.models.cloture_caisse import ClotureCaisse
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
    ReportJournalResponse,
    ReportJournalLine,
    ReportAnnualSynthese,
    ReportAnnualMonth,
    ReportAnnualCanalSplit,
    ReportTopExpense,
)
from app.schemas.sortie_fonds import SortieFondsOut
from app.utils.formatters import calculer_journal_avec_solde

router = APIRouter()
logger = logging.getLogger("onec_cpk_reports")

STATUT_PAIEMENT_INCLUS = ("complet", "partiel")
REQUISITION_STATUT_EN_ATTENTE = (
    "EN_ATTENTE_COMMISSION",
    "EN_ATTENTE",
    "AUTORISEE",
    "APPROUVEE",
    "PENDING_VALIDATION_IMPORT",
)
REQUISITION_STATUT_APPROUVEE = ("APPROUVEE", "PAYEE")


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
        budget_poste_id=sortie.budget_poste_id,
        budget_poste_code=sortie.budget_poste_code,
        budget_poste_libelle=sortie.budget_poste_libelle,
        service_id=sortie.service_id,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        reference_numero=sortie.reference_numero,
        pdf_path=sortie.pdf_path,
        statut=sortie.statut or "VALIDE",
        motif_annulation=sortie.motif_annulation,
        annulee_le=sortie.annulee_le,
        exchange_rate_snapshot=sortie.exchange_rate_snapshot,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
        annexes=sortie.annexes,
        created_by=str(sortie.created_by) if sortie.created_by else None,
        created_at=sortie.created_at,
        requisition=None,
    )


def _parse_datetime_value(value: str | None, end_of_day: bool = False) -> datetime | None:
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


@router.get("/summary", response_model=ReportSummaryResponse)
async def summary(
    date_debut: str | None = None,
    date_fin: str | None = None,
    canal: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ReportSummaryResponse:
    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    date_end_excl = _end_exclusive(date_end)
    daily_start, daily_end = _daily_range(date_start, date_end)
    canal_value = (canal or "").strip().upper() or None
    if canal_value == "ALL":
        canal_value = None
    if canal_value not in {None, "CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")

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
    par_poste_budgetaire: list[ReportBreakdownCountTotal] = []
    par_statut_requisition: list[ReportBreakdownCount] = []
    requisitions_summary = ReportRequisitionsSummary(total=0, en_attente=0, approuvees=0)

    initial_balance = Decimal("0")
    opening_balance = Decimal("0")
    try:
        opening_res = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(solde_initial), 0) AS total
                FROM public.comptes_bancaires
                WHERE organisation_id = :tenant_id
                  AND is_active IS TRUE
                """
            ),
            {"tenant_id": tenant_id},
        )
        opening_balance = Decimal(str(opening_res.scalar_one() or 0))
    except Exception:
        await db.rollback()
        opening_balance = Decimal("0")

    if date_start:
        try:
            q_init = await db.execute(
                text(
                    """
                    SELECT 
                        :opening_balance +
                        (SELECT COALESCE(SUM(montant_paye), 0) FROM public.encaissements
                         WHERE organisation_id = :tenant_id
                           AND COALESCE(est_proforma, false) = false
                           AND LOWER(statut_paiement) = ANY(:statuts)
                           AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                           AND CAST(date_encaissement AS date) < CAST(:date_start AS date)) -
                        (SELECT COALESCE(SUM(montant_paye), 0) FROM public.sorties_fonds
                         WHERE organisation_id = :tenant_id
                           AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
                           AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                           AND CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_start AS date))
                    AS solde_initial
                    """
                ),
                {
                    "opening_balance": opening_balance,
                    "statuts": list(STATUT_PAIEMENT_INCLUS),
                    "canal": canal_value,
                    "date_start": date_start,
                    "tenant_id": tenant_id,
                },
            )
            initial_balance = Decimal(str(q_init.scalar() or 0))
        except Exception:
            await db.rollback()
            availability.encaissements = False
            availability.sorties = False
            initial_balance = Decimal("0")
    else:
        initial_balance = opening_balance

    try:
        enc_total = await db.execute(
            text(
                """
                SELECT COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE organisation_id = :tenant_id
                  AND COALESCE(est_proforma, false) = false
                  AND LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "canal": canal_value,
                "date_start": date_start,
                "date_end_excl": date_end_excl,
                "tenant_id": tenant_id,
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
                WHERE organisation_id = :tenant_id
                  AND COALESCE(est_proforma, false) = false
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
                GROUP BY statut_paiement
                ORDER BY statut_paiement
                """
            ),
            {"canal": canal_value, "date_start": date_start, "date_end_excl": date_end_excl, "tenant_id": tenant_id},
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
                WHERE organisation_id = :tenant_id
                  AND COALESCE(est_proforma, false) = false
                  AND LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
                GROUP BY mode_paiement
                ORDER BY mode_paiement
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "canal": canal_value,
                "date_start": date_start,
                "date_end_excl": date_end_excl,
                "tenant_id": tenant_id,
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
        enc_postes = await db.execute(
            text(
                """
                SELECT
                    CASE
                        WHEN budget_poste_code IS NULL AND budget_poste_libelle IS NULL THEN 'Non renseigné'
                        WHEN budget_poste_code IS NULL THEN budget_poste_libelle
                        WHEN budget_poste_libelle IS NULL THEN budget_poste_code
                        ELSE budget_poste_code || ' - ' || budget_poste_libelle
                    END AS poste,
                       COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE organisation_id = :tenant_id
                  AND COALESCE(est_proforma, false) = false
                  AND LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(date_encaissement AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(date_encaissement AS date) < CAST(:date_end_excl AS date))
                GROUP BY poste
                ORDER BY poste
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "canal": canal_value,
                "date_start": date_start,
                "date_end_excl": date_end_excl,
                "tenant_id": tenant_id,
            },
        )
        par_poste_budgetaire = [
            ReportBreakdownCountTotal(
                key=row.poste,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_postes
        ]
    except Exception:
        await db.rollback()
        availability.encaissements = False
        par_poste_budgetaire = []

    sorties_daily_map: dict[str, Decimal] = {}
    enc_daily_map: dict[str, Decimal] = {}

    try:
        enc_daily = await db.execute(
            text(
                """
                SELECT CAST(date_encaissement AS date) AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.encaissements
                WHERE organisation_id = :tenant_id
                  AND COALESCE(est_proforma, false) = false
                  AND LOWER(statut_paiement) = ANY(:statuts)
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND CAST(date_encaissement AS date) >= CAST(:daily_start AS date)
                  AND CAST(date_encaissement AS date) <= CAST(:daily_end AS date)
                GROUP BY day
                ORDER BY day
                """
            ),
            {
                "statuts": list(STATUT_PAIEMENT_INCLUS),
                "canal": canal_value,
                "daily_start": daily_start,
                "daily_end": daily_end,
                "tenant_id": tenant_id,
            },
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
                WHERE organisation_id = :tenant_id
                  AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"canal": canal_value, "date_start": date_start, "date_end_excl": date_end_excl, "tenant_id": tenant_id},
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
                WHERE organisation_id = :tenant_id
                  AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_end_excl AS date))
                GROUP BY mode_paiement
                ORDER BY mode_paiement
                """
            ),
            {"canal": canal_value, "date_start": date_start, "date_end_excl": date_end_excl, "tenant_id": tenant_id},
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
                SELECT CAST(COALESCE(date_paiement, created_at) AS date) AS day, COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE organisation_id = :tenant_id
                  AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:daily_start AS date)
                  AND CAST(COALESCE(date_paiement, created_at) AS date) <= CAST(:daily_end AS date)
                GROUP BY day
                ORDER BY day
                """
            ),
            {"canal": canal_value, "daily_start": daily_start, "daily_end": daily_end, "tenant_id": tenant_id},
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
                WHERE organisation_id = :tenant_id
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {"date_start": date_start, "date_end": date_end, "tenant_id": tenant_id},
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
                WHERE organisation_id = :tenant_id
                  AND status = ANY(:status_list)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {
                "status_list": list(REQUISITION_STATUT_EN_ATTENTE),
                "date_start": date_start,
                "date_end": date_end,
                "tenant_id": tenant_id,
            },
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
                WHERE organisation_id = :tenant_id
                  AND status = ANY(:status_list)
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                """
            ),
            {
                "status_list": list(REQUISITION_STATUT_APPROUVEE),
                "date_start": date_start,
                "date_end": date_end,
                "tenant_id": tenant_id,
            },
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
                WHERE organisation_id = :tenant_id
                  AND (CAST(:date_start AS date) IS NULL OR CAST(created_at AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end AS date) IS NULL OR CAST(created_at AS date) <= CAST(:date_end AS date))
                GROUP BY status
                ORDER BY status
                """
            ),
            {"date_start": date_start, "date_end": date_end, "tenant_id": tenant_id},
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
                WHERE organisation_id = :tenant_id
                  AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
                  AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
                  AND (CAST(:date_start AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) >= CAST(:date_start AS date))
                  AND (CAST(:date_end_excl AS date) IS NULL OR CAST(COALESCE(date_paiement, created_at) AS date) < CAST(:date_end_excl AS date))
                """
            ),
            {"canal": canal_value, "date_start": date_start, "date_end_excl": date_end_excl, "tenant_id": tenant_id},
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
            par_poste_budgetaire=par_poste_budgetaire,
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> ReportClotureResponse:
    parsed_date = _parse_date_value(date_jour)
    target_date = parsed_date or datetime.now(timezone.utc).date()
    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    res = await db.execute(
        select(SortieFonds)
        .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
        .where(SortieFonds.organisation_id == tenant_id)
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


@router.get("/synthese-annuelle", response_model=ReportAnnualSynthese)
async def synthese_annuelle(
    year: int,
    devise: str = "USD",
    canal: str = "ALL",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ReportAnnualSynthese:
    devise = (devise or "USD").upper()
    canal = (canal or "ALL").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    if canal not in {"ALL", "CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")

    enc_amount_expr = "montant_paye" if devise == "USD" else "montant_percu"
    enc_canal_filter = "" if canal == "ALL" else "AND canal = :canal"
    sort_canal_filter = "" if canal == "ALL" else "AND canal = :canal"

    enc_months = await db.execute(
        text(
            f"""
            SELECT EXTRACT(MONTH FROM date_encaissement)::int AS mois,
                   COALESCE(SUM({enc_amount_expr}),0) AS total_entrees
            FROM public.encaissements
            WHERE organisation_id = :tenant_id
              AND EXTRACT(YEAR FROM date_encaissement) = :year
              AND devise_perception = :devise
              AND is_deleted = FALSE
              {enc_canal_filter}
            GROUP BY mois
            ORDER BY mois
            """
        ),
        {"year": year, "devise": devise, "canal": canal, "tenant_id": tenant_id},
    )

    sort_months = await db.execute(
        text(
            f"""
            SELECT EXTRACT(MONTH FROM COALESCE(date_paiement, created_at))::int AS mois,
                   COALESCE(SUM(montant_paye),0) AS total_sorties
            FROM public.sorties_fonds
            WHERE organisation_id = :tenant_id
              AND EXTRACT(YEAR FROM COALESCE(date_paiement, created_at)) = :year
              AND devise = :devise
              AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
              {sort_canal_filter}
            GROUP BY mois
            ORDER BY mois
            """
        ),
        {"year": year, "devise": devise, "canal": canal, "tenant_id": tenant_id},
    )

    month_map: dict[int, dict[str, Decimal]] = {m: {"entrees": Decimal("0"), "sorties": Decimal("0")} for m in range(1, 13)}
    for row in enc_months:
        month_map[int(row.mois)]["entrees"] = Decimal(row.total_entrees or 0)
    for row in sort_months:
        month_map[int(row.mois)]["sorties"] = Decimal(row.total_sorties or 0)

    months: list[ReportAnnualMonth] = []
    total_entrees = Decimal("0")
    total_sorties = Decimal("0")
    critical_month = None
    critical_value = Decimal("-1")

    for m in range(1, 13):
        ent = month_map[m]["entrees"]
        sor = month_map[m]["sorties"]
        solde = ent - sor
        months.append(ReportAnnualMonth(mois=m, total_entrees=ent, total_sorties=sor, solde=solde))
        total_entrees += ent
        total_sorties += sor
        if sor > critical_value:
            critical_value = sor
            critical_month = m

    solde_net = total_entrees - total_sorties
    coverage_rate = None
    if total_sorties > 0:
        coverage_rate = (total_entrees / total_sorties).quantize(Decimal("0.0001"))

    canal_split_enc = ReportAnnualCanalSplit()
    canal_split_sort = ReportAnnualCanalSplit()

    enc_split = await db.execute(
        text(
            f"""
            SELECT canal, COALESCE(SUM({enc_amount_expr}),0) AS total
            FROM public.encaissements
            WHERE organisation_id = :tenant_id
              AND EXTRACT(YEAR FROM date_encaissement) = :year
              AND devise_perception = :devise
              AND is_deleted = FALSE
            GROUP BY canal
            """
        ),
        {"year": year, "devise": devise, "tenant_id": tenant_id},
    )
    for row in enc_split:
        if (row.canal or "").upper() == "CAISSE":
            canal_split_enc.caisse = Decimal(row.total or 0)
        if (row.canal or "").upper() == "BANQUE":
            canal_split_enc.banque = Decimal(row.total or 0)

    sort_split = await db.execute(
        text(
            """
            SELECT canal, COALESCE(SUM(montant_paye),0) AS total
            FROM public.sorties_fonds
            WHERE organisation_id = :tenant_id
              AND EXTRACT(YEAR FROM COALESCE(date_paiement, created_at)) = :year
              AND devise = :devise
              AND (statut IS NULL OR UPPER(statut) = 'VALIDE')
            GROUP BY canal
            """
        ),
        {"year": year, "devise": devise, "tenant_id": tenant_id},
    )
    for row in sort_split:
        if (row.canal or "").upper() == "CAISSE":
            canal_split_sort.caisse = Decimal(row.total or 0)
        if (row.canal or "").upper() == "BANQUE":
            canal_split_sort.banque = Decimal(row.total or 0)

    return ReportAnnualSynthese(
        year=year,
        devise=devise,
        canal=canal,
        months=months,
        total_entrees=total_entrees,
        total_sorties=total_sorties,
        solde_net=solde_net,
        coverage_rate=coverage_rate,
        critical_month=critical_month,
        encaissements_par_canal=canal_split_enc,
        sorties_par_canal=canal_split_sort,
    )


@router.get("/top-depenses", response_model=list[ReportTopExpense])
async def top_depenses(
    date_debut: str | None = None,
    date_fin: str | None = None,
    limit: int = 5,
    canal: str | None = None,
    devise: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[ReportTopExpense]:
    start_dt = _parse_datetime_value(date_debut)
    end_dt = _parse_datetime_value(date_fin, end_of_day=True)
    if not start_dt or not end_dt:
        today = datetime.now(timezone.utc)
        start_dt = start_dt or datetime(today.year, today.month, 1, tzinfo=timezone.utc)
        end_dt = end_dt or (start_dt + timedelta(days=32)).replace(day=1) - timedelta(microseconds=1)

    canal_value = (canal or "").upper() if canal else None
    devise_value = (devise or "").upper() if devise else None
    if canal_value and canal_value not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")
    if devise_value and devise_value not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")

    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    stmt = (
        select(
            SortieFonds.motif.label("motif"),
            func.coalesce(func.sum(SortieFonds.montant_paye), 0).label("total"),
        )
        .where(SortieFonds.organisation_id == tenant_id)
        .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
        .where(paiement_ts >= start_dt, paiement_ts <= end_dt)
        .group_by(SortieFonds.motif)
        .order_by(func.coalesce(func.sum(SortieFonds.montant_paye), 0).desc())
        .limit(max(1, min(int(limit), 20)))
    )
    if canal_value:
        stmt = stmt.where(SortieFonds.canal == canal_value)
    if devise_value:
        stmt = stmt.where(SortieFonds.devise == devise_value)

    res = await db.execute(stmt)
    return [ReportTopExpense(motif=row.motif, total=row.total) for row in res.all()]


@router.get("/journal-tresorerie", response_model=ReportJournalResponse)
async def journal_tresorerie(
    canal: str,
    devise: str,
    compte_bancaire_id: int | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ReportJournalResponse:
    canal = (canal or "").upper()
    devise = (devise or "").upper()
    if canal not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    if canal == "BANQUE" and not compte_bancaire_id:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour BANQUE")

    start_dt = _parse_datetime_value(date_debut)
    end_dt = _parse_datetime_value(date_fin, end_of_day=True)

    compte_label = None
    solde_base = Decimal("0")
    base_date = None

    if canal == "BANQUE":
        res = await db.execute(
            select(CompteBancaire, Banque)
            .join(Banque, CompteBancaire.banque_id == Banque.id)
            .where(CompteBancaire.id == compte_bancaire_id, CompteBancaire.organisation_id == tenant_id)
        )
        row = res.first()
        compte = row[0] if row else None
        banque = row[1] if row else None
        if compte is None or compte.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
        solde_base = Decimal(compte.solde_initial or 0)
        compte_label = f"{banque.nom if banque else compte.banque_id} - {compte.intitule}"
    else:
        if compte_bancaire_id:
            res = await db.execute(
                select(CompteBancaire).where(
                    CompteBancaire.id == compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
            )
            compte = res.scalar_one_or_none()
            if compte is None or compte.is_active is False:
                raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
            if (compte.account_type or "").upper() != "CASH":
                raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
            if (compte.devise or "").upper() != devise:
                raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
            compte_label = compte.intitule
        if start_dt:
            last_res = await db.execute(
                select(ClotureCaisse)
                .where(ClotureCaisse.date_cloture < start_dt, ClotureCaisse.organisation_id == tenant_id)
                .order_by(ClotureCaisse.date_cloture.desc())
                .limit(1)
            )
            last = last_res.scalar_one_or_none()
            if last:
                solde_base = Decimal(
                    last.solde_theorique_usd if devise == "USD" else last.solde_theorique_cdf
                )
                base_date = last.date_cloture

    def _enc_amount_expr():
        return (
            Encaissement.montant_paye
            if devise == "USD"
            else Encaissement.montant_percu
        )

    async def _sum_encaissements(before: bool) -> Decimal:
        query = select(func.coalesce(func.sum(_enc_amount_expr()), 0)).where(
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
            Encaissement.canal == canal,
            Encaissement.devise_perception == devise,
            Encaissement.organisation_id == tenant_id,
        )
        if compte_bancaire_id:
            query = query.where(Encaissement.compte_bancaire_id == compte_bancaire_id)
        if base_date:
            query = query.where(Encaissement.date_encaissement >= base_date)
        if start_dt and before:
            query = query.where(Encaissement.date_encaissement < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(Encaissement.date_encaissement >= start_dt, Encaissement.date_encaissement <= end_dt)
        return Decimal((await db.execute(query)).scalar_one() or 0)

    async def _sum_sorties(before: bool) -> Decimal:
        paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
        query = select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.canal == canal,
            SortieFonds.devise == devise,
            SortieFonds.organisation_id == tenant_id,
        )
        if compte_bancaire_id:
            query = query.where(SortieFonds.compte_bancaire_id == compte_bancaire_id)
        if base_date:
            query = query.where(paiement_ts >= base_date)
        if start_dt and before:
            query = query.where(paiement_ts < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(paiement_ts >= start_dt, paiement_ts <= end_dt)
        return Decimal((await db.execute(query)).scalar_one() or 0)

    async def _sum_transferts(before: bool, incoming: bool) -> Decimal:
        if canal == "CAISSE":
            return Decimal("0")
        query = select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
            TransfertInterne.devise == devise,
        )
        if incoming:
            query = query.where(
                TransfertInterne.destination_type == canal,
                (TransfertInterne.destination_id == compte_bancaire_id)
                if canal == "BANQUE"
                else TransfertInterne.destination_id.is_(None),
            )
        else:
            query = query.where(
                TransfertInterne.source_type == canal,
                (TransfertInterne.source_id == compte_bancaire_id)
                if canal == "BANQUE"
                else TransfertInterne.source_id.is_(None),
            )
        if base_date:
            query = query.where(TransfertInterne.date_transfert >= base_date)
        if start_dt and before:
            query = query.where(TransfertInterne.date_transfert < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(
                TransfertInterne.date_transfert >= start_dt,
                TransfertInterne.date_transfert <= end_dt,
            )
        return Decimal((await db.execute(query)).scalar_one() or 0)

    if start_dt:
        pre_entrees = (await _sum_encaissements(True)) + (await _sum_transferts(True, True))
        pre_sorties = (await _sum_sorties(True)) + (await _sum_transferts(True, False))
        solde_initial = solde_base + pre_entrees - pre_sorties
    else:
        solde_initial = solde_base

    mouvements: list[dict] = []

    enc_query = select(
        Encaissement.id,
        Encaissement.date_encaissement,
        Encaissement.libelle,
        Encaissement.reference,
        _enc_amount_expr().label("montant"),
        Encaissement.is_reconciled,
        Encaissement.reconciled_at,
        Encaissement.bank_statement_ref,
    ).where(
        Encaissement.is_deleted.is_(False),
        Encaissement.est_proforma.is_(False),
        Encaissement.canal == canal,
        Encaissement.devise_perception == devise,
        Encaissement.organisation_id == tenant_id,
    )
    if compte_bancaire_id:
        enc_query = enc_query.where(Encaissement.compte_bancaire_id == compte_bancaire_id)
    if start_dt:
        enc_query = enc_query.where(Encaissement.date_encaissement >= start_dt)
    if end_dt:
        enc_query = enc_query.where(Encaissement.date_encaissement <= end_dt)
    enc_rows = (await db.execute(enc_query)).all()
    for enc_id, dt, libelle, reference, montant, is_reconciled, reconciled_at, bank_statement_ref in enc_rows:
        mouvements.append(
            {
                "date": dt,
                "libelle": libelle,
                "reference": reference,
                "compte_label": compte_label,
                "entree": Decimal(montant or 0),
                "sortie": Decimal("0"),
                "type_operation": "ENCAISSEMENT",
                "transaction_id": str(enc_id) if enc_id else None,
                "transaction_type": "ENCAISSEMENT",
                "is_reconciled": bool(is_reconciled),
                "reconciled_at": reconciled_at,
                "bank_statement_ref": bank_statement_ref,
            }
        )

    paiement_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    sortie_query = select(
        SortieFonds.id,
        paiement_ts,
        SortieFonds.motif,
        SortieFonds.reference_numero,
        SortieFonds.reference,
        SortieFonds.montant_paye,
        SortieFonds.is_reconciled,
        SortieFonds.reconciled_at,
        SortieFonds.bank_statement_ref,
    ).where(
        (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
        SortieFonds.canal == canal,
        SortieFonds.devise == devise,
        SortieFonds.organisation_id == tenant_id,
    )
    if compte_bancaire_id:
        sortie_query = sortie_query.where(SortieFonds.compte_bancaire_id == compte_bancaire_id)
    if start_dt:
        sortie_query = sortie_query.where(paiement_ts >= start_dt)
    if end_dt:
        sortie_query = sortie_query.where(paiement_ts <= end_dt)
    sortie_rows = (await db.execute(sortie_query)).all()
    for sortie_id, dt, motif, ref_num, ref, montant, is_reconciled, reconciled_at, bank_statement_ref in sortie_rows:
        mouvements.append(
            {
                "date": dt,
                "libelle": motif,
                "reference": ref_num or ref,
                "compte_label": compte_label,
                "entree": Decimal("0"),
                "sortie": Decimal(montant or 0),
                "type_operation": "SORTIE",
                "transaction_id": str(sortie_id) if sortie_id else None,
                "transaction_type": "SORTIE",
                "is_reconciled": bool(is_reconciled),
                "reconciled_at": reconciled_at,
                "bank_statement_ref": bank_statement_ref,
            }
        )

    if canal == "BANQUE":
        transfert_query = select(
            TransfertInterne.date_transfert,
            TransfertInterne.reference,
            TransfertInterne.source_type,
            TransfertInterne.source_id,
            TransfertInterne.destination_type,
            TransfertInterne.destination_id,
            TransfertInterne.montant,
        ).where(
            TransfertInterne.devise == devise,
            (
                (TransfertInterne.source_type == canal)
                | (TransfertInterne.destination_type == canal)
            ),
            (TransfertInterne.source_id == compte_bancaire_id)
            | (TransfertInterne.destination_id == compte_bancaire_id),
        )
        if start_dt:
            transfert_query = transfert_query.where(TransfertInterne.date_transfert >= start_dt)
        if end_dt:
            transfert_query = transfert_query.where(TransfertInterne.date_transfert <= end_dt)
        transfer_rows = (await db.execute(transfert_query)).all()
        for dt, reference, src_type, src_id, dst_type, dst_id, montant in transfer_rows:
            is_source = src_type == canal and src_id == compte_bancaire_id
            is_dest = dst_type == canal and dst_id == compte_bancaire_id
            if is_source:
                mouvements.append(
                    {
                        "date": dt,
                        "libelle": "Transfert interne",
                        "reference": reference,
                        "compte_label": compte_label,
                        "entree": Decimal("0"),
                        "sortie": Decimal(montant or 0),
                        "type_operation": "TRANSFERT_SORTIE",
                        "transaction_id": None,
                        "transaction_type": "TRANSFERT",
                        "is_reconciled": None,
                        "reconciled_at": None,
                        "bank_statement_ref": None,
                    }
                )
            if is_dest:
                mouvements.append(
                    {
                        "date": dt,
                        "libelle": "Transfert interne",
                        "reference": reference,
                        "compte_label": compte_label,
                        "entree": Decimal(montant or 0),
                        "sortie": Decimal("0"),
                        "type_operation": "TRANSFERT_ENTREE",
                        "transaction_id": None,
                        "transaction_type": "TRANSFERT",
                        "is_reconciled": None,
                        "reconciled_at": None,
                        "bank_statement_ref": None,
                    }
                )

    mouvements.sort(key=lambda m: (m["date"] or datetime.min.replace(tzinfo=timezone.utc)))
    lignes = calculer_journal_avec_solde(mouvements, solde_initial)

    total_entrees = sum((Decimal(line["entree"]) for line in lignes), Decimal("0"))
    total_sorties = sum((Decimal(line["sortie"]) for line in lignes), Decimal("0"))
    solde_final = (lignes[-1]["solde"] if lignes else solde_initial) or solde_initial

    period = PeriodInfo(
        start=start_dt.date() if start_dt else None,
        end=end_dt.date() if end_dt else None,
        label=None,
    )

    return ReportJournalResponse(
        canal=canal,
        devise=devise,
        compte_bancaire_id=compte_bancaire_id,
        compte_bancaire_label=compte_label,
        solde_initial=solde_initial,
        total_entrees=total_entrees,
        total_sorties=total_sorties,
        solde_final=solde_final,
        period=period,
        lignes=[ReportJournalLine(**line) for line in lignes],
    )
