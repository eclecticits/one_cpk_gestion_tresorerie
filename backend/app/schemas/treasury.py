from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import Field

from app.schemas.base import DecimalBaseModel
from app.schemas.banque import CompteBancaireOut


class TreasuryCaisseOut(DecimalBaseModel):
    solde_usd: Decimal = Decimal("0")
    solde_cdf: Decimal = Decimal("0")
    derniere_maj: datetime | None = None


class TreasuryOverviewOut(BaseModel):
    caisse: TreasuryCaisseOut
    comptes: list[CompteBancaireOut]


class TreasuryConfirmClassificationRequest(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    account: str = Field(min_length=1, max_length=10)
    confidence_score: float = 1.0


class TreasuryConfirmClassificationResponse(BaseModel):
    status: str
