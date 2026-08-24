"""Service de notification : un point d'entrée, deux temps.

Le fonctionnement en deux temps est ce qui rend l'ensemble sûr :

1. **Mise en file, dans la requête.** Le contexte tenant est vivant, les objets
   métier sont chargés : on résout les destinataires, on rend les messages et on
   écrit une ligne `notification_logs` par destinataire, en `PENDING`. La
   contrainte d'unicité sur `dedup_key` fait ici tout le travail d'idempotence :
   un double-clic ou un rejeu HTTP n'insère rien de plus, donc n'enverra rien de
   plus. Aucun appel réseau à ce stade.

2. **Remise, en tâche de fond.** Seuls des scalaires traversent — des UUID de
   lignes et une configuration figée. La tâche rouvre sa propre session, repose
   explicitement le contexte tenant, envoie, et met à jour le statut. Aucun objet
   SQLAlchemy de la requête n'est réutilisé : c'est ce qui évite le
   `MissingGreenlet` classique sur objets expirés après commit.

Conséquence recherchée : un paiement ou une sortie de fonds ne peut pas échouer
à cause de WhatsApp. Au pire, une ligne du journal porte `FAILED` et son motif.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import (
    CHANNEL_WHATSAPP,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    NotificationLog,
)

from . import events as event_types
from . import templates
from .phone import normalize_phone
from .providers.base import ProviderConfig
from .providers.registry import DEFAULT_PROVIDER, get_provider

logger = logging.getLogger("onec_cpk_api.notifications")


# ── Types d'entrée ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Recipient:
    """Un destinataire résolu. `phone` peut être brut : il sera normalisé."""

    phone: str | None
    name: str = ""
    role: str = ""


@dataclass(frozen=True)
class WhatsAppSettings:
    """Configuration figée, capturée dans la requête et transportable telle quelle.

    Aucun objet SQLAlchemy ici : c'est ce qui permet de la passer à une tâche de
    fond sans risquer une lecture différée hors contexte tenant.
    """

    enabled: bool = False
    notify_payments: bool = False
    notify_sorties: bool = False
    provider: str = DEFAULT_PROVIDER
    provider_config: ProviderConfig = field(default_factory=ProviderConfig)
    templates: dict = field(default_factory=dict)
    organisation_name: str = ""

    def accepts(self, event_type: str) -> bool:
        """Le canal est-il ouvert pour ce type d'événement ?"""
        if not self.enabled:
            return False
        if event_type in event_types.PAYMENT_EVENTS:
            return self.notify_payments
        if event_type in event_types.OUTFLOW_EVENTS:
            return self.notify_sorties
        # TEST_MESSAGE : l'activation générale suffit, c'est le seul moyen de
        # vérifier une configuration avant d'ouvrir les familles d'événements.
        return True


# ── Clé de dé-duplication ────────────────────────────────────────────────────


