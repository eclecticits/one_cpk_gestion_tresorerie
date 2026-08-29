"""Ouvrir une session hors HTTP sans jamais perdre le cloisonnement.

C'EST LE RISQUE NUMÉRO UN DE TOUTE LA MIGRATION, avant toute considération de
performance. `app/db/session.py` applique les critères multi-tenant ainsi :

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return          # ← aucun filtre appliqué

En HTTP, `deps.py` pose toujours le contexte : l'absence est impossible. Hors
HTTP, un oubli ne lève rien — il produit des requêtes NON FILTRÉES. Un export
généré sans contexte contiendrait les données de toutes les organisations,
silencieusement, dans un fichier téléchargeable.

D'où ce module : hors HTTP, l'absence de contexte doit devenir une erreur
bruyante, pas un repli. `session_tenant()` refuse de s'ouvrir sans organisation,
et `session_technique()` est le seul chemin autorisé pour une session non
filtrée — nommé pour qu'on ne l'écrive pas par distraction, et restreint à la
lecture d'une ligne par clé primaire (le job lui-même, dont on ne connaît pas
encore l'organisation).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_current_tenant_id, set_current_tenant_id
from app.db.session import SessionLocal


class ContexteTenantManquant(RuntimeError):
    """Levée quand un traitement hors HTTP tente de lire sans organisation.

    Une exception, et non un repli sur « toutes les organisations » : le repli
    est exactement le comportement qui produirait une fuite silencieuse.
    """


@asynccontextmanager
async def session_tenant(tenant_id: int | None) -> AsyncIterator[AsyncSession]:
    """Session filtrée sur `tenant_id`, qui refuse de s'ouvrir sans lui.

    Le contexte précédent est restauré à la sortie, y compris en cas d'erreur :
    un worker traite les jobs les uns après les autres dans la même tâche
    asyncio, et un contexte qui déborde d'un job sur le suivant serait une fuite
    d'un tenant vers un autre.
    """
    if tenant_id is None:
        raise ContexteTenantManquant(
            "Session hors HTTP demandée sans organisation : refusé. "
            "Sans contexte tenant, le listener de app/db/session.py n'applique "
            "AUCUN filtre et la requête verrait toutes les organisations."
        )

    precedent = get_current_tenant_id()
    set_current_tenant_id(tenant_id)
    try:
        async with SessionLocal() as session:
            # Vérification de cohérence après ouverture : si le contexte n'est
            # pas celui qu'on vient de poser, quelque chose l'a écrasé entre
            # temps et il ne faut surtout pas continuer.
            actuel = get_current_tenant_id()
            if actuel != tenant_id:
                raise ContexteTenantManquant(
                    f"Contexte tenant incohérent : attendu {tenant_id}, trouvé {actuel}."
                )
            yield session
    finally:
        set_current_tenant_id(precedent)


@asynccontextmanager
async def session_technique() -> AsyncIterator[AsyncSession]:
    """Session NON filtrée, réservée à la lecture d'une ligne par clé primaire.

    Un seul usage légitime : charger la ligne `export_jobs` dont on ne connaît
    pas encore l'organisation — c'est elle qui la porte. La lecture se fait par
    identifiant public (UUID), qui n'est pas devinable et ne permet pas
    d'énumérer les jobs d'autrui.

    `skip_tenant_scope` est posé explicitement plutôt que laissé au hasard de
    l'absence de contexte : la trace dans le code dit que c'est voulu, et une
    relecture n'a pas à deviner si l'auteur y a pensé.
    """
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True
        yield session
