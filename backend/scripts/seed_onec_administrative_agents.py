#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.commission_member import CommissionMember, CommissionRole
from app.models.organisation import Organisation
from app.models.rbac import Role
from app.models.service import Service
from app.models.service_member_function import ServiceMemberFunction
from app.models.user import User
from app.models.user_service import user_services


DEFAULT_PASSWORD = "Onec2025"

TENANTS = {
    "cn": {
        "nom": "Conseil National",
        "is_active": True,
        "status_abonnement": "ACTIVE",
        "limite_utilisateurs": 20,
    },
    "cpk": {
        "nom": "Conseil Provincial de Kinshasa",
        "is_active": True,
        "status_abonnement": "ACTIVE",
        "limite_utilisateurs": 20,
    },
    "cphk": {
        "nom": "Conseil Provincial du Haut-Katanga",
        "is_active": False,
        "status_abonnement": "SUSPENDED",
        "limite_utilisateurs": 5,
    },
    "cpsk": {
        "nom": "Conseil Provincial de Sud-Kivu",
        "is_active": False,
        "status_abonnement": "SUSPENDED",
        "limite_utilisateurs": 5,
    },
    "cpnk": {
        "nom": "Conseil Provincial du Nord-Kivu",
        "is_active": False,
        "status_abonnement": "SUSPENDED",
        "limite_utilisateurs": 5,
    },
}

AGENTS = [
    ("cn", "Constant MORO", "Secrétaire Exécutif", "constantmoro@onecrdc.com", "secretaire_executif"),
    ("cn", "Gloria BUTUBA", "Assistant du Conseil National", "gloriabutuba@onecrdc.com", "agent_documents"),
    ("cn", "Joseph MAVINGA", "Comptable National / CN", "josephmavinga@onecrdc.com", "comptable"),
    ("cn", "Galilée KIBAWA", "Webmaster Conseil National", "galileekibawa@onecrdc.com", "agent_documents"),
    (
        "cn",
        "Laurène BITOTA",
        "Chef de Service du Système d'Information / Conseil National",
        "laurenebitota@onecrdc.com",
        "validateur",
    ),
    ("cn", "Hézir MBANGALALA", "Assistant Commission de Stage Conseil National", "hezirmayala@onecrdc.com", "agent_documents"),
    ("cn", "Trésor PALUKU", "Financier / Conseil National", "tresorpaluku@onecrdc.com", "comptable"),
    ("cn", "Fabrice NGANGA", "Assistant Commission Contrôle Qualité / Conseil National", "fabricenganga@onecrdc.com", "agent_documents"),
    (
        "cpk",
        "Esther BIMPE",
        "Réceptionniste et Assistante à la Trésorerie / Conseil Provincial de Kinshasa",
        "estherbimpe@onecrdc.com",
        "agent_courrier",
    ),
    (
        "cpk",
        "Nicole MUSWAMBA",
        "Responsable RH & Juridique / Conseil Provincial de Kinshasa",
        "nicolemuswamba@onecrdc.com",
        "validateur",
    ),
    (
        "cpk",
        "Alain Luc LUKA",
        "Secrétaire Permanent / Conseil Provincial de Kinshasa",
        "alainluka@onecrdc.com",
        "secretaire_permanant",
    ),
    (
        "cpk",
        "Annie NDONA",
        "Agent de Logistique et entretien / Conseil Provincial de Kinshasa",
        "annie.ndona@onec-rdc.org",
        "agent_documents",
    ),
    (
        "cpk",
        "Jared KITIMINI",
        "Chargé de Transport / Conseil Provincial de Kinshasa",
        "jaredkit0074@gmail.com",
        "agent_documents",
    ),
    (
        "cpk",
        "Christian KIDIKALA",
        "Secrétaire Administratif / Conseil Provincial de Kinshasa",
        "kidikala@onecrdc.com",
        "secretaire_permanant",
    ),
    (
        "cphk",
        "Samuel SONGOLO",
        "Assistant comptable / Conseil Provincial du Haut Katanga",
        "samuelkikasa1@gmail.com",
        "comptable",
    ),
    (
        "cphk",
        "Jean-Marie TSHILUMBU",
        "Consultant Administratif / Conseil Provincial du Haut Katanga",
        "maryjoe.bilenge1@gmail.com",
        "validateur",
    ),
    (
        "cpsk",
        "Rachel LINGONGE",
        "Secrétaire Administratif / Conseil Provincial du Sud Kivu",
        "lingongesafi@gmail.com",
        "secretaire_permanant",
    ),
    (
        "cpnk",
        "Hélène ALIMA AWAZI",
        "Secrétaire Administratif / Conseil Provincial du Nord Kivu",
        "alimaawazi1316@gmail.com",
        "secretaire_permanant",
    ),
]


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.split()
    if len(parts) <= 1:
        return full_name, ""
    last_name = parts[-1]
    first_names = " ".join(parts[:-1])
    return last_name, first_names


async def role_map(session) -> dict[str, int]:
    rows = (await session.execute(select(Role.code, Role.id))).all()
    return {code.lower(): role_id for code, role_id in rows}


