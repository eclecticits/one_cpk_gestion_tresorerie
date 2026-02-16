from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_sequence import DocumentSequence


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def generate_document_number(db: AsyncSession, doc_type: str) -> str:
    year = datetime.now(timezone.utc).year
    stmt = (
        select(DocumentSequence)
        .where(DocumentSequence.doc_type == doc_type, DocumentSequence.year == year)
        .with_for_update()
    )
    res = await db.execute(stmt)
    seq = res.scalar_one_or_none()
    if not seq:
        seq = DocumentSequence(doc_type=doc_type, year=year, counter=1, updated_at=_utcnow())
        db.add(seq)
    else:
        if seq.counter >= 9999:
            raise HTTPException(status_code=400, detail="Capacité annuelle atteinte")
        seq.counter += 1
        seq.updated_at = _utcnow()
    await db.flush()
    return f"{doc_type}-ONEC-CPK-{year}-{seq.counter:04d}"
