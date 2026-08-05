from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_sequence import DocumentSequence
from app.models.service import Service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def generate_document_number(
    db: AsyncSession, doc_type: str, tenant_id: int, service_id: int | None = None
) -> str:
    year = datetime.now(timezone.utc).year
    now = _utcnow()
    insert_stmt = pg_insert(DocumentSequence).values(
        doc_type=doc_type,
        year=year,
        tenant_id=tenant_id,
        service_id=service_id,
        counter=1,
        updated_at=now,
    )
    if service_id is None:
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["doc_type", "year", "tenant_id"],
            index_where=DocumentSequence.service_id.is_(None),
            set_={
                "counter": DocumentSequence.counter + 1,
                "updated_at": now,
            },
            where=DocumentSequence.counter < 99999,
        )
    else:
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["doc_type", "year", "tenant_id", "service_id"],
            index_where=DocumentSequence.service_id.is_not(None),
            set_={
                "counter": DocumentSequence.counter + 1,
                "updated_at": now,
            },
            where=DocumentSequence.counter < 99999,
        )
    stmt = stmt.returning(DocumentSequence.counter)
    res = await db.execute(stmt)
    counter = res.scalar_one_or_none()
    if counter is None:
        raise HTTPException(status_code=400, detail="Capacité annuelle atteinte")

    # New ONEC debit-note references are tenant-wide. Existing encaissement
    # references remain unchanged in the database.
    if doc_type in {"ND", "PF-ND"}:
        return f"{doc_type}-{year}-{counter:06d}"

    # Fetch Service code if service_id is provided
    service_code = "CENTRAL"
    if service_id:
        svc_res = await db.execute(
            select(Service.code).where(Service.id == service_id).limit(1)
        )
        service_code = (svc_res.scalar_one_or_none() or "SVC").strip().upper()

    return f"{doc_type}-{service_code}-{year}-{counter:05d}"
