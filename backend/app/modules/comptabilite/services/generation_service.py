"""Moteur de génération automatique d'écritures (Lot 2).

⚠️ Pas encore branché sur les endpoints métier réels (`encaissements`,
`sorties_fonds`) — décision délibérée : la résolution de compte échoue de
façon bloquante (décision actée) si aucun mapping n'existe, et aucun mapping
n'est encore configuré pour les organisations existantes. Brancher ces
fonctions sur les endpoints de création casserait la saisie de trésorerie en
production tant que le paramétrage (`ComptaMappingPosteBudgetaire`,
`ComptaMappingCompteBancaire`) n'est pas rempli pour les postes/comptes déjà
en usage. Le branchement doit être une décision explicite et accompagnée
d'une vérification de couverture des mappings.

Principes (cf. dossier d'architecture §4) :
- Génération dans la MÊME transaction que l'opération métier (C3) — ces
  fonctions ne committent jamais elles-mêmes, l'appelant le fait.
- Idempotence garantie en base (contrainte unique sur l'origine) — un rejeu
  ne peut pas créer de doublon ; on le détecte ici en amont pour renvoyer
  l'écriture existante plutôt que de heurter la contrainte.
- Aucun compte codé en dur : tout compte est résolu via les tables de
  mapping ; un mapping absent est un échec bloquant (décision actée),
  jamais un compte d'attente silencieux.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaSociete,
)


async def est_comptabilite_activee(db: AsyncSession, organisation_id: int) -> bool:
    """Indique si l'organisation a activé la comptabilité (société par défaut
    provisionnée). Utilisé par les endpoints métier pour décider s'il faut
    tenter la génération automatique — les organisations qui n'ont pas
    activé le module ne doivent jamais voir leur saisie de trésorerie
    bloquée par ce moteur."""
    res = await db.execute(
        select(ComptaSociete.id).where(
            ComptaSociete.organisation_id == organisation_id, ComptaSociete.is_default.is_(True)
        )
    )
    return res.scalar_one_or_none() is not None


async def _get_default_societe(db: AsyncSession, organisation_id: int) -> ComptaSociete:
    res = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == organisation_id, ComptaSociete.is_default.is_(True)
        )
    )
    societe = res.scalar_one_or_none()
    if societe is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comptabilité non activée pour cette organisation (aucune société par défaut).",
        )
    return societe


async def _get_exercice_for_date(
    db: AsyncSession, organisation_id: int, societe_id: int, operation_date: date
) -> ComptaExercice:
    res = await db.execute(
        select(ComptaExercice).where(
            ComptaExercice.organisation_id == organisation_id,
            ComptaExercice.societe_id == societe_id,
            ComptaExercice.date_debut <= operation_date,
            ComptaExercice.date_fin >= operation_date,
        )
    )
    exercice = res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Aucun exercice comptable ne couvre la date {operation_date}.",
        )
    return exercice


async def _get_journal(
    db: AsyncSession, organisation_id: int, societe_id: int, code: str
) -> ComptaJournal:
    res = await db.execute(
        select(ComptaJournal).where(
            ComptaJournal.organisation_id == organisation_id,
            ComptaJournal.societe_id == societe_id,
            ComptaJournal.code == code,
        )
    )
    journal = res.scalar_one_or_none()
    if journal is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Journal '{code}' introuvable — provisionnement comptable incomplet.",
        )
    return journal


async def resolve_compte_poste_budgetaire(
    db: AsyncSession, organisation_id: int, budget_poste_id: int
) -> ComptaCompte:
    """Résout le compte comptable d'un poste budgétaire. Échec bloquant si non mappé."""
    res = await db.execute(
        select(ComptaCompte)
        .join(ComptaMappingPosteBudgetaire, ComptaMappingPosteBudgetaire.compte_id == ComptaCompte.id)
        .where(
            ComptaMappingPosteBudgetaire.organisation_id == organisation_id,
            ComptaMappingPosteBudgetaire.budget_poste_id == budget_poste_id,
        )
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Poste budgétaire #{budget_poste_id} sans compte comptable mappé. "
                "Configurez le mapping avant de générer des écritures pour ce poste."
            ),
        )
    return compte


