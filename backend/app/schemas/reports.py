from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.base import DecimalBaseModel


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
    solde: Decimal = Decimal("0")


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
    par_type_operation: list[ReportBreakdownCountTotal] = []
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
