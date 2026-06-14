from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.secretariat.models import SecretariatApproval, SecretariatDocument, SecretariatMailDraft, SecretariatMeeting
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata



def _user_id(user: User):
    identity = inspect(user).identity
    if identity and identity[0] is not None:
        return identity[0]
    raise RuntimeError("User identity is not available")

def _clean_metadata(metadata: dict | None) -> dict | None:
    return sanitize_secretariat_metadata(metadata)


async def _get_approval(db: AsyncSession, organisation_id: int, approval_id: int) -> SecretariatApproval:
    approval = await db.get(SecretariatApproval, approval_id)
    if approval is not None and approval.organisation_id != organisation_id:
        approval = None
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demande d'approbation introuvable")
    return approval


async def find_approved_request(
    db: AsyncSession,
    organisation_id: int,
    *,
    approval_type: str,
    target_type: str,
    target_id: str | int,
) -> SecretariatApproval | None:
    res = await db.execute(
        select(SecretariatApproval)
        .where(
            SecretariatApproval.organisation_id == organisation_id,
            SecretariatApproval.approval_type == approval_type,
            SecretariatApproval.target_type == target_type,
            SecretariatApproval.target_id == str(target_id),
            SecretariatApproval.status == "approved",
        )
        .order_by(SecretariatApproval.decided_at.desc().nullslast(), SecretariatApproval.updated_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def find_pending_request(
    db: AsyncSession,
    organisation_id: int,
    *,
    approval_type: str,
    target_type: str,
    target_id: str | int,
) -> SecretariatApproval | None:
    res = await db.execute(
        select(SecretariatApproval)
        .where(
            SecretariatApproval.organisation_id == organisation_id,
            SecretariatApproval.approval_type == approval_type,
            SecretariatApproval.target_type == target_type,
            SecretariatApproval.target_id == str(target_id),
            SecretariatApproval.status == "pending",
        )
        .order_by(SecretariatApproval.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def create_approval_request(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload,
) -> SecretariatApproval:
    existing = await find_pending_request(
        db,
        organisation_id,
        approval_type=payload.approval_type,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    if existing is not None:
        return existing
    approval = SecretariatApproval(
        organisation_id=organisation_id,
        requested_by_user_id=_user_id(user),
        agent_type=payload.agent_type,
        approval_type=payload.approval_type,
        target_type=payload.target_type,
        target_id=str(payload.target_id),
        title=payload.title,
        description=payload.description,
        status="pending",
        priority=payload.priority,
        metadata_json=_clean_metadata(payload.metadata_json),
    )
    db.add(approval)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="approval_requested",
        agent_type=approval.agent_type,
        target_type=approval.target_type,
        target_id=approval.target_id,
        metadata_json={
            "approval_id": approval.id,
            "approval_type": approval.approval_type,
            "priority": approval.priority,
            "status": approval.status,
        },
    )
    return approval


async def list_pending_approvals(db: AsyncSession, user: User, organisation_id: int) -> list[SecretariatApproval]:
    res = await db.execute(
        select(SecretariatApproval)
        .where(SecretariatApproval.organisation_id == organisation_id)
        .order_by(SecretariatApproval.status.asc(), SecretariatApproval.priority.desc(), SecretariatApproval.created_at.desc())
    )
    return list(res.scalars().all())


async def get_approval_detail(db: AsyncSession, user: User, organisation_id: int, approval_id: int) -> SecretariatApproval:
    approval = await _get_approval(db, organisation_id, approval_id)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="approval_viewed",
        agent_type=approval.agent_type,
        target_type="secretariat_approval",
        target_id=approval.id,
        metadata_json={"approval_type": approval.approval_type, "status": approval.status},
    )
    return approval


async def _apply_approval_side_effect(db: AsyncSession, approval: SecretariatApproval, status_value: str) -> None:
    if approval.target_type == "secretariat_mail_draft":
        if approval.approval_type not in {"mail_draft_approval", "gmail_draft_creation"}:
            return
        res = await db.execute(
            select(SecretariatMailDraft).where(
                SecretariatMailDraft.organisation_id == approval.organisation_id,
                SecretariatMailDraft.id == int(approval.target_id),
            )
        )
        draft = res.scalar_one_or_none()
        if draft is None:
            return
        if approval.approval_type == "mail_draft_approval":
            draft.status = status_value
        return

    if approval.target_type == "secretariat_document" and approval.approval_type == "document_synthesis_validation":
        res = await db.execute(
            select(SecretariatDocument).where(
                SecretariatDocument.organisation_id == approval.organisation_id,
                SecretariatDocument.id == int(approval.target_id),
            )
        )
        document = res.scalar_one_or_none()
        if document is None:
            return
        if status_value == "approved":
            document.status = "approved"
            await record_secretariat_audit(
                db,
                organisation_id=approval.organisation_id,
                user_id=approval.approved_by_user_id,
                action="document_synthesis_approved",
                agent_type="documents",
                target_type="secretariat_document",
                target_id=document.id,
                metadata_json={"approval_id": approval.id, "status": document.status},
            )
        elif status_value == "rejected":
            document.status = "rejected"
            await record_secretariat_audit(
                db,
                organisation_id=approval.organisation_id,
                user_id=approval.approved_by_user_id,
                action="document_synthesis_rejected",
                agent_type="documents",
                target_type="secretariat_document",
                target_id=document.id,
                metadata_json={"approval_id": approval.id, "status": document.status},
            )
        return

    if approval.target_type == "secretariat_meeting" and approval.approval_type == "meeting_minutes_validation":
        res = await db.execute(
            select(SecretariatMeeting).where(
                SecretariatMeeting.organisation_id == approval.organisation_id,
                SecretariatMeeting.id == int(approval.target_id),
            )
        )
        meeting = res.scalar_one_or_none()
        if meeting is None:
            return
        if status_value == "approved":
            meeting.approved_minutes = meeting.minutes_draft
            meeting.status = "approved"
            await record_secretariat_audit(
                db,
                organisation_id=approval.organisation_id,
                user_id=approval.approved_by_user_id,
                action="reunion_minutes_approved",
                agent_type="reunion",
                target_type="secretariat_meeting",
                target_id=meeting.id,
                metadata_json={"approval_id": approval.id, "status": meeting.status},
            )
        elif status_value == "rejected":
            meeting.status = "minutes_rejected"
            await record_secretariat_audit(
                db,
                organisation_id=approval.organisation_id,
                user_id=approval.approved_by_user_id,
                action="reunion_minutes_rejected",
                agent_type="reunion",
                target_type="secretariat_meeting",
                target_id=meeting.id,
                metadata_json={"approval_id": approval.id, "status": meeting.status},
            )


async def approve_request(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    approval_id: int,
    comment: str | None = None,
) -> SecretariatApproval:
    approval = await _get_approval(db, organisation_id, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette demande a déjà été décidée.")
    approval.status = "approved"
    approval.approved_by_user_id = _user_id(user)
    approval.decision_comment = comment
    approval.decided_at = datetime.now(timezone.utc)
    await _apply_approval_side_effect(db, approval, "approved")
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="approval_approved",
        agent_type=approval.agent_type,
        target_type=approval.target_type,
        target_id=approval.target_id,
        metadata_json={"approval_id": approval.id, "approval_type": approval.approval_type, "status": approval.status},
    )
    return approval


async def reject_request(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    approval_id: int,
    comment: str | None = None,
) -> SecretariatApproval:
    approval = await _get_approval(db, organisation_id, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette demande a déjà été décidée.")
    approval.status = "rejected"
    approval.approved_by_user_id = _user_id(user)
    approval.decision_comment = comment
    approval.decided_at = datetime.now(timezone.utc)
    await _apply_approval_side_effect(db, approval, "rejected")
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="approval_rejected",
        agent_type=approval.agent_type,
        target_type=approval.target_type,
        target_id=approval.target_id,
        metadata_json={"approval_id": approval.id, "approval_type": approval.approval_type, "status": approval.status},
    )
    return approval


async def cancel_request(db: AsyncSession, user: User, organisation_id: int, approval_id: int) -> SecretariatApproval:
    approval = await _get_approval(db, organisation_id, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette demande a déjà été décidée.")
    approval.status = "cancelled"
    approval.approved_by_user_id = _user_id(user)
    approval.decided_at = datetime.now(timezone.utc)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="approval_cancelled",
        agent_type=approval.agent_type,
        target_type=approval.target_type,
        target_id=approval.target_id,
        metadata_json={"approval_id": approval.id, "approval_type": approval.approval_type, "status": approval.status},
    )
    return approval