async def resolve_compte_tresorerie(
    db: AsyncSession, organisation_id: int, societe: ComptaSociete, canal: Literal["CAISSE", "BANQUE"],
    compte_bancaire_id: int | None,
) -> ComptaCompte:
    """Résout le compte comptable de trésorerie (512x/571). Échec bloquant si non mappé.

    Deux façons pour une opération de référencer sa trésorerie :
    - `compte_bancaire_id` renseigné (BANQUE toujours, ou CAISSE via un
      compte CASH nommé individuellement — « caisse progressive ») : mappé
      via `ComptaMappingCompteBancaire`.
    - `compte_bancaire_id` absent en canal CAISSE : la caisse unique de
      l'organisation (`CaisseCentrale`) est utilisée ; résolue via
      `societe.compte_caisse_defaut_id`.
    """
    if compte_bancaire_id is not None:
        res = await db.execute(
            select(ComptaCompte)
            .join(ComptaMappingCompteBancaire, ComptaMappingCompteBancaire.compte_id == ComptaCompte.id)
            .where(
                ComptaMappingCompteBancaire.organisation_id == organisation_id,
                ComptaMappingCompteBancaire.compte_bancaire_id == compte_bancaire_id,
            )
        )
        compte = res.scalar_one_or_none()
        if compte is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Compte bancaire/caisse #{compte_bancaire_id} sans compte comptable mappé. "
                    "Configurez le mapping avant de générer des écritures pour ce compte."
                ),
            )
        return compte

    if canal != "CAISSE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compte de trésorerie requis pour une opération en canal BANQUE.",
        )
    if societe.compte_caisse_defaut_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Aucun compte caisse par défaut configuré pour cette société. "
                "Configurez `compte_caisse_defaut_id` avant de générer des écritures pour la caisse."
            ),
        )
    compte = await db.get(ComptaCompte, societe.compte_caisse_defaut_id)
    if compte is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le compte caisse par défaut configuré pour cette société est introuvable.",
        )
    return compte


async def _find_existing_ecriture(
    db: AsyncSession, organisation_id: int, module_origine: str, type_origine: str, objet_origine_id: str
) -> ComptaEcriture | None:
    """Idempotence côté application : évite de heurter la contrainte unique pour un rejeu identifié."""
    res = await db.execute(
        select(ComptaEcriture).where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.module_origine == module_origine,
            ComptaEcriture.type_origine == type_origine,
            ComptaEcriture.objet_origine_id == objet_origine_id,
        )
    )
    return res.scalar_one_or_none()


async def generer_ecriture_encaissement(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: str,
    date_operation: date,
    montant: Decimal,
    devise: str,
    canal: Literal["CAISSE", "BANQUE"],
    compte_bancaire_id: int | None,
    budget_poste_id: int | None,
    libelle: str,
    created_by=None,
) -> ComptaEcriture:
    """Débit Trésorerie / Crédit Produit — cf. catalogue §4.5 du dossier d'architecture.

    `compte_bancaire_id` : optionnel en canal CAISSE (caisse unique — cf.
    `resolve_compte_tresorerie`), requis en canal BANQUE.
    """
    existing = await _find_existing_ecriture(db, organisation_id, "encaissements", "encaissement", encaissement_id)
    if existing is not None:
        return existing

    if budget_poste_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encaissement sans poste budgétaire : impossible de résoudre le compte de produit.",
        )

    societe = await _get_default_societe(db, organisation_id)
    exercice = await _get_exercice_for_date(db, organisation_id, societe.id, date_operation)
    journal_code = "BQ" if canal == "BANQUE" else "CA"
    journal = await _get_journal(db, organisation_id, societe.id, journal_code)

    compte_tresorerie = await resolve_compte_tresorerie(db, organisation_id, societe, canal, compte_bancaire_id)
    compte_produit = await resolve_compte_poste_budgetaire(db, organisation_id, budget_poste_id)

    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=date_operation,
        libelle=libelle,
        statut="BROUILLON",
        devise=devise,
        module_origine="encaissements",
        type_origine="encaissement",
        objet_origine_id=encaissement_id,
        est_automatique=True,
        created_by=created_by,
    )
    db.add(ecriture)
    await db.flush()

    db.add_all([
        ComptaLigneEcriture(
            organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_tresorerie.id, ordre=1, libelle=libelle,
            debit=montant, credit=Decimal("0"), devise=devise, debit_tenue=montant, credit_tenue=Decimal("0"),
        ),
        ComptaLigneEcriture(
            organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_produit.id, ordre=2, libelle=libelle,
            debit=Decimal("0"), credit=montant, devise=devise, debit_tenue=Decimal("0"), credit_tenue=montant,
        ),
    ])
    await db.flush()
    return ecriture


