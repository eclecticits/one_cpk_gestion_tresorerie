from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, EmailStr, Field


class SuperAdminOrganisationCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100)
    plan_type: str | None = None
    status_abonnement: str | None = None
    trial_days: int | None = Field(default=30, ge=0, le=365)
    limite_utilisateurs: int | None = Field(default=None, ge=1, le=10000)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)


class SuperAdminOrganisationReservation(BaseModel):
    nom: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100)
    admin_email: EmailStr
    admin_phone: str | None = None
    plan_id: int
    max_users: int = Field(default=5, ge=1, le=10000)
    storage_quota_mb: int = Field(default=1024, ge=128, le=1024 * 10000)
    is_ai_enabled: bool = False
    is_mobile_money_enabled: bool = True
    is_audit_logs_enabled: bool = True
    fiscal_year_start: int = Field(default=1, ge=1, le=12)
    currency_code: str = Field(default="CDF", min_length=3, max_length=10)


class SuperAdminOrganisationUpdate(BaseModel):
    plan_type: str | None = None
    status_abonnement: str | None = None
    date_expiration_abonnement: datetime | None = None
    limite_utilisateurs: int | None = Field(default=None, ge=1, le=10000)
    is_active: bool | None = None


class SuperAdminOrganisationOut(BaseModel):
    id: int
    uuid: str
    nom: str
    slug: str
    plan_type: str
    status_abonnement: str
    date_expiration_abonnement: datetime | None = None
    limite_utilisateurs: int
    is_active: bool
    user_count: int
    created_at: datetime


class OrganisationSettingsOut(BaseModel):
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
    modules_config: dict[str, Any] | None = None


class OrganisationSettingsUpdate(BaseModel):
    # 0 => illimité
    max_users: int | None = Field(default=None, ge=0, le=10000)
    # 0 => illimité
    storage_quota_mb: int | None = Field(default=None, ge=0, le=1024 * 10000)
    is_ai_enabled: bool | None = None
    is_mobile_money_enabled: bool | None = None
    is_audit_logs_enabled: bool | None = None
    fiscal_year_start: int | None = Field(default=None, ge=1, le=12)
    currency_code: str | None = Field(default=None, min_length=3, max_length=10)
    theme_primary_color: str | None = None
    theme_sidebar_color: str | None = None
    theme_sidebar_text_color: str | None = None
    theme_sidebar_active_color: str | None = None
    theme_accent_color: str | None = None
    theme_text_color: str | None = None
    theme_button_text_color: str | None = None
    modules_config: dict[str, Any] | None = None


class SimulatePaymentRequest(BaseModel):
    admin_email: EmailStr | None = None
    billing_months: int = Field(default=1, ge=1, le=12)


class GrantTrialRequest(BaseModel):
    plan_type: str = Field(default="FREE")
    duration_days: int = Field(default=30, ge=1, le=365)


class GoogleOAuthSettingsOut(BaseModel):
    google_client_id: str | None
    google_oauth_redirect_uri: str | None
    google_oauth_redirect_uri_enabled: bool
    google_oauth_redirect_uri_local: str | None
    google_oauth_redirect_uri_local_enabled: bool
    google_client_secret_configured: bool
    source: str  # "database" | "environment" | "none"


class GoogleOAuthSettingsUpdate(BaseModel):
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None
    google_oauth_redirect_uri_enabled: bool | None = None
    google_oauth_redirect_uri_local: str | None = None
    google_oauth_redirect_uri_local_enabled: bool | None = None
