from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AIResponse:
    content: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class ChatCompletionResponse:
    """Réponse d'un appel chat/completions (avec ou sans tool calls)."""
    content: str | None
    tool_calls: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length"
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProviderError(Exception):
    """Erreur levée par un provider IA — capturée par AIService."""


class AIUnavailableError(AIProviderError):
    """Provider injoignable (réseau, timeout, service arrêté)."""


class AIResponseError(AIProviderError):
    """Provider joignable mais réponse invalide ou vide."""


class AIConfigError(AIProviderError):
    """Configuration manquante ou incorrecte (clé API, URL…)."""


class AIProvider(ABC):
    """Interface commune à tous les providers IA."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> AIResponse: ...

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema_name: str = "response",
        schema: dict | None = None,
    ) -> dict:
        """
        Génère une réponse structurée en JSON.
        Implémentation par défaut : génère du texte et parse le JSON.
        Les providers qui supportent le mode JSON natif (OpenAI) surchargent cette méthode.
        """
        import json
        import re

        json_instruction = ""
        if schema:
            import json as _json
            json_instruction = (
                f"\n\nTu dois répondre UNIQUEMENT avec un objet JSON valide "
                f"correspondant exactement à ce schéma :\n{_json.dumps(schema, ensure_ascii=False)}"
            )

        full_system = (system or "") + json_instruction
        response = await self.generate(prompt, system=full_system, temperature=0.0, max_tokens=4000)

        text = response.content.strip()
        # Extraire le JSON même si entouré de ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            from app.core.ai.base import AIResponseError
            raise AIResponseError(f"JSON invalide retourné par {self.provider_name}: {exc}") from exc

    async def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatCompletionResponse:
        """
        Chat completion avec support optionnel du function calling (tools).
        Implémentation par défaut : fallback sur generate() (sans tools).
        """
        import json

        # Construction d'un prompt simple à partir de l'historique
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            if role == "system":
                lines.append(f"[Instructions]: {content}")
            elif role == "user":
                lines.append(f"[Utilisateur]: {content}")
            elif role == "assistant":
                lines.append(f"[Assistant]: {content}")

        combined = "\n".join(lines)
        response = await self.generate(combined, temperature=temperature, max_tokens=max_tokens)
        return ChatCompletionResponse(
            content=response.content,
            provider=self.provider_name,
            model=self.model,
            finish_reason="stop",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    @abstractmethod
    async def health_check(self) -> bool: ...
