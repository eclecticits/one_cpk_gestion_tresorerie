from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.secretariat.models import (
    OAuthConnection,
    SecretariatAgent,
    SecretariatAgendaItem,
    SecretariatAgendaReminder,
    SecretariatApproval,
    SecretariatDocument,
    SecretariatMailDraft,
    SecretariatMeeting,
    SecretariatTask,
)
from app.modules.secretariat.services.oauth_service import GMAIL_COMPOSE_SCOPE, GMAIL_READONLY_SCOPE


def _task_stats(tasks: list[SecretariatTask]) -> dict:
    return {
        "pending": sum(1 for task in tasks if task.status == "pending"),
        "in_progress": sum(1 for task in tasks if task.status == "in_progress"),
        "completed": sum(1 for task in tasks if task.status == "completed"),
        "rejected": sum(1 for task in tasks if task.status == "rejected"),
        "urgent": sum(1 for task in tasks if task.priority == "urgent"),
    }


def _draft_stats(drafts: list[SecretariatMailDraft]) -> dict:
    return {
        "internal_drafts": sum(1 for draft in drafts if draft.status == "draft"),
        "approved": sum(1 for draft in drafts if draft.status == "approved"),
        "rejected": sum(1 for draft in drafts if draft.status == "rejected"),
        "gmail_draft_created": sum(1 for draft in drafts if draft.status == "gmail_draft_created"),
    }


def _approval_stats(approvals: list[SecretariatApproval]) -> dict:
    return {
        "pending": sum(1 for approval in approvals if approval.status == "pending"),
        "approved": sum(1 for approval in approvals if approval.status == "approved"),
        "rejected": sum(1 for approval in approvals if approval.status == "rejected"),
        "cancelled": sum(1 for approval in approvals if approval.status == "cancelled"),
        "urgent": sum(1 for approval in approvals if approval.priority == "urgent" and approval.status == "pending"),
    }


def _document_stats(documents: list[SecretariatDocument], approvals: list[SecretariatApproval]) -> dict:
    pending_approval = sum(1 for document in documents if document.status == "pending_approval")
    syntheses_to_validate = sum(
        1
        for approval in approvals
        if approval.status == "pending"
        and approval.approval_type == "document_synthesis_validation"
        and approval.target_type == "secretariat_document"
    )
    recent_created = [
        {
            "id": document.id,
            "title": document.title,
            "document_type": document.document_type,
            "status": document.status,
            "created_at": document.created_at,
        }
        for document in documents[:5]
    ]
    return {
        "pending_approval": pending_approval,
        "syntheses_to_validate": syntheses_to_validate,
        "recent_created": recent_created,
    }


def _day_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _agenda_stats(items: list[SecretariatAgendaItem], reminders: list[SecretariatAgendaReminder]) -> dict:
    today_start, today_end = _day_bounds()
    now = datetime.now(timezone.utc)
    active = {"pending", "in_progress", "overdue"}
    return {
        "today": sum(1 for item in items if item.due_at and today_start <= item.due_at < today_end and item.status in active),
        "overdue": sum(1 for item in items if item.status == "overdue" or (item.due_at and item.due_at < now and item.status in {"pending", "in_progress"})),
        "urgent": sum(1 for item in items if item.priority == "urgent" and item.status in active),
        "reminders_pending": sum(1 for reminder in reminders if reminder.status == "pending"),
    }


async def _manager_agent_id(db: AsyncSession, organisation_id: int) -> int:
    res = await db.execute(
        select(SecretariatAgent).where(
            SecretariatAgent.organisation_id == organisation_id,
            SecretariatAgent.type == "manager",
        )
    )
    agent = res.scalar_one_or_none()
    if agent is None:
        agent = SecretariatAgent(
            organisation_id=organisation_id,
            name="Agent Manager",
            type="manager",
            status="active",
        )
        db.add(agent)
        await db.flush()
    return agent.id


async def _tasks(db: AsyncSession, organisation_id: int) -> list[SecretariatTask]:
    res = await db.execute(
        select(SecretariatTask)
        .where(SecretariatTask.organisation_id == organisation_id)
        .order_by(SecretariatTask.created_at.desc())
    )
    return list(res.scalars().all())


async def _drafts(db: AsyncSession, organisation_id: int) -> list[SecretariatMailDraft]:
    res = await db.execute(
        select(SecretariatMailDraft)
        .where(SecretariatMailDraft.organisation_id == organisation_id)
        .order_by(SecretariatMailDraft.updated_at.desc())
    )
    return list(res.scalars().all())


async def _documents(db: AsyncSession, organisation_id: int) -> list[SecretariatDocument]:
    res = await db.execute(
        select(SecretariatDocument)
        .where(SecretariatDocument.organisation_id == organisation_id)
        .order_by(SecretariatDocument.created_at.desc())
    )
    return list(res.scalars().all())


