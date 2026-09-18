from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import DecimalBaseModel


class EncaissementTarifBase(DecimalBaseModel):
    libelle: str = Field(min_length=1, max_length=255)
    #: Prix unitaire ; vide = montant libre à la saisie.
    montant: Decimal | None = Field(default=None, gt=0)
    devise: Literal["USD", "CDF"] = "USD"
    #: Code du poste de recette ; vide = imputation libre.
    budget_poste_code: str | None = Field(default=None, max_length=50)
    is_active: bool = True
    position: int = 0


class EncaissementTarifCreate(EncaissementTarifBase):
    pass


class EncaissementTarifUpdate(DecimalBaseModel):
    libelle: str | None = Field(default=None, min_length=1, max_length=255)
    montant: Decimal | None = Field(default=None, gt=0)
    devise: Literal["USD", "CDF"] | None = None
    budget_poste_code: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    position: int | None = None


class EncaissementTarifOut(EncaissementTarifBase):
    id: int
    #: Poste de l'exercice courant auquel le code se résout aujourd'hui.
    #: Nul alors que `budget_poste_code` est renseigné : le code ne désigne
    #: aucun poste de recette actif — l'écran le signale plutôt que de laisser
    #: croire à une imputation qui n'aura pas lieu.
    budget_poste_id: int | None = None
    budget_poste_libelle: str | None = None
    #: Fenêtre de validité de CETTE version. `effet_au` nul = version en
    #: vigueur ; renseigné = version close, qui vaut encore pour les reçus
    #: qu'elle couvrait mais ne s'applique plus à une saisie d'aujourd'hui.
    effet_du: date
    effet_au: date | None = None
    #: La version que celle-ci a remplacée, s'il y en a une.
    remplace_id: int | None = None
    #: Nombre de lignes d'encaissement passées sous cette version. Ce qui rend
    #: une modification versionnable, et une suppression impossible.
    utilisations: int = 0
    created_at: datetime
    updated_at: datetime
