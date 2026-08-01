"""Validation en lot des écritures au brouillon.

Le moteur de génération automatique produit des écritures au BROUILLON, et les
restitutions comme les états financiers ne retiennent que les écritures
validées. Sans validation en masse, une reprise d'historique de plusieurs
centaines d'opérations resterait inexploitable et la clôture d'exercice
inatteignable.

Quatre décisions structurent ce service.

**1. Chaque écriture est validée par `valider_ecriture`, une par une.**
Aucun raccourci en SQL de masse : les contrôles (équilibre, exercice ouvert,
période non fermée, comptes actifs et non collectifs, devise) doivent être
EXACTEMENT ceux de la validation unitaire. Le coût est réel — quelques
requêtes par écriture — mais c'est un traitement occasionnel, et une règle
comptable contournée « pour aller plus vite » est un défaut silencieux.

**2. Échec isolé, pas échec global.**
Chaque écriture est traitée dans son propre point de sauvegarde. Une écriture
refusée n'annule pas les précédentes : elle est rapportée avec son motif et le
lot continue. Tout arrêter au premier refus obligerait à corriger et relancer
autant de fois qu'il y a de problèmes.

**3. Numérotation dans l'ordre chronologique.**
Les écritures sont traitées triées par date, puis par date de création. Sans
ce tri, un lot attribuerait les numéros de pièce dans un ordre arbitraire — un
journal dont la numérotation ne suit pas les dates est un défaut qu'un
auditeur relève immédiatement.

**4. Simulation d'abord.**
Le mode `simulation` exécute exactement le même traitement puis annule tout,
et retourne le rapport. L'utilisateur voit donc ce qui passerait et ce qui
bloquerait AVANT de figer quoi que ce soit. Les numéros consommés pendant la
simulation sont eux aussi annulés : le compteur vit dans une table, pas dans
une séquence PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import ComptaEcriture
from app.modules.comptabilite.services.ecriture_service import valider_ecriture

# Garde-fou : une transaction qui validerait des dizaines de milliers
# d'écritures tiendrait des verrous trop longtemps. Au-delà, l'appelant
# relance le traitement — il est repris là où il s'est arrêté puisque les
# écritures validées ne sont plus au brouillon.
LIMITE_MAX = 2000
LIMITE_DEFAUT = 500


@dataclass
class EchecValidation:
    ecriture_id: UUID
    libelle: str
    date_ecriture: date
    motif: str


@dataclass
class RapportValidationLot:
    simulation: bool
    total_examinees: int
    validees: int
    echecs: list[EchecValidation] = field(default_factory=list)
    # Vrai si d'autres brouillons correspondent aux filtres au-delà de la
    # limite : l'écran doit inviter à relancer plutôt que laisser croire que
    # tout a été traité.
    reste_a_traiter: bool = False


async def valider_lot(
    db: AsyncSession,
    *,
    organisation_id: int,
    ecriture_ids: list[UUID] | None = None,
    exercice_id: int | None = None,
    journal_id: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    module_origine: str | None = None,
    automatiques_uniquement: bool = False,
    limite: int = LIMITE_DEFAUT,
    simulation: bool = False,
    user_id: UUID | None = None,
) -> RapportValidationLot:
    """Valide les écritures au brouillon correspondant aux critères.

    `ecriture_ids` restreint à une sélection explicite ; les autres filtres
    s'appliquent en plus. Sans aucun critère, le lot porte sur tous les
    brouillons de l'organisation, dans la limite de `limite`.
    """
    limite = max(1, min(limite, LIMITE_MAX))

    stmt = select(ComptaEcriture).where(
        ComptaEcriture.organisation_id == organisation_id,
        ComptaEcriture.statut == "BROUILLON",
    )
    if ecriture_ids:
        stmt = stmt.where(ComptaEcriture.id.in_(ecriture_ids))
    if exercice_id is not None:
        stmt = stmt.where(ComptaEcriture.exercice_id == exercice_id)
    if journal_id is not None:
        stmt = stmt.where(ComptaEcriture.journal_id == journal_id)
    if date_debut is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture >= date_debut)
    if date_fin is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture <= date_fin)
    if module_origine:
        stmt = stmt.where(ComptaEcriture.module_origine == module_origine)
    if automatiques_uniquement:
        stmt = stmt.where(ComptaEcriture.est_automatique.is_(True))

    # Ordre chronologique : c'est lui qui détermine l'ordre des numéros de
    # pièce. `id` en dernier ressort pour un tri stable et reproductible.
    stmt = stmt.order_by(
        ComptaEcriture.date_ecriture, ComptaEcriture.created_at, ComptaEcriture.id
    ).limit(limite + 1)

    res = await db.execute(stmt)
    ecritures = list(res.scalars().all())
    reste_a_traiter = len(ecritures) > limite
    ecritures = ecritures[:limite]

    rapport = RapportValidationLot(
        simulation=simulation,
        total_examinees=len(ecritures),
        validees=0,
        reste_a_traiter=reste_a_traiter,
    )
    if not ecritures:
        return rapport

    # Point de sauvegarde englobant : il permet d'annuler tout le lot en mode
    # simulation sans toucher à ce que l'appelant a déjà fait dans sa
    # transaction.
    enveloppe = await db.begin_nested()
    try:
        for ecriture in ecritures:
            identite = (ecriture.id, ecriture.libelle, ecriture.date_ecriture)
            try:
                async with db.begin_nested():
                    await valider_ecriture(
                        db,
                        ecriture_id=ecriture.id,
                        organisation_id=organisation_id,
                        user_id=user_id,
                    )
                rapport.validees += 1
            except HTTPException as exc:
                rapport.echecs.append(
                    EchecValidation(
                        ecriture_id=identite[0], libelle=identite[1],
                        date_ecriture=identite[2], motif=str(exc.detail),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — un lot ne s'interrompt pas
                rapport.echecs.append(
                    EchecValidation(
                        ecriture_id=identite[0], libelle=identite[1],
                        date_ecriture=identite[2],
                        motif=f"Erreur inattendue : {exc}",
                    )
                )
    except Exception:
        await enveloppe.rollback()
        raise

    if simulation:
        await enveloppe.rollback()
    else:
        await enveloppe.commit()

    return rapport
