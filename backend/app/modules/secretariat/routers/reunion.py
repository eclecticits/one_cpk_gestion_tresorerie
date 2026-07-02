from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import (
    SecretariatAgendaItem,
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
)
from app.modules.secretariat.schemas import (
    AgendaItemCreate,
    AgendaItemRead,
    MeetingGeneratedTextOut,
    MeetingNotesRequest,
    MeetingSubmitApprovalOut,
    MeetingTextGenerationRequest,
    SecretariatMeetingActionItemOut,
    SecretariatMeetingCreate,
    SecretariatMeetingDecisionOut,
    SecretariatMeetingDetailOut,
    SecretariatMeetingOut,
    SecretariatMeetingParticipantCreate,
    SecretariatMeetingParticipantOut,
    SecretariatMeetingUpdate,
)
from app.modules.secretariat.services.agenda_agent import get_or_create_reunion_agenda_item as agenda_get_or_create_reunion_item
from app.modules.secretariat.services.reunion_agent import (
    add_participant as reunion_add_participant,
    create_meeting as reunion_create_meeting,
    extract_action_items as reunion_extract_action_items,
    extract_decisions as reunion_extract_decisions,
    generate_agenda as reunion_generate_agenda,
    generate_invitation_draft as reunion_generate_invitation_draft,
    generate_minutes_draft as reunion_generate_minutes_draft,
    get_meeting_detail as reunion_get_meeting_detail,
    list_meetings as reunion_list_meetings,
    remove_participant as reunion_remove_participant,
    save_discussion_notes as reunion_save_discussion_notes,
    submit_minutes_for_approval as reunion_submit_minutes_for_approval,
    update_meeting as reunion_update_meeting,
)

router = APIRouter()


@router.get(
    "/reunions",
    response_model=list[SecretariatMeetingOut],
    dependencies=[Depends(has_any_permission(["secretariat.view", "secretariat.use_agent_reunion"]))],
)
async def list_reunions(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatMeeting]:
    return await reunion_list_meetings(db, tenant_id)


