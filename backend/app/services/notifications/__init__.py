"""Couche de notification d'ONEC Smart.

    Événement métier
          │
          ▼
    notify_whatsapp()  ──► notification_logs (PENDING)
          │
          ▼  (tâche de fond)
    WhatsAppProvider ──► Evolution · Meta · Twilio
          │
          ▼
    notification_logs (SENT / FAILED)

Le canal e-mail existant (`app/services/mailer.py`) n'est pas déplacé : il
continue de fonctionner tel quel. Ce paquet ajoute le canal WhatsApp avec ce qui
lui manquait — journal, dé-duplication, remontée d'erreur — et servira de socle
si l'e-mail est un jour réunifié ici.
"""

from .events import (
    ALL_EVENTS,
    EVENT_LABELS,
    FUND_OUTFLOW,
    OUTFLOW_EVENTS,
    PAYMENT_COMPLEMENT,
    PAYMENT_EVENTS,
    PAYMENT_PROFORMA_CONVERTED,
    PAYMENT_RECEIVED,
    PAYMENT_REMINDER,
    REQUISITION_APPROVED,
    TEST_MESSAGE,
)
from .phone import format_phone_display, mask_phone, normalize_phone, normalize_phone_list
from .providers.base import ProviderConfig, ProviderResult, WhatsAppProvider
from .providers.registry import available_providers, get_provider, register_provider
from .recipients import (
    load_bureau_members,
    resolve_client_recipient,
    resolve_outflow_recipients,
)
from .service import (
    Recipient,
    WhatsAppSettings,
    build_dedup_key,
    deliver_pending,
    notify_whatsapp,
    queue_whatsapp,
)
from .settings_loader import (
    build_settings,
    describe_whatsapp_settings,
    load_whatsapp_settings,
)

__all__ = [
    # Événements
    "ALL_EVENTS",
    "EVENT_LABELS",
    "FUND_OUTFLOW",
    "OUTFLOW_EVENTS",
    "PAYMENT_COMPLEMENT",
    "PAYMENT_EVENTS",
    "PAYMENT_PROFORMA_CONVERTED",
    "PAYMENT_RECEIVED",
    "PAYMENT_REMINDER",
    "REQUISITION_APPROVED",
    "TEST_MESSAGE",
    # Téléphone
    "format_phone_display",
    "mask_phone",
    "normalize_phone",
    "normalize_phone_list",
    # Fournisseurs
    "ProviderConfig",
    "ProviderResult",
    "WhatsAppProvider",
    "available_providers",
    "get_provider",
    "register_provider",
    # Destinataires
    "load_bureau_members",
    "resolve_client_recipient",
    "resolve_outflow_recipients",
    # Service
    "Recipient",
    "WhatsAppSettings",
    "build_dedup_key",
    "deliver_pending",
    "notify_whatsapp",
    "queue_whatsapp",
    # Réglages
    "build_settings",
    "describe_whatsapp_settings",
    "load_whatsapp_settings",
]
