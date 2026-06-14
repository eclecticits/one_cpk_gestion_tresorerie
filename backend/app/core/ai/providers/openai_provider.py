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
    ChatCompletionResponse,
)

logger = logging.getLogger("onec_cpk_ai.openai")

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(AIProvider):
    """Provider OpenAI — chat/completions + responses (JSON structuré)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 60.0,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise AIConfigError("api_key est requis pour le provider OpenAI.")
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._default_max_tokens = max_tokens
        self._default_temperature = temperature

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AIResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self.chat_completion(
            messages,
            temperature=temperature if temperature is not None else self._default_temperature,
            max_tokens=max_tokens or self._default_max_tokens,
        )
        return AIResponse(
            content=response.content or "",
            provider=self.provider_name,
            model=self._model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_name: str = "response",
        schema: dict | None = None,
    ) -> dict:
        """Utilise l'endpoint /responses d'OpenAI pour un JSON structuré strict."""
        payload: dict = {
            "model": self._model,
            "instructions": system or "Tu es un assistant qui répond uniquement en JSON.",
            "input": prompt,
        }
        if schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            }
        else:
            payload["text"] = {"format": {"type": "text"}}

        logger.debug("openai.generate_json model=%s schema=%s", self._model, schema_name)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/responses",
                    headers=self._auth_headers(),
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(f"OpenAI timeout ({self._timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise AIConfigError("Clé API OpenAI invalide (401).") from exc
            if status == 429:
                raise AIUnavailableError("OpenAI : quota dépassé (429).") from exc
            raise AIUnavailableError(f"OpenAI HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"OpenAI injoignable : {exc}") from exc

        data = resp.json()
        output_text = data.get("output_text")
        if not output_text:
            for item in data.get("output", []) or []:
                for block in item.get("content", []) or []:
                    if block.get("type") in {"output_text", "text"} and block.get("text"):
                        output_text = block["text"]
                        break
                if output_text:
                    break

        if not output_text:
            raise AIResponseError("OpenAI a retourné une réponse JSON vide.")

        try:
            return json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise AIResponseError(f"JSON invalide retourné par OpenAI: {exc}") from exc

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatCompletionResponse:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._default_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.debug("openai.chat_completion model=%s tools=%d", self._model, len(tools or []))
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._auth_headers(),
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(f"OpenAI timeout ({self._timeout}s)") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise AIConfigError("Clé API OpenAI invalide (401).") from exc
            if status == 429:
                raise AIUnavailableError("OpenAI : quota dépassé (429).") from exc
            raise AIUnavailableError(f"OpenAI HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"OpenAI injoignable : {exc}") from exc

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})

        return ChatCompletionResponse(
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls") or [],
            provider=self.provider_name,
            model=self._model,
            finish_reason=choice.get("finish_reason", "stop"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers=self._auth_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
