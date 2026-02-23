from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy import delete, select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.service_rubrique import ServiceRubrique  # noqa: E402


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _resolve_column(
    df: pd.DataFrame,
    column: str | None,
    synonyms: set[str],
    required: bool = False,
) -> str | None:
    if column:
        if column in df.columns:
            return column
        raise ValueError(f"Colonne '{column}' introuvable dans le fichier.")

    normalized = {_normalize_header(col): col for col in df.columns}
    for name in synonyms:
        if name in normalized:
            return normalized[name]

    if required:
        raise ValueError(f"Colonne requise introuvable. Options attendues: {sorted(synonyms)}")
    return None


def _normalize_amount(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    raw = str(value).strip()
    if not raw:
        return Decimal("0")

    raw = raw.replace("\u00a0", "").replace(" ", "")
    raw = raw.replace("$", "").replace("€", "")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")

    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("0")


def _get_parent_code(code: str) -> str | None:
    if "." not in code:
        return None
    parts = [part.strip() for part in code.split(".") if part.strip()]
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1])


def _normalize_service_code(value: str) -> str:
    code = re.sub(r"[^A-Z0-9_]", "", value.strip().upper().replace(" ", "_"))
    return code[:20] or "SERVICE"


async def import_budget_excel(
    file_path: str,
    annee: int,
    statut: StatutBudget,
    sheet_name: str | int | None,
    code_column: str | None,
    libelle_column: str | None,
    montant_column: str | None,
    service_column: str | None,
    service_code_column: str | None,
    type_column: str | None,
    default_type: str | None,
    skip_rows: int,
    replace_existing: bool,
    append_existing: bool,
    link_services: bool,
    dry_run: bool,
) -> None:
    df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=skip_rows)

    code_col = _resolve_column(
        df,
        code_column,
        {"code", "rubrique", "rubriques", "ligne", "budgetcode"},
        required=True,
    )
    libelle_col = _resolve_column(
        df,
        libelle_column,
        {"designation", "libelle", "libell", "description", "intitule", "intitul"},
        required=True,
    )
    montant_col = _resolve_column(
        df,
        montant_column,
        {"montantprevu", "montant", "budget", "budget2026", "montantprevisionnel"},
        required=True,
    )
    service_col = _resolve_column(
        df,
        service_column,
        {"service", "commission", "structure"},
        required=False,
    )
    service_code_col = _resolve_column(
        df,
        service_code_column,
        {"servicecode", "codeservice"},
        required=False,
    )
    type_col = _resolve_column(
        df,
        type_column,
        {"type", "categorie"},
        required=False,
    )

    async with SessionLocal() as session:
        result = await session.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
        exercice = result.scalar_one_or_none()

        if exercice is not None and not replace_existing and not append_existing:
            raise RuntimeError(
                f"Un budget {annee} existe deja. Utilise --replace pour reimporter ou --append pour ajouter."
            )

        if exercice is None:
            exercice = BudgetExercice(annee=annee, statut=statut)
            session.add(exercice)
            await session.flush()
        else:
            exercice.statut = statut
            await session.flush()
            if replace_existing:
                await session.execute(delete(BudgetPoste).where(BudgetPoste.exercice_id == exercice.id))

        existing_postes = await session.execute(
            select(BudgetPoste).where(BudgetPoste.exercice_id == exercice.id)
        )
        postes_by_code = {poste.code: poste for poste in existing_postes.scalars().all()}

        existing_services = await session.execute(select(Service))
        services_by_key = {service.libelle.lower(): service for service in existing_services.scalars().all()}
        services_by_code = {service.code.upper(): service for service in services_by_key.values()}

        mapping_cache: set[tuple[int, int]] = set()
        service_links_to_add: list[ServiceRubrique] = []

        created_postes = 0
        updated_postes = 0

        for _, row in df.iterrows():
            raw_code = row.get(code_col) if code_col else None
            if raw_code is None or (isinstance(raw_code, float) and pd.isna(raw_code)):
                continue
            code = str(raw_code).strip()
            if not code:
                continue

            libelle = str(row.get(libelle_col, "")).strip() if libelle_col else code
            if not libelle:
                libelle = code

            montant = _normalize_amount(row.get(montant_col))
            parent_code = _get_parent_code(code)

            poste = postes_by_code.get(code)
            if poste is None:
                poste = BudgetPoste(
                    exercice_id=exercice.id,
                    code=code,
                    libelle=libelle,
                    parent_code=parent_code,
                    type=str(row.get(type_col)).strip() if type_col and row.get(type_col) else default_type,
                    montant_prevu=montant,
                )
                session.add(poste)
                postes_by_code[code] = poste
                created_postes += 1
            else:
                poste.libelle = libelle
                poste.parent_code = parent_code
                poste.type = str(row.get(type_col)).strip() if type_col and row.get(type_col) else poste.type or default_type
                poste.montant_prevu = montant
                updated_postes += 1

            if not link_services or service_col is None:
                continue

            raw_service = row.get(service_col)
            if raw_service is None or (isinstance(raw_service, float) and pd.isna(raw_service)):
                continue
            service_name = str(raw_service).strip()
            if not service_name:
                continue

            service_code = None
            if service_code_col is not None:
                raw_service_code = row.get(service_code_col)
                if raw_service_code is not None and not (isinstance(raw_service_code, float) and pd.isna(raw_service_code)):
                    service_code = str(raw_service_code).strip()

            service_key = service_name.lower()
            service = services_by_key.get(service_key)
            if service is None:
                service_code = service_code or _normalize_service_code(service_name)
                service = services_by_code.get(service_code.upper())
                if service is None:
                    service = Service(code=service_code, libelle=service_name, is_active=True)
                    session.add(service)
                    await session.flush()
                services_by_key[service_key] = service
                services_by_code[service.code.upper()] = service

            await session.flush()
            if poste.id is None:
                await session.flush()

            mapping_key = (service.id, poste.id)
            if mapping_key not in mapping_cache:
                mapping_cache.add(mapping_key)
                service_links_to_add.append(
                    ServiceRubrique(service_id=service.id, budget_poste_id=poste.id)
                )

        if service_links_to_add:
            session.add_all(service_links_to_add)

        await session.flush()

        for poste in postes_by_code.values():
            if poste.parent_code and poste.parent_id is None:
                parent = postes_by_code.get(poste.parent_code)
                if parent is None:
                    result = await session.execute(
                        select(BudgetPoste).where(
                            BudgetPoste.exercice_id == exercice.id,
                            BudgetPoste.code == poste.parent_code,
                        )
                    )
                    parent = result.scalar_one_or_none()
                if parent is not None:
                    poste.parent_id = parent.id

        if dry_run:
            await session.rollback()
            print(
                f"[DRY RUN] Postes crees: {created_postes}, postes mis a jour: {updated_postes}, "
                f"liens services: {len(service_links_to_add)}"
            )
            return

        await session.commit()
        print(
            f"Import termine: postes crees {created_postes}, postes mis a jour {updated_postes}, "
            f"liens services {len(service_links_to_add)}."
        )


