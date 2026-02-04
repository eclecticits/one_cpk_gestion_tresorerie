from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.base import DecimalBaseModel


class PeriodInfo(DecimalBaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class DashboardStats(DecimalBaseModel):
    total_encaissements_period: Decimal = Decimal("0")
    total_encaissements_jour: Decimal = Decimal("0")
    total_sorties_period: Decimal = Decimal("0")
    total_sorties_jour: Decimal = Decimal("0")
    solde_period: Decimal = Decimal("0")
    solde_actuel: Decimal = Decimal("0")
    solde_jour: Decimal = Decimal("0")
    requisitions_en_attente: int = 0
    note: str | None = None


class DashboardDailyStats(DecimalBaseModel):
    date: date
    encaissements: Decimal = Decimal("0")
    sorties: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")


class DashboardStatsResponse(DecimalBaseModel):
    stats: DashboardStats
    daily_stats: list[DashboardDailyStats]
    period: PeriodInfo | None = None
