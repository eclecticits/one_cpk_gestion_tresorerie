from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.models.document_sequence import DocumentSequence
from app.models.requisition import Requisition
from app.models.remboursement_transport import RemboursementTransport
from app.models.sortie_fonds import SortieFonds

REF_RE = re.compile(r"^(?P<doc>REQ|REM|PAY)-(?:ONEC-CPK|ONE-CPK)-(?P<year>\d{4})-(?P<num>\d{4})$")


def _parse_ref(ref: str) -> tuple[int, int] | None:
    match = REF_RE.match(ref or "")
    if not match:
        return None
    return int(match.group("year")), int(match.group("num"))


async def _max_existing_counter(db: AsyncSession, model, doc_type: str, year: int) -> int:
    stmt = select(model.reference_numero).where(
        model.reference_numero.isnot(None),
        (
            model.reference_numero.like(f"{doc_type}-ONEC-CPK-{year}-%")
            | model.reference_numero.like(f"{doc_type}-ONE-CPK-{year}-%")
        ),
    )
    res = await db.execute(stmt)
    max_num = 0
    for (ref,) in res.all():
        parsed = _parse_ref(ref)
        if parsed and parsed[0] == year:
            max_num = max(max_num, parsed[1])
    return max_num


async def backfill_table(db: AsyncSession, model, doc_type: str, *, year_filter: int | None, dry_run: bool) -> None:
    logging.info("--- Backfill pour %s ---", doc_type)
    stmt = select(model).where(model.reference_numero.is_(None)).order_by(model.created_at.asc())
    res = await db.execute(stmt)
    items = res.scalars().all()
    if not items:
        logging.info("Aucun document à traiter pour %s.", doc_type)
        return

    items_by_year: dict[int, list] = defaultdict(list)
    for item in items:
        if not item.created_at:
            continue
        year = item.created_at.year
        if year_filter and year != year_filter:
            continue
        items_by_year[year].append(item)

    for year, year_items in sorted(items_by_year.items()):
        counter = 1
        for item in year_items:
            new_ref = f"{doc_type}-ONEC-CPK-{year}-{counter:04d}"
            if not dry_run:
                item.reference_numero = new_ref
            counter += 1
            logging.info("Attribution : %s", new_ref)

        max_existing = await _max_existing_counter(db, model, doc_type, year)
        target_counter = max(counter - 1, max_existing)

        seq_stmt = select(DocumentSequence).where(
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.year == year,
        )
        seq_res = await db.execute(seq_stmt)
        seq = seq_res.scalar_one_or_none()
        if not dry_run:
            if seq:
                if seq.counter < target_counter:
                    seq.counter = target_counter
            else:
                seq = DocumentSequence(doc_type=doc_type, year=year, counter=target_counter, updated_at=datetime.utcnow())
                db.add(seq)

    if not dry_run:
        await db.commit()
    logging.info("Terminé pour %s.\n", doc_type)


def _get_session_factory():
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        def _factory(engine):
            return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        return _factory
    except ImportError:
        from sqlalchemy.ext.asyncio import async_session

        def _factory(engine):
            return async_session(bind=engine, expire_on_commit=False)

        return _factory


async def run_backfill(year_filter: int | None, dry_run: bool) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL manquant. Ex: export DATABASE_URL=postgresql+asyncpg://user:pass@host/db")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    SessionLocal = _get_session_factory()(engine)
    async with SessionLocal() as db:
        await backfill_table(db, Requisition, "REQ", year_filter=year_filter, dry_run=dry_run)
        await backfill_table(db, RemboursementTransport, "REM", year_filter=year_filter, dry_run=dry_run)
        await backfill_table(db, SortieFonds, "PAY", year_filter=year_filter, dry_run=dry_run)
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill des numéros de référence")
    parser.add_argument("--year", type=int, default=None, help="Limiter le backfill à une année (YYYY)")
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans écrire en base")
    parser.add_argument("--log", type=str, default=None, help="Chemin de fichier log")
    args = parser.parse_args()

    handlers = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(message)s")

    asyncio.run(run_backfill(args.year, args.dry_run))
