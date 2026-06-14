import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from fastapi import HTTPException

from app.api.v1.endpoints.encaissements import create_encaissement, list_encaissements
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.payment import EncaissementCreate


@pytest.mark.asyncio
async def test_create_and_list_encaissement_with_expert(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement Test", slug=f"enc-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-001",
        libelle="Poste encaissement",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    expert = ExpertComptable(
        numero_ordre="EC-001",
        nom_denomination="Cabinet Alpha",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.commit()
    await db_session.refresh(expert)

    user = User(id=uuid.uuid4(), email="tester@example.com", role="admin", organisation_id=org.id)

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-20260127-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="REC-20260127-0001",
        type_client="expert_comptable",
        expert_comptable_id=str(expert.id),
        client_nom=None,
        libelle="Cotisation annuelle",
        description="Test encaissement",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        reference="REF-001",
        budget_poste_id=poste.id,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    created = await create_encaissement(payload=payload, user=user, tenant_id=org.id, db=db_session)
    assert created["numero_recu"] == "REC-20260127-0001"
    assert created["expert_comptable"]["numero_ordre"] == "EC-001"

    results = await list_encaissements(
        include="expert_comptable",
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0]["expert_comptable"]["nom_denomination"] == "Cabinet Alpha"


@pytest.mark.asyncio
async def test_filters_and_pagination(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement List", slug=f"enc-list-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-LIST-001",
        libelle="Poste liste",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="tester2@example.com", role="admin", organisation_id=org.id)

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-20260127-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    for idx in range(3):
        enc = Encaissement(
            numero_recu=f"REC-20260127-00{idx+2}",
            organisation_id=org.id,
            type_client="client_externe",
            client_nom=f"Client {idx}",
            libelle=f"Libellé {idx}",
            description=None,
            montant=50,
            montant_total=50,
            montant_paye=25 if idx == 0 else 50,
            statut_paiement="partiel" if idx == 0 else "complet",
            mode_paiement="cash",
            reference=None,
            date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
            created_by=user.id,
            budget_poste_id=poste.id,
        )
        db_session.add(enc)
    await db_session.commit()

    results = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(results) == 3

    paged = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        limit=1,
        offset=1,
        order="numero_recu.asc",
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(paged) == 1

    filtered = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        numero_recu="REC-20260127-003",
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_create_encaissement_retries_on_duplicate_numero(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement Retry", slug=f"enc-retry-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-RETRY-001",
        libelle="Poste retry",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="tester3@example.com", role="admin", organisation_id=org.id)

    existing = Encaissement(
        numero_recu="REC-20260127-0001",
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client A",
        libelle="Formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
        created_by=user.id,
        budget_poste_id=poste.id,
    )
    db_session.add(existing)
    await db_session.commit()

    attempts = {"count": 0}

    async def fake_generate_numero_recu(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return "REC-20260127-0001"
        return "REC-20260127-0002"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="",
        type_client="client_externe",
        client_nom="Client B",
        libelle="Formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        budget_poste_id=poste.id,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    try:
        created = await create_encaissement(payload=payload, user=user, tenant_id=org.id, db=db_session)
        assert created["numero_recu"] == "REC-20260127-0002"
    except HTTPException as exc:
        assert exc.status_code == 409
