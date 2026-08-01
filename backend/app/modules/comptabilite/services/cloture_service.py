"""Clôture d'exercice et report des à-nouveaux (Lot 5).

Trois opérations distinctes, volontairement séparées pour rester réversibles
le plus longtemps possible :

1. **Détermination du résultat** — solde les comptes de gestion (classes 6 et
   7) par contrepartie du compte de résultat (120 bénéfice / 129 perte). Après
   cette écriture, les charges et produits sont à zéro et le bilan porte le
   résultat.
2. **Clôture** — passe l'exercice au statut CLOTURE. Les écritures validées y
   deviennent CLOTUREE : plus aucune saisie n'est possible.
3. **Report des à-nouveaux** — ouvre l'exercice suivant en y reprenant les
   soldes de bilan (classes 1 à 5), au journal AN.

Chaque opération est **idempotente** : elle vérifie son propre travail avant
de le refaire. Un rejeu ne peut pas produire de double écriture ni de double
report.

Le résultat et les à-nouveaux sont générés en écritures **VALIDEE**, pas au
brouillon : ce sont des écritures de système, produites par un calcul
déterministe à partir d'écritures déjà validées. Les laisser au brouillon
signifierait qu'un exercice clôturé puisse rester déséquilibré.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaSociete,
)
from app.modules.comptabilite.services.numerotation import generer_numero_ecriture
from app.modules.comptabilite.services.reporting_service import STATUTS_COMPTABILISES

# Classes de comptes de gestion, soldées à la détermination du résultat.
CLASSES_GESTION = ("6", "7")
# Classes de bilan, reportées à nouveau sur l'exercice suivant.
CLASSES_BILAN = ("1", "2", "3", "4", "5")

# Comptes de résultat : le bénéfice est crédité en 120, la perte débitée en
# 129. Ces numéros sont les seuls du module à être connus du code — un plan
# comptable qui ne les fournirait pas ne peut pas être clôturé, et l'erreur
# est explicite plutôt que silencieuse.
COMPTE_RESULTAT_BENEFICE = "120"
COMPTE_RESULTAT_PERTE = "129"

ORIGINE_MODULE = "comptabilite"
TYPE_RESULTAT = "determination_resultat"
TYPE_A_NOUVEAUX = "a_nouveaux"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClotureError(Exception):
    """Erreur métier de clôture — traduite en 400 par le router."""


async def _societe(db: AsyncSession, organisation_id: int, societe_id: int) -> ComptaSociete:
    societe = await db.get(ComptaSociete, societe_id)
    if societe is None or societe.organisation_id != organisation_id:
        raise ClotureError("Société comptable introuvable.")
    return societe


async def _journal(db: AsyncSession, exercice: ComptaExercice, code: str) -> ComptaJournal:
    res = await db.execute(
        select(ComptaJournal).where(
            ComptaJournal.organisation_id == exercice.organisation_id,
            ComptaJournal.societe_id == exercice.societe_id,
            ComptaJournal.code == code,
        )
    )
    journal = res.scalar_one_or_none()
    if journal is None:
        raise ClotureError(
            f"Journal « {code} » absent : la comptabilité a été activée avant le Lot 5. "
            "Créez ce journal avant de clôturer."
        )
    return journal


async def _compte_par_numero(db: AsyncSession, exercice: ComptaExercice, numero: str) -> ComptaCompte:
    res = await db.execute(
        select(ComptaCompte).where(
            ComptaCompte.organisation_id == exercice.organisation_id,
            ComptaCompte.referentiel_id == exercice.referentiel_id,
            ComptaCompte.numero == numero,
        )
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise ClotureError(
            f"Compte « {numero} » introuvable dans le référentiel de l'exercice : "
            "la clôture ne peut pas déterminer le résultat."
        )
    return compte


async def _soldes(
    db: AsyncSession, exercice: ComptaExercice, classes: tuple[str, ...]
) -> list[tuple[ComptaCompte, Decimal]]:
    """Soldes algébriques (débit − crédit) des comptes d'une famille de classes."""
    res = await db.execute(
        select(
            ComptaCompte,
            func.coalesce(
                func.sum(ComptaLigneEcriture.debit_tenue - ComptaLigneEcriture.credit_tenue), 0
            ).label("solde"),
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaCompte, ComptaCompte.id == ComptaLigneEcriture.compte_id)
        .where(
            ComptaLigneEcriture.organisation_id == exercice.organisation_id,
            ComptaEcriture.organisation_id == exercice.organisation_id,
            ComptaEcriture.exercice_id == exercice.id,
            ComptaEcriture.statut.in_(STATUTS_COMPTABILISES),
        )
        .group_by(ComptaCompte.id)
    )
    soldes: list[tuple[ComptaCompte, Decimal]] = []
    for compte, solde in res.all():
        classe = (compte.numero or "")[:1]
        if classe in classes and Decimal(solde) != 0:
            soldes.append((compte, Decimal(solde)))
    return sorted(soldes, key=lambda c: c[0].numero)


