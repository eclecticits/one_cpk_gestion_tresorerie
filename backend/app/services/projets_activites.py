"""Rattachement facultatif d'une opération à un projet ou une activité."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projet_activite import ProjetActivite


async def resoudre_projet_activite(
    db: AsyncSession,
    project_activity_id: int | None,
    tenant_id: int,
) -> int | None:
    """Vérifie que le projet existe, appartient à l'organisation et est actif.

    `None` reste `None` : le rattachement est toujours facultatif.
    """
    if project_activity_id is None:
        return None
    item = await db.scalar(
        select(ProjetActivite).where(
            ProjetActivite.id == project_activity_id,
            ProjetActivite.organisation_id == tenant_id,
            ProjetActivite.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=400, detail="Projet ou activité invalide ou inactive.")
    return item.id
