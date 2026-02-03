from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.requisition_approver import RequisitionApprover
from app.models.user import User
from app.schemas.admin import RequisitionApproverOut, SimpleUserInfo

router = APIRouter()


def _approver_out(a: RequisitionApprover, u: User | None) -> RequisitionApproverOut:
    return RequisitionApproverOut(
        id=str(a.id),
        user_id=str(a.user_id),
        active=a.active,
        added_at=a.added_at.isoformat(),
        notes=a.notes,
        user=(
            SimpleUserInfo(nom=u.nom, prenom=u.prenom, email=u.email)
            if u is not None
            else None
        ),
    )


@router.get("", response_model=list[RequisitionApproverOut])
async def list_requisition_approvers(
    user_id: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RequisitionApproverOut]:
    if user_id:
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user_id")
        if current_user.role != "admin" and current_user.id != uid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        query = select(RequisitionApprover, User).join(User, User.id == RequisitionApprover.user_id)
        query = query.where(RequisitionApprover.user_id == uid)
    else:
        if current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        query = select(RequisitionApprover, User).join(User, User.id == RequisitionApprover.user_id)

    if active is not None:
        query = query.where(RequisitionApprover.active == active)

    query = query.order_by(RequisitionApprover.added_at.desc()).offset(offset).limit(limit)
    res = await db.execute(query)
    return [_approver_out(a, u) for (a, u) in res.all()]
