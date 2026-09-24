"""Préparer N+1 recopie le budget sans détourner la racine des recettes.

L'initialisation réécrivait le poste « I » de l'année cible en ligne
« Report N-1 ». Dans un plan où « I » est la racine des recettes, c'était
renommer toutes les recettes et remplacer leur total par le reliquat des
dépenses.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.organisation import Organisation
from app.models.user import User


async def _budget_2026(db, postes: list[tuple[str, str | None, str, str, str]]):
    """postes : (code, parent, libellé, type, prévu)."""
    org = Organisation(nom="Init", slug=f"in-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    ex = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.VOTE)
    db.add_all([user, ex])
    await db.flush()
    lignes = {}
    for code, parent, libelle, type_, prevu in postes:
        ligne = BudgetPoste(
            organisation_id=org.id, exercice_id=ex.id, code=code, libelle=libelle, type=type_,
            parent_code=parent, parent_id=lignes[parent].id if parent else None, active=True,
            montant_prevu=Decimal(prevu), montant_engage=0, montant_paye=0, is_deleted=False,
            code_poste_arrieres="I.3.4" if code == "I.3.1" else None,
        )
        db.add(ligne)
        await db.flush()
        lignes[code] = ligne
    await db.commit()
    return org, user


async def _postes_2027(db, org_id: int) -> dict[str, BudgetPoste]:
    rows = (
        await db.execute(
            select(BudgetPoste)
            .join(BudgetExercice, BudgetExercice.id == BudgetPoste.exercice_id)
            .where(BudgetPoste.organisation_id == org_id, BudgetExercice.annee == 2027)
        )
    ).scalars().all()
    return {p.code: p for p in rows}


@pytest.mark.asyncio
async def test_une_racine_des_recettes_reste_une_racine(db_session):
    from app.api.v1.endpoints.budget import initialize_next_exercise

    db = db_session
    org, user = await _budget_2026(db, [
        ("I", None, "RECETTES", "RECETTE", "1000"),
        ("I.3", "I", "COTISATION ANNUELLE", "RECETTE", "1000"),
        ("I.3.1", "I.3", "EC-en cabinet", "RECETTE", "800"),
        ("I.3.4", "I.3", "Arriérés de Cotisation EC", "RECETTE", "200"),
        ("II", None, "DÉPENSES", "DEPENSE", "900"),
    ])

    await initialize_next_exercise(
        annee=2026, annee_cible=None, coefficient=0.0, overwrite=False, user=user, tenant_id=org.id, db=db
    )

    postes = await _postes_2027(db, org.id)
    assert postes["I"].libelle == "RECETTES"
    assert Decimal(postes["I"].montant_prevu) == Decimal("1000")
    assert postes["I.3"].parent_id == postes["I"].id
    # Le poste d'arriérés désigné suit le poste d'une année sur l'autre.
    assert postes["I.3.1"].code_poste_arrieres == "I.3.4"
    assert not any(p.libelle == "Report N-1" for p in postes.values())


@pytest.mark.asyncio
async def test_une_ligne_i_isolee_devient_le_report(db_session):
    """Le plan qui réserve « I » au report garde son comportement."""
    from app.api.v1.endpoints.budget import initialize_next_exercise

    db = db_session
    org, user = await _budget_2026(db, [
        ("I", None, "Report", "RECETTE", "0"),
        ("II", None, "Fonctionnement", "DEPENSE", "900"),
    ])

    await initialize_next_exercise(
        annee=2026, annee_cible=None, coefficient=0.0, overwrite=False, user=user, tenant_id=org.id, db=db
    )

    postes = await _postes_2027(db, org.id)
    assert postes["I"].libelle == "Report N-1"
    # Rien de payé en 2026 : tout le prévu des dépenses est reporté.
    assert Decimal(postes["I"].montant_prevu) == Decimal("900")
