from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.print_settings import PrintSettings
from app.models.requisition_approver import RequisitionApprover
from app.models.rubrique import Rubrique
from app.models.user import User
from app.models.user_menu_permission import UserMenuPermission
from app.models.user_role import UserRole
from app.schemas.admin import (
    DeleteUserRequest,
    MenuPermissionsOut,
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
    SetMenuPermissionsRequest,
    SetUserPasswordRequest,
    SimpleUserInfo,
    ToggleStatusRequest,
    UserCreateRequest,
    UserOut,
    UserRoleAssignmentCreateRequest,
    UserRoleAssignmentOut,
    UserUpdateRequest,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        nom=getattr(u, "nom", None),
        prenom=getattr(u, "prenom", None),
        role=u.role,
        active=u.active,
        must_change_password=u.must_change_password,
        created_at=u.created_at.isoformat() if getattr(u, "created_at", None) else None,
    )


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
        footer_text=ps.footer_text,
        show_header_logo=ps.show_header_logo,
        show_footer_signature=ps.show_footer_signature,
        logo_url=ps.logo_url,
        stamp_url=ps.stamp_url,
        signature_name=ps.signature_name,
        signature_title=ps.signature_title,
        paper_format=ps.paper_format,
        compact_header=ps.compact_header,
    )


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

@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_roles(["admin"]))])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    res = await db.execute(select(User).order_by(User.created_at.desc()))
    return [_user_out(u) for u in res.scalars().all()]


@router.post("/users", response_model=UserOut, dependencies=[Depends(require_roles(["admin"]))])
async def create_user(payload: UserCreateRequest, db: AsyncSession = Depends(get_db)) -> UserOut:
    # Default password policy: set to ONECCPK and force change.
    u = User(
        email=str(payload.email).lower(),
        nom=payload.nom,
        prenom=payload.prenom,
        role=payload.role,
        active=True,
        must_change_password=True,
        hashed_password=hash_password("ONECCPK"),
    )
    db.add(u)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")

    return _user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_roles(["admin"]))])
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

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists")

    return _user_out(u)


@router.post("/users/toggle-status", dependencies=[Depends(require_roles(["admin"]))])
async def toggle_user_status(payload: ToggleStatusRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)
    new_status = not payload.current_status

    await db.execute(update(User).where(User.id == uid).values(active=new_status))
    await db.commit()
    return {"ok": True, "active": new_status}


@router.post("/users/reset-password", dependencies=[Depends(require_roles(["admin"]))])
async def reset_user_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    await db.execute(
        update(User)
        .where(User.id == uid)
        .values(hashed_password=hash_password("ONECCPK"), must_change_password=True)
    )
    await db.commit()
    return {"ok": True}


@router.post("/users/set-password", dependencies=[Depends(require_roles(["admin"]))])
async def set_user_password(payload: SetUserPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    await db.execute(
        update(User)
        .where(User.id == uid)
        .values(hashed_password=hash_password(payload.password), must_change_password=payload.force_change)
    )
    await db.commit()
    return {"ok": True}


@router.post("/users/delete", dependencies=[Depends(require_roles(["admin"]))])
async def delete_user(payload: DeleteUserRequest, db: AsyncSession = Depends(get_db)) -> dict:
    uid = uuid.UUID(payload.user_id)

    # Clean dependent rows first
    await db.execute(delete(UserMenuPermission).where(UserMenuPermission.user_id == uid))
    await db.execute(delete(UserRole).where(UserRole.user_id == uid))
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
# Menu permissions per user
# ----------------------

@router.get(
    "/users/{user_id}/menu-permissions",
    response_model=MenuPermissionsOut,
    dependencies=[Depends(require_roles(["admin"]))],
)
async def get_user_menu_permissions(user_id: str, db: AsyncSession = Depends(get_db)) -> MenuPermissionsOut:
    uid = uuid.UUID(user_id)
    res = await db.execute(
        select(UserMenuPermission.menu_name)
        .where(UserMenuPermission.user_id == uid)
        .where(UserMenuPermission.can_access.is_(True))
    )
    menus = [row[0] for row in res.all()]
    return MenuPermissionsOut(menus=menus)


@router.put("/users/{user_id}/menu-permissions")
async def set_user_menu_permissions(
    user_id: str,
    payload: SetMenuPermissionsRequest,
    admin_user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = uuid.UUID(user_id)

    await db.execute(delete(UserMenuPermission).where(UserMenuPermission.user_id == uid))

    for menu_name in payload.menus:
        db.add(
            UserMenuPermission(
                user_id=uid,
                menu_name=menu_name,
                can_access=True,
                created_by=admin_user.id,
            )
        )

    await db.commit()
    return {"ok": True}


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