def _parse_statut(value: str) -> StatutBudget:
    normalized = value.strip().upper()
    try:
        return StatutBudget[normalized]
    except KeyError as exc:
        options = ", ".join(item.name for item in StatutBudget)
        raise argparse.ArgumentTypeError(f"Statut invalide '{value}'. Options: {options}.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importer un budget Excel dans la base.")
    parser.add_argument("file", help="Chemin du fichier Excel (.xlsx)")
    parser.add_argument("--annee", type=int, default=2026)
    parser.add_argument("--statut", type=_parse_statut, default=StatutBudget.VOTE)
    parser.add_argument("--sheet", dest="sheet_name", default=None)
    parser.add_argument("--code-column", default=None)
    parser.add_argument("--libelle-column", default=None)
    parser.add_argument("--montant-column", default=None)
    parser.add_argument("--service-column", default=None)
    parser.add_argument("--service-code-column", default=None)
    parser.add_argument("--type-column", default=None)
    parser.add_argument("--default-type", default=None)
    parser.add_argument("--skip-rows", type=int, default=0)
    parser.add_argument("--replace", action="store_true", help="Reimporte en ecrasant les lignes existantes.")
    parser.add_argument("--append", action="store_true", help="Ajoute des lignes a un exercice existant.")
    parser.add_argument("--link-services", action="store_true", help="Associe les rubriques aux services.")
    parser.add_argument("--dry-run", action="store_true", help="Valide sans ecrire en base.")
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    await import_budget_excel(
        file_path=args.file,
        annee=args.annee,
        statut=args.statut,
        sheet_name=args.sheet_name,
        code_column=args.code_column,
        libelle_column=args.libelle_column,
        montant_column=args.montant_column,
        service_column=args.service_column,
        service_code_column=args.service_code_column,
        type_column=args.type_column,
        default_type=args.default_type,
        skip_rows=args.skip_rows,
        replace_existing=args.replace,
        append_existing=args.append,
        link_services=args.link_services,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
