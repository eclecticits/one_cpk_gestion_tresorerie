from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class TenantSignupCreate(BaseModel):
    organisation_name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=100)
    admin_email: EmailStr
    admin_phone: str | None = None
    plan_id: int
    billing_months: int = Field(default=1)


class TenantSignupResponse(BaseModel):
    id: str
    reference: str
    status: str
    plan_id: int
    organisation_id: int | None = None


class TenantCheckoutRequest(BaseModel):
    reference: str
    success_url: str | None = None
    cancel_url: str | None = None


class InvitationCheckRequest(BaseModel):
    email: EmailStr


class InvitationCheckResponse(BaseModel):
    organisation_id: int
    organisation_name: str
    slug: str
    plan_id: int
    plan_name: str
    monthly_price_usd: str
    discounts: dict | None = None


class TenantCheckoutResponse(BaseModel):
    checkout_url: str
    transaction_id: str | None = None
    status: str


class PlanOut(BaseModel):
    id: int
    name: str
    monthly_price_usd: str
    features: dict | None = None
    discounts: dict | None = None
