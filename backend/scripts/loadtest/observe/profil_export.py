#!/usr/bin/env python3
"""Profil CPU de la generation d'un classeur d'export.

    docker compose cp observe/profil_export.py backend:/app/profil_export.py
    docker compose exec -T backend python /app/profil_export.py encaissements
    docker compose exec -T backend python /app/profil_export.py requisitions

Pourquoi ce detour : le travail lourd s'execute dans un thread, via
`anyio.to_thread.run_sync(_build_workbook)`. cProfile ne suit que le thread
courant — profiler l'appel HTTP ne montrerait donc rien du coût reel.

Ce script neutralise `run_sync` pour executer la construction EN LIGNE, dans le
thread profile. Il ne modifie aucun code de production : la substitution vit
dans ce processus de mesure uniquement, et le chemin de code parcouru est
exactement celui de l'endpoint (memes requetes, memes helpers, meme classeur).

Mesure de reference relevee via les journaux applicatifs, avant tout correctif :
    /exports/encaissements, 4 800 lignes
    duree 33 616 ms | SQL 730 ms (6 requetes) | connexion retenue 33 204 ms
"""

from __future__ import annotations

import asyncio
import cProfile
import io
import pstats
import sys

import anyio.to_thread
from sqlalchemy import select

CIBLE = sys.argv[1] if len(sys.argv) > 1 else "encaissements"
SLUG = "load-test-20260803"


async def principal() -> None:
    from app.db.session import SessionLocal
    from app.models.organisation import Organisation
    from app.models.user import User
    from app.core.tenant_context import set_current_tenant_id
    from app.api.v1.endpoints import exports

    async with SessionLocal() as db:
        db.info["skip_tenant_scope"] = True
        org = (
            await db.execute(select(Organisation).where(Organisation.slug == SLUG))
        ).scalar_one()
        user = (
            await db.execute(
                select(User)
                .where(User.organisation_id == org.id, User.role == "super_admin")
                .limit(1)
            )
        ).scalar_one()
        db.info.pop("skip_tenant_scope", None)

    set_current_tenant_id(org.id)

    # Substitution locale : la construction s'execute dans CE thread, donc sous
    # le profileur. `run_sync` est normalement attendu, on garde donc une
    # coroutine pour ne rien changer au flot d'appel de l'endpoint.
    async def run_sync_en_ligne(fn, *args, **kwargs):
        return fn(*args)

    anyio.to_thread.run_sync = run_sync_en_ligne
    exports.anyio.to_thread.run_sync = run_sync_en_ligne

    async with SessionLocal() as db:
        if CIBLE == "encaissements":
            appel = exports.export_encaissements(
                date_debut="2026-08-01",
                date_fin="2026-08-31",
                statut_paiement=None,
                numero_recu=None,
                client=None,
                budget_poste_id=None,
                type_client=None,
                mode_paiement=None,
                expert_comptable_id=None,
                deleted_status="all",
                est_proforma=False,
                user=user,
                db=db,
            )
        elif CIBLE == "requisitions":
            appel = exports.export_requisitions(
                date_debut=None,
                date_fin=None,
                statut=None,
                service_id=None,
                type_requisition=None,
                mode_paiement=None,
                budget_poste_id=None,
                search=None,
                objet=None,
                user=user,
                db=db,
            )
        else:
            raise SystemExit(f"cible inconnue : {CIBLE}")

        profileur = cProfile.Profile()
        profileur.enable()
        await appel
        profileur.disable()

    flux = io.StringIO()
    stats = pstats.Stats(profileur, stream=flux).sort_stats("cumulative")
    stats.print_stats(28)
    print(f"===== PROFIL CUMULE — /exports/{CIBLE} =====")
    print(flux.getvalue())

    flux2 = io.StringIO()
    pstats.Stats(profileur, stream=flux2).sort_stats("tottime").print_stats(20)
    print(f"===== TEMPS PROPRE (tottime) — /exports/{CIBLE} =====")
    print(flux2.getvalue())


if __name__ == "__main__":
    asyncio.run(principal())
