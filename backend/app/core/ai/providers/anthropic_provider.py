from __future__ import annotations

import logging

import httpx

from app.core.ai.base import (
    AIConfigError,
    AIProvider,
    AIResponse,
    AIResponseError,
    AIUnavailableError,
)

logger = logging.getLogger("onec_cpk_ai.anthropic")

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    """Provider Anthropic (claude-*) — provider principal de production."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout: float = 60.0,
        max_tokens: int = 4000,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise AIConfigError(
                "ANTHROPIC_API_KEY est requis pour le provider Anthropic."
            )
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._default_max_tokens = max_tokens
        self._default_temperature = temperature

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIResponse:
        payload: dict = {
            "model": self._model,
            "max_tokens": max_tokens or self._default_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        # Anthropic ne supporte pas temperature=0, clamp à 0.0 minimum
        temp = temperature if temperature is not None else self._default_temperature
        if temp is not None:
            payload["temperature"] = max(0.0, float(temp))

        logger.debug("anthropic.generate model=%s", self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    _ANTHROPIC_API_URL, headers=self._headers(), json=payload
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(
                f"Anthropic timeout ({self._timeout}s)"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise AIConfigError("ANTHROPIC_API_KEY invalide ou manquante.") from exc
            if status == 429:
                raise AIUnavailableError("Anthropic : quota dépassé (429).") from exc
            raise AIUnavailableError(
                f"Anthropic HTTP {status}"
            ) from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Anthropic injoignable : {exc}") from exc

        data = resp.json()
        content_blocks = data.get("content") or []
        text = next(
            (b.get("text", "") for b in content_blocks if b.get("type") == "text"),
            "",
        )
        if not text:
            raise AIResponseError("Anthropic a retourné une réponse vide.")

        usage = data.get("usage") or {}
        return AIResponse(
            content=text,
            provider=self.provider_name,
            model=self._model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    async def health_check(self) -> bool:
        # Vérifie la clé sans consommer de tokens : liste de modèles
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
