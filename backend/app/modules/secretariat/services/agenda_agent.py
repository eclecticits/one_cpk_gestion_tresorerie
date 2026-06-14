from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.secretariat.models import SecretariatAgendaItem, SecretariatAgendaReminder
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata


ACTIVE_STATUSES = {"pending", "in_progress", "overdue"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_bounds(value: datetime | None = None) -> tuple[datetime, datetime]:
    current = value or _now()
    start = datetime.combine(current.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


async def _get_item(db: AsyncSession, organisation_id: int, item_id: int) -> SecretariatAgendaItem:
    res = await db.execute(
        select(SecretariatAgendaItem).where(
            SecretariatAgendaItem.organisation_id == organisation_id,
            SecretariatAgendaItem.id == item_id,
        )
    )
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Échéance agenda introuvable")
    return item


async def _get_reminder(db: AsyncSession, organisation_id: int, reminder_id: int) -> SecretariatAgendaReminder:
    res = await db.execute(
        select(SecretariatAgendaReminder).where(
            SecretariatAgendaReminder.organisation_id == organisation_id,
            SecretariatAgendaReminder.id == reminder_id,
        )
    )
    reminder = res.scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rappel agenda introuvable")
    return reminder


def _safe_item_metadata(item: SecretariatAgendaItem) -> dict:
    return {
        "item_type": item.item_type,
        "priority": item.priority,
        "status": item.status,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "due_at": item.due_at.isoformat() if item.due_at else None,
    }


async def _validate_assigned_user(db: AsyncSession, organisation_id: int, assigned_to_user_id):
    if assigned_to_user_id is None:
        return None
    res = await db.execute(
        select(User).where(
            User.id == assigned_to_user_id,
            User.organisation_id == organisation_id,
        )
    )
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Responsable invalide pour ce tenant.")
    return assigned_to_user_id


async def _find_active_reunion_item(db: AsyncSession, organisation_id: int, meeting_id: int) -> SecretariatAgendaItem | None:
    res = await db.execute(
        select(SecretariatAgendaItem).where(
            SecretariatAgendaItem.organisation_id == organisation_id,
            SecretariatAgendaItem.item_type == "meeting",
            SecretariatAgendaItem.target_type == "secretariat_meeting",
            SecretariatAgendaItem.target_id == str(meeting_id),
            SecretariatAgendaItem.status.in_(ACTIVE_STATUSES),
        )
    )
    return res.scalar_one_or_none()


async def create_agenda_item(db: AsyncSession, user: User, organisation_id: int, payload) -> SecretariatAgendaItem:
    if payload.status not in {"pending", "in_progress"}:
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id,
            action="agenda_transition_blocked",
            agent_type="agenda",
            target_type="secretariat_agenda_item",
            target_id=None,
            metadata_json={
                "current_status": None,
                "requested_status": payload.status,
                "reason": "create_status_forbidden",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La création ne peut démarrer qu’avec un statut actif simple.",
        )
    assigned_to_user_id = await _validate_assigned_user(db, organisation_id, payload.assigned_to_user_id)
    item = SecretariatAgendaItem(
        organisation_id=organisation_id,
        created_by_user_id=user.id,
        **payload.model_dump(exclude={"assigned_to_user_id"}),
        assigned_to_user_id=assigned_to_user_id,
    )
    item.metadata_json = sanitize_secretariat_metadata(item.metadata_json)
    if item.status == "completed" and item.completed_at is None:
        item.completed_at = _now()
    db.add(item)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_item_created",
        agent_type="agenda",
        target_type="secretariat_agenda_item",
        target_id=item.id,
        metadata_json=_safe_item_metadata(item),
    )
    return item


async def update_agenda_item(db: AsyncSession, user: User, organisation_id: int, item_id: int, payload) -> SecretariatAgendaItem:
    item = await _get_item(db, organisation_id, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if "assigned_to_user_id" in changes:
        changes["assigned_to_user_id"] = await _validate_assigned_user(db, organisation_id, changes["assigned_to_user_id"])
    if "status" in changes:
        requested_status = changes["status"]
        if requested_status != item.status:
            await record_secretariat_audit(
                db,
                organisation_id=organisation_id,
                user_id=user.id,
                action="agenda_transition_blocked",
                agent_type="agenda",
                target_type="secretariat_agenda_item",
                target_id=item.id,
                metadata_json={
                    "current_status": item.status,
                    "requested_status": requested_status,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Les changements de statut passent par les actions dédiées de l’agenda.",
            )
        changes.pop("status")
    for field, value in changes.items():
        if field == "metadata_json":
            value = sanitize_secretariat_metadata(value)
        setattr(item, field, value)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_item_updated",
        agent_type="agenda",
        target_type="secretariat_agenda_item",
        target_id=item.id,
        metadata_json={"fields": sorted(changes.keys()), "status": item.status},
    )
    return item


async def list_agenda_items(
    db: AsyncSession,
    organisation_id: int,
    *,
    status_value: str | None = None,
    priority: str | None = None,
    item_type: str | None = None,
    assigned_to_user_id=None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SecretariatAgendaItem]:
    stmt = select(SecretariatAgendaItem).where(SecretariatAgendaItem.organisation_id == organisation_id)
    if status_value:
        stmt = stmt.where(SecretariatAgendaItem.status == status_value)
    if priority:
        stmt = stmt.where(SecretariatAgendaItem.priority == priority)
    if item_type:
        stmt = stmt.where(SecretariatAgendaItem.item_type == item_type)
    if assigned_to_user_id:
        stmt = stmt.where(SecretariatAgendaItem.assigned_to_user_id == assigned_to_user_id)
    if date_from:
        stmt = stmt.where(SecretariatAgendaItem.due_at >= date_from)
    if date_to:
        stmt = stmt.where(SecretariatAgendaItem.due_at < date_to)
    stmt = stmt.order_by(SecretariatAgendaItem.due_at.asc().nullslast(), SecretariatAgendaItem.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_agenda_item(db: AsyncSession, organisation_id: int, item_id: int) -> SecretariatAgendaItem:
    return await _get_item(db, organisation_id, item_id)


async def complete_agenda_item(db: AsyncSession, user: User, organisation_id: int, item_id: int) -> SecretariatAgendaItem:
    item = await _get_item(db, organisation_id, item_id)
    if item.status in {"completed", "cancelled"}:
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id,
            action="agenda_transition_blocked",
            agent_type="agenda",
            target_type="secretariat_agenda_item",
            target_id=item.id,
            metadata_json={"current_status": item.status, "requested_status": "completed"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette échéance ne peut plus être validée via cette action.")
    item.status = "completed"
    item.completed_at = _now()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_item_completed",
        agent_type="agenda",
        target_type="secretariat_agenda_item",
        target_id=item.id,
        metadata_json={"status": item.status},
    )
    return item


async def cancel_agenda_item(db: AsyncSession, user: User, organisation_id: int, item_id: int) -> SecretariatAgendaItem:
    item = await _get_item(db, organisation_id, item_id)
    if item.status in {"completed", "cancelled"}:
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id,
            action="agenda_transition_blocked",
            agent_type="agenda",
            target_type="secretariat_agenda_item",
            target_id=item.id,
            metadata_json={"current_status": item.status, "requested_status": "cancelled"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette échéance ne peut plus être annulée via cette action.")
    item.status = "cancelled"
    item.completed_at = None
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_item_cancelled",
        agent_type="agenda",
        target_type="secretariat_agenda_item",
        target_id=item.id,
        metadata_json={"status": item.status},
    )
    return item


async def mark_overdue_items(db: AsyncSession, user: User | None, organisation_id: int) -> int:
    now = _now()
    res = await db.execute(
        select(SecretariatAgendaItem).where(
            SecretariatAgendaItem.organisation_id == organisation_id,
            SecretariatAgendaItem.status.in_({"pending", "in_progress"}),
            SecretariatAgendaItem.due_at.is_not(None),
            SecretariatAgendaItem.due_at < now,
        )
    )
    items = list(res.scalars().all())
    for item in items:
        item.status = "overdue"
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id if user else None,
            action="agenda_item_marked_overdue",
            agent_type="agenda",
            target_type="secretariat_agenda_item",
            target_id=item.id,
            metadata_json={"status": item.status},
        )
    return len(items)


async def create_reminder(db: AsyncSession, user: User, organisation_id: int, item_id: int, payload) -> SecretariatAgendaReminder:
    item = await _get_item(db, organisation_id, item_id)
    reminder = SecretariatAgendaReminder(
        organisation_id=organisation_id,
        agenda_item_id=item.id,
        reminder_at=payload.reminder_at,
        message=payload.message,
        status="pending",
    )
    db.add(reminder)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_reminder_created",
        agent_type="agenda",
        target_type="secretariat_agenda_reminder",
        target_id=reminder.id,
        metadata_json={"agenda_item_id": item.id, "reminder_at": reminder.reminder_at.isoformat(), "status": reminder.status},
    )
    return reminder


async def list_reminders(
    db: AsyncSession,
    organisation_id: int,
    *,
    status_value: str | None = None,
) -> list[SecretariatAgendaReminder]:
    stmt = select(SecretariatAgendaReminder).where(SecretariatAgendaReminder.organisation_id == organisation_id)
    if status_value:
        stmt = stmt.where(SecretariatAgendaReminder.status == status_value)
    stmt = stmt.order_by(SecretariatAgendaReminder.reminder_at.asc(), SecretariatAgendaReminder.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def dismiss_reminder(db: AsyncSession, user: User, organisation_id: int, reminder_id: int) -> SecretariatAgendaReminder:
    reminder = await _get_reminder(db, organisation_id, reminder_id)
    reminder.status = "dismissed"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="agenda_reminder_dismissed",
        agent_type="agenda",
        target_type="secretariat_agenda_reminder",
        target_id=reminder.id,
        metadata_json={"agenda_item_id": reminder.agenda_item_id, "status": reminder.status},
    )
    return reminder


async def get_agenda_overview(db: AsyncSession, user: User | None, organisation_id: int, *, audit: bool = True) -> dict:
    items = await list_agenda_items(db, organisation_id)
    reminders = await list_reminders(db, organisation_id, status_value="pending")
    today_start, today_end = _day_bounds()
    week_end = today_start + timedelta(days=7)
    now = _now()
    overdue_count = sum(1 for item in items if item.status == "overdue" or (item.due_at and item.due_at < now and item.status in {"pending", "in_progress"}))
    overview = {
        "today": sum(1 for item in items if item.due_at and today_start <= item.due_at < today_end and item.status in ACTIVE_STATUSES),
        "this_week": sum(1 for item in items if item.due_at and today_start <= item.due_at < week_end and item.status in ACTIVE_STATUSES),
        "overdue": overdue_count,
        "upcoming": sum(1 for item in items if item.due_at and item.due_at >= today_end and item.status in ACTIVE_STATUSES),
        "completed": sum(1 for item in items if item.status == "completed"),
        "urgent": sum(1 for item in items if item.priority == "urgent" and item.status in ACTIVE_STATUSES),
        "reminders_pending": len(reminders),
    }
    if audit:
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id if user else None,
            action="agenda_overview_viewed",
            agent_type="agenda",
            target_type="secretariat_agenda",
            target_id=None,
            metadata_json=overview,
        )
    return overview


async def get_or_create_reunion_agenda_item(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    meeting_id: int,
    payload,
) -> tuple[SecretariatAgendaItem, bool]:
    existing = await _find_active_reunion_item(db, organisation_id, meeting_id)
    if existing is not None:
        await record_secretariat_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id,
            action="agenda_duplicate_reunion_item_reused",
            agent_type="agenda",
            target_type="secretariat_agenda_item",
            target_id=existing.id,
            metadata_json={
                "target_type": "secretariat_meeting",
                "target_id": str(meeting_id),
                "status": existing.status,
            },
        )
        return existing, True
    return await create_agenda_item(db, user, organisation_id, payload), False
