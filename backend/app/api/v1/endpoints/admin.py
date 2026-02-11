from __future__ import annotations

import uuid
import secrets
from datetime import datetime, timezone

import smtplib
import logging
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles, has_permission
from app.core.security import hash_password
from app.db.session import get_db
from app.models.print_settings import PrintSettings
from app.models.refresh_token import RefreshToken
from app.models.requisition_approver import RequisitionApprover
from app.models.rubrique import Rubrique
from app.models.system_settings import SystemSettings
from app.models.rbac import Role, Permission, role_permissions
from app.models.user import User
from app.models.user_role import UserRole
from app.services.mailer import send_security_code
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


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        nom=getattr(u, "nom", None),
        prenom=getattr(u, "prenom", None),
        role=u.role,
        role_id=u.role_id,
        active=u.active,
        must_change_password=u.must_change_password,
        is_first_login=u.is_first_login,
        is_email_verified=u.is_email_verified,
        created_at=u.created_at.isoformat() if getattr(u, "created_at", None) else None,
    )


async def _resolve_role_id(db: AsyncSession, role_value: str | None) -> int | None:
    if not role_value:
        return None
    normalized = role_value.strip().lower()
    mapping = {
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
    code = mapping.get(normalized, normalized)
    res = await db.execute(select(Role).where(Role.code == code))
    role = res.scalar_one_or_none()
    return role.id if role else None


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
        default_currency=ps.default_currency,
        secondary_currency=ps.secondary_currency,
        exchange_rate=float(ps.exchange_rate or 0),
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
        "smtp_password": ns.smtp_password,
        "smtp_host": ns.smtp_host,
        "smtp_port": ns.smtp_port,
        "updated_by": str(ns.updated_by) if ns.updated_by else None,
        "updated_at": ns.updated_at.isoformat() if ns.updated_at else None,
    }


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


# ----------------------
# Users (admin)
# ----------------------

@router.get("/users", response_model=list[UserOut], dependencies=[Depends(has_permission("can_manage_users"))])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    res = await db.execute(select(User).order_by(User.created_at.desc()))
    return [_user_out(u) for u in res.scalars().all()]


