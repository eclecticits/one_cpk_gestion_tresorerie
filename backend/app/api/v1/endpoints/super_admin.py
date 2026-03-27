from __future__ import annotations

import re
import uuid
import time
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
from app.services.admin_stats import get_global_treasury_stats
from app.services.monitoring.events import log_system_event
from app.services.monthly_report import generate_national_report
from app.utils.scheduler import get_monthly_report_status
from app.schemas.super_admin import (
    SuperAdminOrganisationCreate,
    SuperAdminOrganisationOut,
    SuperAdminOrganisationUpdate,
    SuperAdminOrganisationReservation,
    OrganisationSettingsOut,
    OrganisationSettingsUpdate,
    SimulatePaymentRequest,
)
from app.schemas.saas_billing import BillingConfigOut, BillingConfigUpdate, BillingConfigApplyRequest
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.organisation_settings import OrganisationSettings
from app.models.tenant_signup import TenantSignup
from app.models.platform_settings import PlatformSettings
from app.models.saas_transaction import PaymentStatus, Transaction
from app.services.tenant_manager import add_months
from app.services.tenant_manager import activate_reserved_tenant, add_months

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


def _interval_to_months(interval: str | None) -> int:
    value = (interval or "").strip().lower()
    if value in {"year", "yearly", "annual", "annually"}:
        return 12
    if value in {"quarter", "quarterly"}:
        return 3
    if value in {"semiannual", "semi-annually", "biannual"}:
        return 6
    return 1


