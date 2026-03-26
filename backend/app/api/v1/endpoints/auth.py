import uuid
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.limiter import limiter
from passlib.exc import UnknownHashError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_password_strength,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.services.service_access import get_user_service_ids
from app.models.refresh_token import RefreshToken
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.rbac import Role
from app.models.user import User
from app.models.organisation import Organisation
from app.schemas.auth import (
    BootstrapAdminRequest,
    ChangePasswordRequest,
    ConfirmPasswordUpdate,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RequestOtpRequest,
    RequestPasswordChange,
    TokenResponse,
    TenantDiscoveryItem,
)
from app.core.tenant_resolver import extract_tenant_hint, is_admin_host, resolve_tenant
from app.services.mailer import send_security_code

router = APIRouter()


def _set_refresh_cookie(response: Response, raw_refresh_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.refresh_cookie_secure_effective(),
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_otp() -> str:
    return f"{secrets.randbelow(1000000):06d}"


@router.get("/discover-tenants", response_model=list[TenantDiscoveryItem])
async def discover_tenants(email: str, db: AsyncSession = Depends(get_db)) -> list[TenantDiscoveryItem]:
    normalized = email.strip().lower()
    user_res = await db.execute(select(User).where(User.email == normalized, User.active.is_(True)))
    user = user_res.scalar_one_or_none()
    if user and (user.role or "").lower() == "super_admin":
        org_res = await db.execute(
            select(Organisation.id, Organisation.nom, Organisation.slug)
            .where(Organisation.is_active.is_(True))
            .order_by(Organisation.nom.asc())
        )
        rows = org_res.all()
        if rows:
            return [TenantDiscoveryItem(id=row[0], name=row[1], slug=row[2]) for row in rows]
        return [TenantDiscoveryItem(id=0, name="Administration centrale", slug="admin")]
    res = await db.execute(
        select(Organisation.id, Organisation.nom, Organisation.slug)
        .join(User, User.organisation_id == Organisation.id)
        .where(User.email == normalized, User.active.is_(True), Organisation.is_active.is_(True))
        .distinct()
        .order_by(Organisation.nom.asc())
    )
    rows = res.all()
    if not rows:
        raise HTTPException(status_code=404, detail="Utilisateur non reconnu")

    return [TenantDiscoveryItem(id=row[0], name=row[1], slug=row[2]) for row in rows]


async def _resolve_user_for_email(
    db: AsyncSession,
    email: str,
    request: Request | None = None,
    x_tenant_id: str | None = None,
) -> tuple[User | None, Organisation | None]:
    normalized = email.strip().lower()
    tenant_hint = extract_tenant_hint(request, x_tenant_id) if request is not None else (x_tenant_id or None)
    if tenant_hint:
        hinted_org = await resolve_tenant(db, tenant_hint)
        if hinted_org is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")
        super_res = await db.execute(
            select(User)
            .where(
                User.email == normalized,
                User.active.is_(True),
                func.lower(User.role) == "super_admin",
            )
            .order_by(User.organisation_id.asc())
        )
        super_user = super_res.scalars().first()
        if super_user is not None:
            return super_user, hinted_org
        res = await db.execute(
            select(User).where(User.email == normalized, User.organisation_id == hinted_org.id)
        )
        return res.scalar_one_or_none(), hinted_org

    res = await db.execute(select(User).where(User.email == normalized))
    users = res.scalars().all()
    if len(users) > 1:
        default_org = await resolve_tenant(db, "cn")
        if default_org is not None:
            user_res = await db.execute(
                select(User).where(User.email == normalized, User.organisation_id == default_org.id)
            )
            default_user = user_res.scalar_one_or_none()
            if default_user is not None:
                return default_user, default_org
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organisation requise")
    return (users[0] if users else None), None


async def _load_org(db: AsyncSession, org_id: int | None) -> Organisation:
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation requise")
    res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation introuvable")
    return org


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> LoginResponse:
    user, hinted_org = await _resolve_user_for_email(db, payload.email, request, x_tenant_id)
    admin_host = is_admin_host(request)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Migration compatibility:
    # Legacy auth passwords cannot be migrated. If hashed_password is missing, we accept
    # a one-time default password (configured via MIGRATION_DEFAULT_PASSWORD) and force a password change.
    if not user.hashed_password:
        default_pwd = settings.migration_default_password
        if not default_pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Compte non initialisé. Contacter l'administrateur.",
            )
        if payload.password != default_pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password reset required (use the default password)",
            )
        user.hashed_password = hash_password(default_pwd)
        user.must_change_password = True
        user.is_first_login = True
        user.is_email_verified = False
        await db.commit()

    try:
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except UnknownHashError:
        default_pwd = settings.migration_default_password
        if not default_pwd or payload.password != default_pwd:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user.hashed_password = hash_password(default_pwd)
        user.must_change_password = True
        user.is_first_login = True
        user.is_email_verified = False
        await db.commit()

    if admin_host and (user.role or "").lower() != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin requis")

    if hinted_org is not None and hinted_org.id != user.organisation_id:
        if (user.role or "").lower() != "super_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")

    if user.must_change_password or user.is_first_login or not user.is_email_verified:
        return LoginResponse(
            requires_otp=True,
            otp_required_reason="Password verification required",
            must_change_password=user.must_change_password,
            role=user.role,
        )

    if hinted_org is not None:
        org = hinted_org
    elif admin_host and (user.role or "").lower() == "super_admin" and user.organisation_id is None:
        org = None
    else:
        org = await _load_org(db, user.organisation_id)
    access_token, access_exp = create_access_token(
        subject=str(user.id),
        role=user.role,
        org_id=org.id if org else None,
        org_uuid=str(org.uuid) if org else None,
        org_slug=org.slug if org else None,
        plan_status=org.status_abonnement if org else None,
    )
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

    return LoginResponse(
        access_token=access_token,
        expires_in=int((access_exp - datetime.now(timezone.utc)).total_seconds()),
        must_change_password=user.must_change_password,
        role=user.role,
        organisation_id=org.id if org else None,
        organisation_uuid=str(org.uuid) if org else None,
        organisation_slug=org.slug if org else None,
        organisation_name=org.nom if org else None,
        plan_status=org.status_abonnement if org else None,
        plan_type=org.plan_type if org else None,
    )


