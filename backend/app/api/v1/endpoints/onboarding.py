from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.plan import Plan
from app.models.tenant_signup import TenantSignup
from app.schemas.onboarding import (
    InvitationCheckRequest,
    InvitationCheckResponse,
    PlanOut,
    TenantCheckoutRequest,
    TenantCheckoutResponse,
    TenantSignupCreate,
    TenantSignupResponse,
)
from app.core.config import settings
from app.services.tenant_manager import provision_new_tenant, activate_reserved_tenant
import httpx

router = APIRouter()

_RESERVED_SLUGS = {"admin", "www", "app", "signup"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_slug(raw: str) -> str:
    slug = (raw or "").strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _resolve_discount(months: int) -> float:
    if months == 3:
        return settings.billing_discount_3m
    if months == 6:
        return settings.billing_discount_6m
    if months == 12:
        return settings.billing_discount_12m
    return 0.0


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanOut]:
    res = await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_price_usd.asc()))
    plans = res.scalars().all()
    discounts = {
        "3": settings.billing_discount_3m,
        "6": settings.billing_discount_6m,
        "12": settings.billing_discount_12m,
    }
    return [
        PlanOut(
            id=plan.id,
            name=plan.name,
            monthly_price_usd=str(plan.monthly_price_usd),
            features=plan.features or None,
            discounts=discounts,
        )
        for plan in plans
    ]


