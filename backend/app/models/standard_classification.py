from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StandardClassification(Base):
    __tablename__ = "standard_classifications"
    __table_args__ = (
        UniqueConstraint("organisation_id", "raw_label", name="uq_std_class_org_label"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False, index=True)
    raw_label: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    assigned_account: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
