"""Politique des engagements budgétaires.

`budget_postes.montant_engage` est une **valeur dérivée** : c'est, à tout
instant, la somme des lignes des réquisitions qui engagent réellement le
budget. On ne l'incrémente jamais « au fil de l'eau » — un compteur qui monte
sans jamais redescendre est précisément ce qui laissait une réquisition rejetée
geler son montant indéfiniment. Toute transition de workflow appelle donc un
recalcul ciblé, idempotent : rejouer le calcul deux fois donne le même montant,
et un appel oublié se rattrape par la réconciliation d'ensemble.

Règles retenues :

* **Fait générateur** — l'engagement naît à la soumission à l'examen. Un
  brouillon (`NON_EXAMINE`) ne gèle rien : une saisie abandonnée ne consomme pas
  de crédit.
* **Maintien** — le paiement ne libère pas l'engagement, il le consomme. Une
  réquisition payée reste engagée : `montant_paye <= montant_engage` toujours.
* **Libération** — rejet (examen ou validation finale), suppression logique et
  retour en brouillon rendent le crédit au poste.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition

# Une réquisition engage son budget dès qu'elle est partie à l'examen, et le
# reste jusqu'au bout du circuit (approuvée, en décaissement, payée).
EXAMEN_STATUTS_ENGAGEANTS = ("EN_EXAMEN", "EXAMINE")

# Statuts qui libèrent le crédit quel que soit l'état d'examen. « Annuler » une
# demande, dans le vocabulaire métier, c'est la rejeter : les deux rejets — celui
# de l'examen (`examen_status = REJETE`, hors liste ci-dessus) et celui de la
# validation finale (`status = REJETEE`) — rendent le montant au poste.
STATUTS_NON_ENGAGEANTS = ("REJETEE",)


def requisition_engage_le_budget(req: Requisition) -> bool:
    """Version Python de `engagement_actif_clause`, pour raisonner sur un objet.

    Sert au contrôle de disponibilité quand on corrige une ligne : son montant
    actuel est déjà compté dans `montant_engage` si la pièce engage, et il faut
    le lui rendre avant de mesurer ce que la nouvelle version consomme — sinon
    la ligne se heurte à elle-même.
    """
    if getattr(req, "is_deleted", False):
        return False
    if (req.examen_status or "").upper() not in EXAMEN_STATUTS_ENGAGEANTS:
        return False
    return (req.status or "").upper() not in STATUTS_NON_ENGAGEANTS


def engagement_actif_clause() -> ColumnElement[bool]:
    """Prédicat SQL : cette réquisition gèle-t-elle du budget ?"""
    return and_(
        Requisition.is_deleted.is_(False),
        func.upper(func.coalesce(Requisition.examen_status, "")).in_(EXAMEN_STATUTS_ENGAGEANTS),
        func.upper(func.coalesce(Requisition.status, "")).notin_(STATUTS_NON_ENGAGEANTS),
    )


def _engagement_theorique_subquery() -> ColumnElement[Decimal]:
    """Somme corrélée des lignes engageantes du poste courant."""
    return (
        select(func.coalesce(func.sum(LigneRequisition.montant_total), 0))
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            LigneRequisition.budget_poste_id == BudgetPoste.id,
            LigneRequisition.organisation_id == BudgetPoste.organisation_id,
            engagement_actif_clause(),
        )
        .correlate(BudgetPoste)
        .scalar_subquery()
    )


async def resynchroniser_engagements(
    db: AsyncSession,
    *,
    tenant_id: int,
    poste_ids: list[int] | None = None,
) -> int:
    """Recalcule `montant_engage` depuis les lignes. Renvoie le nombre de postes ajustés.

    `poste_ids` restreint le recalcul aux postes concernés par la transition en
    cours ; sans lui, c'est la réconciliation complète de l'organisation.
    Ne commite pas : l'appelant reste maître de sa transaction.
    """
    if poste_ids is not None and not poste_ids:
        return 0

    # Les transitions en cours (statut, lignes ajoutées) doivent être visibles
    # du recalcul : on ne dépend pas de l'autoflush.
    await db.flush()

    theorique = _engagement_theorique_subquery()
    conditions = [
        BudgetPoste.organisation_id == tenant_id,
        BudgetPoste.is_deleted.is_(False),
        BudgetPoste.montant_engage.is_distinct_from(theorique),
    ]
    if poste_ids is not None:
        conditions.append(BudgetPoste.id.in_(poste_ids))

    result = await db.execute(
        update(BudgetPoste)
        .where(*conditions)
        .values(montant_engage=theorique)
        .execution_options(synchronize_session=False)
    )

    # L'UPDATE est massif : la session garde en mémoire des postes dont
    # `montant_engage` vient de changer sous elle. Tout ce qui relit un poste
    # après un recalcul — le contrôle de disponibilité d'une ligne corrigée,
    # par exemple — lirait la valeur d'avant et laisserait passer un
    # dépassement. On périme la seule colonne dérivée, sans requête de plus.
    if result.rowcount:
        session = db.sync_session
        for objet in list(session.identity_map.values()):
            if isinstance(objet, BudgetPoste) and objet in session:
                session.expire(objet, ["montant_engage"])

    return result.rowcount or 0


async def postes_de_requisition(db: AsyncSession, requisition_id: uuid.UUID) -> list[int]:
    """Postes budgétaires touchés par les lignes d'une réquisition."""
    res = await db.execute(
        select(LigneRequisition.budget_poste_id)
        .where(
            LigneRequisition.requisition_id == requisition_id,
            LigneRequisition.budget_poste_id.isnot(None),
        )
        .distinct()
    )
    return [pid for pid in res.scalars().all() if pid is not None]