async def _ecriture_existante(
    db: AsyncSession, organisation_id: int, type_origine: str, exercice_id: int
) -> ComptaEcriture | None:
    res = await db.execute(
        select(ComptaEcriture).where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.module_origine == ORIGINE_MODULE,
            ComptaEcriture.type_origine == type_origine,
            ComptaEcriture.objet_origine_id == str(exercice_id),
            ComptaEcriture.statut != "ANNULEE",
        )
    )
    return res.scalar_one_or_none()


async def _creer_ecriture_validee(
    db: AsyncSession,
    *,
    exercice: ComptaExercice,
    journal: ComptaJournal,
    date_ecriture,
    libelle: str,
    type_origine: str,
    objet_origine_id: str,
    lignes: list[tuple[int, Decimal, Decimal]],
    user_id: UUID | None,
) -> ComptaEcriture:
    """Crée une écriture de système directement au statut VALIDEE.

    `lignes` : (compte_id, débit, crédit). L'équilibre est contrôlé ici — une
    écriture de clôture déséquilibrée serait un défaut du calcul, pas une
    saisie à corriger.
    """
    total_debit = sum((d for _, d, _ in lignes), Decimal("0"))
    total_credit = sum((c for _, _, c in lignes), Decimal("0"))
    if total_debit != total_credit:
        raise ClotureError(
            f"Écriture de clôture déséquilibrée (débit {total_debit} ≠ crédit {total_credit}) : "
            "anomalie de calcul, aucune écriture n'a été enregistrée."
        )

    ecriture = ComptaEcriture(
        organisation_id=exercice.organisation_id,
        societe_id=exercice.societe_id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=date_ecriture,
        libelle=libelle,
        statut="BROUILLON",
        devise=exercice.devise_tenue,
        module_origine=ORIGINE_MODULE,
        type_origine=type_origine,
        objet_origine_id=objet_origine_id,
        est_automatique=True,
        created_by=user_id,
    )
    db.add(ecriture)
    await db.flush()

    for ordre, (compte_id, debit, credit) in enumerate(lignes, start=1):
        db.add(
            ComptaLigneEcriture(
                organisation_id=exercice.organisation_id,
                societe_id=exercice.societe_id,
                ecriture_id=ecriture.id,
                compte_id=compte_id,
                ordre=ordre,
                libelle=libelle,
                debit=debit, credit=credit, devise=exercice.devise_tenue,
                debit_tenue=debit, credit_tenue=credit,
            )
        )
    await db.flush()

    # Numérotation puis validation, sans passer par valider_ecriture : les
    # lignes viennent d'être écrites dans cette transaction et les contrôles
    # de saisie (compte actif, période ouverte) ne s'appliquent pas à une
    # écriture de système.
    ecriture.numero = await generer_numero_ecriture(
        db,
        organisation_id=exercice.organisation_id,
        societe_id=exercice.societe_id,
        exercice_id=exercice.id,
        journal_id=journal.id,
    )
    ecriture.statut = "VALIDEE"
    ecriture.valide_par = user_id
    ecriture.valide_le = _utcnow()
    await db.flush()
    return ecriture