async def _approvals(db: AsyncSession, organisation_id: int) -> list[SecretariatApproval]:
    res = await db.execute(
        select(SecretariatApproval)
        .where(SecretariatApproval.organisation_id == organisation_id)
        .order_by(SecretariatApproval.created_at.desc())
    )
    return list(res.scalars().all())


async def _agenda_items(db: AsyncSession, organisation_id: int) -> list[SecretariatAgendaItem]:
    res = await db.execute(
        select(SecretariatAgendaItem)
        .where(SecretariatAgendaItem.organisation_id == organisation_id)
        .order_by(SecretariatAgendaItem.due_at.asc().nullslast(), SecretariatAgendaItem.created_at.desc())
    )
    return list(res.scalars().all())


async def _agenda_reminders(db: AsyncSession, organisation_id: int) -> list[SecretariatAgendaReminder]:
    res = await db.execute(
        select(SecretariatAgendaReminder)
        .where(SecretariatAgendaReminder.organisation_id == organisation_id)
        .order_by(SecretariatAgendaReminder.reminder_at.asc())
    )
    return list(res.scalars().all())


async def _meetings(db: AsyncSession, organisation_id: int) -> list[SecretariatMeeting]:
    res = await db.execute(
        select(SecretariatMeeting)
        .where(SecretariatMeeting.organisation_id == organisation_id)
        .order_by(SecretariatMeeting.meeting_date.asc().nullslast(), SecretariatMeeting.created_at.desc())
    )
    return list(res.scalars().all())


async def _oauth_status(db: AsyncSession, user: User, organisation_id: int) -> dict:
    res = await db.execute(
        select(OAuthConnection).where(
            OAuthConnection.organisation_id == organisation_id,
            OAuthConnection.user_id == user.id,
            OAuthConnection.provider == "google",
        )
    )
    connection = res.scalar_one_or_none()
    scopes = set(connection.scopes or []) if connection else set()
    connected = bool(connection and connection.status == "connected")
    return {
        "gmail_connected": connected,
        "email": connection.email if connected else None,
        "has_gmail_readonly": GMAIL_READONLY_SCOPE in scopes,
        "has_gmail_compose": GMAIL_COMPOSE_SCOPE in scopes,
    }


def _recommended_actions(
    tasks: list[SecretariatTask],
    drafts: list[SecretariatMailDraft],
    approvals: list[SecretariatApproval],
    oauth: dict,
    documents: list[SecretariatDocument] | None = None,
    agenda: dict | None = None,
    meetings: list[SecretariatMeeting] | None = None,
) -> list[dict]:
    actions: list[dict] = []
    agenda = agenda or {}
    if agenda.get("overdue"):
        actions.append(
            {
                "type": "agenda_overdue",
                "title": f"{agenda['overdue']} échéance(s) agenda en retard",
                "priority": "urgent",
                "target_id": "agenda",
            }
        )
    if agenda.get("today"):
        actions.append(
            {
                "type": "agenda_today",
                "title": f"{agenda['today']} échéance(s) à traiter aujourd'hui",
                "priority": "high",
                "target_id": "agenda",
            }
        )
    if agenda.get("reminders_pending"):
        actions.append(
            {
                "type": "agenda_reminders",
                "title": f"{agenda['reminders_pending']} rappel(s) agenda en attente",
                "priority": "normal",
                "target_id": "agenda",
            }
        )
    if meetings:
        today_start, _ = _day_bounds()
        week_end_date = (today_start + timedelta(days=7)).date()
        meetings_without_minutes = [
            meeting
            for meeting in meetings
            if meeting.meeting_date and today_start.date() <= meeting.meeting_date <= week_end_date and not meeting.minutes_draft and meeting.status not in {"cancelled", "approved"}
        ]
        if meetings_without_minutes:
            actions.append(
                {
                    "type": "meeting_minutes_missing",
                    "title": f"{len(meetings_without_minutes)} réunion(s) cette semaine sans projet de PV",
                    "priority": "normal",
                    "target_id": "reunions",
                }
            )
    for approval in approvals:
        if approval.status != "pending":
            continue
        actions.append(
            {
                "type": "approval_required",
                "title": approval.title,
                "priority": approval.priority,
                "target_id": str(approval.id),
            }
        )
    if documents:
        docs_pending = sum(1 for document in documents if document.status == "pending_approval")
        if docs_pending:
            actions.append(
                {
                    "type": "documents_pending_approval",
                    "title": f"{docs_pending} document(s) en attente de validation",
                    "priority": "high",
                    "target_id": "documents",
                }
            )
        recent_created = [document for document in documents if document.status in {"draft", "active", "pending_approval"}][:5]
        if recent_created:
            actions.append(
                {
                    "type": "documents_recent",
                    "title": f"{len(recent_created)} document(s) récemment créés",
                    "priority": "normal",
                    "target_id": "documents",
                }
            )
    for draft in drafts:
        has_pending_mail_approval = any(
            approval.status == "pending"
            and approval.approval_type == "mail_draft_approval"
            and approval.target_type == "secretariat_mail_draft"
            and approval.target_id == str(draft.id)
            for approval in approvals
        )
        has_pending_gmail_approval = any(
            approval.status == "pending"
            and approval.approval_type == "gmail_draft_creation"
            and approval.target_type == "secretariat_mail_draft"
            and approval.target_id == str(draft.id)
            for approval in approvals
        )
        if draft.status == "draft" and not has_pending_mail_approval:
            actions.append(
                {
                    "type": "approve_draft",
                    "title": draft.subject,
                    "priority": "normal",
                    "target_id": str(draft.id),
                }
            )
        elif draft.status == "approved" and not draft.gmail_draft_id and not has_pending_gmail_approval:
            actions.append(
                {
                    "type": "create_gmail_draft",
                    "title": draft.subject,
                    "priority": "high" if oauth.get("has_gmail_compose") else "normal",
                    "target_id": str(draft.id),
                }
            )
    for task in tasks:
        if task.priority == "urgent" and task.status in {"pending", "in_progress"}:
            actions.append(
                {
                    "type": "handle_urgent_task",
                    "title": task.title,
                    "priority": "urgent",
                    "target_id": str(task.id),
                }
            )
    return actions[:10]


