from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.deps import get_current_tenant_id, has_permission, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.organisation import Organisation
from app.schemas.billing import (
    BillingInvoiceListOut,
    BillingInvoiceOut,
    BillingPaymentMethodListOut,
    BillingPaymentMethodOut,
    BillingSummaryOut,
)
from app.schemas.billing_payment import BillingPaymentRequest
from app.models.payment_log import PaymentLog
from app.schemas.payment_log import PaymentLogListOut, PaymentLogOut

router = APIRouter()


def _saas_base_url() -> str | None:
    base = (settings.saas_console_base_url or "").strip()
    if not base:
        return None
    base = base.rstrip("/")
    if base.endswith("/api/v1"):
        return base
    if base.endswith("/api"):
        return f"{base}/v1"
    return f"{base}/api/v1"


def _is_saas_configured() -> bool:
    return bool(settings.saas_console_base_url and settings.saas_internal_key)


def _parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _normalize_invoices(payload: Any) -> list[BillingInvoiceOut]:
    items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("items", "invoices", "data"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
    elif isinstance(payload, list):
        items = payload

    normalized: list[BillingInvoiceOut] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        invoice_id = raw.get("id") or raw.get("invoice_id") or raw.get("number") or str(idx + 1)
        number = raw.get("number") or raw.get("invoice_number") or raw.get("reference")
        date_value = raw.get("date") or raw.get("issued_at") or raw.get("created_at")
        amount_value = raw.get("amount") or raw.get("amount_usd") or raw.get("total")
        currency = raw.get("currency") or raw.get("currency_code") or "USD"
        status = raw.get("status") or raw.get("state")
        pdf_available = raw.get("pdf_available")
        if pdf_available is None:
            pdf_available = bool(raw.get("pdf_url") or raw.get("pdf"))

        normalized.append(
            BillingInvoiceOut(
                id=str(invoice_id),
                number=str(number) if number else None,
                date=_normalize_date(date_value),
                amount=_parse_amount(amount_value),
                currency=str(currency) if currency else None,
                status=str(status) if status else None,
                pdf_available=bool(pdf_available),
            )
        )
    return normalized


def _build_saas_url(path: str) -> str | None:
    base = (settings.saas_console_base_url or "").strip()
    if not base:
        return None
    base = base.rstrip("/")
    if base.endswith("/api/v1"):
        api_base = base
    elif base.endswith("/api"):
        api_base = f"{base}/v1"
    else:
        api_base = f"{base}/api/v1"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{api_base}{path}"


def _normalize_payment_methods(payload: Any) -> list[BillingPaymentMethodOut]:
    items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("items", "methods", "payment_methods", "data"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
    elif isinstance(payload, list):
        items = payload

    normalized: list[BillingPaymentMethodOut] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        method_id = raw.get("id") or raw.get("method_id") or str(idx + 1)
        label = raw.get("label") or raw.get("brand") or raw.get("provider") or "Moyen de paiement"
        method_type = raw.get("method_type") or raw.get("type")
        last4 = raw.get("last4") or raw.get("last_digits")
        status = raw.get("status")
        is_default = raw.get("is_default")
        normalized.append(
            BillingPaymentMethodOut(
                id=str(method_id),
                label=str(label),
                method_type=str(method_type) if method_type else None,
                last4=str(last4) if last4 else None,
                status=str(status) if status else None,
                is_default=bool(is_default),
            )
        )
    return normalized


def _normalize_summary(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    # Standard attendu depuis la console SaaS : plan_price, currency, plan_type, plan_status, plan_expires_at, renewal_date
    price_value = (
        payload.get("plan_price")
        or payload.get("price")
        or payload.get("price_usd")
        or payload.get("amount")
        or payload.get("monthly_price")
    )
    currency_value = payload.get("currency") or payload.get("currency_code") or payload.get("devise")
    portal_value = payload.get("billing_portal_url") or payload.get("portal_url") or payload.get("billing_url")
    return {
        "plan_type": payload.get("plan_type") or payload.get("plan") or payload.get("plan_name"),
        "plan_status": payload.get("plan_status") or payload.get("status"),
        "plan_expires_at": payload.get("plan_expires_at") or payload.get("expires_at"),
        "renewal_date": payload.get("renewal_date") or payload.get("next_renewal"),
        "plan_price": _parse_amount(price_value),
        "currency": currency_value,
        "billing_portal_url": portal_value,
    }


@router.get("/status")
async def get_billing_status(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    saas_status = await deps.get_cached_saas_status(tenant_id)
    status_value = saas_status or org.status_abonnement
    return {
        "status": (status_value or "").upper(),
        "plan_expires_at": org.date_expiration_abonnement.isoformat() if org.date_expiration_abonnement else None,
        "source": "saas" if saas_status else "local",
    }


@router.get(
    "/config",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def get_billing_config(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Fallback local : lire le champ billing_config JSONB stocké sur l'organisation.
    local_config: dict = {}
    try:
        res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
        org = res.scalar_one_or_none()
        if org is not None and org.billing_config and isinstance(org.billing_config, dict):
            local_config = org.billing_config
    except Exception:
        pass

    # Contact de support par défaut si non configuré localement
    if not local_config.get("support_contact"):
        local_config["support_contact"] = "kidikala@onerdc.com"

    if not _is_saas_configured():
        # Console SaaS absente : on retourne la config locale sans erreur.
        return {
            "configured": False,
            "tenant_id": str(tenant_id),
            **local_config,
        }

    url = _build_saas_url(
        (settings.saas_billing_config_path or "/tenants/{tenant_id}/billing-config").format(
            tenant_id=tenant_id
        )
    )
    if not url:
        return {"configured": False, "tenant_id": str(tenant_id), **local_config}

    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            data = response.json() or {}
            data["configured"] = True
            return data
    except httpx.TimeoutException:
        # Console SaaS injoignable → fallback local sans erreur 502
        return {"configured": False, "tenant_id": str(tenant_id), "saas_error": "timeout", **local_config}
    except httpx.HTTPError as exc:
        return {"configured": False, "tenant_id": str(tenant_id), "saas_error": str(exc), **local_config}


@router.get(
    "/checkout-session",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def create_checkout_session(
    tenant_id: int = Depends(get_current_tenant_id),
    user=Depends(get_current_user),
) -> dict:
    if not settings.saas_internal_key or not settings.saas_console_base_url:
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    url = _build_saas_url(settings.saas_checkout_session_path or "/payments/create-session")
    if not url:
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    # Fetch latest pricing from SaaS config (source de vérité).
    amount: float | None = None
    currency: str | None = None
    try:
        config_url = _build_saas_url((settings.saas_billing_config_path or "/tenants/{tenant_id}/billing-config").format(tenant_id=tenant_id))
        if config_url:
            async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
                config_res = await client.get(config_url, headers={"X-API-KEY": settings.saas_internal_key})
                config_res.raise_for_status()
                config_payload = config_res.json() if config_res else {}
                plan = (config_payload or {}).get("plan") or {}
                if isinstance(plan, dict):
                    amount = _parse_amount(plan.get("price"))
                    currency = plan.get("currency")
    except httpx.HTTPError:
        amount = None

    if amount is None:
        raise HTTPException(status_code=503, detail="Montant indisponible.")

    success_url = settings.saas_checkout_success_url or "http://localhost:5173/settings?status=success"
    cancel_url = settings.saas_checkout_cancel_url or "http://localhost:5173/settings?status=cancel"

    body = {
        "tenant_id": tenant_id,
        "amount": amount,
        "currency": currency or "USD",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "requested_by": str(user.id),
    }
    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.post(url, json=body, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Erreur console SaaS: {exc}") from exc


@router.post(
    "/initiate-payment",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def initiate_tenant_payment(
    payload: BillingPaymentRequest,
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not settings.saas_internal_key or not settings.saas_console_base_url:
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    url = _build_saas_url(settings.saas_payments_path or "/payments/trigger")
    if not url:
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    body = {
        "tenant_id": tenant_id,
        "phone": payload.phone,
        "provider": payload.provider,
        "amount": payload.amount,
        "requested_by": str(user.id),
    }
    try:
        db.add(
            PaymentLog(
                organisation_id=tenant_id,
                phone_number=payload.phone,
                amount=payload.amount,
                provider=payload.provider or "mobile_money",
                status="INITIATED",
                raw_response={"tenant_id": tenant_id},
            )
        )
        await db.commit()
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.post(url, json=body, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            data = response.json()
        db.add(
            PaymentLog(
                organisation_id=tenant_id,
                phone_number=payload.phone,
                amount=payload.amount,
                provider=payload.provider or "mobile_money",
                status="PUSH_SENT",
                raw_response=data,
            )
        )
        await db.commit()
        return data
    except httpx.HTTPError as exc:
        db.add(
            PaymentLog(
                organisation_id=tenant_id,
                phone_number=payload.phone,
                amount=payload.amount,
                provider=payload.provider or "mobile_money",
                status="ERROR",
                raw_response={"error": str(exc)},
            )
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Erreur console SaaS: {exc}") from exc
    except Exception as exc:
        db.add(
            PaymentLog(
                organisation_id=tenant_id,
                phone_number=payload.phone,
                amount=payload.amount,
                provider=payload.provider or "mobile_money",
                status="ERROR",
                raw_response={"error": str(exc)},
            )
        )
        await db.commit()
        raise


@router.get(
    "/summary",
    response_model=BillingSummaryOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def get_billing_summary(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BillingSummaryOut:
    res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    plan_expires = org.date_expiration_abonnement
    plan_expires_str = plan_expires.isoformat() if plan_expires else None
    summary_source = "local"
    summary_override: dict = {}

    if _is_saas_configured():
        url = _build_saas_url((settings.saas_billing_summary_path or "/tenants/{tenant_id}/billing-summary").format(tenant_id=tenant_id))
        if url:
            try:
                async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
                    response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
                    response.raise_for_status()
                    summary_override = _normalize_summary(response.json())
                    if summary_override:
                        summary_source = "saas"
            except httpx.HTTPError:
                summary_override = {}

    return BillingSummaryOut(
        plan_type=summary_override.get("plan_type") or org.plan_type,
        plan_status=summary_override.get("plan_status") or org.status_abonnement,
        plan_expires_at=summary_override.get("plan_expires_at") or plan_expires_str,
        renewal_date=summary_override.get("renewal_date") or plan_expires_str,
        currency=summary_override.get("currency") or org.devise_preferee,
        plan_price=summary_override.get("plan_price"),
        billing_source=summary_source,
        billing_portal_url=summary_override.get("billing_portal_url") or settings.saas_billing_portal_url,
    )


@router.get(
    "/invoices",
    response_model=BillingInvoiceListOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def list_billing_invoices(
    tenant_id: int = Depends(get_current_tenant_id),
) -> BillingInvoiceListOut:
    if not _is_saas_configured():
        return BillingInvoiceListOut(items=[], source="local", configured=False)

    base_url = _saas_base_url()
    if not base_url:
        return BillingInvoiceListOut(items=[], source="local", configured=False)

    url = f"{base_url}/tenants/{tenant_id}/invoices"
    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Erreur console SaaS: {exc}") from exc

    invoices = _normalize_invoices(payload)
    return BillingInvoiceListOut(items=invoices, source="saas", configured=True)


@router.get(
    "/payment-methods",
    response_model=BillingPaymentMethodListOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def list_payment_methods(
    tenant_id: int = Depends(get_current_tenant_id),
) -> BillingPaymentMethodListOut:
    if not _is_saas_configured():
        return BillingPaymentMethodListOut(items=[], source="local", configured=False)

    base_url = _saas_base_url()
    if not base_url:
        return BillingPaymentMethodListOut(items=[], source="local", configured=False)

    url = f"{base_url}/tenants/{tenant_id}/payment-methods"
    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Erreur console SaaS: {exc}") from exc

    methods = _normalize_payment_methods(payload)
    return BillingPaymentMethodListOut(items=methods, source="saas", configured=True)


@router.get(
    "/invoices/{invoice_id}/pdf",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def download_invoice_pdf(
    invoice_id: str,
    tenant_id: int = Depends(get_current_tenant_id),
) -> Response:
    if not _is_saas_configured():
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    base_url = _saas_base_url()
    if not base_url:
        raise HTTPException(status_code=503, detail="Console SaaS non configurée.")

    url = f"{base_url}/tenants/{tenant_id}/invoices/{invoice_id}/pdf"
    try:
        async with httpx.AsyncClient(timeout=settings.saas_console_timeout) as client:
            response = await client.get(url, headers={"X-API-KEY": settings.saas_internal_key})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Erreur console SaaS: {exc}") from exc

    content_type = response.headers.get("content-type", "application/pdf")
    filename = f"facture-{invoice_id}.pdf"
    return Response(
        content=response.content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/refresh-status", include_in_schema=False)
async def refresh_tenant_status(
    x_internal_key: str | None = Header(None, alias="X-Internal-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    if not settings.saas_internal_key or x_internal_key != settings.saas_internal_key:
        raise HTTPException(status_code=403, detail="Unauthorized")

    tenant_id: int | None = None
    if x_tenant_id and x_tenant_id.isdigit():
        tenant_id = int(x_tenant_id)

    await deps.clear_saas_status_cache(tenant_id)
    return {"status": "cache_cleared", "tenant_id": tenant_id}


@router.get(
    "/payment-logs",
    response_model=PaymentLogListOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def list_payment_logs(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    provider: str | None = None,
    phone: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaymentLogListOut:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    query = select(PaymentLog).where(PaymentLog.organisation_id == tenant_id)
    count_query = select(func.count()).select_from(PaymentLog).where(PaymentLog.organisation_id == tenant_id)

    if status:
        query = query.where(PaymentLog.status == status)
        count_query = count_query.where(PaymentLog.status == status)
    if provider:
        query = query.where(PaymentLog.provider == provider)
        count_query = count_query.where(PaymentLog.provider == provider)
    if phone:
        query = query.where(PaymentLog.phone_number.ilike(f"%{phone}%"))
        count_query = count_query.where(PaymentLog.phone_number.ilike(f"%{phone}%"))

    query = query.order_by(PaymentLog.created_at.desc()).limit(limit).offset(offset)

    res = await db.execute(query)
    items = res.scalars().all()
    total_res = await db.execute(count_query)
    total = int(total_res.scalar() or 0)

    return PaymentLogListOut(
        items=[
            PaymentLogOut(
                id=item.id,
                organisation_id=item.organisation_id,
                phone_number=item.phone_number,
                amount=item.amount,
                provider=item.provider,
                status=item.status,
                raw_response=item.raw_response,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
    )


@router.get(
    "/payment-logs/export",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def export_payment_logs(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    provider: str | None = None,
    phone: str | None = None,
) -> Response:
    query = select(PaymentLog).where(PaymentLog.organisation_id == tenant_id)
    if status:
        query = query.where(PaymentLog.status == status)
    if provider:
        query = query.where(PaymentLog.provider == provider)
    if phone:
        query = query.where(PaymentLog.phone_number.ilike(f"%{phone}%"))

    query = query.order_by(PaymentLog.created_at.desc())
    res = await db.execute(query)
    items = res.scalars().all()

    header = "id,organisation_id,phone_number,amount,provider,status,created_at\n"
    lines = [header]
    for item in items:
        amount = f"{item.amount:.2f}" if item.amount is not None else ""
        phone_val = (item.phone_number or "").replace(",", " ")
        provider_val = (item.provider or "").replace(",", " ")
        status_val = (item.status or "").replace(",", " ")
        created_val = item.created_at.isoformat() if item.created_at else ""
        lines.append(
            f"{item.id},{item.organisation_id},{phone_val},{amount},{provider_val},{status_val},{created_val}\n"
        )

    content = "".join(lines)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="payment_logs.csv"'},
    )
