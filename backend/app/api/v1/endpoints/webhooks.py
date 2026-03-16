from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.tenant_signup import TenantSignup
from app.services.tenant_manager import provision_new_tenant, activate_reserved_tenant, add_months
from app.services.mailer import send_tenant_welcome
from app.utils.fedapay import verify_fedapay_signature

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_event(payload: dict) -> tuple[str | None, dict]:
    event_type = payload.get("event") or payload.get("type") or payload.get("name")
    data = payload.get("data") or payload.get("entity") or payload.get("transaction") or {}
    if isinstance(data, dict) and "transaction" in data and isinstance(data["transaction"], dict):
        data = data["transaction"]
    return event_type, data if isinstance(data, dict) else {}


def _extract_signup_ref(payload: dict, data: dict) -> str | None:
    meta = data.get("metadata") or data.get("custom_metadata") or {}
    if isinstance(meta, dict):
        ref = meta.get("signup_id") or meta.get("signup_reference") or meta.get("reference")
        if ref:
            return str(ref)
    ref = data.get("reference") or data.get("description") or payload.get("reference")
    if ref:
        return str(ref)
    return None


@router.post("/fedapay")
async def fedapay_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    body = await request.body()
    signature = request.headers.get("x-fedapay-signature") or request.headers.get("fedapay-signature")
    if settings.fedapay_webhook_secret:
        valid = verify_fedapay_signature(
            payload=body,
            signature_header=signature,
            secret=settings.fedapay_webhook_secret,
            tolerance=settings.fedapay_webhook_tolerance,
        )
        if not valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature invalide")
    elif (settings.env or "").lower() != "dev":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature manquante")

    payload = await request.json()
    event_type, data = _extract_event(payload)
    if event_type != "transaction.approved":
        return {"ok": True}

    signup_ref = _extract_signup_ref(payload, data)
    fedapay_id = data.get("id") or payload.get("id")
    if not signup_ref and not fedapay_id:
        return {"ok": True}

    signup = None
    if signup_ref:
        res = await db.execute(select(TenantSignup).where(TenantSignup.reference == signup_ref))
        signup = res.scalar_one_or_none()
    if signup is None and fedapay_id:
        res = await db.execute(
            select(TenantSignup).where(TenantSignup.fedapay_transaction_id == str(fedapay_id))
        )
        signup = res.scalar_one_or_none()
    if signup is None:
        return {"ok": True}

    if signup.status in {"provisioned", "active"}:
        return {"ok": True}

    signup.fedapay_transaction_id = str(fedapay_id) if fedapay_id else signup.fedapay_transaction_id
    signup.status = "paid"
    signup.updated_at = _utcnow()
    await db.flush()

    org_res = await db.execute(select(Organisation).where(Organisation.slug == signup.slug))
    existing_org = org_res.scalar_one_or_none()
    if existing_org is not None and (signup.organisation_id is None or existing_org.id != signup.organisation_id):
        signup.status = "failed"
        signup.error_message = "Slug déjà utilisé"
        await db.commit()
        raise HTTPException(status_code=409, detail="Organisation déjà existante")

    try:
        if signup.organisation_id:
            org, subscription, temp_password = await activate_reserved_tenant(
                db,
                organisation_id=signup.organisation_id,
                plan_id=signup.plan_id,
                admin_email=signup.admin_email,
                admin_phone=signup.admin_phone,
                paid_months=signup.billing_months,
            )
        else:
            org, subscription, temp_password = await provision_new_tenant(
                db,
                organisation_name=signup.organisation_name,
                slug=signup.slug,
                plan_id=signup.plan_id,
                admin_email=signup.admin_email,
                admin_phone=signup.admin_phone,
                paid_months=signup.billing_months,
            )
    except Exception as exc:
        signup.status = "failed"
        signup.error_message = str(exc)
        signup.updated_at = _utcnow()
        await db.commit()
        raise

    plan_res = await db.execute(select(Plan).where(Plan.id == signup.plan_id))
    plan = plan_res.scalar_one_or_none()

    org.status_abonnement = "ACTIVE"
    org.plan_type = (plan.name if plan else "STANDARD").upper()
    org.date_expiration_abonnement = add_months(_utcnow(), signup.billing_months)
    org.is_active = True

    subscription.status = "ACTIVE"
    subscription.fedapay_transaction_id = str(fedapay_id) if fedapay_id else subscription.fedapay_transaction_id
    subscription.current_period_end = org.date_expiration_abonnement
    subscription.updated_at = _utcnow()

    signup.status = "provisioned"
    signup.updated_at = _utcnow()
    await db.commit()

    if settings.smtp_host and settings.smtp_port and settings.smtp_user and settings.smtp_password:
        base_domain = settings.tenant_base_domain or ""
        if base_domain:
            login_url = f"https://{org.slug}.{base_domain}"
        else:
            login_url = "/login"
        send_tenant_welcome(
            smtp_host=settings.smtp_host,
            smtp_port=int(settings.smtp_port),
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            sender=settings.smtp_user,
            recipient=signup.admin_email,
            organisation_name=org.nom,
            temp_password=temp_password,
            login_url=login_url,
        )

    return {"ok": True, "organisation_id": org.id}
