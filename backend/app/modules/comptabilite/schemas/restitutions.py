"""Schémas des restitutions comptables (Grand Livre, Journal, Balance)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.base import DecimalBaseModel


class LigneBalanceOut(DecimalBaseModel):
    compte_id: int
    compte_numero: str
    compte_libelle: str
    nature: str
    total_debit: Decimal
    total_credit: Decimal
    solde_debiteur: Decimal
    solde_crediteur: Decimal


class BalanceOut(DecimalBaseModel):
    exercice_id: int
    devise_tenue: str
    date_debut: date | None
    date_fin: date | None
    inclure_brouillons: bool
    lignes: list[LigneBalanceOut]
    total_debit: Decimal
    total_credit: Decimal
    total_solde_debiteur: Decimal
    total_solde_crediteur: Decimal
    # Faux si les données ont été altérées hors du service : l'écran doit le
    # signaler plutôt que d'afficher un état muet et inexact.
    equilibree: bool


class MouvementGrandLivreOut(DecimalBaseModel):
    ligne_id: UUID
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    journal_code: str
    libelle: str | None
    reference_piece: str | None
    debit: Decimal
    credit: Decimal
    statut: str
    solde_cumule: Decimal


class GrandLivreOut(DecimalBaseModel):
    exercice_id: int
    devise_tenue: str
    compte_id: int
    compte_numero: str
    compte_libelle: str
    date_debut: date | None
    date_fin: date | None
    inclure_brouillons: bool
    solde_anterieur: Decimal
    mouvements: list[MouvementGrandLivreOut]
    total_debit_page: Decimal
    total_credit_page: Decimal
    solde_final_page: Decimal
    curseur_suivant: str | None


class EcritureJournalOut(DecimalBaseModel):
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    libelle: str
    statut: str
    total_debit: Decimal
    total_credit: Decimal


class LivreJournalOut(DecimalBaseModel):
    exercice_id: int
    devise_tenue: str
    journal_id: int
    journal_code: str
    journal_libelle: str
    date_debut: date | None
    date_fin: date | None
    inclure_brouillons: bool
    ecritures: list[EcritureJournalOut]
    total_debit: Decimal
    total_credit: Decimal


class ExerciceCourantOut(BaseModel):
    """Exercice retenu par défaut par les écrans de restitution."""

    exercice_id: int
    code: str
    devise_tenue: str
