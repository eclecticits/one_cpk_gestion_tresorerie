"""Schémas de l'import du plan comptable depuis Excel.

Le fichier est lu côté navigateur (comme les autres imports Excel de
l'application) : le serveur reçoit des lignes déjà extraites, les rapproche du
plan en base et rend, ligne par ligne, ce qu'il en ferait.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModeImportPlan = Literal["add_only", "update_existing"]
ActionLignePlan = Literal["CREER", "METTRE_A_JOUR", "INCHANGE", "IGNORE", "ERREUR"]


class LignePlanIn(BaseModel):
    """Une ligne du fichier. Seuls le numéro et le libellé sont obligatoires ;
    une colonne absente du fichier arrive à None et n'écrase rien."""

    ligne: int = Field(ge=1, description="Numéro de ligne dans la feuille Excel, pour le rapport.")
    numero: str | None = None
    libelle: str | None = None
    nature: str | None = None
    sens: str | None = None
    parent: str | None = None
    collectif: str | None = None
    auxiliaire: str | None = None
    actif: str | None = None


class ImportPlanIn(BaseModel):
    lignes: list[LignePlanIn] = Field(max_length=5000)
    mode: ModeImportPlan = "update_existing"
    # Simulation par défaut : rien n'est écrit tant que l'appelant ne le demande pas.
    simulation: bool = True
    nom_fichier: str | None = Field(default=None, max_length=255)


class LignePlanOut(BaseModel):
    ligne: int
    numero: str
    libelle: str
    action: ActionLignePlan
    nature: str | None = None
    sens_normal: str | None = None
    parent_numero: str | None = None
    is_collectif: bool | None = None
    is_auxiliaire: bool | None = None
    actif: bool | None = None
    # Champs que le fichier ne donnait pas et que l'import a déduits du numéro.
    deduits: list[str] = []
    # Champs qui changent sur un compte existant.
    changements: list[str] = []
    message: str | None = None


class ImportPlanOut(BaseModel):
    simulation: bool
    enregistre: bool
    total_lignes: int
    crees: int
    mis_a_jour: int
    inchanges: int
    ignores: int
    erreurs: int
    lignes: list[LignePlanOut]
    message: str
