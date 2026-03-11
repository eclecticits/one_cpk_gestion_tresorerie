from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
