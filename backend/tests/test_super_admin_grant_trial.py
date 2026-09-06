"""Tests super admin grant-trial endpoint + support_contact billing default."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.api.v1.endpoints.super_admin import grant_trial_subscription
from app.api.v1.endpoints.billing import get_billing_config
from app.models.organisation import Organisation
from app.models.platform_settings import PlatformSettings
from app.models.subscription import Subscription
from app.schemas.super_admin import GrantTrialRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_org(org_id: int = 1, plan_type: str = "FREE", status: str = "TRIAL") -> Organisation:
    now = _utcnow()
    return Organisation(
        id=org_id,
        uuid=uuid.uuid4(),
        nom=f"Province Test {org_id}",
        slug=f"province-test-{org_id}",
        plan_type=plan_type,
        status_abonnement=status,
        devise_preferee="USD",
        limite_utilisateurs=5,
        is_active=True,
        created_at=now,
        updated_at=now,
        billing_config=None,
    )


def _make_subscription(org_id: int) -> Subscription:
    now = _utcnow()
    sub = Subscription()
    sub.organisation_id = org_id
    sub.status = "PENDING"
    sub.created_at = now
    sub.updated_at = now
    return sub


def _make_db(org: Organisation | None, subscription: Subscription | None = None) -> AsyncMock:
    org_result = MagicMock()
    org_result.scalar_one_or_none.return_value = org

    # L'endpoint lit la grille tarifaire avant d'écrire le plan : sans cette
    # réponse, la requête du catalogue consommerait celle de l'abonnement.
    # `billing_config` vide = grille non saisie, donc plan resté libre — c'est
    # l'état que décrivent les cas ci-dessous.
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = PlatformSettings(
        id=1, billing_config={}
    )

    sub_scalars = MagicMock()
    sub_scalars.first.return_value = subscription
    sub_result = MagicMock()
    sub_result.scalars.return_value = sub_scalars

    count_result = MagicMock()
    count_result.scalar_one.return_value = 3

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[org_result, settings_result, sub_result, count_result])
    mock_db.commit = AsyncMock()
    return mock_db


# ── grant_trial_subscription() ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grant_trial_sets_plan_type_and_status():
    """grant-trial met à jour plan_type et status_abonnement."""
    org = _make_org(org_id=1, plan_type="FREE", status="PENDING")
    mock_db = _make_db(org)

    payload = GrantTrialRequest(plan_type="STANDARD", duration_days=30)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        result = await grant_trial_subscription(org_id=1, payload=payload, db=mock_db)

    assert result["ok"] is True
    assert result["plan_type"] == "STANDARD"
    assert result["status_abonnement"] == "TRIAL"
    assert result["duration_days"] == 30
    assert org.plan_type == "STANDARD"
    assert org.status_abonnement == "TRIAL"
    assert org.is_active is True


@pytest.mark.asyncio
async def test_grant_trial_sets_expiration_date():
    """grant-trial calcule la date d'expiration à partir de duration_days."""
    org = _make_org(org_id=2)
    mock_db = _make_db(org)

    before = _utcnow()
    payload = GrantTrialRequest(plan_type="FREE", duration_days=60)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        result = await grant_trial_subscription(org_id=2, payload=payload, db=mock_db)

    after = _utcnow()
    expires = datetime.fromisoformat(result["expires_at"])
    # Date doit être dans la fenêtre before+60j ... after+60j
    assert before + timedelta(days=59) < expires < after + timedelta(days=61)


@pytest.mark.asyncio
async def test_grant_trial_updates_subscription_if_exists():
    """grant-trial met à jour l'abonnement lié s'il existe."""
    org = _make_org(org_id=3)
    sub = _make_subscription(org_id=3)
    mock_db = _make_db(org, subscription=sub)

    payload = GrantTrialRequest(plan_type="PREMIUM", duration_days=14)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        await grant_trial_subscription(org_id=3, payload=payload, db=mock_db)

    assert sub.status == "TRIAL"
    assert sub.current_period_end is not None


@pytest.mark.asyncio
async def test_grant_trial_no_subscription_ok():
    """grant-trial fonctionne même sans abonnement lié (subscription=None)."""
    org = _make_org(org_id=4)
    mock_db = _make_db(org, subscription=None)

    payload = GrantTrialRequest(plan_type="FREE", duration_days=30)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        result = await grant_trial_subscription(org_id=4, payload=payload, db=mock_db)

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_grant_trial_logs_system_event():
    """grant-trial enregistre un SystemEvent avec les bonnes métadonnées."""
    org = _make_org(org_id=5)
    mock_db = _make_db(org)

    payload = GrantTrialRequest(plan_type="STANDARD", duration_days=45)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock) as mock_log:
        await grant_trial_subscription(org_id=5, payload=payload, db=mock_db)

    mock_log.assert_awaited_once()
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["code"] == "GRANT_TRIAL"
    assert call_kwargs["level"] == "info"
    assert call_kwargs["organisation_id"] == 5
    assert call_kwargs["metadata"]["plan_type"] == "STANDARD"
    assert call_kwargs["metadata"]["duration_days"] == 45


