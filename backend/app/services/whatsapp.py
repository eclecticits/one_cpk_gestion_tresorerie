"""Coque de compatibilité — **déprécié**.

Ce module ne contient plus d'implémentation. Il redirige vers
`app/services/notifications/`, qui est désormais le seul endroit du dépôt où un
message WhatsApp est normalisé, rendu, journalisé et remis.

Pourquoi il subsiste : `requisition_service.py`, `requisitions.py` et
`encaissements.py` l'importent encore. Supprimer les symboles casserait ces
imports pour un gain nul. Les deux fonctions restent donc en place, avec la même
signature qu'avant, et délèguent.

Pourquoi ne plus s'en servir :

* `send_whatsapp_message` reçoit la clé API **en clair** en argument. Depuis la
  migration `20260823_whatsapp_notifs`, `system_settings.whatsapp_api_key` est
  vidée au profit de `whatsapp_api_key_encrypted` : tout appelant qui lit encore
  la colonne en clair transmet une chaîne vide et n'envoie plus rien.
  `load_whatsapp_settings()` déchiffre, lui, la bonne colonne.
* Aucun de ces deux appels n'écrit dans `notification_logs` : un échec y est
  invisible, et rien n'empêche un double envoi sur rejeu HTTP.

À utiliser à la place :

    from app.services.notifications import (
        load_whatsapp_settings, notify_whatsapp, Recipient,
    )

    settings = await load_whatsapp_settings(db, organisation_id, organisation_name)
    await notify_whatsapp(db, background_tasks, ..., settings=settings)
"""

from __future__ import annotations

import logging

logger = logging.getLogger("onec_cpk_api.whatsapp")


def normalize_whatsapp_numbers(raw: str | None) -> list[str]:
    """**Déprécié** — utiliser `notifications.phone.normalize_phone_list`.

    Délègue à l'implémentation unique. Attention : celle-ci ajoute l'indicatif
    pays manquant (« 0810123456 » → « 243810123456 »), ce que cette fonction ne
    faisait pas — un numéro national partait tel quel et échouait en silence
    chez le fournisseur. Le format de sortie perd aussi le « + » de tête, qui
    n'était de toute façon pas attendu par Evolution.
    """
    # Import différé : `app.services.notifications` charge des modèles, et ce
    # module-ci est importé très tôt par plusieurs endpoints.
    from app.services.notifications.phone import normalize_phone_list

    return normalize_phone_list(raw)


async def send_whatsapp_message(api_url: str, api_key: str, number: str, message: str) -> None:
    """**Déprécié** — utiliser `notifications.notify_whatsapp`.

    Envoi direct, sans journal ni dé-duplication. Conservé pour ne pas casser
    les importateurs existants ; ne lève jamais, comme avant.
    """
    if not api_url or not number or not message:
        return

    from app.services.notifications.providers.base import ProviderConfig
    from app.services.notifications.providers.evolution import EvolutionWhatsAppProvider

    provider = EvolutionWhatsAppProvider(ProviderConfig(api_url=api_url, api_key=api_key))
    try:
        result = await provider.send_message(to=number, text=message)
    except Exception:  # pragma: no cover - le provider ne lève pas, filet de sécurité
        logger.exception("WhatsApp send failed for %s", number)
        return
    if not result.ok:
        # Le motif exact vient du fournisseur ; il ne contient pas le secret.
        logger.warning("WhatsApp send failed for %s: %s", number, result.error)
