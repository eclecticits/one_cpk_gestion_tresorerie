from __future__ import annotations

from decimal import Decimal
from pydantic import Field
from uuid import UUID

from app.schemas.base import DecimalBaseModel
from pydantic import BaseModel


class ServiceResponsableOut(BaseModel):
    id: UUID
    nom: str | None = None
    prenom: str | None = None
    email: str | None = None


class ServiceOut(DecimalBaseModel):
    id: int
    code: str
    libelle: str
    is_active: bool
    responsable_id: UUID | None = None
    responsable: ServiceResponsableOut | None = None


class ServiceCreate(DecimalBaseModel):
    code: str = Field(min_length=2, max_length=20)
    libelle: str = Field(min_length=2, max_length=150)
    is_active: bool | None = True


class ServiceUpdate(DecimalBaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=20)
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None


class ServiceConsumptionItem(DecimalBaseModel):
    budget_poste_id: int | None = None
    code: str | None = None
    libelle: str | None = None
    total_paye: Decimal = Field(default=Decimal("0"))


class ServiceConsumption(DecimalBaseModel):
    service_id: int
    total_budget_prevu: Decimal = Field(default=Decimal("0"))
    total_depenses: Decimal = Field(default=Decimal("0"))
    total_recettes: Decimal = Field(default=Decimal("0"))
    requisitions_en_attente: int = 0
    detail_par_rubrique: list[ServiceConsumptionItem] = []


class ServiceRubriqueAssignRequest(BaseModel):
    rubrique_ids: list[int] = Field(default_factory=list)
    # Confirme la désactivation de postes déjà utilisés (usage historique). Sans
    # ce drapeau, le serveur renvoie 409 avec la liste des postes concernés.
    force: bool = False


class ServiceResponsableAssignRequest(BaseModel):
    user_id: UUID | None = None
