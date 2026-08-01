from __future__ import annotations

from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.platform_settings import PlatformSettings
from app.models.saas_invoice import SaaSInvoice
from app.models.saas_transaction import PaymentStatus, Transaction
from app.models.subscription import Subscription
from app.schemas.saas_billing import BillingConfigOut, BillingConfigUpdate
from app.schemas.saas_payments import PaymentSessionCreate, PaymentSessionResponse, PaymentSessionInitiate
from app.services.payments.registry import get_provider
from app.services.saas_billing_notifications import create_and_send_saas_invoice
from app.services.tenant_manager import add_months

router = APIRouter()


def _require_internal_key(x_api_key: str | None) -> None:
    if not settings.saas_internal_key or not x_api_key or x_api_key != settings.saas_internal_key:
        raise HTTPException(status_code=403, detail="Unauthorized")


async def _resolve_org(db: AsyncSession, tenant_id: str) -> Organisation:
    if tenant_id.isdigit():
        res = await db.execute(select(Organisation).where(Organisation.id == int(tenant_id)))
    else:
        res = await db.execute(select(Organisation).where(Organisation.slug == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    return org


async def _get_platform_billing_config(db: AsyncSession) -> dict:
    res = await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    settings_row = res.scalar_one_or_none()
    return settings_row.billing_config if settings_row and settings_row.billing_config else {}


def _merge_billing_config(global_config: dict, tenant_config: dict) -> dict:
    merged = dict(global_config or {})
    for key, value in (tenant_config or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


def _platform_merchant_config(global_config: dict | None = None) -> dict:
    raw = global_config or {}
    platform_payments = raw.get("platform_payments") or raw.get("saas_payments") or {}
    if not isinstance(platform_payments, dict):
        platform_payments = {}
    provider_config = platform_payments.get("epaielink") or {}
    if not isinstance(provider_config, dict):
        provider_config = {}
    return {
        "api_key": provider_config.get("api_key") or settings.epaielink_api_key,
        "site_id": provider_config.get("site_id") or settings.epaielink_site_id,
        "notify_url": provider_config.get("notify_url") or settings.epaielink_notify_url,
        "return_url": provider_config.get("return_url") or settings.epaielink_return_url,
    }


def _merchant_account_ref(config: dict) -> str | None:
    return config.get("site_id") or config.get("merchant_site_id") or config.get("merchant_account")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _interval_to_months(interval: str | None) -> int:
    value = (interval or "").strip().lower()
    if value in {"year", "yearly", "annual", "annually"}:
        return 12
    if value in {"quarter", "quarterly"}:
        return 3
    if value in {"semiannual", "semi-annually", "biannual"}:
        return 6
    return 1


def _checkout_upload_root() -> str:
    default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads"))
    return os.path.abspath(settings.upload_dir) if settings.upload_dir else default_root


def _save_checkout_upload(file: UploadFile, session_id: str, label: str) -> str:
    upload_root = _checkout_upload_root()
    target_dir = os.path.join(upload_root, "checkout", session_id)
    os.makedirs(target_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    filename = f"{label}{ext or ''}"
    file_path = os.path.join(target_dir, filename)
    with open(file_path, "wb") as out:
        out.write(file.file.read())
    return f"/uploads/checkout/{session_id}/{filename}"


@router.get("/tenants/{tenant_id}/billing-config", response_model=BillingConfigOut)
async def get_billing_config_saas(
    tenant_id: str,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    db: AsyncSession = Depends(get_db),
) -> BillingConfigOut:
    _require_internal_key(x_api_key)
    org = await _resolve_org(db, tenant_id)
    global_config = await _get_platform_billing_config(db)
    raw = _merge_billing_config(global_config, org.billing_config or {})
    return BillingConfigOut(
        tenant_id=org.slug,
        plan=raw.get("plan"),
        payment_methods=raw.get("payment_methods"),
        platform_payments=raw.get("platform_payments"),
        tenant_payments=raw.get("tenant_payments"),
        support_contact=raw.get("support_contact"),
        billing_portal_url=raw.get("billing_portal_url"),
        raw=raw,
    )


@router.put("/tenants/{tenant_id}/billing-config", response_model=BillingConfigOut)
async def update_billing_config_saas(
    tenant_id: str,
    payload: BillingConfigUpdate,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    db: AsyncSession = Depends(get_db),
) -> BillingConfigOut:
    _require_internal_key(x_api_key)
    org = await _resolve_org(db, tenant_id)
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
        platform_payments=merged.get("platform_payments"),
        tenant_payments=merged.get("tenant_payments"),
        support_contact=merged.get("support_contact"),
        billing_portal_url=merged.get("billing_portal_url"),
        raw=merged,
    )


@router.get("/tenants/{tenant_id}/invoices")
async def list_tenant_invoices(
    tenant_id: str,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_internal_key(x_api_key)
    org = await _resolve_org(db, tenant_id)
    res = await db.execute(
        select(SaaSInvoice)
        .where(SaaSInvoice.organisation_id == org.id)
        .order_by(SaaSInvoice.issue_date.desc())
    )
    invoices = res.scalars().all()
    return {
        "items": [
            {
                "id": str(invoice.id),
                "number": invoice.invoice_number,
                "reference": invoice.invoice_number,
                "status": invoice.status,
                "amount": float(invoice.amount),
                "currency": invoice.currency,
                "issued_at": invoice.issue_date.isoformat() if invoice.issue_date else None,
                "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
                "period_start": invoice.period_start.isoformat() if invoice.period_start else None,
                "period_end": invoice.period_end.isoformat() if invoice.period_end else None,
                "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None,
            }
            for invoice in invoices
        ]
    }


@router.get("/tenants/{tenant_id}/invoices/{invoice_id}/pdf")
async def download_tenant_invoice_pdf(
    tenant_id: str,
    invoice_id: str,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    _require_internal_key(x_api_key)
    org = await _resolve_org(db, tenant_id)
    filters = [SaaSInvoice.organisation_id == org.id]
    try:
        import uuid

        filters.append(SaaSInvoice.id == uuid.UUID(invoice_id))
    except ValueError:
        filters.append(SaaSInvoice.invoice_number == invoice_id)
    res = await db.execute(select(SaaSInvoice).where(*filters))
    invoice = res.scalar_one_or_none()
    if invoice is None or not invoice.pdf_path or not os.path.exists(invoice.pdf_path):
        raise HTTPException(status_code=404, detail="Note de débit introuvable")
    return FileResponse(invoice.pdf_path, media_type="application/pdf", filename=f"{invoice.invoice_number}.pdf")


@router.post("/payments/create-session", response_model=PaymentSessionResponse)
async def create_payment_session(
    payload: PaymentSessionCreate,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    db: AsyncSession = Depends(get_db),
) -> PaymentSessionResponse:
    _require_internal_key(x_api_key)

    transaction = Transaction(
        tenant_id=payload.tenant_id,
        flow="SAAS_SUBSCRIPTION",
        beneficiary_type="PLATFORM",
        beneficiary_organisation_id=None,
        amount=payload.amount,
        currency=payload.currency or "USD",
        status=PaymentStatus.PENDING,
        metadata_json={
            "success_url": payload.success_url,
            "cancel_url": payload.cancel_url,
        },
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    base = (settings.saas_checkout_base_url or "").strip()
    if not base:
        raise HTTPException(status_code=503, detail="Checkout URL non configurée.")
    checkout_url = f"{base.rstrip('/')}/checkout/{transaction.id}"
    return PaymentSessionResponse(checkout_url=checkout_url, transaction_id=transaction.id)


@router.get("/payments/session/{session_id}")
async def get_payment_session(session_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(select(Transaction).where(Transaction.id == session_id))
    transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Session introuvable")

    org = await _resolve_org(db, transaction.tenant_id)
    global_config = await _get_platform_billing_config(db)
    merged = _merge_billing_config(global_config, org.billing_config or {})

    return {
        "session_id": transaction.id,
        "tenant_id": transaction.tenant_id,
        "amount": float(transaction.amount),
        "currency": transaction.currency,
        "status": transaction.status.value if transaction.status else None,
        "payment_methods": merged.get("payment_methods"),
        "support_contact": merged.get("support_contact"),
        "billing_portal_url": merged.get("billing_portal_url"),
        "success_url": (transaction.metadata_json or {}).get("success_url"),
        "cancel_url": (transaction.metadata_json or {}).get("cancel_url"),
        "checkout_url": (transaction.metadata_json or {}).get("checkout_url"),
        "bank_proof_url": (transaction.metadata_json or {}).get("bank_proof_url"),
    }


@router.post("/payments/session/{session_id}/initiate")
async def initiate_payment_session(
    session_id: str,
    payload: PaymentSessionInitiate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Transaction).where(Transaction.id == session_id))
    transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Session introuvable")

    try:
        provider = get_provider(payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    method = (payload.method or "").strip().upper()
    if not method:
        raise HTTPException(status_code=400, detail="Méthode de paiement manquante")

    if method != "VISA" and not payload.phone:
        raise HTTPException(status_code=400, detail="Numéro de téléphone requis")

    global_config = await _get_platform_billing_config(db)
    merchant_config = _platform_merchant_config(global_config)
    merchant_ref = _merchant_account_ref(merchant_config)
    if not merchant_ref:
        raise HTTPException(status_code=400, detail="Compte marchand SaaS non configuré")

    result = await provider.initiate_payment(
        amount=float(transaction.amount),
        currency=transaction.currency,
        reference=str(transaction.id),
        method=method,
        phone=payload.phone,
        description=f"Abonnement One CPK - {transaction.tenant_id}",
        merchant_config=merchant_config,
    )

    metadata = dict(transaction.metadata_json or {})
    attempts = list(metadata.get("attempts") or [])
    attempts.append(
        {
            "at": _utcnow().isoformat(),
            "method": method,
            "phone": payload.phone,
            "provider": provider.name,
            "status": "INITIATED",
        }
    )
    metadata.update(
        {
            "provider": provider.name,
            "provider_ref": result.provider_ref,
            "checkout_url": result.checkout_url,
            "method": method,
            "init_payload": result.raw,
            "attempts": attempts,
        }
    )
    transaction.provider = provider.name
    transaction.external_reference = result.provider_ref
    transaction.merchant_account_ref = str(merchant_ref)
    transaction.metadata_json = metadata
    await db.commit()
    await db.refresh(transaction)

    return {
        "provider": provider.name,
        "provider_ref": result.provider_ref,
        "checkout_url": result.checkout_url,
        "status": transaction.status.value if transaction.status else None,
    }


@router.post("/payments/session/{session_id}/bank-proof")
async def upload_bank_proof(
    session_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Transaction).where(Transaction.id == session_id))
    transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Session introuvable")

    url = _save_checkout_upload(file, session_id, "bank-proof")
    metadata = dict(transaction.metadata_json or {})
    metadata["bank_proof_url"] = url
    metadata["bank_proof_uploaded_at"] = _utcnow().isoformat()
    transaction.status = PaymentStatus.VALIDATION
    attempts = list(metadata.get("attempts") or [])
    attempts.append(
        {
            "at": _utcnow().isoformat(),
            "method": "BANK",
            "status": "BANK_PROOF_UPLOADED",
        }
    )
    metadata["attempts"] = attempts
    transaction.metadata_json = metadata
    await db.commit()
    return {"ok": True, "url": url}


@router.post("/payments/webhook/{provider_name}")
async def payment_webhook(
    provider_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        provider = get_provider(provider_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not provider.verify_webhook(body=body, headers=headers):
        raise HTTPException(status_code=401, detail="Signature invalide")

    event = provider.parse_event(body=body, headers=headers)
    reference = str(event.reference or "").strip()
    provider_ref = str(event.provider_ref or "").strip()
    if not reference and not provider_ref:
        raise HTTPException(status_code=400, detail="Référence manquante")

    transaction = None
    if reference:
        res = await db.execute(select(Transaction).where(Transaction.id == reference))
        transaction = res.scalar_one_or_none()
    if transaction is None and provider_ref:
        res = await db.execute(select(Transaction).where(Transaction.external_reference == provider_ref))
        transaction = res.scalar_one_or_none()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    status_raw = str(event.status or "PENDING").upper()
    if status_raw == "SUCCESS":
        transaction.status = PaymentStatus.SUCCESS
    elif status_raw == "FAILED":
        transaction.status = PaymentStatus.FAILED
    else:
        transaction.status = PaymentStatus.PENDING
    transaction.external_reference = provider_ref or transaction.external_reference
    transaction.provider = provider.name
    metadata = dict(transaction.metadata_json or {})
    metadata["webhook"] = event.raw
    transaction.metadata_json = metadata
    await db.commit()

    if transaction.status == PaymentStatus.SUCCESS:
        metadata = dict(transaction.metadata_json or {})
        if metadata.get("applied_at"):
            return {"status": "ACK"}
        org = await _resolve_org(db, transaction.tenant_id)
        merged = _merge_billing_config(await _get_platform_billing_config(db), org.billing_config or {})
        interval = None
        plan_name = None
        if isinstance(merged.get("plan"), dict):
            interval = merged.get("plan", {}).get("interval")
            plan_name = merged.get("plan", {}).get("name")
        if plan_name:
            org.plan_type = str(plan_name).upper()
        months = _interval_to_months(interval)
        base_date = org.date_expiration_abonnement if org.date_expiration_abonnement and org.date_expiration_abonnement > _utcnow() else _utcnow()
        period_start = base_date
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

        await create_and_send_saas_invoice(
            db,
            transaction=transaction,
            org=org,
            subscription=subscription,
            period_start=period_start,
            period_end=org.date_expiration_abonnement,
            plan_name=plan_name,
        )

        metadata = dict(transaction.metadata_json or {})
        metadata["applied_at"] = _utcnow().isoformat()
        transaction.metadata_json = metadata
        await db.commit()

    return {"status": "ACK"}
