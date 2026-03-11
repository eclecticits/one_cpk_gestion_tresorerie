from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    numero_compte: str = Field(min_length=1, max_length=120)
    devise: Literal["USD", "CDF"] = "USD"
    solde_initial: Decimal = Decimal("0")
    solde_actuel: Decimal = Decimal("0")
    is_active: bool = True
    account_type: Literal["BANK", "CASH"] = "BANK"


class CompteBancaireCreate(CompteBancaireBase):
    pass


class CompteBancaireUpdate(DecimalBaseModel):
    banque_id: int | None = None
    intitule: str | None = Field(default=None, min_length=1, max_length=200)
    numero_compte: str | None = Field(default=None, min_length=1, max_length=120)
    devise: Literal["USD", "CDF"] | None = None
    solde_initial: Decimal | None = None
    solde_actuel: Decimal | None = None
    is_active: bool | None = None
    account_type: Literal["BANK", "CASH"] | None = None


class CompteBancaireOut(CompteBancaireBase):
    id: int
    banque: BanqueOut | None = None

    model_config = ConfigDict(from_attributes=True)
