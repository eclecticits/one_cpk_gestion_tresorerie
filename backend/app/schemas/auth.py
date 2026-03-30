from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    must_change_password: bool = False
    role: str | None = None
    requires_otp: bool = False
    otp_required_reason: str | None = None
    organisation_id: int | None = None
    organisation_uuid: str | None = None
    organisation_slug: str | None = None
    organisation_name: str | None = None
    plan_status: str | None = None
    plan_type: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False
    role: str
    organisation_id: int | None = None
    organisation_uuid: str | None = None
    organisation_slug: str | None = None
    plan_status: str | None = None
    plan_type: str | None = None


class ChangePasswordRequest(BaseModel):
    # If must_change_password is true, current_password may be omitted.
    current_password: str | None = None
    new_password: str = Field(min_length=8)


class BootstrapAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nom: str
    prenom: str
    bootstrap_password: str


class MeResponse(BaseModel):
    id: UUID
    email: EmailStr
    nom: str | None = None
    prenom: str | None = None
    role: str
    service_id: int | None = None
    service_ids: list[int] = []
    active: bool
    must_change_password: bool
    is_email_verified: bool
    is_first_login: bool
    created_at: str | None = None
    organisation_id: int | None = None
    organisation_uuid: str | None = None
    organisation_slug: str | None = None
    organisation_name: str | None = None
    plan_status: str | None = None
    plan_type: str | None = None
    plan_expires_at: str | None = None
    user_limit: int | None = None


class RequestOtpRequest(BaseModel):
    email: EmailStr


class ConfirmPasswordUpdate(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8)
    otp_code: str = Field(min_length=6, max_length=6)


class RequestPasswordChange(BaseModel):
    current_password: str | None = None


class TenantDiscoveryItem(BaseModel):
    id: int
    name: str
    slug: str
