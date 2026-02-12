from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DenominationBase(BaseModel):
    devise: str
    valeur: float
    label: str
    est_actif: bool = True
    ordre: int = 0


class DenominationCreate(DenominationBase):
    pass


class DenominationUpdate(BaseModel):
    devise: str | None = None
    valeur: float | None = None
    label: str | None = None
    est_actif: bool | None = None
    ordre: int | None = None


class DenominationOut(DenominationBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
