from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin
from app.core.security import hash_password
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.models.rbac import Role
from app.models.system_event import SystemEvent
from app.services.monitoring import (
    detect_anomalies,
    fetch_expiring_soon,
    fetch_platform_summary,
    fetch_tenant_metrics,
    refresh_platform_metrics,
    send_anomaly_alerts,
)
from app.services.monitoring.events import log_system_event
from app.services.monthly_report import generate_national_report
from app.utils.scheduler import get_monthly_report_status
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


@router.get("/organisations/{org_id}/users", dependencies=[Depends(require_super_admin)])
async def list_org_users(org_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(
        select(User)
        .where(User.organisation_id == org_id, User.role != "super_admin")
        .order_by(User.created_at.desc())
    )
    users = []
    for u in res.scalars().all():
        users.append(
            {
                "id": str(u.id),
                "email": u.email,
                "nom": u.nom,
                "prenom": u.prenom,
                "role": u.role,
                "active": u.active,
            }
        )
    return {"users": users}


@router.get("/monitoring/summary", dependencies=[Depends(require_super_admin)])
async def platform_summary(db: AsyncSession = Depends(get_db)) -> dict:
    return await fetch_platform_summary(db)


@router.get("/monitoring/tenants", dependencies=[Depends(require_super_admin)])
async def tenants_metrics(db: AsyncSession = Depends(get_db)) -> dict:
    metrics = await fetch_tenant_metrics(db)
    expiring = await fetch_expiring_soon(db, days=5)
    anomalies = await detect_anomalies(db)
    return {"metrics": metrics, "expiring": expiring, "anomalies": anomalies}


@router.get("/monitoring/events", dependencies=[Depends(require_super_admin)])
async def monitoring_events(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    limit = max(1, min(int(limit), 200))
    res = await db.execute(
        select(SystemEvent)
        .order_by(SystemEvent.created_at.desc())
        .limit(limit)
    )
    events = []
    for ev in res.scalars().all():
        events.append(
            {
                "id": str(ev.id),
                "organisation_id": ev.organisation_id,
                "level": ev.level,
                "code": ev.code,
                "message": ev.message,
                "metadata": ev.event_metadata,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
        )
    return {"events": events}


@router.post("/monitoring/refresh", dependencies=[Depends(require_super_admin)])
async def refresh_metrics(db: AsyncSession = Depends(get_db)) -> dict:
    await refresh_platform_metrics(db)
    sent = await send_anomaly_alerts(db)
    return {"ok": True, "alerts_sent": sent}


@router.get("/reporting/monthly-status", dependencies=[Depends(require_super_admin)])
async def monthly_report_status() -> dict:
    return get_monthly_report_status()


@router.post("/reporting/monthly", dependencies=[Depends(require_super_admin)])
async def run_monthly_report(
    month: int,
    year: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    path = await generate_national_report(db, month=month, year=year)
    await log_system_event(
        db,
        level="info",
        code="MONTHLY_REPORT",
        message="Rapport national mensuel généré",
        organisation_id=None,
        metadata={"month": month, "year": year, "path": path},
    )
    return {"ok": True, "path": path}


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
    cash_usd = CompteBancaire(
        organisation_id=org.id,
        banque_id=None,
        intitule="Caisse USD",
        numero_compte=f"CASH-USD-{org.id}",
        devise="USD",
        solde_initial=0,
        solde_actuel=0,
        is_active=True,
        account_type="CASH",
    )
    cash_cdf = CompteBancaire(
        organisation_id=org.id,
        banque_id=None,
        intitule="Caisse CDF",
        numero_compte=f"CASH-CDF-{org.id}",
        devise="CDF",
        solde_initial=0,
        solde_actuel=0,
        is_active=True,
        account_type="CASH",
    )

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

    db.add_all([caisse, settings, print_settings, cash_usd, cash_cdf, admin_user])
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


@router.post("/impersonate/{user_id}", dependencies=[Depends(require_super_admin)])
async def impersonate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = uuid.UUID(user_id)
    res = await db.execute(select(User).where(User.id == uid))
    target = res.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    org = await db.execute(select(Organisation).where(Organisation.id == target.organisation_id))
    org_row = org.scalar_one_or_none()
    if org_row is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    access_token, access_exp = create_access_token(
        subject=str(target.id),
        role=target.role,
        org_id=org_row.id,
        org_uuid=str(org_row.uuid),
        org_slug=org_row.slug,
        plan_status=org_row.status_abonnement,
    )
    await log_system_event(
        db,
        level="warning",
        code="IMPERSONATION",
        message="Super admin impersonated user",
        organisation_id=org_row.id,
        metadata={
            "target_user_id": str(target.id),
            "target_email": target.email,
            "organisation_slug": org_row.slug,
        },
    )
    return {
        "access_token": access_token,
        "expires_in": int((access_exp - _utcnow()).total_seconds()),
        "user_id": str(target.id),
        "organisation_id": org_row.id,
        "organisation_slug": org_row.slug,
        "impersonated": True,
    }
