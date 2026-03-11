from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_event import SystemEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def log_system_event(
    db: AsyncSession,
    *,
    level: str = "info",
    code: str = "",
    message: str = "",
    organisation_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    event = SystemEvent(
        organisation_id=organisation_id,
        level=level,
        code=code,
        message=message,
        event_metadata=metadata,
        created_at=_utcnow(),
    )
    db.add(event)
    await db.commit()
