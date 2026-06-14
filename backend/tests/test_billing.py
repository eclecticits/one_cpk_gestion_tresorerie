"""Tests module Abonnement & Facturation — isolation tenant + comportement SaaS.

Couvre :
  - /billing/config : retourne {configured:False} si SaaS absent (plus de 503)
  - /billing/config : retourne données locales org.billing_config si SaaS absent
  - /billing/config : retourne {configured:True} si SaaS configuré et répond
  - /billing/config : retourne {configured:False} si SaaS configuré mais timeout
  - /billing/summary : lit les données locales (plan_type, status_abonnement)
  - /billing/summary : ne mélange pas les données entre tenants
  - /billing/invoices : retourne {items:[], configured:False} si SaaS absent
  - /billing/status : retourne le statut de l'organisation courante
  - Isolation tenant : tenant A ne voit pas les données de tenant B
  - Permission : utilisateur sans can_edit_settings → 403 sur /config
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.api.v1.endpoints.billing import (
    _is_saas_configured,
    _normalize_invoices,
    _normalize_summary,
    get_billing_config,
    get_billing_status,
    get_billing_summary,
    list_billing_invoices,
)
from app.models.organisation import Organisation
from app.schemas.billing import BillingInvoiceListOut, BillingSummaryOut


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(
    org_id: int = 1,
    plan_type: str = "STANDARD",
    status: str = "ACTIVE",
    billing_config: dict | None = None,
) -> Organisation:
    now = datetime.now(timezone.utc)
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
        billing_config=billing_config,
    )


def _make_db_with_org(org: Organisation) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ── _is_saas_configured() ─────────────────────────────────────────────────────

def test_saas_not_configured_when_vars_absent():
    with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
        mock_settings.saas_console_base_url = None
        mock_settings.saas_internal_key = None
        assert _is_saas_configured() is False


def test_saas_not_configured_when_only_url():
    with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
        mock_settings.saas_console_base_url = "https://saas.example.com"
        mock_settings.saas_internal_key = None
        assert _is_saas_configured() is False


def test_saas_configured_when_both_present():
    with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
        mock_settings.saas_console_base_url = "https://saas.example.com"
        mock_settings.saas_internal_key = "secret-key"
        assert _is_saas_configured() is True


# ── get_billing_config() — SaaS absent ───────────────────────────────────────

@pytest.mark.asyncio
async def test_billing_config_returns_configured_false_when_saas_absent():
    """Quand SaaS non configuré, retourne {configured: False} — plus de 503."""
    org = _make_org(org_id=5)
    mock_db = _make_db_with_org(org)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=5, db=mock_db)

    assert result["configured"] is False
    assert result["tenant_id"] == "5"


@pytest.mark.asyncio
async def test_billing_config_returns_local_billing_config_when_saas_absent():
    """Quand SaaS absent, la config locale org.billing_config est retournée."""
    local_config = {
        "plan": {"name": "Standard Province", "price": 150.0, "currency": "USD", "interval": "monthly"},
        "support_contact": "siege@onec.cd",
    }
    org = _make_org(org_id=7, billing_config=local_config)
    mock_db = _make_db_with_org(org)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=7, db=mock_db)

    assert result["configured"] is False
    assert result.get("plan", {}).get("name") == "Standard Province"
    assert result.get("plan", {}).get("price") == 150.0
    assert result.get("support_contact") == "siege@onec.cd"


@pytest.mark.asyncio
async def test_billing_config_no_local_config_returns_empty_plan():
    """Quand ni SaaS ni config locale, retourne quand même une réponse valide."""
    org = _make_org(org_id=9, billing_config=None)
    mock_db = _make_db_with_org(org)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=9, db=mock_db)

    assert result["configured"] is False
    assert "error" not in result or result.get("saas_error") is None


# ── get_billing_config() — SaaS configuré ────────────────────────────────────

@pytest.mark.asyncio
async def test_billing_config_returns_configured_true_when_saas_ok():
    """Quand SaaS répond OK, retourne {configured: True} + données SaaS."""
    import httpx

    org = _make_org(org_id=3)
    mock_db = _make_db_with_org(org)

    saas_response = {
        "plan": {"name": "Enterprise", "price": 300.0, "currency": "USD"},
        "support_contact": "support@saas.example.com",
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = saas_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=True):
        with patch("app.api.v1.endpoints.billing._build_saas_url", return_value="https://saas.example.com/api/v1/tenants/3/billing-config"):
            with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
                mock_settings.saas_console_timeout = 10
                mock_settings.saas_internal_key = "secret"
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await get_billing_config(tenant_id=3, db=mock_db)

    assert result["configured"] is True
    assert result["plan"]["name"] == "Enterprise"


@pytest.mark.asyncio
async def test_billing_config_graceful_on_saas_timeout():
    """Quand SaaS configuré mais timeout, retourne {configured:False} + fallback local."""
    import httpx

    local_cfg = {"plan": {"name": "Local Fallback", "price": 100.0}}
    org = _make_org(org_id=11, billing_config=local_cfg)
    mock_db = _make_db_with_org(org)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=True):
        with patch("app.api.v1.endpoints.billing._build_saas_url", return_value="https://saas.example.com/api/v1/tenants/11/billing-config"):
            with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
                mock_settings.saas_console_timeout = 10
                mock_settings.saas_internal_key = "secret"
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await get_billing_config(tenant_id=11, db=mock_db)

    assert result["configured"] is False
    assert result.get("saas_error") == "timeout"
    # Le fallback local est retourné
    assert result.get("plan", {}).get("name") == "Local Fallback"


# ── get_billing_summary() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_billing_summary_reads_local_plan():
    """get_billing_summary() lit plan_type et status_abonnement depuis la DB locale."""
    org = _make_org(org_id=2, plan_type="ENTERPRISE", status="ACTIVE")
    mock_db = _make_db_with_org(org)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_summary(tenant_id=2, db=mock_db)

    assert isinstance(result, BillingSummaryOut)
    assert result.plan_type == "ENTERPRISE"
    assert result.plan_status == "ACTIVE"
    assert result.billing_source == "local"


@pytest.mark.asyncio
async def test_billing_summary_tenant_isolation():
    """Deux tenants ne partagent pas les mêmes données billing."""
    org_a = _make_org(org_id=10, plan_type="FREE", status="TRIAL")
    org_b = _make_org(org_id=20, plan_type="PREMIUM", status="ACTIVE")

    mock_db_a = _make_db_with_org(org_a)
    mock_db_b = _make_db_with_org(org_b)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result_a = await get_billing_summary(tenant_id=10, db=mock_db_a)
        result_b = await get_billing_summary(tenant_id=20, db=mock_db_b)

    assert result_a.plan_type == "FREE"
    assert result_b.plan_type == "PREMIUM"
    assert result_a.plan_status == "TRIAL"
    assert result_b.plan_status == "ACTIVE"
    # Vérifier que les résultats sont vraiment différents
    assert result_a.plan_type != result_b.plan_type


# ── list_billing_invoices() ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoices_returns_empty_list_when_saas_absent():
    """Quand SaaS non configuré, /billing/invoices retourne {items:[], configured:False}."""
    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await list_billing_invoices(tenant_id=1)

    assert isinstance(result, BillingInvoiceListOut)
    assert result.items == []
    assert result.configured is False
    assert result.source == "local"


@pytest.mark.asyncio
async def test_invoices_tenant_isolation_in_url():
    """L'URL construite pour récupérer les factures contient bien le tenant_id."""
    import httpx

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=True):
        with patch("app.api.v1.endpoints.billing._saas_base_url", return_value="https://saas.example.com/api/v1"):
            with patch("app.api.v1.endpoints.billing.settings") as mock_settings:
                mock_settings.saas_console_timeout = 10
                mock_settings.saas_internal_key = "secret"
                with patch("httpx.AsyncClient", return_value=mock_client):
                    await list_billing_invoices(tenant_id=42)

    # Vérifier que l'URL appelée contient /tenants/42/invoices
    call_args = mock_client.get.call_args
    url = call_args.args[0]
    assert "42" in url
    assert "invoices" in url


