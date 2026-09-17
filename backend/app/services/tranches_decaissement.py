"""Rang et cumul des tranches d'une réquisition payée en plusieurs fois.

Une réquisition à décaissement progressif est payée tranche par tranche ;
chaque tranche est une sortie de fonds ordinaire. Lue seule, une ligne
d'export ne dit rien de ce qui a déjà été payé ni de ce qu'il reste à payer :
deux tranches du même dossier se présentent comme deux paiements identiques.
Ce module donne à chaque sortie sa place dans la suite des paiements.

La règle de cumul est celle qui fait passer la réquisition de EN_DECAISSEMENT
à PAYEE (`sorties_fonds.py`, enregistrement d'une sortie) : somme des
`montant_paye` des sorties VALIDES, comparée à `montant_total`. Une sortie
annulée n'a pas de rang — elle n'a rien payé.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ordre_decaissement import OrdreDecaissement
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds


@dataclass(frozen=True)
class TrancheDecaissement:
    #: Rang de la sortie parmi les paiements valides du dossier, dans l'ordre
    #: où ils ont été faits (1 = première tranche).
    numero: int
    #: Tranches payées à ce jour sur le dossier.
    nombre: int
    #: Payé sur le dossier jusqu'à cette tranche incluse.
    cumul_paye: Decimal
    montant_total: Decimal
    #: Ce qu'il restait à payer une fois cette tranche réglée.
    reste: Decimal
    devise: str
    #: Objet de la tranche : le motif de l'ordre de décaissement qui l'a
    #: autorisée. L'objet de la réquisition couvre le dossier entier et ne dit
    #: pas ce que cette tranche-ci paie ; nulle part ailleurs il ne se lit.
    objet: str | None = None


async def tranches_par_sortie(
    db: AsyncSession,
    organisation_id: int,
    requisition_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, TrancheDecaissement]:
    """Tranche de chaque sortie valide des réquisitions données.

    Seules les réquisitions payées en plusieurs fois sont concernées : un
    dossier à décaissement progressif, ou tout dossier ayant reçu plus d'un
    paiement. Un paiement unique et complet n'est pas une « tranche 1 sur 1 ».
    """
    ids = {rid for rid in requisition_ids if rid}
    if not ids:
        return {}

    rows = (
        await db.execute(
            select(
                SortieFonds.id,
                SortieFonds.requisition_id,
                SortieFonds.montant_paye,
                Requisition.montant_total,
                Requisition.devise,
                Requisition.decaissement_progressif,
            )
            .join(Requisition, SortieFonds.requisition_id == Requisition.id)
            .where(
                SortieFonds.organisation_id == organisation_id,
                SortieFonds.requisition_id.in_(ids),
                (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            )
            .order_by(
                SortieFonds.requisition_id,
                SortieFonds.date_paiement.asc().nulls_last(),
                SortieFonds.created_at.asc(),
            )
        )
    ).all()

    # Objet de chaque tranche : le motif de l'ordre qui l'a autorisée. Le lien
    # est porté par l'ordre (`sortie_fonds_id`), posé au paiement.
    objets: dict[uuid.UUID, str | None] = {}
    if rows:
        objets = dict(
            (
                await db.execute(
                    select(OrdreDecaissement.sortie_fonds_id, OrdreDecaissement.motif).where(
                        OrdreDecaissement.organisation_id == organisation_id,
                        OrdreDecaissement.sortie_fonds_id.in_([row.id for row in rows]),
                    )
                )
            ).all()
        )

    par_requisition: dict[uuid.UUID, list] = {}
    for row in rows:
        par_requisition.setdefault(row.requisition_id, []).append(row)

    tranches: dict[uuid.UUID, TrancheDecaissement] = {}
    for paiements in par_requisition.values():
        if not paiements[0].decaissement_progressif and len(paiements) < 2:
            continue
        total = Decimal(paiements[0].montant_total or 0)
        devise = paiements[0].devise or "USD"
        cumul = Decimal("0")
        for rang, paiement in enumerate(paiements, start=1):
            cumul += Decimal(paiement.montant_paye or 0)
            tranches[paiement.id] = TrancheDecaissement(
                numero=rang,
                nombre=len(paiements),
                cumul_paye=cumul,
                montant_total=total,
                reste=max(total - cumul, Decimal("0")),
                devise=devise,
                objet=(objets.get(paiement.id) or "").strip() or None,
            )
    return tranches


def _montant(valeur: Decimal) -> str:
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",")


def libelle_tranche(tranche: TrancheDecaissement) -> str:
    """« Tranche 2 (Achat de carburant) — payé 650,00 / 2 470,00 USD, reste 1 820,00 ».

    L'objet vient avec le rang : les montants disent où en est le dossier,
    l'objet dit ce que cette tranche-ci a payé, et il ne se lit nulle part
    ailleurs.
    """
    rang = f"Tranche {tranche.numero}"
    if tranche.objet:
        rang = f"{rang} ({tranche.objet})"
    base = (
        f"{rang} — payé {_montant(tranche.cumul_paye)}"
        f" / {_montant(tranche.montant_total)} {tranche.devise}"
    )
    if tranche.reste > 0:
        return f"{base}, reste {_montant(tranche.reste)}"
    return f"{base}, soldé"
