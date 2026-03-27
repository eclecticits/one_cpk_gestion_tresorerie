from __future__ import annotations

from pydantic import BaseModel


class BillingSummaryOut(BaseModel):
    plan_type: str | None = None
    plan_status: str | None = None
    plan_expires_at: str | None = None
    renewal_date: str | None = None
    currency: str | None = None
    plan_price: float | None = None
    billing_source: str
    billing_portal_url: str | None = None


class BillingInvoiceOut(BaseModel):
    id: str
    number: str | None = None
    date: str | None = None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None
    pdf_available: bool = False


class BillingInvoiceListOut(BaseModel):
    items: list[BillingInvoiceOut]
    source: str
    configured: bool


class BillingPaymentMethodOut(BaseModel):
    id: str
    label: str
    method_type: str | None = None
    last4: str | None = None
    status: str | None = None
    is_default: bool = False


class BillingPaymentMethodListOut(BaseModel):
    items: list[BillingPaymentMethodOut]
    source: str
    configured: bool
