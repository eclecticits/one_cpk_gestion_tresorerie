from __future__ import annotations

from decimal import Decimal
from typing import Any

from typing import Literal

from pydantic import BaseModel, Field


class OrganisationSettingsPublicOut(BaseModel):
    organisation_id: int
    max_users: int
    storage_quota_mb: int
    is_ai_enabled: bool
    is_mobile_money_enabled: bool
    is_audit_logs_enabled: bool
    fiscal_year_start: int
    currency_code: str
    theme_primary_color: str
    theme_sidebar_color: str
    theme_sidebar_text_color: str
    theme_sidebar_active_color: str
    theme_accent_color: str
    theme_text_color: str
    theme_button_text_color: str
    accounting_integration_mode: Literal["disabled", "manual", "automatic"] = "manual"
    #: Bornes d'une collation de réunion en sortie directe. Le prix par tête dit
    #: que c'en est bien une ; le total dit qu'elle reste une sortie directe.
    #: Lisibles par tous : l'écran de saisie les annonce avant le refus.
    collation_plafond_par_personne_usd: Decimal = Decimal("10")
    collation_plafond_total_usd: Decimal = Decimal("500")
    modules_config: dict[str, Any] | None = None
    workflow_config: dict[str, Any] | None = None


class OrganisationWorkflowUpdate(BaseModel):
    """Mise à jour du circuit de validation (réservée au super admin)."""

    workflow_config: dict[str, Any]


class OrganisationSettingsUpdate(BaseModel):
    currency_code: str | None = None
    theme_primary_color: str | None = None
    theme_sidebar_color: str | None = None
    theme_sidebar_text_color: str | None = None
    theme_sidebar_active_color: str | None = None
    theme_accent_color: str | None = None
    theme_text_color: str | None = None
    theme_button_text_color: str | None = None
    accounting_integration_mode: Literal["disabled", "manual", "automatic"] | None = None
    accounting_integration_change_motif: str | None = Field(default=None, max_length=500)
    collation_plafond_par_personne_usd: Decimal | None = Field(default=None, gt=0)
    collation_plafond_total_usd: Decimal | None = Field(default=None, gt=0)
