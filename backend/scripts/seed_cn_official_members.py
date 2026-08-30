#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.commission_member import CommissionMember, CommissionRole  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.rbac import Role  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.service_member_function import ServiceMemberFunction  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_service import user_services  # noqa: E402


DEFAULT_PASSWORD = "Onec2025"
ORG_SLUG = "cn"

BUREAU_MEMBERS = [
    ("TUMBA KABALAMBI Jean Marie", "Président", "Président", "president"),
    ("KILUBA MWANSA Elisée", "Vice-président(e)", "Vice-président", "president"),
    ("MAMPASI MABAYA Dieudonné", "Rapporteur", "Rapporteur", "rapporteur"),
    ("HABAKARAMO TUUNGANE Berchmans", "Rapporteur adjoint", "Rapporteur adjoint", "rapporteur"),
    ("NAMUTUTU KUNGWA Diane Esther", "Trésorier", "Trésorière", "tresorier"),
    ("KAMBALE PALUKU Roger", "Trésorier(e) adjoint", "Trésorier adjoint", "tresorier"),
]

COMMISSION_PRESIDENTS = [
    (
        "CT",
        "Commission du Tableau",
        "NTUMBA MPUTU Odilon",
        "Président de la Commission du Tableau",
    ),
    (
        "STAG",
        "Commission de stage",
        "KAMBAJA MUBALAMATA Bruno",
        "Président de la Commission de stage",
    ),
    (
        "NORM",
        "Commission de normes professionnelles",
        "MUKULA MIJI Jean Jacques",
        "Président de la Commission de normes professionnelles",
    ),
    (
        "DISC",
        "Commission de discipline",
        "LUNGANGI KITUNDU Françoise",
        "Présidente de la Commission de discipline",
    ),
    (
        "FORCO",
        "Commission de formation continue",
        "KALAMBAY NYINDU Raphaël",
        "Président de la Commission de formation continue",
    ),
    (
        "CQ",
        "Commission de contrôle de qualité",
        "MBAYA KANGOMBA MBABU Maurice",
        "Président de la Commission de contrôle de qualité",
    ),
]

COUNCIL_MEMBERS = [
    ("TSHAMALA KALAMBAYI Eric", "Membre du Conseil national", "Membre", "validateur"),
    ("KETU MIHIGO Désiré", "Membre du Conseil national", "Membre", "validateur"),
]


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.split()
    last_name: list[str] = []
    index = 0
    while index < len(parts):
        normalized = strip_accents(parts[index])
        if normalized.upper() != normalized or not any(char.isalpha() for char in normalized):
            break
        last_name.append(parts[index])
        index += 1
    if not last_name:
        return parts[0], " ".join(parts[1:])
    return " ".join(last_name), " ".join(parts[index:])


def technical_email(full_name: str) -> str:
    normalized = strip_accents(full_name).lower()
    normalized = re.sub(r"[^a-z0-9]+", ".", normalized).strip(".")
    return f"cn.{normalized}@onec.invalid"


async def role_map(session) -> dict[str, int]:
    rows = (await session.execute(select(Role.code, Role.id))).all()
    return {code.lower(): role_id for code, role_id in rows}


async def ensure_service(session, org_id: int, code: str, libelle: str, created: list[str]) -> Service:
    service = (
        await session.execute(
            select(Service).where(Service.organisation_id == org_id, func.upper(Service.code) == code.upper())
        )
    ).scalar_one_or_none()
    if service:
        service.libelle = libelle
        service.is_active = True
        return service
    service = Service(organisation_id=org_id, code=code.upper(), libelle=libelle, is_active=True)
    session.add(service)
    await session.flush()
    created.append(f"service {code.upper()} {libelle}")
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
        existing.sort_order = sort_order
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
    created.append(f"fonction {label}")
    return function


async def ensure_user(
    session,
    org_id: int,
    service: Service,
    full_name: str,
    role_code: str,
    roles: dict[str, int],
    created: list[str],
) -> User:
    nom, prenom = split_name(full_name)
    email = technical_email(full_name)
    user = (
        await session.execute(
            select(User).where(User.organisation_id == org_id, func.lower(User.email) == email)
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            organisation_id=org_id,
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
        created.append(f"user {email}")
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
    function: ServiceMemberFunction,
    role_type: CommissionRole,
    custom_title: str,
    signer: bool,
    created: list[str],
) -> None:
    email = user.email.lower().strip()
    existing = (
        await session.execute(
            select(CommissionMember).where(
                CommissionMember.service_id == service.id,
                or_(
                    func.lower(CommissionMember.email) == email,
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
    existing.email = email
    existing.function_id = function.id
    existing.role_type = role_type
    existing.custom_title = custom_title
    existing.is_signer = signer


async def seed(commit: bool) -> None:
    created: list[str] = []
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True
        org = (
            await session.execute(select(Organisation).where(Organisation.slug == ORG_SLUG))
        ).scalar_one()
        roles = await role_map(session)

        bureau = await ensure_service(session, org.id, "BR", "BUREAU", created)
        conseil = await ensure_service(session, org.id, "CN", "Conseil National", created)

        for index, (full_name, function_label, title, role_code) in enumerate(BUREAU_MEMBERS, start=1):
            user = await ensure_user(session, org.id, bureau, full_name, role_code, roles, created)
            function = await ensure_function(session, org.id, bureau.id, function_label, index, created)
            await ensure_member(
                session,
                bureau,
                user,
                full_name,
                function,
                CommissionRole.PRESIDENT if title == "Président" else CommissionRole.MEMBRE,
                title,
                role_code in {"president", "tresorier"},
                created,
            )

        for index, (full_name, function_label, title, role_code) in enumerate(BUREAU_MEMBERS, start=1):
            user = await ensure_user(session, org.id, conseil, full_name, role_code, roles, created)
            function = await ensure_function(session, org.id, conseil.id, function_label, index, created)
            await ensure_member(
                session,
                conseil,
                user,
                full_name,
                function,
                CommissionRole.PRESIDENT if title == "Président" else CommissionRole.MEMBRE,
                title,
                role_code in {"president", "tresorier"},
                created,
            )

        commission_offset = len(BUREAU_MEMBERS)
        for index, (code, libelle, full_name, title) in enumerate(COMMISSION_PRESIDENTS, start=1):
            role_code = "president"
            user = await ensure_user(session, org.id, conseil, full_name, role_code, roles, created)
            council_function = await ensure_function(
                session,
                org.id,
                conseil.id,
                title,
                commission_offset + index,
                created,
            )
            await ensure_member(
                session,
                conseil,
                user,
                full_name,
                council_function,
                CommissionRole.PRESIDENT,
                title,
                True,
                created,
            )

            service = await ensure_service(session, org.id, code, libelle, created)
            user = await ensure_user(session, org.id, service, full_name, role_code, roles, created)
            president_function = await ensure_function(session, org.id, service.id, "Président", 1, created)
            await ensure_member(
                session,
                service,
                user,
                full_name,
                president_function,
                CommissionRole.PRESIDENT,
                title,
                True,
                created,
            )
            service.responsable_id = user.id

        member_function = await ensure_function(
            session,
            org.id,
            conseil.id,
            "Membre du Conseil national",
            commission_offset + len(COMMISSION_PRESIDENTS) + 1,
            created,
        )
        for full_name, _function_label, title, role_code in COUNCIL_MEMBERS:
            user = await ensure_user(session, org.id, conseil, full_name, role_code, roles, created)
            await ensure_member(
                session,
                conseil,
                user,
                full_name,
                member_function,
                CommissionRole.MEMBRE,
                title,
                False,
                created,
            )

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
