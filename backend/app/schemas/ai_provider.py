from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


VALID_PROVIDER_TYPES = {"openai", "anthropic", "gemini", "ollama"}


class AIProviderConfigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Nom lisible du provider")
    provider_type: str = Field(..., description="openai | anthropic | gemini | ollama")
    base_url: str | None = Field(None, max_length=512)
    default_model: str = Field("", max_length=120)
    is_active: bool = True
    is_default: bool = False
    fallback_priority: int = Field(10, ge=1, le=100)
    config_json: dict[str, Any] | None = None

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str) -> str:
        if v not in VALID_PROVIDER_TYPES:
            raise ValueError(
                f"provider_type invalide : '{v}'. Valeurs acceptées : {sorted(VALID_PROVIDER_TYPES)}"
            )
        return v


class AIProviderConfigCreate(AIProviderConfigBase):
    api_key: str | None = Field(
        None,
        description="Clé API en clair — sera chiffrée côté serveur avant stockage.",
    )


class AIProviderConfigUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    provider_type: str | None = None
    api_key: str | None = Field(None, description="Laisser vide pour ne pas modifier la clé.")
    base_url: str | None = None
    default_model: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    fallback_priority: int | None = Field(None, ge=1, le=100)
    config_json: dict[str, Any] | None = None

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PROVIDER_TYPES:
            raise ValueError(
                f"provider_type invalide : '{v}'. Valeurs acceptées : {sorted(VALID_PROVIDER_TYPES)}"
            )
        return v


class AIProviderConfigOut(AIProviderConfigBase):
    id: int
    organisation_id: int | None
    has_api_key: bool = Field(description="Indique si une clé API est configurée (sans la révéler).")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIProviderTestRequest(BaseModel):
    provider_type: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class AIProviderTestResult(BaseModel):
    ok: bool
    provider: str
    model: str
    message: str
