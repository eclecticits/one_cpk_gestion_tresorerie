import argparse
import importlib
import pkgutil
from pathlib import Path

import pytest

import app.models
from app.db.base import Base
from app.scripts import reset_cpk_test_data as reset


def _load_all_metadata():
    """Peuple `Base.metadata` avec toutes les tables déclarées.

    Les modèles ne sont pas importés par `app.models` : sans ce parcours, la
    métadonnée serait partielle et le contrôle de dépendances ci-dessous
    passerait en ne voyant rien — exactement le faux négatif à éviter.
    """
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")
    importlib.import_module("app.modules.comptabilite.models")
    return Base.metadata


def test_destructive_targets_are_scoped_to_organisation():
    targets = (
        *reset.DELETE_TARGETS,
        *reset.RESET_TARGETS,
        *reset.OPTIONAL_DELETE_TARGETS,
    )

    unscoped = [
        target.table
        for target in targets
        if not target.where_sql
        or (
            ":organisation_id" not in target.where_sql
            and "tenant_id = :organisation_id" not in target.where_sql
        )
    ]

    assert unscoped == []


def test_global_expert_tables_are_review_only_and_blocked():
    assert {target.table for target in reset.UNSCOPED_REVIEW_TARGETS} == {
        "experts_comptables",
        "imports_history",
        "category_changes_history",
    }
    assert all(target.action == "review_only" for target in reset.UNSCOPED_REVIEW_TARGETS)
    assert all(target.blocked for target in reset.UNSCOPED_REVIEW_TARGETS)


def test_protected_configuration_tables_are_preserved():
    protected = {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "user_menu_permissions",
        "refresh_tokens",
        "rubriques",
        "print_settings",
        "requisition_approvers",
        "budget_exercices",
        "budget_postes",
        "compta_comptes",
        "compta_journaux",
        "compta_exercices",
        "banques",
        "comptes_bancaires",
    }

    assert protected.issubset(set(reset.PRESERVED_TABLES))


def test_preserved_tables_keep_banks_without_delete_banks():
    preserved = set(reset.build_preserved_tables(delete_banks=False))

    assert "banques" in preserved
    assert "comptes_bancaires" in preserved


def test_preserved_tables_remove_banks_with_delete_banks():
    preserved = set(reset.build_preserved_tables(delete_banks=True))

    assert "banques" not in preserved
    assert "comptes_bancaires" not in preserved


def test_reset_targets_reset_bank_balances_only_without_delete_banks():
    targets = {target.table for target in reset.iter_reset_targets(delete_banks=False)}

    assert "comptes_bancaires" in targets


def test_reset_targets_do_not_reset_bank_balances_when_banks_are_deleted():
    targets = {target.table for target in reset.iter_reset_targets(delete_banks=True)}

    assert "comptes_bancaires" not in targets


def test_delete_banks_optional_targets_include_mappings_before_accounts():
    tables = [target.table for target in reset.OPTIONAL_DELETE_TARGETS]

    assert tables == ["compta_mapping_compte_bancaire", "comptes_bancaires", "banques"]


def test_delete_targets_include_requisition_parent_after_children():
    tables = [target.table for target in reset.DELETE_TARGETS]

    assert "lignes_requisition" in tables
    assert "requisitions" in tables
    assert tables.index("lignes_requisition") < tables.index("requisitions")


def test_restrict_dependencies_are_deleted_before_their_parent():
    """Toute table qui référence une cible du reset en RESTRICT doit être
    supprimée elle aussi, et avant elle.

    PostgreSQL refuse de supprimer un parent tant qu'une ligne enfant le
    référence en RESTRICT : une table oubliée ici ne dégrade pas le reset, elle
    le fait échouer entièrement. Le contrôle part de la métadonnée SQLAlchemy
    plutôt que d'une liste écrite à la main, pour qu'une table ajoutée demain
    soit couverte sans que personne ait à y penser — c'est ainsi que
    `retours_caisse` et `regularisations_caisse` avaient pu manquer.
    """
    metadata = _load_all_metadata()
    tables = [target.table for target in reset.DELETE_TARGETS]
    cibles = set(tables)

    manquants: list[str] = []
    mal_ordonnes: list[str] = []
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent not in cibles or fk.ondelete != "RESTRICT":
                continue
            if table.name not in cibles:
                manquants.append(f"{table.name} -> {parent}")
            elif tables.index(table.name) > tables.index(parent):
                mal_ordonnes.append(f"{table.name} (après {parent})")

    assert not manquants, f"Tables RESTRICT absentes de DELETE_TARGETS : {sorted(set(manquants))}"
    assert not mal_ordonnes, f"Tables RESTRICT supprimées trop tard : {sorted(set(mal_ordonnes))}"


