"""Meta WhatsApp Business Cloud API.

Contrat volontairement écrit en entier plutôt que laissé en `NotImplementedError` :
migrer d'Evolution vers Meta doit être un changement de réglage, pas un chantier.

Deux différences comptent au moment de basculer, et l'interface ne peut pas les
masquer — elles sont annoncées ici pour qu'elles ne surprennent personne :

1. **Fenêtre de 24 heures.** Meta n'accepte un message libre que si le
   destinataire a écrit à l'entreprise dans les 24 h. Hors de cette fenêtre, seul
   un *template* approuvé passe. Les notifications d'ONEC sont non sollicitées :
   en pratique, sur Meta, elles devront toutes être des templates approuvés.
   `template_name` porte celui à utiliser.
2. **Numéro émetteur.** Meta n'envoie pas depuis une URL mais depuis un
   `phone_number_id` — d'où le champ dédié dans `ProviderConfig`.
"""

from __future__ import annotations

import logging

import httpx

from .base import ProviderConfig, ProviderResult, WhatsAppProvider

logger = logging.getLogger("onec_cpk_api.notifications.meta")

_TIMEOUT_SECONDS = 20
_DEFAULT_GRAPH_VERSION = "v21.0"
_DEFAULT_LANGUAGE = "fr"


class MetaWhatsAppProvider(WhatsAppProvider):
    name = "meta"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.graph_version = config.extra.get("graph_version") or _DEFAULT_GRAPH_VERSION
        self.template_name = config.extra.get("template_name") or ""
        self.language = config.extra.get("language") or _DEFAULT_LANGUAGE

    def is_configured(self) -> tuple[bool, str]:
        if not self.config.api_key:
            return False, "Jeton d'accès Meta non renseigné."
        if not self.config.phone_number_id:
            return False, "Identifiant du numéro émetteur (phone_number_id) non renseigné."
        return True, ""

    @property
    def endpoint(self) -> str:
        base = (self.config.api_url or "https://graph.facebook.com").rstrip("/")
        return f"{base}/{self.graph_version}/{self.config.phone_number_id}/messages"

    async def send_message(self, *, to: str, text: str) -> ProviderResult:
        if not to:
            return ProviderResult.failure("Destinataire vide.")
        if not text:
            return ProviderResult.failure("Message vide.")

        ok, reason = self.is_configured()
        if not ok:
            return ProviderResult.failure(reason)

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(to=to, text=text)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(self.endpoint, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("meta.send_failed status=%s", exc.response.status_code)
            return ProviderResult.failure(
                f"HTTP {exc.response.status_code} — {_extract_meta_error(exc.response)}"
            )
        except httpx.HTTPError as exc:
            logger.warning("meta.send_failed reason=%s", type(exc).__name__)
            return ProviderResult.failure(f"Connexion impossible : {type(exc).__name__}")

        return ProviderResult.success(_extract_message_id(response))

    def _build_payload(self, *, to: str, text: str) -> dict:
        if self.template_name:
            # Hors fenêtre de 24 h, c'est la seule forme que Meta accepte. Le corps
            # du message rendu est passé en unique paramètre de corps ; le template
            # approuvé doit donc être défini avec un seul `{{1}}`.
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": self.template_name,
                    "language": {"code": self.language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": text}],
                        }
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }


def _extract_meta_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return (response.text or "").strip()[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        parts = [str(error.get("message") or "").strip()]
        if error.get("error_user_msg"):
            parts.append(str(error["error_user_msg"]).strip())
        joined = " — ".join(p for p in parts if p)
        if joined:
            return joined[:400]
    return (response.text or "").strip()[:400]


def _extract_message_id(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])[:255]
    return None
