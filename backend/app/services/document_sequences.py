from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_sequence import DocumentSequence
from app.models.organisation import Organisation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def generate_document_number(db: AsyncSession, doc_type: str, tenant_id: int) -> str:
    year = datetime.now(timezone.utc).year
    stmt = (
        select(DocumentSequence)
        .where(
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.year == year,
            DocumentSequence.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    res = await db.execute(stmt)
    seq = res.scalar_one_or_none()
    if not seq:
        seq = DocumentSequence(
            doc_type=doc_type,
            year=year,
            tenant_id=tenant_id,
            counter=1,
            updated_at=_utcnow(),
        )
        db.add(seq)
    else:
        if seq.counter >= 9999:
            raise HTTPException(status_code=400, detail="Capacité annuelle atteinte")
        seq.counter += 1
        seq.updated_at = _utcnow()
    await db.flush()
    org_res = await db.execute(
        select(Organisation.slug).where(Organisation.id == tenant_id).limit(1)
    )
    slug = (org_res.scalar_one_or_none() or "ORG").strip().upper()
    return f"{doc_type}-ONEC-{slug}-{year}-{seq.counter:04d}"
