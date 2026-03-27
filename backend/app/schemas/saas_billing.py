from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BillingPlanConfig(BaseModel):
    name: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    interval: str | None = None


class BillingBankConfig(BaseModel):
    enabled: bool = True
    bank_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    swift_code: str | None = None


class BillingMobileMoneyConfig(BaseModel):
    enabled: bool = True
    provider: str | None = None
    merchant_number: str | None = None
    instructions: str | None = None


class BillingPaymentMethodsConfig(BaseModel):
    bank: BillingBankConfig | None = None
    mobile_money: BillingMobileMoneyConfig | None = None


class BillingConfigOut(BaseModel):
    tenant_id: str | None = None
    plan: BillingPlanConfig | None = None
    payment_methods: BillingPaymentMethodsConfig | None = None
    support_contact: str | None = None
    billing_portal_url: str | None = None
    raw: dict[str, Any] | None = None


class BillingConfigUpdate(BaseModel):
    plan: BillingPlanConfig | None = None
    payment_methods: BillingPaymentMethodsConfig | None = None
    support_contact: str | None = None
    billing_portal_url: str | None = None


class BillingConfigApplyRequest(BaseModel):
    overwrite: bool = False
