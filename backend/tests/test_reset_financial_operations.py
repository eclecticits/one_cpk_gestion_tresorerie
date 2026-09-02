import argparse

from app.scripts import reset_financial_operations as reset


def test_dry_run_is_default_and_execute_requires_strong_confirmation(monkeypatch):
    monkeypatch.setattr("sys.argv", ["reset_financial_operations"])
    args = reset.parse_args()
    assert args.dry_run is True
    assert args.execute is False


def test_operation_scope_excludes_only_load_test_tenants():
    assert "load-test-%" in reset.EXCLUDED_ORGANISATION_PREDICATE
    assert "encaissements" in reset.OPERATION_TABLES
    assert "transferts_internes" in reset.OPERATION_TABLES
    assert "fonds_tiers_operations" in reset.OPERATION_TABLES
    assert "remboursements_transport" in reset.OPERATION_TABLES
    assert "participants_transport" in reset.OPERATION_TABLES


def test_clients_and_reference_tables_are_not_reset_targets():
    assert "clients" not in reset.OPERATION_TABLES
    assert "experts_comptables" not in reset.OPERATION_TABLES
    assert "budget_postes" not in reset.OPERATION_TABLES
    assert "organisations" not in reset.OPERATION_TABLES


def test_accounting_scope_is_explicitly_classified():
    assert "encaissements" in reset.ACCOUNTING_MODULES
    assert "sorties_fonds" in reset.ACCOUNTING_MODULES
    assert "transferts" in reset.ACCOUNTING_MODULES
    assert "encaissement" in reset.ACCOUNTING_TYPES
    assert "sortie_fonds" in reset.ACCOUNTING_TYPES


def test_sequences_are_preserved_by_default():
    assert "preserved_by_default" in reset.collect_report.__code__.co_consts
