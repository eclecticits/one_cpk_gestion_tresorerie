"""Changement du canal de paiement d'une réquisition validée et non payée.

Le canal (caisse ou banque, et le compte) se décide à la rédaction, mais il
arrive qu'on apprenne après la validation qu'il faut payer autrement : la
caisse n'a pas les fonds, le bénéficiaire veut un virement. La pièce est alors
verrouillée — lignes et champs sensibles gelés en base — et la rejeter pour la
refaire relançait tout le circuit.

Ce service est la seule porte, et elle est étroite :
  - seuls le mode et le compte bougent, sur la pièce et sur toutes ses lignes ;
  - jamais après un paiement : dès qu'une sortie de fonds ou un ordre de
    décaissement existe, ou que la pièce est en décaissement ou payée, le canal
    est celui par lequel l'argent est sorti, et il le reste ;
  - les déclencheurs ne laissent passer l'écriture que sous le drapeau de
    session `onec.changement_canal` (cf. migration 20261008_changement_canal).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compte_bancaire import CompteBancaire
from app.models.ligne_requisition import LigneRequisition
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.services.historical_snapshots import model_snapshot
from app.services.reglement import MODE_PAIEMENT_MIXTE, MODES_PAIEMENT, normaliser_mode, resoudre_compte_bancaire

# L'argent est sorti, ou sort : le canal est un fait, plus une intention.
STATUTS_PAYES = {"PAYEE", "EN_DECAISSEMENT"}
# Une pièce close sans paiement n'a plus de canal à corriger.
STATUTS_CLOS = {"REJETEE", "ANNULEE"}


async def verifier_changement_canal_possible(db: AsyncSession, req: Requisition) -> None:
    statut = (req.status or "").upper()
    if statut in STATUTS_PAYES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Réquisition déjà payée ou en cours de paiement : le canal de paiement ne change plus.",
        )
    if statut in STATUTS_CLOS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Réquisition {statut.lower()} : aucun canal à modifier.",
        )

    sorties = await db.scalar(
        select(func.count())
        .select_from(SortieFonds)
        .where(SortieFonds.requisition_id == req.id, func.upper(SortieFonds.statut) != "ANNULEE")
    )
    if sorties:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Une sortie de fonds existe déjà pour cette réquisition : le canal de paiement ne change plus.",
        )

    # Un ordre de décaissement porte son propre canal, fixé à l'autorisation :
    # changer la pièce sous lui les désaccorderait.
    ordres = await db.scalar(
        select(func.count())
        .select_from(OrdreDecaissement)
        .where(OrdreDecaissement.requisition_id == req.id, func.upper(OrdreDecaissement.statut) != "ANNULE")
    )
    if ordres:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un ordre de décaissement est déjà émis : annulez-le avant de changer le canal de paiement.",
        )


async def changer_canal_requisition(
    db: AsyncSession,
    *,
    requisition: Requisition,
    mode_paiement: str,
    compte_bancaire_id: int | None,
    tenant_id: int,
) -> dict[str, Any]:
    """Aligne la pièce et toutes ses lignes sur un seul canal. Renvoie l'avant/après."""
    mode = normaliser_mode(mode_paiement)
    if mode == MODE_PAIEMENT_MIXTE or mode not in MODES_PAIEMENT:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mode de paiement invalide")

    await verifier_changement_canal_possible(db, requisition)
    compte_id = await resoudre_compte_bancaire(
        compte_bancaire_id, mode_paiement=mode, tenant_id=tenant_id, db=db
    )

    lignes = (
        await db.execute(
            select(LigneRequisition)
            .where(LigneRequisition.requisition_id == requisition.id)
            .with_for_update()
        )
    ).scalars().all()

    avant = {
        "mode_paiement": requisition.mode_paiement,
        "compte_bancaire_id": requisition.compte_bancaire_id,
        "lignes": sorted(
            {f"{normaliser_mode(l.mode_paiement)}:{l.compte_bancaire_id or ''}" for l in lignes}
        ),
    }
    if (
        normaliser_mode(requisition.mode_paiement) == mode
        and requisition.compte_bancaire_id == compte_id
        and all(normaliser_mode(l.mode_paiement) == mode and l.compte_bancaire_id == compte_id for l in lignes)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La réquisition est déjà réglée par ce canal.",
        )

    # Ne vaut que pour cette transaction ; les déclencheurs ne l'honorent que si
    # seuls le mode et le compte changent, et jamais sur une pièce payée.
    await db.execute(text("SET LOCAL onec.changement_canal = 'on'"))

    for ligne in lignes:
        ligne.mode_paiement = mode
        ligne.compte_bancaire_id = compte_id
    await db.flush()

    requisition.mode_paiement = mode
    requisition.compte_bancaire_id = compte_id
    # L'empreinte du compte suit : une pièce réimprimée doit montrer le compte
    # sur lequel elle sera payée, pas celui qu'on a abandonné.
    compte = None
    if compte_id is not None:
        compte = (
            await db.execute(
                select(CompteBancaire).where(
                    CompteBancaire.id == compte_id, CompteBancaire.organisation_id == tenant_id
                )
            )
        ).scalar_one_or_none()
    requisition.bank_account_snapshot = model_snapshot(
        compte, ["id", "intitule", "numero_compte", "devise", "account_type"]
    )
    await db.flush()

    return {
        "avant": avant,
        "apres": {"mode_paiement": mode, "compte_bancaire_id": compte_id},
        "lignes_alignees": len(lignes),
    }
