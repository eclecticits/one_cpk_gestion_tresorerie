"""Résolution des destinataires du Bureau.

On réutilise `commission_members` plutôt que de créer un second registre de
personnes : la table porte déjà le nom, l'e-mail, la qualité de signataire, et
son référentiel `service_member_functions` sème par tenant « Président(e),
Vice-président(e), Rapporteur, Rapporteur adjoint, Trésorier, Trésorier(e)
adjoint, Secrétaire exécutif, Assistant(e), Autre ». Deux colonnes lui ont été
ajoutées — `telephone` et `notify_whatsapp` — plutôt qu'une table de liaison :
avec deux registres de personnes, la question n'est pas de savoir s'ils vont
diverger, mais quand.

Le filtre tenant est appliqué explicitement par jointure sur `Service`, sans
compter sur le filtre implicite de session : ces fonctions peuvent être appelées
depuis un contexte où il n'est pas posé, et il ne filtre alors rien du tout.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.commission_member import CommissionMember
from app.models.service import Service

from .phone import normalize_phone
from .service import Recipient

logger = logging.getLogger("onec_cpk_api.notifications.recipients")


def _get(obj: object, name: str, default=None):
    value = getattr(obj, name, None)
    return default if value is None else value


def _function_label(member: CommissionMember) -> str:
    """Fonction affichée : le libellé du référentiel, sinon le titre libre, sinon le rôle."""
    function = getattr(member, "function", None)
    label = getattr(function, "label", "") if function is not None else ""
    if label:
        return str(label)
    custom = _get(member, "custom_title", "")
    if custom:
        return str(custom)
    role = getattr(member, "role_type", None)
    return getattr(role, "value", "") or ""


async def load_bureau_members(
    db: AsyncSession,
    organisation_id: int,
    *,
    only_opted_in: bool = True,
) -> list[CommissionMember]:
    """Membres du Bureau d'une organisation, triés par fonction puis par nom."""
    statement = (
        select(CommissionMember)
        .join(Service, Service.id == CommissionMember.service_id)
        .where(Service.organisation_id == organisation_id)
        .options(selectinload(CommissionMember.function))
    )
    if only_opted_in:
        # `is True` ne s'écrit pas en SQL : on compare la colonne à True.
        statement = statement.where(CommissionMember.notify_whatsapp == True)  # noqa: E712

    members = (await db.execute(statement)).scalars().all()
    return sorted(members, key=lambda m: (_function_label(m), m.full_name or ""))


async def resolve_outflow_recipients(
    db: AsyncSession,
    organisation_id: int | None,
    *,
    fallback_numbers: str | None = None,
) -> list[Recipient]:
    """Destinataires d'une notification de sortie de fonds.

    Deux sources, dans cet ordre :

    1. Les membres du Bureau ayant coché « recevoir les sorties » et portant un
       numéro exploitable — la source normale, nominative et traçable.
    2. À défaut seulement, la liste libre `system_settings.whatsapp_agents`, qui
       est le mécanisme actuel. Ce repli existe pour qu'aucun tenant ne cesse
       d'être notifié le jour du déploiement, avant d'avoir renseigné les
       téléphones du Bureau. Il n'a ni nom ni fonction : le journal le montrera,
       et c'est l'incitation à passer à la source nominative.
    """
    if organisation_id is None:
        return []

    recipients: list[Recipient] = []
    seen: set[str] = set()

    try:
        for member in await load_bureau_members(db, organisation_id, only_opted_in=True):
            normalized = normalize_phone(_get(member, "telephone", ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            recipients.append(
                Recipient(
                    phone=normalized,
                    name=member.full_name or "",
                    role=_function_label(member),
                )
            )
    except Exception:
        # Colonne absente (migration non appliquée) ou souci de lecture : on ne
        # perd pas la notification, on bascule sur le repli.
        logger.exception("notifications.bureau_lookup_failed org=%s", organisation_id)

    if recipients:
        return recipients

    from .phone import normalize_phone_list

    for number in normalize_phone_list(fallback_numbers):
        if number in seen:
            continue
        seen.add(number)
        recipients.append(Recipient(phone=number, name="", role="Liste des agents"))

    return recipients


def resolve_client_recipient(
    *,
    expert=None,
    client=None,
) -> Recipient | None:
    """Destinataire d'une notification de paiement.

    Même règle que l'e-mail : l'expert-comptable prime, sinon le client. La
    différence tenue avec l'existant est que le client non-expert n'est plus
    ignoré — le bloc WhatsApp actuel ne regarde que `expert.telephone`.
    """
    for source in (expert, client):
        if source is None:
            continue
        normalized = normalize_phone(_get(source, "telephone", ""))
        if not normalized:
            continue
        name = (
            _get(source, "nom_complet", "")
            or _get(source, "nom_denomination", "")
            or " ".join(
                part for part in [_get(source, "prenom", ""), _get(source, "nom", "")] if part
            ).strip()
            or _get(source, "raison_sociale", "")
            or _get(source, "denomination", "")
            or ""
        )
        return Recipient(phone=normalized, name=str(name).strip(), role="")
    return None
