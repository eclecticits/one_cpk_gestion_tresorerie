from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget


CORE_BUDGET_POSTES: list[dict[str, str]] = [
    {"code": "ADM-01", "libelle": "Loyer et Charges Locatives", "type": "DEPENSE"},
    {"code": "PERS-01", "libelle": "Salaires et Gratifications", "type": "DEPENSE"},
    {"code": "TRA-01", "libelle": "Carburant et Maintenance", "type": "DEPENSE"},
    {"code": "COM-01", "libelle": "Communication et Internet", "type": "DEPENSE"},
    {"code": "MISS-01", "libelle": "Missions et Per Diem", "type": "DEPENSE"},
    {"code": "DIV-01", "libelle": "Divers et Imprévus", "type": "DEPENSE"},
]


async def ensure_core_budget_postes(
    db: AsyncSession,
    *,
    organisation_id: int,
    annee: int | None = None,
) -> None:
    if annee is None:
        res = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == organisation_id)
        )
        annee = res.scalar_one_or_none()
        if annee is None:
            annee = datetime.now(timezone.utc).year

    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.organisation_id == organisation_id,
            BudgetExercice.annee == annee,
        )
    )
    exercice = ex_res.scalar_one_or_none()
    if exercice is None:
        exercice = BudgetExercice(
            organisation_id=organisation_id,
            annee=annee,
            statut=StatutBudget.BROUILLON,
        )
        db.add(exercice)
        await db.flush()

    existing_res = await db.execute(
        select(BudgetPoste.code).where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    existing_codes = {(code or "").upper() for code in existing_res.scalars().all()}

    for item in CORE_BUDGET_POSTES:
        code = item["code"]
        if code.upper() in existing_codes:
            continue
        db.add(
            BudgetPoste(
                organisation_id=organisation_id,
                exercice_id=exercice.id,
                code=code,
                libelle=item["libelle"],
                type=item["type"],
                active=True,
                is_global=True,
                montant_prevu=0,
                montant_engage=0,
                montant_paye=0,
            )
        )
    await db.flush()
