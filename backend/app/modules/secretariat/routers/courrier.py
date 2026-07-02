from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parseaddr

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import SecretariatMailDraft
from app.modules.secretariat.schemas import (
    GmailDraftCreateOut,
    GmailMessageDetailOut,
    GmailMessageSummaryOut,
    MailClassificationOut,
    MailDraftOut,
    MailDraftRequest,
    MailDraftResponseOut,
    MailDraftSaveRequest,
    MailSummaryOut,
    SecretariatApprovalCreate,
)
from app.modules.secretariat.services.ai_service import (
    classify_email as ai_classify_email,
    generate_email_response as ai_generate_email_response,
    summarize_email as ai_summarize_email,
)
from app.modules.secretariat.services.approval_service import (
    create_approval_request as approval_create_request,
    find_approved_request as approval_find_approved_request,
    find_pending_request as approval_find_pending_request,
)
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata
from app.modules.secretariat.services.gmail_service import (
    create_gmail_draft as gmail_create_draft,
    get_message_detail as gmail_get_message_detail,
    list_recent_messages as gmail_list_recent_messages,
)

router = APIRouter()


async def _get_mail_draft(db: AsyncSession, tenant_id: int, draft_id: int) -> SecretariatMailDraft:
    res = await db.execute(
        select(SecretariatMailDraft).where(
            SecretariatMailDraft.organisation_id == tenant_id,
            SecretariatMailDraft.id == draft_id,
        )
    )
    draft = res.scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brouillon introuvable")
    return draft


@router.get(
    "/courrier/emails",
    response_model=list[GmailMessageSummaryOut],
    dependencies=[Depends(has_any_permission(["secretariat.read_mail", "secretariat.use_agent_courrier"]))],
)
async def list_courrier_emails(
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[dict]:
    rows = await gmail_list_recent_messages(db, user, tenant_id, limit=limit)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="gmail_messages_listed",
        agent_type="courrier",
        target_type="gmail_messages",
        target_id=None,
        metadata_json={"count": len(rows), "limit": limit},
    )
    await db.commit()
    return rows


@router.get(
    "/courrier/emails/{message_id}",
    response_model=GmailMessageDetailOut,
    dependencies=[Depends(has_any_permission(["secretariat.read_mail", "secretariat.use_agent_courrier"]))],
)
async def get_courrier_email(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    detail = await gmail_get_message_detail(db, user, tenant_id, message_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="gmail_message_read",
        agent_type="courrier",
        target_type="gmail_message",
        target_id=message_id,
        metadata_json={"message_id": message_id},
    )
    await db.commit()
    return detail


@router.post(
    "/courrier/emails/{message_id}/summarize",
    response_model=MailSummaryOut,
    dependencies=[Depends(has_permission("secretariat.generate_mail_summary"))],
)
async def summarize_courrier_email(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    detail = await gmail_get_message_detail(db, user, tenant_id, message_id)
    summary = await ai_summarize_email(detail, db=db, organisation_id=tenant_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_email_summarized",
        agent_type="courrier",
        target_type="gmail_message",
        target_id=message_id,
        metadata_json={
            "message_id": message_id,
            "priority": summary.get("suggested_priority"),
            "requires_response": summary.get("requires_response"),
        },
    )
    await db.commit()
    return {"message_id": message_id, **summary}


@router.post(
    "/courrier/emails/{message_id}/classify",
    response_model=MailClassificationOut,
    dependencies=[Depends(has_permission("secretariat.generate_mail_summary"))],
)
async def classify_courrier_email(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    detail = await gmail_get_message_detail(db, user, tenant_id, message_id)
    classification = await ai_classify_email(detail, db=db, organisation_id=tenant_id)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_email_classified",
        agent_type="courrier",
        target_type="gmail_message",
        target_id=message_id,
        metadata_json={
            "message_id": message_id,
            "category": classification.get("category"),
            "priority": classification.get("priority"),
        },
    )
    await db.commit()
    return {"message_id": message_id, **classification}


@router.post(
    "/courrier/emails/{message_id}/draft-response",
    response_model=MailDraftResponseOut,
    dependencies=[Depends(has_permission("secretariat.generate_mail_draft"))],
)
async def draft_courrier_response(
    message_id: str,
    payload: MailDraftRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> MailDraftResponseOut:
    detail = await gmail_get_message_detail(db, user, tenant_id, message_id)
    draft_payload = await ai_generate_email_response(detail, tone=payload.tone, instructions=payload.instructions, db=db, organisation_id=tenant_id)
    draft = SecretariatMailDraft(
        organisation_id=tenant_id,
        user_id=user.id,
        gmail_message_id=message_id,
        gmail_thread_id=detail.get("thread_id"),
        source_gmail_message_id=message_id,
        recipient_email=parseaddr(detail.get("from") or "")[1] or None,
        subject=draft_payload.get("subject") or f"Re: {detail.get('subject') or ''}".strip(),
        body=draft_payload.get("draft_body") or "",
        status="draft",
        ai_metadata_json={
            "tone": payload.tone,
            "has_user_instructions": bool(payload.instructions),
            "requires_human_validation": True,
        },
    )
    db.add(draft)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_response_generated",
        agent_type="courrier",
        target_type="secretariat_mail_draft",
        target_id=draft.id,
        metadata_json={"message_id": message_id, "status": "draft"},
    )
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_draft_saved",
        agent_type="courrier",
        target_type="secretariat_mail_draft",
        target_id=draft.id,
        metadata_json={"message_id": message_id, "status": "draft"},
    )
    await approval_create_request(
        db,
        user,
        tenant_id,
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id=str(draft.id),
            title=f"Valider le projet de réponse : {draft.subject}",
            description="Validation humaine requise avant toute action Gmail future.",
            priority="normal",
            metadata_json={"message_id": message_id, "draft_id": draft.id},
        ),
    )
    await db.commit()
    return MailDraftResponseOut(
        message_id=message_id,
        draft_id=draft.id,
        subject=draft.subject,
        draft_body=draft.body,
        requires_human_validation=True,
    )


