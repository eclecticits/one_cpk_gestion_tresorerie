from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base import AIProviderError, AIUnavailableError
from app.core.ai.service import get_ai_service_for_org

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "detected_request": {"type": ["string", "null"]},
        "suggested_priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "requires_response": {"type": "boolean"},
    },
    "required": ["summary", "key_points", "detected_request", "suggested_priority", "requires_response"],
}

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "enum": ["administratif", "financier", "réunion", "réquisition", "cotisation", "tableau", "forco", "juridique", "technique", "autre"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "recommended_action": {"type": "string", "enum": ["répondre", "classer", "transférer", "traiter_plus_tard", "demander_validation"]},
    },
    "required": ["category", "priority", "confidence", "reason", "recommended_action"],
}

DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "subject": {"type": "string"},
        "draft_body": {"type": "string"},
        "requires_human_validation": {"type": "boolean"},
    },
    "required": ["subject", "draft_body", "requires_human_validation"],
}

DOCUMENT_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary_text": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "requires_human_validation": {"type": "boolean"},
    },
    "required": ["summary_text", "key_points", "missing_information", "requires_human_validation"],
}

DOCUMENT_SYNTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "object": {"type": "string"},
        "context": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "decisions_or_requests": {"type": "array", "items": {"type": "string"}},
        "actions_to_follow": {"type": "array", "items": {"type": "string"}},
        "risks_or_observations": {"type": "array", "items": {"type": "string"}},
        "proposed_next_steps": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "requires_human_validation": {"type": "boolean"},
    },
    "required": [
        "object",
        "context",
        "key_points",
        "decisions_or_requests",
        "actions_to_follow",
        "risks_or_observations",
        "proposed_next_steps",
        "missing_information",
        "requires_human_validation",
    ],
}


def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def _mail_context(email: dict) -> str:
    body = (email.get("body") or email.get("snippet") or "").strip()
    if len(body) > 6000:
        body = f"{body[:6000]}\n\n[Contenu tronqué pour minimisation des données]"
    headers = email.get("headers") or {}
    safe = {
        "subject": email.get("subject"),
        "from": email.get("from"),
        "to": email.get("to"),
        "cc": email.get("cc"),
        "date": email.get("date"),
        "snippet": email.get("snippet"),
        "headers": {k: headers.get(k) for k in ["from", "to", "cc", "date", "subject"] if headers.get(k)},
        "body": body,
    }
    return json.dumps(safe, ensure_ascii=False)


def _document_context(document: dict) -> str:
    extracted = (document.get("extracted_text") or "").strip()
    if len(extracted) > 8000:
        extracted = f"{extracted[:8000]}\n\n[Contenu tronqué pour minimisation des données]"
    safe = {
        "title": document.get("title"),
        "document_type": document.get("document_type"),
        "category": document.get("category"),
        "source": document.get("source"),
        "description": document.get("description"),
        "keywords": document.get("keywords_json") or [],
        "extracted_text": extracted,
    }
    return json.dumps(safe, ensure_ascii=False)


async def _responses_json(
    system_prompt: str,
    user_input: str,
    schema_name: str,
    schema: dict,
    *,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    """
    Génère une réponse JSON structurée via la couche IA abstraite.
    Utilise le provider configuré en base de données (Super Admin) ou les variables d'environnement.
    """
    try:
        service = await get_ai_service_for_org(db, organisation_id)
        return await service.generate_json(
            user_input,
            system=system_prompt,
            schema_name=schema_name,
            schema=schema,
        )
    except AIUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Le service IA a retourné une réponse invalide. Veuillez réessayer.",
        ) from exc


async def summarize_email(
    email: dict,
    *,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    return await _responses_json(
        _prompt("courrier_summary_system.txt"),
        f"Résume ce mail au format demandé:\n{_mail_context(email)}",
        "courrier_email_summary",
        SUMMARY_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )


async def classify_email(
    email: dict,
    *,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    return await _responses_json(
        _prompt("courrier_classification_system.txt"),
        f"Classifie ce mail au format demandé:\n{_mail_context(email)}",
        "courrier_email_classification",
        CLASSIFICATION_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )


async def generate_email_response(
    email: dict,
    *,
    tone: str,
    instructions: str | None = None,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    user_input = {
        "tone": tone,
        "instructions": (instructions or "").strip() or None,
        "email": json.loads(_mail_context(email)),
    }
    return await _responses_json(
        _prompt("courrier_response_system.txt"),
        f"Génère un projet de réponse interne:\n{json.dumps(user_input, ensure_ascii=False)}",
        "courrier_email_draft_response",
        DRAFT_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )


async def summarize_document(
    document: dict,
    *,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    return await _responses_json(
        _prompt("document_summary_system.txt"),
        f"Résume ce document au format demandé:\n{_document_context(document)}",
        "secretariat_document_summary",
        DOCUMENT_SUMMARY_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )


async def generate_document_synthesis(
    document: dict,
    *,
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    return await _responses_json(
        _prompt("document_synthesis_system.txt"),
        f"Prépare une fiche synthèse au format demandé:\n{_document_context(document)}",
        "secretariat_document_synthesis",
        DOCUMENT_SYNTHESIS_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
