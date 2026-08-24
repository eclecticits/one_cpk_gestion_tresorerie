"""Twilio WhatsApp.

Troisième implémentation, écrite pour prouver que l'abstraction tient : Twilio
n'envoie pas du JSON mais du `application/x-www-form-urlencoded`, s'authentifie
en HTTP Basic (`Account SID` / `Auth Token`) et exige le préfixe `whatsapp:` de
part et d'autre. Rien de tout cela ne remonte au-dessus de ce fichier.

Correspondance des champs de `ProviderConfig` :
  - `api_key`  → Auth Token
  - `extra["account_sid"]` → Account SID (aussi l'utilisateur HTTP Basic)
  - `sender`   → numéro émetteur Twilio, ex. « 14155238886 »
"""

from __future__ import annotations

import logging

import httpx

from .base import ProviderConfig, ProviderResult, WhatsAppProvider

logger = logging.getLogger("onec_cpk_api.notifications.twilio")

_TIMEOUT_SECONDS = 20
_DEFAULT_BASE_URL = "https://api.twilio.com/2010-04-01"


class TwilioWhatsAppProvider(WhatsAppProvider):
    name = "twilio"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.account_sid = config.extra.get("account_sid", "")

    def is_configured(self) -> tuple[bool, str]:
        if not self.account_sid:
            return False, "Account SID Twilio non renseigné."
        if not self.config.api_key:
            return False, "Auth Token Twilio non renseigné."
        if not self.config.sender:
            return False, "Numéro émetteur Twilio non renseigné."
        return True, ""

    @property
    def endpoint(self) -> str:
        base = (self.config.api_url or _DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/Accounts/{self.account_sid}/Messages.json"

    async def send_message(self, *, to: str, text: str) -> ProviderResult:
        if not to:
            return ProviderResult.failure("Destinataire vide.")
        if not text:
            return ProviderResult.failure("Message vide.")

        ok, reason = self.is_configured()
        if not ok:
            return ProviderResult.failure(reason)

        data = {
            "From": f"whatsapp:+{_digits(self.config.sender)}",
            "To": f"whatsapp:+{_digits(to)}",
            "Body": text,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    self.endpoint,
                    data=data,
                    auth=(self.account_sid, self.config.api_key),
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("twilio.send_failed status=%s", exc.response.status_code)
            return ProviderResult.failure(
                f"HTTP {exc.response.status_code} — {_extract_twilio_error(exc.response)}"
            )
        except httpx.HTTPError as exc:
            logger.warning("twilio.send_failed reason=%s", type(exc).__name__)
            return ProviderResult.failure(f"Connexion impossible : {type(exc).__name__}")

        return ProviderResult.success(_extract_message_id(response))


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _extract_twilio_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return (response.text or "").strip()[:400]
    if isinstance(data, dict) and data.get("message"):
        return str(data["message"])[:400]
    return (response.text or "").strip()[:400]


def _extract_message_id(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("sid"):
        return str(data["sid"])[:255]
    return None
