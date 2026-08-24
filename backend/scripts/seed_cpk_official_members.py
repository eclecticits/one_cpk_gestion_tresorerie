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

BUREAU_MEMBERS = [
    ("TUMBA KABALAMBI Jean Marie", "Président", "Président", "jeanmarie747@hotmail.com", "president"),
    ("MAMPASI MABAYA Dieudonné", "Vice-président(e)", "Vice-président", "dieudonne.mampasi@strong-nkuvu.nkv.cd", "president"),
    ("OKENDE MBUNGU Adolphe", "Rapporteur", "Rapporteur", "lapradelle@yahoo.fr", "rapporteur"),
    ("LIGBAKELO MAYKPEL Samy", "Rapporteur adjoint", "Rapporteur adjoint", "ligbakelo@yahoo.fr", "rapporteur"),
    ("BENGA NSUNGI Jolie Rachel", "Trésorier", "Trésorière", "joliebenga@agec-rdc.com", "tresorier"),
    ("BUKASA WA BUKASA Cédric", "Trésorier(e) adjoint", "Trésorier adjoint", "cedric.bukasa@gmail.com", "tresorier"),
]

COUNCIL_MEMBERS = [
    ("PANDI MVEMBA José Patience", "Membre du conseil", "jopandi@yahoo.fr", "validateur"),
    ("MASSALA PANGU Guelord", "Membre du conseil", "guelordmassala08@gmail.com", "validateur"),
    ("MBUDI MASUNDA Martin", "Membre du conseil", "mmbudimasunda@gmail.com", "validateur"),
    ("KIPAMPE KINDUELO LUMBU Lyvie", "Membre du conseil", "lyvie.kipampe@onec-rdc.org", "validateur"),
    ("KULE NONO Corneille", "Membre du conseil", "cornekule@gmail.com", "validateur"),
]

COMMISSION_PRESIDENTS = [
    ("DISC", "Commission Discipline", "MUAMBA TSHILUMBA Simon", "Président", "simon_master@yahoo.fr"),
    ("CT", "Commission Tableau", "NTIAKULU BAYAKISA Glodie", "Président", "glodie.ntiakuku@gmail.com"),
    ("STAG", "Commission de Stage & Examens", "LUNGONZO MBUY François", "Président", "flungonzo@gmail.com"),
    ("FORCO", "Commission Formation Continue", "VANGU KI-TULANDA Joseph", "Président", "josephvangu71@gmail.com"),
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
        service.is_active = True
        return service
    service = Service(organisation_id=org_id, code=code.upper(), libelle=libelle, is_active=True)
    session.add(service)
    await session.flush()
    created.append(f"service {code}")
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
    email: str,
    role_code: str,
    roles: dict[str, int],
    created: list[str],
) -> User:
    nom, prenom = split_name(full_name)
    email = email.lower().strip()
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
    email: str,
    function: ServiceMemberFunction,
    role_type: CommissionRole,
    custom_title: str,
    signer: bool,
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
    existing.email = email.lower().strip()
    existing.function_id = function.id
    existing.role_type = role_type
    existing.custom_title = custom_title
    existing.is_signer = signer


async def seed(commit: bool) -> None:
    created: list[str] = []
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True
        org = (
            await session.execute(select(Organisation).where(Organisation.slug == "cpk"))
        ).scalar_one()
        roles = await role_map(session)

        bureau = await ensure_service(session, org.id, "BR", "BUREAU", created)
        conseil = await ensure_service(session, org.id, "CP", "Conseil Provincial", created)

        for index, (full_name, function_label, title, email, role_code) in enumerate(BUREAU_MEMBERS, start=1):
            user = await ensure_user(session, org.id, bureau, full_name, email, role_code, roles, created)
            function = await ensure_function(session, org.id, bureau.id, function_label, index, created)
            await ensure_member(
                session,
                bureau,
                user,
                full_name,
                email,
                function,
                CommissionRole.PRESIDENT if title == "Président" else CommissionRole.MEMBRE,
                title,
                role_code in {"president", "tresorier"},
                created,
            )

        council_function = await ensure_function(session, org.id, conseil.id, "Membre du conseil", 1, created)
        for index, (full_name, function_label, title, email, role_code) in enumerate(BUREAU_MEMBERS, start=1):
            user = await ensure_user(session, org.id, conseil, full_name, email, role_code, roles, created)
            function = await ensure_function(session, org.id, conseil.id, function_label, index, created)
            await ensure_member(
                session,
                conseil,
                user,
                full_name,
                email,
                function,
                CommissionRole.PRESIDENT if title == "Président" else CommissionRole.MEMBRE,
                title,
                role_code in {"president", "tresorier"},
                created,
            )

        for full_name, title, email, role_code in COUNCIL_MEMBERS:
            user = await ensure_user(session, org.id, conseil, full_name, email, role_code, roles, created)
            await ensure_member(
                session,
                conseil,
                user,
                full_name,
                email,
                council_function,
                CommissionRole.MEMBRE,
                title,
                False,
                created,
            )

        for code, libelle, full_name, title, email in COMMISSION_PRESIDENTS:
            service = await ensure_service(session, org.id, code, libelle, created)
            user = await ensure_user(session, org.id, service, full_name, email, "president", roles, created)
            function = await ensure_function(session, org.id, service.id, title, 1, created)
            await ensure_member(
                session,
                service,
                user,
                full_name,
                email,
                function,
                CommissionRole.PRESIDENT,
                title,
                True,
                created,
            )
            service.responsable_id = user.id

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
