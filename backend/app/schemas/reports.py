from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.schemas.base import DecimalBaseModel
from app.schemas.sortie_fonds import SortieFondsOut


class PeriodInfo(DecimalBaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class ReportDailyStats(DecimalBaseModel):
    date: date
    encaissements: Decimal = Decimal("0")
    # Contrat historique : `sorties` reste le montant brut sorti du périmètre,
    # transferts internes sortants compris.
    sorties: Decimal = Decimal("0")
    retours: Decimal = Decimal("0")
    sorties_nettes: Decimal = Decimal("0")
    transferts_internes: Decimal = Decimal("0")
    entrees_internes: Decimal = Decimal("0")
    # Flux net du jour : encaissements + entrées internes + retours - sorties.
    # Le nom `solde` est conservé pour la rétrocompatibilité de l'API.
    solde: Decimal = Decimal("0")


class ReportDeviseTotals(DecimalBaseModel):
    """Totaux d'une seule devise, sans aucune conversion.

    Les champs plats de `ReportTotals` additionnent des montants de devises
    différentes (une sortie est stockée dans SA devise) : leur somme n'a de sens
    que pour une organisation mono-devise. Ce bloc est la vue exacte.

    Nuance sur les encaissements : `montant_paye` est toujours le pivot USD et
    `montant_percu` le montant réellement perçu. Ici, la ligne USD somme des
    `montant_paye` d'encaissements perçus en USD, et la ligne CDF des
    `montant_percu` — même convention que la trésorerie et la clôture de caisse,
    donc `encaissements_total` (pivot USD, toutes devises) n'est PAS la somme
    des lignes ci-dessous.
    """

    devise: str
    encaissements_total: Decimal = Decimal("0")
    sorties_total: Decimal = Decimal("0")
    depenses_reelles: Decimal = Decimal("0")
    transferts_internes: Decimal = Decimal("0")
    entrees_internes: Decimal = Decimal("0")
    encaissements_hors_budget: Decimal = Decimal("0")
    retours_total: Decimal = Decimal("0")
    sorties_nettes: Decimal = Decimal("0")
    flux_periode: Decimal = Decimal("0")
    solde_initial: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")


class ReportTotals(DecimalBaseModel):
    encaissements_total: Decimal = Decimal("0")
    # Contrat historique : montant BRUT sorti du périmètre. Ne pas changer sa
    # sémantique ; les champs additifs ci-dessous portent le net des retours.
    sorties_total: Decimal = Decimal("0")
    # Détail des sorties : dépenses réelles vs transferts internes caisse<->banque.
    depenses_reelles: Decimal = Decimal("0")
    transferts_internes: Decimal = Decimal("0")
    # Contrepartie ENTRANTE des transferts internes : versements reçus par la
    # banque, approvisionnements reçus par la caisse — les deux en vue consolidée,
    # où ils compensent exactement `transferts_internes`. Ce n'est PAS une recette :
    # à afficher à part de `encaissements_total`.
    entrees_internes: Decimal = Decimal("0")
    # Encaissements sans impact budgétaire (fonds de tiers, hors-budget à
    # régulariser) : entrés en trésorerie, donc dans le solde, mais PAS des
    # recettes — d'où leur absence de `encaissements_total`.
    encaissements_hors_budget: Decimal = Decimal("0")
    # Retours validés vers le même canal / la même devise que le rapport.
    retours_total: Decimal = Decimal("0")
    sorties_nettes: Decimal = Decimal("0")
    # encaissements (recettes + hors budget) + entrées internes + retours
    # - sorties brutes.
    flux_periode: Decimal = Decimal("0")
    solde_initial: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")
    solde_final: Decimal = Decimal("0")
    # Même période, même canal, mais sans mélange de devises. Vide si le détail
    # n'a pas pu être calculé (les champs plats restent alors seuls disponibles).
    par_devise: list[ReportDeviseTotals] = []


class ReportBreakdownCountTotal(DecimalBaseModel):
    key: str
    count: int = 0
    total: Decimal = Decimal("0")


class ReportBreakdownCount(DecimalBaseModel):
    key: str
    count: int = 0


class ReportModePaiementBreakdown(DecimalBaseModel):
    encaissements: list[ReportBreakdownCountTotal] = []
    sorties: list[ReportBreakdownCountTotal] = []


class ReportRequisitionsSummary(DecimalBaseModel):
    total: int = 0
    en_attente: int = 0
    approuvees: int = 0


class ReportBreakdowns(DecimalBaseModel):
    par_statut_paiement: list[ReportBreakdownCountTotal] = []
    par_mode_paiement: ReportModePaiementBreakdown = ReportModePaiementBreakdown()
    par_poste_budgetaire: list[ReportBreakdownCountTotal] = []
    par_statut_requisition: list[ReportBreakdownCount] = []
    requisitions: ReportRequisitionsSummary = ReportRequisitionsSummary()


class ReportAvailability(DecimalBaseModel):
    encaissements: bool = True
    sorties: bool = True
    requisitions: bool = True


class ReportSummaryStats(DecimalBaseModel):
    totals: ReportTotals = ReportTotals()
    breakdowns: ReportBreakdowns = ReportBreakdowns()
    availability: ReportAvailability = ReportAvailability()


class ReportSummaryResponse(DecimalBaseModel):
    stats: ReportSummaryStats
    daily_stats: list[ReportDailyStats]
    period: PeriodInfo | None = None


class ReportClotureResponse(DecimalBaseModel):
    date: date
    total: Decimal = Decimal("0")
    nombre_transactions: int = 0
    details: list[SortieFondsOut] = []


class ReportJournalLine(DecimalBaseModel):
    date: datetime
    # Libellé complet, précisions comprises entre parenthèses : c'est lui que
    # reprennent le PDF et les exports. `libelle_base` et `precision` en sont
    # les deux morceaux, pour un affichage qui les distingue.
    libelle: str | None = None
    libelle_base: str | None = None
    precision: str | None = None
    # Qui a payé (entrée) ou qui a reçu (sortie) : le nom seul, pour la recherche.
    tiers: str | None = None
    reference: str | None = None
    compte_label: str | None = None
    entree: Decimal = Decimal("0")
    sortie: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")
    type_operation: str | None = None
    transaction_id: UUID | None = None
    transaction_type: str | None = None
    is_reconciled: bool | None = None
    reconciled_at: datetime | None = None
    bank_statement_ref: str | None = None


class ReportVersementLine(DecimalBaseModel):
    """Un versement encaissé, daté du jour où l'argent est entré.

    Les champs d'en-tête de la note (`numero_recu`, `client_nom`, …) gardent
    leur nom d'origine pour que les écrans et exports qui lisaient la liste des
    notes lisent celle-ci sans traduction. `montant_paye`/`montant_percu` y
    valent le montant DU VERSEMENT, pas le cumul de la note.
    """

    id: str
    encaissement_id: UUID
    versement_id: UUID | None = None
    date_versement: datetime
    date_encaissement: datetime | None = None
    numero_recu: str | None = None
    type_client: str | None = None
    client_nom: str | None = None
    expert_comptable: dict | None = None
    libelle: str | None = None
    description: str | None = None
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    canal: str | None = None
    compte_bancaire_id: int | None = None
    devise_perception: str = "USD"
    mode_paiement: str | None = None
    reference: str | None = None
    montant_paye: Decimal = Decimal("0")
    montant_percu: Decimal = Decimal("0")
    montant_total: Decimal = Decimal("0")
    cumul_paye: Decimal = Decimal("0")
    reste_apres: Decimal = Decimal("0")
    rang: int = 1
    nombre_versements: int = 1
    nature_versement: str = "Paiement intégral"
    statut_paiement: str | None = None
    # « Budgétaire », « Hors budget », « Fonds de tiers »… : libellé de la
    # colonne « Nature budgétaire » de l'export des encaissements.
    nature_budgetaire: str = "Budgétaire"
    # Compte dans « Encaissements » du résumé ; sinon dans « hors budget ».
    est_recette: bool = True


class ReportRetourLine(DecimalBaseModel):
    """Un retour en trésorerie, daté du jour où l'argent est revenu.

    La sortie d'origine n'est pas modifiée : elle reste à sa date avec son
    montant décaissé. Le retour est une ligne à part, à SA date, qui rappelle
    la sortie qu'il corrige et ce qu'il en reste à justifier après lui.
    """

    id: UUID
    date_retour: datetime
    reference_numero: str | None = None
    type_retour: str
    motif: str | None = None
    montant: Decimal
    devise: str = "USD"
    canal: str = "CAISSE"
    compte_bancaire_id: int | None = None
    mode: str | None = None
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    sortie_fonds_id: UUID
    sortie_reference: str | None = None
    sortie_date: datetime | None = None
    sortie_beneficiaire: str | None = None
    sortie_motif: str | None = None
    sortie_montant: Decimal = Decimal("0")
    numero_requisition: str | None = None
    total_retourne_apres: Decimal = Decimal("0")
    reste_a_justifier_apres: Decimal = Decimal("0")


class ReportJournalResponse(DecimalBaseModel):
    canal: str
    devise: str
    compte_bancaire_id: int | None = None
    compte_bancaire_label: str | None = None
    solde_initial: Decimal = Decimal("0")
    total_entrees: Decimal = Decimal("0")
    total_sorties: Decimal = Decimal("0")
    solde_final: Decimal = Decimal("0")
    period: PeriodInfo | None = None
    lignes: list[ReportJournalLine] = []


class ReportAnnualMonth(DecimalBaseModel):
    mois: int
    total_entrees: Decimal = Decimal("0")
    total_sorties: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")


class ReportAnnualCanalSplit(DecimalBaseModel):
    caisse: Decimal = Decimal("0")
    banque: Decimal = Decimal("0")


class ReportAnnualSynthese(DecimalBaseModel):
    year: int
    devise: str
    canal: str
    months: list[ReportAnnualMonth] = []
    total_entrees: Decimal = Decimal("0")
    total_sorties: Decimal = Decimal("0")
    solde_net: Decimal = Decimal("0")
    coverage_rate: Decimal | None = None
    critical_month: int | None = None
    encaissements_par_canal: ReportAnnualCanalSplit = ReportAnnualCanalSplit()
    sorties_par_canal: ReportAnnualCanalSplit = ReportAnnualCanalSplit()


class ReportTopExpense(DecimalBaseModel):
    motif: str
    total: Decimal = Decimal("0")
