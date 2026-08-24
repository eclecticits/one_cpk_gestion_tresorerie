"""Lecture des réglages WhatsApp d'une organisation.

Deux règles gouvernent ce module :

* **Le secret ne remonte jamais.** `load_whatsapp_settings` déchiffre la clé pour
  la placer dans une `ProviderConfig` destinée au seul provider. Tout ce qui part
  vers l'API ou le frontend passe par `describe_whatsapp_settings`, qui ne
  contient aucun secret — pas même masqué, ce qui a déjà induit en erreur avec
  l'`<input type="password">` de l'écran actuel.
* **Compatibilité ascendante.** Tant que la migration n'a pas été appliquée, ou
  pour une organisation dont la clé n'a pas encore été reprise, on retombe sur
  l'ancienne colonne `whatsapp_api_key` en clair. Rien ne casse ; la reprise se
  fait à la première sauvegarde.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_settings import SystemSettings

from .providers.base import ProviderConfig
from .providers.registry import DEFAULT_PROVIDER, PROVIDER_LABELS
from .service import WhatsAppSettings

logger = logging.getLogger("onec_cpk_api.notifications.settings")


def _get(obj: object, name: str, default=None):
    """Lecture tolérante : la colonne peut ne pas exister avant la migration."""
    value = getattr(obj, name, None)
    return default if value is None else value


def resolve_api_key(row: SystemSettings) -> str:
    """Clé en clair, depuis la colonne chiffrée si elle existe, sinon l'ancienne."""
    encrypted = _get(row, "whatsapp_api_key_encrypted", "")
    if encrypted:
        try:
            from app.core.encryption import decrypt_secret

            return decrypt_secret(encrypted)
        except Exception:
            # Clé maître changée : on ne fait pas tomber les notifications d'un
            # tenant sur une erreur de configuration d'un autre. Le provider
            # signalera « clé absente » et la ligne du journal le dira.
            logger.warning(
                "notifications.key_undecryptable org=%s", getattr(row, "organisation_id", None)
            )
            return ""
    return _get(row, "whatsapp_api_key", "") or ""


def build_settings(row: SystemSettings | None, organisation_name: str = "") -> WhatsAppSettings:
    """Construit la configuration figée transportable vers une tâche de fond."""
    if row is None:
        return WhatsAppSettings(organisation_name=organisation_name)

    provider = (_get(row, "whatsapp_provider", "") or DEFAULT_PROVIDER).strip().lower()

    extra: dict[str, str] = {}
    for key in ("whatsapp_template_name", "whatsapp_account_sid", "whatsapp_graph_version"):
        value = _get(row, key, "")
        if value:
            extra[key.replace("whatsapp_", "")] = str(value)

    config = ProviderConfig(
        api_url=_get(row, "whatsapp_api_url", "") or "",
        api_key=resolve_api_key(row),
        phone_number_id=_get(row, "whatsapp_phone_number_id", "") or "",
        business_account_id=_get(row, "whatsapp_business_account_id", "") or "",
        sender=_get(row, "whatsapp_sender", "") or "",
        extra=extra,
    )

    raw_templates = _get(row, "whatsapp_templates", None)
    template_overrides = raw_templates if isinstance(raw_templates, dict) else {}

    return WhatsAppSettings(
        enabled=bool(_get(row, "whatsapp_enabled", False)),
        notify_payments=bool(_get(row, "whatsapp_notify_payments", False)),
        notify_sorties=bool(_get(row, "whatsapp_notify_sorties", False)),
        provider=provider,
        provider_config=config,
        templates=template_overrides,
        organisation_name=organisation_name,
    )


async def load_whatsapp_settings(
    db: AsyncSession,
    organisation_id: int | None,
    organisation_name: str = "",
) -> WhatsAppSettings:
    """Charge les réglages du tenant. Ne lève jamais : au pire, canal fermé."""
    if organisation_id is None:
        return WhatsAppSettings(organisation_name=organisation_name)
    try:
        # `.limit(1)` et non `scalar_one_or_none()` : une organisation peut porter
        # plusieurs lignes `system_settings` — c'est le défaut que
        # `consolidate_system_settings` répare — et une exception ici couperait
        # toutes ses notifications sans que rien ne l'explique.
        row = (
            await db.execute(
                select(SystemSettings)
                .where(SystemSettings.organisation_id == organisation_id)
                .order_by(SystemSettings.updated_at.desc())
                .limit(1)
            )
        ).scalars().first()
    except Exception:
        logger.exception("notifications.settings_load_failed org=%s", organisation_id)
        return WhatsAppSettings(organisation_name=organisation_name)
    return build_settings(row, organisation_name)


def describe_whatsapp_settings(row: SystemSettings | None) -> dict:
    """Vue publique, sans aucun secret — c'est elle que l'API renvoie.

    `has_api_key` remplace la clé : l'interface a besoin de savoir si une clé est
    posée, jamais de sa valeur.
    """
    if row is None:
        return {
            "enabled": False,
            "notify_payments": False,
            "notify_sorties": False,
            "provider": DEFAULT_PROVIDER,
            "provider_label": PROVIDER_LABELS.get(DEFAULT_PROVIDER, DEFAULT_PROVIDER),
            "api_url": "",
            "sender": "",
            "phone_number_id": "",
            "business_account_id": "",
            "has_api_key": False,
            "templates": {},
        }

    provider = (_get(row, "whatsapp_provider", "") or DEFAULT_PROVIDER).strip().lower()
    raw_templates = _get(row, "whatsapp_templates", None)

    return {
        "enabled": bool(_get(row, "whatsapp_enabled", False)),
        "notify_payments": bool(_get(row, "whatsapp_notify_payments", False)),
        "notify_sorties": bool(_get(row, "whatsapp_notify_sorties", False)),
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "api_url": _get(row, "whatsapp_api_url", "") or "",
        "sender": _get(row, "whatsapp_sender", "") or "",
        "phone_number_id": _get(row, "whatsapp_phone_number_id", "") or "",
        "business_account_id": _get(row, "whatsapp_business_account_id", "") or "",
        "has_api_key": bool(resolve_api_key(row)),
        "templates": raw_templates if isinstance(raw_templates, dict) else {},
    }
