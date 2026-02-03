from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import BootstrapAdminRequest, ChangePasswordRequest, LoginRequest, MeResponse, TokenResponse

router = APIRouter()


def _set_refresh_cookie(response: Response, raw_refresh_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain or None,
        path="/",
        expires=int(expires_at.timestamp()),
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/",
        domain=settings.refresh_cookie_domain or None,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    res = await db.execute(select(User).where(User.email == payload.email))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Migration compatibility:
    # Legacy auth passwords cannot be migrated. If hashed_password is missing, we accept
    # a one-time default password (ONECCPK) and force a password change.
    if not user.hashed_password:
        if payload.password != "ONECCPK":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password reset required (use the default password)",
            )
        user.hashed_password = hash_password("ONECCPK")
        user.must_change_password = True
        await db.commit()

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token, access_exp = create_access_token(subject=str(user.id), role=user.role)
    raw_refresh, jti, refresh_exp = create_refresh_token(subject=str(user.id))

    rt = RefreshToken(
        user_id=user.id,
        jti=jti,
        token_hash=hash_refresh_token(raw_refresh),
        revoked=False,
        expires_at=refresh_exp,
    )
    db.add(rt)
    await db.commit()

    _set_refresh_cookie(response, raw_refresh, refresh_exp)

    return TokenResponse(
        access_token=access_token,
        expires_in=int((access_exp - datetime.now(timezone.utc)).total_seconds()),
        must_change_password=user.must_change_password,
        role=user.role,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    raw_refresh = request.cookies.get(settings.refresh_cookie_name)
    if not raw_refresh:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = decode_token(raw_refresh)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    sub = payload.get("sub")
    jti = payload.get("jti")
    if not sub or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = uuid.UUID(sub)

    # ensure user exists and is active
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    token_hash = hash_refresh_token(raw_refresh)
    res = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.jti == jti,
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    stored = res.scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    # rotate token: revoke old
    await db.execute(update(RefreshToken).where(RefreshToken.id == stored.id).values(revoked=True))

    access_token, access_exp = create_access_token(subject=str(user.id), role=user.role)
    new_raw_refresh, new_jti, new_refresh_exp = create_refresh_token(subject=str(user.id))

    new_rt = RefreshToken(
        user_id=user.id,
        jti=new_jti,
        token_hash=hash_refresh_token(new_raw_refresh),
        revoked=False,
        expires_at=new_refresh_exp,
    )
    db.add(new_rt)
    await db.commit()

    _set_refresh_cookie(response, new_raw_refresh, new_refresh_exp)

    return TokenResponse(
        access_token=access_token,
        expires_in=int((access_exp - datetime.now(timezone.utc)).total_seconds()),
        must_change_password=user.must_change_password,
        role=user.role,
    )


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    # best-effort revoke by hash if cookie exists
    raw_refresh = request.cookies.get(settings.refresh_cookie_name)
    if raw_refresh:
        try:
            payload = decode_token(raw_refresh)
            if payload.get("type") == "refresh" and payload.get("sub") and payload.get("jti"):
                user_id = uuid.UUID(payload["sub"])
                token_hash = hash_refresh_token(raw_refresh)
                await db.execute(
                    update(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.jti == payload["jti"],
                        RefreshToken.token_hash == token_hash,
                    )
                    .values(revoked=True)
                )
                await db.commit()
        except Exception:
            pass

    _clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=str(user.id),
        email=user.email,
        nom=user.nom,
        prenom=user.prenom,
        role=user.role,
        active=user.active,
        must_change_password=user.must_change_password,
        created_at=user.created_at.isoformat() if getattr(user, "created_at", None) else None,
    )


@router.post("/bootstrap-admin")
async def bootstrap_admin(payload: BootstrapAdminRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """One-time endpoint to create the first admin user.

    Must be protected by a server-side secret (BOOTSTRAP_ADMIN_PASSWORD).
    Works only if there is no user yet.
    """
    if not settings.bootstrap_admin_password:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Bootstrap disabled")

    if payload.bootstrap_password != settings.bootstrap_admin_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bootstrap password")

    # allow only if there is no admin yet (works both for fresh DB and imported DB)
    res = await db.execute(select(User.id).where(User.role == "admin").limit(1))
    if res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Admin already exists")

    user = User(
        email=str(payload.email).lower(),
        nom=payload.nom,
        prenom=payload.prenom,
        hashed_password=hash_password(payload.password),
        role="admin",
        active=True,
        must_change_password=False,
    )
    db.add(user)
    await db.commit()

    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not payload.new_password or len(payload.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password too short")

    # If the user is forced to change password (must_change_password), we allow omitting current_password.
    if not user.must_change_password:
        if not payload.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password required")
        if not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password invalid")
    else:
        # If provided, still verify it
        if payload.current_password and not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password invalid")

    new_hash = hash_password(payload.new_password)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(hashed_password=new_hash, must_change_password=False)
    )
    await db.commit()

    return {"ok": True}
