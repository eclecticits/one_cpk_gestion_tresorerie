from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import SecretariatApproval
from app.modules.secretariat.schemas import SecretariatApprovalCreate, SecretariatApprovalDecision, SecretariatApprovalOut
from app.modules.secretariat.services.approval_service import (
    approve_request as approval_approve_request,
    cancel_request as approval_cancel_request,
    create_approval_request as approval_create_request,
    get_approval_detail as approval_get_detail,
    list_pending_approvals as approval_list_pending,
    reject_request as approval_reject_request,
)

router = APIRouter()


@router.get(
    "/approvals",
    response_model=list[SecretariatApprovalOut],
    dependencies=[Depends(has_any_permission(["secretariat.view_approvals", "secretariat.view_pending_approvals", "secretariat.use_agent_manager"]))],
)
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatApproval]:
    return await approval_list_pending(db, user, tenant_id)


@router.get(
    "/approvals/{approval_id}",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_any_permission(["secretariat.view_approvals", "secretariat.view_pending_approvals", "secretariat.use_agent_manager"]))],
)
async def get_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await approval_get_detail(db, user, tenant_id, approval_id)
    await db.commit()
    return approval


@router.post(
    "/approvals",
    response_model=SecretariatApprovalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.create_approval"))],
)
async def create_approval(
    payload: SecretariatApprovalCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await approval_create_request(db, user, tenant_id, payload)
    await db.commit()
    return approval


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_permission("secretariat.approve_action"))],
)
async def approve_approval(
    approval_id: int,
    payload: SecretariatApprovalDecision | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await approval_approve_request(db, user, tenant_id, approval_id, comment=payload.comment if payload else None)
    await db.commit()
    return approval


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_permission("secretariat.reject_action"))],
)
async def reject_approval(
    approval_id: int,
    payload: SecretariatApprovalDecision | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await approval_reject_request(db, user, tenant_id, approval_id, comment=payload.comment if payload else None)
    await db.commit()
    return approval


@router.post(
    "/approvals/{approval_id}/cancel",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_permission("secretariat.cancel_approval"))],
)
async def cancel_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await approval_cancel_request(db, user, tenant_id, approval_id)
    await db.commit()
    return approval