@router.post(
    "/reunions",
    response_model=SecretariatMeetingDetailOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_meetings"))],
)
async def create_reunion(
    payload: SecretariatMeetingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMeeting:
    meeting = await reunion_create_meeting(db, user, tenant_id, payload)
    await db.commit()
    return meeting


@router.post(
    "/reunions/{meeting_id}/create-agenda-item",
    response_model=AgendaItemRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_agenda"))],
)
async def create_reunion_agenda_item(
    meeting_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatAgendaItem:
    meeting = await reunion_get_meeting_detail(db, tenant_id, meeting_id)
    due_at = None
    if meeting.meeting_date:
        due_time = meeting.start_time or datetime.min.time()
        due_at = datetime.combine(meeting.meeting_date, due_time, tzinfo=timezone.utc)
    item, reused = await agenda_get_or_create_reunion_item(
        db,
        user,
        tenant_id,
        meeting.id,
        AgendaItemCreate(
            title=f"Préparer la réunion : {meeting.title}",
            description="Échéance interne liée à une réunion Secrétariat.",
            item_type="meeting",
            priority="normal",
            status="pending",
            due_at=due_at,
            target_type="secretariat_meeting",
            target_id=str(meeting.id),
            metadata_json={"source": "reunion"},
        ),
    )
    if reused:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Agenda-Message"] = "Une échéance Agenda existe déjà pour cette réunion."
    await db.commit()
    return item


@router.get(
    "/reunions/{meeting_id}",
    response_model=SecretariatMeetingDetailOut,
    dependencies=[Depends(has_any_permission(["secretariat.view", "secretariat.use_agent_reunion"]))],
)
async def get_reunion(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMeeting:
    return await reunion_get_meeting_detail(db, tenant_id, meeting_id)


@router.patch(
    "/reunions/{meeting_id}",
    response_model=SecretariatMeetingDetailOut,
    dependencies=[Depends(has_permission("secretariat.manage_meetings"))],
)
async def update_reunion(
    meeting_id: int,
    payload: SecretariatMeetingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMeeting:
    meeting = await reunion_update_meeting(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return await reunion_get_meeting_detail(db, tenant_id, meeting.id)


@router.post(
    "/reunions/{meeting_id}/participants",
    response_model=SecretariatMeetingParticipantOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_meetings"))],
)
async def add_reunion_participant(
    meeting_id: int,
    payload: SecretariatMeetingParticipantCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMeetingParticipant:
    participant = await reunion_add_participant(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return participant


@router.delete(
    "/reunions/{meeting_id}/participants/{participant_id}",
    dependencies=[Depends(has_permission("secretariat.manage_meetings"))],
)
async def remove_reunion_participant(
    meeting_id: int,
    participant_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    await reunion_remove_participant(db, user, tenant_id, meeting_id, participant_id)
    await db.commit()
    return {"ok": True}


@router.post(
    "/reunions/{meeting_id}/generate-agenda",
    response_model=MeetingGeneratedTextOut,
    dependencies=[Depends(has_permission("secretariat.generate_meeting_documents"))],
)
async def generate_reunion_agenda(
    meeting_id: int,
    payload: MeetingTextGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> MeetingGeneratedTextOut:
    text = await reunion_generate_agenda(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return MeetingGeneratedTextOut(meeting_id=meeting_id, text=text)


@router.post(
    "/reunions/{meeting_id}/generate-invitation",
    response_model=MeetingGeneratedTextOut,
    dependencies=[Depends(has_permission("secretariat.generate_meeting_documents"))],
)
async def generate_reunion_invitation(
    meeting_id: int,
    payload: MeetingTextGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> MeetingGeneratedTextOut:
    text = await reunion_generate_invitation_draft(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return MeetingGeneratedTextOut(meeting_id=meeting_id, text=text)


@router.post(
    "/reunions/{meeting_id}/save-notes",
    response_model=SecretariatMeetingDetailOut,
    dependencies=[Depends(has_permission("secretariat.manage_meetings"))],
)
async def save_reunion_notes(
    meeting_id: int,
    payload: MeetingNotesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMeeting:
    meeting = await reunion_save_discussion_notes(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return await reunion_get_meeting_detail(db, tenant_id, meeting.id)


@router.post(
    "/reunions/{meeting_id}/extract-decisions",
    response_model=list[SecretariatMeetingDecisionOut],
    dependencies=[Depends(has_permission("secretariat.generate_meeting_documents"))],
)
async def extract_reunion_decisions(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatMeetingDecision]:
    rows = await reunion_extract_decisions(db, user, tenant_id, meeting_id)
    await db.commit()
    return rows


@router.post(
    "/reunions/{meeting_id}/extract-action-items",
    response_model=list[SecretariatMeetingActionItemOut],
    dependencies=[Depends(has_permission("secretariat.generate_meeting_documents"))],
)
async def extract_reunion_action_items(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatMeetingActionItem]:
    rows = await reunion_extract_action_items(db, user, tenant_id, meeting_id)
    await db.commit()
    return rows


@router.post(
    "/reunions/{meeting_id}/generate-minutes",
    response_model=MeetingGeneratedTextOut,
    dependencies=[Depends(has_permission("secretariat.generate_meeting_documents"))],
)
async def generate_reunion_minutes(
    meeting_id: int,
    payload: MeetingTextGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> MeetingGeneratedTextOut:
    text = await reunion_generate_minutes_draft(db, user, tenant_id, meeting_id, payload)
    await db.commit()
    return MeetingGeneratedTextOut(meeting_id=meeting_id, text=text)


@router.post(
    "/reunions/{meeting_id}/submit-minutes-approval",
    response_model=MeetingSubmitApprovalOut,
    dependencies=[Depends(has_permission("secretariat.submit_meeting_minutes"))],
)
async def submit_reunion_minutes_approval(
    meeting_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> MeetingSubmitApprovalOut:
    approval = await reunion_submit_minutes_for_approval(db, user, tenant_id, meeting_id)
    await db.commit()
    return MeetingSubmitApprovalOut(meeting_id=meeting_id, approval_id=approval.id, status=approval.status)
