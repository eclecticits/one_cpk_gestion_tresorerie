"""Abstraction du fournisseur WhatsApp.

Le dépôt parle aujourd'hui à Evolution API (Baileys, auto-hébergé) : header
`apikey`, corps `{"number", "text"}`, une seule URL. Meta Cloud API et Twilio ont
des contrats très différents — JSON imbriqué et `phone_number_id` d'un côté,
form-urlencoded et préfixe `whatsapp:` de l'autre. Cette interface est le seul
endroit du code qui connaît ces différences ; changer de fournisseur ne doit
toucher aucune ligne de logique métier.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration d'un fournisseur, résolue depuis les réglages du tenant.

    `api_key` est le secret déchiffré : il ne doit jamais quitter le backend,
    ni être journalisé, ni figurer dans un message d'erreur remonté au client.
    """

    api_url: str = ""
    api_key: str = ""
    phone_number_id: str = ""
    business_account_id: str = ""
    sender: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    """Résultat d'un envoi unitaire.

    Un provider ne lève jamais : il renvoie toujours un résultat. C'est ce qui
    garantit qu'un paiement ou une sortie de fonds ne peut pas échouer à cause
    d'une panne WhatsApp — l'appelant journalise et poursuit.
    """

    ok: bool
    provider_message_id: str | None = None
    error: str | None = None

    @classmethod
    def success(cls, message_id: str | None = None) -> "ProviderResult":
        return cls(ok=True, provider_message_id=message_id)

    @classmethod
    def failure(cls, error: str) -> "ProviderResult":
        # Tronqué : certains fournisseurs renvoient une page HTML entière en cas
        # d'erreur, qui n'a rien à faire dans une colonne de journal.
        return cls(ok=False, error=(error or "")[:1000])


class WhatsAppProvider(abc.ABC):
    """Contrat commun à tous les fournisseurs WhatsApp."""

    #: Identifiant stocké dans `notification_logs.provider` et dans les réglages.
    name: str = "base"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def send_message(self, *, to: str, text: str) -> ProviderResult:
        """Envoie un message texte. `to` est au format E.164 sans le « + »."""

    def is_configured(self) -> tuple[bool, str]:
        """Dit si le fournisseur a de quoi émettre, et sinon pourquoi.

        Renvoyer la raison permet à l'interface d'afficher « Clé API manquante »
        plutôt qu'un « service indisponible » opaque.
        """
        if not self.config.api_url:
            return False, "URL de l'API non renseignée."
        return True, ""

    def describe(self) -> dict[str, str]:
        """Résumé sans secret, destiné à l'écran de paramètres."""
        return {
            "provider": self.name,
            "api_url": self.config.api_url,
            "sender": self.config.sender or self.config.phone_number_id,
            "has_key": "oui" if self.config.api_key else "non",
        }
