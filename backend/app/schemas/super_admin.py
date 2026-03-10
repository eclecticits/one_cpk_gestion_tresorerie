from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class SuperAdminOrganisationCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100)
    plan_type: str | None = None
    status_abonnement: str | None = None
    trial_days: int | None = Field(default=30, ge=0, le=365)
    limite_utilisateurs: int | None = Field(default=None, ge=1, le=10000)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)


class SuperAdminOrganisationUpdate(BaseModel):
    plan_type: str | None = None
    status_abonnement: str | None = None
    date_expiration_abonnement: datetime | None = None
    limite_utilisateurs: int | None = Field(default=None, ge=1, le=10000)
    is_active: bool | None = None


class SuperAdminOrganisationOut(BaseModel):
    id: int
    uuid: str
    nom: str
    slug: str
    plan_type: str
    status_abonnement: str
    date_expiration_abonnement: datetime | None = None
    limite_utilisateurs: int
    is_active: bool
    user_count: int
    created_at: datetime
