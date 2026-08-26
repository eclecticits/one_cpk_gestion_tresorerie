"""Fabrique le fichier de contexte lu par les scenarios k6.

Pourquoi des jetons pre-frappes plutot qu'un /auth/login par utilisateur
virtuel : `POST /auth/login` est limite a 3 appels par tranche de 3 minutes et
PAR IP (backend/app/api/v1/endpoints/auth.py:307, cle IP dans
backend/app/core/limiter.py:33), doublé d'un verrou Redis par
(IP, tenant, email) — backend/app/api/v1/endpoints/auth.py:67. Depuis un
generateur unique, tout scenario qui se connecte mesure l'anti-bruteforce, pas
l'application. C'est deja le choix retenu par
backend/scripts/load_campaign.py:451 (`--auth-mode direct-token`) et
documente dans docs/PERFORMANCE_LOAD_AUDIT_20260803.md.

Le parcours de connexion reste mesure, mais par un scenario dedie a tres bas
debit (voir k6/journeys.js, scenario `login_probe`).

Execution DANS le conteneur backend (acces au JWT_SECRET et a la base) :

    docker compose cp seed/mint_tokens.py backend:/app/mint_tokens.py
    docker compose exec backend python /app/mint_tokens.py --out /app/context.json
    docker compose cp backend:/app/context.json k6/context.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
for candidate in ("/app", PROJECT_ROOT):
    if candidate not in sys.path and os.path.isdir(os.path.join(candidate, "app")):
        sys.path.insert(0, candidate)

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetExercice, BudgetPoste  # noqa: E402
from app.models.compte_bancaire import CompteBancaire  # noqa: E402
from app.models.ligne_requisition import LigneRequisition  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.requisition import Requisition  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402

# Roles court-circuites par has_permission (backend/app/api/deps.py:560-563).
ROLES_PLEIN_DROIT = {"super_admin", "admin"}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Genere context.json pour k6")
    parser.add_argument("--slug", default="load-test-20260803")
    parser.add_argument("--out", default="/app/context.json")
    parser.add_argument("--users", type=int, default=400, help="Nombre de jetons a frapper")
    parser.add_argument("--ttl-minutes", type=int, default=480, help="Duree de vie des jetons (campagne longue)")
    parser.add_argument("--approuvees", type=int, default=20000, help="Requisitions APPROUVEE exportees pour le scenario sortie de fonds")
    parser.add_argument("--login-password", default="Load_Test_2026!", help="Mot de passe des comptes semés par load_campaign.py")
    args = parser.parse_args()

    # create_access_token lit la duree depuis les settings : on l'allonge le
    # temps de la frappe pour qu'un tir de 30 minutes ne perime pas ses jetons.
    settings.access_token_expire_minutes = args.ttl_minutes

    async with SessionLocal() as db:
        org = (await db.execute(select(Organisation).where(Organisation.slug == args.slug))).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"Organisation '{args.slug}' introuvable.")

        services = (
            await db.execute(
                select(Service.id, Service.code)
                .where(Service.organisation_id == org.id, Service.is_active.is_(True))
                .order_by(Service.id)
            )
        ).all()
        if not services:
            raise SystemExit("Aucun service actif : lancez seed_volume.py d'abord.")

        exercice = (
            await db.execute(
                select(BudgetExercice.id, BudgetExercice.annee)
                .where(BudgetExercice.organisation_id == org.id)
                .order_by(BudgetExercice.annee.desc())
                .limit(1)
            )
        ).first()

        postes = (
            await db.execute(
                select(BudgetPoste.id, BudgetPoste.code, BudgetPoste.libelle, BudgetPoste.type)
                .where(
                    BudgetPoste.organisation_id == org.id,
                    BudgetPoste.exercice_id == exercice[0],
                    BudgetPoste.is_deleted.is_(False),
                    BudgetPoste.active.is_(True),
                )
                .limit(2000)
            )
        ).all()
        recettes = [{"id": p[0], "code": p[1], "libelle": p[2]} for p in postes if (p[3] or "") == "RECETTE"]
        depenses = [{"id": p[0], "code": p[1], "libelle": p[2]} for p in postes if (p[3] or "") == "DEPENSE"]
        if not recettes or not depenses:
            raise SystemExit("Postes budgetaires recette/depense manquants.")

        compte = (
            await db.execute(
                select(CompteBancaire.id, CompteBancaire.devise)
                .where(
                    CompteBancaire.organisation_id == org.id,
                    CompteBancaire.is_active.is_(True),
                    CompteBancaire.account_type == "BANK",
                )
                .limit(1)
            )
        ).first()

        rows = (
            await db.execute(
                select(User.id, User.role, User.service_id, User.email)
                .where(
                    User.organisation_id == org.id,
                    User.email.like("load-%@example.test"),
                    User.active.is_(True),
                )
                .order_by(User.email)
                .limit(args.users)
            )
        ).all()
        if len(rows) < 4:
            raise SystemExit("Moins de 4 comptes de charge : relancez load_campaign.py --stages ''.")

        utilisateurs = []
        for row in rows:
            token, _exp = create_access_token(
                subject=str(row[0]),
                role=row[1],
                org_id=org.id,
                org_uuid=str(org.uuid),
                org_slug=org.slug,
                plan_status=org.status_abonnement,
            )
            utilisateurs.append(
                {
                    "id": str(row[0]),
                    "email": row[3],
                    "role": row[1],
                    "service_id": row[2],
                    "token": token,
                    "plein_droit": (row[1] or "").lower() in ROLES_PLEIN_DROIT,
                }
            )

        pleins = [u for u in utilisateurs if u["plein_droit"]]
        if len(pleins) < 2:
            raise SystemExit(
                "Il faut au moins 2 comptes admin/super_admin distincts : "
                "POST /requisitions/{id}/vise refuse le viseur qui a deja valide "
                "(backend/app/services/requisition_service.py:923)."
            )

        # Stock de requisitions APPROUVEE non encore payees, consomme une seule
        # fois par iteration du scenario « sortie de fonds ».
        approuvees_rows = (
            await db.execute(
                select(Requisition.id, Requisition.service_id, Requisition.montant_total, LigneRequisition.budget_poste_id)
                .join(LigneRequisition, LigneRequisition.requisition_id == Requisition.id)
                .where(
                    Requisition.organisation_id == org.id,
                    Requisition.status == "APPROUVEE",
                    Requisition.is_deleted.is_(False),
                )
                .limit(args.approuvees * 3)
            )
        ).all()
        vues: set[str] = set()
        approuvees = []
        for rid, service_id, montant, poste_id in approuvees_rows:
            key = str(rid)
            if key in vues:
                continue
            vues.add(key)
            approuvees.append(
                {
                    "id": key,
                    "service_id": service_id,
                    "budget_poste_id": poste_id,
                    "montant": str(montant),
                }
            )
            if len(approuvees) >= args.approuvees:
                break

        contexte = {
            "organisation_id": org.id,
            "organisation_slug": org.slug,
            "annee": exercice[1],
            "services": [{"id": s[0], "code": s[1]} for s in services],
            "postes_recette": recettes[:200],
            "postes_depense": depenses[:200],
            "compte_bancaire_id": compte[0] if compte else None,
            "utilisateurs": utilisateurs,
            "utilisateurs_plein_droit": [u["token"] for u in pleins],
            "identifiants_plein_droit": [
                {"email": u["email"], "password": args.login_password} for u in pleins[:5]
            ],
            "requisitions_approuvees": approuvees,
            "jetons_valides_minutes": args.ttl_minutes,
        }

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(contexte, handle, ensure_ascii=False)
    print(
        f"context.json ecrit dans {args.out} : "
        f"{len(contexte['utilisateurs'])} jetons ({len(pleins)} plein droit), "
        f"{len(contexte['services'])} services, "
        f"{len(recettes)} postes recette / {len(depenses)} postes depense, "
        f"{len(approuvees)} requisitions APPROUVEE disponibles."
    )


if __name__ == "__main__":
    asyncio.run(main())
