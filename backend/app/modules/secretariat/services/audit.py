from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.secretariat.models import SecretariatAuditLog


SENSITIVE_METADATA_KEYS = {
    "access_token",
    "api_key",
    "body",
    "content",
    "description",
    "draft_body",
    "extracted_text",
    "file_path",
    "instructions",
    "mail_body",
    "message",
    "message_body",
    "notes",
    "prompt",
    "raw_response",
    "refresh_token",
    "response",
    "secret",
    "summary_text",
    "synthesis_text",
    "token",
}


def _sanitize_value(value):
    if isinstance(value, dict):
        cleaned: dict = {}
        for key, item in value.items():
            if key in SENSITIVE_METADATA_KEYS:
                continue
            cleaned[key] = _sanitize_value(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, set):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    return value


def sanitize_secretariat_metadata(metadata_json: dict | None) -> dict | None:
    if not metadata_json:
        return None
    cleaned = _sanitize_value(metadata_json)
    return cleaned or None


async def record_secretariat_audit(
    db: AsyncSession,
    *,
    organisation_id: int,
    user_id: UUID | None,
    action: str,
    agent_type: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    status: str = "success",
    metadata_json: dict | None = None,
) -> SecretariatAuditLog:
    log = SecretariatAuditLog(
        organisation_id=organisation_id,
        user_id=user_id,
        agent_type=agent_type,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        status=status,
        metadata_json=sanitize_secretariat_metadata(metadata_json),
    )
    db.add(log)
    return log
