#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
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

PROVINCIAL_COUNCILS = {
    "cphk": {
        "council_label": "Conseil Provincial du Haut-Katanga",
        "members": [
            ("KILUBA MWANSA Elisée", "Président", "Président", "elisee.kiluba@pwc.com", "president"),
            (
                "TSHAMALA KALAMBAYI Eric",
                "Vice-président(e)",
                "Vice-Président",
                "eric.kalambayi@orkam-consulting.com",
                "president",
            ),
            ("MACUMU KABURABUZA Moïse", "Rapporteur", "Rapporteur", "macumumoise@gmail.com", "rapporteur"),
            (
                "MULUNDA KAZOKO Maurice",
                "Rapporteur adjoint",
                "Rapporteur Adjoint",
                "mauricemelder@gmail.com",
                "rapporteur",
            ),
            ("KINKELA ORELIS Michel", "Trésorier", "Trésorier", "michel.orelis@gmail.com", "tresorier"),
            (
                "MWAMBA WA MWAMBA Genthy Willy",
                "Trésorier(e) adjoint",
                "Trésorier Adjoint",
                "gentsmwamba@yahoo.fr",
                "tresorier",
            ),
        ],
    },
    "cpnk": {
        "council_label": "Conseil Provincial du Nord-Kivu",
        "members": [
            ("KAMBALE PALUKU Roger", "Président", "Président", "rogerkambalepaluku@gmail.com", "president"),
            ("KETU MIHIGO Désiré", "Vice-président(e)", "Vice-Président", "desyketu2@gmail.com", "president"),
            ("KAKULE VAHEMBI Guillain", "Rapporteur", "Rapporteur", "guilva2005@gmail.com", "rapporteur"),
            (
                "SHEKATSANA SHEMATARA Japhet",
                "Rapporteur adjoint",
                "Rapporteur adjoint",
                "jshekatsana@gmail.com",
                "rapporteur",
            ),
            ("MUTWILO KIMBILI Kharkevitch", "Trésorier", "Trésorier", "mutwikimbili@gmail.com", "tresorier"),
            ("MUDEKEREZA ZIGABE Severin", "Membre du conseil", "Membre", "wisechoicecabine@gmail.com", "validateur"),
            ("PALUKU SARATA Bruno", "Membre du conseil", "Membre", "brunosarata5569@gmail.com", "validateur"),
            ("IDUNGA BASINDILA Augustin", "Membre du conseil", "Membre", "idungaaugustin@gmail.com", "validateur"),
            ("PALUKU MBARAGHA Flavien", "Membre du conseil", "Membre", "flavienpalumba@gmail.com", "validateur"),
        ],
    },
    "cpsk": {
        "council_label": "Conseil Provincial du Sud-Kivu",
        "members": [
            ("HABAKARAMO TUUNGANE Berchmans", "Président", "Président", "berchytuungane@gmail.com", "president"),
            ("NAMUTUTU KUNGWA Diane-Esther", "Vice-président(e)", "Vice-Président", "kungwadiane@gmail.com", "president"),
            ("WABULAKOMBE BULAMBO Stanyslas", "Rapporteur", "Rapporteur", "wabulambo@gmail.com", "rapporteur"),
            ("KIPAKA BAENEKE François", "Trésorier", "Trésorier", "fbaenake@gmail.com", "tresorier"),
            ("MAHESHE MUSHAMBARHWA Cléophas", "Membre du conseil", "Membre", "cleomaheshe@gmail.com", "validateur"),
            ("MAOMBI MUSHI Fabien", "Membre du conseil", "Membre", "mamufabien@gmail.com", "validateur"),
            (
                "MUDEKUZA MUKUBAGANYI Philippe",
                "Membre du conseil",
                "Membre",
                "philomudekuza@gmail.com",
                "validateur",
            ),
            ("KUFUTAMA KOY Kafaire", "Membre du conseil", "Membre", "kafairekoy@gmail.com", "validateur"),
        ],
    },
}


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
    created.append(f"fonction {label} ({org_id})")
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
    email = email.lower().strip()
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


def commission_role(title: str) -> CommissionRole:
    return CommissionRole.PRESIDENT if strip_accents(title).lower().startswith("president") else CommissionRole.MEMBRE


async def seed(commit: bool, slugs: list[str]) -> None:
    created: list[str] = []
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True
        roles = await role_map(session)

        for slug in slugs:
            config = PROVINCIAL_COUNCILS[slug]
            org = (
                await session.execute(select(Organisation).where(Organisation.slug == slug))
            ).scalar_one()
            bureau = await ensure_service(session, org.id, "BR", "BUREAU", created)
            conseil = await ensure_service(session, org.id, "CP", config["council_label"], created)

            for index, (full_name, function_label, title, email, role_code) in enumerate(config["members"], start=1):
                role_type = commission_role(title)
                signer = role_code in {"president", "tresorier"}

                user = await ensure_user(session, org.id, bureau, full_name, email, role_code, roles, created)
                function = await ensure_function(session, org.id, bureau.id, function_label, index, created)
                await ensure_member(
                    session,
                    bureau,
                    user,
                    full_name,
                    email,
                    function,
                    role_type,
                    title,
                    signer,
                    created,
                )

                user = await ensure_user(session, org.id, conseil, full_name, email, role_code, roles, created)
                function = await ensure_function(session, org.id, conseil.id, function_label, index, created)
                await ensure_member(
                    session,
                    conseil,
                    user,
                    full_name,
                    email,
                    function,
                    role_type,
                    title,
                    signer,
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
    parser.add_argument(
        "--slug",
        action="append",
        choices=sorted(PROVINCIAL_COUNCILS),
        help="Limiter le seed à un conseil provincial. Répéter l'option si besoin.",
    )
    args = parser.parse_args()
    slugs = args.slug or sorted(PROVINCIAL_COUNCILS)
    asyncio.run(seed(commit=args.commit, slugs=slugs))


if __name__ == "__main__":
    main()
