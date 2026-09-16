"""Journal d'audit du module Tableau.

Le module consigne lui-même ce qui touche à sa base : correction d'un dossier,
décision de commission, analyse relancée, question posée à l'assistant. Les
valeurs susceptibles de porter du texte libre ou un secret ne sont jamais
recopiées dans le journal.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import TableauAuditLog


# Clés dont la valeur n'a pas sa place dans un journal : texte libre saisi par
# l'utilisateur, contenu de document, jeton d'accès.
CLES_SENSIBLES = {
    "access_token",
    "api_key",
    "body",
    "content",
    "contenu",
    "instructions",
    "message",
    "observations",
    "prompt",
    "raw_data",
    "raw_response",
    "refresh_token",
    "response",
    "secret",
    "token",
}


def _nettoyer(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        return {cle: _nettoyer(item) for cle, item in valeur.items() if cle not in CLES_SENSIBLES}
    if isinstance(valeur, (list, tuple, set)):
        return [_nettoyer(item) for item in valeur]
    if isinstance(valeur, (datetime, date, UUID)):
        return str(valeur)
    return valeur


def sanitize_tableau_metadata(metadata_json: dict | None) -> dict | None:
    if not metadata_json:
        return None
    return _nettoyer(metadata_json) or None


async def record_tableau_audit(
    db: AsyncSession,
    *,
    organisation_id: int,
    user_id: UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    status: str = "success",
    metadata_json: dict | None = None,
) -> TableauAuditLog:
    log = TableauAuditLog(
        organisation_id=organisation_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        status=status,
        metadata_json=sanitize_tableau_metadata(metadata_json),
    )
    db.add(log)
    await db.flush()
    return log
