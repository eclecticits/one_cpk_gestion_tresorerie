from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class OrganisationOut(BaseModel):
    id: int
    uuid: str
    nom: str
    slug: str
    logo_url: str | None = None
    email_contact: str | None = None
    telephone: str | None = None
    adresse: str | None = None
    devise_preferee: str
    taux_change_interne: float
    plan_type: str
    status_abonnement: str
    date_expiration_abonnement: datetime | None = None
    limite_utilisateurs: int


class OrganisationPublicOut(BaseModel):
    nom: str
    slug: str
    logo_url: str | None = None


class OrganisationUpdate(BaseModel):
    nom: str | None = None
    logo_url: str | None = None
    email_contact: str | None = None
    telephone: str | None = None
    adresse: str | None = None
    devise_preferee: str | None = Field(default=None, min_length=3, max_length=3)
    taux_change_interne: float | None = None
