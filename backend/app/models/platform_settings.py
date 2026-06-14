from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlatformSettings(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    billing_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # Google OAuth — configurables depuis la console SaaS (priorité sur .env)
    google_client_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    google_client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_oauth_redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_oauth_redirect_uri_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    google_oauth_redirect_uri_local: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_oauth_redirect_uri_local_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
