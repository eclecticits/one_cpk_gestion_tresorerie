from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.schemas.base import DecimalBaseModel
from app.schemas.sortie_fonds import SortieFondsOut


class PeriodInfo(DecimalBaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class ReportDailyStats(DecimalBaseModel):
    date: date
    encaissements: Decimal = Decimal("0")
    sorties: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")


class ReportTotals(DecimalBaseModel):
    encaissements_total: Decimal = Decimal("0")
    sorties_total: Decimal = Decimal("0")
    solde_initial: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")
    solde_final: Decimal = Decimal("0")


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
    libelle: str | None = None
    reference: str | None = None
    entree: Decimal = Decimal("0")
    sortie: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")
    type_operation: str | None = None
    transaction_id: str | None = None
    transaction_type: str | None = None
    is_reconciled: bool | None = None
    reconciled_at: datetime | None = None
    bank_statement_ref: str | None = None


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
