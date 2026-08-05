from __future__ import annotations

import asyncio
import uuid

import pytest

from app.models.organisation import Organisation
from app.models.service import Service
from app.services.document_sequences import generate_document_number


async def _reserve_number(
    session_factory,
    semaphore: asyncio.Semaphore,
    doc_type: str,
    tenant_id: int,
    service_id: int | None,
) -> str:
    async with semaphore:
        async with session_factory() as session:
            number = await generate_document_number(session, doc_type, tenant_id, service_id=service_id)
            await session.commit()
            return number


def _sequence_value(number: str) -> int:
    return int(number.rsplit("-", 1)[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [10, 25, 50, 100])
@pytest.mark.parametrize(
    ("doc_type", "use_service"),
    [
        ("REQ", True),
        ("ND", False),
        ("PAY", True),
        ("OD", False),
    ],
)
async def test_document_number_generation_is_unique_under_concurrency(
    async_session,
    count: int,
    doc_type: str,
    use_service: bool,
):
    async with async_session() as setup:
        org = Organisation(
            nom=f"DocSeq {doc_type} {uuid.uuid4().hex[:8]}",
            slug=f"docseq-{doc_type.lower()}-{uuid.uuid4().hex[:8]}",
            is_active=True,
        )
        setup.add(org)
        await setup.flush()

        service_id = None
        service_code = "CENTRAL"
        if use_service:
            service_code = f"S{uuid.uuid4().hex[:4]}".upper()
            service = Service(
                organisation_id=org.id,
                code=service_code,
                libelle="Service sequence",
                is_active=True,
            )
            setup.add(service)
            await setup.flush()
            service_id = service.id

        tenant_id = org.id
        await setup.commit()

    db_slots = asyncio.Semaphore(20)
    numbers = await asyncio.gather(
        *[
            _reserve_number(async_session, db_slots, doc_type, tenant_id, service_id)
            for _ in range(count)
        ]
    )

    assert len(numbers) == count
    assert len(set(numbers)) == count

    values = sorted(_sequence_value(number) for number in numbers)
    assert values == list(range(1, count + 1))

    if doc_type in {"ND", "PF-ND"}:
        assert all(number.startswith(f"{doc_type}-") for number in numbers)
        assert all(len(number.rsplit("-", 1)[-1]) == 6 for number in numbers)
    else:
        assert all(f"-{service_code}-" in number for number in numbers)
        assert all(len(number.rsplit("-", 1)[-1]) == 5 for number in numbers)