@pytest.mark.asyncio
async def test_grant_trial_404_when_org_not_found():
    """grant-trial retourne 404 si l'organisation n'existe pas."""
    from fastapi import HTTPException

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    payload = GrantTrialRequest(plan_type="FREE", duration_days=30)

    with pytest.raises(HTTPException) as exc_info:
        await grant_trial_subscription(org_id=999, payload=payload, db=mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_grant_trial_normalizes_plan_type_uppercase():
    """plan_type est normalisé en majuscules même si fourni en minuscules."""
    org = _make_org(org_id=6)
    mock_db = _make_db(org)

    payload = GrantTrialRequest(plan_type="standard", duration_days=30)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        result = await grant_trial_subscription(org_id=6, payload=payload, db=mock_db)

    assert result["plan_type"] == "STANDARD"
    assert org.plan_type == "STANDARD"


@pytest.mark.asyncio
async def test_grant_trial_commits_to_db():
    """grant-trial appelle bien db.commit() pour persister les changements."""
    org = _make_org(org_id=7)
    mock_db = _make_db(org)

    payload = GrantTrialRequest(plan_type="FREE", duration_days=30)

    with patch("app.api.v1.endpoints.super_admin.log_system_event", new_callable=AsyncMock):
        await grant_trial_subscription(org_id=7, payload=payload, db=mock_db)

    mock_db.commit.assert_awaited_once()


# ── GrantTrialRequest validation ──────────────────────────────────────────────

def test_grant_trial_request_defaults():
    """GrantTrialRequest a des valeurs par défaut sensées."""
    req = GrantTrialRequest()
    assert req.plan_type == "FREE"
    assert req.duration_days == 30


def test_grant_trial_request_validates_min_days():
    """duration_days doit être >= 1."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        GrantTrialRequest(plan_type="FREE", duration_days=0)


def test_grant_trial_request_validates_max_days():
    """duration_days doit être <= 365."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        GrantTrialRequest(plan_type="FREE", duration_days=366)


# ── Billing config default support_contact ────────────────────────────────────

@pytest.mark.asyncio
async def test_billing_config_injects_default_support_contact():
    """Quand org.billing_config n'a pas de support_contact, la valeur par défaut est injectée."""
    from app.models.organisation import Organisation as OrgModel
    now = datetime.now(timezone.utc)
    org = OrgModel(
        id=10,
        uuid=uuid.uuid4(),
        nom="Test",
        slug="test",
        plan_type="FREE",
        status_abonnement="TRIAL",
        devise_preferee="USD",
        limite_utilisateurs=2,
        is_active=True,
        created_at=now,
        updated_at=now,
        billing_config={"plan": {"name": "Free"}},  # pas de support_contact
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=10, db=mock_db)

    assert result.get("support_contact") == "kidikala@onerdc.com"


@pytest.mark.asyncio
async def test_billing_config_preserves_existing_support_contact():
    """La valeur support_contact existante n'est pas écrasée par le défaut."""
    from app.models.organisation import Organisation as OrgModel
    now = datetime.now(timezone.utc)
    org = OrgModel(
        id=11,
        uuid=uuid.uuid4(),
        nom="Test",
        slug="test",
        plan_type="STANDARD",
        status_abonnement="ACTIVE",
        devise_preferee="USD",
        limite_utilisateurs=5,
        is_active=True,
        created_at=now,
        updated_at=now,
        billing_config={"support_contact": "siege@onec.cd"},
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=11, db=mock_db)

    assert result.get("support_contact") == "siege@onec.cd"


@pytest.mark.asyncio
async def test_billing_config_default_support_contact_when_no_local_config():
    """Sans billing_config local du tout, le contact de support par défaut est retourné."""
    from app.models.organisation import Organisation as OrgModel
    now = datetime.now(timezone.utc)
    org = OrgModel(
        id=12,
        uuid=uuid.uuid4(),
        nom="Test",
        slug="test",
        plan_type="FREE",
        status_abonnement="TRIAL",
        devise_preferee="USD",
        limite_utilisateurs=2,
        is_active=True,
        created_at=now,
        updated_at=now,
        billing_config=None,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=12, db=mock_db)

    assert result.get("support_contact") == "kidikala@onerdc.com"
    assert result["configured"] is False
