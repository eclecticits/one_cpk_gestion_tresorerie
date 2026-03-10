from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field


class OnlinePaymentInitRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    reference: str
    description: str | None = None
    method: str  # MOMO_AIRTEL | MOMO_MPESA | MOMO_ORANGE | VISA
    phone: str | None = None
    provider: str | None = None


class OnlinePaymentInitResponse(BaseModel):
    provider: str
    provider_ref: str
    checkout_url: str | None = None
    status: str


class OnlinePaymentStatusResponse(BaseModel):
    provider_ref: str
    status: str
    amount: Decimal
    currency: str
    fees: Decimal
    method: str
