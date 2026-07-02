from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import (
    SecretariatAgent,
    SecretariatAuditLog,
    SecretariatConversation,
    SecretariatMessage,
    SecretariatTask,
)
from app.modules.secretariat.schemas import (
    SecretariatAgentCreate,
    SecretariatAgentOut,
    SecretariatAuditLogOut,
    SecretariatConversationCreate,
    SecretariatConversationOut,
    SecretariatMessageCreate,
    SecretariatMessageOut,
    SecretariatTaskCreate,
    SecretariatTaskOut,
    SecretariatTaskUpdate,
)
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata

router = APIRouter()


async def _get_agent(db: AsyncSession, tenant_id: int, agent_id: int) -> SecretariatAgent:
    res = await db.execute(
        select(SecretariatAgent).where(
            SecretariatAgent.organisation_id == tenant_id,
            SecretariatAgent.id == agent_id,
        )
    )
    agent = res.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent introuvable")
    return agent


async def _get_conversation(db: AsyncSession, tenant_id: int, conversation_id: int) -> SecretariatConversation:
    res = await db.execute(
        select(SecretariatConversation).where(
            SecretariatConversation.organisation_id == tenant_id,
            SecretariatConversation.id == conversation_id,
        )
    )
    conversation = res.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation introuvable")
    return conversation


@router.get("/agents", response_model=list[SecretariatAgentOut], dependencies=[Depends(has_permission("secretariat.view"))])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatAgent]:
    res = await db.execute(
        select(SecretariatAgent)
        .where(SecretariatAgent.organisation_id == tenant_id)
        .order_by(SecretariatAgent.type.asc(), SecretariatAgent.name.asc())
    )
    return list(res.scalars().all())


@router.post(
    "/agents",
    response_model=SecretariatAgentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_agents"))],
)
async def create_agent(
    payload: SecretariatAgentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgent:
    agent = SecretariatAgent(
        organisation_id=tenant_id,
        name=payload.name,
        type=payload.type,
        status=payload.status,
        config_json=sanitize_secretariat_metadata(payload.config_json),
    )
    db.add(agent)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="agent.create",
        agent_type=agent.type,
        target_type="secretariat_agent",
        target_id=agent.id,
    )
    await db.commit()
    return agent


@router.get("/agents/{agent_id}", response_model=SecretariatAgentOut, dependencies=[Depends(has_permission("secretariat.view"))])
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgent:
    return await _get_agent(db, tenant_id, agent_id)


@router.get("/conversations", response_model=list[SecretariatConversationOut], dependencies=[Depends(has_permission("secretariat.view"))])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatConversation]:
    res = await db.execute(
        select(SecretariatConversation)
        .where(SecretariatConversation.organisation_id == tenant_id)
        .order_by(SecretariatConversation.updated_at.desc())
    )
    return list(res.scalars().all())


@router.post(
    "/conversations",
    response_model=SecretariatConversationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.view"))],
)
async def create_conversation(
    payload: SecretariatConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatConversation:
    agent = await _get_agent(db, tenant_id, payload.agent_id)
    conversation = SecretariatConversation(
        organisation_id=tenant_id,
        user_id=user.id,
        agent_id=agent.id,
        title=payload.title,
        status=payload.status,
    )
    db.add(conversation)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="conversation.create",
        agent_type=agent.type,
        target_type="secretariat_conversation",
        target_id=conversation.id,
    )
    await db.commit()
    return conversation


@router.get("/conversations/{conversation_id}", response_model=SecretariatConversationOut, dependencies=[Depends(has_permission("secretariat.view"))])
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatConversation:
    return await _get_conversation(db, tenant_id, conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SecretariatMessageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.view"))],
)
async def create_message(
    conversation_id: int,
    payload: SecretariatMessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMessage:
    conversation = await _get_conversation(db, tenant_id, conversation_id)
    agent = await _get_agent(db, tenant_id, conversation.agent_id)
    message = SecretariatMessage(
        organisation_id=tenant_id,
        conversation_id=conversation.id,
        sender_type="user",
        content=payload.content,
        metadata_json=sanitize_secretariat_metadata(payload.metadata_json),
    )
    db.add(message)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="message.create",
        agent_type=agent.type,
        target_type="secretariat_message",
        target_id=message.id,
    )
    await db.commit()
    return message


@router.get("/tasks", response_model=list[SecretariatTaskOut], dependencies=[Depends(has_permission("secretariat.view"))])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatTask]:
    res = await db.execute(
        select(SecretariatTask)
        .where(SecretariatTask.organisation_id == tenant_id)
        .order_by(SecretariatTask.created_at.desc())
    )
    return list(res.scalars().all())


@router.post(
    "/tasks",
    response_model=SecretariatTaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_tasks"))],
)
async def create_task(
    payload: SecretariatTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatTask:
    agent = await _get_agent(db, tenant_id, payload.agent_id)
    task = SecretariatTask(
        organisation_id=tenant_id,
        user_id=user.id,
        agent_id=payload.agent_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        due_at=payload.due_at,
        metadata_json=sanitize_secretariat_metadata(payload.metadata_json),
    )
    db.add(task)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="task.create",
        agent_type=agent.type,
        target_type="secretariat_task",
        target_id=task.id,
    )
    await db.commit()
    return task


@router.patch("/tasks/{task_id}", response_model=SecretariatTaskOut, dependencies=[Depends(has_permission("secretariat.manage_tasks"))])
async def update_task(
    task_id: int,
    payload: SecretariatTaskUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatTask:
    res = await db.execute(
        select(SecretariatTask).where(
            SecretariatTask.organisation_id == tenant_id,
            SecretariatTask.id == task_id,
        )
    )
    task = res.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    agent = await _get_agent(db, tenant_id, task.agent_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="task.update",
        agent_type=agent.type,
        target_type="secretariat_task",
        target_id=task.id,
        metadata_json={
            "fields": sorted(payload.model_dump(exclude_unset=True).keys()),
            "status": task.status,
            "priority": task.priority,
        },
    )
    await db.commit()
    return task


@router.get(
    "/audit-logs",
    response_model=list[SecretariatAuditLogOut],
    dependencies=[Depends(has_permission("secretariat.view_audit_logs"))],
)
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatAuditLog]:
    res = await db.execute(
        select(SecretariatAuditLog)
        .where(SecretariatAuditLog.organisation_id == tenant_id)
        .order_by(SecretariatAuditLog.created_at.desc())
        .limit(200)
    )
    return list(res.scalars().all())
