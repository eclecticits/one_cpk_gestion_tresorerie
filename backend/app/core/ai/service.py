from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base import (
    AIProvider,
    AIProviderError,
    AIResponse,
    AIUnavailableError,
    ChatCompletionResponse,
)
from app.core.config import settings

logger = logging.getLogger("onec_cpk_ai")

NO_PROVIDER_MESSAGE = (
    "Aucun fournisseur IA valide n'est actuellement configuré. "
    "Veuillez contacter un administrateur système."
)


# ── Construction des providers ────────────────────────────────────────────────

def _build_provider_from_config(cfg: Any) -> AIProvider:
    """Instancie un provider depuis un objet AIProviderConfig (DB)."""
    from app.core.ai.base import AIConfigError
    from app.core.encryption import decrypt_secret

    provider_type = (getattr(cfg, "provider_type", "") or "").strip().lower()
    api_key_enc = getattr(cfg, "api_key_encrypted", None)
    base_url = getattr(cfg, "base_url", None)
    model = getattr(cfg, "default_model", None) or ""
    extra = getattr(cfg, "config_json", None) or {}

    api_key = ""
    if api_key_enc:
        try:
            api_key = decrypt_secret(api_key_enc)
        except Exception as exc:
            raise AIConfigError(f"Impossible de déchiffrer la clé API : {exc}") from exc

    if provider_type == "openai":
        from app.core.ai.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=api_key,
            model=model or "gpt-4o-mini",
            base_url=base_url or "https://api.openai.com/v1",
            timeout=float(extra.get("timeout_seconds", 60)),
            max_tokens=int(extra.get("max_tokens", 4096)),
            temperature=float(extra.get("temperature", 0.2)),
        )
    if provider_type == "anthropic":
        from app.core.ai.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=api_key,
            model=model or "claude-haiku-4-5-20251001",
            timeout=float(extra.get("timeout_seconds", 60)),
            max_tokens=int(extra.get("max_tokens", 4000)),
            temperature=float(extra.get("temperature", 0.2)),
        )
    if provider_type == "gemini":
        from app.core.ai.providers.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=api_key,
            model=model or "gemini-1.5-flash",
            timeout=float(extra.get("timeout_seconds", 60)),
            max_tokens=int(extra.get("max_tokens", 4096)),
            temperature=float(extra.get("temperature", 0.2)),
        )
    if provider_type == "ollama":
        from app.core.ai.providers.ollama_provider import OllamaProvider
        return OllamaProvider(
            base_url=base_url or "http://localhost:11434",
            model=model or "gemma2:2b",
            timeout=float(extra.get("timeout_seconds", 60)),
        )

    raise AIConfigError(
        f"Type de fournisseur IA inconnu : '{provider_type}'. "
        "Types valides : openai, anthropic, gemini, ollama."
    )


def _build_provider_from_env(name: str) -> AIProvider:
    """Instancie un provider depuis les variables d'environnement."""
    from app.core.ai.base import AIConfigError
    from app.core.ai.providers.anthropic_provider import AnthropicProvider
    from app.core.ai.providers.ollama_provider import OllamaProvider

    name = (name or "").strip().lower()
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise AIConfigError("ANTHROPIC_API_KEY absent.")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=float(settings.anthropic_timeout_seconds),
            max_tokens=settings.anthropic_max_tokens,
            temperature=settings.anthropic_temperature,
        )
    if name == "openai":
        if not settings.openai_api_key:
            raise AIConfigError("OPENAI_API_KEY absent.")
        from app.core.ai.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )
    if name == "gemini":
        if not settings.gemini_api_key:
            raise AIConfigError("GEMINI_API_KEY absent.")
        from app.core.ai.providers.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=getattr(settings, "gemini_model", "gemini-1.5-flash"),
        )
    if name == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url or "http://localhost:11434",
            model=settings.ollama_model or "gemma2:2b",
            timeout=float(settings.ollama_timeout_seconds),
        )
    raise AIConfigError(
        f"Provider IA inconnu dans la config : '{name}'. "
        "Valides : openai, anthropic, gemini, ollama."
    )


# ── Résolution DB ─────────────────────────────────────────────────────────────

