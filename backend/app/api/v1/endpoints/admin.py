from __future__ import annotations

import uuid
import secrets
from datetime import datetime, timezone

import re
import logging
import unicodedata
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_tenant_id,
    invalidate_auth_context_cache,
    require_roles,
    has_permission,
)
from app.core.config import settings
from app.core.security import hash_password_async, validate_password_strength
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.print_settings import PrintSettings
from app.models.refresh_token import RefreshToken
from app.models.requisition_approver import RequisitionApprover
from app.models.rubrique import Rubrique
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.rbac import Role, Permission, role_permissions
from app.models.user import User
from app.models.organisation_settings import OrganisationSettings
from app.models.service import Service
from app.models.user_service import user_services
from app.models.user_role import UserRole
from app.services.audit_service import get_request_ip, log_action
from app.services.mailer import _send_email_message, send_in_thread, send_security_code
from app.services.email_config import resolve_smtp_config
from app.services.system_settings_service import consolidate_system_settings
from app.services.weekly_report import send_weekly_report, _get_system_settings
from app.utils.scheduler import get_weekly_report_status
from app.schemas.admin import (
    DeleteUserRequest,
    NotificationSettingsResponse,
    NotificationSettingsUpdateRequest,
    PrintSettingsOut,
    PrintSettingsResponse,
    PrintSettingsUpdateRequest,
    RequisitionApproverCreateRequest,
    RequisitionApproverOut,
    RequisitionApproverUpdateRequest,
    ResetPasswordRequest,
    RubriqueCreateRequest,
    RubriqueOut,
    RubriqueUpdateRequest,
    SetUserPasswordRequest,
    SimpleUserInfo,
    ToggleStatusRequest,
    UserCreateRequest,
    UserListOut,
    UserOut,
    UserRoleAssignmentCreateRequest,
    UserRoleAssignmentOut,
    UserUpdateRequest,
)
from app.schemas.rbac import PermissionOut, RoleOut, RolePermissionsPayload, RoleCreate, RoleUpdate

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.admin")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_default_user_password() -> str:
    default_pwd = settings.default_user_password
    if not default_pwd:
        raise HTTPException(status_code=501, detail="Default user password not configured")
    return default_pwd


def _user_out(u: User) -> UserOut:
    service_ids = []
    if hasattr(u, "services") and u.services:
        service_ids = [s.id for s in u.services]
    if not service_ids and getattr(u, "service_id", None) is not None:
        service_ids = [u.service_id]
    return UserOut(
        id=str(u.id),
        email=u.email,
        nom=getattr(u, "nom", None),
        prenom=getattr(u, "prenom", None),
        role=u.role,
        role_id=u.role_id,
        service_id=getattr(u, "service_id", None),
        service_ids=service_ids,
        active=u.active,
        must_change_password=u.must_change_password,
        is_first_login=u.is_first_login,
        is_email_verified=u.is_email_verified,
        created_at=u.created_at.isoformat() if getattr(u, "created_at", None) else None,
    )


async def _resolve_service_id(db: AsyncSession, service_id: int | None) -> int | None:
    if service_id is None:
        return None
    res = await db.execute(select(Service).where(Service.id == service_id))
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail=f"Service introuvable: {service_id}")
    return service_id


async def _resolve_service_ids(db: AsyncSession, service_ids: list[int] | None) -> list[int]:
    if not service_ids:
        return []
    res = await db.execute(select(Service.id).where(Service.id.in_(service_ids)))
    found = {row[0] for row in res.all()}
    missing = [sid for sid in service_ids if sid not in found]
    if missing:
        missing_values = ", ".join(str(sid) for sid in missing)
        raise HTTPException(status_code=400, detail=f"Service(s) introuvable(s): {missing_values}")
    return list(dict.fromkeys(service_ids))