async def ensure_org(session, slug: str, created: list[str]) -> Organisation:
    cfg = TENANTS[slug]
    org = (await session.execute(select(Organisation).where(Organisation.slug == slug))).scalar_one_or_none()
    if org:
        return org
    org = Organisation(
        nom=cfg["nom"],
        slug=slug,
        is_active=cfg["is_active"],
        status_abonnement=cfg["status_abonnement"],
        limite_utilisateurs=cfg["limite_utilisateurs"],
    )
    session.add(org)
    await session.flush()
    created.append(f"tenant {slug}")
    return org


async def ensure_administration(session, org: Organisation, created: list[str]) -> Service:
    service = (
        await session.execute(
            select(Service).where(Service.organisation_id == org.id, func.upper(Service.code) == "ADM")
        )
    ).scalar_one_or_none()
    if service:
        service.libelle = "Administration"
        service.is_active = True
        return service
    service = Service(organisation_id=org.id, code="ADM", libelle="Administration", is_active=True)
    session.add(service)
    await session.flush()
    created.append(f"service ADM {org.slug}")
    return service


async def ensure_function(
    session,
    org_id: int,
    service_id: int,
    label: str,
    sort_order: int,
    created: list[str],
) -> ServiceMemberFunction:
    existing = (
        await session.execute(
            select(ServiceMemberFunction).where(
                ServiceMemberFunction.organisation_id == org_id,
                ServiceMemberFunction.service_id == service_id,
                func.lower(ServiceMemberFunction.label) == label.lower(),
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.sort_order = min(existing.sort_order or sort_order, sort_order)
        existing.is_active = True
        return existing
    function = ServiceMemberFunction(
        organisation_id=org_id,
        service_id=service_id,
        label=label,
        sort_order=sort_order,
        is_active=True,
        is_default=False,
    )
    session.add(function)
    await session.flush()
    created.append(f"fonction {label} ({org_id})")
    return function


async def ensure_user(
    session,
    org: Organisation,
    service: Service,
    full_name: str,
    email: str,
    role_code: str,
    roles: dict[str, int],
    created: list[str],
) -> User:
    nom, prenom = split_name(full_name)
    email = email.lower().strip()
    user = (
        await session.execute(
            select(User).where(User.organisation_id == org.id, func.lower(User.email) == email)
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            organisation_id=org.id,
            email=email,
            nom=nom,
            prenom=prenom,
            hashed_password=hash_password(DEFAULT_PASSWORD),
            role=role_code,
            role_id=roles.get(role_code),
            service_id=service.id,
            active=True,
            must_change_password=True,
            is_first_login=True,
            is_email_verified=True,
        )
        session.add(user)
        await session.flush()
        created.append(f"user {email} ({org.slug})")
    else:
        user.nom = nom
        user.prenom = prenom
        user.role = role_code
        user.role_id = roles.get(role_code)
        user.service_id = service.id
        user.active = True
        user.is_email_verified = True

    link = (
        await session.execute(
            select(user_services.c.user_id).where(
                user_services.c.user_id == user.id,
                user_services.c.service_id == service.id,
            )
        )
    ).first()
    if link is None:
        await session.execute(user_services.insert().values(user_id=user.id, service_id=service.id))
    return user


async def ensure_member(
    session,
    service: Service,
    user: User,
    full_name: str,
    email: str,
    function: ServiceMemberFunction,
    created: list[str],
) -> None:
    existing = (
        await session.execute(
            select(CommissionMember).where(
                CommissionMember.service_id == service.id,
                or_(
                    func.lower(CommissionMember.email) == email.lower().strip(),
                    func.lower(CommissionMember.full_name) == full_name.lower().strip(),
                ),
            ).order_by(CommissionMember.id.asc()).limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = CommissionMember(service_id=service.id, full_name=full_name)
        session.add(existing)
        created.append(f"member {full_name} -> {service.code}")
    existing.user_id = user.id
    existing.full_name = full_name
    existing.email = email.lower().strip()
    existing.function_id = function.id
    existing.role_type = CommissionRole.MEMBRE
    existing.custom_title = function.label
    existing.is_signer = False


async def seed(commit: bool) -> None:
    created: list[str] = []
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True
        roles = await role_map(session)

        function_orders: dict[tuple[int, str], int] = {}
        for slug, full_name, function_label, email, role_code in AGENTS:
            org = await ensure_org(session, slug, created)
            service = await ensure_administration(session, org, created)
            key = (service.id, strip_accents(function_label).lower())
            if key not in function_orders:
                function_orders[key] = len(function_orders) + 1
            function = await ensure_function(
                session,
                org.id,
                service.id,
                function_label,
                function_orders[key],
                created,
            )
            user = await ensure_user(session, org, service, full_name, email, role_code, roles, created)
            await ensure_member(session, service, user, full_name, email, function, created)

        if commit:
            await session.commit()
            mode = "COMMIT"
        else:
            await session.rollback()
            mode = "DRY-RUN"

    print(f"{mode} {datetime.now(timezone.utc).isoformat()}")
    print(f"Objets créés: {len(created)}")
    for item in created:
        print(f"  - {item}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(seed(commit=args.commit))


if __name__ == "__main__":
    main()
