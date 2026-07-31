"""Backfill : applique le mapping comptable par défaut à toutes les
organisations ayant déjà activé la comptabilité, AVANT le branchement du
moteur de génération sur les endpoints réels (encaissements/sorties_fonds).

Sans ce backfill, toute organisation avec un poste budgétaire ou un compte
bancaire non mappé verrait sa saisie de trésorerie bloquée dès le
branchement (échec bloquant délibéré du moteur — cf. generation_service.py).

Idempotent : `generer_mappings_par_defaut` ne touche jamais un mapping déjà
configuré individuellement, et ce script peut être rejoué sans risque.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session  # noqa: F401 — enregistre les event listeners de scoping tenant
from app.core.tenant_context import set_current_tenant_id
from app.modules.comptabilite.models import ComptaSociete
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut


async def run_backfill(dry_run: bool) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL manquant. Ex: export DATABASE_URL=postgresql+asyncpg://user:pass@host/db")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as db:
        set_current_tenant_id(None)
        res = await db.execute(
            select(ComptaSociete.organisation_id).where(ComptaSociete.is_default.is_(True))
        )
        organisation_ids = sorted({row for row, in res.all()})

    logging.info("%d organisation(s) avec comptabilité activée.", len(organisation_ids))

    for organisation_id in organisation_ids:
        async with SessionLocal() as db:
            set_current_tenant_id(organisation_id)
            try:
                resume = await generer_mappings_par_defaut(db, organisation_id=organisation_id)
                if dry_run:
                    await db.rollback()
                    logging.info(
                        "[dry-run] org #%d : %d poste(s), %d compte(s) bancaire(s) à mapper, caisse défaut #%s",
                        organisation_id, resume["postes_mappes"], resume["comptes_bancaires_mappes"],
                        resume["compte_caisse_defaut_id"],
                    )
                else:
                    await db.commit()
                    logging.info(
                        "org #%d : %d poste(s) mappé(s), %d compte(s) bancaire(s) mappé(s), caisse défaut #%s",
                        organisation_id, resume["postes_mappes"], resume["comptes_bancaires_mappes"],
                        resume["compte_caisse_defaut_id"],
                    )
            except Exception:
                await db.rollback()
                logging.exception("org #%d : échec du mapping par défaut, organisation ignorée.", organisation_id)
            finally:
                set_current_tenant_id(None)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill du mapping comptable par défaut")
    parser.add_argument("--dry-run", action="store_true", help="Calculer sans écrire en base")
    parser.add_argument("--log", type=str, default=None, help="Chemin de fichier log")
    args = parser.parse_args()

    handlers = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(message)s")

    asyncio.run(run_backfill(args.dry_run))
