from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_service import user_services


async def get_user_service_ids(db: AsyncSession, user: User) -> list[int]:
    if user is None:
        return []

    res = await db.execute(
        select(user_services.c.service_id).where(user_services.c.user_id == user.id)
    )
    ids = [row[0] for row in res.all()]
    if user.service_id and user.service_id not in ids:
        ids.append(user.service_id)
    return ids
