from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app.db.session import SessionLocal


DEFAULT_SLUG = "load-test-20260803"


@dataclass
class TableCount:
    table_name: str
    count: int


async def resolve_org_id(slug: str, expected_org_id: int | None) -> int:
    async with SessionLocal() as db:
        row = (
            await db.execute(
                text("select id from organisations where slug = :slug"),
                {"slug": slug},
            )
        ).first()
        if row is None:
            raise SystemExit(f"Organisation introuvable: {slug}")
        org_id = int(row[0])
        if expected_org_id is not None and expected_org_id != org_id:
            raise SystemExit(f"Refus: l'organisation {slug} a id={org_id}, pas {expected_org_id}")
        return org_id


async def organisation_table_counts(org_id: int) -> list[TableCount]:
    async with SessionLocal() as db:
        tables = (
            await db.execute(
                text(
                    """
                    select table_name
                    from information_schema.columns
                    where table_schema = 'public'
                      and column_name = 'organisation_id'
                    order by table_name
                    """
                )
            )
        ).scalars().all()
        counts: list[TableCount] = []
        for table_name in tables:
            quoted = '"' + table_name.replace('"', '""') + '"'
            count = (
                await db.execute(
                    text(f"select count(*) from {quoted} where organisation_id = :org_id"),
                    {"org_id": org_id},
                )
            ).scalar_one()
            if int(count) > 0:
                counts.append(TableCount(table_name=table_name, count=int(count)))
        expert_count = (
            await db.execute(
                text("select count(*) from experts_comptables where numero_ordre like 'LT/%'")
            )
        ).scalar_one()
        if int(expert_count) > 0:
            counts.append(TableCount(table_name="experts_comptables[numero_ordre LT/%]", count=int(expert_count)))
        return counts


async def delete_load_test_data(org_id: int) -> None:
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(text("delete from role_permissions where role_id in (select id from roles where code like 'load_test_%')"))
            await db.execute(text("delete from roles where code like 'load_test_%'"))
            await db.execute(text("delete from experts_comptables where numero_ordre like 'LT/%'"))

            await db.execute(text("delete from encaissement_articles where encaissement_id in (select id from encaissements where organisation_id = :org_id)"), {"org_id": org_id})
            await db.execute(text("delete from payment_history where encaissement_id in (select id from encaissements where organisation_id = :org_id)"), {"org_id": org_id})
            await db.execute(text("delete from encaissements where organisation_id = :org_id"), {"org_id": org_id})

            await db.execute(text("delete from lignes_requisition where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from requisition_annexes where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from requisition_approvers where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from requisition_status_history where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from requisitions where organisation_id = :org_id"), {"org_id": org_id})

            await db.execute(text("delete from service_rubriques where service_id in (select id from services where organisation_id = :org_id)"), {"org_id": org_id})
            await db.execute(text("delete from user_services where user_id in (select id from users where organisation_id = :org_id)"), {"org_id": org_id})
            await db.execute(text("delete from users where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from comptes_bancaires where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from banques where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from caisse_centrale where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from budget_postes where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from budget_exercices where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from services where organisation_id = :org_id"), {"org_id": org_id})
            await db.execute(text("delete from organisations where id = :org_id and slug = :slug"), {"org_id": org_id, "slug": DEFAULT_SLUG})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nettoyage explicite des donnees de charge ONEC Smart")
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument("--confirm", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    org_id = await resolve_org_id(args.slug, args.org_id)
    counts = await organisation_table_counts(org_id)
    print(f"Organisation cible: slug={args.slug} id={org_id}")
    for item in counts:
        print(f"{item.table_name}: {item.count}")
    if not args.confirm:
        print("Mode dry-run. Ajouter --confirm pour supprimer dans une transaction.")
        return
    await delete_load_test_data(org_id)
    print("Nettoyage termine.")


if __name__ == "__main__":
    asyncio.run(main())