@router.post(
    "/courrier/emails/{message_id}/drafts",
    response_model=MailDraftOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.generate_mail_draft"))],
)
async def save_courrier_draft(
    message_id: str,
    payload: MailDraftSaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMailDraft:
    detail = await gmail_get_message_detail(db, user, tenant_id, message_id)
    draft = SecretariatMailDraft(
        organisation_id=tenant_id,
        user_id=user.id,
        gmail_message_id=message_id,
        gmail_thread_id=detail.get("thread_id"),
        source_gmail_message_id=message_id,
        recipient_email=parseaddr(detail.get("from") or "")[1] or None,
        subject=payload.subject,
        body=payload.body,
        status="draft",
        ai_metadata_json=sanitize_secretariat_metadata(payload.ai_metadata_json),
    )
    db.add(draft)
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_draft_saved",
        agent_type="courrier",
        target_type="secretariat_mail_draft",
        target_id=draft.id,
        metadata_json={"message_id": message_id, "status": "draft"},
    )
    await approval_create_request(
        db,
        user,
        tenant_id,
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id=str(draft.id),
            title=f"Valider le projet de réponse : {draft.subject}",
            description="Validation humaine requise avant toute action Gmail future.",
            priority="normal",
            metadata_json={"message_id": message_id, "draft_id": draft.id},
        ),
    )
    await db.commit()
    return draft


