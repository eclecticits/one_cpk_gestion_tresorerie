"""Corriger une ligne après le visa d'examen.

L'examinateur répond du texte qu'il a visé : c'est donc lui, et lui seul, qui
le corrige tant que la pièce n'est pas validée. Ces tests verrouillent les deux
conséquences comptables d'une correction — le total de la réquisition suit ses
lignes, et l'engagement du poste ne compte pas deux fois la même ligne — ainsi
que le refus opposé à quiconque d'autre.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.lignes_requisition import (
    delete_ligne_requisition,
    update_ligne_requisition,
)
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.requisition import LigneRequisitionUpdate
from app.services.budget_engagement import resynchroniser_engagement_requisition

PREVU = Decimal("10000.00")
MONTANT = Decimal("2500.00")


async def _org(db):
    org = Organisation(nom="Correction", slug=f"corr-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _user(db, org, *, nom="Examinateur"):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        nom=nom,
        prenom="Test",
        role="admin",
        organisation_id=org.id,
        active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _exercice(db, org):
    """Un seul exercice par organisation : la clé (organisation, année) est unique."""
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    return exercice


async def _poste(db, org, exercice, *, prevu=PREVU, libelle="Fournitures"):
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle=libelle,
        type="DEPENSE",
        active=True,
        montant_prevu=prevu,
        montant_engage=Decimal("0"),
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _contexte(db, *, montant=MONTANT, postes=1):
    """Réquisition visée par l'examen, une ligne, poste(s) ouvert(s) au service."""
    org = await _org(db)
    examinateur = await _user(db, org)
    redacteur = await _user(db, org, nom="Redacteur")
    service = Service(
        organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True
    )
    db.add(service)
    await db.flush()

    exercice = await _exercice(db, org)
    liste_postes = [
        await _poste(db, org, exercice, libelle=f"Poste {i}") for i in range(postes)
    ]
    for poste in liste_postes:
        db.add(
            ServiceRubrique(
                service_id=service.id,
                budget_poste_id=poste.id,
                active=True,
            )
        )
    await db.flush()

    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Achat a corriger",
        mode_paiement="cash",
        type_requisition="classique",
        status="EN_ATTENTE",
        examen_status="EXAMINE",
        examen_par=examinateur.id,
        examen_le=datetime.now(timezone.utc),
        montant_total=montant,
        devise="USD",
        created_by=redacteur.id,
        workflow_snapshot={"steps": {"examen": {"enabled": True}}},
    )
    db.add(req)
    await db.flush()
    ligne = LigneRequisition(
        organisation_id=org.id,
        requisition_id=req.id,
        budget_poste_id=liste_postes[0].id,
        rubrique="Fournitures",
        description="Ramettes",
        quantite=1,
        montant_unitaire=montant,
        montant_total=montant,
        devise="USD",
    )
    db.add(ligne)
    await db.flush()
    # La pièce est visée : son montant est déjà engagé sur le poste.
    await resynchroniser_engagement_requisition(db, req)
    await db.commit()
    return org, service, req, ligne, liste_postes, examinateur, redacteur


async def _engage(db, poste_id) -> Decimal:
    res = await db.execute(select(BudgetPoste.montant_engage).where(BudgetPoste.id == poste_id))
    return Decimal(res.scalar_one() or 0)


def _payload(poste_id, *, montant, description="Ramettes A4", quantite=1):
    return LigneRequisitionUpdate(
        budget_poste_id=poste_id,
        rubrique="Fournitures",
        description=description,
        quantite=quantite,
        montant_unitaire=montant,
        montant_total=montant,
        devise="USD",
    )


@pytest.mark.asyncio
async def test_examinateur_corrige_une_ligne_et_le_total_suit(db_session):
    db = db_session
    org, _, req, ligne, postes, examinateur, _ = await _contexte(db)

    corrigee = await update_ligne_requisition(
        ligne_id=str(ligne.id),
        payload=_payload(postes[0].id, montant=Decimal("1800.00")),
        db=db,
        user=examinateur,
        tenant_id=org.id,
    )

    assert Decimal(corrigee.montant_total) == Decimal("1800.00")
    await db.refresh(req)
    # Le total de la pièce n'est pas une saisie : il suit ses lignes.
    assert Decimal(req.montant_total) == Decimal("1800.00")
    # L'engagement se recale sans compter deux fois la même ligne.
    assert await _engage(db, postes[0].id) == Decimal("1800.00")


