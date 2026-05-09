from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.print_settings import PrintSettings
from app.models.rbac import Permission, Role
from app.models.service import Service
from app.models.service_member_function import ServiceMemberFunction
from app.models.system_settings import SystemSettings
from app.models.user import User


async def _resolve_org(session, tenant_ref: str) -> Organisation | None:
    tenant_ref = tenant_ref.strip().lower()
    stmt = select(Organisation)
    if tenant_ref.isdigit():
        stmt = stmt.where(Organisation.id == int(tenant_ref))
    else:
        stmt = stmt.where(func.lower(Organisation.slug) == tenant_ref)
    res = await session.execute(stmt.limit(1))
    return res.scalar_one_or_none()


async def _collect_org_snapshot(session, org: Organisation) -> dict:
    user_count = await session.scalar(select(func.count(User.id)).where(User.organisation_id == org.id))
    roles_res = await session.execute(
        select(func.coalesce(User.role, ""), func.count(User.id))
        .where(User.organisation_id == org.id)
        .group_by(User.role)
        .order_by(User.role.asc())
    )
    roles_present = {str(role or ""): int(count or 0) for role, count in roles_res.all()}

    services_res = await session.execute(
        select(Service.code, Service.libelle).where(Service.organisation_id == org.id).order_by(Service.code.asc())
    )
    services = [f"{code}::{libelle}" for code, libelle in services_res.all()]

    functions_res = await session.execute(
        select(Service.code, ServiceMemberFunction.label)
        .join(Service, Service.id == ServiceMemberFunction.service_id)
        .where(
            ServiceMemberFunction.organisation_id == org.id,
            ServiceMemberFunction.is_active.is_(True),
        )
        .order_by(Service.code.asc(), ServiceMemberFunction.sort_order.asc(), ServiceMemberFunction.label.asc())
    )
    functions_by_service: dict[str, list[str]] = defaultdict(list)
    for service_code, label in functions_res.all():
        functions_by_service[str(service_code)].append(str(label))

    org_settings_exists = await session.scalar(
        select(func.count(OrganisationSettings.id)).where(OrganisationSettings.organisation_id == org.id)
    )
    print_settings_exists = await session.scalar(
        select(func.count(PrintSettings.id)).where(PrintSettings.organisation_id == org.id)
    )
    system_settings_exists = await session.scalar(
        select(func.count(SystemSettings.id)).where(SystemSettings.organisation_id == org.id)
    )
    caisse_exists = await session.scalar(
        select(func.count(CaisseCentrale.id)).where(CaisseCentrale.organisation_id == org.id)
    )

    cash_res = await session.execute(
        select(CompteBancaire.devise)
        .where(CompteBancaire.organisation_id == org.id, CompteBancaire.account_type == "CASH")
        .order_by(CompteBancaire.devise.asc())
    )
    cash_currencies = [str(row[0]) for row in cash_res.all()]

    ex_res = await session.execute(
        select(BudgetExercice.id, BudgetExercice.annee)
        .where(BudgetExercice.organisation_id == org.id)
        .order_by(BudgetExercice.annee.asc())
    )
    exercices = ex_res.all()
    budget_years = [int(row[1]) for row in exercices]

    budget_codes_res = await session.execute(
        select(BudgetPoste.code)
        .where(BudgetPoste.organisation_id == org.id, BudgetPoste.is_deleted.is_(False))
        .order_by(BudgetPoste.code.asc())
    )
    budget_codes = [str(code) for code in budget_codes_res.scalars().all()]

    global_roles = [str(code) for code in (await session.execute(select(Role.code).order_by(Role.code.asc()))).scalars().all()]
    global_permissions = [
        str(code) for code in (await session.execute(select(Permission.code).order_by(Permission.code.asc()))).scalars().all()
    ]
    module_permissions = [code for code in global_permissions if code.startswith("menu_")]

    return {
        "org": org,
        "user_count": int(user_count or 0),
        "roles_present": roles_present,
        "services": services,
        "functions_by_service": dict(functions_by_service),
        "org_settings_exists": bool(org_settings_exists),
        "print_settings_exists": bool(print_settings_exists),
        "system_settings_exists": bool(system_settings_exists),
        "caisse_exists": bool(caisse_exists),
        "cash_currencies": cash_currencies,
        "budget_years": budget_years,
        "budget_codes": budget_codes,
        "global_roles": global_roles,
        "global_permissions": global_permissions,
        "module_permissions": module_permissions,
    }


