"""Schémas de l'écran de paramétrage des mappings comptables.

Le moteur de génération résout chaque compte via ces mappings et échoue de
façon bloquante quand l'un d'eux manque (décision actée). Cet écran est donc
le point de contrôle avant toute mise en service réelle du module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class MappingPosteOut(BaseModel):
    """Un poste budgétaire et le compte comptable qui lui est associé."""

    budget_poste_id: int
    code: str
    libelle: str
    type: str | None
    compte_id: int | None = None
    compte_numero: str | None = None
    compte_libelle: str | None = None


class MappingCompteBancaireOut(BaseModel):
    """Un compte de trésorerie (banque ou caisse nommée) et son compte comptable."""

    compte_bancaire_id: int
    intitule: str
    numero_compte: str | None
    account_type: str | None
    devise: str | None
    compte_id: int | None = None
    compte_numero: str | None = None
    compte_libelle: str | None = None


class MappingRubriqueOut(BaseModel):
    """Une rubrique technique (paie, produit sans poste budgétaire)."""

    code_rubrique: str
    libelle: str
    description: str
    compte_id: int | None = None
    compte_numero: str | None = None
    compte_libelle: str | None = None


class MappingsOut(BaseModel):
    budget_exercice_id: int | None
    budget_exercice_annee: int | None
    caisse_defaut_compte_id: int | None = None
    caisse_defaut_compte_numero: str | None = None
    caisse_defaut_compte_libelle: str | None = None
    postes: list[MappingPosteOut]
    comptes_bancaires: list[MappingCompteBancaireOut]
    rubriques: list[MappingRubriqueOut]
    # Nombre de résolutions qui échoueraient en l'état — l'écran doit le
    # signaler explicitement, c'est ce qui bloquerait la saisie de trésorerie.
    nb_non_mappes: int


class MappingCompteIn(BaseModel):
    compte_id: int = Field(gt=0)


class TauxChangeOut(BaseModel):
    id: int
    devise_source: str
    devise_cible: str
    taux: Decimal
    date_taux: date
    source: str | None
    # Le même taux exprimé « unités pour 1 USD », convention de la trésorerie
    # et du frontend : c'est ainsi que le comptable le lit habituellement.
    taux_inverse: Decimal


class TauxChangeIn(BaseModel):
    devise_source: str = Field(min_length=3, max_length=3)
    devise_cible: str = Field(min_length=3, max_length=3)
    taux: Decimal = Field(gt=0)
    date_taux: date
    source: str | None = Field(default=None, max_length=100)


class TauxChangeManquantOut(BaseModel):
    """Devise utilisée par l'organisation sans taux comptable pour l'exercice."""

    devise: str
    devise_tenue: str
    # Taux de trésorerie traduit en convention comptable, proposé comme point
    # de départ. `None` si la trésorerie n'en a pas non plus.
    taux_tresorerie_propose: Decimal | None


class TauxChangeListOut(BaseModel):
    devise_tenue: str
    taux: list[TauxChangeOut]
    manquants: list[TauxChangeManquantOut]


class MappingsDefautOut(BaseModel):
    postes_mappes: int
    comptes_bancaires_mappes: int
    rubriques_mappees: int
    compte_caisse_defaut_id: int | None