@pytest.mark.asyncio
async def test_un_tiers_ne_corrige_pas_ce_qu_il_n_a_pas_vise(db_session):
    db = db_session
    org, _, _, ligne, postes, _, redacteur = await _contexte(db)

    with pytest.raises(HTTPException) as exc:
        await update_ligne_requisition(
            ligne_id=str(ligne.id),
            payload=_payload(postes[0].id, montant=Decimal("1800.00")),
            db=db,
            user=redacteur,
            tenant_id=org.id,
        )

    assert exc.value.status_code == 409
    assert "examen" in exc.value.detail


@pytest.mark.asyncio
async def test_la_ligne_corrigee_ne_se_heurte_pas_a_son_propre_engagement(db_session):
    # Le poste est prévu à 10 000 et déjà engagé à 2 500 par cette ligne. La
    # porter à 9 000 doit passer : son ancien montant lui est rendu d'abord.
    db = db_session
    org, _, req, ligne, postes, examinateur, _ = await _contexte(db)

    corrigee = await update_ligne_requisition(
        ligne_id=str(ligne.id),
        payload=_payload(postes[0].id, montant=Decimal("9000.00")),
        db=db,
        user=examinateur,
        tenant_id=org.id,
    )

    assert Decimal(corrigee.montant_total) == Decimal("9000.00")
    assert await _engage(db, postes[0].id) == Decimal("9000.00")


@pytest.mark.asyncio
async def test_la_correction_reste_soumise_au_disponible(db_session):
    db = db_session
    org, _, _, ligne, postes, examinateur, _ = await _contexte(db)

    with pytest.raises(HTTPException) as exc:
        await update_ligne_requisition(
            ligne_id=str(ligne.id),
            payload=_payload(postes[0].id, montant=Decimal("12000.00")),
            db=db,
            user=examinateur,
            tenant_id=org.id,
        )

    assert exc.value.status_code == 400
    assert "Dépassement budgétaire" in exc.value.detail


@pytest.mark.asyncio
async def test_changer_de_poste_libere_l_ancien(db_session):
    db = db_session
    org, _, _, ligne, postes, examinateur, _ = await _contexte(db, postes=2)

    await update_ligne_requisition(
        ligne_id=str(ligne.id),
        payload=_payload(postes[1].id, montant=MONTANT),
        db=db,
        user=examinateur,
        tenant_id=org.id,
    )

    # Le poste quitté ne doit plus rien geler : `postes_de_requisition` ne le
    # voit plus, c'est le rattrapage explicite qui s'en charge.
    assert await _engage(db, postes[0].id) == Decimal("0")
    assert await _engage(db, postes[1].id) == MONTANT


@pytest.mark.asyncio
async def test_supprimer_une_ligne_rend_le_credit(db_session):
    db = db_session
    org, _, req, ligne, postes, examinateur, _ = await _contexte(db, postes=2)
    # Une seconde ligne, pour que la suppression ne vide pas la réquisition.
    autre = LigneRequisition(
        organisation_id=org.id,
        requisition_id=req.id,
        budget_poste_id=postes[1].id,
        rubrique="Fournitures",
        description="Encre",
        quantite=1,
        montant_unitaire=Decimal("500.00"),
        montant_total=Decimal("500.00"),
        devise="USD",
    )
    db.add(autre)
    await db.flush()
    await resynchroniser_engagement_requisition(db, req)
    await db.commit()

    await delete_ligne_requisition(
        ligne_id=str(ligne.id), db=db, user=examinateur, tenant_id=org.id
    )

    assert await _engage(db, postes[0].id) == Decimal("0")
    await db.refresh(req)
    assert Decimal(req.montant_total) == Decimal("500.00")


@pytest.mark.asyncio
async def test_la_derniere_ligne_ne_se_supprime_pas(db_session):
    # Une réquisition budgétaire sans ligne n'autorise plus rien : elle serait
    # en course sans montant opposable à la caisse.
    db = db_session
    org, _, _, ligne, _, examinateur, _ = await _contexte(db)

    with pytest.raises(HTTPException) as exc:
        await delete_ligne_requisition(
            ligne_id=str(ligne.id), db=db, user=examinateur, tenant_id=org.id
        )

    assert exc.value.status_code == 400
    assert "Dernière ligne" in exc.value.detail