def _diff_sets(reference: list[str], target: list[str]) -> tuple[list[str], list[str]]:
    ref_set = set(reference)
    target_set = set(target)
    return sorted(ref_set - target_set), sorted(target_set - ref_set)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Auditer le socle d'un tenant.")
    parser.add_argument("--tenant", required=True, help="Slug ou identifiant du tenant cible")
    parser.add_argument("--reference", default="cpk", help="Slug ou identifiant du tenant de référence")
    args = parser.parse_args()

    async with SessionLocal() as session:
        target = await _resolve_org(session, args.tenant)
        if target is None:
            print(f"tenant_exists: non ({args.tenant})")
            return
        print(f"tenant_exists: oui ({target.slug}, id={target.id})")
        print(f"tenant_active: {'oui' if target.is_active else 'non'}")

        target_snapshot = await _collect_org_snapshot(session, target)
        print(f"user_count: {target_snapshot['user_count']}")
        print(f"roles_present: {target_snapshot['roles_present']}")
        print(f"global_roles: {target_snapshot['global_roles']}")
        print(f"global_permissions_count: {len(target_snapshot['global_permissions'])}")
        print(f"modules_enabled_globally: {target_snapshot['module_permissions']}")
        print(f"services: {target_snapshot['services']}")
        print(f"member_functions: {target_snapshot['functions_by_service']}")
        print(
            "settings_present:"
            f" org={target_snapshot['org_settings_exists']}"
            f" print={target_snapshot['print_settings_exists']}"
            f" system={target_snapshot['system_settings_exists']}"
            f" caisse={target_snapshot['caisse_exists']}"
        )
        print(f"cash_currencies: {target_snapshot['cash_currencies']}")
        print(f"budget_years: {target_snapshot['budget_years']}")
        print(f"budget_codes_count: {len(target_snapshot['budget_codes'])}")

        reference = await _resolve_org(session, args.reference)
        if reference is None:
            print(f"reference_exists: non ({args.reference})")
            return

        reference_snapshot = await _collect_org_snapshot(session, reference)
        print(f"reference_tenant: {reference.slug} (id={reference.id})")

        missing_services, extra_services = _diff_sets(reference_snapshot["services"], target_snapshot["services"])
        missing_budget_codes, extra_budget_codes = _diff_sets(reference_snapshot["budget_codes"], target_snapshot["budget_codes"])
        missing_cash, extra_cash = _diff_sets(reference_snapshot["cash_currencies"], target_snapshot["cash_currencies"])

        print("diff_services_missing_from_target:", missing_services)
        print("diff_services_extra_in_target:", extra_services)
        print("diff_cash_missing_from_target:", missing_cash)
        print("diff_cash_extra_in_target:", extra_cash)
        print("diff_budget_codes_missing_from_target_count:", len(missing_budget_codes))
        print("diff_budget_codes_extra_in_target_count:", len(extra_budget_codes))

        ref_functions = sorted(f"{service}:{label}" for service, labels in reference_snapshot["functions_by_service"].items() for label in labels)
        target_functions = sorted(f"{service}:{label}" for service, labels in target_snapshot["functions_by_service"].items() for label in labels)
        missing_functions, extra_functions = _diff_sets(ref_functions, target_functions)
        print("diff_member_functions_missing_from_target:", missing_functions)
        print("diff_member_functions_extra_in_target:", extra_functions)


if __name__ == "__main__":
    asyncio.run(main())
