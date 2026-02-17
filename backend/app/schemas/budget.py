from __future__ import annotations

from decimal import Decimal

from pydantic import field_serializer

from app.schemas.base import DecimalBaseModel


class BudgetPosteSummary(DecimalBaseModel):
    id: int
    code: str
    libelle: str
    parent_code: str | None = None
    parent_id: int | None = None
    type: str | None = None
    active: bool = True
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


class BudgetAuditLogOut(DecimalBaseModel):
    id: int
    exercice_id: int | None = None
    budget_poste_id: int | None = None
    action: str
    field_name: str
    old_value: Decimal | None = None
    new_value: Decimal | None = None
    user_id: str | None = None
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
    montant_prevu: Decimal = Decimal("0")


class BudgetPosteUpdate(DecimalBaseModel):
    code: str | None = None
    libelle: str | None = None
    type: str | None = None
    parent_code: str | None = None
    parent_id: int | None = None
    active: bool | None = None
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
    rows: list[BudgetPosteImportRow]


class BudgetPosteImportResponse(DecimalBaseModel):
    success: bool
    imported: int
    skipped: int = 0
    total_lignes: int = 0
    errors: list[dict] = []
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
