from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIProviderConfig(Base):
    """
    Configuration d'un fournisseur IA.
    organisation_id = NULL  → configuration système (Super Admin)
    organisation_id = X     → surcharge par tenant (réservé future)
    """

    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # NULL = système global (Super Admin) ; futur : surcharge par tenant
    organisation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Identificateur lisible : "OpenAI Production", "Claude Dev"
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # "openai" | "anthropic" | "gemini" | "ollama"
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Clé API chiffrée avec Fernet (app/core/encryption.py)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # URL de base custom (Ollama local, Azure OpenAI, proxy…)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Modèle sélectionné par défaut pour ce fournisseur
    default_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # Est-ce que ce fournisseur est actif ?
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Provider de premier choix (un seul par scope organisation_id)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Ordre d'essai en cas de fallback (1 = essayé en premier)
    fallback_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Configuration supplémentaire (timeout, temperature, max_tokens…)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
