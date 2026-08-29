from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import DecimalBaseModel


SourceDestType = Literal["CAISSE", "BANQUE"]


class TransfertInterneBase(DecimalBaseModel):
    source_type: SourceDestType
    source_id: int | None = None
    destination_type: SourceDestType
    destination_id: int | None = None
    montant: Decimal = Field(gt=0)
    devise: Literal["USD", "CDF"] = "USD"
    reference: str | None = None
    date_transfert: datetime | None = None

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value, info):
        source_type = info.data.get("source_type")
        if source_type == "BANQUE" and value is None:
            raise ValueError("source_id requis pour une source BANQUE")
        if source_type == "CAISSE" and value is not None:
            raise ValueError("source_id interdit pour une source CAISSE")
        return value

    @field_validator("destination_id")
    @classmethod
    def validate_destination_id(cls, value, info):
        destination_type = info.data.get("destination_type")
        if destination_type == "BANQUE" and value is None:
            raise ValueError("destination_id requis pour une destination BANQUE")
        if destination_type == "CAISSE" and value is not None:
            raise ValueError("destination_id interdit pour une destination CAISSE")
        return value


class TransfertInterneCreate(TransfertInterneBase):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class TransfertContrepassationCreate(DecimalBaseModel):
    """Une contre-passation est une décision : elle exige un motif écrit."""

    motif: str = Field(min_length=3, max_length=500)


class TransfertInterneOut(TransfertInterneBase):
    id: int
    execute_par: str | None = None
    #: ``EXECUTE`` ou ``CONTREPASSE``. Le statut est de l'affichage : un
    #: transfert contre-passé reste compté, sa correction étant portée par une
    #: ligne inverse distincte (cf. modèle `TransfertInterne`).
    statut: str
    idempotency_key: str | None = None
    #: Renseignés sur le transfert d'origine une fois corrigé.
    contrepasse_le: datetime | None = None
    contrepasse_par: str | None = None
    motif_contrepassation: str | None = None
    #: Renseigné sur la ligne inverse, pointe vers le transfert corrigé.
    transfert_origine_id: int | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})
