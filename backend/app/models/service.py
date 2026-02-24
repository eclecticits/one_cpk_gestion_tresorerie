from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user_service import user_services


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    libelle: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    responsable_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    requisitions = relationship("Requisition", back_populates="service")
    encaissements = relationship("Encaissement", back_populates="service")
    sorties_fonds = relationship("SortieFonds", back_populates="service")
    allowed_rubriques = relationship(
        "ServiceRubrique",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    commission_members = relationship(
        "CommissionMember",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    users = relationship("User", secondary=user_services, back_populates="services")
    responsable = relationship("User", foreign_keys=[responsable_id])
