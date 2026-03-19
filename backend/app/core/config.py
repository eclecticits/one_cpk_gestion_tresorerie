from __future__ import annotations

import logging
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger("onec_cpk_config")


def _find_env_file() -> str | None:
    # Look for .env in current working directory or any parent of this file.
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return str(cwd_env)
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


_ENV_FILE_PATH = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE_PATH, extra="ignore")

    # App
    env: str = "dev"
    log_level: str = "INFO"

    # DB
    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    # Uploads
    upload_dir: str = ""

    # JWT
    jwt_secret: str
    jwt_issuer: str = "onec-cpk-api"
    jwt_audience: str = "onec-cpk-frontend"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 7

    # One-time bootstrap (create first admin). Keep this secret server-side.
    bootstrap_admin_password: str | None = None

    # Default password for newly created users or password resets (server-side only).
    default_user_password: str | None = None

    # Legacy migration: allow login for users without a hashed password.
    migration_default_password: str | None = None

    # Debug endpoints (must be off in prod).
    enable_debug_endpoints: bool = False

    # Cookies
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool | None = None
    refresh_cookie_samesite: str = "lax"  # lax/strict/none
    refresh_cookie_domain: str | None = None

    # CORS
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    cors_origin_regex: str = Field(default="", alias="CORS_ORIGIN_REGEX")

    # Weekly report email scheduler
    weekly_report_enabled: bool = False
    weekly_report_to: str | None = None
    weekly_report_cc: str | None = None
    weekly_report_day_of_week: str = "mon"
    weekly_report_hour: int = 8
    weekly_report_minute: int = 0
    weekly_report_timezone: str = "UTC"

    monthly_report_enabled: bool = False
    monthly_report_to: str | None = None
    monthly_report_cc: str | None = None
    monthly_report_day_of_month: int = 1
    monthly_report_hour: int = 8
    monthly_report_minute: int = 0
    monthly_report_timezone: str = "UTC"

    # Billing guard (auto suspend)
    billing_guard_enabled: bool = False
    billing_guard_hour: int = 2
    billing_guard_minute: int = 0
    billing_guard_timezone: str = "UTC"

    # Discounts for upfront payments (fractions, e.g. 0.1 = 10%)
    billing_discount_3m: float = 0.05
    billing_discount_6m: float = 0.1
    billing_discount_12m: float = 0.15

    # SMTP (optional fallback if system settings are empty)
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None

    # Online payments (aggregator)
    online_payments_compte_bancaire_id: int | None = None
    epaielink_api_key: str | None = None
    epaielink_webhook_secret: str | None = None
    epaielink_base_url: str | None = None
    epaielink_site_id: str | None = None
    epaielink_return_url: str | None = None
    epaielink_notify_url: str | None = None

    # FedaPay (SaaS onboarding)
    fedapay_api_key: str | None = None
    fedapay_base_url: str | None = None
    fedapay_webhook_secret: str | None = None
    fedapay_webhook_tolerance: int = 300
    fedapay_return_url: str | None = None
    fedapay_currency: str = "XOF"

    # Public domain for tenant URLs (ex: mondomaine.com)
    tenant_base_domain: str | None = None

    def parsed_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def refresh_cookie_secure_effective(self) -> bool:
        if self.refresh_cookie_secure is None:
            return self.env.lower() != "dev"
        return self.refresh_cookie_secure


settings = Settings()  # singleton

if getattr(settings, "env", "dev").lower() == "dev":
    if _ENV_FILE_PATH:
        logger.info("Loaded .env from %s", _ENV_FILE_PATH)
    else:
        logger.info("No .env found; relying on environment variables only")
