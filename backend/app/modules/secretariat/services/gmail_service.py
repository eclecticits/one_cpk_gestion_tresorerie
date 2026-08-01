from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from email.utils import parsedate_to_datetime

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.secretariat.services.oauth_service import (
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_SCOPE,
    get_oauth_connection,
    refresh_access_token_if_needed,
)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _headers_to_dict(payload: dict) -> dict[str, str]:
    headers = payload.get("payload", {}).get("headers", []) or []
    return {str(item.get("name", "")).lower(): str(item.get("value", "")) for item in headers if item.get("name")}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _decode_body(data: str | None) -> str | None:
    if not data:
        return None
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return None


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def _has_attachments(payload: dict) -> bool:
    root = payload.get("payload", {}) or {}
    return any(bool(part.get("filename") and part.get("body", {}).get("attachmentId")) for part in _walk_parts(root))


def _attachments(payload: dict) -> list[dict]:
    root = payload.get("payload", {}) or {}
    items = []
    for part in _walk_parts(root):
        body = part.get("body", {}) or {}
        if part.get("filename") and body.get("attachmentId"):
            items.append(
                {
                    "filename": part.get("filename"),
                    "mime_type": part.get("mimeType"),
                    "size": body.get("size"),
                    "attachment_id": body.get("attachmentId"),
                }
            )
    return items


def _extract_text_body(payload: dict) -> str | None:
    root = payload.get("payload", {}) or {}
    for part in _walk_parts(root):
        if part.get("mimeType") == "text/plain":
            decoded = _decode_body((part.get("body") or {}).get("data"))
            if decoded:
                return decoded.strip()
    if root.get("mimeType") == "text/plain":
        decoded = _decode_body((root.get("body") or {}).get("data"))
        if decoded:
            return decoded.strip()
    return None


async def _access_token(db: AsyncSession, user: User, organisation_id: int) -> str:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=organisation_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connexion Google non configurée.")
    return await refresh_access_token_if_needed(db, connection)


async def _readonly_access_token(db: AsyncSession, user: User, organisation_id: int) -> str:
    """Jeton d'accès pour la LECTURE de la boîte Gmail.

    gmail.readonly est un scope restreint désormais désactivé par défaut (conformité
    Google CASA). Si le compte ne l'a pas accordé, on renvoie une erreur explicite
    au lieu d'un 403 brut de l'API Google.
    """
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=organisation_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connexion Google non configurée.")
    if GMAIL_READONLY_SCOPE not in set(connection.scopes or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Lecture de la boîte Gmail non autorisée : le scope gmail.readonly n'est pas "
                "accordé. Cette fonctionnalité est désactivée par défaut pour la conformité ; "
                "un administrateur peut la réactiver via GOOGLE_OAUTH_SCOPES."
            ),
        )
    return await refresh_access_token_if_needed(db, connection)


async def _connection_and_access_token(db: AsyncSession, user: User, organisation_id: int):
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=organisation_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connexion Google non configurée.")
    return connection, await refresh_access_token_if_needed(db, connection)


async def _gmail_get(access_token: str, path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    if response.status_code == 401:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connexion Gmail expirée.")
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gmail API indisponible.")
    return response.json()


async def _gmail_post(access_token: str, path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    if response.status_code == 401:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connexion Gmail expirée.")
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Création du brouillon Gmail impossible.")
    return response.json()


def _encode_mime_message(
    *,
    to: str,
    subject: str,
    body: str,
    in_reply_to_message_id: str | None = None,
) -> str:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if in_reply_to_message_id:
        message["In-Reply-To"] = in_reply_to_message_id
        message["References"] = in_reply_to_message_id
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")


async def list_recent_messages(db: AsyncSession, user: User, organisation_id: int, limit: int = 20) -> list[dict]:
    access_token = await _readonly_access_token(db, user, organisation_id)
    listing = await _gmail_get(
        access_token,
        "/messages",
        {"maxResults": max(1, min(limit, 50)), "q": "newer_than:30d"},
    )
    messages = listing.get("messages") or []
    rows = []
    for item in messages:
        message_id = item.get("id")
        if not message_id:
            continue
        detail = await _gmail_get(access_token, f"/messages/{message_id}", {"format": "metadata"})
        headers = _headers_to_dict(detail)
        rows.append(
            {
                "id": detail.get("id"),
                "thread_id": detail.get("threadId"),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "subject": headers.get("subject"),
                "snippet": detail.get("snippet"),
                "received_at": _parse_date(headers.get("date")),
                "labels": detail.get("labelIds") or [],
                "has_attachments": _has_attachments(detail),
            }
        )
    return rows


async def get_message_detail(db: AsyncSession, user: User, organisation_id: int, message_id: str) -> dict:
    access_token = await _readonly_access_token(db, user, organisation_id)
    detail = await _gmail_get(access_token, f"/messages/{message_id}", {"format": "full"})
    headers = _headers_to_dict(detail)
    useful_headers = {
        key: value
        for key, value in headers.items()
        if key in {"from", "to", "cc", "date", "subject", "message-id"}
    }
    return {
        "id": detail.get("id"),
        "thread_id": detail.get("threadId"),
        "headers": useful_headers,
        "subject": headers.get("subject"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "cc": headers.get("cc"),
        "date": headers.get("date"),
        "snippet": detail.get("snippet"),
        "body": _extract_text_body(detail),
        "labels": detail.get("labelIds") or [],
        "attachments": _attachments(detail),
    }


async def create_gmail_draft(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    *,
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    in_reply_to_message_id: str | None = None,
) -> dict:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=organisation_id, active_only=True)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connexion Google non configurée.")
    scopes = set(connection.scopes or [])
    if GMAIL_COMPOSE_SCOPE not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scope Gmail compose manquant. Reconnectez le compte Google.",
        )
    access_token = await refresh_access_token_if_needed(db, connection)
    if not to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Destinataire requis pour le brouillon Gmail.")
    raw = _encode_mime_message(
        to=to,
        subject=subject,
        body=body,
        in_reply_to_message_id=in_reply_to_message_id,
    )
    message_payload: dict = {"raw": raw}
    if thread_id:
        message_payload["threadId"] = thread_id
    result = await _gmail_post(access_token, "/drafts", {"message": message_payload})
    message = result.get("message") or {}
    return {
        "gmail_draft_id": result.get("id"),
        "gmail_message_id": message.get("id"),
        "thread_id": message.get("threadId") or thread_id,
        "status": "gmail_draft_created",
    }
