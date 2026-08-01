"""Tests Phase 4 — couche d'abstraction IA.

Couvre :
  - AIProvider ABC et hiérarchie d'erreurs
  - OllamaProvider : generate(), health_check()
  - AnthropicProvider : generate(), health_check(), erreurs HTTP
  - AIService : fallback, health_check()
  - get_ai_service() : factory selon settings
  - log_ai_audit() : log structuré sans données sensibles
  - build_finance_snapshot() : isolation tenant (organisation_id requis)
  - ask_ai() : fallback local quand provider indisponible
  - classify_expense_with_gemma() : refactorisation syscebnl
  - AIBatchProcessor : refactorisation batch
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

from app.core.ai.base import (
    AIConfigError,
    AIProvider,
    AIResponse,
    AIResponseError,
    AIUnavailableError,
)
from app.core.ai.providers.anthropic_provider import AnthropicProvider
from app.core.ai.providers.ollama_provider import OllamaProvider
from app.core.ai.service import AIService, get_ai_service, log_ai_audit


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ollama_response(text: str = '{"answer": "ok"}') -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"response": text}
    resp.raise_for_status = MagicMock()
    return resp


def _make_anthropic_response(text: str = '{"answer": "ok"}') -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    resp.raise_for_status = MagicMock()
    return resp


# ── AIProvider ABC ───────────────────────────────────────────────────────────

def test_ai_response_defaults():
    r = AIResponse(content="hello", provider="test", model="m")
    assert r.input_tokens is None
    assert r.output_tokens is None


def test_error_hierarchy():
    assert issubclass(AIUnavailableError, AIProviderError := __import__("app.core.ai.base", fromlist=["AIProviderError"]).AIProviderError)
    assert issubclass(AIResponseError, AIProviderError)
    assert issubclass(AIConfigError, AIProviderError)


# ── OllamaProvider ───────────────────────────────────────────────────────────

class TestOllamaProvider:
    def _provider(self, **kwargs) -> OllamaProvider:
        return OllamaProvider(base_url="http://ollama-test:11434", model="gemma2:2b", **kwargs)

    def test_provider_name(self):
        p = self._provider()
        assert p.provider_name == "ollama"
        assert p.model == "gemma2:2b"

    def test_missing_base_url_raises(self):
        with pytest.raises(AIConfigError):
            OllamaProvider(base_url="", model="gemma2:2b")

    @pytest.mark.asyncio
    async def test_generate_success(self):
        p = self._provider()
        mock_resp = _make_ollama_response('{"answer": "solde ok"}')
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            result = await p.generate("question")
        assert result.provider == "ollama"
        assert result.model == "gemma2:2b"
        assert "solde" in result.content

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_unavailable(self):
        p = self._provider(timeout=1.0)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client
            with pytest.raises(AIUnavailableError, match="timeout"):
                await p.generate("question")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        p = self._provider()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": ""}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            with pytest.raises(AIResponseError):
                await p.generate("question")

    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        p = self._provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_down(self):
        p = self._provider()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client
            assert await p.health_check() is False


# ── AnthropicProvider ─────────────────────────────────────────────────────────

class TestAnthropicProvider:
    def _provider(self, **kwargs) -> AnthropicProvider:
        return AnthropicProvider(
            api_key="sk-ant-test-key",
            model="claude-haiku-4-5-20251001",
            **kwargs,
        )

    def test_provider_name(self):
        p = self._provider()
        assert p.provider_name == "anthropic"

    def test_empty_api_key_raises(self):
        with pytest.raises(AIConfigError):
            AnthropicProvider(api_key="", model="claude-haiku-4-5-20251001")

    @pytest.mark.asyncio
    async def test_generate_success(self):
        p = self._provider()
        mock_resp = _make_anthropic_response('{"answer": "réponse IA"}')
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            result = await p.generate("question", system="tu es un assistant")
        assert result.provider == "anthropic"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert "réponse" in result.content

    @pytest.mark.asyncio
    async def test_generate_401_raises_config_error(self):
        p = self._provider()
        http_err = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock(status_code=401)
        )
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=http_err)
            mock_client_cls.return_value = mock_client
            with pytest.raises(AIConfigError, match="invalide"):
                await p.generate("question")

    @pytest.mark.asyncio
    async def test_generate_429_raises_unavailable(self):
        p = self._provider()
        http_err = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=MagicMock(status_code=429)
        )
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=http_err)
            mock_client_cls.return_value = mock_client
            with pytest.raises(AIUnavailableError, match="429"):
                await p.generate("question")

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_unavailable(self):
        p = self._provider()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client
            with pytest.raises(AIUnavailableError, match="timeout"):
                await p.generate("question")

    @pytest.mark.asyncio
    async def test_api_key_never_logged(self, caplog):
        p = self._provider()
        mock_resp = _make_anthropic_response("{}")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            with caplog.at_level(logging.DEBUG, logger="onec_cpk_ai.anthropic"):
                try:
                    await p.generate("question")
                except Exception:
                    pass
        for record in caplog.records:
            assert "sk-ant-test-key" not in record.getMessage()


# ── AIService ────────────────────────────────────────────────────────────────

class TestAIService:
    def _make_mock_provider(self, name: str, response_text: str = '{"answer": "ok"}') -> MagicMock:
        provider = MagicMock()
        provider.provider_name = name
        provider.model = "test-model"
        provider.generate = AsyncMock(
            return_value=AIResponse(content=response_text, provider=name, model="test-model")
        )
        provider.health_check = AsyncMock(return_value=True)
        return provider

    @pytest.mark.asyncio
    async def test_generate_uses_primary(self):
        primary = self._make_mock_provider("anthropic")
        service = AIService([primary])
        result = await service.generate("question")
        assert result.provider == "anthropic"
        primary.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_called_when_primary_fails(self):
        primary = self._make_mock_provider("anthropic")
        primary.generate = AsyncMock(side_effect=AIUnavailableError("down"))
        fallback = self._make_mock_provider("ollama", '{"answer": "fallback"}')
        service = AIService([primary, fallback])
        result = await service.generate("question")
        assert result.provider == "ollama"
        fallback.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_fallback_raises_when_primary_fails(self):
        primary = self._make_mock_provider("anthropic")
        primary.generate = AsyncMock(side_effect=AIUnavailableError("down"))
        service = AIService([primary])
        with pytest.raises(AIUnavailableError):
            await service.generate("question")

    @pytest.mark.asyncio
    async def test_health_check_both_providers(self):
        primary = self._make_mock_provider("anthropic")
        fallback = self._make_mock_provider("ollama")
        service = AIService([primary, fallback])
        result = await service.health_check()
        assert result["providers"][0]["provider"] == "anthropic"
        assert result["providers"][0]["ok"] is True
        assert result["providers"][1]["provider"] == "ollama"


# ── get_ai_service() factory ──────────────────────────────────────────────────

class TestGetAIService:
    def test_ollama_provider_built(self):
        with patch("app.core.ai.service.settings") as mock_settings:
            mock_settings.ai_provider = "ollama"
            mock_settings.ai_enable_fallback = False
            mock_settings.ai_fallback_provider = None
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.ollama_model = "gemma2:2b"
            mock_settings.ollama_timeout_seconds = 60
            service = get_ai_service()
        assert service.provider_name == "ollama"

    def test_anthropic_without_key_raises(self):
        with patch("app.core.ai.service.settings") as mock_settings:
            mock_settings.ai_provider = "anthropic"
            mock_settings.ai_enable_fallback = False
            mock_settings.ai_fallback_provider = None
            mock_settings.anthropic_api_key = None
            # Un provider mal configuré est ignoré → plus aucun provider → indisponible.
            with pytest.raises(AIUnavailableError):
                get_ai_service()

    def test_unknown_provider_raises(self):
        with patch("app.core.ai.service.settings") as mock_settings:
            mock_settings.ai_provider = "unknown-provider"
            mock_settings.ai_enable_fallback = False
            mock_settings.ai_fallback_provider = None
            # Type inconnu → provider ignoré → plus aucun provider → indisponible.
            with pytest.raises(AIUnavailableError):
                get_ai_service()


# ── log_ai_audit ─────────────────────────────────────────────────────────────

def test_log_ai_audit_no_sensitive_data(caplog):
    with caplog.at_level(logging.INFO, logger="onec_cpk_ai"):
        log_ai_audit(
            user_id=42,
            organisation_id=7,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            module="chat",
            status="success",
            duration_ms=350,
            input_tokens=100,
            output_tokens=50,
        )
    assert any("ai.audit" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        msg = record.getMessage()
        assert "sk-ant" not in msg
        assert "prompt" not in msg.lower()


# ── build_finance_snapshot tenant isolation ──────────────────────────────────

@pytest.mark.asyncio
async def test_build_finance_snapshot_filters_by_tenant():
    """build_finance_snapshot ne doit jamais appeler la DB sans organisation_id."""
    from app.services.ai_chat import build_finance_snapshot
    from app.services.forecasting import compute_cash_forecast, CashForecast

    mock_db = AsyncMock()
    # Simuler les résultats des scalars / execute
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    forecast_mock = CashForecast(
        solde_actuel=5000.0,
        lookback_days=30,
        horizon_days=30,
        reserve_threshold=1000.0,
        encaissements_total=2000.0,
        sorties_total=1000.0,
        net_total=1000.0,
        baseline_projection=6000.0,
        stress_projection=4500.0,
        pending_total=500.0,
        pressure_ratio=0.1,
        autonomy_days=90,
    )

    with patch("app.services.ai_chat.compute_cash_forecast", AsyncMock(return_value=forecast_mock)):
        snapshot = await build_finance_snapshot(mock_db, tenant_id=99)

    assert snapshot["solde_actuel"] == 5000.0
    # Vérifier que chaque appel execute contient organisation_id=99 dans le WHERE
    calls = mock_db.execute.call_args_list
    assert len(calls) > 0, "Aucun appel execute — les requêtes SQL ne sont pas lancées"
    for call in calls:
        stmt = call.args[0]
        stmt_text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "99" in stmt_text, (
            f"organisation_id=99 absent de la requête SQL : {stmt_text[:200]}"
        )


# ── ask_ai() fallback local ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_ai_fallback_local_when_provider_unavailable():
    """ask_ai() doit retourner une réponse locale si le provider est indisponible."""
    from app.services.ai_chat import ask_ai
    from app.services.forecasting import CashForecast

    forecast_mock = CashForecast(
        solde_actuel=10000.0,
        lookback_days=30,
        horizon_days=30,
        reserve_threshold=1000.0,
        encaissements_total=5000.0,
        sorties_total=2000.0,
        net_total=3000.0,
        baseline_projection=13000.0,
        stress_projection=8000.0,
        pending_total=2000.0,
        pressure_ratio=0.2,
        autonomy_days=120,
    )

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.ai_chat.compute_cash_forecast", AsyncMock(return_value=forecast_mock)):
        with patch("app.services.ai_chat.get_ai_service_for_org") as mock_svc_factory:
            mock_svc = MagicMock()
            mock_svc.generate = AsyncMock(side_effect=AIUnavailableError("ollama down"))
            mock_svc_factory.return_value = mock_svc
            result = await ask_ai(
                question="quel est le solde ?",
                history=[],
                db=mock_db,
                tenant_id=1,
                user_id=None,
            )

    assert "answer" in result
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0


@pytest.mark.asyncio
async def test_ask_ai_does_not_expose_prompt_in_logs(caplog):
    """Le prompt complet (avec données financières) ne doit pas apparaître dans les logs."""
    from app.services.ai_chat import ask_ai
    from app.services.forecasting import CashForecast

    forecast_mock = CashForecast(
        solde_actuel=999.0,
        lookback_days=30, horizon_days=30, reserve_threshold=1000.0,
        encaissements_total=0.0, sorties_total=0.0, net_total=0.0,
        baseline_projection=0.0, stress_projection=0.0, pending_total=0.0,
        pressure_ratio=0.0, autonomy_days=None,
    )

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    ai_resp = AIResponse(
        content='{"answer": "réponse test"}', provider="anthropic", model="m"
    )

    with patch("app.services.ai_chat.compute_cash_forecast", AsyncMock(return_value=forecast_mock)):
        with patch("app.services.ai_chat.get_ai_service_for_org") as mock_factory:
            mock_svc = MagicMock()
            mock_svc.generate = AsyncMock(return_value=ai_resp)
            mock_factory.return_value = mock_svc
            with caplog.at_level(logging.DEBUG, logger="onec_cpk_ai"):
                await ask_ai(
                    question="test question confidentielle",
                    history=[],
                    db=mock_db,
                    tenant_id=1,
                )

    for record in caplog.records:
        msg = record.getMessage()
        assert "confidentielle" not in msg
        assert "999" not in msg


# ── classify_expense_with_gemma ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_expense_uses_ai_service():
    """classify_expense_with_gemma() doit utiliser AIService, pas Ollama directement."""
    from app.services.ai_syscebnl import classify_expense_with_gemma

    ai_resp = AIResponse(
        content='{"compte": "6010", "categorie": "Fournitures", "explication": "ok", "taux_confiance": 0.9}',
        provider="ollama",
        model="gemma2:2b",
    )

    with patch("app.services.ai_syscebnl.get_ai_service") as mock_factory:
        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(return_value=ai_resp)
        mock_factory.return_value = mock_svc
        result = await classify_expense_with_gemma("Achat fournitures de bureau")

    assert result["compte"] == "6010"
    assert "error" not in result


@pytest.mark.asyncio
async def test_classify_expense_graceful_on_provider_error():
    from app.services.ai_syscebnl import classify_expense_with_gemma

    with patch("app.services.ai_syscebnl.get_ai_service") as mock_factory:
        mock_svc = MagicMock()
        mock_svc.generate = AsyncMock(side_effect=AIUnavailableError("down"))
        mock_factory.return_value = mock_svc
        result = await classify_expense_with_gemma("test")

    assert "error" in result


# ── AIBatchProcessor ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_processor_uses_ai_service():
    """AIBatchProcessor.process_batch doit déléguer à AIService, pas httpx directement."""
    from app.services.ai_batch_service import AIBatchProcessor

    ai_resp = AIResponse(
        content='{"compte": "6010", "source": "ai"}',
        provider="ollama",
        model="gemma2:2b",
    )

    mock_db = AsyncMock()
    mock_cache_result = MagicMock()
    mock_cache_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_cache_result)
    mock_db.commit = AsyncMock()

    transactions = [{"label": "Achat stylos", "amount": 5000}]

    with patch("app.services.ai_batch_service.get_ai_service_for_org") as mock_org_factory:
        with patch("app.services.ai_memory_service.AIMemoryService.load_cache", AsyncMock(return_value={})):
            with patch("app.services.ai_memory_service.AIMemoryService.get_known_classification", AsyncMock(return_value=None)):
                mock_svc = MagicMock()
                mock_svc.generate = AsyncMock(return_value=ai_resp)
                mock_org_factory.return_value = mock_svc
                results = await AIBatchProcessor.process_batch(transactions, db=mock_db, org_id=1)

    assert len(results) == 1
    assert results[0]["ai_classification"]["compte"] == "6010"


@pytest.mark.asyncio
async def test_batch_processor_empty_input():
    from app.services.ai_batch_service import AIBatchProcessor
    mock_db = AsyncMock()
    result = await AIBatchProcessor.process_batch([], db=mock_db, org_id=1)
    assert result == []
