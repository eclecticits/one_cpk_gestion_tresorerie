"""Schémas du paramétrage et de la reprise des créances."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.base import DecimalBaseModel


class CreancesParametresOut(BaseModel):
    actif: bool
    # Faux si la comptabilité n'est pas en mode automatique : le réglage est
    # alors enregistré mais sans effet.
    mode_automatique: bool
    compte_racine_id: int | None
    compte_racine_numero: str | None
    compte_racine_libelle: str | None
    # Racine des clients non membres ; vide = la même.
    compte_racine_clients_id: int | None
    comptes_tiers: int
    # Vocabulaire de l'organisation : « tiers », « membre », « adhérent », « client »…
    libelle_tiers: str
    libelle_journal: str
    notes_sans_creance: int


class CreancesParametresIn(BaseModel):
    actif: bool
    compte_racine_id: int | None = None
    compte_racine_clients_id: int | None = None
    libelle_tiers: str | None = Field(default=None, max_length=40)
    libelle_journal: str | None = Field(default=None, max_length=100)


class RepriseCreancesIn(BaseModel):
    # Simulation par défaut : on voit ce qui serait constaté avant de l'écrire.
    simulation: bool = True


class EchecRepriseOut(BaseModel):
    numero: str
    motif: str


class RepriseCreancesOut(DecimalBaseModel):
    simulation: bool
    constatees: int
    montant: Decimal
    deja_reglees_en_partie: int
    echecs: list[EchecRepriseOut]
