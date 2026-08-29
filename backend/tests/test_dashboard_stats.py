import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete

from app.api.v1.endpoints.dashboard import stats as dashboard_stats
from app.api.v1.endpoints.encaissements import create_encaissement
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
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


async def _disable_dashboard_cache(monkeypatch):
    async def fake_get(*args, **kwargs):
        return None

    async def fake_set(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.dashboard.cache_get", fake_get)
    monkeypatch.setattr("app.api.v1.endpoints.dashboard.cache_set", fake_set)


@pytest.mark.asyncio
async def test_dashboard_stats_deduit_retours_des_sorties_periodiques(db_session, monkeypatch):
    await _disable_dashboard_cache(monkeypatch)
    org = Organisation(nom="Dashboard Retours", slug=f"dash-retours-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    user = User(id=uuid.uuid4(), email=f"dash-retours-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    db_session.add(user)
    db_session.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("36719.96"), est_ouverte=True))
    op_date = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    enc = Encaissement(
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client août",
        libelle="Recette économique",
        montant=Decimal("500.00"),
        montant_total=Decimal("500.00"),
        montant_paye=Decimal("500.00"),
        montant_percu=Decimal("500.00"),
        devise_perception="USD",
        canal="CAISSE",
        statut_paiement="complet",
        mode_paiement="cash",
        est_proforma=False,
        is_deleted=False,
        statut_operation="ACTIVE",
        date_encaissement=op_date,
    )
    sortie = SortieFonds(
        organisation_id=org.id,
        type_sortie="autre",
        montant_paye=Decimal("193511.91"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Sorties brutes août",
        beneficiaire="Fournisseurs",
        statut="VALIDE",
        date_paiement=op_date,
        created_by=user.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )
    db_session.add_all([enc, sortie])
    await db_session.flush()
    db_session.add(
        RetourCaisse(
            organisation_id=org.id,
            sortie_fonds_id=sortie.id,
            type_retour="reliquat_avance",
            montant=Decimal("11316.00"),
            devise="USD",
            canal="CAISSE",
            mode="cash",
            reference_numero=f"RET-{uuid.uuid4().hex[:8]}",
            motif="Retours août",
            date_retour=op_date,
            statut="VALIDE",
            created_by=user.id,
        )
    )
    await db_session.commit()

    periods = [
        ("today", "2026-08-27", "2026-08-27"),
        ("week", "2026-08-24", "2026-08-30"),
        ("month", "2026-08-01", "2026-08-31"),
        ("year", "2026-01-01", "2026-12-31"),
        ("custom", "2026-01-01", "2026-08-28"),
    ]
    for period_type, date_debut, date_fin in periods:
        res = await dashboard_stats(
            period_type=period_type,
            date_debut=date_debut,
            date_fin=date_fin,
            tenant_id=org.id,
            user=user,
            db=db_session,
        )
        assert res.stats.total_encaissements_period == Decimal("500.00")
        assert res.stats.total_sorties_brutes_period == Decimal("193511.91")
        assert res.stats.total_retours_period == Decimal("11316.00")
        assert res.stats.total_sorties_nettes_period == Decimal("182195.91")
        assert res.stats.total_sorties_period == Decimal("182195.91")
        assert res.stats.solde_period == Decimal("-181695.91")


@pytest.mark.asyncio
async def test_dashboard_stats_deduit_retours_des_sorties_du_jour(db_session, monkeypatch):
    await _disable_dashboard_cache(monkeypatch)
    org = Organisation(nom="Dashboard Jour", slug=f"dash-jour-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    user = User(id=uuid.uuid4(), email=f"dash-jour-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    db_session.add(user)
    db_session.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True))
    now = datetime.now(timezone.utc)
    sortie = SortieFonds(
        organisation_id=org.id,
        type_sortie="autre",
        montant_paye=Decimal("100.00"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Sortie du jour",
        beneficiaire="Fournisseur",
        statut="VALIDE",
        date_paiement=now,
        created_by=user.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(sortie)
    await db_session.flush()
    db_session.add(
        RetourCaisse(
            organisation_id=org.id,
            sortie_fonds_id=sortie.id,
            montant=Decimal("25.00"),
            devise="USD",
            canal="CAISSE",
            mode="cash",
            reference_numero=f"RET-{uuid.uuid4().hex[:8]}",
            motif="Retour du jour",
            date_retour=now,
            statut="VALIDE",
            created_by=user.id,
        )
    )
    await db_session.commit()

    date_str = now.strftime("%Y-%m-%d")
    res = await dashboard_stats(
        period_type="today",
        date_debut=date_str,
        date_fin=date_str,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert res.stats.total_sorties_brutes_jour == Decimal("100.00")
    assert res.stats.total_retours_jour == Decimal("25.00")
    assert res.stats.total_sorties_nettes_jour == Decimal("75.00")
    assert res.stats.total_sorties_jour == Decimal("75.00")
    assert res.stats.solde_jour == Decimal("-75.00")
