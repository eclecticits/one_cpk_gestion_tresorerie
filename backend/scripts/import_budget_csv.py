from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Iterable
from itertools import islice

from sqlalchemy import delete, select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetExercice, BudgetLigne, StatutBudget  # noqa: E402


def _normalize_amount(raw: str | None) -> Decimal:
    if raw is None:
        return Decimal("0")

    value = raw.strip().replace("\u00a0", "").replace(" ", "")
    if not value:
        return Decimal("0")

    value = value.replace("€", "").replace("$", "")
    if "," in value and "." in value:
        value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")

    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def _iter_rows(reader: Iterable[dict[str, str]], skip_rows: int) -> Iterable[dict[str, str]]:
    for index, row in enumerate(reader):
        if index < skip_rows:
            continue
        yield row


def _get_column_value(row: dict[str, str], column: str | None) -> str | None:
    if column is None:
        return None
    if column in row:
        return row.get(column)
    if column == "":
        for key in row:
            return row.get(key)
    return row.get(column)


async def import_budget_csv(
    file_path: str,
    annee: int,
    statut: StatutBudget,
    code_column: str,
    libelle_column: str,
    montant_column: str,
    type_value: str | None,
    delimiter: str,
    skip_header_rows: int,
    skip_rows: int,
    replace_existing: bool,
    append_existing: bool,
) -> None:
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
                await session.execute(delete(BudgetLigne).where(BudgetLigne.exercice_id == exercice.id))

        with open(file_path, newline="", encoding="utf-8") as handle:
            if skip_header_rows:
                reader = csv.DictReader(islice(handle, skip_header_rows, None), delimiter=delimiter)
            else:
                reader = csv.DictReader(handle, delimiter=delimiter)
            for row in _iter_rows(reader, skip_rows):
                code = (_get_column_value(row, code_column) or "").strip()
                if not code:
                    continue

                libelle = (_get_column_value(row, libelle_column) or "").strip()
                montant = _normalize_amount(_get_column_value(row, montant_column))

                session.add(
                    BudgetLigne(
                        exercice_id=exercice.id,
                        code=code,
                        libelle=libelle or code,
                        type=type_value,
                        montant_prevu=montant,
                    )
                )

        await session.commit()


def _parse_statut(value: str) -> StatutBudget:
    normalized = value.strip().upper()
    try:
        return StatutBudget[normalized]
    except KeyError as exc:
        options = ", ".join(item.name for item in StatutBudget)
        raise argparse.ArgumentTypeError(f"Statut invalide '{value}'. Options: {options}.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importer un budget CSV dans la base.")
    parser.add_argument("file", help="Chemin du fichier CSV")
    parser.add_argument("--annee", type=int, default=2026)
    parser.add_argument("--statut", type=_parse_statut, default=StatutBudget.VOTE)
    parser.add_argument("--code-column", default="RUBRIQUES")
    parser.add_argument("--libelle-column", default="LIBELLE")
    parser.add_argument("--montant-column", default="BUDGET 2026")
    parser.add_argument("--type", dest="type_value", default="DEPENSE")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--skip-header-rows", type=int, default=0)
    parser.add_argument("--skip-rows", type=int, default=0)
    parser.add_argument("--replace", action="store_true", help="Reimporte en ecrasant les lignes existantes.")
    parser.add_argument("--append", action="store_true", help="Ajoute des lignes a un exercice existant.")
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    await import_budget_csv(
        file_path=args.file,
        annee=args.annee,
        statut=args.statut,
        code_column=args.code_column,
        libelle_column=args.libelle_column,
        montant_column=args.montant_column,
        type_value=args.type_value,
        delimiter=args.delimiter,
        skip_header_rows=args.skip_header_rows,
        skip_rows=args.skip_rows,
        replace_existing=args.replace,
        append_existing=args.append,
    )
    print(f"Import termine pour {args.annee}.")


if __name__ == "__main__":
    asyncio.run(main())
