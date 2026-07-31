"""Mapping par défaut — débloque la génération automatique sans écran de
paramétrage complet (décision actée : bridge pragmatique, pas la solution
finale).

Principe : chaque poste budgétaire / compte bancaire non encore mappé
individuellement reçoit un compte comptable GÉNÉRIQUE selon son type
(charge/produit) ou sa nature (banque/caisse) — ``605 Autres achats`` et
``758 Produits divers`` pour les postes, ``512 Banques`` / ``571 Caisse
siège`` pour la trésorerie. Ces quatre comptes existent dans les deux plans
de démarrage (SYSCOHADA et SYSCEBNL).

⚠️ Ceci PERD la granularité analytique (toutes les dépenses non affinées
atterrissent sur un seul compte) : c'est un point de départ à affiner poste
par poste via un vrai mapping (Lot 2 avancé / écran de paramétrage), pas une
solution comptable définitive. Idempotent : ne touche jamais un mapping déjà
configuré individuellement.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.compte_bancaire import CompteBancaire
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaReferentiel,
    ComptaSociete,
)

COMPTE_CHARGE_DEFAUT_NUMERO = "605"   # Autres achats
COMPTE_PRODUIT_DEFAUT_NUMERO = "758"  # Produits divers
COMPTE_BANQUE_DEFAUT_NUMERO = "512"   # Banques
COMPTE_CAISSE_DEFAUT_NUMERO = "571"   # Caisse siège


async def _get_compte_by_numero(db: AsyncSession, referentiel_id: int, numero: str) -> ComptaCompte:
    res = await db.execute(
        select(ComptaCompte).where(ComptaCompte.referentiel_id == referentiel_id, ComptaCompte.numero == numero)
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise ValueError(
            f"Compte générique {numero} introuvable dans le référentiel #{referentiel_id} — "
            "le plan de démarrage a-t-il été altéré ?"
        )
    return compte


async def generer_mappings_par_defaut(db: AsyncSession, *, organisation_id: int) -> dict:
    """Mappe tous les postes budgétaires et comptes bancaires non encore
    mappés vers des comptes génériques. Retourne un résumé (compteurs).
    """
    societe_res = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == organisation_id, ComptaSociete.is_default.is_(True)
        )
    )
    societe = societe_res.scalar_one_or_none()
    if societe is None:
        raise ValueError("Comptabilité non activée pour cette organisation.")

    referentiel_res = await db.execute(
        select(ComptaReferentiel).where(
            ComptaReferentiel.organisation_id == organisation_id, ComptaReferentiel.is_default.is_(True)
        )
    )
    referentiel = referentiel_res.scalar_one_or_none()
    if referentiel is None:
        raise ValueError("Aucun référentiel comptable par défaut pour cette organisation.")

    compte_charge = await _get_compte_by_numero(db, referentiel.id, COMPTE_CHARGE_DEFAUT_NUMERO)
    compte_produit = await _get_compte_by_numero(db, referentiel.id, COMPTE_PRODUIT_DEFAUT_NUMERO)
    compte_banque = await _get_compte_by_numero(db, referentiel.id, COMPTE_BANQUE_DEFAUT_NUMERO)
    compte_caisse = await _get_compte_by_numero(db, referentiel.id, COMPTE_CAISSE_DEFAUT_NUMERO)

    if societe.compte_caisse_defaut_id is None:
        societe.compte_caisse_defaut_id = compte_caisse.id

    # ── Postes budgétaires ───────────────────────────────────────────────────
    deja_mappes_res = await db.execute(
        select(ComptaMappingPosteBudgetaire.budget_poste_id).where(
            ComptaMappingPosteBudgetaire.organisation_id == organisation_id
        )
    )
    postes_deja_mappes = {row for row, in deja_mappes_res.all()}

    postes_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.organisation_id == organisation_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    nb_postes_mappes = 0
    for poste in postes_res.scalars().all():
        if poste.id in postes_deja_mappes:
            continue
        compte_cible = compte_produit if (poste.type or "").upper() == "RECETTE" else compte_charge
        db.add(
            ComptaMappingPosteBudgetaire(
                organisation_id=organisation_id, budget_poste_id=poste.id, compte_id=compte_cible.id,
            )
        )
        nb_postes_mappes += 1

    # ── Comptes bancaires ────────────────────────────────────────────────────
    deja_mappes_cb_res = await db.execute(
        select(ComptaMappingCompteBancaire.compte_bancaire_id).where(
            ComptaMappingCompteBancaire.organisation_id == organisation_id
        )
    )
    comptes_bancaires_deja_mappes = {row for row, in deja_mappes_cb_res.all()}

    comptes_bancaires_res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.organisation_id == organisation_id, CompteBancaire.is_active.is_(True),
        )
    )
    nb_comptes_bancaires_mappes = 0
    for compte_bancaire in comptes_bancaires_res.scalars().all():
        if compte_bancaire.id in comptes_bancaires_deja_mappes:
            continue
        compte_cible = compte_banque if (compte_bancaire.account_type or "").upper() == "BANK" else compte_caisse
        db.add(
            ComptaMappingCompteBancaire(
                organisation_id=organisation_id, compte_bancaire_id=compte_bancaire.id, compte_id=compte_cible.id,
            )
        )
        nb_comptes_bancaires_mappes += 1

    await db.flush()

    return {
        "compte_caisse_defaut_id": societe.compte_caisse_defaut_id,
        "postes_mappes": nb_postes_mappes,
        "comptes_bancaires_mappes": nb_comptes_bancaires_mappes,
    }
