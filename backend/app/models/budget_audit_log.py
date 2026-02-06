from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetAuditLog(Base):
    __tablename__ = "budget_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exercice_id: Mapped[int | None] = mapped_column(ForeignKey("budget_exercices.id"), nullable=True)
    budget_ligne_id: Mapped[int | None] = mapped_column(ForeignKey("budget_lignes.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="update")
    field_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    old_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    new_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
