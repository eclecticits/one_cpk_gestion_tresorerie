from __future__ import annotations

from pydantic import BaseModel, Field


class PaymentSessionCreate(BaseModel):
    tenant_id: str
    amount: float = Field(gt=0)
    currency: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None


class PaymentSessionResponse(BaseModel):
    checkout_url: str
    transaction_id: str


class PaymentSessionInitiate(BaseModel):
    method: str
    phone: str | None = None
    provider: str | None = None
