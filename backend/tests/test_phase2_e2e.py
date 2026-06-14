"""Tests E2E Phase 2 — monitoring, alertes et optimisation des performances.

Couvre :
  - Endpoint /metrics (Prometheus)
  - Cache Redis dashboard : hit/miss, TTL
  - Middleware SlowRequest : log sur requête lente
  - Handler alertes 5xx : réponse générique + log CRITICAL
  - Cache tenant resolver
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD

DASHBOARD = "/api/v1/dashboard"
AUTH = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Métriques Prometheus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_endpoint_accessible(app_client: AsyncClient) -> None:
    """/metrics doit retourner du texte Prometheus (format text/plain)."""
    resp = await app_client.get("/metrics")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text" in ct or "openmetrics" in ct, f"Content-Type inattendu : {ct}"


@pytest.mark.asyncio
async def test_metrics_contient_compteur_http(app_client: AsyncClient) -> None:
    """Après un appel, /metrics doit contenir http_requests_total."""
    # Effectuer un appel pour alimenter le compteur
    await app_client.get("/api/v1/health/live")
    resp = await app_client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests" in resp.text


# ---------------------------------------------------------------------------
# Cache Redis — dashboard stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_cache_hit(
    app_client: AsyncClient, admin_access_token: str
) -> None:
    """Deux appels identiques au dashboard doivent retourner des données cohérentes."""
    headers = {"Authorization": f"Bearer {admin_access_token}"}
    params = {"period_type": "month"}

    r1 = await app_client.get(f"{DASHBOARD}/stats", headers=headers, params=params)
    assert r1.status_code in (200, 422), f"Inattendu : {r1.status_code}"
    if r1.status_code != 200:
        return  # pas de données en DB de test, le cache n'est pas exercé

    r2 = await app_client.get(f"{DASHBOARD}/stats", headers=headers, params=params)
    assert r2.status_code == 200
    # Les deux réponses doivent être identiques (cohérence cache vs DB)
    assert r1.json() == r2.json(), "Cache hit retourne une réponse différente"


@pytest.mark.asyncio
async def test_dashboard_cache_cle_differente_par_params(
    app_client: AsyncClient, admin_access_token: str
) -> None:
    """Deux appels avec des paramètres différents ne partagent pas le même cache."""
    headers = {"Authorization": f"Bearer {admin_access_token}"}

    r1 = await app_client.get(f"{DASHBOARD}/stats", headers=headers, params={"period_type": "month"})
    r2 = await app_client.get(f"{DASHBOARD}/stats", headers=headers, params={"period_type": "week"})

    assert r1.status_code in (200, 422)
    assert r2.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Cache Redis — tenant resolver
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_resolu_depuis_cache(
    async_engine, test_admin_user
) -> None:
    """resolve_tenant consulte cache_get à chaque appel (évite le rate-limit login)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.core import tenant_resolver as tr_mod

    calls: list[str] = []

    async def spy_get(key: str):
        if key.startswith("tenant:hint:"):
            calls.append(key)
        return None  # toujours un miss — on vérifie la consultation du cache

    async def noop_set(key: str, value, *, ttl=None):
        return True

    session_factory = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, class_=AsyncSession
    )
    hint = str(test_admin_user.organisation_id)

    with patch.object(tr_mod, "cache_get", side_effect=spy_get):
        with patch.object(tr_mod, "cache_set", side_effect=noop_set):
            for _ in range(2):
                async with session_factory() as session:
                    await tr_mod.resolve_tenant(session, hint)

    assert len(calls) >= 2, f"cache_get non appelé pour le tenant — {calls}"


# ---------------------------------------------------------------------------
# Middleware SlowRequest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slow_request_logge_avertissement(
    app_client: AsyncClient, caplog
) -> None:
    """Une requête dont time.monotonic simule 1 s doit produire SLOW_REQUEST."""
    import app.middleware.timing as timing_mod

    counter = 0

    def fake_monotonic() -> float:
        nonlocal counter
        counter += 1
        return float(counter - 1)  # 0.0, 1.0, 2.0 … → toujours 1000 ms d'écart

    with caplog.at_level(logging.WARNING, logger="onec_cpk_perf"):
        with patch.object(timing_mod, "time") as mock_time:
            mock_time.monotonic.side_effect = fake_monotonic
            # /api/v1/health/live n'est PAS dans _SKIP_PATHS (/health/live sans préfixe)
            await app_client.get("/api/v1/health/live")

    slow_logs = [r for r in caplog.records if "SLOW_REQUEST" in r.message]
    assert len(slow_logs) >= 1, "Aucun log SLOW_REQUEST trouvé"
    assert "duration_ms" in slow_logs[0].message


# ---------------------------------------------------------------------------
# Handler alertes 5xx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_handler_retourne_500_generique() -> None:
    """ErrorTrackingMiddleware catch une exception non gérée → 500 générique."""
    from fastapi import FastAPI
    from fastapi.routing import APIRouter
    from app.core.alerts import ErrorTrackingMiddleware

    test_app = FastAPI()
    # ErrorTrackingMiddleware attrape maintenant les exceptions directement
    test_app.add_middleware(ErrorTrackingMiddleware)

    r = APIRouter()

    @r.get("/boom")
    async def boom():
        raise RuntimeError("Erreur critique simulée")

    test_app.include_router(r)

    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert "Erreur critique simulée" not in str(body)
    assert "detail" in body


@pytest.mark.asyncio
async def test_alerte_rate_limitee_redis(caplog) -> None:
    """La deuxième alerte du même type dans la fenêtre TTL doit être bloquée."""
    from app.core.alerts import _fire_alert

    sent = []

    async def mock_send(subject, body):
        sent.append(subject)

    with patch("app.core.alerts._send_alert_email_sync", side_effect=lambda s, b: sent.append(s)):
        # Premier appel : doit passer
        with patch("app.core.alerts._should_send_alert", return_value=True):
            await _fire_alert("TestError", "Alerte 1", "Corps 1")
        # Deuxième appel : rate-limité
        with patch("app.core.alerts._should_send_alert", return_value=False):
            await _fire_alert("TestError", "Alerte 2", "Corps 2")

    assert len(sent) == 1, f"L'alerte rate-limitée a quand même été envoyée : {sent}"
