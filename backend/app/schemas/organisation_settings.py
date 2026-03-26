from __future__ import annotations

from pydantic import BaseModel


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


class OrganisationSettingsUpdate(BaseModel):
    theme_primary_color: str | None = None
    theme_sidebar_color: str | None = None
    theme_sidebar_text_color: str | None = None
    theme_sidebar_active_color: str | None = None
    theme_accent_color: str | None = None
    theme_text_color: str | None = None
    theme_button_text_color: str | None = None
