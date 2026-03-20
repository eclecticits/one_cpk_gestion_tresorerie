from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Banque(Base):
    __tablename__ = "banques"
    __table_args__ = (UniqueConstraint("organisation_id", "nom", name="uq_banques_org_nom"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    nom: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organisation = relationship("Organisation")
    comptes_bancaires = relationship("CompteBancaire", back_populates="banque")
