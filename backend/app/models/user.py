from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)

    # profile
    nom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prenom: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # auth
    # When migrating from a legacy auth system, existing rows may not have a password yet.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # authorization
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="reception")
    role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("roles.id"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_first_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    otp_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    otp_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
