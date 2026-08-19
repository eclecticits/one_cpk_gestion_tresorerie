"""Politique des engagements budgétaires.

Le défaut d'origine : une réquisition rejetée — « annulée » dans le vocabulaire
métier — gardait son montant engagé, et le crédit correspondant restait gelé
pour toujours. Ces tests verrouillent le cycle complet engager / libérer.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User
from app.schemas.requisition import RequisitionExamenPayload
from app.services.budget_engagement import (
    ecarts_engagement,
    resynchroniser_engagement_requisition,
    resynchroniser_engagements,
)
from app.services.requisition_service import (
    reject_requisition_examen_logic,
    submit_requisition_examen_logic,
)

PREVU = Decimal("10000.00")
MONTANT = Decimal("2500.00")


async def _org(db):
    org = Organisation(nom="Engagements", slug=f"eng-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _user(db, org):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        nom="Examinateur",
        prenom="Bea",
        role="admin",
        organisation_id=org.id,
        active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _poste(db, org, *, prevu=PREVU):
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle="Fournitures",
        type="DEPENSE",
        active=True,
        montant_prevu=prevu,
        montant_engage=Decimal("0"),
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _requisition(db, org, user, poste, *, montant=MONTANT, examen_status="NON_EXAMINE"):
    """Réquisition prête à être soumise à l'examen, avec une ligne sur `poste`."""
    service = Service(
        organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True
    )
    db.add(service)
    await db.flush()
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Achat de fournitures",
        mode_paiement="cash",
        type_requisition="classique",
        status="SIGNEE_SERVICE",
        examen_status=examen_status,
        montant_total=montant,
        devise="USD",
        created_by=user.id,
        signed_by_id=user.id,
        signed_at=datetime.now(timezone.utc),
    )
    db.add(req)
    await db.flush()
    db.add(
        LigneRequisition(
            organisation_id=org.id,
            requisition_id=req.id,
            budget_poste_id=poste.id,
            rubrique="Fournitures",
            description="Ramettes",
            quantite=1,
            montant_unitaire=montant,
            montant_total=montant,
            devise="USD",
        )
    )
    await db.flush()
    return req


async def _engage(db, poste) -> Decimal:
    res = await db.execute(select(BudgetPoste.montant_engage).where(BudgetPoste.id == poste.id))
    return Decimal(res.scalar_one() or 0)


@pytest.mark.asyncio(loop_scope="function")
async def test_brouillon_n_engage_rien(db_session):
    """Fait générateur : un brouillon ne gèle aucun crédit."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await resynchroniser_engagement_requisition(db_session, req)

    assert await _engage(db_session, poste) == Decimal("0.00")


@pytest.mark.asyncio(loop_scope="function")
async def test_soumission_a_l_examen_engage(db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)

    assert await _engage(db_session, poste) == MONTANT


@pytest.mark.asyncio(loop_scope="function")
async def test_rejet_final_libere_l_engagement(db_session):
    """Le cas d'origine : réquisition rejetée, crédit rendu au poste."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)
    assert await _engage(db_session, poste) == MONTANT

    # Ce que fait l'endpoint POST /requisitions/{id}/reject
    req.status = "REJETEE"
    req.motif_rejet = "Hors budget"
    await resynchroniser_engagement_requisition(db_session, req)

    assert await _engage(db_session, poste) == Decimal("0.00")


@pytest.mark.asyncio(loop_scope="function")
async def test_rejet_d_examen_libere_l_engagement(db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)
    assert await _engage(db_session, poste) == MONTANT

    await reject_requisition_examen_logic(
        db=db_session,
        requisition_id=req.id,
        payload=RequisitionExamenPayload(commentaire="Pièces manquantes"),
        user=user,
        tenant_id=org.id,
    )

    assert await _engage(db_session, poste) == Decimal("0.00")


@pytest.mark.asyncio(loop_scope="function")
async def test_suppression_logique_libere_l_engagement(db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)
    req.is_deleted = True
    await resynchroniser_engagement_requisition(db_session, req)

    assert await _engage(db_session, poste) == Decimal("0.00")


@pytest.mark.asyncio(loop_scope="function")
async def test_paiement_ne_libere_pas_l_engagement(db_session):
    """Le paiement consomme l'engagement, il ne le rend pas."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)
    req.status = "PAYEE"
    await resynchroniser_engagement_requisition(db_session, req)

    assert await _engage(db_session, poste) == MONTANT


@pytest.mark.asyncio(loop_scope="function")
async def test_recalcul_idempotent(db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)

    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)
    for _ in range(3):
        await resynchroniser_engagements(db_session, tenant_id=org.id)

    assert await _engage(db_session, poste) == MONTANT
    assert await ecarts_engagement(db_session, tenant_id=org.id) == []


@pytest.mark.asyncio(loop_scope="function")
async def test_reconciliation_detecte_et_corrige_un_ecart(db_session):
    """Filet de sécurité : un compteur corrompu est repéré puis recalé."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste)
    await submit_requisition_examen_logic(db=db_session, requisition_id=req.id, tenant_id=org.id)

    # Compteur figé sur un engagement jamais libéré (l'état d'avant le correctif).
    poste.montant_engage = MONTANT * 3
    await db_session.flush()

    ecarts = await ecarts_engagement(db_session, tenant_id=org.id)
    assert len(ecarts) == 1
    assert ecarts[0]["montant_engage_stocke"] == MONTANT * 3
    assert ecarts[0]["montant_engage_theorique"] == MONTANT
    assert ecarts[0]["ecart"] == MONTANT * 2

    ajustes = await resynchroniser_engagements(db_session, tenant_id=org.id)
    assert ajustes == 1
    assert await _engage(db_session, poste) == MONTANT
