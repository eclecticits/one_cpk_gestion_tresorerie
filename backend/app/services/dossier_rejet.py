"""Décision du service après le rejet d'un dossier à l'examen.

Un dossier rejeté laisse 48 h au service pour choisir :
- le rouvrir (retour en brouillon) pour le corriger puis le resoumettre ;
- accepter le rejet, qui devient définitif.
Sans décision à l'échéance, le rejet est accepté d'office. Un dossier rouvert
mais non resoumis dans le délai est accepté de même : passé 48 h, le même
dossier ne repart plus à l'examen.

L'expiration est constatée à la lecture (pas de tâche planifiée) : chaque
accès aux dossiers clôt d'abord ceux dont le délai est échu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dossier_requisition import DossierRequisition
from app.models.requisition import Requisition
from app.services.budget_engagement import resynchroniser_engagement_requisitions

DELAI_DECISION_REJET = timedelta(hours=48)
STATUT_REJET_ACCEPTE = "REJET_ACCEPTE"
# Statuts dans lesquels le délai court : rejeté sans décision, ou rouvert.
STATUTS_EN_DELAI = ("REJETE", "BROUILLON")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def echeance_rejet(dossier: DossierRequisition) -> datetime | None:
    if dossier.rejete_le is None:
        return None
    return _aware(dossier.rejete_le) + DELAI_DECISION_REJET


def delai_rejet_echu(dossier: DossierRequisition, now: datetime | None = None) -> bool:
    echeance = echeance_rejet(dossier)
    return (
        echeance is not None
        and (dossier.status or "").upper() in STATUTS_EN_DELAI
        and (now or _utcnow()) >= echeance
    )


async def accepter_rejet(
    db: AsyncSession,
    dossier: DossierRequisition,
    requisitions: list[Requisition],
    *,
    par: uuid.UUID | None,
    now: datetime | None = None,
) -> None:
    """Rend le rejet définitif : le dossier et ses pièces sont clos."""
    now = now or _utcnow()
    dossier.status = STATUT_REJET_ACCEPTE
    dossier.rejet_accepte_le = now
    dossier.rejet_accepte_par = par
    dossier.updated_at = now
    for req in requisitions:
        req.status = "REJETEE"
        req.examen_status = "REJETE"
        if not req.examen_commentaire:
            req.examen_commentaire = dossier.commentaires_examen
        req.updated_at = now
    # Rejet : aucun crédit ne reste engagé.
    await resynchroniser_engagement_requisitions(db, list(requisitions))


async def _requisitions_du_dossier(db: AsyncSession, dossier_id: uuid.UUID) -> list[Requisition]:
    res = await db.execute(select(Requisition).where(Requisition.dossier_id == dossier_id))
    return list(res.scalars().all())


async def cloturer_si_echu(db: AsyncSession, dossier: DossierRequisition) -> bool:
    """Accepte d'office le rejet de ce dossier si son délai est échu (sans commit)."""
    if not delai_rejet_echu(dossier):
        return False
    await accepter_rejet(db, dossier, await _requisitions_du_dossier(db, dossier.id), par=None)
    return True


async def cloturer_rejets_echus(db: AsyncSession, tenant_id: int) -> int:
    """Accepte d'office les rejets échus de l'organisation, et valide."""
    limite = _utcnow() - DELAI_DECISION_REJET
    res = await db.execute(
        select(DossierRequisition).where(
            DossierRequisition.organisation_id == tenant_id,
            DossierRequisition.rejete_le.is_not(None),
            DossierRequisition.rejete_le <= limite,
            DossierRequisition.status.in_(STATUTS_EN_DELAI),
        )
    )
    dossiers = list(res.scalars().all())
    for dossier in dossiers:
        await accepter_rejet(db, dossier, await _requisitions_du_dossier(db, dossier.id), par=None)
    if dossiers:
        await db.commit()
    return len(dossiers)
