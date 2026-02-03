import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.api.v1.endpoints.dashboard import stats as dashboard_stats
from app.api.v1.endpoints.encaissements import create_encaissement
from app.models.encaissement import Encaissement
from app.models.user import User
from app.schemas.payment import EncaissementCreate


@pytest.mark.asyncio
async def test_dashboard_stats_reflects_new_encaissement(db_session):
    await db_session.execute(delete(Encaissement))
    await db_session.commit()

    user = User(id=uuid.uuid4(), email="tester-dashboard@example.com", role="admin")
    now = datetime.now(timezone.utc)

    payload = EncaissementCreate(
        numero_recu="REC-TEST-0001",
        type_client="client_externe",
        expert_comptable_id=None,
        client_nom="Client Test",
        type_operation="autre_encaissement",
        description="Test dashboard stats",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        reference="REF-DASH",
        date_encaissement=now,
    )

    await create_encaissement(payload=payload, user=user, db=db_session)

    date_str = now.strftime("%Y-%m-%d")
    res = await dashboard_stats(
        period_type="today",
        date_debut=date_str,
        date_fin=date_str,
        user=user,
        db=db_session,
    )

    assert res["stats"]["totalEncaissements"] == 100.0
    assert res["daily_stats"][-1]["encaissements"] == 100.0
