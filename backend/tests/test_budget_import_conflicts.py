from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints import budget as budget_endpoint
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.budget import BudgetPosteImportRequest


pytestmark = pytest.mark.asyncio


async def _org(db, slug: str) -> Organisation:
    org = Organisation(nom=f"Org {slug}", slug=slug, is_active=True)
    db.add(org)
    await db.flush()
    return org


def _user(org: Organisation) -> User:
    return User(id=uuid.uuid4(), email=f"admin-{org.slug}@example.test", role="admin", organisation_id=org.id)


async def _exercise(db, org: Organisation, annee: int = 2026) -> BudgetExercice:
    exercice = BudgetExercice(organisation_id=org.id, annee=annee, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    return exercice


async def _poste(
    db,
    org: Organisation,
    exercice: BudgetExercice,
    *,
    code: str,
    libelle: str,
    montant: str = "100",
    parent_code: str | None = None,
) -> BudgetPoste:
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=code,
        libelle=libelle,
        parent_code=parent_code,
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal(montant),
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
    )
    db.add(poste)
    await db.flush()
    return poste


def _request(mode: str, rows: list[dict], *, confirmation: str | None = None) -> BudgetPosteImportRequest:
    return BudgetPosteImportRequest(
        annee=2026,
        type="DEPENSE",
        conflict_mode=mode,
        replace_confirmation=confirmation,
        rows=rows,
    )


async def _line_by_code(db, org_id: int, code: str) -> BudgetPoste | None:
    res = await db.execute(
        select(BudgetPoste).where(BudgetPoste.organisation_id == org_id, BudgetPoste.code == code)
    )
    return res.scalar_one_or_none()


async def test_import_add_only_creates_new_and_ignores_existing(db_session):
    org = await _org(db_session, "budget-add-only")
    exercice = await _exercise(db_session, org)
    existing = await _poste(db_session, org, exercice, code="II.1", libelle="Ancien", montant="100")
    await db_session.commit()

    response = await budget_endpoint.import_budget_postes(
        _request(
            "add_only",
            [
                {"code": "II.1", "libelle": "Nouveau libelle ignore", "plafond": 999},
                {"code": "II.2", "libelle": "Nouveau poste", "plafond": 250},
            ],
        ),
        user=_user(org),
        tenant_id=org.id,
        db=db_session,
    )

    assert response.success is True
    assert response.created == 1
    assert response.skipped == 1
    unchanged = await _line_by_code(db_session, org.id, "II.1")
    created = await _line_by_code(db_session, org.id, "II.2")
    assert unchanged.id == existing.id
    assert unchanged.libelle == "Ancien"
    assert unchanged.montant_prevu == Decimal("100.00")
    assert created is not None


async def test_import_update_existing_preserves_id_and_updates_fields(db_session):
    org = await _org(db_session, "budget-update")
    exercice = await _exercise(db_session, org)
    parent = await _poste(db_session, org, exercice, code="II", libelle="Parent", montant="0")
    existing = await _poste(db_session, org, exercice, code="II.1", libelle="Ancien", montant="100")
    await db_session.commit()

    response = await budget_endpoint.import_budget_postes(
        _request("update_existing", [{"code": "II.1", "libelle": "Actualise", "plafond": 300, "parent_code": "II"}]),
        user=_user(org),
        tenant_id=org.id,
        db=db_session,
    )

    assert response.success is True
    assert response.updated == 1
    updated = await _line_by_code(db_session, org.id, "II.1")
    assert updated.id == existing.id
    assert updated.libelle == "Actualise"
    assert updated.parent_id == parent.id
    assert updated.montant_prevu == Decimal("300.00")