async def determiner_resultat(
    db: AsyncSession, *, organisation_id: int, exercice_id: int, user_id: UUID | None = None
) -> dict:
    """Solde les comptes de gestion par le compte de résultat (journal CLO)."""
    exercice = await db.get(ComptaExercice, exercice_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise ClotureError("Exercice introuvable pour cette organisation.")
    if exercice.statut not in {"OUVERT", "ROUVERT"}:
        raise ClotureError(
            f"L'exercice {exercice.code} est {exercice.statut.lower()} : "
            "le résultat ne peut plus être déterminé."
        )

    existante = await _ecriture_existante(db, organisation_id, TYPE_RESULTAT, exercice_id)
    if existante is not None:
        return {"ecriture_id": str(existante.id), "deja_fait": True, "resultat": None}

    soldes = await _soldes(db, exercice, CLASSES_GESTION)
    if not soldes:
        raise ClotureError(
            "Aucun mouvement sur les comptes de charges et de produits : "
            "il n'y a pas de résultat à déterminer."
        )

    # Solder chaque compte de gestion, c'est passer l'inverse de son solde.
    lignes: list[tuple[int, Decimal, Decimal]] = []
    resultat = Decimal("0")  # positif = bénéfice
    for compte, solde in soldes:
        if solde > 0:  # compte débiteur (charge) → on le crédite
            lignes.append((compte.id, Decimal("0"), solde))
            resultat -= solde
        else:  # compte créditeur (produit) → on le débite
            lignes.append((compte.id, -solde, Decimal("0")))
            resultat += -solde

    if resultat >= 0:
        compte_resultat = await _compte_par_numero(db, exercice, COMPTE_RESULTAT_BENEFICE)
        lignes.append((compte_resultat.id, Decimal("0"), resultat))
    else:
        compte_resultat = await _compte_par_numero(db, exercice, COMPTE_RESULTAT_PERTE)
        lignes.append((compte_resultat.id, -resultat, Decimal("0")))

    journal = await _journal(db, exercice, "CLO")
    ecriture = await _creer_ecriture_validee(
        db,
        exercice=exercice,
        journal=journal,
        date_ecriture=exercice.date_fin,
        libelle=f"Détermination du résultat — exercice {exercice.code}",
        type_origine=TYPE_RESULTAT,
        objet_origine_id=str(exercice_id),
        lignes=lignes,
        user_id=user_id,
    )
    return {"ecriture_id": str(ecriture.id), "deja_fait": False, "resultat": resultat}


async def cloturer_exercice(
    db: AsyncSession, *, organisation_id: int, exercice_id: int, user_id: UUID | None = None
) -> dict:
    """Clôture l'exercice : plus aucune écriture ne peut y être saisie."""
    exercice = await db.get(ComptaExercice, exercice_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise ClotureError("Exercice introuvable pour cette organisation.")
    if exercice.statut == "CLOTURE":
        return {"deja_cloture": True, "ecritures_cloturees": 0}
    if exercice.statut not in {"OUVERT", "ROUVERT"}:
        raise ClotureError(f"L'exercice {exercice.code} est {exercice.statut.lower()}.")

    if await _ecriture_existante(db, organisation_id, TYPE_RESULTAT, exercice_id) is None:
        raise ClotureError(
            "Le résultat de l'exercice n'a pas été déterminé : clôturer maintenant laisserait "
            "les comptes de charges et de produits ouverts. Déterminez le résultat d'abord."
        )

    brouillons = await db.execute(
        select(func.count(ComptaEcriture.id)).where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.exercice_id == exercice_id,
            ComptaEcriture.statut == "BROUILLON",
        )
    )
    nb_brouillons = brouillons.scalar_one()
    if nb_brouillons:
        raise ClotureError(
            f"{nb_brouillons} écriture(s) encore au brouillon sur cet exercice. "
            "Validez-les ou annulez-les avant de clôturer — elles seraient définitivement "
            "perdues pour les états financiers."
        )

    res = await db.execute(
        update(ComptaEcriture)
        .where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.exercice_id == exercice_id,
            ComptaEcriture.statut == "VALIDEE",
        )
        .values(statut="CLOTUREE")
    )
    exercice.statut = "CLOTURE"
    exercice.cloture_par = user_id
    exercice.cloture_le = _utcnow()
    exercice.updated_at = _utcnow()
    await db.flush()
    return {"deja_cloture": False, "ecritures_cloturees": res.rowcount or 0}


async def reporter_a_nouveaux(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    exercice_suivant_id: int,
    user_id: UUID | None = None,
) -> dict:
    """Reprend les soldes de bilan de l'exercice clôturé sur le suivant."""
    exercice = await db.get(ComptaExercice, exercice_id)
    suivant = await db.get(ComptaExercice, exercice_suivant_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise ClotureError("Exercice source introuvable pour cette organisation.")
    if suivant is None or suivant.organisation_id != organisation_id:
        raise ClotureError("Exercice de destination introuvable pour cette organisation.")
    if suivant.id == exercice.id:
        raise ClotureError("L'exercice de destination doit être différent de l'exercice clôturé.")
    if suivant.date_debut <= exercice.date_debut:
        raise ClotureError(
            "L'exercice de destination doit être postérieur à l'exercice clôturé."
        )
    if exercice.statut != "CLOTURE":
        raise ClotureError(
            f"L'exercice {exercice.code} n'est pas clôturé : ses soldes peuvent encore changer, "
            "les reporter maintenant produirait une ouverture fausse."
        )
    if suivant.statut not in {"OUVERT", "ROUVERT"}:
        raise ClotureError(f"L'exercice {suivant.code} est {suivant.statut.lower()}.")

    existante = await _ecriture_existante(db, organisation_id, TYPE_A_NOUVEAUX, suivant.id)
    if existante is not None:
        return {"ecriture_id": str(existante.id), "deja_fait": True, "nb_comptes": 0}

    soldes = await _soldes(db, exercice, CLASSES_BILAN)
    if not soldes:
        raise ClotureError("Aucun solde de bilan à reporter.")

    lignes = [
        (compte.id, solde, Decimal("0")) if solde > 0 else (compte.id, Decimal("0"), -solde)
        for compte, solde in soldes
    ]

    journal = await _journal(db, suivant, "AN")
    ecriture = await _creer_ecriture_validee(
        db,
        exercice=suivant,
        journal=journal,
        date_ecriture=suivant.date_debut,
        libelle=f"Report à nouveau — reprise de l'exercice {exercice.code}",
        type_origine=TYPE_A_NOUVEAUX,
        objet_origine_id=str(suivant.id),
        lignes=lignes,
        user_id=user_id,
    )
    suivant.exercice_precedent_id = exercice.id
    suivant.a_nouveaux_generes = True
    await db.flush()
    return {"ecriture_id": str(ecriture.id), "deja_fait": False, "nb_comptes": len(lignes)}
