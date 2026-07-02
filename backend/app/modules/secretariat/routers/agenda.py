from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import SecretariatAgendaItem, SecretariatAgendaReminder
from app.modules.secretariat.schemas import (
    AgendaItemCreate,
    AgendaItemRead,
    AgendaItemUpdate,
    AgendaOverview,
    AgendaReminderCreate,
    AgendaReminderRead,
)
from app.modules.secretariat.services.agenda_agent import (
    cancel_agenda_item as agenda_cancel_item,
    complete_agenda_item as agenda_complete_item,
    create_agenda_item as agenda_create_item,
    create_reminder as agenda_create_reminder,
    dismiss_reminder as agenda_dismiss_reminder,
    get_agenda_item as agenda_get_item,
    get_agenda_overview as agenda_get_overview,
    list_agenda_items as agenda_list_items,
    list_reminders as agenda_list_reminders,
    update_agenda_item as agenda_update_item,
)

router = APIRouter()


@router.get(
    "/agenda/items",
    response_model=list[AgendaItemRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_agenda", "secretariat.use_agent_agenda"]))],
)
async def list_agenda_items(
    status_value: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    item_type: str | None = Query(default=None),
    assigned_to_user_id: UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatAgendaItem]:
    return await agenda_list_items(
        db,
        tenant_id,
        status_value=status_value,
        priority=priority,
        item_type=item_type,
        assigned_to_user_id=assigned_to_user_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.post(
    "/agenda/items",
    response_model=AgendaItemRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_agenda"))],
)
async def create_agenda_item(
    payload: AgendaItemCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    item = await agenda_create_item(db, user, tenant_id, payload)
    await db.commit()
    return item


@router.get(
    "/agenda/items/{item_id}",
    response_model=AgendaItemRead,
    dependencies=[Depends(has_any_permission(["secretariat.view_agenda", "secretariat.use_agent_agenda"]))],
)
async def get_agenda_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    return await agenda_get_item(db, tenant_id, item_id)


@router.patch(
    "/agenda/items/{item_id}",
    response_model=AgendaItemRead,
    dependencies=[Depends(has_permission("secretariat.manage_agenda"))],
)
async def update_agenda_item(
    item_id: int,
    payload: AgendaItemUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    item = await agenda_update_item(db, user, tenant_id, item_id, payload)
    await db.commit()
    return item


@router.post(
    "/agenda/items/{item_id}/complete",
    response_model=AgendaItemRead,
    dependencies=[Depends(has_permission("secretariat.manage_agenda"))],
)
async def complete_agenda_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    item = await agenda_complete_item(db, user, tenant_id, item_id)
    await db.commit()
    return item


@router.post(
    "/agenda/items/{item_id}/cancel",
    response_model=AgendaItemRead,
    dependencies=[Depends(has_permission("secretariat.manage_agenda"))],
)
async def cancel_agenda_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    item = await agenda_cancel_item(db, user, tenant_id, item_id)
    await db.commit()
    return item


@router.get(
    "/agenda/reminders",
    response_model=list[AgendaReminderRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_agenda", "secretariat.use_agent_agenda"]))],
)
async def list_agenda_reminders(
    status_value: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatAgendaReminder]:
    return await agenda_list_reminders(db, tenant_id, status_value=status_value)


@router.post(
    "/agenda/items/{item_id}/reminders",
    response_model=AgendaReminderRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_agenda_reminders"))],
)
async def create_agenda_reminder(
    item_id: int,
    payload: AgendaReminderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaReminder:
    reminder = await agenda_create_reminder(db, user, tenant_id, item_id, payload)
    await db.commit()
    return reminder


@router.post(
    "/agenda/reminders/{reminder_id}/dismiss",
    response_model=AgendaReminderRead,
    dependencies=[Depends(has_permission("secretariat.manage_agenda_reminders"))],
)
async def dismiss_agenda_reminder(
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaReminder:
    reminder = await agenda_dismiss_reminder(db, user, tenant_id, reminder_id)
    await db.commit()
    return reminder


@router.get(
    "/agenda/overview",
    response_model=AgendaOverview,
    dependencies=[Depends(has_any_permission(["secretariat.view_agenda", "secretariat.use_agent_agenda"]))],
)
async def agenda_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    overview = await agenda_get_overview(db, user, tenant_id)
    await db.commit()
    return overview