def test_caisse_reset_closes_the_session():
    """Les soldes remis à zéro sans refermer la session laisseraient la caisse
    « ouverte » sur une ouverture supprimée, donc impossible à rouvrir."""
    cible = next(t for t in reset.RESET_TARGETS if t.table == "caisse_centrale")
    assert cible.reset_columns == ("solde_usd", "solde_cdf")
    assert "ouvertures_caisse" in [t.table for t in reset.DELETE_TARGETS]


def test_confirm_requires_exact_reset_cpk(monkeypatch):
    args = argparse.Namespace(delete_banks=False, delete_national_experts=False)
    monkeypatch.setattr(reset.settings, "env", "dev")
    monkeypatch.setattr("builtins.input", lambda _prompt: "WRONG")

    with pytest.raises(SystemExit, match="Confirmation incorrecte"):
        reset.require_confirmations(args)


def test_confirm_requires_bank_confirmation_when_delete_banks(monkeypatch):
    args = argparse.Namespace(delete_banks=True, delete_national_experts=False)
    answers = iter(["RESET CPK", "WRONG"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    with pytest.raises(SystemExit, match="Confirmation banques incorrecte"):
        reset.require_confirmations(args)


def test_confirm_requires_national_experts_confirmation(monkeypatch):
    args = argparse.Namespace(delete_banks=False, delete_national_experts=True, delete_budget_year=None)
    answers = iter(["WRONG"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    with pytest.raises(SystemExit, match="Confirmation experts nationale incorrecte"):
        reset.require_confirmations(args)


def test_confirm_requires_budget_2026_confirmation(monkeypatch):
    args = argparse.Namespace(delete_banks=False, delete_national_experts=False, delete_budget_year=2026)
    monkeypatch.setattr("builtins.input", lambda _prompt: "WRONG")

    with pytest.raises(SystemExit, match="Confirmation budget 2026 incorrecte"):
        reset.require_confirmations(args)


def test_national_experts_are_separate_delete_targets():
    assert [target.table for target in reset.NATIONAL_EXPERT_DELETE_TARGETS] == [
        "category_changes_history",
        "experts_comptables",
        "imports_history",
    ]
    assert all(target.where_sql is None for target in reset.NATIONAL_EXPERT_DELETE_TARGETS)
    assert all(target.action == "delete_national" for target in reset.NATIONAL_EXPERT_DELETE_TARGETS)


def test_national_experts_report_is_global_not_tenant_scoped():
    args = argparse.Namespace(delete_national_experts=True, delete_budget_year=None)

    assert reset.operation_name(args) == "delete_national_experts"


def test_budget_year_operation_is_separate_from_cpk_reset():
    args = argparse.Namespace(delete_national_experts=False, delete_budget_year=2026)

    assert reset.operation_name(args) == "delete_budget_year"


@pytest.mark.asyncio
async def test_budget_delete_rejects_non_cpk_or_wrong_exercice():
    with pytest.raises(RuntimeError, match="organisation_id=1 slug=cpk"):
        await reset.validate_budget_delete_report(
            {
                "target_organisation": {"id": 9, "slug": "cphk"},
                "target_exercice": {"id": 1, "annee": 2026},
                "blockers": [],
            }
        )

    with pytest.raises(RuntimeError, match="exercice budgétaire CPK 2026"):
        await reset.validate_budget_delete_report(
            {
                "target_organisation": {"id": 1, "slug": "cpk"},
                "target_exercice": {"id": 5, "annee": 2026},
                "blockers": [],
            }
        )


@pytest.mark.asyncio
async def test_budget_delete_rejects_operational_references():
    with pytest.raises(RuntimeError, match="références opérationnelles"):
        await reset.validate_budget_delete_report(
            {
                "target_organisation": {"id": 1, "slug": "cpk"},
                "target_exercice": {"id": 1, "annee": 2026},
                "blockers": [{"table": "encaissements", "rows": 1}],
            }
        )


def test_backup_converts_asyncpg_url_for_pg_dump(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        Path(cmd[3]).write_text("-- dump\n", encoding="utf-8")

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr(reset.settings, "database_url", "postgresql+asyncpg://user:pass@db:5432/onec_cpk")
    monkeypatch.setattr(reset.subprocess, "run", fake_run)

    path = reset.create_backup(argparse.Namespace(backup_path=str(tmp_path / "backup.sql")))

    assert path.endswith("backup.sql")
    assert calls[0][0] == "pg_dump"
    assert calls[0][1] == "postgresql://user:pass@db:5432/onec_cpk"


def test_backup_failure_refuses_confirm(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text, check):
        class Result:
            returncode = 1
            stderr = "pg_dump failed"
            stdout = ""

        return Result()

    monkeypatch.setattr(reset.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="Sauvegarde PostgreSQL échouée"):
        reset.create_backup(argparse.Namespace(backup_path=str(tmp_path / "backup.sql")))


@pytest.mark.asyncio
async def test_admin_reset_mode_is_transaction_local():
    calls = []

    class FakeSession:
        async def execute(self, statement):
            calls.append(str(statement))

    await reset.enable_admin_reset_mode(FakeSession())

    assert calls == ["SET LOCAL onec.admin_reset = 'on'"]


@pytest.mark.asyncio
async def test_sequence_resets_restart_at_zero(monkeypatch):
    calls = []

    class Result:
        rowcount = 3

    class FakeSession:
        async def execute(self, statement, params):
            calls.append((str(statement), params))
            return Result()

        async def scalar(self, statement, params):
            return True

    async def fake_table_exists(_session, _table):
        return True

    async def fake_table_has_column(_session, _table, _column):
        return True

    monkeypatch.setattr(reset, "table_exists", fake_table_exists)
    monkeypatch.setattr(reset, "table_has_column", fake_table_has_column)

    doc_rows = await reset.execute_target(
        FakeSession(),
        reset.Target("document_sequences", "reset", "tenant_id = :organisation_id", reset_columns=("counter",)),
        1,
    )
    compta_rows = await reset.execute_target(
        FakeSession(),
        reset.Target("compta_sequences", "reset", "organisation_id = :organisation_id", reset_columns=("compteur",)),
        1,
    )

    assert doc_rows == 3
    assert compta_rows == 3
    assert "SET counter = 0" in calls[0][0]
    assert "SET compteur = 0" in calls[1][0]


@pytest.mark.asyncio
async def test_confirm_rolls_back_on_error(monkeypatch):
    class FakeBegin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def __init__(self):
            self.rollback_called = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def begin(self):
            return FakeBegin()

        async def execute(self, statement):
            return None

        async def rollback(self):
            self.rollback_called = True

    before_session = FakeSession()
    main_session = FakeSession()
    sessions = [before_session, main_session]

    def fake_session_local():
        return sessions.pop(0)

    calls = []

    async def fake_execute_target(_session, target, organisation_id):
        calls.append((target.table, organisation_id))
        if target.table == "second":
            raise RuntimeError("boom")
        return 1

    async def fake_collect_balances(_session, _org_id):
        return {"caisse_usd": "1"}

    monkeypatch.setattr(reset, "SessionLocal", fake_session_local)
    monkeypatch.setattr(reset, "collect_balances", fake_collect_balances)
    monkeypatch.setattr(reset, "create_backup", lambda _args: "backup.sql")
    monkeypatch.setattr(reset, "validate_confirm_allowed", lambda _args: None)
    monkeypatch.setattr(reset, "require_confirmations", lambda _args: None)
    monkeypatch.setattr(reset, "DELETE_TARGETS", (
        reset.Target("first", "delete", "organisation_id = :organisation_id"),
        reset.Target("second", "delete", "organisation_id = :organisation_id"),
    ))
    monkeypatch.setattr(reset, "RESET_TARGETS", ())
    monkeypatch.setattr(reset, "BANK_RESET_TARGETS", ())
    monkeypatch.setattr(reset, "OPTIONAL_DELETE_TARGETS", ())
    monkeypatch.setattr(reset, "execute_target", fake_execute_target)

    args = argparse.Namespace(delete_banks=False, delete_national_experts=False, backup_path="backup.sql")
    report = {"target_organisation": {"id": 1, "slug": "cpk"}}

    with pytest.raises(RuntimeError, match="boom"):
        await reset.execute_confirm(args, report)

    assert calls == [("first", 1), ("second", 1)]
    assert sessions == []
    assert before_session.rollback_called is True
    assert main_session.rollback_called is True
