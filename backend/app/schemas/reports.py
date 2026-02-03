from __future__ import annotations

from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field


class PeriodInfo(BaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class ReportDailyStats(BaseModel):
    date: date
    encaissements: Decimal = Decimal("0")
    sorties: Decimal = Decimal("0")
    solde_journalier: Decimal = Decimal("0")


class ReportTotals(BaseModel):
    encaissements_total: Decimal = Decimal("0")
    sorties_total: Decimal = Decimal("0")
    solde_initial: Decimal = Decimal("0")
    flux_periode: Decimal = Decimal("0")
    solde_final: Decimal = Decimal("0")


class ReportBreakdownCountTotal(BaseModel):
    key: str
    count: int = 0
    total: Decimal = Decimal("0")


class ReportBreakdownCount(BaseModel):
    key: str
    count: int = 0


class ReportModePaiementBreakdown(BaseModel):
    encaissements: list[ReportBreakdownCountTotal] = Field(default_factory=list)
    sorties: list[ReportBreakdownCountTotal] = Field(default_factory=list)


class ReportRequisitionsSummary(BaseModel):
    total: int = 0
    en_attente: int = 0
    approuvees: int = 0
    rejetees: int = 0
    annulees: int = 0


class ReportBreakdowns(BaseModel):
    par_statut_paiement: list[ReportBreakdownCountTotal] = Field(default_factory=list)
    par_mode_paiement: ReportModePaiementBreakdown = Field(default_factory=ReportModePaiementBreakdown)
    par_type_operation: list[ReportBreakdownCountTotal] = Field(default_factory=list)
    par_statut_requisition: list[ReportBreakdownCount] = Field(default_factory=list)
    requisitions: ReportRequisitionsSummary = Field(default_factory=ReportRequisitionsSummary)


class ReportAvailability(BaseModel):
    encaissements: bool = True
    sorties: bool = True
    requisitions: bool = True


class ReportSummaryStats(BaseModel):
    totals: ReportTotals = Field(default_factory=ReportTotals)
    breakdowns: ReportBreakdowns = Field(default_factory=ReportBreakdowns)
    availability: ReportAvailability = Field(default_factory=ReportAvailability)


class ReportSummaryResponse(BaseModel):
    stats: ReportSummaryStats
    daily_stats: list[ReportDailyStats]
    period: PeriodInfo | None = None
