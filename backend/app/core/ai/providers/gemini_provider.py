from __future__ import annotations

import json
import logging

import httpx

from app.core.ai.base import (
    AIConfigError,
    AIProvider,
    AIProviderError,
    AIResponse,
    AIResponseError,
    AIUnavailableError,
    ChatCompletionResponse,
)

logger = logging.getLogger("onec_cpk_ai.gemini")

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    """Provider Google Gemini — generateContent API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        timeout: float = 60.0,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise AIConfigError("api_key est requis pour le provider Gemini.")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._default_max_tokens = max_tokens
        self._default_temperature = temperature

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    def _url(self, method: str = "generateContent") -> str:
        return f"{_BASE_URL}/models/{self._model}:{method}"

    def _headers(self) -> dict[str, str]:
        # Clé en en-tête et non en paramètre d'URL : une query string finit
        # dans les journaux d'accès des proxys et les traces d'observabilité.
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIResponse:
        payload: dict = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}],
            "generationConfig": {
                "maxOutputTokens": max_tokens or self._default_max_tokens,
                "temperature": temperature if temperature is not None else self._default_temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        logger.debug("gemini.generate model=%s", self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url("generateContent"), headers=self._headers(), json=payload
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(f"Gemini timeout ({self._timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 400:
                raise AIConfigError(f"Gemini 400 — vérifiez la clé API et le modèle.") from exc
            if status == 429:
                raise AIUnavailableError("Gemini : quota dépassé (429).") from exc
            raise AIUnavailableError(f"Gemini HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Gemini injoignable : {exc}") from exc

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIResponseError(f"Gemini : structure de réponse inattendue : {exc}") from exc

        if not text:
            raise AIResponseError("Gemini a retourné une réponse vide.")

        usage = data.get("usageMetadata", {})
        return AIResponse(
            content=text,
            provider=self.provider_name,
            model=self._model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatCompletionResponse:
        """Chat multi-tour Gemini avec function calling basique."""
        contents = []
        system_text = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            if role == "system":
                system_text = content
            elif role == "user":
                contents.append({"parts": [{"text": content}], "role": "user"})
            elif role == "assistant":
                contents.append({"parts": [{"text": content}], "role": "model"})
            elif role == "tool":
                # Réponse d'outil — Gemini attend un format spécifique
                contents.append({
                    "parts": [{"text": f"[Tool result]: {content}"}],
                    "role": "user",
                })

        payload: dict = {
            "contents": contents or [{"parts": [{"text": "Continue."}], "role": "user"}],
            "generationConfig": {
                "maxOutputTokens": max_tokens or self._default_max_tokens,
                "temperature": temperature if temperature is not None else self._default_temperature,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        # Les tools au format OpenAI ne sont pas traduits par cette
        # implémentation. Répondre quand même en texte simple rendrait toujours
        # tool_calls=[] : l'appelant croirait que le modèle n'a rien à appeler,
        # alors que la question ne lui a jamais été posée. On échoue donc
        # franchement, ce qui laisse le service basculer sur un fournisseur
        # capable de le faire.
        if tools:
            raise AIProviderError(
                "Gemini : appel d'outils (function calling) non implémenté par ce fournisseur."
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url("generateContent"), headers=self._headers(), json=payload
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(f"Gemini timeout ({self._timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            raise AIUnavailableError(f"Gemini HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Gemini injoignable : {exc}") from exc

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            text = ""

        usage = data.get("usageMetadata", {})
        return ChatCompletionResponse(
            content=text,
            tool_calls=[],
            provider=self.provider_name,
            model=self._model,
            finish_reason="stop",
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                url = f"{_BASE_URL}/models"
                resp = await client.get(url, headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False
