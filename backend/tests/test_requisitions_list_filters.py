"""Tests E2E du filtrage de la liste des réquisitions (service_id, budget_poste_id)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.service import Service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_requisition(db_session, *, organisation_id: int, service_id: int, budget_poste_id: int):
    req = Requisition(
        numero_requisition=f"REQ-FLT-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REQ-FLT-{uuid.uuid4().hex[:8]}",
        objet="Réquisition filtre test",
        mode_paiement="cash",
        type_requisition="classique",
        status="BROUILLON",
        examen_status="NON_EXAMINE",
        montant_total=Decimal("50.00"),
        organisation_id=organisation_id,
        service_id=service_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        is_deleted=False,
    )
    db_session.add(req)
    await db_session.flush()
    db_session.add(
        LigneRequisition(
            organisation_id=organisation_id,
            requisition_id=req.id,
            budget_poste_id=budget_poste_id,
            rubrique="Test filtre",
            description="Ligne filtre test",
            quantite=1,
            montant_unitaire=Decimal("50.00"),
            montant_total=Decimal("50.00"),
            devise="USD",
        )
    )
    await db_session.flush()
    return req


@pytest.mark.asyncio
async def test_list_requisitions_filters_by_budget_poste_and_service(
    app_client: AsyncClient, admin_access_token: str, test_organisation, db_session
):
    org_id = test_organisation.id

    service_a = Service(code=f"SRVA-{uuid.uuid4().hex[:6]}", libelle="Service A", organisation_id=org_id)
    service_b = Service(code=f"SRVB-{uuid.uuid4().hex[:6]}", libelle="Service B", organisation_id=org_id)
    db_session.add_all([service_a, service_b])
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org_id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    poste_1 = BudgetPoste(
        organisation_id=org_id,
        exercice_id=exercice.id,
        code=f"FLT-{uuid.uuid4().hex[:6]}",
        libelle="Poste filtre 1",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("1000"),
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
        is_deleted=False,
    )
    poste_2 = BudgetPoste(
        organisation_id=org_id,
        exercice_id=exercice.id,
        code=f"FLT-{uuid.uuid4().hex[:6]}",
        libelle="Poste filtre 2",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("1000"),
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
        is_deleted=False,
    )
    db_session.add_all([poste_1, poste_2])
    await db_session.flush()

    req_1 = await _seed_requisition(
        db_session, organisation_id=org_id, service_id=service_a.id, budget_poste_id=poste_1.id
    )
    req_2 = await _seed_requisition(
        db_session, organisation_id=org_id, service_id=service_b.id, budget_poste_id=poste_2.id
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {admin_access_token}"}

    # Filtre par poste budgétaire : seule la réquisition dont une ligne référence le poste sort.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"budget_poste_id": poste_1.id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert str(req_1.id) in ids
    assert str(req_2.id) not in ids

    # Filtre par service : seule la réquisition du service demandé sort.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"service_id": service_b.id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert str(req_2.id) in ids
    assert str(req_1.id) not in ids

    # Filtres combinés incompatibles : aucun résultat.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"budget_poste_id": poste_1.id, "service_id": service_b.id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert str(req_1.id) not in ids
    assert str(req_2.id) not in ids
