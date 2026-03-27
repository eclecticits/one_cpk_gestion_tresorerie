from __future__ import annotations

from pydantic import BaseModel, Field


class BillingPaymentRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    provider: str | None = None
    amount: float | None = None
