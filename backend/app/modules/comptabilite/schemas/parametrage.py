"""Schémas de l'écran de paramétrage des mappings comptables.

Le moteur de génération résout chaque compte via ces mappings et échoue de
façon bloquante quand l'un d'eux manque (décision actée). Cet écran est donc
le point de contrôle avant toute mise en service réelle du module.
"""

from __future__ import annotations

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


class MappingsDefautOut(BaseModel):
    postes_mappes: int
    comptes_bancaires_mappes: int
    rubriques_mappees: int
    compte_caisse_defaut_id: int | None
