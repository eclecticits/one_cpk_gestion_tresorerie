from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import func, insert, select

# Ensure /app is in sys.path when executed in the container.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_service import user_services  # noqa: E402


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_service_code(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).upper()
    if normalized == "ADMIN":
        return "ADM"
    return normalized


def _normalize_service_libelle(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split())
    if normalized.lower() in {"administration", "administrations"}:
        return "Administration"
    return normalized


def _service_label_match_expr():
    normalized_expr = func.regexp_replace(func.lower(func.btrim(Service.libelle)), r"\s+", " ", "g")
    return normalized_expr.in_(["administration", "administrations"])


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} manquant.")
    return value


async def main() -> None:
    org_slug = _require_env("ORG_SLUG").lower()
    org_name = _require_env("ORG_NAME")
    admin_email = _require_env("ADMIN_EMAIL").lower()
    admin_password = _require_env("ADMIN_PASSWORD")

    admin_prenom = os.getenv("ADMIN_PRENOM", "Admin").strip() or "Admin"
    admin_nom = os.getenv("ADMIN_NOM", "User").strip() or "User"
    admin_role = os.getenv("ADMIN_ROLE", "admin").strip() or "admin"
    plan_status = os.getenv("ORG_PLAN_STATUS", "ACTIVE").strip() or "ACTIVE"

    service_code = _normalize_service_code(os.getenv("SERVICE_CODE", "ADM"))
    service_libelle = _normalize_service_libelle(os.getenv("SERVICE_LIBELLE", "Administration"))

    async with SessionLocal() as session:
        org_res = await session.execute(select(Organisation).where(Organisation.slug == org_slug))
        org = org_res.scalar_one_or_none()
        if org is None:
            org = Organisation(
                nom=org_name,
                slug=org_slug,
                status_abonnement=plan_status,
                is_active=True,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            session.add(org)
            await session.flush()
            print(f"created organisation: {org.slug} (id={org.id})")
        else:
            org.nom = org_name
            org.status_abonnement = plan_status or org.status_abonnement
            org.is_active = True
            org.updated_at = _utcnow()
            await session.flush()
            print(f"updated organisation: {org.slug} (id={org.id})")

        service_res = await session.execute(
            select(Service).where(
                Service.organisation_id == org.id,
                (func.regexp_replace(func.upper(func.btrim(Service.code)), r"\s+", " ", "g").in_(["ADM", "ADMIN"]))
                | _service_label_match_expr(),
            )
        )
        service = service_res.scalar_one_or_none()
        if service is None:
            service = Service(
                code=service_code,
                libelle=service_libelle,
                organisation_id=org.id,
                is_active=True,
            )
            session.add(service)
            await session.flush()
            print(f"created service: {service.code} (id={service.id})")
        else:
            service.libelle = service_libelle
            service.is_active = True
            await session.flush()
            print(f"updated service: {service.code} (id={service.id})")

        user_res = await session.execute(
            select(User).where(User.email == admin_email, User.organisation_id == org.id)
        )
        user = user_res.scalar_one_or_none()
        if user is None:
            user = User(
                email=admin_email,
                nom=admin_nom,
                prenom=admin_prenom,
                role=admin_role,
                active=True,
                must_change_password=False,
                is_first_login=False,
                is_email_verified=True,
                organisation_id=org.id,
                service_id=service.id,
                hashed_password=hash_password(admin_password),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            session.add(user)
            await session.flush()
            print(f"created admin: {user.email} (id={user.id})")
        else:
            user.nom = user.nom or admin_nom
            user.prenom = user.prenom or admin_prenom
            user.role = admin_role or user.role
            user.organisation_id = org.id
            user.service_id = user.service_id or service.id
            user.active = True
            user.must_change_password = False
            user.is_first_login = False
            user.is_email_verified = True
            user.hashed_password = hash_password(admin_password)
            user.updated_at = _utcnow()
            await session.flush()
            print(f"updated admin: {user.email} (id={user.id})")

        link_res = await session.execute(
            select(user_services.c.user_id)
            .where(user_services.c.user_id == user.id, user_services.c.service_id == service.id)
        )
        if link_res.first() is None:
            await session.execute(
                insert(user_services).values(user_id=user.id, service_id=service.id)
            )
            print("linked admin to service")

        await session.commit()
        print("seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
