from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.modules.secretariat.models import OAuthConnection

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
STATE_AUDIENCE = "onec-secretariat-google-oauth"
STATE_EXPIRE_MINUTES = 15
GOOGLE_PROVIDER = "google"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
ALLOWED_GOOGLE_SCOPES = {GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _google_scopes() -> list[str]:
    configured = [scope.strip() for scope in (settings.google_oauth_scopes or "").replace(",", " ").split() if scope.strip()]
    scopes = configured or [GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE]
    filtered = [scope for scope in scopes if scope in ALLOWED_GOOGLE_SCOPES]
    return filtered or [GMAIL_READONLY_SCOPE]


def _require_google_config() -> None:
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_oauth_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration Google OAuth incomplète. Configurer dans la console SaaS : Super Admin → Intégrations → Google OAuth.",
        )


async def _get_google_config(db: AsyncSession) -> tuple[str, str, str]:
    """Retourne (client_id, client_secret, redirect_uri) — DB en priorité, .env en fallback.

    Sélectionne l'URI locale (dev) si enable_debug_endpoints est True, sinon l'URI production.
    """
    from sqlalchemy import select as _select
    from app.models.platform_settings import PlatformSettings
    from app.core.encryption import decrypt_secret

    res = await db.execute(_select(PlatformSettings).where(PlatformSettings.id == 1))
    ps = res.scalar_one_or_none()

    client_id = (ps.google_client_id if ps else None) or settings.google_client_id

    # URI sélectionnée selon les toggles activés (production prioritaire sur locale)
    redirect_uri = None
    if ps and ps.google_oauth_redirect_uri and ps.google_oauth_redirect_uri_enabled:
        redirect_uri = ps.google_oauth_redirect_uri
    elif ps and ps.google_oauth_redirect_uri_local and ps.google_oauth_redirect_uri_local_enabled:
        redirect_uri = ps.google_oauth_redirect_uri_local
    if not redirect_uri:
        redirect_uri = settings.google_oauth_redirect_uri

    client_secret = settings.google_client_secret
    if ps and ps.google_client_secret_encrypted:
        try:
            client_secret = decrypt_secret(ps.google_client_secret_encrypted)
        except Exception:
            pass

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration Google OAuth incomplète. Configurer dans la console SaaS : Super Admin → Intégrations → Google OAuth.",
        )
    return client_id, client_secret, redirect_uri


def _fernet() -> Fernet:
    key_material = settings.jwt_secret.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
    return Fernet(key)


def encrypt_token(raw_token: str | None) -> str | None:
    if not raw_token:
        return None
    return _fernet().encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str | None) -> str | None:
    if not encrypted_token:
        return None
    try:
        return _fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token OAuth illisible.")


async def build_google_authorization_url(
    *, db: AsyncSession, user: User, organisation_id: int, frontend_origin: str | None = None
) -> str:
    import logging
    _log = logging.getLogger("onec_cpk.oauth")
    client_id, _secret, redirect_uri = await _get_google_config(db)
    _log.info(
        "[OAuth/connect] redirect_uri_effectif=%s  client_id=%s  user=%s  org=%s  frontend_origin=%s",
        redirect_uri, client_id[:20] + "...", user.email, organisation_id, frontend_origin,
    )
    # L'origin du frontend est embarqué dans le state pour que le callback
    # puisse rediriger vers la bonne URL (multi-tenant, dev vs prod).
    return_to = f"{frontend_origin.rstrip('/')}/secretariat/courrier" if frontend_origin else None
    state_payload = {
        "iss": settings.jwt_issuer,
        "aud": STATE_AUDIENCE,
        "sub": str(user.id),
        "org_id": organisation_id,
        "nonce": secrets.token_urlsafe(24),
        "iat": int(_utcnow().timestamp()),
        "exp": int((_utcnow() + timedelta(minutes=STATE_EXPIRE_MINUTES)).timestamp()),
    }
    if return_to:
        state_payload["return_to"] = return_to
    state = jwt.encode(state_payload, settings.jwt_secret, algorithm="HS256")
    scopes = _google_scopes()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    final_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    _log.info(
        "[OAuth/connect] URL générée:\n"
        "  client_id     = %s\n"
        "  redirect_uri  = %s\n"
        "  scope         = %s\n"
        "  response_type = code\n"
        "  access_type   = offline\n"
        "  return_to     = %s",
        client_id, redirect_uri, scopes, return_to,
    )
    return final_url


