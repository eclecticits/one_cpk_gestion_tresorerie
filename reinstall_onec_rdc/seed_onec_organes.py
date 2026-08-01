#!/usr/bin/env python3
"""
Peuplement des organes ONEC dans la base onec_rdc.

Cree, par tenant (organisation) :
  - les commissions (table services),
  - le service "Bureau du Conseil",
  - les utilisateurs (bureau + presidents de commission) avec le ROLE EXISTANT
    correspondant a leur fonction (aucun privilege n'est redefini : on reutilise
    les roles deja presents dans la base),
  - les membres de commission (CommissionMember), les presidents en role PRESIDENT.

NE TOUCHE PAS aux comptes admin / super_admin (voir KEEP_USER_ROLES).
Idempotent : relancable sans creer de doublons.

Execution (voir RUNBOOK, etape 11) :
  # copie dans le conteneur puis :
  docker compose exec backend python /app/seed_onec_organes.py --dry-run
  docker compose exec backend python /app/seed_onec_organes.py --commit
Options :
  --dry-run   (defaut) simule et annule (rollback), affiche le plan.
  --commit    ecrit reellement en base.
  --purge     supprime d'abord les commissions/users NON admin du tenant cible
              (structure de test) avant de recreer. A utiliser apres --dry-run.
  --only CLE  limite a un tenant (conseil_national | conseil_kinshasa).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()


def _find_backend(p: Path) -> Path:
    for parent in [p.parent, *p.parents]:
        if (parent / "app").is_dir():
            return parent
    return p.parent


BACKEND_ROOT = _find_backend(HERE)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, func, select, text, update  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.commission_member import CommissionMember, CommissionRole  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.rbac import Role  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_service import user_services  # noqa: E402

# ------------------------- CONFIGURATION -------------------------
DATA_FILE = os.getenv("ONEC_DATA_FILE", str(HERE.parent / "data_onec_organes.json"))
EMAIL_DOMAIN = os.getenv("ONEC_EMAIL_DOMAIN", "onec-rdc.org")
DEFAULT_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD", "Onec2025")

# Comptes JAMAIS supprimes par --purge (role sur User.role, en minuscules)
KEEP_USER_ROLES = {"admin", "super_admin"}

# Fonction (dans le JSON) -> code de role EXISTANT dans la table roles
FUNCTION_ROLE = {
    "president": "president",
    "vice-president": "president",
    "rapporteur": "rapporteur",
    "rapporteur adjoint": "rapporteur",
    "tresorier": "tresorier",
    "tresoriere": "tresorier",
    "tresorier adjoint": "tresorier",
    "membre": "demandeur",
}
COMMISSION_PRESIDENT_ROLE = "president"          # role d'un president de commission
FALLBACK_ROLE = "demandeur"                       # si fonction inconnue
BUREAU_SERVICE = {"code": "BUR", "libelle": "Bureau du Conseil"}
# Creer aussi un compte de connexion pour les membres simples de commission ?
CREATE_LOGIN_FOR_COMMISSION_MEMBERS = False
# ------------------------------------------------------------------


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def slugify(s: str) -> str:
    s = strip_accents(s or "").lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def split_name(full: str) -> tuple[str, str]:
    """'TUMBA KABALAMBI Jean Marie' -> ('TUMBA KABALAMBI', 'Jean Marie')."""
    toks = full.split()
    nom, i = [], 0
    while i < len(toks) and toks[i] == toks[i].upper() and any(c.isalpha() for c in toks[i]):
        nom.append(toks[i])
        i += 1
    prenom = toks[i:]
    if not nom:
        nom, prenom = [toks[0]], toks[1:]
    if not prenom:
        prenom, nom = [nom[-1]], (nom[:-1] or [toks[0]])
    return " ".join(nom), " ".join(prenom)


def base_local_part(nom: str, prenom: str) -> str:
    p = slugify(prenom.split()[0]) if prenom else ""
    n = slugify(nom.split()[0]) if nom else ""
    return (f"{p}.{n}".strip(".")) or "membre"


class Stats:
    def __init__(self) -> None:
        self.orgs = 0
        self.services = 0
        self.users = 0
        self.members = 0
        self.deleted_users = 0
        self.deleted_services = 0
        self.lines: list[str] = []

    def log(self, msg: str) -> None:
        self.lines.append(msg)
        print(msg)


async def get_role_map(session) -> dict[str, int]:
    rows = (await session.execute(select(Role.code, Role.id))).all()
    return {code.lower(): rid for code, rid in rows}


async def get_or_create_org(session, slug: str, nom: str, stats: Stats) -> Organisation:
    org = (await session.execute(select(Organisation).where(Organisation.slug == slug))).scalar_one_or_none()
    if org:
        stats.log(f"  [org] existante : {org.nom} (id={org.id}, slug={slug})")
        return org
    org = Organisation(nom=nom, slug=slug, status_abonnement="ACTIVE", is_active=True)
    session.add(org)
    await session.flush()
    stats.orgs += 1
    stats.log(f"  [org] CREEE : {nom} (id={org.id}, slug={slug})")
    return org


async def purge_org_structure(session, org: Organisation, stats: Stats) -> None:
    svc_ids = select(Service.id).where(Service.organisation_id == org.id)
    await session.execute(delete(user_services).where(user_services.c.service_id.in_(svc_ids)))
    await session.execute(delete(CommissionMember).where(CommissionMember.service_id.in_(svc_ids)))
    from app.models.service_member_function import ServiceMemberFunction
    await session.execute(delete(ServiceMemberFunction).where(ServiceMemberFunction.organisation_id == org.id))
    try:
        from app.models.service_rubrique import ServiceRubrique
        await session.execute(delete(ServiceRubrique).where(ServiceRubrique.service_id.in_(svc_ids)))
    except Exception:
        pass
    await session.execute(
        update(Service).where(Service.organisation_id == org.id).values(responsable_id=None)
    )
    await session.execute(
        update(User).where(User.organisation_id == org.id).values(service_id=None)
    )
    keep = [r for r in KEEP_USER_ROLES]
    # Seule table PRESERVEE a FK NOT NULL vers users (hors tables deja videes) : user_roles.
    # On supprime ses lignes pour les users cibles avant de supprimer ces users.
    target_sql = (
        "IN (SELECT id FROM users WHERE organisation_id = :oid "
        "AND lower(coalesce(role,'')) NOT IN ('admin','super_admin'))"
    )
    if (await session.execute(text("SELECT to_regclass('public.user_roles')"))).scalar():
        await session.execute(text(f"DELETE FROM user_roles WHERE user_id {target_sql}"), {"oid": org.id})
    del_users = await session.execute(
        select(func.count()).select_from(User).where(
            User.organisation_id == org.id, func.lower(User.role).notin_(keep)
        )
    )
    n_users = del_users.scalar() or 0
    await session.execute(
        delete(User).where(User.organisation_id == org.id, func.lower(User.role).notin_(keep))
    )
    n_svc = (await session.execute(
        select(func.count()).select_from(Service).where(Service.organisation_id == org.id)
    )).scalar() or 0
    await session.execute(delete(Service).where(Service.organisation_id == org.id))
    stats.deleted_users += n_users
    stats.deleted_services += n_svc
    stats.log(f"  [purge] supprime : {n_users} user(s) non-admin, {n_svc} service(s)")


async def ensure_service(session, org: Organisation, code: str, libelle: str, stats: Stats) -> Service:
    svc = (await session.execute(
        select(Service).where(Service.organisation_id == org.id, func.upper(Service.code) == code.upper())
    )).scalar_one_or_none()
    if svc:
        svc.libelle = libelle
        svc.is_active = True
        return svc
    svc = Service(code=code.upper(), libelle=libelle, organisation_id=org.id, is_active=True)
    session.add(svc)
    await session.flush()
    stats.services += 1
    stats.log(f"    [service] {code} — {libelle} (id={svc.id})")
    return svc


async def ensure_user(session, org, service, full_name, fonction, role_code, email, used, stats) -> User:
    nom, prenom = split_name(full_name)
    if not email:
        local = base_local_part(nom, prenom)
        candidate = f"{local}@{EMAIL_DOMAIN}"
        k = 2
        while candidate.lower() in used:
            candidate = f"{local}{k}@{EMAIL_DOMAIN}"
            k += 1
        email = candidate
    email = email.strip().lower()
    used.add(email)
    role_map = session.info["role_map"]
    role_id = role_map.get((role_code or "").lower())

    user = (await session.execute(
        select(User).where(User.organisation_id == org.id, func.lower(User.email) == email)
    )).scalar_one_or_none()
    if user:
        user.nom = user.nom or nom
        user.prenom = user.prenom or prenom
        user.role = role_code
        user.role_id = role_id
        user.service_id = service.id if service else user.service_id
        user.active = True
        user.is_email_verified = True
        stats.log(f"      [user=] {email} ({fonction} -> {role_code})")
    else:
        user = User(
            email=email, nom=nom, prenom=prenom, role=role_code, role_id=role_id,
            service_id=service.id if service else None, organisation_id=org.id,
            active=True, must_change_password=True, is_first_login=True, is_email_verified=True,
            hashed_password=hash_password(DEFAULT_PASSWORD),
        )
        session.add(user)
        await session.flush()
        stats.users += 1
        stats.log(f"      [user+] {email} ({fonction} -> {role_code})")

    if service:
        link = (await session.execute(
            select(user_services.c.user_id).where(
                user_services.c.user_id == user.id, user_services.c.service_id == service.id
            )
        )).first()
        if link is None:
            await session.execute(user_services.insert().values(user_id=user.id, service_id=service.id))
    return user


async def ensure_member(session, service, user, full_name, email, role_type, title, signer, stats) -> None:
    existing = (await session.execute(
        select(CommissionMember).where(
            CommissionMember.service_id == service.id,
            func.lower(CommissionMember.full_name) == full_name.lower(),
        )
    )).scalar_one_or_none()
    if existing:
        existing.role_type = role_type
        existing.is_signer = signer
        existing.custom_title = title
        if user and not existing.user_id:
            existing.user_id = user.id
        return
    session.add(CommissionMember(
        service_id=service.id, user_id=(user.id if user else None), full_name=full_name,
        email=(email.strip().lower() if email else None), role_type=role_type,
        custom_title=title, is_signer=signer,
    ))
    stats.members += 1


async def process_tenant(session, t: dict, stats: Stats, do_purge: bool) -> None:
    slug = os.getenv(f"ONEC_SLUG_{t['cle'].upper()}", t["slug_defaut"])
    stats.log(f"\n=== TENANT {t['nom']} (cle={t['cle']}, slug={slug}) ===")
    org = await get_or_create_org(session, slug, t["nom"], stats)
    if do_purge:
        await purge_org_structure(session, org, stats)

    used_emails: set[str] = set()
    for e in (await session.execute(select(func.lower(User.email)).where(User.organisation_id == org.id))).all():
        used_emails.add(e[0])

    # Bureau
    bureau = await ensure_service(session, org, BUREAU_SERVICE["code"], BUREAU_SERVICE["libelle"], stats)
    for m in t.get("bureau", []):
        fonction = m["fonction"]
        role_code = FUNCTION_ROLE.get(fonction.lower(), FALLBACK_ROLE)
        u = await ensure_user(session, org, bureau, m["full_name"], fonction, role_code, m.get("email"), used_emails, stats)
        is_pres = fonction.lower() == "president"
        await ensure_member(
            session, bureau, u, m["full_name"], m.get("email"),
            CommissionRole.PRESIDENT if is_pres else CommissionRole.MEMBRE,
            fonction, signer=(role_code in {"president", "tresorier"}), stats=stats,
        )

    # Membres du conseil (hors bureau)
    for m in t.get("membres_conseil", []):
        role_code = FUNCTION_ROLE.get(m["fonction"].lower(), FALLBACK_ROLE)
        u = await ensure_user(session, org, bureau, m["full_name"], m["fonction"], role_code, m.get("email"), used_emails, stats)
        await ensure_member(session, bureau, u, m["full_name"], m.get("email"), CommissionRole.MEMBRE, m["fonction"], False, stats)

    # Commissions
    for c in t.get("commissions", []):
        svc = await ensure_service(session, org, c["code"], c["nom"], stats)
        pres_user = await ensure_user(
            session, org, svc, c["president"], "President de commission",
            COMMISSION_PRESIDENT_ROLE, c.get("president_email"), used_emails, stats,
        )
        await ensure_member(
            session, svc, pres_user, c["president"], c.get("president_email"),
            CommissionRole.PRESIDENT, "President", signer=True, stats=stats,
        )
        svc.responsable_id = pres_user.id
        for mem in c.get("membres", []):
            name = mem["full_name"] if isinstance(mem, dict) else str(mem)
            memail = mem.get("email") if isinstance(mem, dict) else None
            muser = None
            if CREATE_LOGIN_FOR_COMMISSION_MEMBERS:
                muser = await ensure_user(session, org, svc, name, "Membre", FALLBACK_ROLE, memail, used_emails, stats)
            await ensure_member(session, svc, muser, name, memail, CommissionRole.MEMBRE, "Membre", False, stats)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="ecrit reellement (sinon dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="simulation (defaut)")
    ap.add_argument("--purge", action="store_true", help="supprime la structure de test (non-admin) du tenant avant de recreer")
    ap.add_argument("--only", default=None, help="conseil_national | conseil_kinshasa")
    args = ap.parse_args()
    commit = args.commit and not args.dry_run

    data = json.loads(Path(DATA_FILE).read_text(encoding="utf-8"))
    tenants = [t for t in data["tenants"] if (args.only is None or t["cle"] == args.only)]

    stats = Stats()
    async with SessionLocal() as session:
        session.info["skip_tenant_scope"] = True  # bypass hooks tenant pour le seed
        session.info["role_map"] = await get_role_map(session)
        print(f"Roles existants: {sorted(session.info['role_map'])}")

        print("\nOrganisations actuelles dans la base :")
        for oid, onom, oslug in (await session.execute(
            select(Organisation.id, Organisation.nom, Organisation.slug).order_by(Organisation.id)
        )).all():
            print(f"  - id={oid}  {onom}  (slug={oslug})")

        for t in tenants:
            await process_tenant(session, t, stats, args.purge)

        if commit:
            await session.commit()
            mode = "COMMIT (ecrit)"
        else:
            await session.rollback()
            mode = "DRY-RUN (annule)"

    print("\n================ RESUME ================")
    print(f" Mode                 : {mode}")
    print(f" Organisations creees : {stats.orgs}")
    print(f" Services/commissions : {stats.services}")
    print(f" Utilisateurs crees   : {stats.users}")
    print(f" Membres commission   : {stats.members}")
    if args.purge:
        print(f" Users supprimes      : {stats.deleted_users}")
        print(f" Services supprimes   : {stats.deleted_services}")
    print(f" Mot de passe initial : {DEFAULT_PASSWORD}  (changement force a la 1ere connexion)")
    print("========================================")
    if not commit:
        print("Aucune ecriture effectuee. Relancez avec --commit pour appliquer.")


if __name__ == "__main__":
    asyncio.run(main())
