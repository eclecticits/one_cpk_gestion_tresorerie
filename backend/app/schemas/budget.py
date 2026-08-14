from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import field_serializer

from app.schemas.base import DecimalBaseModel
from uuid import UUID


class BudgetPosteSummary(DecimalBaseModel):
    id: int
    code: str
    libelle: str
    parent_code: str | None = None
    parent_id: int | None = None
    type: str | None = None
    active: bool = True
    is_global: bool = False
    # Ligne comptée dans les totaux et la synthèse. Faux = affichée partout,
    # ignorée de tous les agrégats (cf. BudgetPoste.inclure_dans_calculs).
    inclure_dans_calculs: bool = True
    montant_prevu: Decimal = Decimal("0")
    montant_engage: Decimal = Decimal("0")
    montant_paye: Decimal = Decimal("0")
    montant_disponible: Decimal = Decimal("0")
    pourcentage_consomme: Decimal = Decimal("0")

    @field_serializer(
        "montant_prevu",
        "montant_engage",
        "montant_paye",
        "montant_disponible",
        "pourcentage_consomme",
        mode="plain",
    )
    def _serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class BudgetPostesResponse(DecimalBaseModel):
    annee: int | None = None
    statut: str | None = None
    postes: list[BudgetPosteSummary]


class BudgetPosteTree(BudgetPosteSummary):
    children: list["BudgetPosteTree"] = []


class BudgetPostesTreeResponse(DecimalBaseModel):
    annee: int | None = None
    statut: str | None = None
    postes: list[BudgetPosteTree]


class BudgetExerciseSummary(DecimalBaseModel):
    annee: int
    statut: str | None = None


class BudgetExercisesResponse(DecimalBaseModel):
    exercices: list[BudgetExerciseSummary]


class BudgetExerciseCreate(DecimalBaseModel):
    annee: int


class BudgetAuditLogOut(DecimalBaseModel):
    id: int
    exercice_id: int | None = None
    budget_poste_id: int | None = None
    action: str
    field_name: str
    old_value: Decimal | None = None
    new_value: Decimal | None = None
    user_id: UUID | None = None
    user_name: str | None = None
    user_role: str | None = None
    created_at: str

    @field_serializer("old_value", "new_value", mode="plain")
    def _serialize_audit_decimal(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        return str(value)

class BudgetPosteCreate(DecimalBaseModel):
    annee: int
    code: str
    libelle: str
    type: str
    parent_code: str | None = None
    parent_id: int | None = None
    active: bool = True
    is_global: bool = False
    inclure_dans_calculs: bool = True
    montant_prevu: Decimal = Decimal("0")


class BudgetPosteUpdate(DecimalBaseModel):
    code: str | None = None
    libelle: str | None = None
    type: str | None = None
    parent_code: str | None = None
    parent_id: int | None = None
    active: bool | None = None
    is_global: bool | None = None
    inclure_dans_calculs: bool | None = None
    montant_prevu: Decimal | None = None


class BudgetPosteImportRow(DecimalBaseModel):
    code: str
    libelle: str
    plafond: Decimal = Decimal("0")
    parent_code: str | None = None
    parent_id: int | None = None


class BudgetPosteImportRequest(DecimalBaseModel):
    annee: int
    type: str
    filename: str | None = None
    conflict_mode: Literal["add_only", "update_existing", "replace_exercise"] = "update_existing"
    replace_confirmation: str | None = None
    rows: list[BudgetPosteImportRow]


class BudgetPosteImportResponse(DecimalBaseModel):
    success: bool
    imported: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    error_count: int = 0
    total_lignes: int = 0
    errors: list[dict] = []
    backup_path: str | None = None
    message: str


# Compatibilité temporaire (API /budget/lines)
BudgetLineSummary = BudgetPosteSummary
BudgetLineTree = BudgetPosteTree


class BudgetLinesResponse(DecimalBaseModel):
    annee: int | None = None
    statut: str | None = None
    lignes: list[BudgetPosteSummary]


class BudgetLinesTreeResponse(DecimalBaseModel):
    annee: int | None = None
    statut: str | None = None
    lignes: list[BudgetPosteTree]


BudgetLineCreate = BudgetPosteCreate
BudgetLineUpdate = BudgetPosteUpdate


class BudgetCommentaireOut(DecimalBaseModel):
    id: int
    exercice_id: int
    code: str
    budget_poste_id: int | None = None
    texte: str
    statut_budget: str | None = None
    auteur_id: UUID | None = None
    auteur_nom: str | None = None
    created_at: str
    updated_at: str | None = None
    # Calculé côté serveur : le client n'a pas à rejouer la règle « brouillon +
    # auteur » pour savoir s'il doit afficher le bouton Modifier.
    modifiable: bool = False


class BudgetCommentaireCreate(DecimalBaseModel):
    annee: int
    code: str
    texte: str


class BudgetCommentaireUpdate(DecimalBaseModel):
    texte: str


class BudgetCommentaireGeneralOut(DecimalBaseModel):
    """Commentaire général de l'exercice, un texte par vue.

    Les deux textes voyagent ensemble : l'écran budgétaire bascule entre
    dépenses et recettes sans recharger, un aller-retour réseau par bascule
    n'apporterait rien.
    """

    annee: int
    statut: str | None = None
    depense: str | None = None
    recette: str | None = None
    # Calculé côté serveur, comme pour les commentaires de ligne : le client
    # n'a pas à rejouer la règle d'ouverture pour afficher le champ en lecture
    # seule ou non.
    modifiable: bool = False


class BudgetCommentaireGeneralUpdate(DecimalBaseModel):
    annee: int
    vue: Literal["DEPENSE", "RECETTE"]
    texte: str


class BudgetCommentairesResponse(DecimalBaseModel):
    annee: int
    # Fil complet de l'exercice, groupé par code de poste : l'écran budgétaire
    # affiche un compteur sur chaque ligne, il lui faut tout d'un coup plutôt
    # qu'un appel par ligne (un budget dépasse la centaine de postes).
    commentaires: list[BudgetCommentaireOut] = []
