from __future__ import annotations

import logging
from pathlib import Path
from pydantic import Field
from pydantic import model_validator
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

    # Redis cache
    redis_url: str = "redis://localhost:6379/0"
    redis_default_ttl: int = 300  # seconds

    # Monitoring / Prometheus
    enable_metrics: bool = True
    # Si défini, GET /metrics exige « Authorization: Bearer <token> »
    metrics_token: str | None = None

    # Alertes Telegram (optionnel — laisser vide pour désactiver)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # ── Couche IA abstraite ──────────────────────────────────────────────────
    # Provider principal : "anthropic" | "ollama"
    ai_provider: str = "ollama"
    # Provider de secours (utilisé si AI_ENABLE_FALLBACK=true et primary échoue)
    ai_fallback_provider: str | None = None
    ai_enable_fallback: bool = False
    ai_max_context_chars: int = 12000
    ai_max_response_chars: int = 4000

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_timeout_seconds: int = 60
    anthropic_max_tokens: int = 4000
    anthropic_temperature: float = 0.2

    # Ollama (provider secondaire / local)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma2:2b"
    ollama_timeout_seconds: int = 60

    # DB
    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    # Uploads
    upload_dir: str = ""
    serve_uploads_publicly: bool = Field(default=True, alias="SERVE_UPLOADS_PUBLICLY")

    # JWT
    jwt_secret: str
    jwt_issuer: str = "onec-cpk-api"
    jwt_audience: str = "onec-cpk-frontend"
    # Défaut prudent (30 min) : un déploiement qui oublie de définir
    # ACCESS_TOKEN_EXPIRE_MINUTES ne se retrouve pas avec un token de 8 h.
    # Le refresh HttpOnly (7 j) assure la continuité de session.
    access_token_expire_minutes: int = 30
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

    # Google OAuth/Gmail read-only integration for Secretariat.
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_oauth_redirect_uri: str | None = Field(default=None, alias="GOOGLE_OAUTH_REDIRECT_URI")
    google_oauth_scopes: str = Field(
        default="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose",
        alias="GOOGLE_OAUTH_SCOPES",
    )
    privacy_policy_url: str | None = Field(default=None, alias="PRIVACY_POLICY_URL")
    terms_of_service_url: str | None = Field(default=None, alias="TERMS_OF_SERVICE_URL")
    account_deletion_url: str | None = Field(default=None, alias="ACCOUNT_DELETION_URL")

    # OpenAI (legacy env var — prefer DB-backed config via Super Admin)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # Google Gemini (legacy env var — prefer DB-backed config via Super Admin)
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-flash", alias="GEMINI_MODEL")

    # Chiffrement des clés API stockées en base de données.
    # Générer avec : GET /api/v1/ai-providers/encryption-key/generate
    ai_provider_encryption_key: str | None = Field(default=None, alias="AI_PROVIDER_ENCRYPTION_KEY")

    # FedaPay (SaaS onboarding)
    fedapay_api_key: str | None = None
    fedapay_base_url: str | None = None
    fedapay_webhook_secret: str | None = None
    fedapay_webhook_tolerance: int = 300
    fedapay_return_url: str | None = None

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        secret = (self.jwt_secret or "").strip()
        weak_values = {"oneckncd", "change_me", "changeme", "secret", "jwt_secret"}
        is_weak = len(secret) < 32 or secret.lower() in weak_values
        if is_weak:
            message = (
                "JWT_SECRET trop faible ou compromis. Générer une valeur aléatoire "
                "d'au moins 32 octets, par exemple avec backend/scripts/generate_jwt_secret.py."
            )
            if (self.env or "").lower() in {"prod", "production"}:
                raise ValueError(message)
            logger.warning(message)
        google_oauth_enabled = bool(self.google_client_id or self.google_client_secret)
        missing_legal_urls = [
            name
            for name, value in {
                "PRIVACY_POLICY_URL": self.privacy_policy_url,
                "TERMS_OF_SERVICE_URL": self.terms_of_service_url,
                "ACCOUNT_DELETION_URL": self.account_deletion_url,
            }.items()
            if not (value or "").strip()
        ]
        if google_oauth_enabled and missing_legal_urls:
            message = (
                "Google OAuth/Gmail configuré sans URLs légales obligatoires: "
                + ", ".join(missing_legal_urls)
                + ". Publication OAuth impossible sans politique de confidentialité, conditions et suppression de compte."
            )
            if (self.env or "").lower() in {"prod", "production"}:
                raise ValueError(message)
            logger.warning(message)
        if (self.env or "").lower() in {"prod", "production"} and self.enable_metrics and not (self.metrics_token or "").strip():
            raise ValueError("METRICS_TOKEN obligatoire en production quand ENABLE_METRICS=true.")
        return self
    fedapay_currency: str = "XOF"

    # Console SaaS (facturation centralisée)
    saas_console_base_url: str | None = None
    saas_internal_key: str | None = None
    saas_console_timeout: int = 20
    saas_billing_portal_url: str | None = None
    saas_status_path: str = "/tenants/{tenant_id}/status"
    saas_status_cache_ttl_seconds: int = 300
    saas_payments_path: str = "/payments/trigger"
    saas_billing_summary_path: str = "/tenants/{tenant_id}/billing-summary"
    saas_billing_config_path: str = "/tenants/{tenant_id}/billing-config"
    saas_checkout_session_path: str = "/payments/create-session"
    saas_checkout_success_url: str | None = None
    saas_checkout_cancel_url: str | None = None
    saas_checkout_base_url: str | None = None

    # Public domain for tenant URLs (ex: mondomaine.com)
    tenant_base_domain: str | None = None

    def parsed_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def refresh_cookie_secure_effective(self) -> bool:
        if self.refresh_cookie_secure is None:
            # dev et test tournent en HTTP : un cookie Secure ne serait jamais
            # renvoyé par le navigateur / client de test. Secure ailleurs (prod).
            return self.env.lower() not in ("dev", "test")
        return self.refresh_cookie_secure


settings = Settings()  # singleton

if getattr(settings, "env", "dev").lower() == "dev":
    if _ENV_FILE_PATH:
        logger.info("Loaded .env from %s", _ENV_FILE_PATH)
    else:
        logger.info("No .env found; relying on environment variables only")
