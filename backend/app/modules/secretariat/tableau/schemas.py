from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class TableauImportOut(BaseModel):
    id: int
    exercice: str
    file_name: str
    status: str
    total_rows: int
    imported_rows: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TableauDossierOut(BaseModel):
    id: int
    import_id: int
    exercice: str
    numero_ordre: str | None
    nom: str
    prenom: str | None
    categorie: str
    statut_membre: str | None
    cotisation_montant: float | None
    cotisation_payee: bool | None
    heures_forco: float | None
    assurance: bool | None
    chiffre_affaires: bool | None = None
    sexe: str | None = None
    date_naissance: date | None = None
    age: int | None = None
    nif: str | None = None
    anciennete: str | None = None
    conclusion: str | None = None
    conclusion_motif: str | None = None
    email: str | None
    telephone: str | None
    cabinet: str | None
    statut_dossier: str
    anomalie_detectee: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TableauAnalyseOut(BaseModel):
    id: int
    import_id: int
    exercice: str
    status: str
    total_dossiers: int
    dossiers_complets: int
    dossiers_incomplets: int
    anomalies_count: int
    doublons_count: int
    cotisations_non_payees: int
    heures_forco_insuffisantes: int
    assurances_manquantes: int
    observations_ia: str | None
    stats_json: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TableauAnomalieOut(BaseModel):
    id: int
    dossier_id: int
    type_anomalie: str
    gravite: str
    description: str
    champ_concerne: str | None
    valeur_trouvee: str | None
    valeur_attendue: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TableauDecisionOut(BaseModel):
    id: int
    dossier_id: int
    type_decision: str
    decision: str
    motif: str | None
    observations: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TableauDecisionCreate(BaseModel):
    dossier_id: int
    type_decision: str
    decision: str
    motif: str | None = None
    observations: str | None = None


class TableauReportOut(BaseModel):
    id: int
    exercice: str
    type_rapport: str
    titre: str
    contenu: str | None
    format_sortie: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TableauReportCreate(BaseModel):
    import_id: int
    exercice: str
    type_rapport: str = Field(default="analyse")
    titre: str
    instructions: str | None = None


class TableauStatsOut(BaseModel):
    dossiers_importes: int
    dossiers_analyses: int
    dossiers_incomplets: int
    anomalies_detectees: int
    decisions_a_valider: int
    imports_count: int
    last_exercice: str | None


class TableauComparisonOut(BaseModel):
    exercice_a: str
    exercice_b: str
    dossiers_en_commun: int
    nouveaux_dans_b: int
    absents_de_b: int
    changements_categorie: int
    details: list[dict[str, Any]]


class TableauAnalyseRequest(BaseModel):
    import_id: int


class TableauComparisonRequest(BaseModel):
    exercice_a: str
    exercice_b: str


class TableauPVCreate(BaseModel):
    import_id: int
    exercice: str
    instructions: str | None = None


class TableauImportResult(BaseModel):
    """Réponse standardisée d'un import (aligné sur le procédé budget)."""
    success: bool
    import_id: int | None = None
    exercice: str
    file_name: str
    imported: int
    updated: int = 0
    skipped: int = 0
    total_lignes: int = 0
    errors: list[dict] = Field(default_factory=list)
    message: str


class TableauReglagesIn(BaseModel):
    """Réglages de délibération, configurables dans l'application."""
    heures_formation_min: float | None = None
    age_seuil: int | None = None
    age_action: str | None = None            # "a_deliberer" | "inscrit" | "aucune"
    age_conclusion_label: str | None = None  # libellé si age_action == "inscrit"
    nouveau_anciennete_ans: int | None = None
    exempter_nouveaux: bool | None = None
