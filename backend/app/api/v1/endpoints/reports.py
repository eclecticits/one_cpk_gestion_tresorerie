from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, literal, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id
from app.core.cache import cache_get, cache_set
from app.services.encaissement_flux import (
    encaissements_retenus,
    flux_encaissements,
    nature_versement,
    versements_numerotes,
)
from app.services.report_cache import report_summary_cache_key
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.compte_bancaire import CompteBancaire
from app.models.banque import Banque
from app.models.transfert_interne import TransfertInterne
from app.models.cloture_caisse import ClotureCaisse
from app.models.requisition import Requisition
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.schemas.reports import (
    PeriodInfo,
    ReportAvailability,
    ReportBreakdownCount,
    ReportBreakdownCountTotal,
    ReportBreakdowns,
    ReportClotureResponse,
    ReportDailyStats,
    ReportDeviseTotals,
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
    ReportRetourLine,
    ReportVersementLine,
)
from app.schemas.sortie_fonds import SortieFondsOut
from app.api.v1.endpoints.exports import _nature_budgetaire_label
from app.utils.formatters import calculer_journal_avec_solde

router = APIRouter()
logger = logging.getLogger("onec_cpk_reports")

STATUT_PAIEMENT_INCLUS = ("complet", "partiel")
TRANSFERT_TYPES = ("versement_banque", "approvisionnement_caisse")
# Devises présentées en premier dans les totaux par devise ; toute autre devise
# rencontrée en base est ajoutée à la suite, par ordre alphabétique.
DEVISES_CONNUES = ("USD", "CDF")
REQUISITION_STATUT_EN_ATTENTE = (
    "EN_ATTENTE_COMMISSION",
    "EN_ATTENTE",
    "AUTORISEE",
    "APPROUVEE",
    "PENDING_VALIDATION_IMPORT",
)
# Approuvée et au-delà : une réquisition en cours de paiement par tranches
# (EN_DECAISSEMENT) a été approuvée comme les autres.
REQUISITION_STATUT_APPROUVEE = ("APPROUVEE", "EN_DECAISSEMENT", "PAYEE")


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
    devise: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ReportSummaryResponse:
    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    if date_start and date_end and date_start > date_end:
        date_start, date_end = date_end, date_start
    date_end_excl = _end_exclusive(date_end)
    daily_start, daily_end = _daily_range(date_start, date_end)
    canal_value = (canal or "").strip().upper() or None
    if canal_value == "ALL":
        canal_value = None
    if canal_value not in {None, "CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")

    # Filtre devise, symétrique du canal : `None` = toutes devises cumulées
    # (comportement historique, conservé pour les appelants qui ne le passent pas).
    devise_value = (devise or "").strip().upper() or None
    if devise_value == "ALL":
        devise_value = None
    if devise_value not in {None, *DEVISES_CONNUES}:
        raise HTTPException(status_code=400, detail="devise invalide")

    # Le résumé n'est cadré que par l'organisation (aucun filtrage par service
    # ou par utilisateur) : la clé n'a donc pas à intégrer l'appelant. Si un
    # filtrage par service est ajouté, la clé DOIT être étendue en conséquence.
    # La devise EST dans la clé : sans elle, une vue USD servirait ses chiffres
    # à une vue CDF pendant tout le TTL.
    cache_key = report_summary_cache_key(tenant_id, date_debut, date_fin, canal_value, devise_value)
    cached = await cache_get(cache_key)
    if cached is not None:
        return ReportSummaryResponse(**cached)

    availability = ReportAvailability(encaissements=True, sorties=True, requisitions=True)

    # Contrepartie entrante des transferts internes, vue depuis le canal filtré :
    # un versement (caisse -> banque) est une SORTIE de canal CAISSE mais une
    # ENTRÉE du canal BANQUE ; un approvisionnement (banque -> caisse) est
    # l'inverse. Sans ce terme, la vue par canal perd la moitié du mouvement et
    # son solde diverge du solde réel du compte / de la caisse (même correctif
    # que clotures.py:232 et journal-tresorerie).
    # Vue consolidée (canal = Tous) : les DEUX types comptent, et leur jambe
    # sortante compte aussi — les deux s'annulent dans le solde. Les afficher
    # (plutôt que de les masquer des deux côtés) rend le rapport auto-cohérent :
    # entrées + transferts reçus - sorties retombe sur le solde affiché.
    internal_in_types = {
        "BANQUE": ["versement_banque"],
        "CAISSE": ["approvisionnement_caisse"],
    }.get(canal_value or "", list(TRANSFERT_TYPES))

    # Comptes qui portent le solde d'OUVERTURE du périmètre. La caisse s'ouvre sur
    # ses comptes CASH, la banque sur ses comptes BANK : sans cette distinction, un
    # rapport « Caisse » démarrait avec l'ouverture des comptes bancaires (et
    # réciproquement). Même règle que treasury.py:79 (qui ne somme que les CASH
    # pour la caisse) et que journal-tresorerie (solde_initial du compte BANK visé).
    # `COALESCE` : une ligne insérée hors ORM sans account_type disparaîtrait
    # sinon de TOUTES les vues — le pire mode de défaillance ici.
    account_types = {
        "BANQUE": ["BANK"],
        "CAISSE": ["CASH"],
    }.get(canal_value or "", ["BANK", "CASH"])
    date_start_dt = (
        datetime.combine(date_start, datetime.min.time(), tzinfo=timezone.utc)
        if date_start
        else None
    )
    date_end_excl_dt = (
        datetime.combine(date_end_excl, datetime.min.time(), tzinfo=timezone.utc)
        if date_end_excl
        else None
    )
    daily_start_dt = datetime.combine(daily_start, datetime.min.time(), tzinfo=timezone.utc)
    daily_end_excl_dt = datetime.combine(
        daily_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )

    # Source canonique des encaissements : un paiement peut être fractionné et
    # chaque versement peut viser un canal / compte différent de l'en-tête.
    flux = flux_encaissements(tenant_id)
    flux_from = flux.join(Encaissement, Encaissement.id == flux.c.encaissement_id)
    # Une recette est un encaissement qui pèse sur le budget. Un fonds de tiers
    # ou un hors-budget à régulariser entre bien en trésorerie — il compte dans
    # le solde — mais n'est pas une recette : il est servi à part de
    # `encaissements_total`.
    est_recette = and_(
        Encaissement.nature_mouvement == "BUDGETAIRE",
        Encaissement.impact_budgetaire.is_(True),
    )

    def _range_conditions(column, start, end) -> list:
        conditions: list = []
        if start is not None:
            conditions.append(column >= start)
        if end is not None:
            conditions.append(column < end)
        return conditions

    def _encaissement_conditions(start=None, end=None, *, filter_devise: bool = True) -> list:
        conditions = [
            Encaissement.organisation_id == tenant_id,
            Encaissement.statut_paiement.in_(STATUT_PAIEMENT_INCLUS),
        ]
        if canal_value:
            conditions.append(flux.c.canal == canal_value)
        if filter_devise and devise_value:
            conditions.append(flux.c.devise == devise_value)
        conditions.extend(_range_conditions(flux.c.date_flux, start, end))
        return conditions

    sortie_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)

    def _sortie_range_conditions(start=None, end=None) -> list:
        """Filtre la date métier sans envelopper la colonne indexée.

        Les anciennes lignes sans ``date_paiement`` retombent sur ``created_at``;
        les lignes normales restent éligibles à l'index
        ``(organisation_id, date_paiement)``.
        """

        conditions: list = []
        if start is not None:
            conditions.append(
                or_(
                    SortieFonds.date_paiement >= start,
                    and_(
                        SortieFonds.date_paiement.is_(None),
                        SortieFonds.created_at >= start,
                    ),
                )
            )
        if end is not None:
            conditions.append(
                or_(
                    SortieFonds.date_paiement < end,
                    and_(
                        SortieFonds.date_paiement.is_(None),
                        SortieFonds.created_at < end,
                    ),
                )
            )
        return conditions

    def _sortie_conditions(start=None, end=None, *, filter_devise: bool = True) -> list:
        conditions = [
            SortieFonds.organisation_id == tenant_id,
            or_(SortieFonds.statut.is_(None), SortieFonds.statut == "VALIDE"),
        ]
        if canal_value:
            conditions.append(SortieFonds.canal == canal_value)
        if filter_devise and devise_value:
            conditions.append(SortieFonds.devise == devise_value)
        conditions.extend(_sortie_range_conditions(start, end))
        return conditions

    def _legacy_internal_in_conditions(
        start=None, end=None, *, filter_devise: bool = True
    ) -> list:
        conditions = [
            SortieFonds.organisation_id == tenant_id,
            or_(SortieFonds.statut.is_(None), SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie.in_(internal_in_types),
        ]
        if filter_devise and devise_value:
            conditions.append(SortieFonds.devise == devise_value)
        conditions.extend(_sortie_range_conditions(start, end))
        return conditions

    def _transfer_conditions(
        *, incoming: bool, start=None, end=None, filter_devise: bool = True
    ) -> list:
        pocket = TransfertInterne.destination_type if incoming else TransfertInterne.source_type
        conditions = [TransfertInterne.organisation_id == tenant_id]
        if canal_value:
            conditions.append(pocket == canal_value)
        if filter_devise and devise_value:
            conditions.append(TransfertInterne.devise == devise_value)
        conditions.extend(_range_conditions(TransfertInterne.date_transfert, start, end))
        return conditions

    def _retour_conditions(start=None, end=None, *, filter_devise: bool = True) -> list:
        conditions = [
            RetourCaisse.organisation_id == tenant_id,
            RetourCaisse.statut == "VALIDE",
        ]
        if canal_value:
            conditions.append(RetourCaisse.canal == canal_value)
        if filter_devise and devise_value:
            conditions.append(RetourCaisse.devise == devise_value)
        conditions.extend(_range_conditions(RetourCaisse.date_retour, start, end))
        return conditions

    async def _sum_amount(statement) -> Decimal:
        return Decimal((await db.execute(statement)).scalar_one() or 0)

    async def _daily_amounts(
        from_clause,
        timestamp,
        amount,
        conditions: list,
        *,
        date_conditions: list | None = None,
    ) -> dict[str, Decimal]:
        # Jour UTC, comme les bornes : un découpage au fuseau de la session
        # ferait tomber un mouvement hors de la plage qui l'a pourtant retenu.
        day = func.date(func.timezone("UTC", timestamp)).label("day")
        statement = (
            select(day, func.coalesce(func.sum(amount), 0).label("total"))
            .select_from(from_clause)
            .where(
                *conditions,
                *(
                    date_conditions
                    if date_conditions is not None
                    else _range_conditions(timestamp, daily_start_dt, daily_end_excl_dt)
                ),
            )
            .group_by(day)
            .order_by(day)
        )
        return {
            row.day.isoformat(): Decimal(row.total or 0)
            for row in (await db.execute(statement)).all()
            if row.day is not None
        }

    logger.info(
        "reports period start=%s end=%s canal=%s devise=%s",
        date_start,
        date_end,
        canal_value,
        devise_value,
    )

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
        opening_conditions = [
            CompteBancaire.organisation_id == tenant_id,
            CompteBancaire.is_active.is_(True),
            func.coalesce(CompteBancaire.account_type, "BANK").in_(account_types),
        ]
        if devise_value:
            opening_conditions.append(CompteBancaire.devise == devise_value)
        opening_balance = await _sum_amount(
            select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
                *opening_conditions
            )
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Solde d'ouverture du rapport indisponible: %s", exc, exc_info=True)
        opening_balance = Decimal("0")

    if date_start_dt:
        try:
            enc_before = await _sum_amount(
                select(func.coalesce(func.sum(flux.c.montant), 0))
                .select_from(flux_from)
                .where(*_encaissement_conditions(end=date_start_dt))
            )
            sorties_before = await _sum_amount(
                select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                    *_sortie_conditions(end=date_start_dt)
                )
            )
            transferts_sortants_before = await _sum_amount(
                select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                    *_transfer_conditions(incoming=False, end=date_start_dt)
                )
            )
            entrees_legacy_before = await _sum_amount(
                select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                    *_legacy_internal_in_conditions(end=date_start_dt)
                )
            )
            entrees_transferts_before = await _sum_amount(
                select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                    *_transfer_conditions(incoming=True, end=date_start_dt)
                )
            )
            retours_before = await _sum_amount(
                select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(
                    *_retour_conditions(end=date_start_dt)
                )
            )
            initial_balance = (
                opening_balance
                + enc_before
                + entrees_legacy_before
                + entrees_transferts_before
                + retours_before
                - sorties_before
                - transferts_sortants_before
            )
        except Exception as exc:
            await db.rollback()
            availability.encaissements = False
            availability.sorties = False
            logger.error("Solde initial du rapport indisponible: %s", exc, exc_info=True)
            initial_balance = Decimal("0")
    else:
        initial_balance = opening_balance

    try:
        enc_totaux = (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(case((est_recette, flux.c.montant), else_=0)), 0
                    ).label("recettes"),
                    func.coalesce(
                        func.sum(case((est_recette, 0), else_=flux.c.montant)), 0
                    ).label("hors_budget"),
                )
                .select_from(flux_from)
                .where(*_encaissement_conditions(date_start_dt, date_end_excl_dt))
            )
        ).one()
        totals.encaissements_total = Decimal(enc_totaux.recettes or 0)
        totals.encaissements_hors_budget = Decimal(enc_totaux.hors_budget or 0)
    except Exception as exc:
        await db.rollback()
        availability.encaissements = False
        logger.error("Total des encaissements indisponible: %s", exc, exc_info=True)
        totals.encaissements_total = Decimal("0")
        totals.encaissements_hors_budget = Decimal("0")

    try:
        # Ventilation des NOTES, tous statuts confondus : une note impayée n'a
        # aucun versement, d'où la jointure externe et le repli sur son en-tête
        # (canal, devise, date). Une note payée se range là où ses versements
        # sont réellement entrés.
        statut_conditions = [
            *encaissements_retenus(tenant_id),
            *_range_conditions(
                func.coalesce(flux.c.date_flux, Encaissement.date_encaissement),
                date_start_dt,
                date_end_excl_dt,
            ),
        ]
        if canal_value:
            statut_conditions.append(
                func.coalesce(flux.c.canal, Encaissement.canal) == canal_value
            )
        if devise_value:
            statut_conditions.append(
                func.coalesce(flux.c.devise, Encaissement.devise_perception) == devise_value
            )
        enc_statut = await db.execute(
            select(
                Encaissement.statut_paiement.label("statut"),
                func.count(func.distinct(Encaissement.id)).label("count"),
                func.coalesce(func.sum(flux.c.montant), 0).label("total"),
            )
            .select_from(Encaissement)
            .outerjoin(flux, flux.c.encaissement_id == Encaissement.id)
            .where(*statut_conditions)
            .group_by(Encaissement.statut_paiement)
            .order_by(Encaissement.statut_paiement)
        )
        par_statut_paiement = [
            ReportBreakdownCountTotal(
                key=row.statut,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_statut
        ]
    except Exception as exc:
        await db.rollback()
        availability.encaissements = False
        logger.error("Ventilation des encaissements par statut indisponible: %s", exc, exc_info=True)
        par_statut_paiement = []

    try:
        enc_modes = await db.execute(
            select(
                flux.c.mode_paiement.label("mode"),
                func.count(func.distinct(Encaissement.id)).label("count"),
                func.coalesce(func.sum(flux.c.montant), 0).label("total"),
            )
            .select_from(flux_from)
            .where(*_encaissement_conditions(date_start_dt, date_end_excl_dt))
            .group_by(flux.c.mode_paiement)
            .order_by(flux.c.mode_paiement)
        )
        par_mode_paiement_enc = [
            ReportBreakdownCountTotal(
                key=row.mode,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_modes
        ]
    except Exception as exc:
        await db.rollback()
        availability.encaissements = False
        logger.error("Ventilation des encaissements par mode indisponible: %s", exc, exc_info=True)
        par_mode_paiement_enc = []

    try:
        poste_expr = case(
            (
                and_(
                    Encaissement.budget_poste_code.is_(None),
                    Encaissement.budget_poste_libelle.is_(None),
                ),
                "Non renseigné",
            ),
            (Encaissement.budget_poste_code.is_(None), Encaissement.budget_poste_libelle),
            (Encaissement.budget_poste_libelle.is_(None), Encaissement.budget_poste_code),
            else_=(
                Encaissement.budget_poste_code
                + literal(" - ")
                + Encaissement.budget_poste_libelle
            ),
        ).label("poste")
        enc_postes = await db.execute(
            select(
                poste_expr,
                func.count(func.distinct(Encaissement.id)).label("count"),
                func.coalesce(func.sum(flux.c.montant), 0).label("total"),
            )
            .select_from(flux_from)
            .where(*_encaissement_conditions(date_start_dt, date_end_excl_dt))
            .group_by(poste_expr)
            .order_by(poste_expr)
        )
        par_poste_budgetaire = [
            ReportBreakdownCountTotal(
                key=row.poste,
                count=int(row.count or 0),
                total=Decimal(row.total or 0),
            )
            for row in enc_postes
        ]
    except Exception as exc:
        await db.rollback()
        availability.encaissements = False
        logger.error("Ventilation des encaissements par poste indisponible: %s", exc, exc_info=True)
        par_poste_budgetaire = []

    sorties_daily_map: dict[str, Decimal] = {}
    transferts_sortants_daily_map: dict[str, Decimal] = {}
    entrees_daily_map: dict[str, Decimal] = {}
    retours_daily_map: dict[str, Decimal] = {}
    enc_daily_map: dict[str, Decimal] = {}

    try:
        enc_daily_map = await _daily_amounts(
            flux_from,
            flux.c.date_flux,
            flux.c.montant,
            _encaissement_conditions(),
        )
    except Exception as exc:
        await db.rollback()
        availability.encaissements = False
        logger.error("Encaissements journaliers indisponibles: %s", exc, exc_info=True)
        enc_daily_map = {}

    try:
        sorties_legacy = await _sum_amount(
            select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                *_sortie_conditions(date_start_dt, date_end_excl_dt)
            )
        )
        transferts_sortants = await _sum_amount(
            select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                *_transfer_conditions(
                    incoming=False,
                    start=date_start_dt,
                    end=date_end_excl_dt,
                )
            )
        )
        # sorties_total = tous les mouvements sortants (sert au solde, cohérent
        # avec le solde initial). Le détail dépenses réelles / transferts internes
        # est fourni séparément ci-dessous pour l'affichage.
        totals.sorties_total = sorties_legacy + transferts_sortants

        # Détail : transferts internes (versement/approvisionnement) et dépenses
        # réelles (le reste). Pour l'affichage « combien réellement dépensé ».
        transferts_legacy = await _sum_amount(
            select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                *_sortie_conditions(date_start_dt, date_end_excl_dt),
                SortieFonds.type_sortie.in_(TRANSFERT_TYPES),
            )
        )
        totals.transferts_internes = transferts_legacy + transferts_sortants
        totals.depenses_reelles = totals.sorties_total - totals.transferts_internes

        # Jambe ENTRANTE des transferts internes du périmètre (versements reçus en
        # banque / approvisionnements reçus en caisse ; les deux en vue consolidée).
        # Pas de filtre sur `canal` : la ligne porte justement le canal opposé.
        entrees_legacy = await _sum_amount(
            select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                *_legacy_internal_in_conditions(date_start_dt, date_end_excl_dt)
            )
        )
        entrees_transferts = await _sum_amount(
            select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                *_transfer_conditions(
                    incoming=True,
                    start=date_start_dt,
                    end=date_end_excl_dt,
                )
            )
        )
        totals.entrees_internes = entrees_legacy + entrees_transferts
        totals.retours_total = await _sum_amount(
            select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(
                *_retour_conditions(date_start_dt, date_end_excl_dt)
            )
        )
        totals.sorties_nettes = totals.sorties_total - totals.retours_total
    except Exception as exc:
        await db.rollback()
        availability.sorties = False
        logger.error("Flux sortants du rapport indisponibles: %s", exc, exc_info=True)
        totals.sorties_total = Decimal("0")
        totals.transferts_internes = Decimal("0")
        totals.depenses_reelles = Decimal("0")
        totals.entrees_internes = Decimal("0")
        totals.retours_total = Decimal("0")
        totals.sorties_nettes = Decimal("0")

    try:
        sorties_modes = await db.execute(
            select(
                SortieFonds.mode_paiement.label("mode"),
                func.count(SortieFonds.id).label("count"),
                func.coalesce(func.sum(SortieFonds.montant_paye), 0).label("total"),
            )
            .where(*_sortie_conditions(date_start_dt, date_end_excl_dt))
            .group_by(SortieFonds.mode_paiement)
            .order_by(SortieFonds.mode_paiement)
        )
        modes = {
            str(row.mode or "non_renseigne"): {
                "count": int(row.count or 0),
                "total": Decimal(row.total or 0),
            }
            for row in sorties_modes
        }
        transfert_mode = (
            await db.execute(
                select(
                    func.count(TransfertInterne.id).label("count"),
                    func.coalesce(func.sum(TransfertInterne.montant), 0).label("total"),
                ).where(
                    *_transfer_conditions(
                        incoming=False,
                        start=date_start_dt,
                        end=date_end_excl_dt,
                    )
                )
            )
        ).one()
        if transfert_mode.count:
            modes["transfert_interne"] = {
                "count": int(transfert_mode.count),
                "total": Decimal(transfert_mode.total or 0),
            }
        par_mode_paiement_sorties = [
            ReportBreakdownCountTotal(key=mode, **values)
            for mode, values in sorted(modes.items())
        ]
    except Exception as exc:
        await db.rollback()
        availability.sorties = False
        logger.error("Ventilation des sorties par mode indisponible: %s", exc, exc_info=True)
        par_mode_paiement_sorties = []

    try:
        sorties_legacy_daily = await _daily_amounts(
            SortieFonds,
            sortie_ts,
            SortieFonds.montant_paye,
            _sortie_conditions(),
            date_conditions=_sortie_range_conditions(daily_start_dt, daily_end_excl_dt),
        )
        transferts_legacy_daily = await _daily_amounts(
            SortieFonds,
            sortie_ts,
            SortieFonds.montant_paye,
            [*_sortie_conditions(), SortieFonds.type_sortie.in_(TRANSFERT_TYPES)],
            date_conditions=_sortie_range_conditions(daily_start_dt, daily_end_excl_dt),
        )
        transferts_dedies_daily = await _daily_amounts(
            TransfertInterne,
            TransfertInterne.date_transfert,
            TransfertInterne.montant,
            _transfer_conditions(incoming=False),
        )
        entrees_legacy_daily = await _daily_amounts(
            SortieFonds,
            sortie_ts,
            SortieFonds.montant_paye,
            _legacy_internal_in_conditions(),
            date_conditions=_sortie_range_conditions(daily_start_dt, daily_end_excl_dt),
        )
        entrees_dediees_daily = await _daily_amounts(
            TransfertInterne,
            TransfertInterne.date_transfert,
            TransfertInterne.montant,
            _transfer_conditions(incoming=True),
        )
        retours_daily_map = await _daily_amounts(
            RetourCaisse,
            RetourCaisse.date_retour,
            RetourCaisse.montant,
            _retour_conditions(),
        )
        daily_keys = (
            set(sorties_legacy_daily)
            | set(transferts_legacy_daily)
            | set(transferts_dedies_daily)
            | set(entrees_legacy_daily)
            | set(entrees_dediees_daily)
        )
        for key in daily_keys:
            sortie_legacy = sorties_legacy_daily.get(key, Decimal("0"))
            transfert_dedie = transferts_dedies_daily.get(key, Decimal("0"))
            sorties_daily_map[key] = sortie_legacy + transfert_dedie
            transferts_sortants_daily_map[key] = (
                transferts_legacy_daily.get(key, Decimal("0")) + transfert_dedie
            )
            entrees_daily_map[key] = (
                entrees_legacy_daily.get(key, Decimal("0"))
                + entrees_dediees_daily.get(key, Decimal("0"))
            )
    except Exception as exc:
        await db.rollback()
        availability.sorties = False
        logger.error("Flux journaliers sortants indisponibles: %s", exc, exc_info=True)
        sorties_daily_map = {}
        transferts_sortants_daily_map = {}
        entrees_daily_map = {}
        retours_daily_map = {}

    current = daily_start
    while current <= daily_end:
        key = current.isoformat()
        enc_v = enc_daily_map.get(key, Decimal("0"))
        sor_v = sorties_daily_map.get(key, Decimal("0"))
        ret_v = retours_daily_map.get(key, Decimal("0"))
        transferts_v = transferts_sortants_daily_map.get(key, Decimal("0"))
        entrees_v = entrees_daily_map.get(key, Decimal("0"))
        par_jour.append(
            ReportDailyStats(
                date=current,
                encaissements=enc_v,
                sorties=sor_v,
                retours=ret_v,
                sorties_nettes=sor_v - ret_v,
                transferts_internes=transferts_v,
                entrees_internes=entrees_v,
                solde=enc_v + entrees_v + ret_v - sor_v,
            )
        )
        current += timedelta(days=1)

    try:
        requisition_conditions = [
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
            *_range_conditions(Requisition.created_at, date_start_dt, date_end_excl_dt),
        ]
        req_by_status = await db.execute(
            select(
                Requisition.status.label("statut"),
                func.count(Requisition.id).label("count"),
            )
            .where(*requisition_conditions)
            .group_by(Requisition.status)
            .order_by(Requisition.status)
        )
        counts_by_status = {
            str(row.statut): int(row.count or 0)
            for row in req_by_status
        }
        requisitions_summary.total = sum(counts_by_status.values())
        requisitions_summary.en_attente = sum(
            counts_by_status.get(status, 0) for status in REQUISITION_STATUT_EN_ATTENTE
        )
        requisitions_summary.approuvees = sum(
            counts_by_status.get(status, 0) for status in REQUISITION_STATUT_APPROUVEE
        )
        par_statut_requisition = [
            ReportBreakdownCount(key=status, count=count)
            for status, count in counts_by_status.items()
        ]
    except Exception as exc:
        await db.rollback()
        availability.requisitions = False
        logger.error("Statistiques des réquisitions indisponibles: %s", exc, exc_info=True)
        requisitions_summary = ReportRequisitionsSummary()
        par_statut_requisition = []

    totals.solde_initial = initial_balance
    # Formule unique, quel que soit le canal : toutes les sorties sont retranchées,
    # et la jambe entrante des transferts internes est ajoutée. En vue consolidée
    # les deux jambes se compensent exactement (le solde vaut donc, comme avant,
    # solde_initial + encaissements - depenses_reelles) mais les deux montants
    # restent visibles au lieu d'être masqués des deux côtés.
    totals.flux_periode = (
        totals.encaissements_total
        + totals.encaissements_hors_budget
        + totals.entrees_internes
        + totals.retours_total
        - totals.sorties_total
    )
    totals.solde = totals.solde_initial + totals.flux_periode
    totals.solde_final = totals.solde

    # --- Totaux par devise -------------------------------------------------
    # Les champs plats ci-dessus additionnent des montants de devises différentes
    # (une sortie est stockée dans SA devise) : sur une organisation qui manipule
    # USD et CDF, `sorties_total` ne veut rien dire. On recalcule donc les mêmes
    # agrégats groupés par devise, sans conversion. Chaque requête sépare
    # « avant la période » (pour le solde d'ouverture) et « dans la période » par
    # agrégation conditionnelle, pour ne pas doubler le nombre d'aller-retours.
    #
    # Ce bloc IGNORE volontairement le filtre `devise` : quelle que soit la devise
    # regardée, le tableau montre toutes les devises. C'est ce qui garantit qu'un
    # utilisateur en vue USD voit qu'il existe des mouvements CDF hors de son
    # écran, au lieu de croire son rapport exhaustif.
    try:
        async def _amounts_by_currency(
            from_clause,
            currency,
            timestamp,
            amount,
            conditions: list,
            *,
            transfer_condition=None,
        ) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
            """Agrège avant/période sans fonction sur les colonnes filtrées."""

            currency_expr = func.coalesce(currency, "USD")
            before_value = (
                case((timestamp < date_start_dt, amount), else_=0)
                if date_start_dt
                else literal(0)
            )
            period_conditions = _range_conditions(
                timestamp, date_start_dt, date_end_excl_dt
            )
            period_condition = and_(*period_conditions) if period_conditions else true()
            period_value = case((period_condition, amount), else_=0)
            transfer_value = (
                case(
                    (and_(period_condition, transfer_condition), amount),
                    else_=0,
                )
                if transfer_condition is not None
                else literal(0)
            )
            rows = await db.execute(
                select(
                    currency_expr.label("devise"),
                    func.coalesce(func.sum(before_value), 0).label("avant"),
                    func.coalesce(func.sum(period_value), 0).label("periode"),
                    func.coalesce(func.sum(transfer_value), 0).label("transferts"),
                )
                .select_from(from_clause)
                .where(*conditions)
                .group_by(currency_expr)
            )
            result: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
            for row in rows:
                key = str(row.devise or "USD").upper()
                previous = result.get(
                    key, (Decimal("0"), Decimal("0"), Decimal("0"))
                )
                result[key] = (
                    previous[0] + Decimal(row.avant or 0),
                    previous[1] + Decimal(row.periode or 0),
                    previous[2] + Decimal(row.transferts or 0),
                )
            return result

        enc_map = await _amounts_by_currency(
            flux_from,
            flux.c.devise,
            flux.c.date_flux,
            flux.c.montant,
            _encaissement_conditions(filter_devise=False),
            # Troisième valeur : la part de la période qui n'est pas une recette.
            transfer_condition=~est_recette,
        )
        sorties_legacy_map = await _amounts_by_currency(
            SortieFonds,
            SortieFonds.devise,
            sortie_ts,
            SortieFonds.montant_paye,
            _sortie_conditions(filter_devise=False),
            transfer_condition=SortieFonds.type_sortie.in_(TRANSFERT_TYPES),
        )
        transferts_sortants_map = await _amounts_by_currency(
            TransfertInterne,
            TransfertInterne.devise,
            TransfertInterne.date_transfert,
            TransfertInterne.montant,
            _transfer_conditions(incoming=False, filter_devise=False),
            transfer_condition=true(),
        )
        entrees_legacy_map = await _amounts_by_currency(
            SortieFonds,
            SortieFonds.devise,
            sortie_ts,
            SortieFonds.montant_paye,
            _legacy_internal_in_conditions(filter_devise=False),
        )
        entrees_transferts_map = await _amounts_by_currency(
            TransfertInterne,
            TransfertInterne.devise,
            TransfertInterne.date_transfert,
            TransfertInterne.montant,
            _transfer_conditions(incoming=True, filter_devise=False),
        )
        retours_map = await _amounts_by_currency(
            RetourCaisse,
            RetourCaisse.devise,
            RetourCaisse.date_retour,
            RetourCaisse.montant,
            _retour_conditions(filter_devise=False),
        )

        opening_currency = func.coalesce(CompteBancaire.devise, "USD")
        opening_devise_res = await db.execute(
            select(
                opening_currency.label("devise"),
                func.coalesce(func.sum(CompteBancaire.solde_initial), 0).label("total"),
            )
            .where(
                CompteBancaire.organisation_id == tenant_id,
                CompteBancaire.is_active.is_(True),
                func.coalesce(CompteBancaire.account_type, "BANK").in_(account_types),
            )
            .group_by(opening_currency)
        )
        opening_map: dict[str, Decimal] = {}
        for row in opening_devise_res:
            key = str(row.devise or "USD").upper()
            opening_map[key] = opening_map.get(key, Decimal("0")) + Decimal(
                row.total or 0
            )

        devises = (
            set(enc_map)
            | set(sorties_legacy_map)
            | set(transferts_sortants_map)
            | set(entrees_legacy_map)
            | set(entrees_transferts_map)
            | set(retours_map)
            | set(opening_map)
        )
        ordonnees = [d for d in DEVISES_CONNUES if d in devises] + sorted(
            d for d in devises if d not in DEVISES_CONNUES
        )

        par_devise: list[ReportDeviseTotals] = []
        for devise in ordonnees:
            zero = (Decimal("0"), Decimal("0"), Decimal("0"))
            enc_avant_d, enc_periode_d, enc_hors_budget_d = enc_map.get(devise, zero)
            sor_avant_d, sor_periode_d, transf_legacy_d = sorties_legacy_map.get(
                devise, zero
            )
            transf_avant_d, transf_periode_d, _ = transferts_sortants_map.get(
                devise, zero
            )
            ent_legacy_avant_d, ent_legacy_periode_d, _ = entrees_legacy_map.get(
                devise, zero
            )
            ent_transfert_avant_d, ent_transfert_periode_d, _ = (
                entrees_transferts_map.get(devise, zero)
            )
            retour_avant_d, retour_periode_d, _ = retours_map.get(devise, zero)
            sorties_brutes_d = sor_periode_d + transf_periode_d
            transferts_d = transf_legacy_d + transf_periode_d
            entrees_avant_d = ent_legacy_avant_d + ent_transfert_avant_d
            entrees_periode_d = ent_legacy_periode_d + ent_transfert_periode_d
            solde_initial_d = (
                opening_map.get(devise, Decimal("0"))
                + enc_avant_d
                + entrees_avant_d
                + retour_avant_d
                - sor_avant_d
                - transf_avant_d
            )
            flux_periode_d = (
                enc_periode_d
                + entrees_periode_d
                + retour_periode_d
                - sorties_brutes_d
            )
            ligne = ReportDeviseTotals(
                devise=devise,
                encaissements_total=enc_periode_d - enc_hors_budget_d,
                encaissements_hors_budget=enc_hors_budget_d,
                sorties_total=sorties_brutes_d,
                depenses_reelles=sorties_brutes_d - transferts_d,
                transferts_internes=transferts_d,
                entrees_internes=entrees_periode_d,
                retours_total=retour_periode_d,
                sorties_nettes=sorties_brutes_d - retour_periode_d,
                flux_periode=flux_periode_d,
                solde_initial=solde_initial_d,
                solde=solde_initial_d + flux_periode_d,
            )
            # Une devise sans aucun mouvement ni ouverture n'apporte qu'une ligne
            # de zéros : on ne l'expose pas.
            if any(
                value
                for value in (
                    ligne.encaissements_total,
                    ligne.encaissements_hors_budget,
                    ligne.sorties_total,
                    ligne.entrees_internes,
                    ligne.retours_total,
                    ligne.solde_initial,
                )
            ):
                par_devise.append(ligne)
        totals.par_devise = par_devise
    except Exception as exc:
        # Dégradation volontaire : les champs plats restent servis, seul le détail
        # par devise manque (le front sait retomber dessus).
        await db.rollback()
        logger.warning("totaux par devise indisponibles: %s", exc, exc_info=True)
        totals.par_devise = []

    # Le décompte sort de la ventilation par mode, déjà calculée : inutile de
    # réinterroger la base pour une ligne de journal.
    logger.info(
        "sorties period count=%s",
        sum(item.count for item in par_mode_paiement_sorties),
    )

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

    response = ReportSummaryResponse(
        stats=stats,
        daily_stats=par_jour,
        period=PeriodInfo(start=daily_start, end=daily_end, label="custom"),
    )
    await cache_set(cache_key, response.model_dump(mode="json"), ttl=settings.report_summary_cache_ttl_seconds)
    return response


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
    # Vue consolidée (canal = Tous) : le solde annuel ne compte que les dépenses
    # réelles (hors transferts internes). Par canal, tous les mouvements comptent.
    sort_transfer_filter = (
        "AND type_sortie NOT IN ('versement_banque', 'approvisionnement_caisse')"
        if canal == "ALL"
        else ""
    )

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
              AND COALESCE(statut_operation, 'ACTIVE') = 'ACTIVE'
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
              {sort_transfer_filter}
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
              AND COALESCE(statut_operation, 'ACTIVE') = 'ACTIVE'
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
        # Exclure les transferts internes (versement/approvisionnement) : ce ne
        # sont pas des dépenses.
        .where(SortieFonds.type_sortie.notin_(("versement_banque", "approvisionnement_caisse")))
        # Un remboursement de fonds de tiers est une sortie de trésorerie et une
        # dette éteinte, pas une dépense de l'organisation.
        .where(or_(SortieFonds.nature_mouvement.is_(None), SortieFonds.nature_mouvement != "FONDS_DE_TIERS"))
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