async def test_import_replace_deletes_current_exercise_settings_only(db_session):
    org = await _org(db_session, "budget-replace")
    other_org = await _org(db_session, "budget-replace-other")
    exercice = await _exercise(db_session, org)
    other_exercice = await _exercise(db_session, other_org)
    old_poste = await _poste(db_session, org, exercice, code="OLD", libelle="Ancien", montant="100")
    other_poste = await _poste(db_session, other_org, other_exercice, code="OLD", libelle="Autre", montant="100")
    service = Service(code="ADM", libelle="Administration", organisation_id=org.id)
    db_session.add(service)
    await db_session.flush()
    db_session.add(ServiceRubrique(service_id=service.id, budget_poste_id=old_poste.id))
    await db_session.commit()

    response = await budget_endpoint.import_budget_postes(
        _request(
            "replace_exercise",
            [{"code": "NEW", "libelle": "Nouveau", "plafond": 450}],
            confirmation=budget_endpoint.REPLACE_BUDGET_CONFIRMATION,
        ),
        user=_user(org),
        tenant_id=org.id,
        db=db_session,
    )

    assert response.success is True
    assert response.created == 1
    assert response.backup_path
    assert await _line_by_code(db_session, org.id, "OLD") is None
    assert await _line_by_code(db_session, org.id, "NEW") is not None
    assert await _line_by_code(db_session, other_org.id, "OLD") is not None
    service_link_count = await db_session.scalar(select(func.count()).select_from(ServiceRubrique))
    assert service_link_count == 0
    assert (await _line_by_code(db_session, other_org.id, "OLD")).id == other_poste.id


async def test_import_replace_requires_exact_confirmation(db_session):
    org = await _org(db_session, "budget-replace-confirm")
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await budget_endpoint.import_budget_postes(
            _request("replace_exercise", [{"code": "NEW", "libelle": "Nouveau", "plafond": 450}]),
            user=_user(org),
            tenant_id=org.id,
            db=db_session,
        )

    assert exc.value.status_code == 400
    assert "REMPLACER BUDGET" in str(exc.value.detail)


async def test_import_duplicate_file_codes_rolls_back(db_session):
    org = await _org(db_session, "budget-duplicates")
    exercice = await _exercise(db_session, org)
    await _poste(db_session, org, exercice, code="II.1", libelle="Stable", montant="100")
    await db_session.commit()

    response = await budget_endpoint.import_budget_postes(
        _request(
            "update_existing",
            [
                {"code": "II.1", "libelle": "A", "plafond": 200},
                {"code": "II.1", "libelle": "B", "plafond": 300},
            ],
        ),
        user=_user(org),
        tenant_id=org.id,
        db=db_session,
    )

    assert response.success is False
    assert response.error_count == 1
    unchanged = await _line_by_code(db_session, org.id, "II.1")
    assert unchanged.libelle == "Stable"
    assert unchanged.montant_prevu == Decimal("100.00")


async def test_import_preserves_parent_child_hierarchy_and_parent_total(db_session):
    org = await _org(db_session, "budget-hierarchy")
    await db_session.commit()

    response = await budget_endpoint.import_budget_postes(
        _request(
            "update_existing",
            [
                {"code": "II.1", "libelle": "Enfant", "plafond": 275, "parent_code": "II"},
                {"code": "II", "libelle": "Parent", "plafond": 0},
            ],
        ),
        user=_user(org),
        tenant_id=org.id,
        db=db_session,
    )

    assert response.success is True
    parent = await _line_by_code(db_session, org.id, "II")
    child = await _line_by_code(db_session, org.id, "II.1")
    assert child.parent_id == parent.id
    assert child.parent_code == "II"
    assert parent.montant_prevu == Decimal("275.00")


async def test_import_replace_rolls_back_on_internal_error(db_session, monkeypatch):
    org = await _org(db_session, "budget-rollback")
    exercice = await _exercise(db_session, org)
    await _poste(db_session, org, exercice, code="OLD", libelle="Ancien", montant="100")
    org_id = org.id
    await db_session.commit()

    async def fail_delete(*args, **kwargs):
        raise RuntimeError("delete failed")

    monkeypatch.setattr(budget_endpoint, "_delete_budget_exercise_poste_settings", fail_delete)

    with pytest.raises(RuntimeError):
        await budget_endpoint.import_budget_postes(
            _request(
                "replace_exercise",
                [{"code": "NEW", "libelle": "Nouveau", "plafond": 450}],
                confirmation=budget_endpoint.REPLACE_BUDGET_CONFIRMATION,
            ),
            user=_user(org),
            tenant_id=org.id,
            db=db_session,
        )

    assert await _line_by_code(db_session, org_id, "OLD") is not None
    assert await _line_by_code(db_session, org_id, "NEW") is None
