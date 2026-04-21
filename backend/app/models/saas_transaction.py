from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"
    VALIDATION = "validation"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("flow IN ('SAAS_SUBSCRIPTION')", name="ck_transactions_flow"),
        CheckConstraint("beneficiary_type IN ('PLATFORM')", name="ck_transactions_beneficiary_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    flow: Mapped[str] = mapped_column(String(30), nullable=False, default="SAAS_SUBSCRIPTION")
    beneficiary_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PLATFORM")
    beneficiary_organisation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    merchant_account_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=utcnow)
