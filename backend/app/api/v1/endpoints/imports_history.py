from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from app.schemas.admin import UserOut
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.imports_history import ImportsHistory
from app.models.user import User
from app.schemas.imports import ImportsHistoryResponseWithUser


router = APIRouter()


@router.get("", response_model=list[ImportsHistoryResponseWithUser])
async def list_imports_history(
    category: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ImportsHistoryResponseWithUser]:
    _ = user
    query = select(ImportsHistory)
    if category:
        query = query.where(ImportsHistory.category == category)
    query = query.order_by(ImportsHistory.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(query)
    records = list(res.scalars().all())
    if not records:
        return []
    user_ids = {r.imported_by for r in records if r.imported_by}
    users_map: dict[uuid.UUID, User] = {}
    if user_ids:
        users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
        users_map = {u.id: u for u in users_res.scalars().all()}

    items: list[dict] = []
    for record in records:
        payload = ImportsHistoryResponseWithUser.model_validate(record).model_dump()
        if record.imported_by and record.imported_by in users_map:
            payload["imported_by_user"] = UserOut.model_validate(users_map[record.imported_by]).model_dump()
        items.append(payload)
    return items


@router.delete("/{import_id}")
async def delete_import_history(
    import_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ = user
    try:
        iid = uuid.UUID(import_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid import_id")
    res = await db.execute(select(ImportsHistory).where(ImportsHistory.id == iid))
    record = res.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    await db.delete(record)
    await db.commit()
    return {"ok": True}
