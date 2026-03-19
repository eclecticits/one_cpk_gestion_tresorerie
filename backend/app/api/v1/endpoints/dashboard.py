from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.organisation import Organisation
from app.models.compte_bancaire import CompteBancaire
from app.models.system_settings import SystemSettings
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.requisition import Requisition
from app.schemas.dashboard import (
    DashboardDailyStats,
    DashboardStats,
    DashboardStatsResponse,
    PeriodInfo,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_dashboard")


STATUT_PAIEMENT_INCLUS = ("complet", "partiel")
REQUISITION_STATUT_EN_ATTENTE = (
    "EN_ATTENTE_COMMISSION",
    "EN_ATTENTE",
    "AUTORISEE",
    "APPROUVEE",
    "PENDING_VALIDATION_IMPORT",
)


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
    canal: str | None = None,
    compte_bancaire_id: int | None = None,
    devise: str | None = None,
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

    org_id = user.organisation_id
    canal_value = (canal or "").upper() if canal else None
    if canal_value == "ALL":
        canal_value = None
    if canal_value and canal_value not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")

    devise_value: str | None = None
    if devise:
        devise_value = devise.upper()
        if devise_value not in {"USD", "CDF"}:
            raise HTTPException(status_code=400, detail="devise invalide")
    else:
        org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
        org = org_res.scalar_one_or_none()
        devise_value = (org.devise_preferee if org else None) or "USD"

    compte_id_value: int | None = None
    compte_selected: CompteBancaire | None = None
    if compte_bancaire_id:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == compte_bancaire_id,
                CompteBancaire.organisation_id == org_id,
                CompteBancaire.is_active.is_(True),
            )
        )
        compte_selected = res.scalar_one_or_none()
        if compte_selected is None:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        compte_canal = "CAISSE" if (compte_selected.account_type or "").upper() == "CASH" else "BANQUE"
        if devise_value and (compte_selected.devise or "").upper() != devise_value:
            raise HTTPException(status_code=400, detail="compte_bancaire_id incompatible avec la devise")
        if canal_value and canal_value != compte_canal:
            raise HTTPException(status_code=400, detail="compte_bancaire_id incompatible avec le canal")
        canal_value = canal_value or compte_canal
        compte_id_value = compte_bancaire_id

    # Best-effort real stats (works only after the DB schema/data is imported)
    try:
        enc_filters = [Encaissement.organisation_id == org_id]
        if not include_all_status:
            enc_filters.append(Encaissement.statut_paiement.in_(STATUT_PAIEMENT_INCLUS))
        if canal_value:
            enc_filters.append(Encaissement.canal == canal_value)
        if compte_id_value:
            enc_filters.append(Encaissement.compte_bancaire_id == compte_id_value)
        if devise_value:
            enc_filters.append(Encaissement.devise_perception == devise_value)

        enc_all_stmt = select(
            func.coalesce(
                func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)),
                0,
            )
        ).where(*enc_filters)
        enc_all_v = Decimal((await db.execute(enc_all_stmt)).scalar_one() or 0)
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
        enc_period_filters = list(enc_filters)
        if date_start:
            enc_period_filters.append(func.date(Encaissement.date_encaissement) >= date_start)
        if date_end_excl:
            enc_period_filters.append(func.date(Encaissement.date_encaissement) < date_end_excl)

        enc_period_stmt = select(
            func.coalesce(
                func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)),
                0,
            ).label("total"),
            func.count().label("count"),
        ).where(*enc_period_filters)
        row = (await db.execute(enc_period_stmt)).first()
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

    sorties_filters = [
        SortieFonds.organisation_id == org_id,
        or_(SortieFonds.statut.is_(None), func.upper(SortieFonds.statut) == "VALIDE"),
    ]
    if canal_value:
        sorties_filters.append(SortieFonds.canal == canal_value)
    if compte_id_value:
        sorties_filters.append(SortieFonds.compte_bancaire_id == compte_id_value)
    if devise_value:
        sorties_filters.append(SortieFonds.devise == devise_value)

    try:
        sorties_all_stmt = select(
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)
        ).where(*sorties_filters)
        sorties_all_v = Decimal((await db.execute(sorties_all_stmt)).scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties global): %s", exc, exc_info=True)
        sorties_all_v = Decimal("0")

    stats_out.solde_actuel = enc_all_v - sorties_all_v
    logger.info("SORTIES_ALL=%s", sorties_all_v)

    try:
        bank_init_res = await db.execute(
            select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
                CompteBancaire.organisation_id == org_id,
                CompteBancaire.is_active.is_(True),
                CompteBancaire.account_type == "BANK",
                CompteBancaire.devise == devise_value,
            )
        )
        cash_init_res = await db.execute(
            select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
                CompteBancaire.organisation_id == org_id,
                CompteBancaire.is_active.is_(True),
                CompteBancaire.account_type == "CASH",
                CompteBancaire.devise == devise_value,
            )
        )
        bank_initial = Decimal(bank_init_res.scalar_one() or 0)
        cash_initial = Decimal(cash_init_res.scalar_one() or 0)
    except Exception:
        bank_initial = Decimal("0")
        cash_initial = Decimal("0")

    if compte_selected is not None:
        base_initial = Decimal(compte_selected.solde_initial or 0)
        stats_out.solde_actuel = base_initial + (enc_all_v - sorties_all_v)
    elif canal_value == "BANQUE":
        stats_out.solde_actuel = bank_initial + (enc_all_v - sorties_all_v)
    elif canal_value == "CAISSE":
        stats_out.solde_actuel = cash_initial + (enc_all_v - sorties_all_v)
    else:
        stats_out.solde_actuel = bank_initial + cash_initial + (enc_all_v - sorties_all_v)

    try:
        settings_res = await db.execute(
            select(SystemSettings).where(SystemSettings.organisation_id == org_id).limit(1)
        )
        ns = settings_res.scalar_one_or_none()
        if ns:
            max_amount = Decimal(str(ns.max_caisse_amount or 0))
            stats_out.max_caisse_amount = max_amount
            if canal_value == "BANQUE":
                stats_out.caisse_overlimit = False
            else:
                stats_out.caisse_overlimit = max_amount > 0 and stats_out.solde_actuel > max_amount
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Settings): %s", exc, exc_info=True)

    try:
        sorties_period_filters = list(sorties_filters)
        sortie_date = func.date(func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at))
        if date_start:
            sorties_period_filters.append(sortie_date >= date_start)
        if date_end_excl:
            sorties_period_filters.append(sortie_date < date_end_excl)

        sorties_period_stmt = select(
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)
        ).where(*sorties_period_filters)
        sorties_period_total_v = Decimal((await db.execute(sorties_period_stmt)).scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties période): %s", exc, exc_info=True)
        sorties_period_total_v = Decimal("0")

    logger.info("SORTIES_PERIOD=%s", sorties_period_total_v)

    stats_out.total_encaissements_period = enc_period_total_v
    stats_out.total_sorties_period = sorties_period_total_v
    stats_out.solde_period = enc_period_total_v - sorties_period_total_v

    try:
        sorties_period_count_stmt = select(func.count()).where(*sorties_period_filters)
        logger.info(
            "sorties period count=%s",
            int((await db.execute(sorties_period_count_stmt)).scalar_one() or 0),
        )
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties période count): %s", exc, exc_info=True)

    enc_day_total_v = Decimal("0")
    enc_day_count_v = 0
    try:
        enc_day_filters = list(enc_filters)
        enc_day_filters.append(func.date(Encaissement.date_encaissement) == func.current_date())
        enc_day_stmt = select(
            func.coalesce(
                func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)),
                0,
            ).label("total"),
            func.count().label("count"),
        ).where(*enc_day_filters)
        row = (await db.execute(enc_day_stmt)).first()
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
        sorties_day_filters = list(sorties_filters)
        sortie_day_date = func.date(func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at))
        sorties_day_filters.append(sortie_day_date == func.current_date())
        sorties_day_stmt = select(
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)
        ).where(*sorties_day_filters)
        sorties_day_total_v = Decimal((await db.execute(sorties_day_stmt)).scalar_one() or 0)
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
        enc_daily_filters = list(enc_filters)
        enc_daily_filters.append(func.date(Encaissement.date_encaissement) >= (func.current_date() - 6))
        enc_daily_stmt = (
            select(
                func.date(Encaissement.date_encaissement).label("day"),
                func.coalesce(
                    func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)),
                    0,
                ).label("total"),
            )
            .where(*enc_daily_filters)
            .group_by("day")
            .order_by("day DESC")
        )
        for row in (await db.execute(enc_daily_stmt)).all():
            day = row.day
            if day is None:
                continue
            enc_daily_map[day.isoformat()] = Decimal(row.total or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Encaissements 7 jours): %s", exc, exc_info=True)
        enc_daily_map = {}

    try:
        sorties_daily_filters = list(sorties_filters)
        sortie_day = func.date(func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at))
        sorties_daily_filters.append(sortie_day >= (func.current_date() - 6))
        sorties_daily_stmt = (
            select(
                sortie_day.label("day"),
                func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0).label("total"),
            )
            .where(*sorties_daily_filters)
            .group_by("day")
            .order_by("day DESC")
        )
        for row in (await db.execute(sorties_daily_stmt)).all():
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
        req_pending_stmt = (
            select(func.count())
            .select_from(Requisition)
            .where(
                Requisition.organisation_id == org_id,
                Requisition.status.in_(REQUISITION_STATUT_EN_ATTENTE),
            )
        )
        requisitions_en_attente_v = int((await db.execute(req_pending_stmt)).scalar_one() or 0)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Réquisitions en attente): %s", exc, exc_info=True)
        requisitions_en_attente_v = 0

    stats_out.requisitions_en_attente = requisitions_en_attente_v

    return DashboardStatsResponse(
        stats=stats_out,
        daily_stats=daily_stats,
        period=PeriodInfo(start=date_start, end=date_end, label=period_type),
    )
