"""Schémas des états financiers et de la clôture d'exercice (Lot 5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.base import DecimalBaseModel


class LigneEtatOut(DecimalBaseModel):
    poste_id: int
    code: str
    libelle: str
    niveau: int
    est_total: bool
    sens_normal: str
    brut: Decimal
    amortissement: Decimal
    net: Decimal


class EtatOut(DecimalBaseModel):
    type_etat: str
    exercice_id: int
    exercice_code: str
    devise_tenue: str
    date_arrete: date
    inclure_brouillons: bool
    lignes: list[LigneEtatOut]
    total: Decimal
    # Comptes mouvementés qui n'entrent dans aucun poste : ils manqueraient
    # silencieusement à l'état si l'écran ne les signalait pas.
    comptes_non_couverts: list[str]


class ControleBilanOut(DecimalBaseModel):
    total_actif: Decimal
    total_passif: Decimal
    ecart: Decimal
    equilibre: bool
    comptes_non_couverts: list[str]


class DeterminationResultatOut(BaseModel):
    ecriture_id: str
    deja_fait: bool
    resultat: Decimal | None


class ClotureOut(BaseModel):
    deja_cloture: bool
    ecritures_cloturees: int


class ANouveauxIn(BaseModel):
    exercice_suivant_id: int


class ANouveauxOut(BaseModel):
    ecriture_id: str
    deja_fait: bool
    nb_comptes: int
