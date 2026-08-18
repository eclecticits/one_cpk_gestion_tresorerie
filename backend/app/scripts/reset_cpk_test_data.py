from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal


ORG_PARAM = "organisation_id"
ADMIN_RESET_GUC = "onec.admin_reset"


@dataclass(frozen=True)
class Target:
    table: str
    action: str
    where_sql: str | None
    dependencies: tuple[str, ...] = ()
    notes: str = ""
    blocked: bool = False
    reset_columns: tuple[str, ...] = ()


RESET_CPK_CONFIRMATION = "RESET CPK"
DELETE_CPK_BANKS_CONFIRMATION = "DELETE CPK BANKS"
DELETE_NATIONAL_EXPERTS_CONFIRMATION = "DELETE NATIONAL EXPERTS LIST"
DELETE_BUDGET_2026_CONFIRMATION = "DELETE BUDGET 2026"


DELETE_TARGETS: tuple[Target, ...] = (
    Target("document_signatory_snapshots", "delete", "organisation_id = :organisation_id", ("generated_documents",)),
    Target("generated_documents", "delete", "organisation_id = :organisation_id", notes="Documents générés liés aux opérations."),
    # Ces deux tables référencent `encaissements` et `sorties_fonds` en
    # ondelete=RESTRICT : PostgreSQL refuse la suppression du parent tant
    # qu'elles portent une ligne. Elles doivent donc précéder les deux, sinon
    # tout le reset échoue sur une violation de clé étrangère.
    Target("regularisations_caisse", "delete", "organisation_id = :organisation_id", ("encaissements", "sorties_fonds"), notes="RESTRICT vers encaissements et sorties_fonds : à supprimer avant les deux."),
    Target("retours_caisse", "delete", "organisation_id = :organisation_id", ("sorties_fonds",), notes="RESTRICT vers sorties_fonds : à supprimer avant."),
    Target("payment_history", "delete", "organisation_id = :organisation_id", ("encaissements",)),
    Target("payment_transactions", "delete", "organisation_id = :organisation_id AND flow = 'TENANT_BUSINESS'", ("encaissements",)),
    Target("payment_logs", "delete", "organisation_id = :organisation_id"),
    Target("encaissement_articles", "delete", "organisation_id = :organisation_id", ("encaissements",)),
    Target("encaissements", "delete", "organisation_id = :organisation_id"),
    Target("clients", "delete", "organisation_id = :organisation_id", ("encaissements",), notes="Référentiel client alimenté par les opérations d'encaissement de test."),
    Target("ordres_decaissement", "delete", "organisation_id = :organisation_id", ("requisitions", "sorties_fonds")),
    Target("requisition_status_history", "delete", "organisation_id = :organisation_id", ("requisitions",)),
    Target("requisition_annexes", "delete", "organisation_id = :organisation_id", ("requisitions",)),
    Target("lignes_requisition", "delete", "organisation_id = :organisation_id", ("requisitions",)),
    Target("participants_transport", "delete", "organisation_id = :organisation_id", ("remboursements_transport",)),
    Target("remboursements_transport", "delete", "organisation_id = :organisation_id"),
    Target("sorties_fonds", "delete", "organisation_id = :organisation_id"),
    Target("requisitions", "delete", "organisation_id = :organisation_id"),
    Target("dossiers_requisition", "delete", "organisation_id = :organisation_id", notes="Dossiers d'examen de réquisitions opérationnels."),
    Target("transferts_internes", "delete", "organisation_id = :organisation_id"),
    Target("ouvertures_caisse", "delete", "organisation_id = :organisation_id"),
    Target("clotures", "delete", "organisation_id = :organisation_id"),
    Target("compta_lignes_ecriture", "delete", "organisation_id = :organisation_id", ("compta_ecritures",)),
    Target("compta_ecritures", "delete", "organisation_id = :organisation_id"),
    Target("budget_audit_logs", "delete", "organisation_id = :organisation_id"),
    Target("audit_logs", "delete", "organisation_id = :organisation_id", notes="Audit opérationnel du tenant; préserver si traçabilité historique requise."),
)


RESET_TARGETS: tuple[Target, ...] = (
    Target("caisse_centrale", "reset", "organisation_id = :organisation_id", reset_columns=("solde_usd", "solde_cdf")),
    Target("budget_postes", "reset", "organisation_id = :organisation_id AND is_deleted = false", reset_columns=("montant_engage", "montant_paye")),
    Target("document_sequences", "reset", "tenant_id = :organisation_id", reset_columns=("counter",), notes="Compteurs reçus/réquisitions/remboursements/sorties selon doc_type."),
    Target("compta_sequences", "reset", "organisation_id = :organisation_id", reset_columns=("compteur",)),
)


BANK_RESET_TARGETS: tuple[Target, ...] = (
    Target("comptes_bancaires", "reset", "organisation_id = :organisation_id", reset_columns=("solde_initial", "solde_actuel")),
)


