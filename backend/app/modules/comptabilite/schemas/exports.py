from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import DecimalBaseModel


JournalExport = Literal["CAISSE", "BANQUE", "TOUS"]
FormatExport = Literal["XLSX", "CSV"]


class ExportComptableFiltres(DecimalBaseModel):
    date_debut: date
    date_fin: date
    journal: JournalExport = "TOUS"
    compte_bancaire_id: int | None = None
    devise: Literal["USD", "CDF"]
    format: FormatExport = "XLSX"
    autoriser_reexport: bool = False

    @model_validator(mode="after")
    def _coherence(self):
        if self.date_fin < self.date_debut:
            raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")
        if self.compte_bancaire_id is not None and self.journal != "BANQUE":
            raise ValueError("Un compte bancaire ne peut être filtré que pour le journal BANQUE.")
        return self


class ExportAnomalieOut(DecimalBaseModel):
    code: str
    message: str
    bloquante: bool = True
    ecriture_id: UUID | None = None
    numero: str | None = None


class ExportLigneApercuOut(DecimalBaseModel):
    ecriture_id: UUID
    date: date
    piece: str
    compte: str
    libelle: str
    debit: Decimal
    credit: Decimal


class ExportComptableApercuOut(DecimalBaseModel):
    date_debut: date
    date_fin: date
    journal: JournalExport
    compte_bancaire_id: int | None = None
    devise: str
    nombre_ecritures: int
    nombre_lignes: int
    total_debit: Decimal
    total_credit: Decimal
    ecart: Decimal
    equilibre: bool
    exportable: bool
    nombre_deja_exportees: int
    lignes: list[ExportLigneApercuOut] = Field(default_factory=list)
    anomalies: list[ExportAnomalieOut] = Field(default_factory=list)


class ExportHistoriqueOut(DecimalBaseModel):
    id: UUID
    type_export: str
    format: str
    journal: str
    compte_bancaire_id: int | None
    devise: str
    date_debut: date
    date_fin: date
    nombre_ecritures: int
    nombre_lignes: int
    total_debit: Decimal
    total_credit: Decimal
    ecart: Decimal
    nom_fichier: str
    genere_par: UUID | None
    reexport_de_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}

