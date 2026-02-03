from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrintSettings(Base):
    __tablename__ = "print_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    organization_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    organization_subtitle: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    header_text: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    bank_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bank_account: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    mobile_money_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    mobile_money_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    footer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    show_header_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_footer_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    logo_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    stamp_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    signature_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    signature_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    paper_format: Mapped[str] = mapped_column(String(3), nullable=False, default="A5")
    compact_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
