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
        format_json: bool = False,
    ) -> AIResponse:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        # Le mode JSON n'est activé que sur demande explicite. Le forcer ici
        # contraindrait AUSSI les réponses en langage naturel — le chat ne
        # pourrait plus produire une phrase, seulement un objet JSON.
        if format_json:
            payload["format"] = "json"

        logger.debug("ollama.generate model=%s json=%s", self._model, format_json)
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

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_name: str = "response",
        schema: dict | None = None,
    ) -> dict:
        """Sortie structurée : ici, et seulement ici, on contraint Ollama au JSON.

        L'implémentation de base se contente de demander du JSON dans le prompt ;
        le mode natif d'Ollama garantit une sortie parsable.
        """
        json_instruction = ""
        if schema:
            json_instruction = (
                "\n\nTu dois répondre UNIQUEMENT avec un objet JSON valide "
                f"correspondant exactement à ce schéma :\n{json.dumps(schema, ensure_ascii=False)}"
            )
        response = await self.generate(
            prompt,
            system=(system or "") + json_instruction,
            temperature=0.0,
            format_json=True,
        )
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise AIResponseError(f"JSON invalide retourné par ollama : {exc}") from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
