"""Preflight and controlled reset of financial operations.

This command deliberately does not use TRUNCATE ... CASCADE.  It targets every
organisation except load-test tenants, preserves reference data, and refuses an
execution when the database contains an unexpected direct FK or an accounting
row that cannot be classified.

Usage::

    python -m app.scripts.reset_financial_operations --dry-run
    python -m app.scripts.reset_financial_operations --execute \
        --confirm RESET_ALL_FINANCIAL_OPERATIONS
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal


EXCLUDED_ORGANISATION_PREDICATE = "o.slug NOT LIKE 'load-test-%'"
ADMIN_RESET_GUC = "onec.admin_reset"
CONFIRMATION = "RESET_ALL_FINANCIAL_OPERATIONS"

OPERATION_TABLES = (
    "encaissements",
    "encaissement_articles",
    "encaissement_pieces_jointes",
    "payment_history",
    "payment_transactions",
    "requisitions",
    "lignes_requisition",
    "requisition_status_history",
    "requisition_annexes",
    "participants_transport",
    "remboursements_transport",
    "dossiers_requisition",
    "ordres_decaissement",
    "sorties_fonds",
    "retours_caisse",
    "fonds_tiers_operations",
    "transferts_internes",
    "mouvement_budget_imputations",
    "regularisations_budgetaires",
    "regularisations_caisse",
    "ouvertures_caisse",
    "clotures",
)

SCOPED_TRACE_TABLES = ("generated_documents", "document_signatory_snapshots", "notification_logs", "audit_logs")

ACCOUNTING_MODULES = {
    "encaissements",
    "sorties_fonds",
    "retours_caisse",
    "transferts",
    "transferts_internes",
    "regularisations",
    "regularisations_budgetaires",
}

ACCOUNTING_TYPES = {
    "encaissement",
    "payment_history",
    "sortie_fonds",
    "retour_caisse",
    "transfert_interne",
    "regularisation_budgetaire",
    "regularisation_caisse",
    "remboursement_transport",
    "CONTREPASSATION",
}

TRACE_ENTITY_TYPES = {
    "encaissement",
    "sortie_fonds",
    "requisition",
    "fonds_tiers_operation",
    "transfert_interne",
    "retour_caisse",
    "regularisation_budgetaire",
    "regularisation_caisse",
    "payment_history",
}

EXPECTED_OPERATION_FK_CHILDREN = set(OPERATION_TABLES) | set(SCOPED_TRACE_TABLES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Préflight sans aucune modification (défaut).")
    mode.add_argument("--execute", action="store_true", help="Exécuter après sauvegarde et confirmation forte.")
    parser.add_argument("--confirm", help="Doit être exactement RESET_ALL_FINANCIAL_OPERATIONS.")
    parser.add_argument("--backup-path", help="Chemin du pg_dump préalable.")
    parser.add_argument("--output-json", help="Écrire le rapport dans ce fichier.")
    args = parser.parse_args()
    if not args.dry_run and not args.execute:
        args.dry_run = True
    if args.execute and args.confirm != CONFIRMATION:
        parser.error(f"--execute exige --confirm {CONFIRMATION}")
    return args


async def table_exists(session, table: str) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=:table)"
            ),
            {"table": table},
        )
    )


async def organisation_ids(session) -> list[int]:
    rows = (
        await session.execute(
            text(
                "SELECT o.id FROM organisations o "
                f"WHERE {EXCLUDED_ORGANISATION_PREDICATE} ORDER BY o.id"
            )
        )
    ).scalars().all()
    return [int(value) for value in rows]


async def organisations_report(session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT o.id, o.slug, o.nom, o.is_active, "
                "(o.slug LIKE 'load-test-%') AS excluded "
                "FROM organisations o ORDER BY o.id"
            )
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def scoped_count(session, table: str, ids: list[int]) -> int | None:
    if not await table_exists(session, table):
        return None
    if table == "document_signatory_snapshots":
        predicate = "organisation_id = ANY(:ids)"
    elif table == "generated_documents":
        predicate = "organisation_id = ANY(:ids) AND resource_type = ANY(:types)"
    elif table == "notification_logs":
        predicate = "organisation_id = ANY(:ids) AND entity_type = ANY(:types)"
    elif table == "audit_logs":
        predicate = "organisation_id = ANY(:ids) AND entity_type = ANY(:types)"
    elif table == "payment_transactions":
        predicate = "organisation_id = ANY(:ids) AND encaissement_id IS NOT NULL"
    else:
        predicate = "organisation_id = ANY(:ids)"
    params: dict[str, Any] = {"ids": ids}
    if ":types" in predicate:
        params["types"] = tuple(TRACE_ENTITY_TYPES)
    return int(await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {predicate}"), params) or 0)


async def accounting_inventory(session, ids: list[int]) -> dict[str, Any]:
    if not await table_exists(session, "compta_ecritures"):
        return {"operation_candidates": [], "manual_or_ambiguous": [], "total": 0}
    rows = (
        await session.execute(
            text(
                "SELECT organisation_id, module_origine, type_origine, "
                "count(*) AS rows, COALESCE(sum(l.total),0) AS amount "
                "FROM compta_ecritures e "
                "LEFT JOIN LATERAL (SELECT COALESCE(sum(debit_tenue),0) + COALESCE(sum(credit_tenue),0) AS total "
                "FROM compta_lignes_ecriture WHERE ecriture_id=e.id) l ON true "
                "WHERE e.organisation_id = ANY(:ids) "
                "GROUP BY organisation_id, module_origine, type_origine "
                "ORDER BY organisation_id, module_origine, type_origine"
            ),
            {"ids": ids},
        )
    ).mappings().all()
    operation_candidates: list[dict[str, Any]] = []
    manual_or_ambiguous: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        module = str(item.get("module_origine") or "")
        origin_type = str(item.get("type_origine") or "")
        if module in ACCOUNTING_MODULES and origin_type in ACCOUNTING_TYPES:
            operation_candidates.append(item)
        else:
            item["reason"] = "manual_or_unclassified_origin"
            manual_or_ambiguous.append(item)
    return {
        "operation_candidates": operation_candidates,
        "manual_or_ambiguous": manual_or_ambiguous,
        "total": sum(int(row["rows"]) for row in rows),
    }


async def protected_snapshot(session, ids: list[int]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for table in ("users", "organisations", "experts_comptables", "clients"):
        snapshot[table] = int(await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
    snapshot["budget_postes"] = int(
        await session.scalar(text("SELECT count(*) FROM budget_postes WHERE organisation_id = ANY(:ids)"), {"ids": ids}) or 0
    )
    rows = (
        await session.execute(
            text(
                "SELECT organisation_id, count(*) AS rows, COALESCE(sum(montant_prevu),0) AS montant_prevu, "
                "md5(COALESCE(string_agg(concat_ws('|', id, code, libelle, parent_id, type, active, is_deleted), E'\\n' ORDER BY id),'')) AS structure_hash "
                "FROM budget_postes WHERE organisation_id = ANY(:ids) GROUP BY organisation_id ORDER BY organisation_id"
            ),
            {"ids": ids},
        )
    ).mappings().all()
    snapshot["budget_by_organisation"] = [dict(row) for row in rows]
    return snapshot


async def unexpected_foreign_keys(session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT child.relname AS child_table, parent.relname AS parent_table, "
                "c.conname, pg_get_constraintdef(c.oid) AS definition "
                "FROM pg_constraint c JOIN pg_class child ON child.oid=c.conrelid "
                "JOIN pg_class parent ON parent.oid=c.confrelid "
                "WHERE c.contype='f' AND (child.relname = ANY(:tables) OR parent.relname = ANY(:tables)) "
                "ORDER BY child.relname, parent.relname, c.conname"
            ),
            {"tables": list(OPERATION_TABLES)},
        )
    ).mappings().all()
    unexpected = []
    for row in rows:
        child = str(row["child_table"])
        parent = str(row["parent_table"])
        if child not in EXPECTED_OPERATION_FK_CHILDREN and parent in OPERATION_TABLES:
            unexpected.append(dict(row))
    return unexpected


async def collect_report() -> dict[str, Any]:
    async with SessionLocal() as session:
        ids = await organisation_ids(session)
        all_orgs = await organisations_report(session)
        protected = await protected_snapshot(session, ids)
        counts = {}
        for table in (*OPERATION_TABLES, *SCOPED_TRACE_TABLES):
            counts[table] = await scoped_count(session, table, ids)
        accounting = await accounting_inventory(session, ids)
        foreign_keys = await unexpected_foreign_keys(session)
        balances = (
            await session.execute(
                text(
                    "SELECT o.id, o.slug, "
                    "COALESCE((SELECT sum(solde_usd) FROM caisse_centrale WHERE organisation_id=o.id),0) AS caisse_usd, "
                    "COALESCE((SELECT sum(solde_cdf) FROM caisse_centrale WHERE organisation_id=o.id),0) AS caisse_cdf, "
                    "COALESCE((SELECT sum(solde_initial) FROM comptes_bancaires WHERE organisation_id=o.id),0) AS banque_initial, "
                    "COALESCE((SELECT sum(solde_actuel) FROM comptes_bancaires WHERE organisation_id=o.id),0) AS banque_actuel "
                    "FROM organisations o WHERE o.id = ANY(:ids) ORDER BY o.id"
                ),
                {"ids": ids},
            )
        ).mappings().all()
        await session.rollback()
        blockers = []
        if foreign_keys:
            blockers.append("unexpected_foreign_keys")
        if accounting["manual_or_ambiguous"]:
            blockers.append("manual_or_ambiguous_accounting_entries")
        return {
            "mode": "DRY_RUN",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": settings.env,
            "included_organisations": [row for row in all_orgs if not row["excluded"]],
            "excluded_organisations": [row for row in all_orgs if row["excluded"]],
            "operation_counts_before": counts,
            "balances_before": [dict(row) for row in balances],
            "protected_snapshot": protected,
            "accounting": accounting,
            "foreign_keys_review": {"unexpected": foreign_keys, "blockers": bool(foreign_keys)},
            "blockers": blockers,
            "sequences": "preserved_by_default",
            "tables_preserved": [
                "users", "roles", "permissions", "user_roles", "role_permissions",
                "organisations", "experts_comptables", "clients", "services", "commissions",
                "budget_exercices", "budget_postes.montant_prevu", "projets_activites",
                "banques", "comptes_bancaires", "caisse_centrale", "parametres", "referentiels",
                "budget_audit_logs", "configuration_comptable", "compta_comptes", "compta_journaux",
                "compta_periodes", "compta_mappings", "donnees_saas",
            ],
            "planned_order": list(OPERATION_TABLES),
            "planned_balance_reset": ["caisse_centrale", "comptes_bancaires", "budget_postes"],
        }


def backup_path(args: argparse.Namespace) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path(args.backup_path or f"backups/financial_operations_reset_{stamp}.dump")


def create_backup(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    url = str(settings.database_url).replace("postgresql+asyncpg://", "postgresql://", 1)
    result = subprocess.run(["pg_dump", "--format=custom", url, "-f", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0 or not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Sauvegarde PostgreSQL échouée: {result.stderr.strip()}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path} (sha256:{digest})"


async def execute_reset(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if report["blockers"]:
        raise RuntimeError(f"Reset bloqué par le dry-run: {', '.join(report['blockers'])}")
    if (settings.env or "").lower() in {"prod", "production"} and os.getenv("ALLOW_PRODUCTION_FINANCIAL_RESET") != "true":
        raise RuntimeError("Reset refusé en production sans ALLOW_PRODUCTION_FINANCIAL_RESET=true")
    backup = create_backup(backup_path(args))
    ids = [int(row["id"]) for row in report["included_organisations"]]
    operation_predicate = "organisation_id = ANY(:ids)"
    statements = [
        ("compta_lignes_ecriture", "DELETE FROM compta_lignes_ecriture WHERE ecriture_id IN (SELECT id FROM compta_ecritures WHERE organisation_id = ANY(:ids) AND module_origine = ANY(:modules) AND type_origine = ANY(:types))"),
        ("compta_ecritures", "DELETE FROM compta_ecritures WHERE organisation_id = ANY(:ids) AND module_origine = ANY(:modules) AND type_origine = ANY(:types)"),
        ("mouvement_budget_imputations", f"DELETE FROM mouvement_budget_imputations WHERE {operation_predicate}"),
        ("regularisations_budgetaires", f"DELETE FROM regularisations_budgetaires WHERE {operation_predicate}"),
        ("regularisations_caisse", f"DELETE FROM regularisations_caisse WHERE {operation_predicate}"),
        ("retours_caisse", f"DELETE FROM retours_caisse WHERE {operation_predicate}"),
        ("payment_history", f"DELETE FROM payment_history WHERE {operation_predicate}"),
        ("payment_transactions", f"DELETE FROM payment_transactions WHERE {operation_predicate} AND encaissement_id IS NOT NULL"),
        ("encaissement_articles", f"DELETE FROM encaissement_articles WHERE {operation_predicate}"),
        ("encaissement_pieces_jointes", f"DELETE FROM encaissement_pieces_jointes WHERE {operation_predicate}"),
        ("ordres_decaissement", f"DELETE FROM ordres_decaissement WHERE {operation_predicate}"),
        ("requisition_status_history", f"DELETE FROM requisition_status_history WHERE {operation_predicate}"),
        ("requisition_annexes", f"DELETE FROM requisition_annexes WHERE {operation_predicate}"),
        ("participants_transport", f"DELETE FROM participants_transport WHERE {operation_predicate}"),
        ("remboursements_transport", f"DELETE FROM remboursements_transport WHERE {operation_predicate}"),
        ("lignes_requisition", f"DELETE FROM lignes_requisition WHERE {operation_predicate}"),
        ("sorties_fonds", f"DELETE FROM sorties_fonds WHERE {operation_predicate}"),
        ("fonds_tiers_operations", f"DELETE FROM fonds_tiers_operations WHERE {operation_predicate}"),
        ("encaissements", f"DELETE FROM encaissements WHERE {operation_predicate}"),
        ("requisitions", f"DELETE FROM requisitions WHERE {operation_predicate}"),
        ("dossiers_requisition", f"DELETE FROM dossiers_requisition WHERE {operation_predicate}"),
        ("transferts_internes.references", "UPDATE transferts_internes SET transfert_origine_id=NULL WHERE organisation_id = ANY(:ids)"),
        ("transferts_internes", f"DELETE FROM transferts_internes WHERE {operation_predicate}"),
        ("ouvertures_caisse", f"DELETE FROM ouvertures_caisse WHERE {operation_predicate}"),
        ("clotures", f"DELETE FROM clotures WHERE {operation_predicate}"),
        ("caisse_centrale", "UPDATE caisse_centrale SET solde_usd=0, solde_cdf=0, est_ouverte=false, ouverte_le=NULL, ouverte_par_id=NULL WHERE organisation_id = ANY(:ids)"),
        ("comptes_bancaires", "UPDATE comptes_bancaires SET solde_initial=0, solde_actuel=0 WHERE organisation_id = ANY(:ids)"),
        ("budget_postes", "UPDATE budget_postes SET montant_engage=0, montant_paye=0 WHERE organisation_id = ANY(:ids)"),
        ("generated_documents", "DELETE FROM generated_documents WHERE organisation_id = ANY(:ids) AND resource_type = ANY(:trace_types)"),
        ("notification_logs", "DELETE FROM notification_logs WHERE organisation_id = ANY(:ids) AND entity_type = ANY(:trace_types)"),
        ("audit_logs", "DELETE FROM audit_logs WHERE organisation_id = ANY(:ids) AND entity_type = ANY(:trace_types)"),
    ]
    params: dict[str, Any] = {"ids": ids, "modules": tuple(ACCOUNTING_MODULES), "types": tuple(ACCOUNTING_TYPES), "trace_types": tuple(TRACE_ENTITY_TYPES)}
    executed: list[dict[str, Any]] = []
    async with SessionLocal() as session:
        try:
            async with session.begin():
                await session.execute(text(f"SET LOCAL {ADMIN_RESET_GUC} = 'on'"))
                for name, sql in statements:
                    if not await table_exists(session, name.split(".")[0]):
                        continue
                    result = await session.execute(text(sql), params)
                    executed.append({"table": name, "rows": int(result.rowcount or 0)})
                after = await collect_post_reset_checks(session, ids, report["protected_snapshot"])
                if after["failures"]:
                    raise RuntimeError(f"Contrôles post-reset en échec: {after['failures']}")
        except Exception:
            await session.rollback()
            raise
    return {"mode": "EXECUTED", "backup": backup, "executed": executed, "post_reset": after}


async def collect_post_reset_checks(session, ids: list[int], protected_before: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    failures: list[str] = []
    for table in OPERATION_TABLES:
        if await table_exists(session, table):
            condition = "organisation_id = ANY(:ids)"
            if table == "payment_transactions":
                condition += " AND encaissement_id IS NOT NULL"
            value = int(await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {condition}"), {"ids": ids}) or 0)
            checks[table] = value
            if value != 0:
                failures.append(table)
    checks["caisse"] = [dict(row) for row in (await session.execute(text("SELECT organisation_id, solde_usd, solde_cdf, est_ouverte FROM caisse_centrale WHERE organisation_id=ANY(:ids)"), {"ids": ids})).mappings().all()]
    checks["banques"] = [dict(row) for row in (await session.execute(text("SELECT organisation_id, COALESCE(sum(solde_initial),0) AS initial, COALESCE(sum(solde_actuel),0) AS actuel FROM comptes_bancaires WHERE organisation_id=ANY(:ids) GROUP BY organisation_id"), {"ids": ids})).mappings().all()]
    checks["budget_consumption"] = [dict(row) for row in (await session.execute(text("SELECT organisation_id, COALESCE(sum(montant_engage),0) AS engage, COALESCE(sum(montant_paye),0) AS paye FROM budget_postes WHERE organisation_id=ANY(:ids) GROUP BY organisation_id"), {"ids": ids})).mappings().all()]
    if any(row["solde_usd"] != 0 or row["solde_cdf"] != 0 or row["est_ouverte"] for row in checks["caisse"]):
        failures.append("caisse_balance")
    if any(row["initial"] != 0 or row["actuel"] != 0 for row in checks["banques"]):
        failures.append("bank_balance")
    if any(row["engage"] != 0 or row["paye"] != 0 for row in checks["budget_consumption"]):
        failures.append("budget_consumption")
    protected_after = await protected_snapshot(session, ids)
    checks["protected_unchanged"] = protected_after == protected_before
    if not checks["protected_unchanged"]:
        failures.append("protected_snapshot")
    checks["failures"] = failures
    return checks


async def main() -> None:
    args = parse_args()
    report = await collect_report()
    if args.execute:
        result = await execute_reset(report, args)
        payload = result
    else:
        payload = report
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
