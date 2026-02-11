from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email_expediteur: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_president: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_tresorier: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_sortie_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    smtp_password: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    smtp_host: Mapped[str] = mapped_column(String(200), nullable=False, default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=465)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
