from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict

from sqlalchemy import delete, select, update

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetPoste  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.service_rubrique import ServiceRubrique  # noqa: E402
from app.models import encaissement as _encaissement  # noqa: F401,E402
from app.models import requisition as _requisition  # noqa: F401,E402
from app.models import sortie_fonds as _sortie_fonds  # noqa: F401,E402


def _parent_code(code: str) -> str | None:
    if "." not in code:
        return None
    parts = [part.strip() for part in code.split(".") if part.strip()]
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1])


def _normalize_code(value: str) -> str:
    return value.strip().upper().replace(" ", "_")[:20]


async def run_migration(mapping_path: str, replace_existing: bool, dry_run: bool) -> None:
    with open(mapping_path, "r", encoding="utf-8") as handle:
        mapping = json.load(handle)

    async with SessionLocal() as session:
        postes_result = await session.execute(select(BudgetPoste))
        postes = postes_result.scalars().all()
        postes_by_code = {poste.code: poste for poste in postes}

        if replace_existing:
            await session.execute(update(BudgetPoste).values(parent_id=None))
            await session.execute(delete(ServiceRubrique))

        updated_parents = 0
        for poste in postes:
            parent_code = _parent_code(poste.code)
            if not parent_code:
                continue
            parent = postes_by_code.get(parent_code)
            if parent and poste.parent_id != parent.id:
                poste.parent_id = parent.id
                updated_parents += 1

        services_result = await session.execute(select(Service))
        services = services_result.scalars().all()
        services_by_code = {service.code.upper(): service for service in services}
        services_by_libelle = {service.libelle.lower(): service for service in services}

        links_added = 0
        links_by_service: dict[str, int] = defaultdict(int)
        created_services: list[str] = []

        for service_code, data in mapping.items():
            libelle = data.get("libelle", service_code)
            prefixes = [str(value).strip() for value in data.get("prefixes", []) if str(value).strip()]
            if not prefixes:
                continue

            normalized_code = _normalize_code(service_code)
            service = services_by_code.get(normalized_code)
            if service is None:
                service = services_by_libelle.get(libelle.lower())

            if service is None:
                service = Service(code=normalized_code, libelle=libelle, is_active=True)
                session.add(service)
                await session.flush()
                created_services.append(service.code)
                services_by_code[service.code.upper()] = service
                services_by_libelle[service.libelle.lower()] = service

            for prefix in prefixes:
                matching = [
                    poste
                    for poste in postes
                    if poste.code == prefix or poste.code.startswith(f"{prefix}.")
                ]
                if not matching:
                    continue

                existing_links_result = await session.execute(
                    select(ServiceRubrique.budget_poste_id).where(ServiceRubrique.service_id == service.id)
                )
                existing_links = {row[0] for row in existing_links_result.all()}

                for poste in matching:
                    if poste.id in existing_links:
                        continue
                    session.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste.id))
                    existing_links.add(poste.id)
                    links_added += 1
                    links_by_service[service.code] += 1

        if dry_run:
            await session.rollback()
            print(
                f"[DRY RUN] Parents maj: {updated_parents}, liens ajoutés: {links_added}, "
                f"services: {len(links_by_service)}."
            )
            if created_services:
                print(f"[DRY RUN] Services créés: {', '.join(sorted(created_services))}.")
            else:
                print("[DRY RUN] Services créés: aucun.")

            if links_by_service:
                print("[DRY RUN] Liens par service:")
                for service_code in sorted(links_by_service.keys()):
                    print(f"  - {service_code}: {links_by_service[service_code]}")
            return

        await session.commit()
        print(
            f"Migration terminée. Parents maj: {updated_parents}, "
            f"liens ajoutés: {links_added}."
        )
        if created_services:
            print(f"Services créés: {', '.join(sorted(created_services))}.")
        if links_by_service:
            print("Liens par service:")
            for service_code in sorted(links_by_service.keys()):
                print(f"  - {service_code}: {links_by_service[service_code]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recalcule parent_id des budget_postes et alimente service_rubriques via un mapping JSON."
    )
    parser.add_argument(
        "--mapping",
        default=os.path.join(os.path.dirname(__file__), "mapping_services.json"),
        help="Chemin du fichier JSON de mapping.",
    )
    parser.add_argument("--replace", action="store_true", help="Réinitialise parent_id et service_rubriques avant.")
    parser.add_argument("--dry-run", action="store_true", help="Valide sans écrire en base.")
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    await run_migration(args.mapping, args.replace, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