def build_dedup_key(
    *,
    organisation_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    channel: str,
    recipient: str,
    nonce: str = "",
) -> str:
    """Empreinte stable de (organisation, événement, entité, canal, destinataire).

    `nonce` sert aux envois qui doivent pouvoir se répéter : un message de test,
    ou un renvoi manuel déclenché depuis l'administration.
    """
    raw = "|".join(
        [
            str(organisation_id or 0),
            event_type or "",
            entity_type or "",
            str(entity_id or ""),
            channel or "",
            recipient or "",
            nonce or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Temps 1 : mise en file ───────────────────────────────────────────────────


async def queue_whatsapp(
    db: AsyncSession,
    *,
    organisation_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    recipients: Iterable[Recipient],
    variables: dict,
    settings: WhatsAppSettings,
    nonce: str = "",
) -> list[UUID]:
    """Écrit une ligne par destinataire et renvoie les identifiants à remettre.

    Les lignes déjà présentes (même `dedup_key`) ne sont pas réinsérées et ne
    figurent pas dans le retour : elles ne seront donc pas renvoyées.
    """
    if not settings.accepts(event_type):
        # Canal fermé : aucune ligne, aucun appel réseau. Le journal ne se
        # remplit pas de bruit pour une fonctionnalité que le tenant n'a pas
        # activée.
        return []

    template = templates.resolve(event_type, settings.templates)
    if not template:
        logger.warning("notifications.no_template event=%s", event_type)
        return []

    base_variables = dict(variables or {})
    base_variables.setdefault("organisation", settings.organisation_name)

    to_deliver: list[UUID] = []

    for recipient in recipients:
        normalized = normalize_phone(recipient.phone)
        message = templates.render(
            template,
            {**base_variables, "nom": recipient.name or base_variables.get("nom", ""),
             "fonction": recipient.role or ""},
        )

        if not normalized:
            # Trace explicite : sans elle, l'administrateur ne peut pas
            # distinguer « pas de numéro » de « panne du fournisseur ».
            await _insert_log(
                db,
                organisation_id=organisation_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                recipient=(recipient.phone or "")[:120] or "(vide)",
                recipient_name=recipient.name,
                recipient_role=recipient.role,
                message=message,
                status=STATUS_SKIPPED,
                provider=settings.provider,
                error_message="Numéro absent ou invalide.",
                nonce=nonce,
            )
            continue

        inserted_id = await _insert_log(
            db,
            organisation_id=organisation_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            recipient=normalized,
            recipient_name=recipient.name,
            recipient_role=recipient.role,
            message=message,
            status=STATUS_PENDING,
            provider=settings.provider,
            nonce=nonce,
        )
        if inserted_id is not None:
            to_deliver.append(inserted_id)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("notifications.queue_commit_failed event=%s", event_type)
        return []

    return to_deliver


async def _insert_log(
    db: AsyncSession,
    *,
    organisation_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    recipient: str,
    recipient_name: str,
    recipient_role: str,
    message: str,
    status: str,
    provider: str,
    error_message: str | None = None,
    nonce: str = "",
) -> UUID | None:
    """INSERT … ON CONFLICT DO NOTHING. Renvoie l'id seulement si la ligne est neuve."""
    dedup_key = build_dedup_key(
        organisation_id=organisation_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        channel=CHANNEL_WHATSAPP,
        recipient=recipient,
        nonce=nonce,
    )
    statement = (
        pg_insert(NotificationLog)
        .values(
            organisation_id=organisation_id,
            channel=CHANNEL_WHATSAPP,
            event_type=event_type,
            entity_type=entity_type or "",
            entity_id=str(entity_id or "")[:80],
            recipient=recipient[:120],
            recipient_name=(recipient_name or "")[:255],
            recipient_role=(recipient_role or "")[:120],
            message=message or "",
            status=status,
            provider=provider or "",
            error_message=error_message,
            dedup_key=dedup_key,
            created_at=_utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(NotificationLog.id)
    )
    result = await db.execute(statement)
    return result.scalar_one_or_none()


# ── Temps 2 : remise ─────────────────────────────────────────────────────────


async def deliver_pending(
    log_ids: list[UUID],
    settings: WhatsAppSettings,
    organisation_id: int | None = None,
    session_factory=None,
) -> None:
    """Envoie les lignes indiquées. Conçu pour `BackgroundTasks.add_task`.

    Ne lève jamais : toute exception est journalisée et convertie en `FAILED`.
    Une notification qui casse ne doit jamais remonter jusqu'au client HTTP,
    dont la requête métier est de toute façon déjà terminée.

    `session_factory` n'existe que pour les tests, qui doivent pouvoir viser la
    base d'essai plutôt que celle de l'application. En production le paramètre
    reste vide et `SessionLocal` est utilisée.
    """
    if not log_ids:
        return

    # Importés ici pour ne pas créer de dépendance circulaire au chargement des
    # modèles, et pour que le module reste testable sans base.
    from app.core.tenant_context import get_current_tenant_id, set_current_tenant_id

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal

    provider = get_provider(settings.provider, settings.provider_config)
    ok, reason = provider.is_configured()

    # Le contexte tenant est reposé explicitement : une tâche de fond n'hérite pas
    # de celui de la requête, et `_apply_tenant_criteria` ne pose AUCUN filtre
    # quand le contexte est vide — une lecture sans contexte traverserait donc
    # silencieusement les organisations. L'ancienne valeur est restaurée à la fin
    # car le contexte peut être partagé avec d'autres tâches de la même boucle.
    previous_tenant = get_current_tenant_id()
    if organisation_id is not None:
        set_current_tenant_id(organisation_id)

    try:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(NotificationLog).where(
                        NotificationLog.id.in_(log_ids),
                        NotificationLog.status == STATUS_PENDING,
                    )
                )
            ).scalars().all()

            for row in rows:
                if not ok:
                    await _mark(session, row.id, STATUS_FAILED, error=reason)
                    continue
                try:
                    result = await provider.send_message(to=row.recipient, text=row.message)
                except Exception as exc:  # pragma: no cover - filet de sécurité
                    logger.exception("notifications.provider_crashed provider=%s", settings.provider)
                    await _mark(session, row.id, STATUS_FAILED, error=f"{type(exc).__name__}")
                    continue

                if result.ok:
                    await _mark(
                        session,
                        row.id,
                        STATUS_SENT,
                        provider_message_id=result.provider_message_id,
                    )
                else:
                    await _mark(session, row.id, STATUS_FAILED, error=result.error)

            await session.commit()
    except Exception:  # pragma: no cover - filet de sécurité
        logger.exception("notifications.delivery_failed")
    finally:
        set_current_tenant_id(previous_tenant)


async def _mark(
    session: AsyncSession,
    log_id: UUID,
    status: str,
    *,
    provider_message_id: str | None = None,
    error: str | None = None,
) -> None:
    values: dict = {
        "status": status,
        "attempts": NotificationLog.attempts + 1,
        "error_message": (error or None),
    }
    if status == STATUS_SENT:
        values["sent_at"] = _utcnow()
        values["provider_message_id"] = provider_message_id
        values["error_message"] = None
    await session.execute(
        update(NotificationLog).where(NotificationLog.id == log_id).values(**values)
    )


# ── Point d'entrée unique pour les endpoints ─────────────────────────────────


async def notify_whatsapp(
    db: AsyncSession,
    background_tasks,
    *,
    organisation_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    recipients: Iterable[Recipient],
    variables: dict,
    settings: WhatsAppSettings,
    nonce: str = "",
    session_factory=None,
) -> int:
    """Met en file puis programme la remise. Renvoie le nombre de messages à partir.

    À appeler **après** le `commit()` de l'opération métier. Encapsulé dans un
    `try` : quoi qu'il arrive ici, l'endpoint appelant doit rendre sa réponse.
    """
    try:
        log_ids = await queue_whatsapp(
            db,
            organisation_id=organisation_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            recipients=recipients,
            variables=variables,
            settings=settings,
            nonce=nonce,
        )
    except Exception:
        logger.exception("notifications.queue_failed event=%s", event_type)
        return 0

    if not log_ids:
        return 0

    if background_tasks is not None:
        background_tasks.add_task(
            deliver_pending, log_ids, settings, organisation_id, session_factory
        )
    else:
        await deliver_pending(log_ids, settings, organisation_id, session_factory)

    return len(log_ids)
