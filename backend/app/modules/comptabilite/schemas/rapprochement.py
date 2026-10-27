from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import DecimalBaseModel


class PropositionRapprochementOut(DecimalBaseModel):
    operation_type: str
    operation_id: str
    date_operation: date
    reference: str | None = None
    libelle: str
    tiers: str | None = None
    debit: Decimal
    credit: Decimal
    score: Decimal


class ReleveBancaireLigneOut(DecimalBaseModel):
    id: UUID
    releve_import_id: UUID
    compte_bancaire_id: int
    numero_ligne: int
    date_operation: date
    date_valeur: date | None
    reference: str | None
    tiers: str | None
    libelle: str
    debit: Decimal
    credit: Decimal
    solde: Decimal | None
    devise: str
    est_doublon: bool
    doublon_de_id: UUID | None
    statut_rapprochement: str
    operation_type: str | None
    operation_id: str | None
    score: Decimal | None
    propositions: list[PropositionRapprochementOut] = Field(default_factory=list)
    rapproche_par: UUID | None
    rapproche_le: datetime | None


class ReleveBancaireImportOut(DecimalBaseModel):
    id: UUID
    compte_bancaire_id: int
    devise: str
    nom_fichier: str
    format: str
    statut: str
    nombre_lignes: int
    nombre_doublons: int
    nombre_propositions: int
    nombre_rapprochees: int
    importe_par: UUID | None
    created_at: datetime
    lignes: list[ReleveBancaireLigneOut] = Field(default_factory=list)


class DecisionRapprochementIn(DecimalBaseModel):
    # ANNULER remet à décider une ligne rapprochée ou ignorée par erreur.
    decision: Literal["RAPPROCHER", "IGNORER", "ANNULER"]
    operation_type: str | None = None
    operation_id: str | None = None

    @model_validator(mode="after")
    def _operation_requise(self):
        if self.decision == "RAPPROCHER" and (not self.operation_type or not self.operation_id):
            raise ValueError("L'opération proposée est obligatoire pour confirmer le rapprochement.")
        return self

