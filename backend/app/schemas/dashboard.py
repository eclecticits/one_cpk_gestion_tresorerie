from __future__ import annotations

from datetime import date
from pydantic import BaseModel


class PeriodInfo(BaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class DashboardStats(BaseModel):
    total_encaissements_period: float = 0
    total_encaissements_jour: float = 0
    total_sorties_period: float = 0
    total_sorties_jour: float = 0
    solde_period: float = 0
    solde_actuel: float = 0
    solde_jour: float = 0
    requisitions_en_attente: int = 0
    note: str | None = None


class DashboardDailyStats(BaseModel):
    date: date
    encaissements: float = 0
    sorties: float = 0
    solde: float = 0


class DashboardStatsResponse(BaseModel):
    stats: DashboardStats
    daily_stats: list[DashboardDailyStats]
    period: PeriodInfo | None = None