@router.get("/versements", response_model=list[ReportVersementLine])
async def versements(
    date_debut: str | None = None,
    date_fin: str | None = None,
    canal: str | None = None,
    devise: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[ReportVersementLine]:
    """Détail des encaissements du rapport : une ligne par versement, à sa date.

    La liste des notes (`GET /encaissements`) filtre sur la date de la NOTE et
    montre son cumul payé : le complément versé cinq jours après l'acompte n'y
    apparaissait pas à son jour, et le jour de l'acompte affichait de l'argent
    pas encore reçu. Le détail divergeait ainsi du total du résumé, lui calculé
    au versement. Cette liste reprend exactement le périmètre de ce total
    (mêmes bornes, même filtre de statut) : sa somme lui est égale.
    """
    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    if date_start and date_end and date_start > date_end:
        date_start, date_end = date_end, date_start
    date_end_excl = _end_exclusive(date_end)
    canal_value = (canal or "").strip().upper() or None
    if canal_value == "ALL":
        canal_value = None
    if canal_value not in {None, "CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")
    devise_value = (devise or "").strip().upper() or None
    if devise_value == "ALL":
        devise_value = None
    if devise_value not in {None, *DEVISES_CONNUES}:
        raise HTTPException(status_code=400, detail="devise invalide")

    v = versements_numerotes(tenant_id)
    conditions = [
        Encaissement.organisation_id == tenant_id,
        Encaissement.statut_paiement.in_(STATUT_PAIEMENT_INCLUS),
    ]
    if canal_value:
        conditions.append(v.c.canal == canal_value)
    if devise_value:
        conditions.append(v.c.devise == devise_value)
    if date_start:
        conditions.append(
            v.c.date_flux >= datetime.combine(date_start, datetime.min.time(), tzinfo=timezone.utc)
        )
    if date_end_excl:
        conditions.append(
            v.c.date_flux < datetime.combine(date_end_excl, datetime.min.time(), tzinfo=timezone.utc)
        )

    rows = (
        await db.execute(
            select(v, Encaissement, ExpertComptable.nom_denomination, ExpertComptable.numero_ordre)
            .select_from(v)
            .join(Encaissement, Encaissement.id == v.c.encaissement_id)
            .outerjoin(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
            .where(*conditions)
            .order_by(v.c.date_flux, Encaissement.numero_recu, v.c.rang)
        )
    ).all()

    lignes: list[ReportVersementLine] = []
    for row in rows:
        enc: Encaissement = row.Encaissement
        montant_total = Decimal(enc.montant_total or enc.montant or 0)
        cumul = Decimal(row.cumul or 0)
        lignes.append(
            ReportVersementLine(
                id=str(row.versement_id or enc.id),
                encaissement_id=enc.id,
                versement_id=row.versement_id,
                date_versement=row.date_flux,
                date_encaissement=enc.date_encaissement,
                numero_recu=enc.numero_recu,
                type_client=enc.type_client,
                client_nom=enc.client_nom,
                expert_comptable=(
                    {"nom_denomination": row.nom_denomination, "numero_ordre": row.numero_ordre}
                    if row.nom_denomination
                    else None
                ),
                libelle=enc.libelle,
                description=enc.description,
                budget_poste_code=enc.budget_poste_code,
                budget_poste_libelle=enc.budget_poste_libelle,
                canal=row.canal,
                compte_bancaire_id=row.compte_bancaire_id,
                devise_perception=row.devise or "USD",
                mode_paiement=row.mode_paiement,
                reference=row.reference,
                montant_paye=Decimal(row.montant or 0),
                montant_percu=Decimal(row.montant or 0),
                montant_total=montant_total,
                cumul_paye=cumul,
                reste_apres=max(montant_total - cumul, Decimal("0")),
                rang=int(row.rang or 1),
                nombre_versements=int(row.nombre or 1),
                nature_versement=nature_versement(int(row.rang or 1), montant_total, cumul),
                statut_paiement=enc.statut_paiement,
                nature_budgetaire=_nature_budgetaire_label(enc),
                # Même règle que `est_recette` du résumé.
                est_recette=(
                    (enc.nature_mouvement or "BUDGETAIRE") == "BUDGETAIRE"
                    and bool(enc.impact_budgetaire)
                ),
            )
        )
    return lignes


RETOUR_TYPE_LIBELLES = {
    "reliquat_avance": "Reliquat d'avance",
    "correction": "Correction",
    "trop_percu": "Trop-perçu",
}


def _retours_cumules(tenant_id: int):
    """Retours valides, chacun avec le cumul rendu sur sa sortie APRÈS lui.

    Le cumul porte sur toute l'histoire de la sortie : filtrer la période
    autour de cette sous-requête, jamais dedans.
    """
    return select(
        RetourCaisse.id.label("retour_id"),
        func.sum(RetourCaisse.montant)
        .over(
            partition_by=RetourCaisse.sortie_fonds_id,
            order_by=(RetourCaisse.date_retour, RetourCaisse.id),
        )
        .label("cumul"),
    ).where(
        RetourCaisse.organisation_id == tenant_id,
        RetourCaisse.statut == "VALIDE",
    ).subquery("retours_cumules")


@router.get("/retours", response_model=list[ReportRetourLine])
async def retours(
    date_debut: str | None = None,
    date_fin: str | None = None,
    canal: str | None = None,
    devise: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[ReportRetourLine]:
    """Détail des retours en trésorerie : une ligne par retour, à sa date.

    Le résumé comptait bien les retours du jour (« Retours en trésorerie »),
    mais aucun écran ne les listait : un reliquat de transport rendu
    aujourd'hui sur une avance d'il y a deux semaines n'apparaissait nulle
    part à sa date. Même périmètre que `retours_total` du résumé.
    """
    date_start = _parse_date_value(date_debut)
    date_end = _parse_date_value(date_fin)
    if date_start and date_end and date_start > date_end:
        date_start, date_end = date_end, date_start
    date_end_excl = _end_exclusive(date_end)
    canal_value = (canal or "").strip().upper() or None
    if canal_value == "ALL":
        canal_value = None
    if canal_value not in {None, "CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="canal invalide")
    devise_value = (devise or "").strip().upper() or None
    if devise_value == "ALL":
        devise_value = None
    if devise_value not in {None, *DEVISES_CONNUES}:
        raise HTTPException(status_code=400, detail="devise invalide")

    cumuls = _retours_cumules(tenant_id)
    conditions = [
        RetourCaisse.organisation_id == tenant_id,
        RetourCaisse.statut == "VALIDE",
    ]
    if canal_value:
        conditions.append(RetourCaisse.canal == canal_value)
    if devise_value:
        conditions.append(RetourCaisse.devise == devise_value)
    if date_start:
        conditions.append(
            RetourCaisse.date_retour >= datetime.combine(date_start, datetime.min.time(), tzinfo=timezone.utc)
        )
    if date_end_excl:
        conditions.append(
            RetourCaisse.date_retour < datetime.combine(date_end_excl, datetime.min.time(), tzinfo=timezone.utc)
        )

    rows = (
        await db.execute(
            select(RetourCaisse, SortieFonds, Requisition.numero_requisition, cumuls.c.cumul)
            .join(SortieFonds, SortieFonds.id == RetourCaisse.sortie_fonds_id)
            .outerjoin(Requisition, Requisition.id == SortieFonds.requisition_id)
            .join(cumuls, cumuls.c.retour_id == RetourCaisse.id)
            .where(*conditions)
            .order_by(RetourCaisse.date_retour, RetourCaisse.id)
        )
    ).all()

    lignes: list[ReportRetourLine] = []
    for retour, sortie, numero_requisition, cumul in rows:
        montant_sortie = Decimal(sortie.montant_paye or 0)
        cumul = Decimal(cumul or 0)
        lignes.append(
            ReportRetourLine(
                id=retour.id,
                date_retour=retour.date_retour,
                reference_numero=retour.reference_numero,
                type_retour=RETOUR_TYPE_LIBELLES.get(retour.type_retour, retour.type_retour),
                motif=retour.motif,
                montant=Decimal(retour.montant or 0),
                devise=retour.devise or "USD",
                canal=retour.canal or "CAISSE",
                compte_bancaire_id=retour.compte_bancaire_id,
                mode=retour.mode,
                budget_poste_code=retour.budget_poste_code,
                budget_poste_libelle=retour.budget_poste_libelle,
                sortie_fonds_id=sortie.id,
                sortie_reference=sortie.reference_numero or sortie.reference,
                sortie_date=sortie.date_paiement or sortie.created_at,
                sortie_beneficiaire=sortie.beneficiaire,
                sortie_motif=sortie.motif,
                sortie_montant=montant_sortie,
                numero_requisition=numero_requisition,
                total_retourne_apres=cumul,
                reste_a_justifier_apres=max(montant_sortie - cumul, Decimal("0")),
            )
        )
    return lignes


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

    # Une note réglée en plusieurs fois peut viser deux destinations : l'acompte
    # au tiroir, le solde par virement. Ce relevé suit donc les versements, pas
    # l'en-tête — sinon le compte bancaire se verrait crédité de tout, acompte
    # en espèces compris, et la caisse de rien.
    flux = flux_encaissements(tenant_id)

    def _flux_du_compte(query):
        query = query.where(flux.c.canal == canal, flux.c.devise == devise)
        if compte_bancaire_id:
            query = query.where(flux.c.compte_bancaire_id == compte_bancaire_id)
        return query

    async def _sum_encaissements(before: bool) -> Decimal:
        query = _flux_du_compte(select(func.coalesce(func.sum(flux.c.montant), 0)))
        if base_date:
            query = query.where(flux.c.date_flux >= base_date)
        if start_dt and before:
            query = query.where(flux.c.date_flux < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(flux.c.date_flux >= start_dt, flux.c.date_flux <= end_dt)
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
        # NE PAS filtrer sur `TransfertInterne.statut`. La correction d'un transfert
        # est additive : l'original (CONTREPASSE) et sa ligne inverse (EXECUTE)
        # coexistent et s'annulent arithmétiquement. Exclure l'original en gardant
        # l'inverse produirait un net inversé, c'est-à-dire de l'argent créé de rien.
        query = select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
            TransfertInterne.organisation_id == tenant_id,
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

    _sortie_ts = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)

    async def _sum_appro(before: bool) -> Decimal:
        # Approvisionnements (banque -> caisse) : ENTRÉES de la caisse. Modélisés
        # en SortieFonds canal=BANQUE, donc absents des sorties caisse ci-dessus.
        if canal != "CAISSE":
            return Decimal("0")
        query = select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "approvisionnement_caisse",
            SortieFonds.devise == devise,
            SortieFonds.organisation_id == tenant_id,
        )
        if base_date:
            query = query.where(_sortie_ts >= base_date)
        if start_dt and before:
            query = query.where(_sortie_ts < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(_sortie_ts >= start_dt, _sortie_ts <= end_dt)
        return Decimal((await db.execute(query)).scalar_one() or 0)

    async def _sum_versement(before: bool) -> Decimal:
        # Versements (caisse -> banque) : ENTRÉES du compte bancaire destinataire.
        # Modélisés en SortieFonds canal=CAISSE, donc absents des sorties banque.
        if canal != "BANQUE" or not compte_bancaire_id:
            return Decimal("0")
        query = select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "versement_banque",
            SortieFonds.compte_bancaire_id == compte_bancaire_id,
            SortieFonds.devise == devise,
            SortieFonds.organisation_id == tenant_id,
        )
        if base_date:
            query = query.where(_sortie_ts >= base_date)
        if start_dt and before:
            query = query.where(_sortie_ts < start_dt)
        if start_dt and not before and end_dt:
            query = query.where(_sortie_ts >= start_dt, _sortie_ts <= end_dt)
        return Decimal((await db.execute(query)).scalar_one() or 0)

    def _retours_du_compte(query):
        # Un retour recrédite la trésorerie qui l'a reçu, à SA date : même
        # filtre de compte que les sorties dont il est le miroir.
        query = query.where(
            RetourCaisse.organisation_id == tenant_id,
            RetourCaisse.statut == "VALIDE",
            RetourCaisse.canal == canal,
            RetourCaisse.devise == devise,
        )
        if compte_bancaire_id:
            query = query.where(RetourCaisse.compte_bancaire_id == compte_bancaire_id)
        if base_date:
            query = query.where(RetourCaisse.date_retour >= base_date)
        return query

    async def _sum_retours(before: bool) -> Decimal:
        query = _retours_du_compte(select(func.coalesce(func.sum(RetourCaisse.montant), 0)))
        if start_dt and before:
            query = query.where(RetourCaisse.date_retour < start_dt)
        return Decimal((await db.execute(query)).scalar_one() or 0)

    if start_dt:
        pre_entrees = (
            (await _sum_encaissements(True))
            + (await _sum_transferts(True, True))
            + (await _sum_appro(True))
            + (await _sum_versement(True))
            # Les retours manquaient : la caisse les avait reçus, le relevé non,
            # et son solde divergeait de celui de la clôture.
            + (await _sum_retours(True))
        )
        pre_sorties = (await _sum_sorties(True)) + (await _sum_transferts(True, False))
        solde_initial = solde_base + pre_entrees - pre_sorties
    else:
        solde_initial = solde_base

    mouvements: list[dict] = []

    # Une ligne par VERSEMENT, à sa date, du montant réellement entré ICI. Une
    # ligne par note datée de son premier versement ramenait le complément
    # d'une note soldée plus tard au jour de l'acompte : introuvable à sa date,
    # et le solde courant du relevé faux entre les deux. Le rapprochement reste
    # porté par la note (`is_reconciled` vit sur l'encaissement) : ses lignes
    # partagent donc la même case.
    v = versements_numerotes(tenant_id)
    enc_query = (
        select(
            Encaissement.id,
            v.c.date_flux,
            Encaissement.libelle,
            Encaissement.numero_recu,
            func.coalesce(v.c.reference, Encaissement.reference).label("reference"),
            v.c.montant,
            v.c.rang,
            v.c.nombre,
            v.c.cumul,
            Encaissement.montant_total,
            Encaissement.is_reconciled,
            Encaissement.reconciled_at,
            Encaissement.bank_statement_ref,
        )
        .select_from(v)
        .join(Encaissement, Encaissement.id == v.c.encaissement_id)
        .where(
            Encaissement.organisation_id == tenant_id,
            v.c.canal == canal,
            v.c.devise == devise,
        )
    )
    if compte_bancaire_id:
        enc_query = enc_query.where(v.c.compte_bancaire_id == compte_bancaire_id)
    if start_dt:
        enc_query = enc_query.where(v.c.date_flux >= start_dt)
    if end_dt:
        enc_query = enc_query.where(v.c.date_flux <= end_dt)
    enc_rows = (await db.execute(enc_query)).all()
    for row in enc_rows:
        libelle = row.libelle
        # Un paiement en une fois garde son libellé nu ; un versement partiel
        # dit ce qu'il est et de quelle note, pour qu'on le reconnaisse seul.
        if int(row.nombre or 1) > 1 or int(row.rang or 1) > 1 or (
            Decimal(row.cumul or 0) < Decimal(row.montant_total or 0) - Decimal("0.01")
        ):
            nature = nature_versement(int(row.rang or 1), Decimal(row.montant_total or 0), Decimal(row.cumul or 0))
            suffixe = f"{nature} {int(row.rang or 1)}/{int(row.nombre or 1)}"
            if row.numero_recu:
                suffixe += f" · note {row.numero_recu}"
            libelle = f"{libelle or ''} — {suffixe}".strip(" —")
        mouvements.append(
            {
                "date": row.date_flux,
                "libelle": libelle,
                "reference": row.reference,
                "compte_label": compte_label,
                "entree": Decimal(row.montant or 0),
                "sortie": Decimal("0"),
                "type_operation": "ENCAISSEMENT",
                "transaction_id": str(row.id) if row.id else None,
                "transaction_type": "ENCAISSEMENT",
                "is_reconciled": bool(row.is_reconciled),
                "reconciled_at": row.reconciled_at,
                "bank_statement_ref": row.bank_statement_ref,
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

    # Retours en trésorerie : une ENTRÉE à la date du retour. La sortie
    # d'origine reste à sa date, intacte ; le libellé rappelle laquelle.
    retour_query = _retours_du_compte(
        select(
            RetourCaisse.id,
            RetourCaisse.date_retour,
            RetourCaisse.motif,
            RetourCaisse.reference_numero,
            RetourCaisse.montant,
            SortieFonds.reference_numero.label("sortie_reference"),
            func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at).label("sortie_date"),
        ).join(SortieFonds, SortieFonds.id == RetourCaisse.sortie_fonds_id)
    )
    if start_dt:
        retour_query = retour_query.where(RetourCaisse.date_retour >= start_dt)
    if end_dt:
        retour_query = retour_query.where(RetourCaisse.date_retour <= end_dt)
    for row in (await db.execute(retour_query)).all():
        origine = row.sortie_reference or "sortie"
        if row.sortie_date:
            origine += f" du {row.sortie_date.strftime('%d/%m/%Y')}"
        mouvements.append(
            {
                "date": row.date_retour,
                "libelle": f"Retour en trésorerie — {row.motif or 'reliquat rendu'} (sur {origine})",
                "reference": row.reference_numero,
                "compte_label": compte_label,
                "entree": Decimal(row.montant or 0),
                "sortie": Decimal("0"),
                "type_operation": "RETOUR",
                "transaction_id": str(row.id),
                "transaction_type": "RETOUR",
                "is_reconciled": None,
                "reconciled_at": None,
                "bank_statement_ref": None,
            }
        )

    # Approvisionnements (banque -> caisse) : ENTRÉES du journal CAISSE.
    if canal == "CAISSE":
        appro_query = select(
            SortieFonds.id,
            _sortie_ts,
            SortieFonds.motif,
            SortieFonds.reference_numero,
            SortieFonds.montant_paye,
        ).where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "approvisionnement_caisse",
            SortieFonds.devise == devise,
            SortieFonds.organisation_id == tenant_id,
        )
        if start_dt:
            appro_query = appro_query.where(_sortie_ts >= start_dt)
        if end_dt:
            appro_query = appro_query.where(_sortie_ts <= end_dt)
        for appro_id, dt, motif, ref_num, montant in (await db.execute(appro_query)).all():
            mouvements.append(
                {
                    "date": dt,
                    "libelle": motif or "Approvisionnement caisse",
                    "reference": ref_num,
                    "compte_label": compte_label,
                    "entree": Decimal(montant or 0),
                    "sortie": Decimal("0"),
                    "type_operation": "APPROVISIONNEMENT",
                    "transaction_id": str(appro_id) if appro_id else None,
                    "transaction_type": "SORTIE",
                    "is_reconciled": None,
                    "reconciled_at": None,
                    "bank_statement_ref": None,
                }
            )

    # Versements (caisse -> banque) : ENTRÉES du journal du compte BANQUE crédité.
    if canal == "BANQUE" and compte_bancaire_id:
        vers_query = select(
            SortieFonds.id,
            _sortie_ts,
            SortieFonds.motif,
            SortieFonds.reference_numero,
            SortieFonds.montant_paye,
        ).where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "versement_banque",
            SortieFonds.compte_bancaire_id == compte_bancaire_id,
            SortieFonds.devise == devise,
            SortieFonds.organisation_id == tenant_id,
        )
        if start_dt:
            vers_query = vers_query.where(_sortie_ts >= start_dt)
        if end_dt:
            vers_query = vers_query.where(_sortie_ts <= end_dt)
        for vers_id, dt, motif, ref_num, montant in (await db.execute(vers_query)).all():
            mouvements.append(
                {
                    "date": dt,
                    "libelle": motif or "Versement à la banque",
                    "reference": ref_num,
                    "compte_label": compte_label,
                    "entree": Decimal(montant or 0),
                    "sortie": Decimal("0"),
                    "type_operation": "VERSEMENT",
                    "transaction_id": str(vers_id) if vers_id else None,
                    "transaction_type": "SORTIE",
                    "is_reconciled": None,
                    "reconciled_at": None,
                    "bank_statement_ref": None,
                }
            )

    # Transferts internes (module dédié) : listés pour les deux canaux. Pour la
    # caisse, l'identifiant de compte est NULL (caisse unique) ; pour la banque,
    # on filtre sur le compte concerné.
    #
    # Aucun filtre de statut : un transfert contre-passé garde sa ligne au
    # journal, et la contre-passation apparaît comme un mouvement distinct daté
    # du jour où elle a été décidée. C'est la trace historique attendue.
    transfert_query = select(
        TransfertInterne.date_transfert,
        TransfertInterne.reference,
        TransfertInterne.source_type,
        TransfertInterne.source_id,
        TransfertInterne.destination_type,
        TransfertInterne.destination_id,
        TransfertInterne.montant,
    ).where(
        TransfertInterne.organisation_id == tenant_id,
        TransfertInterne.devise == devise,
        (
            (TransfertInterne.source_type == canal)
            | (TransfertInterne.destination_type == canal)
        ),
    )
    if canal == "BANQUE":
        transfert_query = transfert_query.where(
            (TransfertInterne.source_id == compte_bancaire_id)
            | (TransfertInterne.destination_id == compte_bancaire_id)
        )
    if True:
        if start_dt:
            transfert_query = transfert_query.where(TransfertInterne.date_transfert >= start_dt)
        if end_dt:
            transfert_query = transfert_query.where(TransfertInterne.date_transfert <= end_dt)
        transfer_rows = (await db.execute(transfert_query)).all()
        for dt, reference, src_type, src_id, dst_type, dst_id, montant in transfer_rows:
            if canal == "BANQUE":
                is_source = src_type == canal and src_id == compte_bancaire_id
                is_dest = dst_type == canal and dst_id == compte_bancaire_id
            else:
                is_source = src_type == canal
                is_dest = dst_type == canal
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
