"""Evolution API / Baileys — le fournisseur déjà en place dans ONEC Smart.

Contrat repris à l'identique de l'ancien `app/services/whatsapp.py` :
`POST <api_url>` avec l'en-tête `apikey` et le corps `{"number", "text"}`.
Seule différence, et c'est tout l'objet de la reprise : cette implémentation
**renvoie** un résultat au lieu d'avaler l'erreur dans un `logger.exception`.
"""

from __future__ import annotations

import logging

import httpx

from .base import ProviderResult, WhatsAppProvider

logger = logging.getLogger("onec_cpk_api.notifications.evolution")

# Evolution répond vite ou pas du tout ; 20 s était déjà la valeur en place.
_TIMEOUT_SECONDS = 20


class EvolutionWhatsAppProvider(WhatsAppProvider):
    name = "evolution"

    def is_configured(self) -> tuple[bool, str]:
        if not self.config.api_url:
            return False, "URL Evolution non renseignée."
        if not self.config.api_key:
            return False, "Clé API Evolution non renseignée."
        return True, ""

    async def send_message(self, *, to: str, text: str) -> ProviderResult:
        if not to:
            return ProviderResult.failure("Destinataire vide.")
        if not text:
            return ProviderResult.failure("Message vide.")

        ok, reason = self.is_configured()
        if not ok:
            return ProviderResult.failure(reason)

        headers = {"apikey": self.config.api_key}
        payload = {"number": to, "text": text}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(self.config.api_url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Le corps de la réponse porte le motif réel (numéro non inscrit sur
            # WhatsApp, instance déconnectée…). On le garde, tronqué.
            body = (exc.response.text or "").strip()[:400]
            logger.warning("evolution.send_failed status=%s", exc.response.status_code)
            return ProviderResult.failure(f"HTTP {exc.response.status_code} — {body}")
        except httpx.HTTPError as exc:
            logger.warning("evolution.send_failed reason=%s", type(exc).__name__)
            return ProviderResult.failure(f"Connexion impossible : {type(exc).__name__}")

        return ProviderResult.success(_extract_message_id(response))


def _extract_message_id(response: httpx.Response) -> str | None:
    """Evolution renvoie `{"key": {"id": "..."}}` — mais pas toujours."""
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    key = data.get("key")
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])[:255]
    for candidate in ("id", "messageId", "message_id"):
        if data.get(candidate):
            return str(data[candidate])[:255]
    return None
