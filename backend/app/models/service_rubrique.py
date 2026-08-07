from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
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
    # Autorisation active. Un poste déjà utilisé qu'on « désactive » passe à
    # active=False (soft-deactivate) au lieu d'être supprimé : il sort des choix
    # futurs mais la liaison au service est conservée pour la cohérence des états.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True, index=True)

    service = relationship("Service", back_populates="allowed_rubriques")
    budget_poste = relationship("BudgetPoste")
