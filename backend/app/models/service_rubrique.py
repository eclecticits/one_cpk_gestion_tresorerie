from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ServiceRubrique(Base):
    __tablename__ = "service_rubriques"
    __table_args__ = (
        UniqueConstraint("service_id", "budget_poste_id", name="uq_service_rubrique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    budget_poste_id: Mapped[int] = mapped_column(ForeignKey("budget_postes.id", ondelete="CASCADE"), nullable=False, index=True)

    service = relationship("Service", back_populates="allowed_rubriques")
    budget_poste = relationship("BudgetPoste")
