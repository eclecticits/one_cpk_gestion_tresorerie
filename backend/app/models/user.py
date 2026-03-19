from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user_service import user_services


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email", name="uq_users_org_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)

    # profile
    nom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prenom: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # auth
    # When migrating from a legacy auth system, existing rows may not have a password yet.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # authorization
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="reception")
    role_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("roles.id"), nullable=True, index=True)
    service_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("services.id"), nullable=True, index=True)
    organisation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_first_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    otp_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    otp_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    service = relationship("Service", foreign_keys=[service_id])
    organisation = relationship("Organisation", foreign_keys=[organisation_id])
    services = relationship("Service", secondary=user_services, back_populates="users")
