from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import anyio
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


# bcrypt coûte plusieurs centaines de millisecondes de CPU par appel (mesuré à
# 609 ms sur le poste de dev, 200-300 ms sur un serveur). Appelé directement
# depuis une coroutine, il fige la boucle d'événements — donc *toutes* les
# requêtes en cours, pas seulement celle qui s'authentifie. Depuis un contexte
# async, utiliser systématiquement les variantes ci-dessous.


async def hash_password_async(password: str) -> str:
    return await anyio.to_thread.run_sync(pwd_context.hash, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await anyio.to_thread.run_sync(pwd_context.verify, password, password_hash)


def validate_password_strength(password: str) -> None:
    if not password or len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
    if not any(ch.isupper() for ch in password):
        raise ValueError("Le mot de passe doit contenir au moins une majuscule.")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Le mot de passe doit contenir au moins un chiffre.")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    subject: str,
    role: str,
    org_id: int | None = None,
    org_uuid: str | None = None,
    org_slug: str | None = None,
    plan_status: str | None = None,
) -> tuple[str, datetime]:
    expires_at = _utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "role": role,
        "org_id": org_id,
        "org_uuid": org_uuid,
        "org_slug": org_slug,
        "plan_status": plan_status,
        "type": "access",
        "exp": int(expires_at.timestamp()),
        "iat": int(_utcnow().timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, expires_at


def create_refresh_token(*, subject: str) -> tuple[str, str, datetime]:
    """Returns (raw_token, jti, expires_at). Raw token is put in HttpOnly cookie.

    We store only a hash of the raw token in DB.
    """
    jti = secrets.token_urlsafe(32)
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "type": "refresh",
        "jti": jti,
        "exp": int(expires_at.timestamp()),
        "iat": int(_utcnow().timestamp()),
    }
    raw = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return raw, jti, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"leeway": 60},
    )