@router.post("/request-password-reset")
async def request_password_reset(
    payload: RequestOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    user, _ = await _resolve_user_for_email(db, payload.email, request, x_tenant_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    settings_res = await db.execute(
        select(SystemSettings)
        .where(SystemSettings.organisation_id == user.organisation_id)
        .limit(1)
    )
    ns = settings_res.scalar_one_or_none()
    if not ns or not ns.email_expediteur or not ns.smtp_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Configuration SMTP manquante")

    code = _generate_otp()
    user.otp_code = code
    user.otp_created_at = _utcnow()
    user.otp_attempts = 0
    await db.commit()

    display_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email
    org_res = await db.execute(
        select(Organisation.nom).where(Organisation.id == user.organisation_id).limit(1)
    )
    org_name = org_res.scalar_one_or_none()
    send_security_code(
        smtp_host=ns.smtp_host or "smtp.gmail.com",
        smtp_port=int(ns.smtp_port or 465),
        smtp_user=ns.email_expediteur,
        smtp_password=ns.smtp_password,
        sender=ns.email_expediteur,
        recipient=user.email,
        recipient_name=display_name,
        code=code,
        brand_name="ONEC",
        organisation_name=org_name,
    )

    return {"ok": True, "message": "Code envoyé par email"}


@router.post("/request-password-change")
async def request_password_change(
    payload: RequestPasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    if not user.must_change_password:
        if not payload.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password required")
        if not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password invalid")

    settings_res = await db.execute(
        select(SystemSettings)
        .where(SystemSettings.organisation_id == user.organisation_id)
        .limit(1)
    )
    ns = settings_res.scalar_one_or_none()
    if not ns or not ns.email_expediteur or not ns.smtp_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Configuration SMTP manquante")

    code = _generate_otp()
    user.otp_code = code
    user.otp_created_at = _utcnow()
    user.otp_attempts = 0
    await db.commit()

    display_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email
    org_res = await db.execute(
        select(Organisation.nom).where(Organisation.id == user.organisation_id).limit(1)
    )
    org_name = org_res.scalar_one_or_none()
    send_security_code(
        smtp_host=ns.smtp_host or "smtp.gmail.com",
        smtp_port=int(ns.smtp_port or 465),
        smtp_user=ns.email_expediteur,
        smtp_password=ns.smtp_password,
        sender=ns.email_expediteur,
        recipient=user.email,
        recipient_name=display_name,
        code=code,
        brand_name="ONEC",
        organisation_name=org_name,
    )

    return {"ok": True, "message": "Code envoyé par email"}


@router.post("/confirm-password-change", response_model=TokenResponse)
async def confirm_password_change(
    payload: ConfirmPasswordUpdate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> TokenResponse:
    user, _ = await _resolve_user_for_email(db, payload.email, request, x_tenant_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    if not user.otp_code or not user.otp_created_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucun code actif. Veuillez en demander un.")

    if user.otp_attempts >= 3:
        user.otp_code = None
        user.otp_created_at = None
        user.otp_attempts = 0
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Trop de tentatives. Nouveau code requis.")

    expires_at = user.otp_created_at + timedelta(minutes=2)
    if _utcnow() > expires_at:
        user.otp_code = None
        user.otp_created_at = None
        user.otp_attempts = 0
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expiré. Veuillez en demander un nouveau.")

    if payload.otp_code != user.otp_code:
        user.otp_attempts = (user.otp_attempts or 0) + 1
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code de confirmation incorrect")

    if user.hashed_password and verify_password(payload.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien.",
        )

    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_hash = hash_password(payload.new_password)
    user.hashed_password = new_hash
    user.must_change_password = False
    user.is_first_login = False
    user.is_email_verified = True
    user.otp_code = None
    user.otp_created_at = None
    user.otp_attempts = 0
    await db.commit()

    org = await _load_org(db, user.organisation_id)
    access_token, access_exp = create_access_token(
        subject=str(user.id),
        role=user.role,
        org_id=org.id,
        org_uuid=str(org.uuid),
        org_slug=org.slug,
        plan_status=org.status_abonnement,
    )
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
        organisation_id=org.id,
        organisation_uuid=str(org.uuid),
        organisation_slug=org.slug,
        plan_status=org.status_abonnement,
        plan_type=org.plan_type,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
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
    if user.must_change_password or user.is_first_login or not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password verification required")

    token_hash = hash_refresh_token(raw_refresh)
    res = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.jti == jti,
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    stored = res.scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    # rotate token: revoke old
    await db.execute(update(RefreshToken).where(RefreshToken.id == stored.id).values(revoked=True))

    org = await _load_org(db, user.organisation_id)
    access_token, access_exp = create_access_token(
        subject=str(user.id),
        role=user.role,
        org_id=org.id,
        org_uuid=str(org.uuid),
        org_slug=org.slug,
        plan_status=org.status_abonnement,
    )
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
        organisation_id=org.id,
        organisation_uuid=str(org.uuid),
        organisation_slug=org.slug,
        plan_status=org.status_abonnement,
        plan_type=org.plan_type,
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
async def me(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    service_ids = await get_user_service_ids(db, user)
    tenant_id = getattr(request.state, "tenant_id", None) or user.organisation_id
    org = await _load_org(db, tenant_id)
    return MeResponse(
        id=str(user.id),
        email=user.email,
        nom=user.nom,
        prenom=user.prenom,
        role=user.role,
        service_id=getattr(user, "service_id", None),
        service_ids=service_ids,
        active=user.active,
        must_change_password=user.must_change_password,
        is_email_verified=user.is_email_verified,
        is_first_login=user.is_first_login,
        created_at=user.created_at.isoformat() if getattr(user, "created_at", None) else None,
        organisation_id=org.id,
        organisation_uuid=str(org.uuid),
        organisation_slug=org.slug,
        organisation_name=org.nom,
        plan_status=org.status_abonnement,
        plan_type=org.plan_type,
        plan_expires_at=org.date_expiration_abonnement.isoformat() if org.date_expiration_abonnement else None,
        user_limit=org.limite_utilisateurs,
    )


@router.post("/bootstrap-admin")
@limiter.limit("3/minute")
async def bootstrap_admin(
    request: Request,
    payload: BootstrapAdminRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
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

    org_res = await db.execute(select(Organisation).order_by(Organisation.id.asc()).limit(1))
    org = org_res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organisation manquante")

    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user = User(
        email=str(payload.email).lower(),
        nom=payload.nom,
        prenom=payload.prenom,
        hashed_password=hash_password(payload.password),
        role="admin",
        role_id=None,
        active=True,
        must_change_password=False,
        is_first_login=False,
        is_email_verified=True,
        organisation_id=org.id,
    )
    role_res = await db.execute(select(Role).where(Role.code == "admin"))
    admin_role = role_res.scalar_one_or_none()
    if admin_role:
        user.role_id = admin_role.id
    db.add(user)
    await db.commit()

    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="OTP required. Use /auth/request-password-change and /auth/confirm-password-change.",
    )
