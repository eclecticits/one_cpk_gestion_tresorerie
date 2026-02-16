from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


TABLES = [
    ("requisitions", "reference_numero"),
    ("remboursements_transport", "reference_numero"),
    ("sorties_fonds", "reference_numero"),
    ("encaissements", "numero_recu"),
]


async def run_fix(dry_run: bool) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL manquant. Ex: export DATABASE_URL=postgresql+asyncpg://user:pass@host/db")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        for table, column in TABLES:
            count_sql = text(
                f"""
                SELECT COUNT(*) FROM public.{table}
                WHERE {column} LIKE '%-ONE-CPK-%'
                """
            )
            count = (await conn.execute(count_sql)).scalar_one() or 0
            print(f"{table}.{column}: {count} ligne(s) à corriger")
            if not dry_run and count:
                update_sql = text(
                    f"""
                    UPDATE public.{table}
                    SET {column} = REPLACE({column}, '-ONE-CPK-', '-ONEC-CPK-')
                    WHERE {column} LIKE '%-ONE-CPK-%'
                    """
                )
                await conn.execute(update_sql)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Remplace ONE-CPK par ONEC-CPK dans les numéros existants.")
    parser.add_argument("--dry-run", action="store_true", help="Affiche le nombre de lignes à corriger sans modifier.")
    args = parser.parse_args()
    asyncio.run(run_fix(args.dry_run))


if __name__ == "__main__":
    main()
