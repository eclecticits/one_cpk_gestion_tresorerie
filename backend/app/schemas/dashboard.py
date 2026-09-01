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
    total_sorties_brutes_period: Decimal = Decimal("0")
    total_retours_period: Decimal = Decimal("0")
    total_sorties_nettes_period: Decimal = Decimal("0")
    total_sorties_period: Decimal = Decimal("0")
    total_sorties_brutes_jour: Decimal = Decimal("0")
    total_retours_jour: Decimal = Decimal("0")
    total_sorties_nettes_jour: Decimal = Decimal("0")
    total_sorties_jour: Decimal = Decimal("0")
    solde_period: Decimal = Decimal("0")
    solde_actuel: Decimal = Decimal("0")
    solde_jour: Decimal = Decimal("0")
    requisitions_en_attente: int = 0
    max_caisse_amount: Decimal = Decimal("0")
    caisse_overlimit: bool = False

    # --- Exécution budgétaire ---------------------------------------------
    # Les totaux ci-dessus sont ceux de la TRÉSORERIE : ils comptent tout ce qui
    # entre et sort, y compris l'argent d'un tiers ou une dépense dont
    # l'imputation n'est pas décidée. Ceux qui suivent ne comptent que ce qui
    # touche réellement le budget. Les deux vues diffèrent, et c'est normal :
    # confondre « il y a de l'argent en caisse » et « le budget le permet » est
    # exactement l'erreur que cette séparation existe pour empêcher.
    total_recettes_budgetaires_period: Decimal = Decimal("0")
    total_depenses_budgetaires_period: Decimal = Decimal("0")
    solde_budgetaire_period: Decimal = Decimal("0")

    # --- Hors budget ------------------------------------------------------
    total_recettes_hors_budget_period: Decimal = Decimal("0")
    total_depenses_hors_budget_period: Decimal = Decimal("0")
    #: Mouvements encore en attente d'une décision d'imputation, toutes périodes
    #: confondues : c'est un encours, pas un flux.
    hors_budget_a_regulariser_montant: Decimal = Decimal("0")
    hors_budget_a_regulariser_count: int = 0
    #: Argent détenu pour autrui et pas encore reversé. Présent en trésorerie,
    #: absent du budget, et dû.
    fonds_tiers_solde: Decimal = Decimal("0")
    fonds_tiers_count: int = 0

    @field_serializer(
        "total_encaissements_period",
        "total_encaissements_jour",
        "total_sorties_brutes_period",
        "total_retours_period",
        "total_sorties_nettes_period",
        "total_sorties_period",
        "total_sorties_brutes_jour",
        "total_retours_jour",
        "total_sorties_nettes_jour",
        "total_sorties_jour",
        "solde_period",
        "solde_actuel",
        "solde_jour",
        "max_caisse_amount",
        "total_recettes_budgetaires_period",
        "total_depenses_budgetaires_period",
        "solde_budgetaire_period",
        "total_recettes_hors_budget_period",
        "total_depenses_hors_budget_period",
        "hors_budget_a_regulariser_montant",
        "fonds_tiers_solde",
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
