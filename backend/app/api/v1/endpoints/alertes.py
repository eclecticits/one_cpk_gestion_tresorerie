"""Ce qui attend une personne, en un appel bref et répété.

Cette route est interrogée en boucle par l'interface : elle rend un COMPTE et
un HORODATAGE, jamais une liste. Le client n'a besoin que de savoir si quelque
chose est arrivé depuis son dernier regard — lui envoyer les dossiers eux-mêmes
coûterait cher pour une information d'une ligne.

Un remboursement de transport n'a pas d'état propre : il est rattaché à une
réquisition et suit la sienne. Le compte porte donc sur les réquisitions, en
distinguant celles qui portent un remboursement — c'est plus vrai que
d'inventer un second circuit d'attente qui n'existe pas dans les données.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user
from app.db.session import get_db
from app.models.remboursement_transport import RemboursementTransport
from app.models.requisition import Requisition
from app.models.user import User
from app.services.service_access import user_has_permission

router = APIRouter()

#: Les états dans lesquels une réquisition attend le geste d'un validateur.
#: `AUTORISEE` et `APPROUVEE` en sont exclus : elles ont déjà été validées et
#: attendent la caisse, pas le validateur. Les compter ferait sonner l'alerte
#: pour du travail qui n'est pas le sien.
STATUTS_EN_ATTENTE = ("EN_ATTENTE", "EN_ATTENTE_COMMISSION", "PENDING_VALIDATION_IMPORT")

#: Les droits qui font d'un compte un validateur. Le premier est le menu, les
#: deux autres les gestes eux-mêmes : un profil peut porter l'un sans l'autre.
DROITS_DE_VALIDATION = ("menu_validation", "can_verify_technical", "can_validate_final")


@router.get("/a-valider")
async def resume_a_valider(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Combien de dossiers attendent cette personne, et depuis quand.

    Rend des zéros — et non une erreur — à qui ne valide pas : l'interface
    interroge cette route pour tout le monde, et refuser bruyamment obligerait
    chaque écran à savoir d'avance qui a le droit de demander.
    """
    vide = {"nb": 0, "dont_transport": 0, "dernier": None, "peut_valider": False}
    for droit in DROITS_DE_VALIDATION:
        if await user_has_permission(db, user, droit):
            break
    else:
        return vide

    attente = (
        Requisition.organisation_id == tenant_id,
        Requisition.status.in_(STATUTS_EN_ATTENTE),
        Requisition.is_deleted.is_(False),
    )
    nb, dernier = (await db.execute(
        select(func.count(Requisition.id), func.max(Requisition.created_at)).where(*attente)
    )).one()
    dont_transport = await db.scalar(
        select(func.count(func.distinct(Requisition.id)))
        .join(RemboursementTransport, RemboursementTransport.requisition_id == Requisition.id)
        .where(*attente)
    )
    return {
        "nb": int(nb or 0),
        "dont_transport": int(dont_transport or 0),
        # L'interface compare cet horodatage à celui qu'elle a retenu : c'est ce
        # qui distingue « il y a du travail » de « il vient d'en arriver ».
        "dernier": dernier.isoformat() if dernier else None,
        "peut_valider": True,
    }