def _merge_billing_config(global_config: dict, tenant_config: dict) -> dict:
    merged = dict(global_config or {})
    for key, value in (tenant_config or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


async def _resolve_org(db: AsyncSession, tenant_id: str) -> Organisation:
    if tenant_id.isdigit():
        res = await db.execute(select(Organisation).where(Organisation.id == int(tenant_id)))
    else:
        res = await db.execute(select(Organisation).where(Organisation.slug == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    return org


@router.post(
    "/organisations/reserve",
    response_model=SuperAdminOrganisationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_super_admin)],
)
async def reserve_organisation(
    payload: SuperAdminOrganisationReservation,
    db: AsyncSession = Depends(get_db),
) -> SuperAdminOrganisationOut:
    slug = _clean_slug(payload.slug)
    if not slug:
        raise HTTPException(status_code=400, detail="Slug invalide")

    existing = await db.execute(select(Organisation).where(Organisation.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Slug déjà utilisé")

    email = str(payload.admin_email).lower().strip()
    email_res = await db.execute(select(Organisation.id).where(Organisation.email_contact == email))
    if email_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email déjà réservé")

    plan_res = await db.execute(select(Plan).where(Plan.id == payload.plan_id, Plan.is_active.is_(True)))
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan introuvable")

    now = _utcnow()
    org = Organisation(
        nom=payload.nom.strip(),
        slug=slug,
        plan_type=plan.name,
        status_abonnement="PENDING_ACTIVATION",
        date_expiration_abonnement=None,
        limite_utilisateurs=payload.max_users,
        is_active=False,
        email_contact=email,
        telephone=payload.admin_phone,
        devise_preferee=payload.currency_code.upper(),
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    await db.flush()

    db.add(
        OrganisationSettings(
            organisation_id=org.id,
            max_users=payload.max_users,
            storage_quota_mb=payload.storage_quota_mb,
            is_ai_enabled=payload.is_ai_enabled,
            is_mobile_money_enabled=payload.is_mobile_money_enabled,
            is_audit_logs_enabled=payload.is_audit_logs_enabled,
            fiscal_year_start=payload.fiscal_year_start,
            currency_code=payload.currency_code.upper(),
        )
    )

    db.add(
        Subscription(
            organisation_id=org.id,
            plan_id=plan.id,
            status="PENDING_PAYMENT",
            created_at=now,
            updated_at=now,
        )
    )

    await db.commit()
    return _org_out(org, 0)


@router.get(
    "/organisations/{org_id}/settings",
    response_model=OrganisationSettingsOut,
    dependencies=[Depends(require_super_admin)],
)
async def get_org_settings(org_id: int, db: AsyncSession = Depends(get_db)) -> OrganisationSettingsOut:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == org_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Configuration introuvable")
    return OrganisationSettingsOut(
        organisation_id=settings.organisation_id,
        max_users=settings.max_users,
        storage_quota_mb=settings.storage_quota_mb,
        is_ai_enabled=settings.is_ai_enabled,
        is_mobile_money_enabled=settings.is_mobile_money_enabled,
        is_audit_logs_enabled=settings.is_audit_logs_enabled,
        fiscal_year_start=settings.fiscal_year_start,
        currency_code=settings.currency_code,
        theme_primary_color=settings.theme_primary_color,
        theme_sidebar_color=settings.theme_sidebar_color,
        theme_sidebar_text_color=settings.theme_sidebar_text_color,
        theme_sidebar_active_color=settings.theme_sidebar_active_color,
        theme_accent_color=settings.theme_accent_color,
        theme_text_color=settings.theme_text_color,
        theme_button_text_color=settings.theme_button_text_color,
    )


@router.put(
    "/organisations/{org_id}/settings",
    response_model=OrganisationSettingsOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_org_settings(
    org_id: int,
    payload: OrganisationSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> OrganisationSettingsOut:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == org_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Configuration introuvable")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is None:
            continue
        setattr(settings, key, value)
    if payload.currency_code:
        settings.currency_code = payload.currency_code.upper()

    org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = org_res.scalar_one_or_none()
    if org:
        if settings.max_users is not None:
            org.limite_utilisateurs = settings.max_users
        if settings.currency_code:
            org.devise_preferee = settings.currency_code
        org.updated_at = _utcnow()

    await db.commit()
    return OrganisationSettingsOut(
        organisation_id=settings.organisation_id,
        max_users=settings.max_users,
        storage_quota_mb=settings.storage_quota_mb,
        is_ai_enabled=settings.is_ai_enabled,
        is_mobile_money_enabled=settings.is_mobile_money_enabled,
        is_audit_logs_enabled=settings.is_audit_logs_enabled,
        fiscal_year_start=settings.fiscal_year_start,
        currency_code=settings.currency_code,
        theme_primary_color=settings.theme_primary_color,
        theme_sidebar_color=settings.theme_sidebar_color,
        theme_sidebar_text_color=settings.theme_sidebar_text_color,
        theme_sidebar_active_color=settings.theme_sidebar_active_color,
        theme_accent_color=settings.theme_accent_color,
        theme_text_color=settings.theme_text_color,
        theme_button_text_color=settings.theme_button_text_color,
    )


async def _get_platform_settings(db: AsyncSession) -> PlatformSettings:
    res = await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    settings = res.scalar_one_or_none()
    if settings is None:
        settings = PlatformSettings(id=1, billing_config=None, updated_at=_utcnow())
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.get(
    "/billing-config",
    response_model=BillingConfigOut,
    dependencies=[Depends(require_super_admin)],
)
async def get_global_billing_config(db: AsyncSession = Depends(get_db)) -> BillingConfigOut:
    settings = await _get_platform_settings(db)
    raw = settings.billing_config or {}
    return BillingConfigOut(
        tenant_id="global",
        plan=raw.get("plan"),
        payment_methods=raw.get("payment_methods"),
        support_contact=raw.get("support_contact"),
        billing_portal_url=raw.get("billing_portal_url"),
        raw=raw,
    )


@router.put(
    "/billing-config",
    response_model=BillingConfigOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_global_billing_config(
    payload: BillingConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> BillingConfigOut:
    settings = await _get_platform_settings(db)
    current = settings.billing_config or {}
    update = payload.model_dump(exclude_none=True)
    merged = {**current, **update}
    settings.billing_config = merged
    settings.updated_at = _utcnow()
    await db.commit()
    await db.refresh(settings)
    return BillingConfigOut(
        tenant_id="global",
        plan=merged.get("plan"),
        payment_methods=merged.get("payment_methods"),
        support_contact=merged.get("support_contact"),
        billing_portal_url=merged.get("billing_portal_url"),
        raw=merged,
    )


@router.post(
    "/billing-config/apply-to-all",
    dependencies=[Depends(require_super_admin)],
)
async def apply_global_billing_config(
    payload: BillingConfigApplyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await _get_platform_settings(db)
    global_config = settings.billing_config or {}
    if not global_config:
        raise HTTPException(status_code=400, detail="Aucune configuration globale à appliquer")

    res = await db.execute(select(Organisation))
    orgs = res.scalars().all()
    applied = 0
    for org in orgs:
        if org.billing_config and not payload.overwrite:
            continue
        org.billing_config = {**global_config} if payload.overwrite else {**global_config, **(org.billing_config or {})}
        applied += 1
    await db.commit()
    return {"ok": True, "applied": applied, "overwrite": payload.overwrite}


async def _apply_transaction_success(
    db: AsyncSession,
    transaction: Transaction,
    org: Organisation,
    global_config: dict,
) -> None:
    metadata = dict(transaction.metadata_json or {})
    if metadata.get("applied_at"):
        return
    merged = _merge_billing_config(global_config, org.billing_config or {})
    interval = None
    plan_name = None
    if isinstance(merged.get("plan"), dict):
        interval = merged.get("plan", {}).get("interval")
        plan_name = merged.get("plan", {}).get("name")
    if plan_name:
        org.plan_type = str(plan_name).upper()

    months = _interval_to_months(interval)
    base_date = (
        org.date_expiration_abonnement
        if org.date_expiration_abonnement and org.date_expiration_abonnement > _utcnow()
        else _utcnow()
    )
    org.date_expiration_abonnement = add_months(base_date, months)
    org.status_abonnement = "ACTIVE"
    org.is_active = True

    sub_res = await db.execute(
        select(Subscription).where(Subscription.organisation_id == org.id).order_by(Subscription.created_at.desc())
    )
    subscription = sub_res.scalars().first()
    if subscription:
        subscription.status = "ACTIVE"
        subscription.current_period_end = org.date_expiration_abonnement
        subscription.updated_at = _utcnow()

    metadata["applied_at"] = _utcnow().isoformat()
    transaction.metadata_json = metadata


@router.get(
    "/organisations/{org_id}/billing-config",
    response_model=BillingConfigOut,
    dependencies=[Depends(require_super_admin)],
)
async def get_org_billing_config(org_id: int, db: AsyncSession = Depends(get_db)) -> BillingConfigOut:
    res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    raw = org.billing_config or {}
    return BillingConfigOut(
        tenant_id=org.slug,
        plan=raw.get("plan"),
        payment_methods=raw.get("payment_methods"),
        support_contact=raw.get("support_contact"),
        billing_portal_url=raw.get("billing_portal_url"),
        raw=raw,
    )


@router.put(
    "/organisations/{org_id}/billing-config",
    response_model=BillingConfigOut,
    dependencies=[Depends(require_super_admin)],
)
async def update_org_billing_config(
    org_id: int,
    payload: BillingConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> BillingConfigOut:
    res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    current = org.billing_config or {}
    update = payload.model_dump(exclude_none=True)
    merged = {**current, **update}
    org.billing_config = merged
    await db.commit()
    await db.refresh(org)
    return BillingConfigOut(
        tenant_id=org.slug,
        plan=merged.get("plan"),
        payment_methods=merged.get("payment_methods"),
        support_contact=merged.get("support_contact"),
        billing_portal_url=merged.get("billing_portal_url"),
        raw=merged,
    )


@router.post(
    "/organisations/{org_id}/billing-config/reset",
    dependencies=[Depends(require_super_admin)],
)
async def reset_org_billing_config(
    org_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    org.billing_config = None
    await db.commit()
    return {"ok": True}


@router.get("/payments/bank-proofs", dependencies=[Depends(require_super_admin)])
async def list_bank_proofs(
    limit: int = 50,
    tenant_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    limit = max(1, min(int(limit), 200))
    query = select(Transaction).order_by(Transaction.created_at.desc())
    if tenant_id:
        query = query.where(Transaction.tenant_id == tenant_id)
    res = await db.execute(query.limit(limit * 5))
    rows = res.scalars().all()
    items = []
    for tx in rows:
        meta = tx.metadata_json or {}
        proof = meta.get("bank_proof_url")
        if not proof:
            continue
        items.append(
            {
                "id": tx.id,
                "tenant_id": tx.tenant_id,
                "amount": float(tx.amount),
                "currency": tx.currency,
                "status": tx.status.value if tx.status else None,
                "provider": tx.provider,
                "proof_url": proof,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
                "applied_at": meta.get("applied_at"),
                "proof_uploaded_at": meta.get("bank_proof_uploaded_at"),
            }
        )
        if len(items) >= limit:
            break
    return {"items": items}


@router.post("/payments/bank-proofs/{transaction_id}/approve", dependencies=[Depends(require_super_admin)])
async def approve_bank_proof(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    org = await _resolve_org(db, transaction.tenant_id)
    global_settings = await _get_platform_settings(db)
    global_config = global_settings.billing_config or {}

    transaction.status = PaymentStatus.SUCCESS
    metadata = dict(transaction.metadata_json or {})
    metadata["bank_proof_approved_at"] = _utcnow().isoformat()
    transaction.metadata_json = metadata

    await _apply_transaction_success(db, transaction, org, global_config)
    await db.commit()
    return {"ok": True}


@router.post("/payments/bank-proofs/{transaction_id}/reject", dependencies=[Depends(require_super_admin)])
async def reject_bank_proof(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    transaction.status = PaymentStatus.FAILED
    metadata = dict(transaction.metadata_json or {})
    metadata["bank_proof_rejected_at"] = _utcnow().isoformat()
    transaction.metadata_json = metadata
    await db.commit()
    return {"ok": True}


@router.get("/organisations/{org_id}/payments", dependencies=[Depends(require_super_admin)])
async def list_org_payments(
    org_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    limit = max(1, min(int(limit), 200))
    org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = org_res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    res = await db.execute(
        select(Transaction)
        .where(Transaction.tenant_id == org.slug)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    items = []
    for tx in res.scalars().all():
        meta = tx.metadata_json or {}
        items.append(
            {
                "id": tx.id,
                "amount": float(tx.amount),
                "currency": tx.currency,
                "status": tx.status.value if tx.status else None,
                "provider": tx.provider,
                "method": meta.get("method"),
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
                "paid_at": meta.get("applied_at"),
            }
        )
    return {"items": items}


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


@router.post("/organisations/{org_id}/simulate-payment", dependencies=[Depends(require_super_admin)])
async def simulate_payment(
    org_id: int,
    payload: SimulatePaymentRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = org_res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    sub_res = await db.execute(
        select(Subscription).where(Subscription.organisation_id == org_id).order_by(Subscription.created_at.desc())
    )
    subscription = sub_res.scalars().first()
    plan = None
    if subscription:
        plan_res = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
        plan = plan_res.scalar_one_or_none()
    if plan is None:
        plan_res = await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.id.asc()))
        plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=400, detail="Aucun plan actif disponible")

    admin_email = (payload.admin_email or org.email_contact or "").strip().lower()
    if not admin_email:
        raise HTTPException(status_code=400, detail="Email admin manquant pour la simulation")

    reference = f"SIM-{org_id}-{int(time.time())}"
    db.add(
        TenantSignup(
            organisation_name=org.nom,
            slug=org.slug,
            admin_email=admin_email,
            plan_id=plan.id,
            organisation_id=org_id,
            billing_months=payload.billing_months,
            status="pending_payment",
            reference=reference,
        )
    )

    org, subscription, temp_password = await activate_reserved_tenant(
        db,
        organisation_id=org_id,
        plan_id=plan.id,
        admin_email=admin_email,
        admin_phone=org.telephone,
        paid_months=payload.billing_months,
    )

    org.plan_type = (plan.name if plan else "STANDARD").upper()
    org.status_abonnement = "ACTIVE"
    org.is_active = True
    org.date_expiration_abonnement = add_months(_utcnow(), payload.billing_months)

    subscription.status = "ACTIVE"
    subscription.current_period_end = org.date_expiration_abonnement
    subscription.updated_at = _utcnow()

    await db.commit()
    return {
        "ok": True,
        "organisation_id": org.id,
        "admin_email": admin_email,
        "reference": reference,
        "temp_password": temp_password,
    }


@router.get("/monitoring/summary", dependencies=[Depends(require_super_admin)])
async def platform_summary(db: AsyncSession = Depends(get_db)) -> dict:
    return await fetch_platform_summary(db)


@router.get("/monitoring/tenants", dependencies=[Depends(require_super_admin)])
async def tenants_metrics(db: AsyncSession = Depends(get_db)) -> dict:
    metrics = await fetch_tenant_metrics(db)
    expiring = await fetch_expiring_soon(db, days=5)
    anomalies = await detect_anomalies(db)
    return {"metrics": metrics, "expiring": expiring, "anomalies": anomalies}


@router.get("/monitoring/treasury", dependencies=[Depends(require_super_admin)])
async def treasury_stats(db: AsyncSession = Depends(get_db)) -> dict:
    items = await get_global_treasury_stats(db)
    return {"items": items}


@router.get("/global-stats", dependencies=[Depends(require_super_admin)])
async def global_stats(db: AsyncSession = Depends(get_db)) -> list[dict]:
    items = await get_global_treasury_stats(db)
    return [
        {
            "id": row["organisation_id"],
            "name": row["organisation_name"],
            "slug": row["organisation_slug"],
            "balance": row["total_encaisse"],
            "usage": 0,
            "is_active": row.get("is_active", True),
        }
        for row in items
    ]


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
