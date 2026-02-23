from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user_service import user_services


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    libelle: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    requisitions = relationship("Requisition", back_populates="service")
    encaissements = relationship("Encaissement", back_populates="service")
    sorties_fonds = relationship("SortieFonds", back_populates="service")
    allowed_rubriques = relationship(
        "ServiceRubrique",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    users = relationship("User", secondary=user_services, back_populates="services")
