from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(20), nullable=True, default="🏢")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    email_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)

    devise_preferee: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    taux_change_interne: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)

    plan_type: Mapped[str] = mapped_column(String(50), nullable=False, default="FREE")
    status_abonnement: Mapped[str] = mapped_column(String(20), nullable=False, default="TRIAL")
    date_expiration_abonnement: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limite_utilisateurs: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
