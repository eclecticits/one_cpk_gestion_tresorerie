from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import DecimalBaseModel


class BanqueBase(BaseModel):
    nom: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    is_active: bool = True


class BanqueCreate(BanqueBase):
    pass


class BanqueUpdate(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class BanqueOut(BanqueBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class CompteBancaireBase(DecimalBaseModel):
    banque_id: int | None = None
    intitule: str = Field(min_length=1, max_length=200)
    numero_compte: str = Field(min_length=1, max_length=50)
    rib: str | None = Field(default=None, max_length=50)
    identifiant_client: str | None = Field(default=None, max_length=50)
    code_swift_bic: str | None = Field(default=None, max_length=20)
    compte_comptable_associe: str | None = Field(default=None, max_length=50)
    journal_comptable_associe: str | None = Field(default=None, max_length=50)
    date_ouverture: date | None = None
    devise: Literal["USD", "CDF"] = "USD"
    solde_initial: Decimal = Decimal("0")
    is_active: bool = True
    is_principal: bool = False
    agence_bancaire: str | None = Field(default=None, max_length=150)
    observations: str | None = None
    account_type: Literal["BANK", "CASH"] = "BANK"

    @field_validator(
        "intitule",
        "numero_compte",
        "rib",
        "identifiant_client",
        "code_swift_bic",
        "compte_comptable_associe",
        "journal_comptable_associe",
        "agence_bancaire",
        "observations",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = " ".join(value.strip().split())
            return cleaned or None
        return value

    @field_validator("code_swift_bic")
    @classmethod
    def _upper_swift(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("solde_initial")
    @classmethod
    def _nonnegative_solde_initial(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Le solde initial doit être supérieur ou égal à zéro.")
        return value


class CompteBancaireCreate(CompteBancaireBase):
    model_config = ConfigDict(extra="forbid")


class CompteBancaireUpdate(DecimalBaseModel):
    model_config = ConfigDict(extra="forbid")

    banque_id: int | None = None
    intitule: str | None = Field(default=None, min_length=1, max_length=200)
    numero_compte: str | None = Field(default=None, min_length=1, max_length=50)
    rib: str | None = Field(default=None, max_length=50)
    identifiant_client: str | None = Field(default=None, max_length=50)
    code_swift_bic: str | None = Field(default=None, max_length=20)
    compte_comptable_associe: str | None = Field(default=None, max_length=50)
    journal_comptable_associe: str | None = Field(default=None, max_length=50)
    date_ouverture: date | None = None
    devise: Literal["USD", "CDF"] | None = None
    solde_initial: Decimal | None = None
    is_active: bool | None = None
    is_principal: bool | None = None
    agence_bancaire: str | None = Field(default=None, max_length=150)
    observations: str | None = None
    account_type: Literal["BANK", "CASH"] | None = None

    @field_validator(
        "intitule",
        "numero_compte",
        "rib",
        "identifiant_client",
        "code_swift_bic",
        "compte_comptable_associe",
        "journal_comptable_associe",
        "agence_bancaire",
        "observations",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = " ".join(value.strip().split())
            return cleaned or None
        return value

    @field_validator("code_swift_bic")
    @classmethod
    def _upper_swift(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("solde_initial")
    @classmethod
    def _nonnegative_solde_initial(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Le solde initial doit être supérieur ou égal à zéro.")
        return value


class CompteBancaireOut(CompteBancaireBase):
    id: int
    solde_actuel: Decimal
    banque: BanqueOut | None = None

    model_config = ConfigDict(from_attributes=True)
