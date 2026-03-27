from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PaymentLogOut(BaseModel):
    id: int
    organisation_id: int
    phone_number: str | None = None
    amount: Decimal | None = None
    provider: str | None = None
    status: str
    raw_response: dict | None = None
    created_at: datetime


class PaymentLogListOut(BaseModel):
    items: list[PaymentLogOut]
    total: int
