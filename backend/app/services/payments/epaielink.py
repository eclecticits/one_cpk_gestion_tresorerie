from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.core.config import settings
from app.services.payments.base import BasePaymentProvider, PaymentEvent, PaymentInitResult


class EPaieLinkProvider(BasePaymentProvider):
    name = "epaielink"

    def __init__(self, *, api_key: str | None = None, webhook_secret: str | None = None, base_url: str | None = None):
        self.api_key = api_key or ""
        self.webhook_secret = webhook_secret or ""
        self.base_url = base_url or ""

    async def initiate_payment(
        self,
        *,
        amount: float,
        currency: str,
        reference: str,
        method: str,
        phone: str | None,
        description: str | None = None,
    ) -> PaymentInitResult:
        if not self.base_url:
            raise ValueError("EPAIELINK_BASE_URL manquant")
        if not self.api_key:
            raise ValueError("EPAIELINK_API_KEY manquant")
        if not settings.epaielink_site_id:
            raise ValueError("EPAIELINK_SITE_ID manquant")

        endpoint = f"{self.base_url.rstrip('/')}/v1/transaction/initiate"
        channels = "CARD" if method == "VISA" else "MOBILE_MONEY"
        payload = {
            "apikey": self.api_key,
            "site_id": settings.epaielink_site_id,
            "transaction_id": reference,
            "amount": amount,
            "currency": currency,
            "description": description or reference,
            "customer_phone": phone,
            "notify_url": settings.epaielink_notify_url,
            "return_url": settings.epaielink_return_url,
            "channels": channels,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        provider_ref = data.get("operator_reference") or data.get("transaction_id") or reference
        checkout_url = data.get("checkout_url") or data.get("payment_url")
        return PaymentInitResult(provider_ref=provider_ref, checkout_url=checkout_url, raw=data)

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> bool:
        signature = headers.get("x-epaielink-signature")
        if not signature or not self.webhook_secret:
            return False
        expected = hmac.new(
            key=self.webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_event(self, *, body: bytes, headers: dict[str, str]) -> PaymentEvent:
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}

        status_raw = str(payload.get("status") or "PENDING").upper()
        if status_raw in {"ACCEPTED", "COMPLETED", "SUCCESS"}:
            status = "SUCCESS"
        elif status_raw in {"REFUSED", "CANCELLED", "EXPIRED", "FAILED"}:
            status = "FAILED"
        else:
            status = "PENDING"

        method_raw = str(payload.get("payment_method") or payload.get("method") or "").upper()
        if method_raw in {"M-PESA", "MPESA", "MOMO_MPESA"}:
            method = "MOMO_MPESA"
        elif method_raw in {"AIRTEL", "AIRTEL_MONEY", "MOMO_AIRTEL"}:
            method = "MOMO_AIRTEL"
        elif method_raw in {"ORANGE", "ORANGE_MONEY", "MOMO_ORANGE"}:
            method = "MOMO_ORANGE"
        elif method_raw in {"VISA", "CARD"}:
            method = "VISA"
        else:
            method = "MOMO_MPESA"

        return PaymentEvent(
            provider_ref=str(payload.get("operator_reference") or payload.get("provider_ref") or ""),
            status=status,
            amount=float(payload.get("amount") or 0),
            currency=str(payload.get("currency") or "USD").upper(),
            fees=float(payload.get("fees") or 0),
            method=method,
            reference=payload.get("external_reference") or payload.get("reference"),
            phone=payload.get("phone"),
            raw=payload,
        )
