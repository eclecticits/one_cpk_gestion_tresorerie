from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.modules.secretariat.models import (
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
)
from app.modules.secretariat.schemas import SecretariatApprovalCreate
from app.modules.secretariat.services.ai_service import _prompt, _responses_json
from app.modules.secretariat.services.approval_service import create_approval_request, find_pending_request
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata


PUBLIC_MEETING_UPDATE_FIELDS = {"title", "meeting_type", "location", "meeting_date", "start_time", "end_time"}
SENSITIVE_MEETING_FIELDS = {"status", "agenda_text", "invitation_draft", "minutes_draft", "approved_minutes", "metadata_json"}


TEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}

DECISIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "decision_text": {"type": "string"},
                    "responsible_name": {"type": ["string", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["open", "in_progress", "completed", "cancelled"]},
                },
                "required": ["decision_text", "responsible_name", "due_date", "status"],
            },
        }
    },
    "required": ["decisions"],
}

ACTION_ITEMS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "responsible_name": {"type": ["string", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                },
                "required": ["title", "description", "responsible_name", "due_date", "priority", "status"],
            },
        }
    },
    "required": ["action_items"],
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _meeting_context(meeting: SecretariatMeeting, *, instructions: str | None = None) -> str:
    notes = ((meeting.metadata_json or {}).get("discussion_notes") or "").strip()
    if len(notes) > 8000:
        notes = f"{notes[:8000]}\n\n[Notes tronquées pour minimisation des données]"
    data = {
        "meeting": {
            "id": meeting.id,
            "title": meeting.title,
            "meeting_type": meeting.meeting_type,
            "location": meeting.location,
            "meeting_date": meeting.meeting_date.isoformat() if meeting.meeting_date else None,
            "start_time": meeting.start_time.isoformat() if meeting.start_time else None,
            "end_time": meeting.end_time.isoformat() if meeting.end_time else None,
            "status": meeting.status,
            "agenda_text": meeting.agenda_text,
            "invitation_draft": meeting.invitation_draft,
            "discussion_notes": notes,
        },
        "participants": [
            {
                "name": participant.name,
                "email": participant.email,
                "role": participant.role,
                "attendance_status": participant.attendance_status,
            }
            for participant in meeting.participants
        ],
        "decisions": [
            {
                "decision_text": decision.decision_text,
                "responsible_name": decision.responsible_name,
                "due_date": decision.due_date.isoformat() if decision.due_date else None,
                "status": decision.status,
            }
            for decision in meeting.decisions
        ],
        "action_items": [
            {
                "title": item.title,
                "description": item.description,
                "responsible_name": item.responsible_name,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "priority": item.priority,
                "status": item.status,
            }
            for item in meeting.action_items
        ],
        "instructions": (instructions or "").strip() or None,
    }
    return json.dumps(data, ensure_ascii=False)


async def _get_meeting(db: AsyncSession, organisation_id: int, meeting_id: int) -> SecretariatMeeting:
    meeting = await db.get(SecretariatMeeting, meeting_id)
    if meeting is not None and meeting.organisation_id != organisation_id:
        meeting = None
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réunion introuvable")
    await db.refresh(
        meeting,
        attribute_names=["participants", "decisions", "action_items"],
    )
    return meeting


async def create_meeting(db: AsyncSession, user: User, organisation_id: int, payload) -> SecretariatMeeting:
    data = payload.model_dump()
    blocked = SENSITIVE_MEETING_FIELDS.intersection(data)
    if blocked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Champs réunion sensibles non modifiables via cette route.")
    meeting = SecretariatMeeting(organisation_id=organisation_id, created_by_user_id=user.id, **data)
    meeting.metadata_json = sanitize_secretariat_metadata(meeting.metadata_json)
    db.add(meeting)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_created",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"status": meeting.status, "meeting_type": meeting.meeting_type},
    )
    return meeting


async def update_meeting(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> SecretariatMeeting:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    changes = payload.model_dump(exclude_unset=True)
    blocked = set(changes) - PUBLIC_MEETING_UPDATE_FIELDS
    if blocked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Champs réunion sensibles non modifiables via cette route.")
    for field, value in changes.items():
        if field == "metadata_json":
            value = sanitize_secretariat_metadata(value)
        setattr(meeting, field, value)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_updated",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"fields": sorted(changes.keys()), "status": meeting.status},
    )
    return meeting


async def list_meetings(db: AsyncSession, organisation_id: int) -> list[SecretariatMeeting]:
    res = await db.execute(
        select(SecretariatMeeting)
        .where(SecretariatMeeting.organisation_id == organisation_id)
        .order_by(SecretariatMeeting.meeting_date.desc().nullslast(), SecretariatMeeting.created_at.desc())
    )
    return list(res.scalars().all())


async def get_meeting_detail(db: AsyncSession, organisation_id: int, meeting_id: int) -> SecretariatMeeting:
    return await _get_meeting(db, organisation_id, meeting_id)


async def add_participant(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> SecretariatMeetingParticipant:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    participant_data = payload.model_dump()
    participant_data["metadata_json"] = sanitize_secretariat_metadata(participant_data.get("metadata_json"))
    participant = SecretariatMeetingParticipant(organisation_id=organisation_id, meeting_id=meeting.id, **participant_data)
    db.add(participant)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_participant_added",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"participant_id": participant.id, "attendance_status": participant.attendance_status},
    )
    return participant


