"""Journal de consommation IA, persisté par organisation.

L'audit n'existait qu'en ligne de log applicative : impossible d'établir une
consommation par organisation ou par mois sans dépouiller des fichiers texte.
Cette table rend la question interrogeable en SQL — un SUM par organisation
suffit à suivre la facture.

L'écriture se fait dans une session courte et indépendante de celle de la
requête : un échec d'audit ne doit jamais faire échouer, ni retarder, la
réponse rendue à l'utilisateur.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        # Index de la requête type : consommation d'une organisation sur une
        # période.
        Index("ix_ai_usage_org_date", "organisation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Module appelant : "chat", "batch", "secretariat"… permet de savoir d'où
    # vient la dépense, pas seulement combien elle coûte.
    module: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
