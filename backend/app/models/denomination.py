from __future__ import annotations

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Denomination(Base):
    __tablename__ = "denominations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    devise: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    valeur: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    est_actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
