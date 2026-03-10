from __future__ import annotations

from app.core.config import settings
from app.services.payments.base import BasePaymentProvider
from app.services.payments.epaielink import EPaieLinkProvider


def get_provider(name: str | None) -> BasePaymentProvider:
    key = (name or "epaielink").lower()
    if key == "epaielink":
        return EPaieLinkProvider(
            api_key=settings.epaielink_api_key,
            webhook_secret=settings.epaielink_webhook_secret,
            base_url=settings.epaielink_base_url,
        )
    raise ValueError(f"Provider inconnu: {name}")
