from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class PeriodInfo(BaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class ReportDailyStats(BaseModel):
    date: date
    encaissements: float = 0
    sorties: float = 0
    solde: float = 0


class ReportTotals(BaseModel):
    encaissements_total: float = 0
    sorties_total: float = 0
    solde: float = 0


class ReportBreakdownCountTotal(BaseModel):
    key: str
    count: int = 0
    total: float = 0


class ReportBreakdownCount(BaseModel):
    key: str
    count: int = 0


class ReportModePaiementBreakdown(BaseModel):
    encaissements: list[ReportBreakdownCountTotal] = []
    sorties: list[ReportBreakdownCountTotal] = []


class ReportRequisitionsSummary(BaseModel):
    total: int = 0
    en_attente: int = 0
    approuvees: int = 0


class ReportBreakdowns(BaseModel):
    par_statut_paiement: list[ReportBreakdownCountTotal] = []
    par_mode_paiement: ReportModePaiementBreakdown = ReportModePaiementBreakdown()
    par_type_operation: list[ReportBreakdownCountTotal] = []
    par_statut_requisition: list[ReportBreakdownCount] = []
    requisitions: ReportRequisitionsSummary = ReportRequisitionsSummary()


class ReportAvailability(BaseModel):
    encaissements: bool = True
    sorties: bool = True
    requisitions: bool = True


class ReportSummaryStats(BaseModel):
    totals: ReportTotals = ReportTotals()
    breakdowns: ReportBreakdowns = ReportBreakdowns()
    availability: ReportAvailability = ReportAvailability()


class ReportSummaryResponse(BaseModel):
    stats: ReportSummaryStats
    daily_stats: list[ReportDailyStats]
    period: PeriodInfo | None = None
