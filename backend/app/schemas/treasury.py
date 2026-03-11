from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.base import DecimalBaseModel
from app.schemas.banque import CompteBancaireOut


class TreasuryCaisseOut(DecimalBaseModel):
    solde_usd: Decimal = Decimal("0")
    solde_cdf: Decimal = Decimal("0")
    derniere_maj: datetime | None = None


class TreasuryOverviewOut(BaseModel):
    caisse: TreasuryCaisseOut
    comptes: list[CompteBancaireOut]
