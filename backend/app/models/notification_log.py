from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Vocabulaire ──────────────────────────────────────────────────────────────
# Volontairement des constantes de chaînes plutôt qu'un Enum PostgreSQL : ajouter
# un canal ou un statut ne doit pas exiger un ALTER TYPE, opération verrouillante
# que le dépôt évite déjà ailleurs.

CHANNEL_EMAIL = "EMAIL"
CHANNEL_WHATSAPP = "WHATSAPP"

STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"  # canal désactivé, destinataire sans numéro, opt-out


class NotificationLog(Base):
    """Journal d'envoi, une ligne par (événement × destinataire × canal).

    Pourquoi une table dédiée plutôt qu'une extension de `system_events` :
    `system_events` est un journal d'incidents (level / code / message + JSONB).
    Il n'a ni destinataire, ni statut, ni canal en colonnes indexables. Or c'est
    exactement ce dont on a besoin pour répondre à « quels envois ont échoué
    pour cette sortie ? » — la question qui rend possible le bouton « Renvoyer ».
    Le motif de dé-duplication, lui, est repris de `system_events`.
    """

    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    organisation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    # Objet métier à l'origine de l'envoi : « sortie_fonds » + son id, etc.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    recipient: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    recipient_role: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING, index=True)

    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Empreinte de (organisation, événement, entité, canal, destinataire).
    # Unique : c'est elle, et non un verrou applicatif, qui garantit qu'un
    # double-clic ou un rejeu HTTP ne produit pas un second message.
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)

    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_notification_logs_dedup_key"),
        Index("ix_notification_logs_entity", "entity_type", "entity_id"),
        Index("ix_notification_logs_org_created", "organisation_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return (
            f"<NotificationLog {self.channel} {self.event_type} "
            f"{self.recipient} {self.status}>"
        )
