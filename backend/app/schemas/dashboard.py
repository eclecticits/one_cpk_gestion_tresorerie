from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import field_serializer

from app.schemas.base import DecimalBaseModel


def _format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


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
    max_caisse_amount: Decimal = Decimal("0")
    caisse_overlimit: bool = False

    @field_serializer(
        "total_encaissements_period",
        "total_encaissements_jour",
        "total_sorties_period",
        "total_sorties_jour",
        "solde_period",
        "solde_actuel",
        "solde_jour",
        "max_caisse_amount",
        mode="plain",
    )
    def _serialize_money(self, value: Decimal) -> str:
        return _format_money(value)


class DashboardDailyStats(DecimalBaseModel):
    date: date
    encaissements: Decimal = Decimal("0")
    sorties: Decimal = Decimal("0")
    solde: Decimal = Decimal("0")

    @field_serializer("encaissements", "sorties", "solde", mode="plain")
    def _serialize_daily_money(self, value: Decimal) -> str:
        return _format_money(value)


class DashboardStatsResponse(DecimalBaseModel):
    stats: DashboardStats
    daily_stats: list[DashboardDailyStats]
    period: PeriodInfo | None = None