def validate_google_state(state_token: str) -> tuple[UUID, int, str | None]:
    """Retourne (user_id, organisation_id, return_to_url)."""
    try:
        payload = jwt.decode(
            state_token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=STATE_AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"leeway": 60},
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth invalide.")
    user_id = payload.get("sub")
    organisation_id = payload.get("org_id")
    if not user_id or organisation_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State OAuth incomplet.")
    return UUID(str(user_id)), int(organisation_id), payload.get("return_to")


async def exchange_code_for_tokens(code: str, db: AsyncSession) -> dict:
    client_id, client_secret, redirect_uri = await _get_google_config(db)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Échange OAuth Google refusé.")
    return response.json()


async def fetch_google_email(access_token: str) -> str | None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(GOOGLE_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code >= 400:
        return None
    payload = response.json()
    email = payload.get("emailAddress")
    return str(email) if email else None


async def get_oauth_connection(
    db: AsyncSession,
    *,
    user_id: UUID,
    organisation_id: int,
    active_only: bool = False,
) -> OAuthConnection | None:
    query = select(OAuthConnection).where(
        OAuthConnection.organisation_id == organisation_id,
        OAuthConnection.user_id == user_id,
        OAuthConnection.provider == GOOGLE_PROVIDER,
    )
    if active_only:
        query = query.where(OAuthConnection.status == "connected")
    res = await db.execute(query.order_by(OAuthConnection.updated_at.desc()).limit(1))
    return res.scalar_one_or_none()


async def upsert_google_connection(
    db: AsyncSession,
    *,
    user_id: UUID,
    organisation_id: int,
    tokens: dict,
    email: str | None,
) -> OAuthConnection:
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token Google manquant.")
    refresh_token = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in") or 3600)
    scope_value = str(tokens.get("scope") or " ".join(_google_scopes()))
    scopes = [scope for scope in scope_value.split() if scope in ALLOWED_GOOGLE_SCOPES]
    connection = await get_oauth_connection(db, user_id=user_id, organisation_id=organisation_id)
    if connection is None:
        connection = OAuthConnection(
            organisation_id=organisation_id,
            user_id=user_id,
            provider=GOOGLE_PROVIDER,
        )
        db.add(connection)
    connection.email = email
    connection.scopes = scopes or _google_scopes()
    connection.status = "connected"
    connection.access_token_encrypted = encrypt_token(access_token)
    if refresh_token:
        connection.refresh_token_encrypted = encrypt_token(refresh_token)
    connection.expires_at = _utcnow() + timedelta(seconds=max(60, expires_in - 60))
    return connection


async def refresh_access_token_if_needed(db: AsyncSession, connection: OAuthConnection) -> str:
    access_token = decrypt_token(connection.access_token_encrypted)
    if access_token and connection.expires_at and connection.expires_at > _utcnow() + timedelta(minutes=2):
        return access_token
    refresh_token = decrypt_token(connection.refresh_token_encrypted)
    if not refresh_token:
        connection.status = "expired"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connexion Google expirée.")
    client_id, client_secret, _redirect_uri = await _get_google_config(db)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        connection.status = "expired"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Rafraîchissement Google refusé.")
    payload = response.json()
    new_access_token = payload.get("access_token")
    if not new_access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token Google manquant.")
    expires_in = int(payload.get("expires_in") or 3600)
    connection.access_token_encrypted = encrypt_token(new_access_token)
    connection.expires_at = _utcnow() + timedelta(seconds=max(60, expires_in - 60))
    connection.status = "connected"
    await db.commit()
    return new_access_token


async def disconnect_google_connection(db: AsyncSession, connection: OAuthConnection) -> OAuthConnection:
    connection.status = "disconnected"
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.expires_at = None
    await db.flush()
    return connection
