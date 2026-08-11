"""Identité de l'organisation émettrice d'un document exporté.

Règle : aucun document ne doit sortir de l'application sans identifier le tenant
qui l'émet. Ce module est le point unique où ce libellé est résolu, pour que les
exports Excel et les PDF désignent toujours le même émetteur.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings


async def tenant_display_name(db: AsyncSession, organisation_id: int) -> str:
    """Nom affichable de l'organisation, à porter sur tout document exporté.

    Priorité au libellé d'impression (celui qui figure déjà sur les PDF), avec
    repli sur le nom de l'organisation. Ne renvoie jamais de chaîne vide : un
    document sans émetteur identifiable ne doit pas pouvoir être produit.
    """
    res = await db.execute(
        select(PrintSettings.organization_name)
        .where(PrintSettings.organisation_id == organisation_id)
        .limit(1)
    )
    label = (res.scalar_one_or_none() or "").strip()
    if label:
        return label

    res = await db.execute(
        select(Organisation.nom).where(Organisation.id == organisation_id).limit(1)
    )
    return (res.scalar_one_or_none() or "").strip() or f"Organisation #{organisation_id}"
