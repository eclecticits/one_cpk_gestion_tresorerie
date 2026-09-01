from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user
from app.core.cache import cache_get, cache_set
from app.db.session import get_db
from app.models.user import User
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.system_settings import SystemSettings
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.retour_caisse import RetourCaisse
from app.models.requisition import Requisition
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.schemas.dashboard import (
    DashboardDailyStats,
    DashboardStats,
    DashboardStatsResponse,
    PeriodInfo,
)

router = APIRouter()
logger = logging.getLogger("onec_cpk_dashboard")

DASHBOARD_CACHE_TTL = 60  # secondes


def _dashboard_cache_key(
    tenant_id: int,
    period_type: str,
    date_debut: str | None,
    date_fin: str | None,
    include_all_status: bool,
    canal: str | None,
    compte_bancaire_id: int | None,
    devise: str | None,
) -> str:
    params = f"{period_type}|{date_debut}|{date_fin}|{include_all_status}|{canal}|{compte_bancaire_id}|{devise}"
    h = hashlib.md5(params.encode()).hexdigest()[:12]
    return f"dashboard:stats:{tenant_id}:{h}"


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
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardStatsResponse:
    """Return dashboard aggregates.

    This endpoint is designed to be resilient during migration:
    - If business tables are not present yet, it returns zeros.
    - Once the DB is imported, it will start returning real data.

    NOTE: Authorization will be refined once RBAC rules are fully implemented.
    """

    # --- Cache Redis (TTL 60s) ---
    cache_key = _dashboard_cache_key(
        tenant_id, period_type, date_debut, date_fin,
        include_all_status, canal, compte_bancaire_id, devise,
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        logger.debug("dashboard cache HIT key=%s", cache_key)
        return DashboardStatsResponse(**cached)

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

    org_id = tenant_id
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
        enc_filters = [
            Encaissement.organisation_id == org_id,
            Encaissement.est_proforma.is_(False),
            Encaissement.is_deleted.is_(False),
            ((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE")),
        ]
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
        # Comparaison de plage sur la colonne brute (pas de func.date) pour que
        # l'index sur date_encaissement soit utilisé.
        if date_start:
            enc_period_filters.append(Encaissement.date_encaissement >= date_start)
        if date_end_excl:
            enc_period_filters.append(Encaissement.date_encaissement < date_end_excl)

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
    sorties_period_brutes_v = Decimal("0")
    retours_period_total_v = Decimal("0")
    sorties_period_total_v = Decimal("0")
    sorties_day_brutes_v = Decimal("0")
    retours_day_total_v = Decimal("0")
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

    # Les versements et approvisionnements sont des TRANSFERTS INTERNES (l'argent
    # reste dans l'organisation), pas des dépenses. On les exclut des indicateurs
    # de « sorties / dépenses » (flux, totaux) tout en les gardant dans les
    # calculs de solde. Filtre réservé au reporting, distinct de sorties_filters.
    depense_only_filter = SortieFonds.type_sortie.notin_(
        ("versement_banque", "approvisionnement_caisse")
    )

    def _retours_filters() -> list:
        filters = [
            RetourCaisse.organisation_id == org_id,
            RetourCaisse.statut == "VALIDE",
        ]
        if canal_value:
            filters.append(RetourCaisse.canal == canal_value)
        if compte_id_value:
            filters.append(RetourCaisse.compte_bancaire_id == compte_id_value)
        if devise_value:
            filters.append(RetourCaisse.devise == devise_value)
        return filters

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
        bank_filters = [
            CompteBancaire.organisation_id == org_id,
            CompteBancaire.is_active.is_(True),
            CompteBancaire.account_type == "BANK",
        ]
        cash_filters = [
            CompteBancaire.organisation_id == org_id,
            CompteBancaire.is_active.is_(True),
            CompteBancaire.account_type == "CASH",
        ]
        if devise_value:
            bank_filters.append(CompteBancaire.devise == devise_value)
            cash_filters.append(CompteBancaire.devise == devise_value)
        bank_init_res = await db.execute(
            select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(*bank_filters)
        )
        bank_current_res = await db.execute(
            select(func.coalesce(func.sum(CompteBancaire.solde_actuel), 0)).where(*bank_filters)
        )
        cash_init_res = await db.execute(
            select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(*cash_filters)
        )
        bank_initial = Decimal(bank_init_res.scalar_one() or 0)
        bank_current = Decimal(bank_current_res.scalar_one() or 0)
        cash_initial = Decimal(cash_init_res.scalar_one() or 0)
    except Exception:
        bank_initial = Decimal("0")
        bank_current = Decimal("0")
        cash_initial = Decimal("0")

    # Solde caisse : on lit le solde CENTRAL faisant autorité (maintenu par
    # /tresorerie/soldes, qui inclut approvisionnements et transferts). On ne le
    # RECALCULE pas ici à partir de enc_all - sorties_all : cette ancienne
    # formule oubliait les approvisionnements et, pour « tous canaux »,
    # double-comptait les mouvements bancaires (déjà dans bank_current).
    try:
        caisse_bal_res = await db.execute(
            select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id).limit(1)
        )
        caisse_bal = caisse_bal_res.scalar_one_or_none()
    except Exception:
        caisse_bal = None
    if caisse_bal is not None:
        caisse_solde = Decimal(
            (caisse_bal.solde_cdf if devise_value == "CDF" else caisse_bal.solde_usd) or 0
        )
    else:
        # Repli : reconstruction à partir des mouvements de caisse uniquement.
        caisse_solde = cash_initial + (enc_all_v - sorties_all_v)

    if compte_selected is not None:
        if (compte_selected.account_type or "").upper() == "BANK":
            stats_out.solde_actuel = Decimal(compte_selected.solde_actuel or 0)
        else:
            stats_out.solde_actuel = caisse_solde
    elif canal_value == "BANQUE":
        stats_out.solde_actuel = bank_current
    elif canal_value == "CAISSE":
        stats_out.solde_actuel = caisse_solde
    else:
        stats_out.solde_actuel = bank_current + caisse_solde

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
        sorties_period_filters.append(depense_only_filter)
        # Plage sur l'expression brute COALESCE(date_paiement, created_at) : un
        # index fonctionnel sur cette expression sera utilisé (pas de func.date).
        sortie_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
        if date_start:
            sorties_period_filters.append(sortie_ts >= date_start)
        if date_end_excl:
            sorties_period_filters.append(sortie_ts < date_end_excl)

        sorties_period_stmt = select(
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)
        ).where(*sorties_period_filters)
        sorties_period_brutes_v = Decimal((await db.execute(sorties_period_stmt)).scalar_one() or 0)

        retours_period_filters = _retours_filters()
        if date_start:
            retours_period_filters.append(RetourCaisse.date_retour >= date_start)
        if date_end_excl:
            retours_period_filters.append(RetourCaisse.date_retour < date_end_excl)
        retours_period_stmt = select(
            func.coalesce(func.sum(func.coalesce(RetourCaisse.montant, 0)), 0)
        ).where(*retours_period_filters)
        retours_period_total_v = Decimal((await db.execute(retours_period_stmt)).scalar_one() or 0)
        sorties_period_total_v = sorties_period_brutes_v - retours_period_total_v
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties période): %s", exc, exc_info=True)
        sorties_period_brutes_v = Decimal("0")
        retours_period_total_v = Decimal("0")
        sorties_period_total_v = Decimal("0")

    logger.info(
        "SORTIES_PERIOD_BRUTES=%s RETOURS_PERIOD=%s SORTIES_PERIOD_NETTES=%s",
        sorties_period_brutes_v,
        retours_period_total_v,
        sorties_period_total_v,
    )

    stats_out.total_encaissements_period = enc_period_total_v
    stats_out.total_sorties_brutes_period = sorties_period_brutes_v
    stats_out.total_retours_period = retours_period_total_v
    stats_out.total_sorties_nettes_period = sorties_period_total_v
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
        # « Aujourd'hui » en plage [CURRENT_DATE, CURRENT_DATE + 1) pour utiliser
        # l'index sur date_encaissement.
        enc_day_filters.append(Encaissement.date_encaissement >= func.current_date())
        enc_day_filters.append(Encaissement.date_encaissement < func.current_date() + 1)
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
        sorties_day_filters.append(depense_only_filter)
        sortie_ts_day = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
        sorties_day_filters.append(sortie_ts_day >= func.current_date())
        sorties_day_filters.append(sortie_ts_day < func.current_date() + 1)
        sorties_day_stmt = select(
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)
        ).where(*sorties_day_filters)
        sorties_day_brutes_v = Decimal((await db.execute(sorties_day_stmt)).scalar_one() or 0)

        retours_day_filters = _retours_filters()
        retours_day_filters.append(RetourCaisse.date_retour >= func.current_date())
        retours_day_filters.append(RetourCaisse.date_retour < func.current_date() + 1)
        retours_day_stmt = select(
            func.coalesce(func.sum(func.coalesce(RetourCaisse.montant, 0)), 0)
        ).where(*retours_day_filters)
        retours_day_total_v = Decimal((await db.execute(retours_day_stmt)).scalar_one() or 0)
        sorties_day_total_v = sorties_day_brutes_v - retours_day_total_v
    except Exception as exc:
        logger.error("Erreur critique Dashboard (Sorties jour): %s", exc, exc_info=True)
        sorties_day_brutes_v = Decimal("0")
        retours_day_total_v = Decimal("0")
        sorties_day_total_v = Decimal("0")

    stats_out.total_encaissements_jour = enc_day_total_v
    stats_out.total_sorties_brutes_jour = sorties_day_brutes_v
    stats_out.total_retours_jour = retours_day_total_v
    stats_out.total_sorties_nettes_jour = sorties_day_total_v
    stats_out.total_sorties_jour = sorties_day_total_v
    stats_out.solde_jour = enc_day_total_v - sorties_day_total_v

    logger.info("SOLDE_ACTUEL=%s SOLDE_PERIOD=%s", stats_out.solde_actuel, stats_out.solde_period)

    # Daily stats for last 7 days (inclusive)
    enc_daily_map: dict[str, Decimal] = {}
    sorties_daily_map: dict[str, Decimal] = {}
    try:
        enc_daily_filters = list(enc_filters)
        # WHERE en plage (index) ; le regroupement journalier garde func.date.
        enc_daily_filters.append(Encaissement.date_encaissement >= (func.current_date() - 6))
        enc_day = func.date(Encaissement.date_encaissement).label("day")
        enc_daily_stmt = (
            select(
                enc_day,
                func.coalesce(
                    func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)),
                    0,
                ).label("total"),
            )
            .where(*enc_daily_filters)
            .group_by(enc_day)
            .order_by(enc_day.desc())
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
        sorties_daily_filters.append(depense_only_filter)
        sortie_day = func.date(func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at))
        # WHERE en plage sur l'expression brute (index fonctionnel) ; regroupement
        # journalier via func.date conservé pour le SELECT/GROUP BY.
        sorties_daily_filters.append(
            func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at) >= (func.current_date() - 6)
        )
        sorties_daily_stmt = (
            select(
                sortie_day.label("day"),
                func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0).label("total"),
            )
            .where(*sorties_daily_filters)
            .group_by(sortie_day)
            .order_by(sortie_day.desc())
        )
        for row in (await db.execute(sorties_daily_stmt)).all():
            day = row.day
            if day is None:
                continue
            sorties_daily_map[day.isoformat()] = Decimal(row.total or 0)

        retours_daily_filters = _retours_filters()
        retours_daily_filters.append(RetourCaisse.date_retour >= (func.current_date() - 6))
        retour_day = func.date(RetourCaisse.date_retour)
        retours_daily_stmt = (
            select(
                retour_day.label("day"),
                func.coalesce(func.sum(func.coalesce(RetourCaisse.montant, 0)), 0).label("total"),
            )
            .where(*retours_daily_filters)
            .group_by(retour_day)
            .order_by(retour_day.desc())
        )
        for row in (await db.execute(retours_daily_stmt)).all():
            day = row.day
            if day is None:
                continue
            key = day.isoformat()
            sorties_daily_map[key] = sorties_daily_map.get(key, Decimal("0")) - Decimal(row.total or 0)
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

    # ------------------------------------------------------------------
    # Exécution budgétaire et hors budget
    #
    # Les totaux calculés jusqu'ici sont ceux de la trésorerie : ils comptent
    # tout mouvement d'argent. Ceux qui suivent isolent ce qui touche le budget
    # de ce qui ne le touche pas. Les lignes antérieures à la classification
    # portent `nature_mouvement` à NULL : elles étaient toutes budgétaires, et
    # sont comptées comme telles tant que le backfill n'a pas tranché.
    est_budgetaire_enc = or_(
        Encaissement.nature_mouvement.is_(None),
        Encaissement.nature_mouvement == "BUDGETAIRE",
    )
    est_budgetaire_sortie = or_(
        SortieFonds.nature_mouvement.is_(None),
        SortieFonds.nature_mouvement == "BUDGETAIRE",
    )
    try:
        enc_budget_filters = list(enc_filters)
        if date_start:
            enc_budget_filters.append(Encaissement.date_encaissement >= date_start)
        if date_end_excl:
            enc_budget_filters.append(Encaissement.date_encaissement < date_end_excl)
        montant_enc = func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)

        recettes_budget = Decimal(
            (
                await db.execute(
                    select(func.coalesce(func.sum(montant_enc), 0)).where(
                        *enc_budget_filters, est_budgetaire_enc
                    )
                )
            ).scalar_one()
            or 0
        )
        recettes_hors_budget = Decimal(
            (
                await db.execute(
                    select(func.coalesce(func.sum(montant_enc), 0)).where(
                        *enc_budget_filters,
                        Encaissement.nature_mouvement == "HORS_BUDGET_A_REGULARISER",
                    )
                )
            ).scalar_one()
            or 0
        )

        sorties_budget_filters = list(sorties_filters)
        sorties_budget_filters.append(depense_only_filter)
        sortie_ts_budget = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
        if date_start:
            sorties_budget_filters.append(sortie_ts_budget >= date_start)
        if date_end_excl:
            sorties_budget_filters.append(sortie_ts_budget < date_end_excl)
        montant_sortie = func.coalesce(SortieFonds.montant_paye, 0)

        depenses_budget = Decimal(
            (
                await db.execute(
                    select(func.coalesce(func.sum(montant_sortie), 0)).where(
                        *sorties_budget_filters, est_budgetaire_sortie
                    )
                )
            ).scalar_one()
            or 0
        )
        depenses_hors_budget = Decimal(
            (
                await db.execute(
                    select(func.coalesce(func.sum(montant_sortie), 0)).where(
                        *sorties_budget_filters,
                        SortieFonds.nature_mouvement.in_(
                            ("HORS_BUDGET_A_REGULARISER", "FONDS_DE_TIERS")
                        ),
                    )
                )
            ).scalar_one()
            or 0
        )

        # Les dépenses budgétaires nettes retranchent les retours de caisse,
        # comme les totaux de trésorerie : un retour annule une dépense.
        depenses_budget_nettes = depenses_budget - retours_period_total_v

        stats_out.total_recettes_budgetaires_period = recettes_budget
        stats_out.total_depenses_budgetaires_period = depenses_budget_nettes
        stats_out.solde_budgetaire_period = recettes_budget - depenses_budget_nettes
        stats_out.total_recettes_hors_budget_period = recettes_hors_budget
        stats_out.total_depenses_hors_budget_period = depenses_hors_budget
    except Exception as exc:
        logger.error("Erreur critique Dashboard (exécution budgétaire): %s", exc, exc_info=True)

    # Encours hors budget : ce qui attend encore une décision, toutes périodes
    # confondues. Un flux de la période ne dirait pas ce qu'il reste à traiter.
    # Les mêmes filtres (canal, compte, devise) que le reste du tableau de bord
    # s'appliquent : sans le filtre de devise, on additionnerait des dollars et
    # des francs dans un seul nombre.
    try:
        enc_attente_filters = list(enc_filters)
        enc_attente_filters.append(Encaissement.nature_mouvement == "HORS_BUDGET_A_REGULARISER")
        row_enc = (
            await db.execute(
                select(
                    func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, Encaissement.montant, 0)), 0),
                    func.count(),
                ).where(*enc_attente_filters)
            )
        ).first()

        sortie_attente_filters = list(sorties_filters)
        sortie_attente_filters.append(SortieFonds.nature_mouvement == "HORS_BUDGET_A_REGULARISER")
        row_sortie = (
            await db.execute(
                select(
                    func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0),
                    func.count(),
                ).where(*sortie_attente_filters)
            )
        ).first()

        stats_out.hors_budget_a_regulariser_montant = Decimal(
            (row_enc[0] if row_enc else 0) or 0
        ) + Decimal((row_sortie[0] if row_sortie else 0) or 0)
        stats_out.hors_budget_a_regulariser_count = int((row_enc[1] if row_enc else 0) or 0) + int(
            (row_sortie[1] if row_sortie else 0) or 0
        )
    except Exception as exc:
        logger.error("Erreur critique Dashboard (encours hors budget): %s", exc, exc_info=True)

    # Fonds de tiers non reversés : de l'argent présent en trésorerie mais dû.
    # Une opération porte la devise de son encaissement d'origine, c'est donc
    # par lui qu'on filtre — et le décompte suit le même filtre que le montant.
    try:
        ft_filters = [
            FondsTiersOperation.organisation_id == org_id,
            FondsTiersOperation.statut.in_(("OUVERT", "PARTIELLEMENT_REMBOURSE")),
            Encaissement.organisation_id == org_id,
            (Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE"),
        ]
        if devise_value:
            ft_filters.append(Encaissement.devise_perception == devise_value)
        if canal_value:
            ft_filters.append(Encaissement.canal == canal_value)
        if compte_id_value:
            ft_filters.append(Encaissement.compte_bancaire_id == compte_id_value)

        ft_rows = (
            await db.execute(
                select(
                    FondsTiersOperation.id,
                    func.coalesce(Encaissement.montant_paye, 0),
                )
                .join(Encaissement, Encaissement.id == FondsTiersOperation.encaissement_id)
                .where(*ft_filters)
            )
        ).all()
        if ft_rows:
            operation_ids = [row[0] for row in ft_rows]
            recu = sum((Decimal(str(row[1] or 0)) for row in ft_rows), Decimal("0"))
            reverse = Decimal(
                (
                    await db.execute(
                        select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).where(
                            SortieFonds.organisation_id == org_id,
                            SortieFonds.fonds_tiers_operation_id.in_(operation_ids),
                            SortieFonds.statut == "VALIDE",
                        )
                    )
                ).scalar_one()
                or 0
            )
            stats_out.fonds_tiers_solde = max(Decimal("0"), recu - reverse)
            stats_out.fonds_tiers_count = len(ft_rows)
    except Exception as exc:
        logger.error("Erreur critique Dashboard (fonds de tiers): %s", exc, exc_info=True)

    result = DashboardStatsResponse(
        stats=stats_out,
        daily_stats=daily_stats,
        period=PeriodInfo(start=date_start, end=date_end, label=period_type),
    )

    # Mise en cache — on sérialise via model_dump pour compatibilité JSON
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=DASHBOARD_CACHE_TTL)
    logger.debug("dashboard cache SET key=%s ttl=%ss", cache_key, DASHBOARD_CACHE_TTL)

    return result