@router.post(
    "/courrier/drafts/{draft_id}/create-gmail-draft",
    response_model=GmailDraftCreateOut,
    dependencies=[Depends(has_permission("secretariat.create_gmail_draft"))],
)
async def create_gmail_draft_from_internal_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> GmailDraftCreateOut:
    draft = await _get_mail_draft(db, tenant_id, draft_id)
    if draft.user_id != user.id and (user.role or "").lower() not in {"admin", "super_admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Brouillon hors périmètre utilisateur.")
    if draft.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Le brouillon interne doit être approuvé avant création Gmail.")
    if draft.gmail_draft_id or draft.status == "gmail_draft_created":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Brouillon Gmail déjà créé.")
    if draft.status == "rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Brouillon rejeté.")
    gmail_approval = await approval_find_approved_request(
        db,
        tenant_id,
        approval_type="gmail_draft_creation",
        target_type="secretariat_mail_draft",
        target_id=draft.id,
    )
    if gmail_approval is None:
        pending = await approval_find_pending_request(
            db,
            tenant_id,
            approval_type="gmail_draft_creation",
            target_type="secretariat_mail_draft",
            target_id=draft.id,
        )
        if pending is None:
            await approval_create_request(
                db,
                user,
                tenant_id,
                SecretariatApprovalCreate(
                    agent_type="courrier",
                    approval_type="gmail_draft_creation",
                    target_type="secretariat_mail_draft",
                    target_id=str(draft.id),
                    title=f"Autoriser la création du brouillon Gmail : {draft.subject}",
                    description="Validation humaine requise avant création du brouillon Gmail. Aucun mail ne sera envoyé.",
                    priority="high",
                    metadata_json={"draft_id": draft.id, "source_gmail_message_id": draft.source_gmail_message_id or draft.gmail_message_id},
                ),
            )
        await record_secretariat_audit(
            db,
            organisation_id=tenant_id,
            user_id=user.id,
            action="approval_execution_blocked",
            agent_type="courrier",
            target_type="secretariat_mail_draft",
            target_id=draft.id,
            status="blocked",
            metadata_json={"draft_id": draft.id, "approval_type": "gmail_draft_creation", "status": "pending"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La création du brouillon Gmail nécessite une approbation centralisée validée.",
        )
    source_detail = None
    recipient_email = draft.recipient_email
    in_reply_to_message_id = draft.source_gmail_message_id or draft.gmail_message_id
    if not recipient_email:
        source_detail = await gmail_get_message_detail(db, user, tenant_id, draft.source_gmail_message_id or draft.gmail_message_id)
        recipient_email = parseaddr(source_detail.get("from") or "")[1] or None
        in_reply_to_message_id = (source_detail.get("headers") or {}).get("message-id") or in_reply_to_message_id
    try:
        result = await gmail_create_draft(
            db,
            user,
            tenant_id,
            to=recipient_email or "",
            subject=draft.subject,
            body=draft.body,
            thread_id=draft.gmail_thread_id,
            in_reply_to_message_id=in_reply_to_message_id,
        )
    except HTTPException:
        await record_secretariat_audit(
            db,
            organisation_id=tenant_id,
            user_id=user.id,
            action="courrier_gmail_draft_creation_failed",
            agent_type="courrier",
            target_type="secretariat_mail_draft",
            target_id=draft.id,
            status="failed",
            metadata_json={
                "draft_id": draft.id,
                "source_gmail_message_id": draft.source_gmail_message_id or draft.gmail_message_id,
                "status": "failed",
            },
        )
        await db.commit()
        raise
    draft.gmail_draft_id = result.get("gmail_draft_id")
    draft.gmail_thread_id = result.get("thread_id") or draft.gmail_thread_id
    draft.gmail_draft_created_at = datetime.now(timezone.utc)
    draft.status = "gmail_draft_created"
    draft.ai_metadata_json = {
        **(draft.ai_metadata_json or {}),
        "gmail_draft_message_id": result.get("gmail_message_id"),
        "gmail_draft_created": True,
    }
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="courrier_gmail_draft_created",
        agent_type="courrier",
        target_type="secretariat_mail_draft",
        target_id=draft.id,
        metadata_json={
            "draft_id": draft.id,
            "gmail_draft_id": draft.gmail_draft_id,
            "source_gmail_message_id": draft.source_gmail_message_id or draft.gmail_message_id,
            "status": draft.status,
        },
    )
    await db.commit()
    return GmailDraftCreateOut(
        draft_id=draft.id,
        gmail_draft_id=draft.gmail_draft_id or "",
        gmail_thread_id=draft.gmail_thread_id,
        status=draft.status,
    )


@router.patch(
    "/courrier/drafts/{draft_id}/approve",
    response_model=MailDraftOut,
    dependencies=[Depends(has_permission("secretariat.approve_mail_draft"))],
)
async def approve_courrier_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMailDraft:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Validation directe désactivée. Utilisez le workflow centralisé des approbations.",
    )


@router.patch(
    "/courrier/drafts/{draft_id}/reject",
    response_model=MailDraftOut,
    dependencies=[Depends(has_permission("secretariat.approve_mail_draft"))],
)
async def reject_courrier_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatMailDraft:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Rejet direct désactivé. Utilisez le workflow centralisé des approbations.",
    )
