from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_sequence import DocumentSequence
from app.models.organisation import Organisation
from app.models.service import Service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def generate_document_number(
    db: AsyncSession, doc_type: str, tenant_id: int, service_id: int | None = None
) -> str:
    year = datetime.now(timezone.utc).year
    stmt = (
        select(DocumentSequence)
        .where(
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.year == year,
            DocumentSequence.tenant_id == tenant_id,
            DocumentSequence.service_id == service_id,
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
            service_id=service_id,
            counter=1,
            updated_at=_utcnow(),
        )
        db.add(seq)
    else:
        if seq.counter >= 99999:  # Augmented capacity to 5 digits for safety
            raise HTTPException(status_code=400, detail="Capacité annuelle atteinte")
        seq.counter += 1
        seq.updated_at = _utcnow()
    await db.flush()

    # Fetch Organisation slug
    org_res = await db.execute(
        select(Organisation.slug).where(Organisation.id == tenant_id).limit(1)
    )
    slug = (org_res.scalar_one_or_none() or "ORG").strip().upper()

    # Fetch Service code if service_id is provided
    service_code = "CENTRAL"
    if service_id:
        svc_res = await db.execute(
            select(Service.code).where(Service.id == service_id).limit(1)
        )
        service_code = (svc_res.scalar_one_or_none() or "SVC").strip().upper()

    return f"{doc_type}-{service_code}-{year}-{seq.counter:05d}"
