from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    email_expediteur: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_president: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_tresorier: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    emails_bureau_sortie_cc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_validation_1: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email_validation_final: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    max_caisse_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    smtp_password: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    smtp_host: Mapped[str] = mapped_column(String(200), nullable=False, default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=465)
    last_weekly_report_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_weekly_report_status: Mapped[str] = mapped_column(String(20), nullable=False, default="never")
    last_weekly_report_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_weekly_report_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_weekly_report_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