async def get_secretariat_overview(db: AsyncSession, user: User, organisation_id: int) -> dict:
    tasks = await _tasks(db, organisation_id)
    drafts = await _drafts(db, organisation_id)
    approvals = await _approvals(db, organisation_id)
    documents = await _documents(db, organisation_id)
    agenda_items = await _agenda_items(db, organisation_id)
    agenda_reminders = await _agenda_reminders(db, organisation_id)
    meetings = await _meetings(db, organisation_id)
    agenda = _agenda_stats(agenda_items, agenda_reminders)
    documents_stats = _document_stats(documents, approvals)
    oauth = await _oauth_status(db, user, organisation_id)
    return {
        "tasks": _task_stats(tasks),
        "mail_drafts": _draft_stats(drafts),
        "approvals": _approval_stats(approvals),
        "documents": documents_stats,
        "agenda": agenda,
        "oauth": oauth,
        "recommended_actions": _recommended_actions(tasks, drafts, approvals, oauth, documents, agenda, meetings),
    }


async def get_pending_approvals(db: AsyncSession, user: User, organisation_id: int) -> list[dict]:
    approvals = await _approvals(db, organisation_id)
    return [
        {
            "id": approval.id,
            "type": approval.approval_type,
            "title": approval.title,
            "status": approval.status,
            "priority": approval.priority,
            "created_at": approval.created_at,
            "target_id": approval.target_id,
        }
        for approval in approvals
        if approval.status == "pending"
    ]


async def get_agent_workload(db: AsyncSession, user: User, organisation_id: int) -> dict:
    res = await db.execute(
        select(SecretariatAgent.type, SecretariatTask)
        .join(SecretariatAgent, SecretariatAgent.id == SecretariatTask.agent_id)
        .where(SecretariatTask.organisation_id == organisation_id)
        .order_by(SecretariatTask.created_at.desc())
    )
    grouped: dict[str, list[SecretariatTask]] = {}
    all_tasks: list[SecretariatTask] = []
    for agent_type, task in res.all():
        grouped.setdefault(agent_type or "unknown", []).append(task)
        all_tasks.append(task)
    return {
        "by_agent": {agent_type: _task_stats(rows) for agent_type, rows in grouped.items()},
        "urgent_tasks": [task for task in all_tasks if task.priority == "urgent" and task.status in {"pending", "in_progress"}][:10],
        "recent_completed": [task for task in all_tasks if task.status == "completed"][:10],
    }


async def get_recommended_actions(db: AsyncSession, user: User, organisation_id: int) -> list[dict]:
    tasks = await _tasks(db, organisation_id)
    drafts = await _drafts(db, organisation_id)
    approvals = await _approvals(db, organisation_id)
    documents = await _documents(db, organisation_id)
    agenda = _agenda_stats(await _agenda_items(db, organisation_id), await _agenda_reminders(db, organisation_id))
    meetings = await _meetings(db, organisation_id)
    oauth = await _oauth_status(db, user, organisation_id)
    return _recommended_actions(tasks, drafts, approvals, oauth, documents, agenda, meetings)


async def create_followup_task(db: AsyncSession, user: User, organisation_id: int, payload) -> SecretariatTask:
    agent_id = await _manager_agent_id(db, organisation_id)
    task = SecretariatTask(
        organisation_id=organisation_id,
        agent_id=agent_id,
        user_id=user.id,
        title=payload.title,
        description=payload.description,
        status="pending",
        priority=payload.priority,
        due_at=payload.due_at,
        metadata_json={
            "source": "agent_manager",
            "target_type": payload.target_type,
            "target_id": payload.target_id,
        },
    )
    db.add(task)
    await db.flush()
    return task
