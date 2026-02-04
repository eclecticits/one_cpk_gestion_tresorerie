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

    # JWT
    jwt_secret: str
    jwt_issuer: str = "onec-cpk-api"
    jwt_audience: str = "onec-cpk-frontend"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # One-time bootstrap (create first admin). Keep this secret server-side.
    bootstrap_admin_password: str | None = None

    # Cookies
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool | None = None
    refresh_cookie_samesite: str = "lax"  # lax/strict/none
    refresh_cookie_domain: str | None = None

    # CORS
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

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
