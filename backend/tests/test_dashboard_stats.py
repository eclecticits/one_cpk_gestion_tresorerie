import uuid
from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete

from app.api.v1.endpoints.dashboard import stats as dashboard_stats
from app.api.v1.endpoints.encaissements import create_encaissement
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.payment import EncaissementCreate


@pytest.mark.asyncio
async def test_dashboard_stats_reflects_new_encaissement(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.commit()

    org = Organisation(nom="Dashboard Test", slug=f"dashboard-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="DASH-001",
        libelle="Poste dashboard",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="tester-dashboard@example.com", role="admin", organisation_id=org.id)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True))
    await db_session.flush()
    now = datetime.now(timezone.utc)

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-TEST-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="REC-TEST-0001",
        type_client="client_externe",
        expert_comptable_id=None,
        client_nom="Client Test",
        libelle="Encaissement test",
        description="Test dashboard stats",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        reference="REF-DASH",
        budget_poste_id=poste.id,
        date_encaissement=now,
    )

    await create_encaissement(payload=payload, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)

    date_str = now.strftime("%Y-%m-%d")
    res = await dashboard_stats(
        period_type="today",
        date_debut=date_str,
        date_fin=date_str,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert str(res.stats.total_encaissements_period) == "100.00"
    assert any(str(day.encaissements) == "100.00" for day in res.daily_stats)
