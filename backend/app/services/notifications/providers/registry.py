"""Fabrique de fournisseurs WhatsApp.

Un seul endroit connaît la liste des implémentations. Ajouter un agrégateur local
revient à écrire une classe et à l'inscrire ici — aucune autre ligne du projet
ne change.
"""

from __future__ import annotations

from .base import ProviderConfig, WhatsAppProvider
from .evolution import EvolutionWhatsAppProvider
from .meta import MetaWhatsAppProvider
from .twilio import TwilioWhatsAppProvider

#: Fournisseur retenu quand le réglage est vide : celui déjà en production.
DEFAULT_PROVIDER = "evolution"

_PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    EvolutionWhatsAppProvider.name: EvolutionWhatsAppProvider,
    MetaWhatsAppProvider.name: MetaWhatsAppProvider,
    TwilioWhatsAppProvider.name: TwilioWhatsAppProvider,
}

#: Libellés pour la liste déroulante des paramètres.
PROVIDER_LABELS: dict[str, str] = {
    "evolution": "Evolution API / Baileys (auto-hébergé)",
    "meta": "Meta WhatsApp Business Cloud",
    "twilio": "Twilio WhatsApp",
}


def available_providers() -> list[dict[str, str]]:
    return [{"value": key, "label": PROVIDER_LABELS.get(key, key)} for key in _PROVIDERS]


def get_provider(name: str | None, config: ProviderConfig) -> WhatsAppProvider:
    """Instancie le fournisseur demandé.

    Un nom inconnu retombe sur le fournisseur par défaut plutôt que de lever :
    une faute de frappe dans un réglage ne doit pas couper toutes les
    notifications d'un tenant sans explication. L'écran de paramètres, lui,
    n'offre que des valeurs valides.
    """
    key = (name or "").strip().lower() or DEFAULT_PROVIDER
    provider_cls = _PROVIDERS.get(key, _PROVIDERS[DEFAULT_PROVIDER])
    return provider_cls(config)


def register_provider(provider_cls: type[WhatsAppProvider], label: str | None = None) -> None:
    """Inscrit une implémentation supplémentaire (agrégateur local, test…)."""
    _PROVIDERS[provider_cls.name] = provider_cls
    if label:
        PROVIDER_LABELS[provider_cls.name] = label
