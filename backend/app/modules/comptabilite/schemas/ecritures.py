"""Schémas API — chemin minimal viable (saisie, validation, consultation).

Pas encore de schémas dédiés au paramétrage du référentiel (création de
comptes/journaux à la volée) : le Lot 1 fournit `seeder_referentiel` pour un
plan de démarrage, complété manuellement en base si besoin le temps que Lot 2
apporte un écran de paramétrage.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.base import DecimalBaseModel


class CompteOut(BaseModel):
    id: int
    numero: str
    libelle: str
    classe: str | None
    nature: str
    sens_normal: str
    is_collectif: bool
    is_auxiliaire: bool
    actif: bool
    parent_id: int | None

    class Config:
        from_attributes = True


class JournalOut(BaseModel):
    id: int
    code: str
    libelle: str
    type_journal: str
    actif: bool

    class Config:
        from_attributes = True


class ExerciceOut(BaseModel):
    id: int
    code: str
    libelle: str | None
    date_debut: date
    date_fin: date
    statut: str
    devise_tenue: str

    class Config:
        from_attributes = True


class LigneEcritureIn(BaseModel):
    compte_id: int
    compte_auxiliaire_id: int | None = None
    libelle: str | None = Field(default=None, max_length=1000)
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def _sens_exclusif(self) -> "LigneEcritureIn":
        if self.debit > 0 and self.credit > 0:
            raise ValueError("Une ligne ne peut être à la fois débitrice et créditrice.")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("Une ligne doit avoir un montant au débit ou au crédit.")
        return self


class EcritureCreateIn(BaseModel):
    journal_id: int
    exercice_id: int
    date_ecriture: date
    date_piece: date | None = None
    reference_piece: str | None = Field(default=None, max_length=100)
    libelle: str = Field(min_length=1, max_length=2000)
    devise: str = Field(default="USD", min_length=3, max_length=3)
    lignes: list[LigneEcritureIn] = Field(min_length=2)


class LigneEcritureOut(DecimalBaseModel):
    id: UUID
    compte_id: int
    compte_numero: str | None = None
    compte_libelle: str | None = None
    compte_auxiliaire_id: int | None
    libelle: str | None
    debit: Decimal
    credit: Decimal
    devise: str


class EcritureOut(DecimalBaseModel):
    id: UUID
    numero: str | None
    journal_id: int
    exercice_id: int
    date_ecriture: date
    date_piece: date | None
    reference_piece: str | None
    libelle: str
    statut: str
    devise: str
    module_origine: str | None
    est_automatique: bool
    valide_par: UUID | None
    valide_le: datetime | None
    contrepasse_ecriture_id: UUID | None
    motif_annulation: str | None
    created_at: datetime
    lignes: list[LigneEcritureOut] = []

    class Config:
        from_attributes = True


class EcritureListOut(BaseModel):
    items: list[EcritureOut]
    total: int


class ContrepasserIn(BaseModel):
    motif: str = Field(min_length=1, max_length=1000)


class SetupComptabiliteIn(BaseModel):
    type_referentiel: str = Field(pattern="^(SYSCOHADA|SYSCEBNL)$")
    exercice_date_debut: date
    exercice_date_fin: date


class SetupComptabiliteOut(BaseModel):
    societe_id: int
    referentiel_id: int
    exercice_id: int
    journaux_ids: list[int]
    nb_comptes: int
    nb_postes_etat: int = 0
    deja_existant: bool
