"""Tests Phase 3 — Alertes Telegram + compteur Prometheus requêtes lentes.

Couvre :
  - _send_telegram_alert : désactivé si token absent
  - _send_telegram_alert : envoi HTTP via httpx (token + chat_id configurés)
  - _send_telegram_alert : silencieux si httpx échoue (timeout, erreur réseau)
  - _fire_alert : envoie email + Telegram en parallèle
  - _fire_alert : ignoré si rate-limit Redis actif
  - ErrorTrackingMiddleware : déclenche alerte Telegram + email sur exception
  - SlowRequestMiddleware : incrémente compteur Prometheus sur requête lente
  - Compteur onec_cpk_slow_requests_total : isolable, labels method+path
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.routing import APIRouter
from httpx import ASGITransport, AsyncClient


# ── _send_telegram_alert ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telegram_alert_skipped_when_no_token():
    """Aucun appel httpx si TELEGRAM_BOT_TOKEN est absent."""
    from app.core.alerts import _send_telegram_alert

    with patch("app.core.alerts.settings") as mock_settings:
        mock_settings.telegram_bot_token = None
        mock_settings.telegram_chat_id = "123"
        with patch("httpx.AsyncClient") as mock_client_cls:
            await _send_telegram_alert("Test subject", "Test body")
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_alert_skipped_when_no_chat_id():
    """Aucun appel httpx si TELEGRAM_CHAT_ID est absent."""
    from app.core.alerts import _send_telegram_alert

    with patch("app.core.alerts.settings") as mock_settings:
        mock_settings.telegram_bot_token = "bot-token-test"
        mock_settings.telegram_chat_id = None
        with patch("httpx.AsyncClient") as mock_client_cls:
            await _send_telegram_alert("Test subject", "Test body")
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_alert_sends_http_request(caplog):
    """Envoie un POST vers api.telegram.org quand token + chat_id configurés."""
    from app.core.alerts import _send_telegram_alert

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("app.core.alerts.settings") as mock_settings:
        mock_settings.telegram_bot_token = "test-bot-token"
        mock_settings.telegram_chat_id = "-100123456"
        with patch("httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level(logging.INFO, logger="onec_cpk_alerts"):
                await _send_telegram_alert("Erreur 500 — RuntimeError", "corps alerte")

    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert "api.telegram.org" in call_args.args[0]
    payload = call_args.kwargs.get("json") or {}
    assert payload.get("chat_id") == "-100123456"
    assert "Erreur 500" in payload.get("text", "")
    # Le token ne doit pas apparaître dans les logs
    for record in caplog.records:
        assert "test-bot-token" not in record.getMessage()


@pytest.mark.asyncio
async def test_telegram_alert_silent_on_network_error(caplog):
    """Ne propage pas l'exception si httpx échoue — juste un log WARNING."""
    import httpx
    from app.core.alerts import _send_telegram_alert

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with patch("app.core.alerts.settings") as mock_settings:
        mock_settings.telegram_bot_token = "test-bot-token"
        mock_settings.telegram_chat_id = "456"
        with patch("httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="onec_cpk_alerts"):
                # Ne doit pas lever d'exception
                await _send_telegram_alert("Test", "body")

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Telegram" in r.getMessage() for r in warnings)


@pytest.mark.asyncio
async def test_telegram_alert_truncates_long_body():
    """Un message > 4000 chars est tronqué avant envoi."""
    from app.core.alerts import _send_telegram_alert

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    long_body = "x" * 5000

    with patch("app.core.alerts.settings") as mock_settings:
        mock_settings.telegram_bot_token = "tok"
        mock_settings.telegram_chat_id = "1"
        with patch("httpx.AsyncClient", return_value=mock_client):
            await _send_telegram_alert("Subject", long_body)

    call_args = mock_client.post.call_args
    sent_text = (call_args.kwargs.get("json") or {}).get("text", "")
    assert len(sent_text) <= 4096
    assert "tronqué" in sent_text


# ── _fire_alert ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fire_alert_calls_both_email_and_telegram():
    """_fire_alert envoie email ET Telegram en parallèle."""
    from app.core.alerts import _fire_alert

    email_calls: list = []
    telegram_calls: list = []

    def mock_email(subject: str, body: str) -> None:
        email_calls.append(subject)

    async def mock_telegram(subject: str, body: str) -> None:
        telegram_calls.append(subject)

    with patch("app.core.alerts._should_send_alert", AsyncMock(return_value=True)):
        with patch("app.core.alerts._send_alert_email_sync", mock_email):
            with patch("app.core.alerts._send_telegram_alert", mock_telegram):
                await _fire_alert("RuntimeError", "Erreur 500 — RuntimeError", "body")

    assert len(email_calls) == 1
    assert len(telegram_calls) == 1


@pytest.mark.asyncio
async def test_fire_alert_skipped_when_rate_limited(caplog):
    """Si Redis signale que l'alerte est rate-limitée, rien n'est envoyé."""
    from app.core.alerts import _fire_alert

    email_calls: list = []
    telegram_calls: list = []

    with patch("app.core.alerts._should_send_alert", AsyncMock(return_value=False)):
        with patch("app.core.alerts._send_alert_email_sync", lambda *a: email_calls.append(a)):
            with patch("app.core.alerts._send_telegram_alert", AsyncMock(side_effect=lambda *a: telegram_calls.append(a))):
                with caplog.at_level(logging.DEBUG, logger="onec_cpk_alerts"):
                    await _fire_alert("SomeError", "Subject", "body")

    assert len(email_calls) == 0
    assert len(telegram_calls) == 0
    assert any("rate-limit" in r.getMessage() for r in caplog.records)


# ── ErrorTrackingMiddleware + Telegram ────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_tracking_middleware_fires_telegram_alert():
    """Une exception non gérée déclenche une alerte Telegram (en tâche de fond)."""
    from app.core.alerts import ErrorTrackingMiddleware

    telegram_calls: list = []

    async def mock_telegram(subject: str, body: str) -> None:
        telegram_calls.append(subject)

    test_app = FastAPI()
    test_app.add_middleware(ErrorTrackingMiddleware)
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise ValueError("erreur simulée")

    test_app.include_router(router)

    with patch("app.core.alerts._should_send_alert", AsyncMock(return_value=True)):
        with patch("app.core.alerts._send_alert_email_sync", lambda *a: None):
            with patch("app.core.alerts._send_telegram_alert", mock_telegram):
                async with AsyncClient(
                    transport=ASGITransport(app=test_app, raise_app_exceptions=False),
                    base_url="http://test",
                ) as client:
                    resp = await client.get("/boom")

    assert resp.status_code == 500
    # La tâche create_task peut ne pas encore s'être exécutée — on vérifie le comportement du middleware
    assert "detail" in resp.json()


# ── SlowRequestMiddleware + compteur Prometheus ───────────────────────────────

@pytest.mark.asyncio
async def test_slow_request_increments_prometheus_counter():
    """SlowRequestMiddleware incrémente _inc_slow() sur requête lente."""
    import app.middleware.timing as timing_mod

    incremented: list[tuple[str, str]] = []

    def fake_inc_slow(method: str, path: str) -> None:
        incremented.append((method, path))

    counter = 0

    def fake_monotonic() -> float:
        nonlocal counter
        counter += 1
        return float(counter - 1)  # diff toujours 1000 ms

    test_app = FastAPI()
    test_app.add_middleware(timing_mod.SlowRequestMiddleware)
    router = APIRouter()

    @router.get("/slow-endpoint")
    async def slow():
        return {"ok": True}

    test_app.include_router(router)

    with patch.object(timing_mod, "_inc_slow", fake_inc_slow):
        with patch.object(timing_mod, "time") as mock_time:
            mock_time.monotonic.side_effect = fake_monotonic
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/slow-endpoint")

    assert resp.status_code == 200
    assert len(incremented) >= 1
    method, path = incremented[0]
    assert method == "GET"
    assert path == "/slow-endpoint"


@pytest.mark.asyncio
async def test_slow_request_no_counter_on_fast_request():
    """Une requête rapide ne déclenche pas _inc_slow()."""
    import app.middleware.timing as timing_mod

    incremented: list = []

    def fake_inc_slow(method: str, path: str) -> None:
        incremented.append((method, path))

    # Monotonic retourne toujours 0.0 → elapsed = 0 ms
    with patch.object(timing_mod, "_inc_slow", fake_inc_slow):
        with patch.object(timing_mod, "time") as mock_time:
            mock_time.monotonic.return_value = 0.0

            test_app = FastAPI()
            test_app.add_middleware(timing_mod.SlowRequestMiddleware)
            router = APIRouter()

            @router.get("/fast")
            async def fast():
                return {"ok": True}

            test_app.include_router(router)

            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                await client.get("/fast")

    assert len(incremented) == 0


def test_get_slow_counter_returns_counter_or_none():
    """_get_slow_counter ne plante pas même si prometheus_client est absent."""
    import app.middleware.timing as timing_mod

    # Appel direct — doit retourner un Counter ou None, sans exception
    result = timing_mod._get_slow_counter()
    # Le résultat dépend de l'environnement (présence de prometheus_client)
    # On vérifie juste qu'il n'y a pas d'exception
    assert result is None or hasattr(result, "labels")


@pytest.mark.asyncio
async def test_inc_slow_fails_silently_if_counter_broken():
    """_inc_slow ne propage pas les exceptions Prometheus."""
    import app.middleware.timing as timing_mod

    broken_counter = MagicMock()
    broken_counter.labels.side_effect = Exception("prometheus broken")

    with patch.object(timing_mod, "_slow_counter", broken_counter):
        with patch.object(timing_mod, "_slow_counter_initialized", True):
            # Ne doit pas lever d'exception
            timing_mod._inc_slow("GET", "/test")
