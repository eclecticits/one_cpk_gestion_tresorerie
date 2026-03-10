from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models.caisse_centrale import CaisseCentrale
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.models.rbac import Role
from app.schemas.super_admin import (
    SuperAdminOrganisationCreate,
    SuperAdminOrganisationOut,
    SuperAdminOrganisationUpdate,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_slug(raw: str) -> str:
    slug = (raw or "").strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _org_out(org: Organisation, user_count: int) -> SuperAdminOrganisationOut:
    return SuperAdminOrganisationOut(
        id=org.id,
        uuid=str(org.uuid),
        nom=org.nom,
        slug=org.slug,
        plan_type=org.plan_type,
        status_abonnement=org.status_abonnement,
        date_expiration_abonnement=org.date_expiration_abonnement,
        limite_utilisateurs=org.limite_utilisateurs,
        is_active=org.is_active,
        user_count=int(user_count or 0),
        created_at=org.created_at,
    )


@router.get("/organisations", response_model=list[SuperAdminOrganisationOut], dependencies=[Depends(require_super_admin)])
async def list_organisations(db: AsyncSession = Depends(get_db)) -> list[SuperAdminOrganisationOut]:
    res = await db.execute(
        select(Organisation, func.count(User.id).label("user_count"))
        .outerjoin(User, User.organisation_id == Organisation.id)
        .group_by(Organisation.id)
        .order_by(Organisation.created_at.desc())
    )
    return [_org_out(row[0], row[1]) for row in res.all()]


@router.post(
    "/organisations",
    response_model=SuperAdminOrganisationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_super_admin)],
)
async def create_organisation(
    payload: SuperAdminOrganisationCreate,
    db: AsyncSession = Depends(get_db),
) -> SuperAdminOrganisationOut:
    slug = _clean_slug(payload.slug)
    if not slug:
        raise HTTPException(status_code=400, detail="Slug invalide")

    existing = await db.execute(select(Organisation).where(Organisation.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")

    email = str(payload.admin_email).lower().strip()
    user_res = await db.execute(select(User).where(User.email == email))
    if user_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email admin déjà utilisé")

    now = _utcnow()
    trial_days = payload.trial_days if payload.trial_days is not None else 30
    expires_at = now + timedelta(days=trial_days) if trial_days and trial_days > 0 else None

    org = Organisation(
        nom=payload.nom.strip(),
        slug=slug,
        plan_type=(payload.plan_type or "FREE").strip().upper(),
        status_abonnement=(payload.status_abonnement or "TRIAL").strip().upper(),
        date_expiration_abonnement=expires_at,
        limite_utilisateurs=payload.limite_utilisateurs or 2,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    await db.flush()

    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=0, solde_cdf=0)
    settings = SystemSettings(organisation_id=org.id, updated_at=now)
    print_settings = PrintSettings(organisation_id=org.id, organization_name=org.nom, updated_at=now)

    role_res = await db.execute(select(Role).where(Role.code == "admin"))
    admin_role = role_res.scalar_one_or_none()

    admin_user = User(
        email=email,
        hashed_password=hash_password(payload.admin_password),
        role="admin",
        role_id=admin_role.id if admin_role else None,
        organisation_id=org.id,
        active=True,
        must_change_password=True,
        is_first_login=True,
        is_email_verified=True,
    )

    db.add_all([caisse, settings, print_settings, admin_user])
    await db.commit()
    await db.refresh(org)

    return _org_out(org, 1)


@router.patch(
    "/organisations/{org_id}",
    response_model=SuperAdminOrganisationOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_organisation(
    org_id: int,
    payload: SuperAdminOrganisationUpdate,
    db: AsyncSession = Depends(get_db),
) -> SuperAdminOrganisationOut:
    res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    data = payload.model_dump(exclude_unset=True)
    if "plan_type" in data and data["plan_type"] is not None:
        org.plan_type = data["plan_type"].strip().upper()
    if "status_abonnement" in data and data["status_abonnement"] is not None:
        org.status_abonnement = data["status_abonnement"].strip().upper()
    if "date_expiration_abonnement" in data:
        org.date_expiration_abonnement = data["date_expiration_abonnement"]
    if "limite_utilisateurs" in data and data["limite_utilisateurs"] is not None:
        org.limite_utilisateurs = int(data["limite_utilisateurs"])
    if "is_active" in data and data["is_active"] is not None:
        org.is_active = bool(data["is_active"])
        await db.execute(
            update(User)
            .where(User.organisation_id == org.id)
            .values(active=org.is_active)
        )

    org.updated_at = _utcnow()
    await db.commit()

    count_res = await db.execute(select(func.count(User.id)).where(User.organisation_id == org.id))
    user_count = count_res.scalar_one() or 0
    return _org_out(org, int(user_count))