@router.post("/users", response_model=UserOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def create_user(payload: UserCreateRequest, db: AsyncSession = Depends(get_db)) -> UserOut:
    # Default password policy: set to ONECCPK and force change.
    role_id = await _resolve_role_id(db, payload.role)
    u = User(
        email=str(payload.email).lower(),
        nom=payload.nom,
        prenom=payload.prenom,
        role=payload.role,
        role_id=role_id,
        active=True,
        must_change_password=True,
        is_first_login=True,
        is_email_verified=False,
        hashed_password=hash_password("ONECCPK"),
    )
    db.add(u)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")

    return _user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def update_user(user_id: str, payload: UserUpdateRequest, db: AsyncSession = Depends(get_db)) -> UserOut:
    uid = uuid.UUID(user_id)
    res = await db.execute(select(User).where(User.id == uid))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.email is not None:
        u.email = str(payload.email).lower()
    if payload.nom is not None:
        u.nom = payload.nom
    if payload.prenom is not None:
        u.prenom = payload.prenom
    if payload.role is not None:
        u.role = payload.role
        u.role_id = await _resolve_role_id(db, payload.role)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")

    return _user_out(u)


@router.post("/users/toggle-status", dependencies=[Depends(has_permission("can_manage_users"))])
async def toggle_user_status(payload: ToggleStatusRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)
    new_status = not payload.current_status

    await db.execute(update(User).where(User.id == uid).values(active=new_status))
    await db.commit()
    return {"ok": True, "active": new_status}


@router.post("/users/reset-password", dependencies=[Depends(has_permission("can_manage_users"))])
async def reset_user_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    res = await db.execute(select(User).where(User.id == uid))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    code = f"{secrets.randbelow(1000000):06d}"
    user.hashed_password = hash_password("ONECCPK")
    user.must_change_password = True
    user.is_first_login = True
    user.is_email_verified = False
    user.otp_code = code
    user.otp_created_at = datetime.now(timezone.utc)
    user.otp_attempts = 0
    await db.commit()

    try:
        settings_res = await db.execute(select(SystemSettings).limit(1))
        ns = settings_res.scalar_one_or_none()
        if ns and ns.email_expediteur and ns.smtp_password:
            display_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email
            send_security_code(
                smtp_host=ns.smtp_host or "smtp.gmail.com",
                smtp_port=int(ns.smtp_port or 465),
                smtp_user=ns.email_expediteur,
                smtp_password=ns.smtp_password,
                sender=ns.email_expediteur,
                recipient=user.email,
                recipient_name=display_name,
                code=code,
            )
    except Exception:
        logger.exception("Failed to send reset OTP for user %s", user.email)
    return {"ok": True}


@router.post("/users/set-password", dependencies=[Depends(has_permission("can_manage_users"))])
async def set_user_password(payload: SetUserPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    await db.execute(
        update(User)
        .where(User.id == uid)
        .values(
            hashed_password=hash_password(payload.password),
            must_change_password=payload.force_change,
            is_first_login=payload.force_change,
            is_email_verified=not payload.force_change,
            otp_code=None,
            otp_created_at=None,
            otp_attempts=0,
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/users/delete", dependencies=[Depends(has_permission("can_manage_users"))])
async def delete_user(payload: DeleteUserRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    # Clean dependent rows first
    await db.execute(delete(UserMenuPermission).where(UserMenuPermission.user_id == uid))
    await db.execute(delete(UserRole).where(UserRole.user_id == uid))
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()
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
async def get_print_settings(db: AsyncSession = Depends(get_db)) -> PrintSettingsResponse:
    res = await db.execute(select(PrintSettings).limit(1))
    ps = res.scalar_one_or_none()

    # Ensure one row exists so the frontend always has editable defaults.
    if ps is None:
        ps = PrintSettings(updated_at=_utcnow())
        db.add(ps)
        await db.commit()
        await db.refresh(ps)

    return PrintSettingsResponse(data=_print_settings_out(ps))


@router.put("/print-settings", dependencies=[Depends(require_roles(["admin"]))])
async def upsert_print_settings(payload: PrintSettingsUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(select(PrintSettings).limit(1))
    ps = res.scalar_one_or_none()

    if ps is None:
        ps = PrintSettings(updated_at=_utcnow())
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
    out: list[RoleOut] = []
    for role in roles:
        perm_res = await db.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role.id)
            .order_by(Permission.code.asc())
        )
        perm_codes = [row[0] for row in perm_res.all()]
        out.append(
            RoleOut(
                id=role.id,
                code=role.code,
                label=role.label,
                description=role.description,
                permissions=perm_codes,
            )
        )
    return out


@router.get("/permissions", response_model=list[PermissionOut], dependencies=[Depends(has_permission("can_manage_users"))])
async def list_permissions(db: AsyncSession = Depends(get_db)) -> list[PermissionOut]:
    res = await db.execute(select(Permission).order_by(Permission.code.asc()))
    perms = res.scalars().all()
    return [PermissionOut(id=p.id, code=p.code, description=p.description) for p in perms]


@router.put("/role-permissions", dependencies=[Depends(has_permission("can_manage_users"))])
async def update_role_permissions(payload: RolePermissionsPayload, db: AsyncSession = Depends(get_db)) -> dict:
    for role_update in payload.roles:
        # remove existing
        await db.execute(
            role_permissions.delete().where(role_permissions.c.role_id == role_update.role_id)
        )
        if role_update.permission_codes:
            perm_res = await db.execute(
                select(Permission).where(Permission.code.in_(role_update.permission_codes))
            )
            perms = perm_res.scalars().all()
            for perm in perms:
                await db.execute(
                    role_permissions.insert().values(role_id=role_update.role_id, permission_id=perm.id)
                )
    await db.commit()
    return {"ok": True}


@router.post("/roles", response_model=RoleOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def create_role(payload: RoleCreate, db: AsyncSession = Depends(get_db)) -> RoleOut:
    code = payload.code.strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Role code required")
    res = await db.execute(select(Role).where(Role.code == code))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Role already exists")
    role = Role(code=code, label=payload.label, description=payload.description)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return RoleOut(id=role.id, code=role.code, label=role.label, description=role.description, permissions=[])


@router.patch("/roles/{role_id}", response_model=RoleOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def update_role(role_id: int, payload: RoleUpdate, db: AsyncSession = Depends(get_db)) -> RoleOut:
    res = await db.execute(select(Role).where(Role.id == role_id))
    role = res.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if payload.label is not None:
        role.label = payload.label
    if payload.description is not None:
        role.description = payload.description
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
async def delete_role(role_id: int, db: AsyncSession = Depends(get_db)) -> dict:
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
async def get_notification_settings(db: AsyncSession = Depends(get_db)) -> NotificationSettingsResponse:
    res = await db.execute(select(SystemSettings).limit(1))
    ns = res.scalar_one_or_none()

    if ns is None:
        ns = SystemSettings(updated_at=_utcnow())
        db.add(ns)
        await db.commit()
        await db.refresh(ns)

    return NotificationSettingsResponse(data=_notification_settings_out(ns))


@router.put("/notification-settings", dependencies=[Depends(has_permission("can_edit_settings"))])
async def upsert_notification_settings(payload: NotificationSettingsUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(select(SystemSettings).limit(1))
    ns = res.scalar_one_or_none()

    if ns is None:
        ns = SystemSettings(updated_at=_utcnow())
        db.add(ns)

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if hasattr(ns, k):
            setattr(ns, k, v)

    ns.updated_at = _utcnow()
    await db.commit()
    return {"ok": True}


@router.post("/test-email-connection", dependencies=[Depends(has_permission("can_edit_settings"))])
async def test_email_connection(payload: NotificationSettingsUpdateRequest) -> dict:
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
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(payload.email_expediteur, payload.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "message": "Connexion réussie ! Vérifiez votre boîte mail."}


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
        user_id=uuid.UUID(payload.user_id),
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
async def list_requisition_approvers(db: AsyncSession = Depends(get_db)) -> list[RequisitionApproverOut]:
    res = await db.execute(
        select(RequisitionApprover, User)
        .join(User, User.id == RequisitionApprover.user_id)
        .order_by(RequisitionApprover.added_at.desc())
    )
    return [_approver_out(a, u) for (a, u) in res.all()]


@router.post("/requisition-approvers", response_model=RequisitionApproverOut)
async def create_requisition_approver(
    payload: RequisitionApproverCreateRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> RequisitionApproverOut:
    uid = uuid.UUID(payload.user_id)
    a = RequisitionApprover(
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

    res = await db.execute(select(User).where(User.id == uid))
    u = res.scalar_one_or_none()
    return _approver_out(a, u)


@router.patch("/requisition-approvers/{approver_id}", response_model=RequisitionApproverOut)
async def update_requisition_approver(
    approver_id: str,
    payload: RequisitionApproverUpdateRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> RequisitionApproverOut:
    aid = uuid.UUID(approver_id)
    res = await db.execute(select(RequisitionApprover).where(RequisitionApprover.id == aid))
    a = res.scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Approver not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if hasattr(a, k):
            setattr(a, k, v)

    await db.commit()

    res = await db.execute(select(User).where(User.id == a.user_id))
    u = res.scalar_one_or_none()
    return _approver_out(a, u)


@router.delete("/requisition-approvers/{approver_id}")
async def delete_requisition_approver(
    approver_id: str,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    aid = uuid.UUID(approver_id)
    await db.execute(delete(RequisitionApprover).where(RequisitionApprover.id == aid))
    await db.commit()
    return {"ok": True}
