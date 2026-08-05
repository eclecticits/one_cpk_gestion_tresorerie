from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from uuid import UUID


CategoryType = Literal["sec", "en_cabinet", "independant", "salarie"]
ExpertImportConflictMode = Literal["add_only", "update_existing"]


class ExpertComptableBase(BaseModel):
    numero_ordre: str = Field(max_length=50)
    nom_denomination: str = Field(max_length=300)
    type_ec: str = Field(default="EC", max_length=10)
    categorie_personne: str | None = None
    statut_professionnel: str | None = None
    sexe: str | None = Field(default=None, max_length=1)
    telephone: str | None = Field(default=None, max_length=50)
    email: str | None = None
    province_attache: str | None = Field(default=None, max_length=100)
    nif: str | None = Field(default=None, max_length=50)
    cabinet_attache: str | None = Field(default=None, max_length=200)
    nom_employeur: str | None = Field(default=None, max_length=200)
    raison_sociale: str | None = Field(default=None, max_length=300)
    associe_gerant: str | None = Field(default=None, max_length=200)


class ExpertComptableCreate(ExpertComptableBase):
    pass


class ExpertComptableUpdate(BaseModel):
    """Schéma pour mise à jour partielle (PATCH)"""
    nom_denomination: str | None = None
    type_ec: str | None = None
    categorie_personne: str | None = None
    statut_professionnel: str | None = None
    sexe: str | None = None
    telephone: str | None = None
    email: str | None = None
    province_attache: str | None = None
    nif: str | None = None
    cabinet_attache: str | None = None
    nom_employeur: str | None = None
    raison_sociale: str | None = None
    associe_gerant: str | None = None
    active: bool | None = None


class ExpertComptableResponse(ExpertComptableBase):
    id: UUID
    # Réponse tolérante: éviter 500 si un email en base est invalide.
    email: str | None = None
    import_id: UUID | None = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ExpertsListResponse(BaseModel):
    items: list[ExpertComptableResponse]
    total: int
    summary: dict[str, int] = Field(default_factory=dict)


class ExpertComptableSearchParams(BaseModel):
    numero_ordre: str | None = None
    nom: str | None = None  # recherche partielle
    type_ec: str | None = None
    active: bool | None = True
    limit: int = Field(default=50, le=200)
    offset: int = 0


# Import batch (depuis Excel)
class ExpertImportRow(BaseModel):
    numero_ordre: str
    nom_denomination: str
    type_ec: str = "EC"
    categorie_personne: str | None = None
    statut_professionnel: str | None = None
    sexe: str | None = None
    telephone: str | None = None
    email: str | None = None
    province_attache: str | None = None
    nif: str | None = None
    cabinet_attache: str | None = None
    nom_employeur: str | None = None
    raison_sociale: str | None = None
    associe_gerant: str | None = None


class ExpertImportRequest(BaseModel):
    category: CategoryType
    filename: str
    rows: list[ExpertImportRow]
    file_data: list[dict] | None = None  # données brutes pour audit
    dry_run: bool = False  # si True, calcule le résultat sans rien écrire en base
    conflict_mode: ExpertImportConflictMode = "update_existing"


class ExpertImportResponse(BaseModel):
    success: bool
    imported: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    total_lignes: int = 0
    errors: list[dict] = []
    import_id: UUID | None = None
    message: str
    dry_run: bool = False


# Changement de catégorie
class CategoryChangeRequest(BaseModel):
    expert_id: UUID
    new_category: CategoryType
    reason: str | None = None
    # Données spécifiques selon catégorie
    nif: str | None = None
    cabinet_attache: str | None = None
    nom_employeur: str | None = None
    raison_sociale: str | None = None
    associe_gerant: str | None = None


class CategoryChangeResponse(BaseModel):
    id: UUID
    expert_id: UUID
    numero_ordre: str
    old_category: str | None
    new_category: str
    changed_by: UUID | None
    reason: str | None
    old_data: dict | None
    new_data: dict | None
    created_at: datetime

    class Config:
        from_attributes = True
