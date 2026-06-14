from __future__ import annotations

import json
import logging

import httpx

from app.core.ai.base import (
    AIConfigError,
    AIProvider,
    AIResponse,
    AIResponseError,
    AIUnavailableError,
)

logger = logging.getLogger("onec_cpk_ai.ollama")


class OllamaProvider(AIProvider):
    """Provider Ollama — serveur LLM local ou sur réseau privé."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        if not base_url:
            raise AIConfigError("OLLAMA_BASE_URL est requis pour le provider Ollama.")
        self._base_url = base_url.rstrip("/")
        self._model = model or "gemma2:2b"
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> AIResponse:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }

        logger.debug("ollama.generate model=%s", self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(f"Ollama timeout ({self._timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            raise AIUnavailableError(
                f"Ollama HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Ollama injoignable : {exc}") from exc

        data = resp.json()
        content = data.get("response", "")
        if not content:
            raise AIResponseError("Ollama a retourné une réponse vide.")

        return AIResponse(
            content=content,
            provider=self.provider_name,
            model=self._model,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
