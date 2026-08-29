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
    # Nouvelles tentatives par fournisseur avant de passer au suivant. Un 429 ou
    # une surcharge passagère ne doit pas faire échouer la requête utilisateur,
    # surtout quand un seul fournisseur est configuré (cas le plus courant).
    ai_max_retries: int = 2
    ai_retry_base_delay_seconds: float = 0.5
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
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_pool_slow_checkout_seconds: float = 2.0
    db_slow_query_ms: float = 500.0
    # Doit refléter le -w passé à gunicorn (docker-compose.yml), sans quoi le
    # budget de connexions calculé dans log_pool_configuration() est faux.
    backend_workers: int = 4
    auth_context_cache_enabled: bool = True
    auth_context_cache_ttl_seconds: int = 30
    report_summary_cache_ttl_seconds: int = 15
    # Uploads
    upload_dir: str = ""
    # Défaut sûr : les uploads ne sont PAS servis publiquement (ils passent par
    # l'endpoint authentifié secure_uploads). Mettre SERVE_UPLOADS_PUBLICLY=true
    # explicitement en dev si besoin.
    serve_uploads_publicly: bool = Field(default=False, alias="SERVE_UPLOADS_PUBLICLY")

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

    # Rate limiting : nombre de reverse-proxies de confiance en amont
    # (Nginx = 1 ; Nginx derrière CloudFront/ALB = 2). Sert à extraire l'IP
    # réelle du client depuis X-Forwarded-For sans faire confiance à la valeur
    # forgée par le client (on lit la Nᵉ entrée en partant de la droite).
    trusted_proxy_hops: int = Field(default=1, alias="TRUSTED_PROXY_HOPS")

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

    # ── Exports Excel ────────────────────────────────────────────────────────
    # Plafond de lignes d'un export direct (synchrone). Voir le commentaire de
    # _compter_lignes() dans app/api/v1/endpoints/exports.py : au-dela, l'export
    # est refuse immediatement plutot que de tenir un worker jusqu'a ce que
    # l'arbitre gunicorn le tue. 0 desactive le plafond.
    export_max_rows: int = 60_000

    # Fraîcheur des métriques d'export publiées sur /metrics. Prometheus scrape
    # typiquement toutes les 15 s, et les quatre workers gunicorn peuvent être
    # scrapés de front : sans ce cache, chaque scrape déclencherait trois
    # agrégats par worker sur `export_jobs`.
    metrics_export_refresh_seconds: int = 15

    # ── Documents produits ───────────────────────────────────────────────────
    # Fuseau de l'horodatage « Généré le … » porté par les classeurs exportés.
    #
    # VIDE = on reprend WEEKLY_REPORT_TIMEZONE, déjà réglé sur le fuseau local du
    # déploiement (Africa/Kinshasa en production). Ce repli est délibéré : un
    # défaut à "UTC" aurait horodaté chaque document d'une heure d'écart avec
    # l'horloge de celui qui le lit, sans que rien ne le signale. Aucune
    # configuration nouvelle n'est donc nécessaire pour que la date soit juste.
    document_timezone: str = ""

    # ── Ordonnanceurs : qui les porte ────────────────────────────────────────
    # false = le backend HTTP (comportement historique, inchangé).
    # true  = le conteneur exports-worker.
    #
    # Pourquoi ce déplacement : un rapport hebdomadaire s'exécute aujourd'hui
    # DANS un worker gunicorn qui sert des requêtes — le même défaut de nature
    # que les exports, pour la même raison (du CPU Python qui tient le GIL).
    # Le déplacer supprime aussi le besoin de dédupliquer l'exécution entre les
    # quatre workers.
    #
    # ⚠️ LE CODE ET LE DÉPLOIEMENT DEVIENNENT SOLIDAIRES. Passer à true sans
    # déployer le conteneur worker arrête purement et simplement les rapports et
    # la garde de facturation. C'est pourquoi le défaut est false : le
    # changement doit être une décision, jamais un effet de bord de mise à jour.
    schedulers_in_worker: bool = False

    # ── Exports asynchrones (phase 1) ────────────────────────────────────────
    # Types d'export routés vers la file, séparés par des virgules
    # ("budget,requisitions"). VIDE PAR DÉFAUT : le drapeau est fermé, rien ne
    # change tant qu'on ne l'ouvre pas explicitement. C'est ce qui rend la
    # bascule réversible type par type.
    export_async_types: str = ""
    # Seuil de bascule, en lignes. Sous ce nombre, le chemin direct est conservé
    # même pour un type ouvert : un export de 500 lignes doit rester instantané,
    # l'asynchrone y serait une régression d'usage (attente, interrogation,
    # second téléchargement) pour un fichier produit en une seconde.
    #
    # 5 000 par défaut : nettement au-dessus de la zone « instantanée », et bien
    # en dessous d'EXPORT_MAX_ROWS (60 000) qui reste le refus absolu. L'ordre
    # des deux valeurs est ce qui garantit qu'un export accepté en 202 ne sera
    # pas refusé plus tard par le worker pour dépassement de plafond.
    #
    # 0 = tout ce qui est ouvert bascule, quelle que soit la taille. C'est le
    # réglage qui permet de valider la chaîne complète sur un petit export.
    export_async_row_threshold: int = 5_000
    # Durée de vie de l'ARTEFACT, pas du job : la ligne reste en base pour
    # l'historique, le fichier est supprimé. Ces classeurs portent des données
    # financières nominatives.
    export_job_retention_days: int = 7
    # Bail d'exécution. Renouvelé pendant le traitement ; passé ce délai sans
    # renouvellement, le balayage considère le worker mort et remet le job en
    # file. Doit rester nettement au-dessus de l'intervalle de renouvellement.
    export_job_lease_seconds: int = 300
    # Nombre total de tentatives avant échec définitif. 2 = une reprise après la
    # mort d'un worker, pas une boucle sur une erreur applicative.
    export_job_max_attempts: int = 2
    # Fenêtre de déduplication : un artefact identique et plus récent que cela
    # est rendu tel quel au lieu d'être régénéré.
    #
    # 30 et non 10 : la fenêtre est mesurée depuis `created_at`, et le client
    # abandonne au bout de 10 minutes (DELAI_TOTAL_MS dans download.ts). À
    # valeurs égales, un job long sortait de la fenêtre à l'instant précis où
    # l'utilisateur renonçait — relancer régénérait au lieu de réutiliser
    # l'artefact qui venait d'être produit, c'est-à-dire exactement quand la
    # déduplication avait le plus de valeur. La fenêtre doit rester supérieure
    # au délai client, avec de la marge.
    export_dedup_window_minutes: int = 30
    # Profondeur de file par organisation. Au-delà, refus explicite à la
    # soumission — une attente muette est pire qu'un refus.
    export_max_queued_per_org: int = 5
    # Jobs traités en parallèle par le worker. 1, et ce n'est pas un défaut
    # timide : un seul export a été mesuré à +310 Mo de RSS, sur une VM de
    # 3,7 Go partagée avec PostgreSQL et le backend. Monter à 2 suppose de
    # mesurer d'abord.
    export_worker_concurrency: int = 1
    # Plafond d'exécution d'un job côté worker. Doit rester NETTEMENT au-dessus
    # du plus long export attendu (112 s mesurées pour un exercice complet) : ce
    # n'est pas un budget de performance, c'est un garde-fou contre une tâche
    # bloquée qui immobiliserait le worker indéfiniment.
    export_job_timeout_seconds: int = 1800

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
    # Exiger TLS (STARTTLS ou SMTPS) avec vérification du certificat pour l'envoi
    # d'e-mails. Ne passer à false qu'en dev/local (ex. MailHog sans TLS).
    smtp_require_tls: bool = Field(default=True, alias="SMTP_REQUIRE_TLS")

    # Online payments (aggregator)
    online_payments_compte_bancaire_id: int | None = None
    epaielink_api_key: str | None = None
    epaielink_webhook_secret: str | None = None
    epaielink_base_url: str | None = None
    epaielink_site_id: str | None = None
    epaielink_return_url: str | None = None
    epaielink_notify_url: str | None = None

    # Google OAuth/Gmail integration for Secretariat.
    # Défaut minimal : gmail.compose UNIQUEMENT (création de brouillons). Le scope
    # restreint gmail.readonly (lecture de boîte) déclenche l'audit Google CASA
    # Tier 2 ; ne l'ajouter via GOOGLE_OAUTH_SCOPES que si réellement nécessaire.
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_oauth_redirect_uri: str | None = Field(default=None, alias="GOOGLE_OAUTH_REDIRECT_URI")
    google_oauth_scopes: str = Field(
        default="https://www.googleapis.com/auth/gmail.compose",
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

    def is_production(self) -> bool:
        return (self.env or "").strip().lower() in {"prod", "production"}

    def refresh_cookie_secure_effective(self) -> bool:
        if self.refresh_cookie_secure is None:
            # dev et test tournent en HTTP : un cookie Secure ne serait jamais
            # renvoyé par le navigateur / client de test. Secure ailleurs (prod).
            return not ((self.env or "").lower() in ("dev", "test"))
        return self.refresh_cookie_secure


settings = Settings()  # singleton

if getattr(settings, "env", "dev").lower() == "dev":
    if _ENV_FILE_PATH:
        logger.info("Loaded .env from %s", _ENV_FILE_PATH)
    else:
        logger.info("No .env found; relying on environment variables only")