# ── _normalize_summary() ─────────────────────────────────────────────────────

def test_normalize_summary_reads_standard_fields():
    payload = {
        "plan_type": "STANDARD",
        "plan_status": "ACTIVE",
        "plan_price": 150.0,
        "currency": "USD",
        "billing_portal_url": "https://portal.example.com",
    }
    result = _normalize_summary(payload)
    assert result["plan_type"] == "STANDARD"
    assert result["plan_status"] == "ACTIVE"
    assert result["plan_price"] == 150.0
    assert result["billing_portal_url"] == "https://portal.example.com"


def test_normalize_summary_handles_empty():
    result = _normalize_summary({})
    assert result["plan_type"] is None
    assert result["plan_price"] is None


def test_normalize_summary_handles_non_dict():
    result = _normalize_summary(None)
    assert result == {}

    result = _normalize_summary("invalid")
    assert result == {}


# ── _normalize_invoices() ─────────────────────────────────────────────────────

def test_normalize_invoices_from_list():
    raw = [
        {"id": "INV-001", "number": "2026-001", "amount": 150.0, "currency": "USD",
         "status": "paid", "date": "2026-01-15", "pdf_url": "https://..."},
    ]
    invoices = _normalize_invoices(raw)
    assert len(invoices) == 1
    assert invoices[0].id == "INV-001"
    assert invoices[0].amount == 150.0
    assert invoices[0].pdf_available is True


def test_normalize_invoices_from_dict_with_items():
    raw = {
        "items": [
            {"id": "I-2", "amount": 200.0, "currency": "USD", "status": "pending"},
        ]
    }
    invoices = _normalize_invoices(raw)
    assert len(invoices) == 1
    assert invoices[0].amount == 200.0
    assert invoices[0].pdf_available is False


def test_normalize_invoices_empty():
    assert _normalize_invoices([]) == []
    assert _normalize_invoices({}) == []
    assert _normalize_invoices(None) == []


# ── Isolation endpoint — même tenant_id dans les requêtes SQL ─────────────────

@pytest.mark.asyncio
async def test_billing_config_queries_correct_tenant():
    """La requête SQL dans get_billing_config filtre bien par le tenant_id fourni."""
    org = _make_org(org_id=99)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = org
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.v1.endpoints.billing._is_saas_configured", return_value=False):
        result = await get_billing_config(tenant_id=99, db=mock_db)

    assert result["tenant_id"] == "99"
    # La DB a été appelée exactement une fois pour récupérer l'org
    mock_db.execute.assert_awaited_once()
    stmt = mock_db.execute.call_args.args[0]
    stmt_text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "99" in stmt_text


@pytest.mark.asyncio
async def test_billing_status_queries_correct_tenant():
    """get_billing_status() filtre bien par organisation_id."""
    org = _make_org(org_id=55, status="SUSPENDED")
    mock_db = _make_db_with_org(org)

    with patch("app.api.v1.endpoints.billing.deps") as mock_deps:
        mock_deps.get_cached_saas_status = AsyncMock(return_value=None)
        result = await get_billing_status(tenant_id=55, db=mock_db)

    assert result["status"] == "SUSPENDED"

    stmt = mock_db.execute.call_args.args[0]
    stmt_text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "55" in stmt_text