def _normalize_role_key(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFD", str(value).strip().lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


LEGACY_ROLE_CODE_MAP = {
    "reception": "demandeur",
    "secretariat": "demandeur",
    "comptabilite": "tresorier",
    "tresorerie": "caissier",
    "rapporteur": "rapporteur",
    "admin": "admin",
    "president": "president",
    "demandeur": "demandeur",
    "caissier": "caissier",
    "tresorier": "tresorier",
}

# Rôles rattachés au module secrétariat (cf. tenant_manager) : masqués par défaut
# dans l'annuaire du module financier.
SECRETARIAT_ROLE_CODES = {"reception", "secretariat", "secretaire"}


async def _resolve_role(db: AsyncSession, role_value: str | None) -> Role:
    raw_value = (role_value or "").strip()
    if not raw_value:
        raise HTTPException(status_code=400, detail="Rôle requis")

    normalized_value = _normalize_role_key(raw_value)
    normalized_candidates = {
        normalized_value,
        LEGACY_ROLE_CODE_MAP.get(normalized_value, normalized_value),
    }

    roles_res = await db.execute(select(Role).order_by(Role.id.asc()))
    roles = roles_res.scalars().all()
    for role in roles:
        role_code_key = _normalize_role_key(role.code)
        role_label_key = _normalize_role_key(role.label)
        if role_code_key in normalized_candidates or role_label_key in normalized_candidates:
            return role

    raise HTTPException(status_code=400, detail=f"Rôle introuvable: {raw_value}")


def _rubrique_out(r: Rubrique) -> RubriqueOut:
    return RubriqueOut(
        id=str(r.id),
        code=r.code,
        libelle=r.libelle,
        description=r.description,
        active=r.active,
    )


def _print_settings_out(ps: PrintSettings) -> PrintSettingsOut:
    return PrintSettingsOut(
        id=str(ps.id),
        organization_name=ps.organization_name,
        organization_subtitle=ps.organization_subtitle,
        header_text=ps.header_text,
        address=ps.address,
        phone=ps.phone,
        email=ps.email,
        website=ps.website,
        bank_name=ps.bank_name,
        bank_account=ps.bank_account,
        mobile_money_name=ps.mobile_money_name,
        mobile_money_number=ps.mobile_money_number,
        pied_de_page_legal=ps.pied_de_page_legal,
        afficher_qr_code=ps.afficher_qr_code,
        show_header_logo=ps.show_header_logo,
        show_footer_signature=ps.show_footer_signature,
        logo_url=ps.logo_url,
        stamp_url=ps.stamp_url,
        recu_label_signature=ps.recu_label_signature,
        recu_nom_signataire=ps.recu_nom_signataire,
        sortie_label_signature=ps.sortie_label_signature,
        sortie_nom_signataire=ps.sortie_nom_signataire,
        sortie_sig_label_1=ps.sortie_sig_label_1,
        sortie_sig_label_2=ps.sortie_sig_label_2,
        sortie_sig_label_3=ps.sortie_sig_label_3,
        sortie_sig_hint=ps.sortie_sig_hint,
        show_sortie_qr=ps.show_sortie_qr,
        sortie_qr_base_url=ps.sortie_qr_base_url,
        show_sortie_watermark=ps.show_sortie_watermark,
        sortie_watermark_text=ps.sortie_watermark_text,
        sortie_watermark_opacity=float(ps.sortie_watermark_opacity or 0),
        paper_format=ps.paper_format,
        compact_header=ps.compact_header,
        req_titre_officiel=ps.req_titre_officiel,
        req_label_gauche=ps.req_label_gauche,
        req_nom_gauche=ps.req_nom_gauche,
        req_label_droite=ps.req_label_droite,
        req_nom_droite=ps.req_nom_droite,
        trans_titre_officiel=ps.trans_titre_officiel,
        trans_label_gauche=ps.trans_label_gauche,
        trans_nom_gauche=ps.trans_nom_gauche,
        trans_label_droite=ps.trans_label_droite,
        trans_nom_droite=ps.trans_nom_droite,
        encaissement_libelle_presets=ps.encaissement_libelle_presets,
        default_currency=ps.default_currency,
        secondary_currency=ps.secondary_currency,
        exchange_rate=float(ps.exchange_rate or 0),
        exchange_rate_cdf=float(ps.exchange_rate_cdf or 0),
        exchange_rate_eur=float(ps.exchange_rate_eur or 0),
        exchange_rate_xof=float(ps.exchange_rate_xof or 0),
        fiscal_year=ps.fiscal_year,
        budget_alert_threshold=ps.budget_alert_threshold,
        budget_block_overrun=ps.budget_block_overrun,
        budget_force_roles=ps.budget_force_roles,
    )


def _notification_settings_out(ns: SystemSettings) -> dict:
    return {
        "id": str(ns.id),
        "email_expediteur": ns.email_expediteur,
        "email_president": ns.email_president,
        "emails_bureau_cc": ns.emails_bureau_cc,
        "email_tresorier": ns.email_tresorier,
        "emails_bureau_sortie_cc": ns.emails_bureau_sortie_cc,
        "email_validation_1": ns.email_validation_1,
        "email_validation_final": ns.email_validation_final,
        "max_caisse_amount": ns.max_caisse_amount,
        "budget_poste_excedent_caisse_id": ns.budget_poste_excedent_caisse_id,
        "budget_poste_deficit_caisse_id": ns.budget_poste_deficit_caisse_id,
        "smtp_password": ns.smtp_password,
        "smtp_host": ns.smtp_host,
        "smtp_port": ns.smtp_port,
        "whatsapp_api_url": ns.whatsapp_api_url,
        "whatsapp_api_key": ns.whatsapp_api_key,
        "whatsapp_agents": ns.whatsapp_agents,
        "updated_by": str(ns.updated_by) if ns.updated_by else None,
        "updated_at": ns.updated_at.isoformat() if ns.updated_at else None,
    }


def _sanitize_notification_settings(data: dict, current_user: User) -> dict:
    if (current_user.role or "").lower() == "super_admin":
        return data
    sanitized = dict(data)
    for field in NOTIFICATION_SENSITIVE_FIELDS:
        sanitized[field] = ""
    return sanitized


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _normalize_email_list(value: str | None) -> str | None:
    if value is None:
        return None
    parts = re.split(r"[,\n;]+", value)
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return ", ".join(cleaned)


def _normalize_phone_list(value: str | None) -> str | None:
    if value is None:
        return None
    parts = re.split(r"[,\n;]+", value)
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        item = item.replace(" ", "")
        if item.startswith("+"):
            normalized = "+" + re.sub(r"\D", "", item)
        else:
            normalized = re.sub(r"\D", "", item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return ", ".join(cleaned)


def _user_role_out(r: UserRole) -> UserRoleAssignmentOut:
    return UserRoleAssignmentOut(
        id=str(r.id),
        user_id=str(r.user_id),
        role=r.role,
        created_at=r.created_at.isoformat() if getattr(r, "created_at", None) else "",
        created_by=str(r.created_by) if getattr(r, "created_by", None) else None,
    )


def _approver_out(a: RequisitionApprover, user: User | None) -> RequisitionApproverOut:
    return RequisitionApproverOut(
        id=str(a.id),
        user_id=str(a.user_id),
        active=a.active,
        added_at=a.added_at.isoformat() if getattr(a, "added_at", None) else "",
        notes=a.notes,
        user=None
        if user is None
        else SimpleUserInfo(
            nom=user.nom,
            prenom=user.prenom,
            email=user.email,
        ),
    )


def _ensure_not_super_admin(target_user: User) -> None:
    if (target_user.role or "").lower() == "super_admin":
        raise HTTPException(status_code=404, detail="User not found")


def _require_super_admin(current_user: User) -> None:
    if (current_user.role or "").lower() != "super_admin":
        raise HTTPException(status_code=403, detail="Accès réservé au super administrateur")


NOTIFICATION_SENSITIVE_FIELDS = {
    "email_expediteur",
    "smtp_password",
    "whatsapp_api_url",
    "whatsapp_api_key",
}


# ----------------------
# Users (admin)
# ----------------------

@router.get("/users", response_model=UserListOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def list_users(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    search: str | None = Query(None),
    include_secretariat: bool = Query(
        False, description="Inclure les agents dont le rôle relève du module secrétariat"
    ),
    tenant_id: int = Depends(get_current_tenant_id),
) -> UserListOut:
    filters = []
    filters.append(User.organisation_id == tenant_id)
    filters.append(User.role != "super_admin")
    # Annuaire commun à toute l'organisation : par défaut, on masque côté module
    # financier les agents purement secrétariat (rôles reception/secretariat),
    # que l'admin financier ne gère pas. `include_secretariat=true` les réaffiche.
    if not include_secretariat:
        filters.append(func.lower(func.coalesce(User.role, "")).notin_(SECRETARIAT_ROLE_CODES))
    if search:
        term = f"%{search.strip()}%"
        if term != "%%":
            filters.append(
                or_(
                    User.email.ilike(term),
                    User.nom.ilike(term),
                    User.prenom.ilike(term),
                    User.role.ilike(term),
                )
            )

    count_stmt = select(func.count()).select_from(User).where(*filters)
    total = (await db.execute(count_stmt)).scalar_one() or 0

    stmt = select(User).options(selectinload(User.services)).order_by(User.created_at.desc())
    stmt = stmt.where(*filters)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    res = await db.execute(stmt)
    items = [_user_out(u) for u in res.scalars().all()]
    return UserListOut(items=items, total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    # Default password policy: set from DEFAULT_USER_PASSWORD and force change.
    default_pwd = _get_default_user_password()
    role = await _resolve_role(db, payload.role)
    service_id = await _resolve_service_id(db, payload.service_id)
    service_ids = await _resolve_service_ids(db, payload.service_ids)
    if not service_ids and service_id is not None:
        service_ids = [service_id]
    if service_id is None and len(service_ids) == 1:
        service_id = service_ids[0]
    settings_res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == current_user.organisation_id).limit(1)
    )
    org_settings = settings_res.scalar_one_or_none()
    if org_settings:
        count_res = await db.execute(
            select(func.count(User.id)).where(
                User.organisation_id == current_user.organisation_id,
                User.active.is_(True),
            )
        )
        active_users = int(count_res.scalar_one() or 0)
        if org_settings.max_users > 0 and active_users >= org_settings.max_users:
            raise HTTPException(status_code=403, detail="Limite d'utilisateurs atteinte")

    u = User(
        email=str(payload.email).lower(),
        nom=payload.nom,
        prenom=payload.prenom,
        role=role.code,
        role_id=role.id,
        service_id=service_id,
        active=True,
        must_change_password=True,
        is_first_login=True,
        is_email_verified=False,
        hashed_password=await hash_password_async(default_pwd),
        organisation_id=current_user.organisation_id,
    )
    db.add(u)
    await log_action(
        db,
        user_id=current_user.id,
        action="USER_CREATED",
        target_table="users",
        target_id=str(u.id),
        new_value={
            "email": u.email,
            "nom": u.nom,
            "prenom": u.prenom,
            "role": u.role,
            "service_id": u.service_id,
            "service_ids": service_ids,
            "active": u.active,
        },
        ip_address=get_request_ip(request),
    )
    try:
        await db.flush()
        if service_ids:
            await db.execute(
                user_services.insert(),
                [{"user_id": u.id, "service_id": sid} for sid in service_ids],
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")

    await invalidate_auth_context_cache(u.id)

    service_ids_out = service_ids if service_ids is not None else [s.id for s in getattr(u, "services", [])]
    if not service_ids_out and getattr(u, "service_id", None) is not None:
        service_ids_out = [u.service_id]

    return UserOut(
        id=str(u.id),
        email=u.email,
        nom=getattr(u, "nom", None),
        prenom=getattr(u, "prenom", None),
        role=u.role,
        role_id=u.role_id,
        service_id=getattr(u, "service_id", None),
        service_ids=service_ids_out,
        active=u.active,
        must_change_password=u.must_change_password,
        is_first_login=u.is_first_login,
        is_email_verified=u.is_email_verified,
        created_at=u.created_at.isoformat() if getattr(u, "created_at", None) else None,
    )


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    try:
        uid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Identifiant utilisateur invalide: {user_id}") from exc

    try:
        res = await db.execute(
            select(User)
            .options(selectinload(User.services))
            .where(User.id == uid, User.organisation_id == current_user.organisation_id)
        )
        u = res.scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        _ensure_not_super_admin(u)

        old_values = {
            "email": u.email,
            "nom": u.nom,
            "prenom": u.prenom,
            "role": u.role,
            "role_id": u.role_id,
            "service_id": getattr(u, "service_id", None),
            "service_ids": [s.id for s in getattr(u, "services", [])],
        }

        if payload.email is not None:
            u.email = str(payload.email).lower()
        if payload.nom is not None:
            u.nom = payload.nom
        if payload.prenom is not None:
            u.prenom = payload.prenom
        if payload.role is not None:
            resolved_role = await _resolve_role(db, payload.role)
            u.role = resolved_role.code
            u.role_id = resolved_role.id

        resolved_service_ids: list[int] | None = None
        if "service_ids" in payload.__fields_set__:
            resolved_service_ids = await _resolve_service_ids(db, payload.service_ids)
        elif "service_id" in payload.__fields_set__:
            sid = await _resolve_service_id(db, payload.service_id)
            resolved_service_ids = [sid] if sid is not None else []

        if resolved_service_ids is not None:
            await db.execute(delete(user_services).where(user_services.c.user_id == u.id))
            if resolved_service_ids:
                await db.execute(
                    user_services.insert(),
                    [{"user_id": u.id, "service_id": sid} for sid in resolved_service_ids],
                )
            u.service_id = resolved_service_ids[0] if len(resolved_service_ids) == 1 else None

        await log_action(
            db,
            user_id=current_user.id,
            action="USER_UPDATED",
            target_table="users",
            target_id=str(u.id),
            old_value=old_values,
            new_value={
                "email": u.email,
                "nom": u.nom,
                "prenom": u.prenom,
                "role": u.role,
                "role_id": u.role_id,
                "service_id": u.service_id,
                "service_ids": resolved_service_ids if resolved_service_ids is not None else old_values.get("service_ids", []),
            },
            ip_address=get_request_ip(request),
        )

        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "USER_UPDATE_FAILED target_user_id=%s actor_user_id=%s payload=%s",
            user_id,
            current_user.id,
            payload.model_dump(exclude_none=False),
        )
        raise HTTPException(
            status_code=500,
            detail="Erreur interne lors de la mise à jour de l'utilisateur.",
        ) from exc

    await invalidate_auth_context_cache(u.id)

    return _user_out(u)


@router.post("/users/toggle-status", dependencies=[Depends(has_permission("can_manage_users"))])
async def toggle_user_status(
    payload: ToggleStatusRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = payload.user_id
    new_status = not payload.current_status

    res = await db.execute(
        select(User)
        .options(selectinload(User.services))
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
    )
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_not_super_admin(target_user)

    await db.execute(
        update(User)
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
        .values(active=new_status)
    )
    await log_action(
        db,
        user_id=current_user.id,
        action="USER_STATUS_TOGGLED",
        target_table="users",
        target_id=str(uid),
        old_value={"active": target_user.active},
        new_value={"active": new_status},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_auth_context_cache(uid)
    return {"ok": True, "active": new_status}


@router.post("/users/reset-password", dependencies=[Depends(has_permission("can_manage_users"))])
async def reset_user_password(
    payload: ResetPasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = payload.user_id

    res = await db.execute(
        select(User)
        .options(selectinload(User.services))
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
    )
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_not_super_admin(user)

    old_must_change = user.must_change_password
    code = f"{secrets.randbelow(1000000):06d}"
    user.hashed_password = await hash_password_async(_get_default_user_password())
    user.must_change_password = True
    user.is_first_login = True
    user.is_email_verified = False
    user.otp_code = code
    user.otp_created_at = datetime.now(timezone.utc)
    user.otp_attempts = 0
    await log_action(
        db,
        user_id=current_user.id,
        action="USER_PASSWORD_RESET",
        target_table="users",
        target_id=str(user.id),
        old_value={"must_change_password": old_must_change},
        new_value={"must_change_password": True},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_auth_context_cache(user.id)

    try:
        settings_res = await db.execute(
            select(SystemSettings)
            .where(SystemSettings.organisation_id == current_user.organisation_id)
            .limit(1)
        )
        ns = settings_res.scalar_one_or_none()
        smtp_cfg = resolve_smtp_config(ns)
        if smtp_cfg:
            display_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email
            org_res = await db.execute(
                select(Organisation.nom).where(Organisation.id == user.organisation_id).limit(1)
            )
            org_name = org_res.scalar_one_or_none()
            await send_in_thread(
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
    except Exception:
        logger.exception("Failed to send reset OTP for user %s", user.email)
    return {"ok": True}


@router.post("/users/set-password", dependencies=[Depends(has_permission("can_manage_users"))])
async def set_user_password(
    payload: SetUserPasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    uid = payload.user_id

    res = await db.execute(
        select(User)
        .options(selectinload(User.services))
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
    )
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_not_super_admin(target_user)

    await db.execute(
        update(User)
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
        .values(
            hashed_password=await hash_password_async(payload.password),
            must_change_password=payload.force_change,
            is_first_login=payload.force_change,
            is_email_verified=not payload.force_change,
            otp_code=None,
            otp_created_at=None,
            otp_attempts=0,
        )
    )
    await log_action(
        db,
        user_id=current_user.id,
        action="USER_PASSWORD_SET",
        target_table="users",
        target_id=str(uid),
        old_value={"must_change_password": target_user.must_change_password},
        new_value={"must_change_password": payload.force_change},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_auth_context_cache(uid)
    return {"ok": True}


@router.post("/users/delete", dependencies=[Depends(has_permission("can_manage_users"))])
async def delete_user(
    payload: DeleteUserRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = payload.user_id

    res = await db.execute(
        select(User)
        .options(selectinload(User.services))
        .where(User.id == uid, User.organisation_id == current_user.organisation_id)
    )
    target_user = res.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_not_super_admin(target_user)

    # Clean dependent rows first
    await db.execute(delete(UserMenuPermission).where(UserMenuPermission.user_id == uid))
    await db.execute(delete(UserRole).where(UserRole.user_id == uid))
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
    await log_action(
        db,
        user_id=current_user.id,
        action="USER_DELETED",
        target_table="users",
        target_id=str(uid),
        old_value={
            "email": target_user.email,
            "nom": target_user.nom,
            "prenom": target_user.prenom,
            "role": target_user.role,
        },
        ip_address=get_request_ip(request),
    )
    await db.execute(delete(User).where(User.id == uid, User.organisation_id == current_user.organisation_id))
    await db.commit()
    await invalidate_auth_context_cache(uid)
    return {"ok": True}


# ----------------------
# Rubriques
# ----------------------

@router.get("/rubriques", response_model=list[RubriqueOut], dependencies=[Depends(require_roles(["admin"]))])
async def list_rubriques(db: AsyncSession = Depends(get_db)) -> list[RubriqueOut]:
    res = await db.execute(select(Rubrique).order_by(Rubrique.libelle.asc()))
    return [_rubrique_out(r) for r in res.scalars().all()]


@router.post("/rubriques", response_model=RubriqueOut, dependencies=[Depends(require_roles(["admin"]))])
async def create_rubrique(payload: RubriqueCreateRequest, db: AsyncSession = Depends(get_db)) -> RubriqueOut:
    r = Rubrique(
        code=payload.code,
        libelle=payload.libelle,
        description=payload.description,
        active=payload.active,
    )
    db.add(r)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Rubrique code already exists")

    return _rubrique_out(r)


@router.patch("/rubriques/{rubrique_id}", response_model=RubriqueOut, dependencies=[Depends(require_roles(["admin"]))])
async def update_rubrique(rubrique_id: str, payload: RubriqueUpdateRequest, db: AsyncSession = Depends(get_db)) -> RubriqueOut:
    rid = uuid.UUID(rubrique_id)
    res = await db.execute(select(Rubrique).where(Rubrique.id == rid))
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Rubrique not found")

    if payload.code is not None:
        r.code = payload.code
    if payload.libelle is not None:
        r.libelle = payload.libelle
    if payload.description is not None:
        r.description = payload.description
    if payload.active is not None:
        r.active = payload.active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Rubrique code already exists")

    return _rubrique_out(r)


# ----------------------
# Print settings
# ----------------------

@router.get(
    "/print-settings",
    response_model=PrintSettingsResponse,
    dependencies=[Depends(require_roles(["admin"]))],
)
async def get_print_settings(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PrintSettingsResponse:
    res = await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1))
    ps = res.scalar_one_or_none()

    # Ensure one row exists so the frontend always has editable defaults.
    if ps is None:
        ps = PrintSettings(organisation_id=tenant_id, updated_at=_utcnow())
        db.add(ps)
        await db.commit()
        await db.refresh(ps)

    return PrintSettingsResponse(data=_print_settings_out(ps))


@router.put("/print-settings", dependencies=[Depends(require_roles(["admin"]))])
async def upsert_print_settings(
    payload: PrintSettingsUpdateRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1))
    ps = res.scalar_one_or_none()

    if ps is None:
        ps = PrintSettings(organisation_id=tenant_id, updated_at=_utcnow())
        db.add(ps)

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if hasattr(ps, k):
            setattr(ps, k, v)

    ps.updated_at = _utcnow()
    await db.commit()
    return {"ok": True}


# ----------------------
# Roles & permissions (RBAC)
# ----------------------


@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(has_permission("can_manage_users"))])
async def list_roles(db: AsyncSession = Depends(get_db)) -> list[RoleOut]:
    res = await db.execute(select(Role).order_by(Role.code.asc()))
    roles = res.scalars().all()
    all_perm_res = await db.execute(
        select(role_permissions.c.role_id, Permission.code)
        .join(Permission, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id.in_([role.id for role in roles]))
        .order_by(Permission.code.asc())
    )
    perm_codes_by_role: dict[int, list[str]] = {}
    for role_id, code in all_perm_res.all():
        perm_codes_by_role.setdefault(role_id, []).append(code)
    out: list[RoleOut] = []
    for role in roles:
        out.append(
            RoleOut(
                id=role.id,
                code=role.code,
                label=role.label,
                description=role.description,
                permissions=perm_codes_by_role.get(role.id, []),
            )
        )
    return out


@router.get("/permissions", response_model=list[PermissionOut], dependencies=[Depends(has_permission("can_manage_users"))])
async def list_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PermissionOut]:
    _require_super_admin(current_user)
    res = await db.execute(select(Permission).order_by(Permission.code.asc()))
    perms = res.scalars().all()
    return [PermissionOut(id=p.id, code=p.code, description=p.description) for p in perms]


@router.put("/role-permissions", dependencies=[Depends(has_permission("can_manage_users"))])
async def update_role_permissions(
    payload: RolePermissionsPayload,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_super_admin(current_user)
    for role_update in payload.roles:
        old_perm_res = await db.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_update.role_id)
            .order_by(Permission.code.asc())
        )
        old_perm_codes = [row[0] for row in old_perm_res.all()]

        # remove existing
        await db.execute(
            role_permissions.delete().where(role_permissions.c.role_id == role_update.role_id)
        )
        if role_update.permission_codes:
            perm_res = await db.execute(
                select(Permission).where(Permission.code.in_(role_update.permission_codes))
            )
            perms = perm_res.scalars().all()
            if perms:
                await db.execute(
                    role_permissions.insert(),
                    [{"role_id": role_update.role_id, "permission_id": perm.id} for perm in perms],
                )

        await log_action(
            db,
            user_id=current_user.id,
            action="ROLE_PERMISSIONS_UPDATED",
            target_table="roles",
            target_id=str(role_update.role_id),
            old_value={"permissions": old_perm_codes},
            new_value={"permissions": role_update.permission_codes or []},
            ip_address=get_request_ip(request),
        )
    await db.commit()
    # Une modification de rôle impacte tous ses porteurs : on ne peut pas cibler
    # les utilisateurs concernés sans requête supplémentaire, on purge donc tout
    # le namespace (opération d'administration, rare).
    await invalidate_auth_context_cache()
    return {"ok": True}


@router.post("/roles", response_model=RoleOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def create_role(
    payload: RoleCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoleOut:
    _require_super_admin(current_user)
    code = payload.code.strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Role code required")
    res = await db.execute(select(Role).where(Role.code == code))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Role already exists")
    role = Role(code=code, label=payload.label, description=payload.description)
    db.add(role)
    await db.flush()
    await log_action(
        db,
        user_id=current_user.id,
        action="ROLE_CREATED",
        target_table="roles",
        target_id=str(role.id),
        new_value={"code": role.code, "label": role.label, "description": role.description},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(role)
    return RoleOut(id=role.id, code=role.code, label=role.label, description=role.description, permissions=[])


@router.patch("/roles/{role_id}", response_model=RoleOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoleOut:
    _require_super_admin(current_user)
    res = await db.execute(select(Role).where(Role.id == role_id))
    role = res.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    old_values = {"label": role.label, "description": role.description}

    if payload.label is not None:
        role.label = payload.label
    if payload.description is not None:
        role.description = payload.description
    await log_action(
        db,
        user_id=current_user.id,
        action="ROLE_UPDATED",
        target_table="roles",
        target_id=str(role.id),
        old_value=old_values,
        new_value={"label": role.label, "description": role.description},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(role)
    perm_res = await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == role.id)
    )
    perm_codes = [row[0] for row in perm_res.all()]
    return RoleOut(
        id=role.id,
        code=role.code,
        label=role.label,
        description=role.description,
        permissions=perm_codes,
    )


@router.delete("/roles/{role_id}", dependencies=[Depends(has_permission("can_manage_users"))])
async def delete_role(
    role_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_super_admin(current_user)
    res = await db.execute(select(Role).where(Role.id == role_id))
    role = res.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.code == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete admin role")
    user_res = await db.execute(select(User.id).where(User.role_id == role_id).limit(1))
    if user_res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role is assigned to users")
    await db.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
    await log_action(
        db,
        user_id=current_user.id,
        action="ROLE_DELETED",
        target_table="roles",
        target_id=str(role.id),
        old_value={"code": role.code, "label": role.label, "description": role.description},
        ip_address=get_request_ip(request),
    )
    await db.execute(delete(Role).where(Role.id == role_id))
    await db.commit()
    return {"ok": True}


# ----------------------
# Notification settings
# ----------------------

@router.get(
    "/notification-settings",
    response_model=NotificationSettingsResponse,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def get_notification_settings(
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsResponse:
    ns = await _get_system_settings(db, tenant_id)

    if ns is None:
        ns = SystemSettings(organisation_id=tenant_id, updated_at=_utcnow())
        db.add(ns)
        await db.commit()
        await db.refresh(ns)

    return NotificationSettingsResponse(data=_sanitize_notification_settings(_notification_settings_out(ns), current_user))


@router.put("/notification-settings", dependencies=[Depends(has_permission("can_edit_settings"))])
async def upsert_notification_settings(
    payload: NotificationSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ns = await _get_system_settings(db, tenant_id)

    if ns is None:
        ns = SystemSettings(organisation_id=tenant_id, updated_at=_utcnow())
        db.add(ns)

    data = payload.model_dump(exclude_unset=True)
    if (current_user.role or "").lower() != "super_admin":
        data = {k: v for k, v in data.items() if k not in NOTIFICATION_SENSITIVE_FIELDS}
    if "email_expediteur" in data:
        data["email_expediteur"] = _normalize_email(data.get("email_expediteur"))
    if "email_president" in data:
        data["email_president"] = _normalize_email(data.get("email_president"))
    if "email_tresorier" in data:
        data["email_tresorier"] = _normalize_email(data.get("email_tresorier"))
    if "email_validation_1" in data:
        data["email_validation_1"] = _normalize_email(data.get("email_validation_1"))
    if "email_validation_final" in data:
        data["email_validation_final"] = _normalize_email(data.get("email_validation_final"))
    if "emails_bureau_cc" in data:
        data["emails_bureau_cc"] = _normalize_email_list(data.get("emails_bureau_cc"))
    if "emails_bureau_sortie_cc" in data:
        data["emails_bureau_sortie_cc"] = _normalize_email_list(data.get("emails_bureau_sortie_cc"))
    if "whatsapp_api_url" in data:
        data["whatsapp_api_url"] = (data.get("whatsapp_api_url") or "").strip()
    if "whatsapp_api_key" in data:
        data["whatsapp_api_key"] = (data.get("whatsapp_api_key") or "").strip()
    if "whatsapp_agents" in data:
        data["whatsapp_agents"] = _normalize_phone_list(data.get("whatsapp_agents"))
    # Postes de régularisation d'écart de caisse : ils doivent appartenir au
    # tenant et porter le bon sens (recette pour un excédent, dépense pour un
    # déficit), sinon la régularisation imputerait un poste étranger.
    for field, type_attendu, libelle in (
        ("budget_poste_excedent_caisse_id", "RECETTE", "excédent"),
        ("budget_poste_deficit_caisse_id", "DEPENSE", "déficit"),
    ):
        if field not in data or data[field] is None:
            continue
        poste = (
            await db.execute(
                select(BudgetPoste).where(
                    BudgetPoste.id == data[field],
                    BudgetPoste.organisation_id == tenant_id,
                    BudgetPoste.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if poste is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Poste budgétaire d'{libelle} de caisse introuvable.",
            )
        if (poste.type or "").upper() != type_attendu:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Le poste d'{libelle} de caisse doit être de type {type_attendu} "
                    f"(reçu : {poste.type})."
                ),
            )
    for k, v in data.items():
        if hasattr(ns, k):
            setattr(ns, k, v)

    ns.updated_at = _utcnow()
    await db.commit()
    await consolidate_system_settings(db, tenant_id)
    return {"ok": True}


@router.post("/test-email-connection", dependencies=[Depends(has_permission("can_edit_settings"))])
async def test_email_connection(
    payload: NotificationSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_super_admin(current_user)
    if not payload.email_expediteur or not payload.smtp_password:
        raise HTTPException(status_code=400, detail="Email expéditeur et mot de passe SMTP requis.")

    smtp_host = payload.smtp_host or "smtp.gmail.com"
    smtp_port = int(payload.smtp_port or 465)

    msg = EmailMessage()
    msg["Subject"] = "Test de connexion ONE-CPK"
    msg["From"] = payload.email_expediteur
    msg["To"] = payload.email_expediteur
    msg.set_content("Si vous lisez ce message, la configuration SMTP est correcte !")

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=payload.email_expediteur,
            smtp_password=payload.smtp_password,
            msg=msg,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "message": "Connexion réussie ! Vérifiez votre boîte mail."}


@router.post("/run-weekly-report", dependencies=[Depends(has_permission("can_edit_settings"))])
async def run_weekly_report(
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await send_weekly_report(db, tenant_id=tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "message": "Rapport hebdomadaire envoyé."}


@router.get("/weekly-report-status", dependencies=[Depends(has_permission("can_edit_settings"))])
async def weekly_report_status(
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    status = get_weekly_report_status()
    ns = await _get_system_settings(db, tenant_id)
    status["last_sent_at"] = ns.last_weekly_report_sent_at.isoformat() if ns and ns.last_weekly_report_sent_at else None
    status["last_status"] = ns.last_weekly_report_status if ns else "never"
    status["last_error"] = ns.last_weekly_report_error if ns else ""
    status["last_success_at"] = ns.last_weekly_report_success_at.isoformat() if ns and ns.last_weekly_report_success_at else None
    status["last_failure_at"] = ns.last_weekly_report_failure_at.isoformat() if ns and ns.last_weekly_report_failure_at else None
    return status


# ----------------------
# System roles (user_roles)
# ----------------------

@router.get(
    "/user-roles",
    response_model=list[UserRoleAssignmentOut],
    dependencies=[Depends(require_roles(["admin"]))],
)
async def list_user_roles(db: AsyncSession = Depends(get_db)) -> list[UserRoleAssignmentOut]:
    res = await db.execute(select(UserRole).order_by(UserRole.created_at.desc()))
    return [_user_role_out(r) for r in res.scalars().all()]


@router.post("/user-roles", response_model=UserRoleAssignmentOut)
async def assign_user_role(
    payload: UserRoleAssignmentCreateRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> UserRoleAssignmentOut:
    r = UserRole(
        user_id=payload.user_id,
        role=payload.role,
        created_by=admin_user.id,
    )
    db.add(r)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Role already assigned")
    return _user_role_out(r)


@router.delete("/user-roles/{role_assignment_id}")
async def remove_user_role(
    role_assignment_id: str,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rid = uuid.UUID(role_assignment_id)
    await db.execute(delete(UserRole).where(UserRole.id == rid))
    await db.commit()
    return {"ok": True}


# ----------------------
# Requisition approvers
# ----------------------

@router.get(
    "/requisition-approvers",
    response_model=list[RequisitionApproverOut],
    dependencies=[Depends(require_roles(["admin"]))],
)
async def list_requisition_approvers(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RequisitionApproverOut]:
    res = await db.execute(
        select(RequisitionApprover, User)
        .join(User, User.id == RequisitionApprover.user_id)
        .where(RequisitionApprover.organisation_id == tenant_id)
        .order_by(RequisitionApprover.added_at.desc())
    )
    return [_approver_out(a, u) for (a, u) in res.all()]


@router.post("/requisition-approvers", response_model=RequisitionApproverOut)
async def create_requisition_approver(
    payload: RequisitionApproverCreateRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RequisitionApproverOut:
    uid = payload.user_id
    user_res = await db.execute(select(User).where(User.id == uid, User.organisation_id == tenant_id))
    target_user = user_res.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    a = RequisitionApprover(
        organisation_id=tenant_id,
        user_id=uid,
        active=payload.active,
        notes=payload.notes,
        added_by=admin_user.id,
    )
    db.add(a)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Approver already exists")

    return _approver_out(a, target_user)


@router.patch("/requisition-approvers/{approver_id}", response_model=RequisitionApproverOut)
async def update_requisition_approver(
    approver_id: str,
    payload: RequisitionApproverUpdateRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RequisitionApproverOut:
    aid = uuid.UUID(approver_id)
    res = await db.execute(
        select(RequisitionApprover).where(
            RequisitionApprover.id == aid,
            RequisitionApprover.organisation_id == tenant_id,
        )
    )
    a = res.scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Approver not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if hasattr(a, k):
            setattr(a, k, v)

    await db.commit()

    res = await db.execute(
        select(User).where(User.id == a.user_id, User.organisation_id == tenant_id)
    )
    u = res.scalar_one_or_none()
    return _approver_out(a, u)


@router.delete("/requisition-approvers/{approver_id}")
async def delete_requisition_approver(
    approver_id: str,
    admin_user: User = Depends(require_roles(["admin"])),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    aid = uuid.UUID(approver_id)
    await db.execute(
        delete(RequisitionApprover).where(
            RequisitionApprover.id == aid,
            RequisitionApprover.organisation_id == tenant_id,
        )
    )
    await db.commit()
    return {"ok": True}