@router.post("/check-invitation", response_model=InvitationCheckResponse)
async def check_invitation(
    payload: InvitationCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> InvitationCheckResponse:
    res = await db.execute(
        select(Organisation).where(
            Organisation.email_contact == str(payload.email).lower().strip(),
            Organisation.status_abonnement == "PENDING_ACTIVATION",
        )
    )
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Aucune invitation trouvée")

    plan_res = await db.execute(
        select(Plan).where(
            Plan.name.ilike(org.plan_type or ""),
            Plan.is_active.is_(True),
        )
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan introuvable")

    discounts = {
        "3": settings.billing_discount_3m,
        "6": settings.billing_discount_6m,
        "12": settings.billing_discount_12m,
    }
    return InvitationCheckResponse(
        organisation_id=org.id,
        organisation_name=org.nom,
        slug=org.slug,
        plan_id=plan.id,
        plan_name=plan.name,
        monthly_price_usd=str(plan.monthly_price_usd),
        discounts=discounts,
    )


@router.post("/signup", response_model=TenantSignupResponse, status_code=status.HTTP_201_CREATED)
async def create_signup(
    payload: TenantSignupCreate,
    db: AsyncSession = Depends(get_db),
) -> TenantSignupResponse:
    slug = _clean_slug(payload.slug)
    if not slug or slug in _RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="Slug invalide")

    plan_res = await db.execute(select(Plan).where(Plan.id == payload.plan_id, Plan.is_active.is_(True)))
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan introuvable")

    if payload.billing_months not in {1, 3, 6, 12}:
        raise HTTPException(status_code=400, detail="Durée d'abonnement invalide")

    org_res = await db.execute(
        select(Organisation).where(
            Organisation.slug == slug,
            Organisation.status_abonnement == "PENDING_ACTIVATION",
        )
    )
    org = org_res.scalar_one_or_none()
    if org is None or (org.email_contact or "").lower() != str(payload.admin_email).lower().strip():
        raise HTTPException(status_code=404, detail="Invitation introuvable")

    plan_match_res = await db.execute(
        select(Plan.id).where(Plan.name.ilike(org.plan_type or ""))
    )
    plan_match_id = plan_match_res.scalar_one_or_none()
    if plan_match_id and plan_match_id != payload.plan_id:
        raise HTTPException(status_code=400, detail="Plan réservé différent")

    signup_res = await db.execute(select(TenantSignup.id).where(TenantSignup.organisation_id == org.id))
    if signup_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Demande déjà enregistrée")

    reference = f"signup_{uuid.uuid4().hex[:12]}"
    signup = TenantSignup(
        organisation_name=org.nom.strip(),
        slug=slug,
        admin_email=str(payload.admin_email).lower().strip(),
        admin_phone=payload.admin_phone,
        plan_id=payload.plan_id,
        organisation_id=org.id,
        billing_months=payload.billing_months,
        status="pending_payment",
        reference=reference,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(signup)
    await db.commit()

    return TenantSignupResponse(
        id=str(signup.id),
        reference=reference,
        status=signup.status,
        plan_id=signup.plan_id,
        organisation_id=signup.organisation_id,
    )


@router.post("/checkout", response_model=TenantCheckoutResponse)
async def create_checkout(
    payload: TenantCheckoutRequest,
    db: AsyncSession = Depends(get_db),
) -> TenantCheckoutResponse:
    res = await db.execute(select(TenantSignup).where(TenantSignup.reference == payload.reference))
    signup = res.scalar_one_or_none()
    if signup is None:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    plan_res = await db.execute(select(Plan).where(Plan.id == signup.plan_id))
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan introuvable")

    if plan.monthly_price_usd <= 0:
        if signup.organisation_id:
            org, subscription, _ = await activate_reserved_tenant(
                db,
                organisation_id=signup.organisation_id,
                plan_id=signup.plan_id,
                admin_email=signup.admin_email,
                admin_phone=signup.admin_phone,
                paid_months=signup.billing_months,
            )
        else:
            org, subscription, _ = await provision_new_tenant(
                db,
                organisation_name=signup.organisation_name,
                slug=signup.slug,
                plan_id=signup.plan_id,
                admin_email=signup.admin_email,
                admin_phone=signup.admin_phone,
                paid_months=signup.billing_months,
            )
        signup.status = "provisioned"
        signup.updated_at = _utcnow()
        await db.commit()
        return TenantCheckoutResponse(checkout_url="", transaction_id=None, status="provisioned")

    if not settings.fedapay_api_key:
        raise HTTPException(status_code=500, detail="FedaPay non configuré")

    base_url = settings.fedapay_base_url or "https://api.fedapay.com/v1"
    return_url = payload.success_url or settings.fedapay_return_url or ""
    cancel_url = payload.cancel_url or settings.fedapay_return_url or ""

    discount_rate = _resolve_discount(signup.billing_months)
    amount = float(plan.monthly_price_usd) * signup.billing_months * (1 - discount_rate)
    metadata = {
        "signup_reference": signup.reference,
        "plan_id": signup.plan_id,
        "billing_months": signup.billing_months,
        "discount_rate": discount_rate,
        "province_name": signup.organisation_name,
        "requested_slug": signup.slug,
        "admin_email": signup.admin_email,
    }
    body = {
        "description": f"Abonnement {plan.name} - {signup.organisation_name}",
        "amount": round(amount, 2),
        "currency": settings.fedapay_currency,
        "callback_url": return_url,
        "customer": {
            "email": signup.admin_email,
            "phone_number": signup.admin_phone,
        },
        "metadata": metadata,
        "cancel_url": cancel_url,
    }

    headers = {"Authorization": f"Bearer {settings.fedapay_api_key}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{base_url}/transactions", json=body, headers=headers)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="FedaPay indisponible")
        data = resp.json()

    tx = data.get("transaction") or data.get("data") or data
    tx_id = tx.get("id") if isinstance(tx, dict) else None
    checkout_url = (
        (tx.get("checkout_url") if isinstance(tx, dict) else None)
        or (tx.get("payment_url") if isinstance(tx, dict) else None)
        or data.get("checkout_url")
        or data.get("payment_url")
    )
    if not checkout_url:
        raise HTTPException(status_code=502, detail="URL de paiement manquante")

    signup.fedapay_transaction_id = str(tx_id) if tx_id else signup.fedapay_transaction_id
    signup.status = "payment_initiated"
    signup.updated_at = _utcnow()
    await db.commit()

    return TenantCheckoutResponse(
        checkout_url=str(checkout_url),
        transaction_id=str(tx_id) if tx_id else None,
        status=signup.status,
    )
