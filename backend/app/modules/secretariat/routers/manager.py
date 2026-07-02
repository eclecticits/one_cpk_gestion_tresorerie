from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import SecretariatTask
from app.modules.secretariat.schemas import (
    ManagerApprovalItem,
    ManagerFollowupTaskCreate,
    ManagerOverviewOut,
    ManagerRecommendedAction,
    ManagerWorkloadOut,
    SecretariatTaskOut,
)
from app.modules.secretariat.services.agent_manager import (
    create_followup_task as manager_create_followup_task,
    get_agent_workload as manager_get_agent_workload,
    get_pending_approvals as manager_get_pending_approvals,
    get_recommended_actions as manager_get_recommended_actions,
    get_secretariat_overview as manager_get_secretariat_overview,
)
from app.modules.secretariat.services.audit import record_secretariat_audit
from app.modules.secretariat.services.manager_agent_agentor import run_manager_agent

router = APIRouter()


@router.get(
    "/manager/overview",
    response_model=ManagerOverviewOut,
    dependencies=[Depends(has_any_permission(["secretariat.view_manager_dashboard", "secretariat.use_agent_manager"]))],
)
async def manager_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    overview = await manager_get_secretariat_overview(db, user, tenant_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="manager_overview_viewed",
        agent_type="manager",
        target_type="secretariat_manager",
        target_id="overview",
        metadata_json={
            "tasks_pending": overview["tasks"]["pending"],
            "urgent_tasks": overview["tasks"]["urgent"],
            "recommended_actions": len(overview["recommended_actions"]),
        },
    )
    await db.commit()
    return overview


@router.get(
    "/manager/pending-approvals",
    response_model=list[ManagerApprovalItem],
    dependencies=[Depends(has_any_permission(["secretariat.view_pending_approvals", "secretariat.use_agent_manager"]))],
)
async def manager_pending_approvals(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[dict]:
    rows = await manager_get_pending_approvals(db, user, tenant_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="manager_pending_approvals_viewed",
        agent_type="manager",
        target_type="secretariat_mail_draft",
        target_id=None,
        metadata_json={"count": len(rows)},
    )
    await db.commit()
    return rows


@router.get(
    "/manager/workload",
    response_model=ManagerWorkloadOut,
    dependencies=[Depends(has_any_permission(["secretariat.view_manager_dashboard", "secretariat.use_agent_manager"]))],
)
async def manager_workload(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    return await manager_get_agent_workload(db, user, tenant_id)


@router.get(
    "/manager/recommended-actions",
    response_model=list[ManagerRecommendedAction],
    dependencies=[Depends(has_any_permission(["secretariat.view_manager_dashboard", "secretariat.use_agent_manager"]))],
)
async def manager_recommended_actions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[dict]:
    rows = await manager_get_recommended_actions(db, user, tenant_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="manager_recommendations_generated",
        agent_type="manager",
        target_type="secretariat_manager",
        target_id="recommended_actions",
        metadata_json={"count": len(rows)},
    )
    await db.commit()
    return rows


@router.post(
    "/manager/followup-task",
    response_model=SecretariatTaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_any_permission(["secretariat.manage_tasks", "secretariat.use_agent_manager"]))],
)
async def manager_followup_task(
    payload: ManagerFollowupTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatTask:
    task = await manager_create_followup_task(db, user, tenant_id, payload)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="manager_followup_task_created",
        agent_type="manager",
        target_type="secretariat_task",
        target_id=task.id,
        metadata_json={
            "task_id": task.id,
            "priority": task.priority,
            "target_type": payload.target_type,
            "target_id": payload.target_id,
        },
    )
    await db.commit()
    return task


# ── Manager Agent Chat (Agentor pattern) ─────────────────────────────────────

class ManagerAgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_history: list[dict] | None = None


class ManagerAgentChatOut(BaseModel):
    response: str
    actions_taken: list[str]
    tool_results: list[dict]


@router.post(
    "/ai/manager/chat",
    response_model=ManagerAgentChatOut,
    dependencies=[Depends(has_permission("secretariat.view"))],
    summary="Manager Agent — chat conversationnel (Agentor pattern)",
)
async def manager_agent_chat(
    payload: ManagerAgentChatIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ManagerAgentChatOut:
    result = await run_manager_agent(
        message=payload.message,
        db=db,
        user=user,
        organisation_id=tenant_id,
        conversation_history=payload.conversation_history,
    )
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="manager_agent_chat",
        agent_type="manager",
        target_type="ai_chat",
        target_id=None,
        metadata_json={
            "tools_called": result.get("actions_taken", []),
            "message_length": len(payload.message),
        },
    )
    await db.commit()
    return ManagerAgentChatOut(**result)
