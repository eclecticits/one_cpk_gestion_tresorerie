"""Schémas du lettrage des comptes de tiers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import DecimalBaseModel


class CompteALettrerOut(DecimalBaseModel):
    compte_id: int
    numero: str
    libelle: str
    lignes_non_lettrees: int
    debit_non_lettre: Decimal
    credit_non_lettre: Decimal
    solde_non_lettre: Decimal


class LigneLettrableOut(DecimalBaseModel):
    ligne_id: UUID
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    journal_code: str
    libelle: str | None
    reference_piece: str | None
    debit: Decimal
    credit: Decimal
    compte_auxiliaire_id: int | None
    lettrage: str | None
    date_lettrage: date | None


class LignesCompteOut(DecimalBaseModel):
    compte_id: int
    compte_numero: str
    compte_libelle: str
    lignes: list[LigneLettrableOut]
    debit_non_lettre: Decimal
    credit_non_lettre: Decimal
    solde_non_lettre: Decimal


class LettrerIn(BaseModel):
    ligne_ids: list[UUID] = Field(min_length=2, max_length=500)


class LettrageOut(BaseModel):
    code: str
    lignes: int


class DelettrerIn(BaseModel):
    compte_id: int
    code: str = Field(min_length=1, max_length=20)


class LettrageAutoIn(BaseModel):
    # Un compte précis, ou tous les comptes lettrables.
    compte_id: int | None = None
    # Simulation par défaut : on montre ce qui serait lettré avant de le faire.
    simulation: bool = True


class GroupeProposeOut(DecimalBaseModel):
    compte_id: int
    compte_numero: str
    motif: str
    montant: Decimal
    code: str | None
    lignes: list[LigneLettrableOut]


class LettrageAutoOut(DecimalBaseModel):
    simulation: bool
    comptes_examines: int
    groupes_lettres: int
    lignes_lettrees: int
    groupes: list[GroupeProposeOut]


class CompteLettrableIn(BaseModel):
    lettrable: bool


class LigneBalanceAgeeOut(DecimalBaseModel):
    compte_id: int
    compte_numero: str
    compte_libelle: str
    lignes: int
    plus_ancienne: date | None
    non_echu: Decimal
    j0_30: Decimal
    j31_60: Decimal
    j61_90: Decimal
    plus_90: Decimal
    solde: Decimal


class BalanceAgeeOut(DecimalBaseModel):
    date_arret: date
    sens: str
    lignes: list[LigneBalanceAgeeOut]
    non_echu: Decimal
    j0_30: Decimal
    j31_60: Decimal
    j61_90: Decimal
    plus_90: Decimal
    total: Decimal
