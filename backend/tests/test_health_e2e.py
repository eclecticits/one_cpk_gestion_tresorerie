"""Tests E2E Phase 1 — health checks.

Format attendu de /health/ready :
  {"status": "ok|degraded", "database": "ok|error: ...", "redis": "ok|error: ..."}
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_live(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_backward_compat(app_client: AsyncClient) -> None:
    """La route /health historique doit toujours retourner 200."""
    resp = await app_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_structure(app_client: AsyncClient) -> None:
    """La réponse /health/ready doit toujours contenir status, database et redis."""
    resp = await app_client.get("/api/v1/health/ready")
    body = resp.json()
    assert "status" in body
    assert "database" in body
    assert "redis" in body
    # Le status global doit être "ok" ou "degraded"
    assert body["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_health_ready_redis_ok(app_client: AsyncClient) -> None:
    """Redis est mocké à True dans app_client : le champ redis doit valoir 'ok'."""
    resp = await app_client.get("/api/v1/health/ready")
    body = resp.json()
    assert body["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_http_status(app_client: AsyncClient) -> None:
    """Si tout est OK → 200. Si dégradé → 503. Le code doit être cohérent."""
    resp = await app_client.get("/api/v1/health/ready")
    body = resp.json()
    if body["status"] == "ok":
        assert resp.status_code == 200
    else:
        assert resp.status_code == 503