OPTIONAL_DELETE_TARGETS: tuple[Target, ...] = (
    Target("compta_mapping_compte_bancaire", "delete_optional", "organisation_id = :organisation_id", ("comptes_bancaires",), notes="Uniquement avec --delete-banks."),
    Target("comptes_bancaires", "delete_optional", "organisation_id = :organisation_id", ("banques",), notes="Uniquement avec --delete-banks."),
    Target("banques", "delete_optional", "organisation_id = :organisation_id", notes="Uniquement avec --delete-banks."),
)


UNSCOPED_REVIEW_TARGETS: tuple[Target, ...] = (
    Target("experts_comptables", "review_only", None, notes="Pas de colonne organisation_id/tenant_id; suppression réelle bloquée sans preuve CPK.", blocked=True),
    Target("imports_history", "review_only", None, notes="Pas de colonne organisation_id/tenant_id; historique import global.", blocked=True),
    Target("category_changes_history", "review_only", None, notes="Pas de colonne organisation_id/tenant_id; dépend des experts globaux.", blocked=True),
)


NATIONAL_EXPERT_DELETE_TARGETS: tuple[Target, ...] = (
    Target("category_changes_history", "delete_national", None, ("experts_comptables",), notes="Suppression nationale globale."),
    Target("experts_comptables", "delete_national", None, notes="Suppression nationale globale."),
    Target("imports_history", "delete_national", None, notes="Suppression nationale globale."),
)

NATIONAL_EXPERT_REFERENCE_TARGETS: tuple[Target, ...] = (
    Target("encaissements", "null_expert_ref", "expert_comptable_id IS NOT NULL", notes="Référence expert globale autorisée à NULL."),
    Target("participants_transport", "null_expert_ref", "expert_comptable_id IS NOT NULL", notes="Référence expert globale autorisée à NULL."),
)

BUDGET_DELETE_TABLES: tuple[str, ...] = (
    "budget_audit_logs",
    "compta_mapping_poste_budgetaire",
    "service_rubriques",
    "budget_postes",
    "budget_exercices",
)


PRESERVED_TABLES: tuple[str, ...] = (
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
    "user_menu_permissions",
    "refresh_tokens",
    "organisations",
    "organisation_settings",
    "print_settings",
    "system_settings",
    "platform_settings",
    "services",
    "service_rubriques",
    "service_member_functions",
    "requisition_approvers",
    "rubriques",
    "budget_exercices",
    "budget_postes",
    "banques",
    "comptes_bancaires",
    "compta_societes",
    "compta_etablissements",
    "compta_referentiels",
    "compta_comptes",
    "compta_journaux",
    "compta_exercices",
    "compta_periodes",
    "compta_taux_change",
    "compta_mapping_poste_budgetaire",
    "compta_mapping_compte_bancaire",
    "compta_mapping_rubrique",
    "compta_postes_etat",
    "compta_poste_etat_comptes",
    "subscriptions",
    "saas_invoices",
    "transactions",
)


def build_preserved_tables(*, delete_banks: bool) -> list[str]:
    preserved = list(PRESERVED_TABLES)
    if delete_banks:
        preserved = [table for table in preserved if table not in {"banques", "comptes_bancaires"}]
    return preserved


def iter_reset_targets(*, delete_banks: bool) -> tuple[Target, ...]:
    if delete_banks:
        return RESET_TARGETS
    return (*RESET_TARGETS, *BANK_RESET_TARGETS)


async def resolve_organisation(session, args: argparse.Namespace) -> dict[str, Any]:
    if args.organisation_id:
        result = await session.execute(
            text("SELECT id, slug, nom, is_active FROM organisations WHERE id = :id"),
            {"id": args.organisation_id},
        )
    elif args.tenant_id:
        tenant_ref = str(args.tenant_id).strip()
        if tenant_ref.isdigit():
            result = await session.execute(
                text("SELECT id, slug, nom, is_active FROM organisations WHERE id = :id"),
                {"id": int(tenant_ref)},
            )
        else:
            result = await session.execute(
                text("SELECT id, slug, nom, is_active FROM organisations WHERE lower(slug) = lower(:slug)"),
                {"slug": tenant_ref},
            )
    else:
        result = await session.execute(
            text("SELECT id, slug, nom, is_active FROM organisations WHERE lower(slug) = 'cpk'")
        )
    row = result.mappings().first()
    if row is None:
        raise SystemExit("Organisation/tenant CPK introuvable. Aucune action effectuée.")
    return dict(row)


async def table_exists(session, table: str) -> bool:
    value = await session.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :table)"
        ),
        {"table": table},
    )
    return bool(value)


async def table_has_column(session, table: str, column: str) -> bool:
    value = await session.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column)"
        ),
        {"table": table, "column": column},
    )
    return bool(value)


async def assert_scoped_target(session, target: Target) -> None:
    if target.where_sql is None:
        raise RuntimeError(f"Refus: cible opérationnelle non filtrée ({target.table}).")
    if not await table_exists(session, target.table):
        return
    if "organisation_id = :organisation_id" in target.where_sql:
        if not await table_has_column(session, target.table, "organisation_id"):
            raise RuntimeError(f"Refus: {target.table} n'a pas de colonne organisation_id.")
    elif "tenant_id = :organisation_id" in target.where_sql:
        if not await table_has_column(session, target.table, "tenant_id"):
            raise RuntimeError(f"Refus: {target.table} n'a pas de colonne tenant_id.")
    else:
        raise RuntimeError(f"Refus: filtre de tenant invalide pour {target.table}: {target.where_sql}")


