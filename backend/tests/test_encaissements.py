import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from fastapi import HTTPException

from app.api.v1.endpoints.encaissements import create_encaissement, list_encaissements
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.user import User
from app.schemas.payment import EncaissementCreate


@pytest.mark.asyncio
async def test_create_and_list_encaissement_with_expert(db_session):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    expert = ExpertComptable(
        numero_ordre="EC-001",
        nom_denomination="Cabinet Alpha",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.commit()
    await db_session.refresh(expert)

    user = User(id=uuid.uuid4(), email="tester@example.com", role="admin")

    payload = EncaissementCreate(
        numero_recu="REC-20260127-0001",
        type_client="expert_comptable",
        expert_comptable_id=str(expert.id),
        client_nom=None,
        type_operation="cotisation_annuelle",
        description="Test encaissement",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        reference="REF-001",
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    created = await create_encaissement(payload=payload, user=user, db=db_session)
    assert created["numero_recu"] == "REC-20260127-0001"
    assert created["expert_comptable"]["numero_ordre"] == "EC-001"

    results = await list_encaissements(
        include="expert_comptable",
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        type_client=None,
        mode_paiement=None,
        expert_comptable_id=None,
        order=None,
        limit=10,
        offset=0,
        user=user,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0]["expert_comptable"]["nom_denomination"] == "Cabinet Alpha"


@pytest.mark.asyncio
async def test_filters_and_pagination(db_session):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    user = User(id=uuid.uuid4(), email="tester2@example.com", role="admin")

    for idx in range(3):
        enc = Encaissement(
            numero_recu=f"REC-20260127-00{idx+2}",
            type_client="client_externe",
            client_nom=f"Client {idx}",
            type_operation="formation" if idx % 2 == 0 else "livre",
            description=None,
            montant=50,
            montant_total=50,
            montant_paye=25 if idx == 0 else 50,
            statut_paiement="partiel" if idx == 0 else "complet",
            mode_paiement="cash",
            reference=None,
            date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
            created_by=user.id,
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
        type_client=None,
        mode_paiement=None,
        expert_comptable_id=None,
        order=None,
        type_operation="formation",
        limit=10,
        offset=0,
        user=user,
        db=db_session,
    )
    assert len(results) == 2

    paged = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        type_client=None,
        mode_paiement=None,
        expert_comptable_id=None,
        limit=1,
        offset=1,
        order="numero_recu.asc",
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
        type_client=None,
        mode_paiement=None,
        expert_comptable_id=None,
        order=None,
        numero_recu="REC-20260127-003",
        limit=10,
        offset=0,
        user=user,
        db=db_session,
    )
    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_create_encaissement_retries_on_duplicate_numero(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    user = User(id=uuid.uuid4(), email="tester3@example.com", role="admin")

    existing = Encaissement(
        numero_recu="REC-20260127-0001",
        type_client="client_externe",
        client_nom="Client A",
        type_operation="formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
        created_by=user.id,
    )
    db_session.add(existing)
    await db_session.commit()

    attempts = {"count": 0}

    async def fake_generate_numero_recu(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return "REC-20260127-0001"
        return "REC-20260127-0002"

    monkeypatch.setattr(
        "app.api.v1.endpoints.encaissements.generate_numero_recu",
        fake_generate_numero_recu,
    )

    payload = EncaissementCreate(
        numero_recu="",
        type_client="client_externe",
        client_nom="Client B",
        type_operation="formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    try:
        created = await create_encaissement(payload=payload, user=user, db=db_session)
        assert created["numero_recu"] == "REC-20260127-0002"
    except HTTPException as exc:
        assert exc.status_code == 409
