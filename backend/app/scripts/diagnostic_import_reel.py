"""Diagnostic (lecture seule) de l'etat du tenant avant import des donnees reelles.

Aucune ecriture en base : la session est ouverte, interrogee, puis annulee
(rollback). A lancer dans le conteneur backend :

    docker compose -p onec_smart exec backend python -m app.scripts.diagnostic_import_reel
    docker compose -p onec_smart exec backend python -m app.scripts.diagnostic_import_reel --output-json diag_cpk.json

Objectif : verifier « ensemble d'abord » ce qui existe deja (organisation,
budget 2026 + postes, services, banques, caisse, experts) et ce qu'il reste a
charger, et confirmer que les codes budgetaires utilises dans le journal Excel
existent bien dans le budget de la base.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.db.session import SessionLocal

try:
    from app.core.config import settings
except Exception:  # pragma: no cover - diagnostic robuste
    settings = None


# --- Codes budgetaires effectivement utilises dans le journal 2026 (caisse +
# --- Equity + TMB), normalises. Sert au controle de correspondance avec la base.
JOURNAL_CODES: tuple[str, ...] = (
    "I.3.1", "I.3.2", "I.3.3", "I.3.4", "I.3.5", "I.3.6", "I.3.8",
    "I.6.1", "I.7.1", "I.7.3", "I.7.4", "I.7.5",
    "II.2.1.1", "II.2.1.6",
    "II.2.10.1", "II.2.10.2", "II.2.10.3", "II.2.10.4", "II.2.10.5",
    "II.2.10.6", "II.2.10.7", "II.2.10.8", "II.2.10.9",
    "II.2.11", "II.2.12.1",
    "II.2.2.2", "II.2.2.3", "II.2.2.5",
    "II.2.4.1", "II.2.4.2", "II.2.5.1",
    "II.2.6.1", "II.2.6.3",
    "II.2.7.1", "II.2.7.2", "II.2.7.3",
    "II.2.8.1", "II.2.9.1",
)

# Tables operationnelles a compter (doivent etre a ~0 si l'app est « vide »).
OPERATION_TABLES: tuple[tuple[str, str], ...] = (
    ("encaissements", "organisation_id = :org"),
    ("sorties_fonds", "organisation_id = :org"),
    ("requisitions", "organisation_id = :org"),
    ("lignes_requisition", "organisation_id = :org"),
    ("ordres_decaissement", "organisation_id = :org"),
    ("retours_caisse", "organisation_id = :org"),
    ("regularisations_caisse", "organisation_id = :org"),
    ("transferts_internes", "organisation_id = :org"),
    ("remboursements_transport", "organisation_id = :org"),
    ("ouvertures_caisse", "organisation_id = :org"),
    ("clotures", "organisation_id = :org"),
    ("dossiers_requisition", "organisation_id = :org"),
    ("compta_ecritures", "organisation_id = :org"),
    ("clients", "organisation_id = :org"),
)


def normalize_code(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper().replace(" ", "")
    s = re.sub(r"\.+", ".", s).rstrip(".")
    return s or None


async def table_exists(session, table: str) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=:t)"
            ),
            {"t": table},
        )
    )


async def column_exists(session, table: str, column: str) -> bool:
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name=:c)"
            ),
            {"t": table, "c": column},
        )
    )


async def count_where(session, table: str, where: str, params: dict) -> int | None:
    if not await table_exists(session, table):
        return None
    try:
        return int(await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params) or 0)
    except Exception:  # pragma: no cover - table presente mais colonne absente
        return None


async def resolve_org(session, args) -> dict[str, Any]:
    if args.organisation_id:
        q = text("SELECT id, slug, nom, devise_preferee FROM organisations WHERE id=:id")
        row = (await session.execute(q, {"id": args.organisation_id})).mappings().first()
    else:
        slug = (args.tenant or "cpk").strip()
        q = text("SELECT id, slug, nom, devise_preferee FROM organisations WHERE lower(slug)=lower(:s)")
        row = (await session.execute(q, {"s": slug})).mappings().first()
    if row is None:
        raise SystemExit("Organisation introuvable (slug par defaut: cpk). Aucune action.")
    return dict(row)


async def collect(args) -> dict[str, Any]:
    async with SessionLocal() as session:
        org = await resolve_org(session, args)
        org_id = int(org["id"])
        params = {"org": org_id}
        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": getattr(settings, "env", None) if settings else None,
            "organisation": org,
            "annee_budget": args.annee,
        }

        # --- Budget : exercices + postes de l'annee ciblee -------------------
        exercices = []
        if await table_exists(session, "budget_exercices"):
            exercices = [
                dict(r)
                for r in (
                    await session.execute(
                        text(
                            "SELECT id, annee, statut FROM budget_exercices "
                            "WHERE organisation_id=:org ORDER BY annee"
                        ),
                        params,
                    )
                ).mappings().all()
            ]
        report["budget_exercices"] = exercices

        exercice = next((e for e in exercices if int(e["annee"]) == args.annee), None)
        budget_block: dict[str, Any] = {"exercice_present": exercice is not None}
        if exercice and await table_exists(session, "budget_postes"):
            ex_id = int(exercice["id"])
            p = {"org": org_id, "ex": ex_id}
            budget_block["exercice_id"] = ex_id
            budget_block["statut"] = exercice["statut"]
            budget_block["nb_postes_total"] = int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM budget_postes "
                        "WHERE organisation_id=:org AND exercice_id=:ex AND is_deleted=false"
                    ),
                    p,
                )
                or 0
            )
            budget_block["montant_prevu_total"] = str(
                await session.scalar(
                    text(
                        "SELECT COALESCE(SUM(montant_prevu),0) FROM budget_postes "
                        "WHERE organisation_id=:org AND exercice_id=:ex AND is_deleted=false"
                    ),
                    p,
                )
            )
            db_rows = (
                await session.execute(
                    text(
                        "SELECT code, montant_prevu, montant_engage, montant_paye "
                        "FROM budget_postes WHERE organisation_id=:org AND exercice_id=:ex "
                        "AND is_deleted=false"
                    ),
                    p,
                )
            ).mappings().all()
            db_by_norm = {normalize_code(r["code"]): dict(r) for r in db_rows}
            present, missing = [], []
            for code in JOURNAL_CODES:
                (present if code in db_by_norm else missing).append(code)
            budget_block["codes_journal_total"] = len(JOURNAL_CODES)
            budget_block["codes_journal_presents"] = len(present)
            budget_block["codes_journal_manquants"] = missing
        report["budget"] = budget_block

        # --- Referentiels : services, banques, comptes, caisse, experts ------
        if await table_exists(session, "services"):
            report["services"] = [
                dict(r)
                for r in (
                    await session.execute(
                        text(
                            "SELECT id, code, libelle, is_active FROM services "
                            "WHERE organisation_id=:org ORDER BY code"
                        ),
                        params,
                    )
                ).mappings().all()
            ]

        if await table_exists(session, "banques"):
            report["banques"] = [
                dict(r)
                for r in (
                    await session.execute(
                        text("SELECT id, nom, code, is_active FROM banques WHERE organisation_id=:org ORDER BY nom"),
                        params,
                    )
                ).mappings().all()
            ]

        if await table_exists(session, "comptes_bancaires"):
            report["comptes_bancaires"] = [
                dict(r)
                for r in (
                    await session.execute(
                        text(
                            "SELECT intitule, numero_compte, devise, solde_initial, solde_actuel, "
                            "is_principal, account_type FROM comptes_bancaires "
                            "WHERE organisation_id=:org ORDER BY intitule"
                        ),
                        params,
                    )
                ).mappings().all()
            ]

        if await table_exists(session, "caisse_centrale"):
            report["caisse_centrale"] = dict(
                (
                    await session.execute(
                        text(
                            "SELECT solde_usd, solde_cdf, est_ouverte, ouverte_le "
                            "FROM caisse_centrale WHERE organisation_id=:org LIMIT 1"
                        ),
                        params,
                    )
                ).mappings().first()
                or {}
            )

        # experts_comptables : table nationale (pas de organisation_id)
        if await table_exists(session, "experts_comptables"):
            report["experts_comptables_total_national"] = int(
                await session.scalar(text("SELECT count(*) FROM experts_comptables")) or 0
            )

        # --- Sequences de documents -----------------------------------------
        if await table_exists(session, "document_sequences"):
            report["document_sequences"] = [
                dict(r)
                for r in (
                    await session.execute(
                        text(
                            "SELECT doc_type, year, service_id, counter FROM document_sequences "
                            "WHERE tenant_id=:org ORDER BY doc_type, year"
                        ),
                        params,
                    )
                ).mappings().all()
            ]

        # --- Volumes operationnels (doivent etre ~0 si app vide) -------------
        ops: dict[str, Any] = {}
        for table, where in OPERATION_TABLES:
            ops[table] = await count_where(session, table, where, params)
        report["operations"] = ops

        await session.rollback()
        return report


def human_summary(r: dict[str, Any]) -> str:
    org = r.get("organisation", {})
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("DIAGNOSTIC IMPORT REEL - lecture seule (aucune ecriture)")
    lines.append("=" * 72)
    lines.append(f"Organisation : {org.get('nom')} (id={org.get('id')}, slug={org.get('slug')}, devise={org.get('devise_preferee')})")
    lines.append(f"Environnement: {r.get('environment')}")
    lines.append("")

    b = r.get("budget", {})
    lines.append("-- BUDGET --------------------------------------------------------------")
    exs = ", ".join(f"{e['annee']}({e['statut']})" for e in r.get("budget_exercices", [])) or "AUCUN"
    lines.append(f"Exercices budgetaires : {exs}")
    if b.get("exercice_present"):
        lines.append(
            f"Exercice {r.get('annee_budget')} : id={b.get('exercice_id')} statut={b.get('statut')} "
            f"postes={b.get('nb_postes_total')} montant_prevu_total={b.get('montant_prevu_total')}"
        )
        miss = b.get("codes_journal_manquants", [])
        lines.append(
            f"Codes du journal presents dans la base : {b.get('codes_journal_presents')}/{b.get('codes_journal_total')}"
        )
        if miss:
            lines.append(f"  ⚠ CODES MANQUANTS ({len(miss)}) : {', '.join(miss)}")
        else:
            lines.append("  ✓ Tous les codes du journal existent dans le budget de la base.")
    else:
        lines.append(f"⚠ Aucun exercice budgetaire {r.get('annee_budget')} dans la base pour cette organisation.")
    lines.append("")

    lines.append("-- REFERENTIELS --------------------------------------------------------")
    lines.append(f"Services        : {len(r.get('services', []))}")
    for s in r.get("services", [])[:30]:
        lines.append(f"    - [{s.get('code')}] {s.get('libelle')}")
    lines.append(f"Banques         : {len(r.get('banques', []))}")
    for bq in r.get("banques", []):
        lines.append(f"    - {bq.get('nom')}")
    cbs = r.get("comptes_bancaires", [])
    lines.append(f"Comptes banc.   : {len(cbs)}")
    for c in cbs:
        lines.append(
            f"    - {c.get('intitule')} [{c.get('devise')}] init={c.get('solde_initial')} actuel={c.get('solde_actuel')}"
        )
    cc = r.get("caisse_centrale", {})
    if cc:
        lines.append(
            f"Caisse centrale : USD={cc.get('solde_usd')} CDF={cc.get('solde_cdf')} ouverte={cc.get('est_ouverte')}"
        )
    else:
        lines.append("Caisse centrale : (aucune ligne)")
    lines.append(f"Experts (national) : {r.get('experts_comptables_total_national')}")
    lines.append("")

    lines.append("-- VOLUMES OPERATIONNELS (attendu ~0 si app vide) ----------------------")
    for table, n in r.get("operations", {}).items():
        flag = "" if (n in (0, None)) else "  <-- contient des donnees"
        shown = "table absente" if n is None else n
        lines.append(f"    {table:26s}: {shown}{flag}")
    lines.append("")
    lines.append("Fin du diagnostic (lecture seule).")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnostic lecture seule avant import des donnees reelles.")
    p.add_argument("--tenant", default="cpk", help="Slug du tenant (defaut: cpk).")
    p.add_argument("--organisation-id", type=int, default=None, help="Id numerique de l'organisation.")
    p.add_argument("--annee", type=int, default=2026, help="Annee budgetaire a controler (defaut: 2026).")
    p.add_argument("--output-json", default=None, help="Ecrire le rapport complet dans un fichier JSON.")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    report = await collect(args)
    print(human_summary(report))
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nRapport JSON ecrit : {args.output_json}")


if __name__ == "__main__":
    asyncio.run(main())