async def count_target(session, target: Target, organisation_id: int) -> int | None:
    if not await table_exists(session, target.table):
        return None
    if target.where_sql:
        sql = f"SELECT count(*) FROM {target.table} WHERE {target.where_sql}"
        value = await session.scalar(text(sql), {ORG_PARAM: organisation_id})
    else:
        value = await session.scalar(text(f"SELECT count(*) FROM {target.table}"))
    return int(value or 0)


async def sum_columns(session, target: Target, organisation_id: int) -> dict[str, str]:
    if not target.reset_columns or not target.where_sql or not await table_exists(session, target.table):
        return {}
    expressions = ", ".join(f"COALESCE(SUM({column}), 0) AS {column}" for column in target.reset_columns)
    row = (
        await session.execute(
            text(f"SELECT {expressions} FROM {target.table} WHERE {target.where_sql}"),
            {ORG_PARAM: organisation_id},
        )
    ).mappings().first()
    return {column: str(row[column]) for column in target.reset_columns} if row else {}


async def collect_sequences(session, organisation_id: int) -> list[dict[str, Any]]:
    if not await table_exists(session, "document_sequences"):
        return []
    rows = (
        await session.execute(
            text(
                "SELECT doc_type, year, service_id, counter "
                "FROM document_sequences WHERE tenant_id = :organisation_id "
                "ORDER BY doc_type, year, service_id NULLS FIRST"
            ),
            {ORG_PARAM: organisation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def collect_compta_sequences(session, organisation_id: int) -> list[dict[str, Any]]:
    if not await table_exists(session, "compta_sequences"):
        return []
    rows = (
        await session.execute(
            text(
                "SELECT cs.id, cs.societe_id, cs.exercice_id, cs.journal_id, j.code AS journal_code, "
                "e.code AS exercice_code, cs.compteur "
                "FROM compta_sequences cs "
                "LEFT JOIN compta_journaux j ON j.id = cs.journal_id "
                "LEFT JOIN compta_exercices e ON e.id = cs.exercice_id "
                "WHERE cs.organisation_id = :organisation_id "
                "ORDER BY e.code, j.code"
            ),
            {ORG_PARAM: organisation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def collect_balances(session, organisation_id: int) -> dict[str, str]:
    row = (
        await session.execute(
            text(
                "SELECT "
                "COALESCE((SELECT solde_usd FROM caisse_centrale WHERE organisation_id = :organisation_id LIMIT 1), 0) AS caisse_usd, "
                "COALESCE((SELECT solde_cdf FROM caisse_centrale WHERE organisation_id = :organisation_id LIMIT 1), 0) AS caisse_cdf, "
                "COALESCE((SELECT SUM(solde_actuel) FROM comptes_bancaires WHERE organisation_id = :organisation_id AND account_type = 'BANK' AND devise = 'USD'), 0) AS banques_usd, "
                "COALESCE((SELECT SUM(solde_actuel) FROM comptes_bancaires WHERE organisation_id = :organisation_id AND account_type = 'BANK' AND devise = 'CDF'), 0) AS banques_cdf"
            ),
            {ORG_PARAM: organisation_id},
        )
    ).mappings().first()
    if row is None:
        return {"caisse_usd": "0", "caisse_cdf": "0", "banques_usd": "0", "banques_cdf": "0"}
    return {key: str(row[key]) for key in row.keys()}


def operation_name(args: argparse.Namespace) -> str:
    if getattr(args, "delete_budget_year", None):
        return "delete_budget_year"
    if getattr(args, "delete_national_experts", False):
        return "delete_national_experts"
    return "reset_cpk"


def default_backup_path(args: argparse.Namespace, report: dict[str, Any] | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    op_name = operation_name(args)
    if op_name == "delete_budget_year":
        year = int(args.delete_budget_year)
        slug = "cpk"
        if report and report.get("target_organisation"):
            slug = str(report["target_organisation"].get("slug") or slug)
        return str(Path("backups") / f"budget_{year}_{slug}_delete_{stamp}.sql")
    if op_name == "delete_national_experts":
        return str(Path("backups") / f"national_experts_delete_{stamp}.sql")
    return str(Path("backups") / f"cpk_reset_{stamp}.sql")


async def collect_budget_year_report(args: argparse.Namespace) -> dict[str, Any]:
    year = int(args.delete_budget_year)
    async with SessionLocal() as session:
        org = await resolve_organisation(session, args)
        organisation_id = int(org["id"])
        exercice = (
            await session.execute(
                text(
                    "SELECT be.id, be.organisation_id, be.annee, be.statut, o.slug, o.nom "
                    "FROM budget_exercices be JOIN organisations o ON o.id = be.organisation_id "
                    "WHERE be.organisation_id = :organisation_id AND be.annee = :year"
                ),
                {ORG_PARAM: organisation_id, "year": year},
            )
        ).mappings().first()

        inventory = (
            await session.execute(
                text(
                    "SELECT be.id AS exercice_id, be.organisation_id, o.slug, o.nom, be.annee, be.statut, "
                    "COUNT(bp.id) AS postes, COALESCE(SUM(bp.montant_prevu),0) AS montant_initial, "
                    "COALESCE(SUM(bp.montant_engage),0) AS montant_engage, "
                    "COALESCE(SUM(bp.montant_paye),0) AS montant_paye, "
                    "COALESCE(SUM(bp.montant_prevu - bp.montant_engage),0) AS montant_disponible "
                    "FROM budget_exercices be JOIN organisations o ON o.id=be.organisation_id "
                    "LEFT JOIN budget_postes bp ON bp.exercice_id=be.id AND bp.organisation_id=be.organisation_id "
                    "WHERE be.annee=:year "
                    "GROUP BY be.id, be.organisation_id, o.slug, o.nom, be.annee, be.statut "
                    "ORDER BY be.organisation_id"
                ),
                {"year": year},
            )
        ).mappings().all()

        sections: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        poste_summary: dict[str, Any] = {}
        if exercice:
            exercice_id = int(exercice["id"])
            params = {ORG_PARAM: organisation_id, "exercice_id": exercice_id, "year": year, "year_text": str(year)}
            section_sql = (
                ("budget_audit_logs", "exercice_id=:exercice_id OR budget_poste_id IN postes", "SELECT count(*) AS rows, COALESCE(sum(COALESCE(new_value,0)),0) AS amount FROM budget_audit_logs WHERE organisation_id=:organisation_id AND (exercice_id=:exercice_id OR budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id))", "delete"),
                ("compta_mapping_poste_budgetaire", "budget_poste_id IN postes", "SELECT count(*) AS rows, 0 AS amount FROM compta_mapping_poste_budgetaire WHERE organisation_id=:organisation_id AND budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id)", "delete"),
                ("service_rubriques", "budget_poste_id IN postes", "SELECT count(*) AS rows, 0 AS amount FROM service_rubriques WHERE budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id)", "delete"),
                ("encaissements", "budget_poste_id IN postes", "SELECT count(*) AS rows, COALESCE(sum(montant_total),0) AS amount FROM encaissements WHERE organisation_id=:organisation_id AND budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id)", "block_if_nonzero"),
                ("lignes_requisition", "budget_poste_id IN postes", "SELECT count(*) AS rows, COALESCE(sum(montant_total),0) AS amount FROM lignes_requisition WHERE organisation_id=:organisation_id AND budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id)", "block_if_nonzero"),
                ("sorties_fonds", "budget_poste_id IN postes", "SELECT count(*) AS rows, COALESCE(sum(montant_paye),0) AS amount FROM sorties_fonds WHERE organisation_id=:organisation_id AND budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id)", "block_if_nonzero"),
                ("compta_ecritures", "compta_exercice.code=:year_text", "SELECT count(*) AS rows, 0 AS amount FROM compta_ecritures ce JOIN compta_exercices cx ON cx.id=ce.exercice_id WHERE ce.organisation_id=:organisation_id AND cx.organisation_id=:organisation_id AND cx.code=:year_text", "block_if_nonzero"),
                ("compta_lignes_ecriture", "compta_exercice.code=:year_text", "SELECT count(*) AS rows, 0 AS amount FROM compta_lignes_ecriture cle JOIN compta_ecritures ce ON ce.id=cle.ecriture_id JOIN compta_exercices cx ON cx.id=ce.exercice_id WHERE cle.organisation_id=:organisation_id AND ce.organisation_id=:organisation_id AND cx.organisation_id=:organisation_id AND cx.code=:year_text", "block_if_nonzero"),
                ("budget_postes", "organisation_id=:organisation_id AND exercice_id=:exercice_id", "SELECT count(*) AS rows, COALESCE(sum(montant_prevu),0) AS amount FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id", "delete"),
                ("budget_exercices", "organisation_id=:organisation_id AND annee=:year", "SELECT count(*) AS rows, 0 AS amount FROM budget_exercices WHERE organisation_id=:organisation_id AND annee=:year", "delete"),
            )
            for table, filter_sql, sql, action in section_sql:
                row = (await session.execute(text(sql), params)).mappings().first()
                count = int(row["rows"] or 0) if row else 0
                amount = str(row["amount"] or 0) if row else "0"
                entry = {
                    "table": table,
                    "filter": filter_sql,
                    "rows": count,
                    "amount": amount,
                    "planned_action": action,
                }
                sections.append(entry)
                if action == "block_if_nonzero" and count > 0:
                    blockers.append(entry)

            poste_summary = dict(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) AS total_postes, "
                            "count(*) FILTER (WHERE parent_id IS NULL) AS racines, "
                            "count(*) FILTER (WHERE parent_id IS NOT NULL) AS sous_postes, "
                            "count(*) FILTER (WHERE is_deleted) AS soft_deleted, "
                            "count(*) FILTER (WHERE NOT is_deleted) AS actifs "
                            "FROM budget_postes WHERE organisation_id=:organisation_id AND exercice_id=:exercice_id"
                        ),
                        params,
                    )
                ).mappings().first()
                or {}
            )

        report = {
            "mode": "DRY_RUN" if args.dry_run else "CONFIRM_REQUESTED",
            "operation": "DELETE_BUDGET_YEAR",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": settings.env,
            "target_organisation": org,
            "year": year,
            "target_exercice": dict(exercice) if exercice else None,
            "all_budget_exercises_for_year": [dict(row) for row in inventory],
            "poste_summary": poste_summary,
            "tables_concerned": sections,
            "blockers": blockers,
            "delete_order": list(BUDGET_DELETE_TABLES),
            "protected_data": [
                "users", "roles", "permissions", "system_settings", "platform_settings",
                "organisations", "subscriptions", "saas_invoices", "transactions",
                "compta_comptes", "compta_journaux", "compta_exercices", "compta_periodes",
                "budget_exercices autres organisations", "budget_exercices autres annees",
            ],
            "expected_after": {
                "budget_exercices": "0 pour organisation_id=1 annee=2026",
                "budget_postes": "0 pour organisation_id=1 exercice 2026",
                "budget_audit_logs": "0 pour exercice/postes 2026 CPK",
                "operation_references": "0 avant et apres",
            },
            "backup_path": args.backup_path or default_backup_path(args, {"target_organisation": org}),
        }
        await session.rollback()
        return report


async def collect_national_experts_report(args: argparse.Namespace) -> dict[str, Any]:
    async with SessionLocal() as session:
        sections: list[dict[str, Any]] = []
        for table, sql, action in (
            ("category_changes_history", "SELECT count(*) AS rows FROM category_changes_history", "delete"),
            ("encaissements", "SELECT count(*) AS rows FROM encaissements WHERE expert_comptable_id IS NOT NULL", "set_null"),
            ("participants_transport", "SELECT count(*) AS rows FROM participants_transport WHERE expert_comptable_id IS NOT NULL", "set_null"),
            ("experts_comptables", "SELECT count(*) AS rows FROM experts_comptables", "delete"),
            ("imports_history", "SELECT count(*) AS rows FROM imports_history", "delete"),
        ):
            count = int(await session.scalar(text(sql)) or 0)
            sections.append({"table": table, "filter": "global" if action == "delete" else "expert_comptable_id IS NOT NULL", "rows": count, "planned_action": action})

        report = {
            "mode": "DRY_RUN" if args.dry_run else "CONFIRM_REQUESTED",
            "operation": "DELETE_NATIONAL_EXPERTS_LIST",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": settings.env,
            "scope": "national_global_all_tenants",
            "tables_concerned": sections,
            "foreign_keys": [
                {"table": "category_changes_history", "column": "expert_id", "delete_rule": "CASCADE"},
                {"table": "encaissements", "column": "expert_comptable_id", "delete_rule": "SET NULL"},
                {"table": "participants_transport", "column": "expert_comptable_id", "delete_rule": "SET NULL"},
            ],
            "delete_order": [
                "category_changes_history",
                "encaissements.expert_comptable_id = NULL",
                "participants_transport.expert_comptable_id = NULL",
                "experts_comptables",
                "imports_history",
            ],
            "expected_after": {
                "experts_comptables": 0,
                "imports_history": 0,
                "category_changes_history": 0,
                "expert_references": 0,
            },
            "backup_path": args.backup_path or default_backup_path(args),
        }
        await session.rollback()
        return report


async def collect_report(args: argparse.Namespace) -> dict[str, Any]:
    op_name = operation_name(args)
    if op_name == "delete_budget_year":
        return await collect_budget_year_report(args)
    if op_name == "delete_national_experts":
        return await collect_national_experts_report(args)

    async with SessionLocal() as session:
        org = await resolve_organisation(session, args)
        organisation_id = int(org["id"])

        sections = []
        for target in (*DELETE_TARGETS, *iter_reset_targets(delete_banks=args.delete_banks)):
            count = await count_target(session, target, organisation_id)
            sections.append(section_row(session, target, count, await sum_columns(session, target, organisation_id)))

        if args.delete_banks:
            for target in OPTIONAL_DELETE_TARGETS:
                count = await count_target(session, target, organisation_id)
                sections.append(section_row(session, target, count, {}))

        review = []
        for target in UNSCOPED_REVIEW_TARGETS:
            count = await count_target(session, target, organisation_id)
            review.append(section_row(session, target, count, {}))

        national_delete = []
        if args.delete_national_experts:
            for target in NATIONAL_EXPERT_DELETE_TARGETS:
                count = await count_target(session, target, organisation_id)
                national_delete.append(section_row(session, target, count, {}))

        report = {
            "mode": "DRY_RUN" if args.dry_run else "CONFIRM_REQUESTED",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": settings.env,
            "target_organisation": org,
            "delete_banks_requested": bool(args.delete_banks),
            "keep_banks_requested": not bool(args.delete_banks),
            "delete_national_experts_requested": bool(args.delete_national_experts),
            "reset_sequences_requested": bool(args.reset_sequences),
            "tables_concerned": sections,
            "unscoped_review_required": review,
            "national_experts_delete_plan": national_delete,
            "document_sequences_before": await collect_sequences(session, organisation_id),
            "compta_sequences_before": await collect_compta_sequences(session, organisation_id),
            "balances_before": await collect_balances(session, organisation_id),
            "expected_after": {
                "caisse_centrale": {"solde_usd": "0", "solde_cdf": "0"},
                "comptes_bancaires": "deleted" if args.delete_banks else {"solde_initial": "0", "solde_actuel": "0"},
                "banques": "deleted" if args.delete_banks else "preserved",
                "operation_rows_for_organisation": "0",
            },
            "tables_preserved": build_preserved_tables(delete_banks=args.delete_banks),
            "backup_path": args.backup_path,
            "confirm_blockers": [
                "Les tables experts_comptables/imports_history/category_changes_history sont nationales et exigent --delete-national-experts + confirmation distincte.",
            ],
        }
        await session.rollback()
        return report


def section_row(_session, target: Target, count: int | None, sums: dict[str, str]) -> dict[str, Any]:
    return {
        "table": target.table,
        "action": target.action,
        "where": target.where_sql,
        "rows": "missing_table" if count is None else count,
        "dependencies": list(target.dependencies),
        "sums_before_reset": sums,
        "notes": target.notes,
        "blocked": target.blocked,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit/reset sécurisé des données opérationnelles CPK.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Afficher uniquement les lignes concernées.")
    mode.add_argument("--confirm", action="store_true", help="Demander la suppression réelle (verrouillée).")
    parser.add_argument("--tenant-id", help="Slug ou id du tenant. Défaut: cpk")
    parser.add_argument("--organisation-id", type=int, help="Id numérique d'organisation.")
    parser.add_argument("--keep-banks", action="store_true", default=True)
    parser.add_argument("--delete-banks", action="store_true", help="Inclure banques et comptes dans le plan.")
    parser.add_argument("--delete-national-experts", action="store_true", help="Supprimer la liste nationale des experts (confirmation séparée).")
    parser.add_argument("--delete-budget-year", type=int, help="Supprimer le budget d'une année pour l'organisation ciblée.")
    parser.add_argument("--keep-budget-structure", action="store_true", default=True)
    parser.add_argument("--reset-sequences", action="store_true", default=True)
    parser.add_argument("--backup-path")
    parser.add_argument("--output-json", help="Écrire le rapport dry-run dans un fichier JSON.")
    args = parser.parse_args()
    if args.delete_budget_year and args.delete_national_experts:
        raise SystemExit("Refus: --delete-budget-year et --delete-national-experts sont deux opérations séparées.")
    if args.delete_budget_year and args.delete_budget_year != 2026:
        raise SystemExit("Refus: seule la suppression du budget 2026 est autorisée par cette commande.")
    if args.delete_budget_year and args.delete_banks:
        raise SystemExit("Refus: --delete-budget-year ne se combine pas avec --delete-banks.")
    return args


def validate_confirm_allowed(args: argparse.Namespace) -> None:
    env = (settings.env or "").lower()
    if env in {"prod", "production"} and os.environ.get("ALLOW_PRODUCTION_CPK_RESET") != "true":
        raise SystemExit("Refus: environnement production sans ALLOW_PRODUCTION_CPK_RESET=true.")


def require_confirmations(args: argparse.Namespace) -> None:
    op_name = operation_name(args)
    if op_name == "delete_budget_year":
        typed_budget = input('Suppression budget CPK 2026. Saisir exactement "DELETE BUDGET 2026": ')
        if typed_budget != DELETE_BUDGET_2026_CONFIRMATION:
            raise SystemExit("Confirmation budget 2026 incorrecte. Aucune action effectuée.")
        return
    if op_name == "delete_national_experts":
        typed_experts = input('Suppression nationale experts. Saisir exactement "DELETE NATIONAL EXPERTS LIST": ')
        if typed_experts != DELETE_NATIONAL_EXPERTS_CONFIRMATION:
            raise SystemExit("Confirmation experts nationale incorrecte. Aucune action effectuée.")
        return

    typed = input('Opération destructive. Saisir exactement "RESET CPK" pour continuer: ')
    if typed != RESET_CPK_CONFIRMATION:
        raise SystemExit("Confirmation incorrecte. Aucune action effectuée.")
    if args.delete_banks:
        typed_banks = input('Suppression des banques CPK. Saisir exactement "DELETE CPK BANKS": ')
        if typed_banks != DELETE_CPK_BANKS_CONFIRMATION:
            raise SystemExit("Confirmation banques incorrecte. Aucune action effectuée.")
    if args.delete_national_experts:
        typed_experts = input('Suppression nationale experts. Saisir exactement "DELETE NATIONAL EXPERTS LIST": ')
        if typed_experts != DELETE_NATIONAL_EXPERTS_CONFIRMATION:
            raise SystemExit("Confirmation experts nationale incorrecte. Aucune action effectuée.")


def create_backup(args: argparse.Namespace) -> str:
    backup_path = Path(args.backup_path or default_backup_path(args))
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = str(settings.database_url).replace("postgresql+asyncpg://", "postgresql://", 1)
    cmd = ["pg_dump", db_url, "-f", str(backup_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SystemExit(
            "Sauvegarde PostgreSQL échouée: pg_dump introuvable dans l'environnement d'exécution."
        ) from exc
    if result.returncode != 0:
        raise SystemExit(f"Sauvegarde PostgreSQL échouée: {result.stderr.strip() or result.stdout.strip()}")
    if not backup_path.exists() or backup_path.stat().st_size <= 0:
        raise SystemExit("Sauvegarde PostgreSQL échouée: fichier absent ou vide.")
    return str(backup_path)


async def execute_target(session, target: Target, organisation_id: int) -> int | None:
    if not await table_exists(session, target.table):
        return None
    if target.action in {"delete", "delete_optional"}:
        await assert_scoped_target(session, target)
        result = await session.execute(
            text(f"DELETE FROM {target.table} WHERE {target.where_sql}"),
            {ORG_PARAM: organisation_id},
        )
        return int(result.rowcount or 0)
    if target.action == "reset":
        await assert_scoped_target(session, target)
        if target.table == "caisse_centrale":
            # La session de caisse est refermée en même temps que les soldes :
            # `ouvertures_caisse` est vidée juste avant, une caisse restée
            # `est_ouverte` pointerait sur une ouverture qui n'existe plus et
            # bloquerait la réouverture.
            assignments = (
                "solde_usd = 0, solde_cdf = 0, "
                "est_ouverte = false, ouverte_le = NULL, ouverte_par_id = NULL"
            )
        elif target.table == "comptes_bancaires":
            assignments = "solde_initial = 0, solde_actuel = 0"
        elif target.table == "budget_postes":
            assignments = "montant_engage = 0, montant_paye = 0"
        elif target.table == "document_sequences":
            assignments = "counter = 0"
        elif target.table == "compta_sequences":
            assignments = "compteur = 0"
        else:
            raise RuntimeError(f"Reset non implémenté pour {target.table}")
        result = await session.execute(
            text(f"UPDATE {target.table} SET {assignments} WHERE {target.where_sql}"),
            {ORG_PARAM: organisation_id},
        )
        return int(result.rowcount or 0)
    raise RuntimeError(f"Action non supportée: {target.action}")


async def enable_admin_reset_mode(session) -> None:
    await session.execute(text(f"SET LOCAL {ADMIN_RESET_GUC} = 'on'"))


async def execute_national_target(session, target: Target) -> int | None:
    if not await table_exists(session, target.table):
        return None
    result = await session.execute(text(f"DELETE FROM {target.table}"))
    return int(result.rowcount or 0)


async def validate_budget_delete_report(report: dict[str, Any]) -> None:
    org = report.get("target_organisation") or {}
    if int(org.get("id") or 0) != 1 or str(org.get("slug") or "").lower() != "cpk":
        raise RuntimeError("Refus: la suppression budget 2026 est limitée à organisation_id=1 slug=cpk.")
    exercice = report.get("target_exercice")
    if not exercice or int(exercice.get("id") or 0) != 1 or int(exercice.get("annee") or 0) != 2026:
        raise RuntimeError("Refus: exercice budgétaire CPK 2026 attendu introuvable ou incohérent.")
    blockers = report.get("blockers") or []
    if blockers:
        raise RuntimeError(f"Refus: références opérationnelles budget 2026 encore présentes: {blockers}")


async def execute_budget_year_confirm(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    validate_confirm_allowed(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    require_confirmations(args)
    backup_path = create_backup(argparse.Namespace(**{**vars(args), "backup_path": args.backup_path or report["backup_path"]}))
    await validate_budget_delete_report(report)
    org_id = int(report["target_organisation"]["id"])
    exercice_id = int(report["target_exercice"]["id"])

    statements: tuple[tuple[str, str], ...] = (
        (
            "budget_audit_logs",
            "DELETE FROM budget_audit_logs WHERE organisation_id = :organisation_id "
            "AND (exercice_id = :exercice_id OR budget_poste_id IN ("
            "SELECT id FROM budget_postes WHERE organisation_id = :organisation_id AND exercice_id = :exercice_id))",
        ),
        (
            "compta_mapping_poste_budgetaire",
            "DELETE FROM compta_mapping_poste_budgetaire WHERE organisation_id = :organisation_id "
            "AND budget_poste_id IN (SELECT id FROM budget_postes WHERE organisation_id = :organisation_id AND exercice_id = :exercice_id)",
        ),
        (
            "service_rubriques",
            "DELETE FROM service_rubriques WHERE budget_poste_id IN ("
            "SELECT id FROM budget_postes WHERE organisation_id = :organisation_id AND exercice_id = :exercice_id)",
        ),
        (
            "budget_postes",
            "DELETE FROM budget_postes WHERE organisation_id = :organisation_id AND exercice_id = :exercice_id",
        ),
        (
            "budget_exercices",
            "DELETE FROM budget_exercices WHERE organisation_id = :organisation_id AND id = :exercice_id AND annee = 2026",
        ),
    )

    async with SessionLocal() as session:
        executed: list[dict[str, Any]] = []
        try:
            async with session.begin():
                for table, sql in statements:
                    result = await session.execute(text(sql), {ORG_PARAM: org_id, "exercice_id": exercice_id})
                    rows = int(result.rowcount or 0)
                    executed.append({"table": table, "action": "delete", "rows": rows})
                    print(f"delete {table}: {rows}")
        except Exception:
            await session.rollback()
            raise

    return {
        "mode": "CONFIRMED_EXECUTED",
        "operation": "DELETE_BUDGET_YEAR",
        "backup_path": backup_path,
        "target_organisation": report["target_organisation"],
        "year": report["year"],
        "target_exercice": report["target_exercice"],
        "executed": executed,
    }


async def execute_national_experts_confirm(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    validate_confirm_allowed(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    require_confirmations(args)
    backup_path = create_backup(argparse.Namespace(**{**vars(args), "backup_path": args.backup_path or report["backup_path"]}))

    statements: tuple[tuple[str, str], ...] = (
        ("category_changes_history", "DELETE FROM category_changes_history"),
        ("encaissements.expert_comptable_id", "UPDATE encaissements SET expert_comptable_id = NULL WHERE expert_comptable_id IS NOT NULL"),
        ("participants_transport.expert_comptable_id", "UPDATE participants_transport SET expert_comptable_id = NULL WHERE expert_comptable_id IS NOT NULL"),
        ("experts_comptables", "DELETE FROM experts_comptables"),
        ("imports_history", "DELETE FROM imports_history"),
    )

    async with SessionLocal() as session:
        executed: list[dict[str, Any]] = []
        try:
            async with session.begin():
                for table, sql in statements:
                    result = await session.execute(text(sql))
                    rows = int(result.rowcount or 0)
                    action = "set_null" if "SET expert_comptable_id" in sql else "delete"
                    executed.append({"table": table, "action": action, "rows": rows})
                    print(f"{action} {table}: {rows}")
        except Exception:
            await session.rollback()
            raise

    return {
        "mode": "CONFIRMED_EXECUTED",
        "operation": "DELETE_NATIONAL_EXPERTS_LIST",
        "scope": "national_global_all_tenants",
        "backup_path": backup_path,
        "executed": executed,
    }


async def execute_confirm(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    op_name = operation_name(args)
    if op_name == "delete_budget_year":
        return await execute_budget_year_confirm(args, report)
    if op_name == "delete_national_experts":
        return await execute_national_experts_confirm(args, report)

    validate_confirm_allowed(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    require_confirmations(args)
    backup_path = create_backup(args)
    org_id = int(report["target_organisation"]["id"])

    async with SessionLocal() as before_session:
        before = await collect_balances(before_session, org_id)
        await before_session.rollback()

    async with SessionLocal() as session:
        executed: list[dict[str, Any]] = []
        try:
            async with session.begin():
                await enable_admin_reset_mode(session)
                print("mode_admin_reset: actif pour cette transaction")
                for target in DELETE_TARGETS:
                    rowcount = await execute_target(session, target, org_id)
                    executed.append({"table": target.table, "action": target.action, "rows": rowcount})
                    print(f"{target.action} {target.table}: {rowcount}")
                for target in iter_reset_targets(delete_banks=args.delete_banks):
                    rowcount = await execute_target(session, target, org_id)
                    executed.append({"table": target.table, "action": target.action, "rows": rowcount})
                    print(f"{target.action} {target.table}: {rowcount}")
                if args.delete_banks:
                    for target in OPTIONAL_DELETE_TARGETS:
                        rowcount = await execute_target(session, target, org_id)
                        executed.append({"table": target.table, "action": target.action, "rows": rowcount})
                        print(f"{target.action} {target.table}: {rowcount}")
                if args.delete_national_experts:
                    for target in NATIONAL_EXPERT_DELETE_TARGETS:
                        rowcount = await execute_national_target(session, target)
                        executed.append({"table": target.table, "action": target.action, "rows": rowcount})
                        print(f"{target.action} {target.table}: {rowcount}")
        except Exception:
            await session.rollback()
            raise

    async with SessionLocal() as verify_session:
        after = await collect_balances(verify_session, org_id)
        await verify_session.rollback()

    return {
        "mode": "CONFIRMED_EXECUTED",
        "backup_path": backup_path,
        "target_organisation": report["target_organisation"],
        "balances_before": before,
        "balances_after": after,
        "executed": executed,
    }


async def main() -> None:
    args = parse_args()
    report = await collect_report(args)
    if args.confirm:
        result = await execute_confirm(args, report)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
