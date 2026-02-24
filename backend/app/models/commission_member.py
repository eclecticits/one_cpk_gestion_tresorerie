from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommissionRole(enum.Enum):
    PRESIDENT = "PRESIDENT"
    DELEGUE = "DELEGUE"
    MEMBRE = "MEMBRE"
    ASSISTANT = "ASSISTANT"


class CommissionMember(Base):
    __tablename__ = "commission_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    matricule: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    role_type: Mapped[CommissionRole] = mapped_column(
        Enum(
            CommissionRole,
            name="commission_role_type",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=CommissionRole.MEMBRE,
    )
    custom_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    is_signer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    service = relationship("Service", back_populates="commission_members")
    user = relationship("User")
