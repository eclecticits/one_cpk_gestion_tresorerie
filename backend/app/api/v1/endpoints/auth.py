import uuid
import secrets
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Request, Response, status
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
from app.services.email_config import resolve_smtp_config
from app.services.system_settings_service import get_system_settings
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
from app.core.tenant_resolver import (
    describe_tenant_resolution,
    extract_tenant_hint,
    has_tenant_hint_conflict,
    is_admin_host,
    resolve_tenant,
)
from app.services.mailer import send_security_code

router = APIRouter()
logger = logging.getLogger("onec_cpk_api")


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
        logger.warning("AUTH_DISCOVER_TENANTS_USER_NOT_FOUND email=%s", normalized)
        raise HTTPException(status_code=404, detail="Utilisateur non reconnu")

    return [TenantDiscoveryItem(id=row[0], name=row[1], slug=row[2]) for row in rows]


async def _resolve_user_for_email(
    db: AsyncSession,
    email: str,
    request: Request | None = None,
    x_tenant_id: str | None = None,
    explicit_tenant_hint: str | None = None,
) -> tuple[User | None, Organisation | None]:
    normalized = email.strip().lower()
    resolution = describe_tenant_resolution(request, x_tenant_id) if request is not None else None
    if request is not None and has_tenant_hint_conflict(request, x_tenant_id):
        logger.warning(
            "Tenant conflict rejected during auth: host=%s header=%s path=%s email=%s",
            request.url.hostname,
            x_tenant_id,
            request.url.path,
            normalized,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conflit de tenant")
    tenant_hint = extract_tenant_hint(request, x_tenant_id) if request is not None else (x_tenant_id or None)
    explicit_hint = str(explicit_tenant_hint).strip().lower() if explicit_tenant_hint else None
    if tenant_hint and explicit_hint and tenant_hint != explicit_hint:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conflit de tenant")
    tenant_hint = tenant_hint or explicit_hint
    if tenant_hint:
        hinted_org = await resolve_tenant(db, tenant_hint)
        if hinted_org is None:
            logger.warning("AUTH_TENANT_NOT_FOUND email=%s tenant_hint=%s", normalized, tenant_hint)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")
        if hinted_org.is_active is False:
            logger.warning("AUTH_TENANT_INACTIVE email=%s tenant_id=%s tenant_slug=%s", normalized, hinted_org.id, hinted_org.slug)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation inactive")
        logger.info(
            "Tenant auth hint resolved: path=%s host=%s source=%s host_hint=%s header_hint=%s effective_hint=%s email=%s tenant_id=%s tenant_slug=%s",
            request.url.path if request is not None else None,
            resolution["host"] if resolution is not None else None,
            resolution["source"] if resolution is not None else "header",
            resolution["host_hint"] if resolution is not None else None,
            resolution["header_hint"] if resolution is not None else x_tenant_id,
            resolution["effective_hint"] if resolution is not None else tenant_hint,
            normalized,
            hinted_org.id,
            hinted_org.slug,
        )
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
        user = res.scalar_one_or_none()
        if user is None:
            logger.warning(
                "AUTH_USER_NOT_FOUND_IN_TENANT email=%s tenant_id=%s tenant_slug=%s",
                normalized,
                hinted_org.id,
                hinted_org.slug,
            )
        return user, hinted_org

    res = await db.execute(select(User).where(User.email == normalized))
    users = res.scalars().all()
    if len(users) > 1:
        logger.warning("AUTH_AMBIGUOUS_TENANT email=%s tenant_count=%s", normalized, len(users))
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
    explicit_tenant_hint = (
        payload.tenant_slug
        or (str(payload.organisation_id) if payload.organisation_id is not None else None)
        or (str(payload.tenant_id) if payload.tenant_id is not None else None)
    )
    user, hinted_org = await _resolve_user_for_email(
        db,
        payload.email,
        request,
        x_tenant_id,
        explicit_tenant_hint=explicit_tenant_hint,
    )
    admin_host = is_admin_host(request)
    if user is None:
        logger.warning("AUTH_LOGIN_USER_NOT_FOUND email=%s tenant_hint=%s", payload.email.strip().lower(), explicit_tenant_hint)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.active:
        logger.warning("AUTH_LOGIN_USER_INACTIVE email=%s user_id=%s tenant_id=%s", user.email, user.id, user.organisation_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Migration compatibility:
    # Legacy auth passwords cannot be migrated. If hashed_password is missing, we accept
    # a one-time default password (configured via MIGRATION_DEFAULT_PASSWORD) and force a password change.
    if not user.hashed_password:
        default_pwd = settings.migration_default_password
        if not default_pwd:
            logger.warning("AUTH_LOGIN_PASSWORD_MISSING email=%s user_id=%s", user.email, user.id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Compte non initialisé. Contacter l'administrateur.",
            )
        if payload.password != default_pwd:
            logger.warning("AUTH_LOGIN_BAD_PASSWORD email=%s user_id=%s reason=migration_default_mismatch", user.email, user.id)
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
            logger.warning("AUTH_LOGIN_BAD_PASSWORD email=%s user_id=%s", user.email, user.id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except UnknownHashError:
        default_pwd = settings.migration_default_password
        if not default_pwd or payload.password != default_pwd:
            logger.warning("AUTH_LOGIN_BAD_PASSWORD email=%s user_id=%s reason=unknown_hash", user.email, user.id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user.hashed_password = hash_password(default_pwd)
        user.must_change_password = True
        user.is_first_login = True
        user.is_email_verified = False
        await db.commit()

    if admin_host and (user.role or "").lower() != "super_admin":
        logger.warning("AUTH_LOGIN_ADMIN_HOST_FORBIDDEN email=%s user_id=%s role=%s", user.email, user.id, user.role)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin requis")

    if hinted_org is not None and hinted_org.id != user.organisation_id:
        if (user.role or "").lower() != "super_admin":
            logger.warning(
                "AUTH_LOGIN_TENANT_MISMATCH email=%s user_id=%s user_org_id=%s hinted_org_id=%s",
                user.email,
                user.id,
                user.organisation_id,
                hinted_org.id,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation invalide")

    if not (user.role or "").strip():
        logger.warning("AUTH_LOGIN_USER_WITHOUT_ROLE email=%s user_id=%s tenant_id=%s", user.email, user.id, user.organisation_id)
    elif user.role_id is None and (user.role or "").lower() not in {"admin", "super_admin"}:
        logger.warning(
            "AUTH_LOGIN_ROLE_WITHOUT_PERMISSIONS email=%s user_id=%s role=%s tenant_id=%s",
            user.email,
            user.id,
            user.role,
            user.organisation_id,
        )

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
@limiter.limit("3/minute")
async def request_password_reset(
    payload: RequestOtpRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    generic_response = {"ok": True, "message": "Si le compte existe, un code sera envoyé par email"}
    user, _ = await _resolve_user_for_email(db, payload.email, request, x_tenant_id)
    if user is None or not user.active:
        logger.warning("AUTH_PASSWORD_RESET_UNKNOWN email=%s", payload.email.strip().lower())
        return generic_response

    ns = await get_system_settings(db, user.organisation_id)
    smtp_cfg = resolve_smtp_config(ns)
    if smtp_cfg is None:
        logger.error("AUTH_PASSWORD_RESET_SMTP_MISSING user_id=%s tenant_id=%s", user.id, user.organisation_id)
        return generic_response

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
    # Envoi SMTP hors du chemin critique : smtplib est bloquant (jusqu'à ~20 s)
    # et stallerait la boucle événementielle du worker.
    background_tasks.add_task(
        send_security_code,
        smtp_host=smtp_cfg.host,
        smtp_port=smtp_cfg.port,
        smtp_user=smtp_cfg.user,
        smtp_password=smtp_cfg.password,
        sender=smtp_cfg.sender,
        recipient=user.email,
        recipient_name=display_name,
        code=code,
        brand_name="ONEC",
        organisation_name=org_name,
    )

    return generic_response


@router.post("/request-password-change")
async def request_password_change(
    payload: RequestPasswordChange,
    background_tasks: BackgroundTasks,
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

    ns = await get_system_settings(db, user.organisation_id)
    smtp_cfg = resolve_smtp_config(ns)
    if smtp_cfg is None:
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
    # Envoi SMTP en tâche de fond (smtplib bloquant, cf. request_password_reset).
    background_tasks.add_task(
        send_security_code,
        smtp_host=smtp_cfg.host,
        smtp_port=smtp_cfg.port,
        smtp_user=smtp_cfg.user,
        smtp_password=smtp_cfg.password,
        sender=smtp_cfg.sender,
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
    started_at = time.perf_counter()
    try:
        raw_refresh = request.cookies.get(settings.refresh_cookie_name)
        if not raw_refresh:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

        try:
            payload = decode_token(raw_refresh)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        sub = payload.get("sub")
        jti = payload.get("jti")
        if not sub or not jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        try:
            user_id = uuid.UUID(sub)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if user is None or not user.active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")
        if user.must_change_password or user.is_first_login or not user.is_email_verified:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password verification required")
        if user.organisation_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Organisation associée au compte manquante")

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

        await db.execute(update(RefreshToken).where(RefreshToken.id == stored.id).values(revoked=True))

        try:
            org = await _load_org(db, user.organisation_id)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Organisation associée au compte introuvable") from exc
            raise
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
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("AUTH_REFRESH_FAILED path=%s", request.url.path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur interne pendant le rafraîchissement de session.") from exc
    finally:
        logger.info("AUTH_REFRESH_COMPLETED path=%s duration_ms=%s", request.url.path, round((time.perf_counter() - started_at) * 1000, 2))


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
            logger.warning("Révocation du refresh token à la déconnexion échouée", exc_info=True)

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