async def _get_db_providers(
    db: AsyncSession,
    organisation_id: int | None = None,
) -> list[AIProvider]:
    """Charge les providers actifs depuis la DB, triés par priorité."""
    from app.models.ai_provider_config import AIProviderConfig

    stmt = (
        select(AIProviderConfig)
        .where(AIProviderConfig.is_active == True)  # noqa: E712
        .where(
            (AIProviderConfig.organisation_id.is_(None))
            | (AIProviderConfig.organisation_id == organisation_id)
            if organisation_id
            else AIProviderConfig.organisation_id.is_(None)
        )
        .order_by(
            AIProviderConfig.is_default.desc(),
            AIProviderConfig.fallback_priority.asc(),
        )
    )

    result = await db.execute(stmt)
    configs = list(result.scalars().all())

    providers: list[AIProvider] = []
    for cfg in configs:
        try:
            providers.append(_build_provider_from_config(cfg))
        except Exception as exc:
            logger.warning(
                "ai.provider_build_failed name=%s type=%s reason=%s",
                cfg.name, cfg.provider_type, exc,
            )
    return providers


def _get_env_providers() -> list[AIProvider]:
    """Providers depuis les variables d'environnement (fallback ultime)."""
    providers: list[AIProvider] = []
    for name in [settings.ai_provider, settings.ai_fallback_provider or ""]:
        if not name:
            continue
        try:
            providers.append(_build_provider_from_env(name))
        except Exception as exc:
            logger.debug("ai.env_provider_skip name=%s reason=%s", name, exc)
    return providers


# ── Service ───────────────────────────────────────────────────────────────────

class AIService:
    """Couche d'abstraction IA multi-fournisseurs avec fallback automatique."""

    def __init__(self, providers: list[AIProvider]) -> None:
        if not providers:
            raise AIUnavailableError(NO_PROVIDER_MESSAGE)
        self._providers = providers

    @property
    def provider_name(self) -> str:
        return self._providers[0].provider_name

    @property
    def model(self) -> str:
        return self._providers[0].model

    async def _try_all(self, method: str, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for provider in self._providers:
            try:
                return await getattr(provider, method)(*args, **kwargs)
            except AIProviderError as exc:
                logger.warning(
                    "ai.provider_failed provider=%s method=%s reason=%s",
                    provider.provider_name, method, exc,
                )
                last_exc = exc
        raise AIUnavailableError(NO_PROVIDER_MESSAGE) from last_exc

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> AIResponse:
        return await self._try_all(
            "generate", prompt, system=system, temperature=temperature, max_tokens=max_tokens
        )

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_name: str = "response",
        schema: dict | None = None,
    ) -> dict:
        return await self._try_all(
            "generate_json", prompt, system=system, schema_name=schema_name, schema=schema
        )

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatCompletionResponse:
        return await self._try_all(
            "chat_completion", messages, tools=tools, temperature=temperature, max_tokens=max_tokens
        )

    async def health_check(self) -> dict[str, Any]:
        results = []
        for provider in self._providers:
            ok = await provider.health_check()
            results.append({
                "provider": provider.provider_name,
                "model": provider.model,
                "ok": ok,
            })
        return {"providers": results}


# ── Factories ─────────────────────────────────────────────────────────────────

def get_ai_service() -> AIService:
    """Factory synchrone — env vars uniquement (compatibilité ascendante)."""
    providers = _get_env_providers()
    if not providers:
        raise AIUnavailableError(NO_PROVIDER_MESSAGE)
    return AIService(providers)


async def get_ai_service_for_org(
    db: AsyncSession,
    organisation_id: int | None = None,
) -> AIService:
    """
    Factory async — cherche les providers en DB en priorité,
    puis se rabat sur les variables d'environnement.
    """
    providers = await _get_db_providers(db, organisation_id)
    if not providers:
        providers = _get_env_providers()
    if not providers:
        raise AIUnavailableError(NO_PROVIDER_MESSAGE)
    return AIService(providers)


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_ai_audit(
    *,
    user_id: Any,
    organisation_id: int,
    provider: str,
    model: str,
    module: str,
    status: str,
    duration_ms: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    logger.info(
        "ai.audit user_id=%s org=%s provider=%s model=%s module=%s "
        "status=%s duration_ms=%d input_tokens=%s output_tokens=%s",
        user_id, organisation_id, provider, model, module,
        status, duration_ms, input_tokens, output_tokens,
    )