async def remove_participant(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, participant_id: int) -> None:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    res = await db.execute(
        select(SecretariatMeetingParticipant).where(
            SecretariatMeetingParticipant.organisation_id == organisation_id,
            SecretariatMeetingParticipant.meeting_id == meeting.id,
            SecretariatMeetingParticipant.id == participant_id,
        )
    )
    participant = res.scalar_one_or_none()
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant introuvable")
    await db.delete(participant)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_participant_removed",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"participant_id": participant_id},
    )


async def generate_agenda(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> str:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    result = await _responses_json(
        _prompt("reunion_agenda_system.txt"),
        f"Prépare un ordre du jour:\n{_meeting_context(meeting, instructions=payload.instructions)}",
        "reunion_agenda",
        TEXT_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
    meeting.agenda_text = result["text"]
    if meeting.status == "draft":
        meeting.status = "planned"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_agenda_generated",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"status": meeting.status},
    )
    return meeting.agenda_text


async def generate_invitation_draft(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> str:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    result = await _responses_json(
        _prompt("reunion_invitation_system.txt"),
        f"Rédige un projet d'invitation interne non envoyé:\n{_meeting_context(meeting, instructions=payload.instructions)}",
        "reunion_invitation",
        TEXT_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
    meeting.invitation_draft = result["text"]
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_invitation_generated",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"participants_count": len(meeting.participants)},
    )
    return meeting.invitation_draft


async def save_discussion_notes(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> SecretariatMeeting:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    meeting.metadata_json = {**(meeting.metadata_json or {}), "discussion_notes": payload.notes}
    if meeting.status in {"draft", "planned"}:
        meeting.status = "held"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_notes_saved",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"notes_length": len(payload.notes), "status": meeting.status},
    )
    return meeting


async def extract_decisions(db: AsyncSession, user: User, organisation_id: int, meeting_id: int) -> list[SecretariatMeetingDecision]:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    result = await _responses_json(
        _prompt("reunion_decisions_system.txt"),
        f"Extrais uniquement les décisions explicites:\n{_meeting_context(meeting)}",
        "reunion_decisions",
        DECISIONS_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
    await db.execute(delete(SecretariatMeetingDecision).where(SecretariatMeetingDecision.organisation_id == organisation_id, SecretariatMeetingDecision.meeting_id == meeting.id))
    decisions = [
        SecretariatMeetingDecision(
            organisation_id=organisation_id,
            meeting_id=meeting.id,
            decision_text=item["decision_text"],
            responsible_name=item.get("responsible_name"),
            due_date=_parse_date(item.get("due_date")),
            status=item.get("status") or "open",
        )
        for item in result.get("decisions", [])
        if item.get("decision_text")
    ]
    db.add_all(decisions)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_decisions_extracted",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"count": len(decisions)},
    )
    return decisions


async def extract_action_items(db: AsyncSession, user: User, organisation_id: int, meeting_id: int) -> list[SecretariatMeetingActionItem]:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    result = await _responses_json(
        _prompt("reunion_decisions_system.txt"),
        f"Extrais uniquement les tâches de suivi explicites:\n{_meeting_context(meeting)}",
        "reunion_action_items",
        ACTION_ITEMS_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
    await db.execute(delete(SecretariatMeetingActionItem).where(SecretariatMeetingActionItem.organisation_id == organisation_id, SecretariatMeetingActionItem.meeting_id == meeting.id))
    action_items = [
        SecretariatMeetingActionItem(
            organisation_id=organisation_id,
            meeting_id=meeting.id,
            title=item["title"],
            description=item.get("description"),
            responsible_name=item.get("responsible_name"),
            due_date=_parse_date(item.get("due_date")),
            priority=item.get("priority") or "normal",
            status=item.get("status") or "pending",
        )
        for item in result.get("action_items", [])
        if item.get("title")
    ]
    db.add_all(action_items)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_action_items_extracted",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"count": len(action_items)},
    )
    return action_items


async def generate_minutes_draft(db: AsyncSession, user: User, organisation_id: int, meeting_id: int, payload) -> str:
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    result = await _responses_json(
        _prompt("reunion_minutes_system.txt"),
        f"Rédige un projet de PV simple:\n{_meeting_context(meeting, instructions=payload.instructions)}",
        "reunion_minutes",
        TEXT_SCHEMA,
        db=db,
        organisation_id=organisation_id,
    )
    meeting.minutes_draft = result["text"]
    meeting.status = "minutes_draft"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_minutes_generated",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"status": meeting.status},
    )
    return meeting.minutes_draft


async def submit_minutes_for_approval(db: AsyncSession, user: User, organisation_id: int, meeting_id: int):
    meeting = await _get_meeting(db, organisation_id, meeting_id)
    if not meeting.minutes_draft:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Projet de PV requis avant soumission.")
    pending = await find_pending_request(
        db,
        organisation_id,
        approval_type="meeting_minutes_validation",
        target_type="secretariat_meeting",
        target_id=meeting.id,
    )
    approval = pending or await create_approval_request(
        db,
        user,
        organisation_id,
        SecretariatApprovalCreate(
            agent_type="reunion",
            approval_type="meeting_minutes_validation",
            target_type="secretariat_meeting",
            target_id=str(meeting.id),
            title=f"Valider le PV : {meeting.title}",
            description="Validation humaine obligatoire du projet de PV.",
            priority="normal",
            metadata_json={"meeting_id": meeting.id, "status": meeting.status},
        ),
    )
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="reunion_minutes_submitted_for_approval",
        agent_type="reunion",
        target_type="secretariat_meeting",
        target_id=meeting.id,
        metadata_json={"approval_id": approval.id, "status": approval.status},
    )
    return approval
