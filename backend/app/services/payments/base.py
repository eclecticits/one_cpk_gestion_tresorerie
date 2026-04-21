from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PaymentInitResult:
    provider_ref: str
    checkout_url: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class PaymentEvent:
    provider_ref: str
    status: str  # SUCCESS | FAILED | PENDING
    amount: float
    currency: str
    fees: float
    method: str  # MOMO_AIRTEL | MOMO_MPESA | MOMO_ORANGE | VISA
    reference: str | None = None
    phone: str | None = None
    raw: dict[str, Any] | None = None


class BasePaymentProvider:
    name: str = "base"

    async def initiate_payment(
        self,
        *,
        amount: float,
        currency: str,
        reference: str,
        method: str,
        phone: str | None,
        description: str | None = None,
        merchant_config: dict[str, Any] | None = None,
    ) -> PaymentInitResult:
        raise NotImplementedError

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> bool:
        raise NotImplementedError

    def parse_event(self, *, body: bytes, headers: dict[str, str]) -> PaymentEvent:
        raise NotImplementedError