async def resynchroniser_engagement_requisition(
    db: AsyncSession, requisition: Requisition
) -> int:
    """À appeler après toute transition qui change l'état engageant d'une réquisition.

    Les lignes doivent être visibles de la transaction : `db.flush()` d'abord si
    elles viennent d'être ajoutées.
    """
    poste_ids = await postes_de_requisition(db, requisition.id)
    return await resynchroniser_engagements(
        db, tenant_id=requisition.organisation_id, poste_ids=poste_ids
    )


async def resynchroniser_engagement_requisitions(
    db: AsyncSession, requisitions: list[Requisition]
) -> int:
    """Variante pour les actions de dossier, qui déplacent plusieurs réquisitions."""
    ajustes = 0
    par_tenant: dict[int, set[int]] = {}
    for req in requisitions:
        poste_ids = await postes_de_requisition(db, req.id)
        if poste_ids:
            par_tenant.setdefault(req.organisation_id, set()).update(poste_ids)
    for tenant_id, poste_ids in par_tenant.items():
        ajustes += await resynchroniser_engagements(
            db, tenant_id=tenant_id, poste_ids=sorted(poste_ids)
        )
    return ajustes


async def ecarts_engagement(db: AsyncSession, *, tenant_id: int) -> list[dict]:
    """Postes dont l'engagement stocké diverge du calcul. Diagnostic, sans écriture."""
    theorique = _engagement_theorique_subquery()
    res = await db.execute(
        select(
            BudgetPoste.id,
            BudgetPoste.exercice_id,
            BudgetPoste.code,
            BudgetPoste.libelle,
            BudgetPoste.montant_engage,
            theorique.label("montant_engage_theorique"),
        )
        .where(
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.montant_engage.is_distinct_from(theorique),
        )
        .order_by(BudgetPoste.code)
    )
    return [
        {
            "budget_poste_id": row.id,
            "exercice_id": row.exercice_id,
            "code": row.code,
            "libelle": row.libelle,
            "montant_engage_stocke": Decimal(row.montant_engage or 0),
            "montant_engage_theorique": Decimal(row.montant_engage_theorique or 0),
            "ecart": Decimal(row.montant_engage or 0) - Decimal(row.montant_engage_theorique or 0),
        }
        for row in res
    ]