async def generer_ecriture_sortie_fonds(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie_fonds_id: str,
    date_operation: date,
    montant: Decimal,
    devise: str,
    canal: Literal["CAISSE", "BANQUE"],
    compte_bancaire_id: int | None,
    budget_poste_id: int | None,
    libelle: str,
    created_by=None,
    imputations: list[tuple[int, Decimal]] | None = None,
) -> ComptaEcriture:
    """Débit Charge / Crédit Trésorerie — cf. catalogue §4.5 du dossier d'architecture.

    `imputations` : réservé aux sorties réparties sur plusieurs postes
    budgétaires (ordre de décaissement multi-postes) — une ligne de débit par
    poste `(budget_poste_id, montant_ligne)`, remplace `budget_poste_id` quand
    fourni. La somme des montants doit égaler `montant`.
    """
    existing = await _find_existing_ecriture(db, organisation_id, "sorties_fonds", "sortie_fonds", sortie_fonds_id)
    if existing is not None:
        return existing

    if imputations:
        total_impute = sum((m for _, m in imputations), Decimal("0"))
        if total_impute != montant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Répartition budgétaire incohérente : somme des imputations "
                    f"({total_impute}) différente du montant de la sortie ({montant})."
                ),
            )
    elif budget_poste_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sortie de fonds sans poste budgétaire : impossible de résoudre le compte de charge.",
        )

    societe = await _get_default_societe(db, organisation_id)
    exercice = await _get_exercice_for_date(db, organisation_id, societe.id, date_operation)
    journal_code = "BQ" if canal == "BANQUE" else "CA"
    journal = await _get_journal(db, organisation_id, societe.id, journal_code)

    compte_tresorerie = await resolve_compte_tresorerie(db, organisation_id, societe, canal, compte_bancaire_id)

    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=date_operation,
        libelle=libelle,
        statut="BROUILLON",
        devise=devise,
        module_origine="sorties_fonds",
        type_origine="sortie_fonds",
        objet_origine_id=sortie_fonds_id,
        est_automatique=True,
        created_by=created_by,
    )
    db.add(ecriture)
    await db.flush()

    lignes: list[ComptaLigneEcriture] = []
    ordre = 1
    if imputations:
        for poste_id, montant_ligne in imputations:
            compte_charge = await resolve_compte_poste_budgetaire(db, organisation_id, poste_id)
            lignes.append(ComptaLigneEcriture(
                organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
                compte_id=compte_charge.id, ordre=ordre, libelle=libelle,
                debit=montant_ligne, credit=Decimal("0"), devise=devise,
                debit_tenue=montant_ligne, credit_tenue=Decimal("0"),
            ))
            ordre += 1
    else:
        compte_charge = await resolve_compte_poste_budgetaire(db, organisation_id, budget_poste_id)
        lignes.append(ComptaLigneEcriture(
            organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_charge.id, ordre=ordre, libelle=libelle,
            debit=montant, credit=Decimal("0"), devise=devise, debit_tenue=montant, credit_tenue=Decimal("0"),
        ))
        ordre += 1

    lignes.append(ComptaLigneEcriture(
        organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
        compte_id=compte_tresorerie.id, ordre=ordre, libelle=libelle,
        debit=Decimal("0"), credit=montant, devise=devise, debit_tenue=Decimal("0"), credit_tenue=montant,
    ))
    db.add_all(lignes)
    await db.flush()
    return ecriture


async def generer_ecriture_transfert_interne(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie_fonds_id: str,
    date_operation: date,
    montant: Decimal,
    devise: str,
    compte_origine_bancaire_id: int | None,
    compte_destination_bancaire_id: int | None,
    libelle: str,
    created_by=None,
) -> ComptaEcriture:
    """Débit Compte destination / Crédit Compte origine — transfert interne de
    trésorerie (versement à la banque ou approvisionnement de la caisse), cf.
    catalogue §4.5 : « Transfert interne | OD | Compte destination | Compte
    origine ». Aucun poste budgétaire : ce n'est pas une dépense.

    `compte_origine_bancaire_id`/`compte_destination_bancaire_id` : `None`
    désigne la caisse unique de l'organisation (cf. `resolve_compte_tresorerie`).
    """
    existing = await _find_existing_ecriture(
        db, organisation_id, "sorties_fonds", "transfert_interne", sortie_fonds_id
    )
    if existing is not None:
        return existing

    societe = await _get_default_societe(db, organisation_id)
    exercice = await _get_exercice_for_date(db, organisation_id, societe.id, date_operation)
    journal = await _get_journal(db, organisation_id, societe.id, "OD")

    compte_origine = await resolve_compte_tresorerie(
        db, organisation_id, societe,
        "CAISSE" if compte_origine_bancaire_id is None else "BANQUE",
        compte_origine_bancaire_id,
    )
    compte_destination = await resolve_compte_tresorerie(
        db, organisation_id, societe,
        "CAISSE" if compte_destination_bancaire_id is None else "BANQUE",
        compte_destination_bancaire_id,
    )

    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=date_operation,
        libelle=libelle,
        statut="BROUILLON",
        devise=devise,
        module_origine="sorties_fonds",
        type_origine="transfert_interne",
        objet_origine_id=sortie_fonds_id,
        est_automatique=True,
        created_by=created_by,
    )
    db.add(ecriture)
    await db.flush()

    db.add_all([
        ComptaLigneEcriture(
            organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_destination.id, ordre=1, libelle=libelle,
            debit=montant, credit=Decimal("0"), devise=devise, debit_tenue=montant, credit_tenue=Decimal("0"),
        ),
        ComptaLigneEcriture(
            organisation_id=organisation_id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_origine.id, ordre=2, libelle=libelle,
            debit=Decimal("0"), credit=montant, devise=devise, debit_tenue=Decimal("0"), credit_tenue=montant,
        ),
    ])
    await db.flush()
    return ecriture
