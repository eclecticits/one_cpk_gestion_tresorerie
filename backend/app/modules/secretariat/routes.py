from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parseaddr
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import (
    OAuthConnection,
    SecretariatAgent,
    SecretariatAgendaItem,
    SecretariatAgendaReminder,
    SecretariatApproval,
    SecretariatAuditLog,
    SecretariatConversation,
    SecretariatMailDraft,
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
    SecretariatMessage,
    SecretariatDocumentVersion,
    SecretariatTask,
)
from app.modules.secretariat.schemas import (
    AgendaItemCreate,
    AgendaItemRead,
    AgendaItemUpdate,
    AgendaOverview,
    AgendaReminderCreate,
    AgendaReminderRead,
    SecretariatDocumentCreate,
    SecretariatDocumentRead,
    SecretariatDocumentSummary,
    SecretariatDocumentSynthesis,
    SecretariatDocumentUpdate,
    SecretariatDocumentVersionCreate,
    SecretariatDocumentVersionRead,
    OAuthStatusOut,
    GmailMessageDetailOut,
    GmailMessageSummaryOut,
    GmailDraftCreateOut,
    GoogleConnectOut,
    MailClassificationOut,
    MailDraftOut,
    MailDraftRequest,
    MailDraftResponseOut,
    MailDraftSaveRequest,
    MailSummaryOut,
    ManagerApprovalItem,
    ManagerFollowupTaskCreate,
    ManagerOverviewOut,
    ManagerRecommendedAction,
    ManagerWorkloadOut,
    MeetingGeneratedTextOut,
    MeetingNotesRequest,
    MeetingSubmitApprovalOut,
    MeetingTextGenerationRequest,
    SecretariatAgentCreate,
    SecretariatAgentOut,
    SecretariatApprovalCreate,
    SecretariatApprovalDecision,
    SecretariatApprovalOut,
    SecretariatAuditLogOut,
    SecretariatConversationCreate,
    SecretariatConversationOut,
    SecretariatMeetingActionItemOut,
    SecretariatMeetingCreate,
    SecretariatMeetingDecisionOut,
    SecretariatMeetingDetailOut,
    SecretariatMeetingOut,
    SecretariatMeetingParticipantCreate,
    SecretariatMeetingParticipantOut,
    SecretariatMeetingUpdate,
    SecretariatMessageCreate,
    SecretariatMessageOut,
    SecretariatTaskCreate,
    SecretariatTaskOut,
    SecretariatTaskUpdate,
)
from app.modules.secretariat.services.audit import record_secretariat_audit
from app.modules.secretariat.services.ai_service import (
    classify_email as ai_classify_email,
    generate_email_response as ai_generate_email_response,
    summarize_email as ai_summarize_email,
)
from app.modules.secretariat.services.approval_service import (
    approve_request as approval_approve_request,
    cancel_request as approval_cancel_request,
    create_approval_request as approval_create_request,
    find_approved_request as approval_find_approved_request,
    find_pending_request as approval_find_pending_request,
    get_approval_detail as approval_get_detail,
    list_pending_approvals as approval_list_pending,
    reject_request as approval_reject_request,
)
from app.modules.secretariat.services.gmail_service import (
    create_gmail_draft as gmail_create_draft,
    get_message_detail as gmail_get_message_detail,
    list_recent_messages as gmail_list_recent_messages,
)
from app.modules.secretariat.services.audit import sanitize_secretariat_metadata
from app.modules.secretariat.services.manager_agent_agentor import run_manager_agent
from app.modules.secretariat.services.agent_manager import (
    create_followup_task as manager_create_followup_task,
    get_agent_workload as manager_get_agent_workload,
    get_pending_approvals as manager_get_pending_approvals,
    get_recommended_actions as manager_get_recommended_actions,
    get_secretariat_overview as manager_get_secretariat_overview,
)
from app.modules.secretariat.services.agenda_agent import (
    cancel_agenda_item as agenda_cancel_item,
    complete_agenda_item as agenda_complete_item,
    create_agenda_item as agenda_create_item,
    create_reminder as agenda_create_reminder,
    dismiss_reminder as agenda_dismiss_reminder,
    get_agenda_item as agenda_get_item,
    get_agenda_overview as agenda_get_overview,
    get_or_create_reunion_agenda_item as agenda_get_or_create_reunion_item,
    list_agenda_items as agenda_list_items,
    list_reminders as agenda_list_reminders,
    update_agenda_item as agenda_update_item,
)
from app.modules.secretariat.services.documents_agent import (
    add_document_version as documents_add_version,
    archive_document as documents_archive,
    create_document as documents_create,
    generate_synthesis as documents_generate_synthesis,
    get_document as documents_get,
    list_documents as documents_list,
    summarize_document as documents_summarize,
    submit_synthesis_for_approval as documents_submit_synthesis,
    update_document as documents_update,
)
from app.modules.secretariat.services.oauth_service import (
    build_google_authorization_url,
    disconnect_google_connection,
    exchange_code_for_tokens,
    fetch_google_email,
    get_oauth_connection,
    upsert_google_connection,
    validate_google_state,
)
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


def _google_callback_html(
    success: bool,
    message: str,
    error_code: str | None = None,
    return_to: str | None = None,
) -> HTMLResponse:
    import json as _json
    import urllib.parse
    params: dict[str, str] = {"google": "connected" if success else "error"}
    if error_code:
        params["google_error"] = error_code

    # Origine autorisée pour postMessage (extraite de return_to pour la sécurité)
    if return_to:
        _parsed = urllib.parse.urlparse(return_to)
        allowed_origin = f"{_parsed.scheme}://{_parsed.netloc}"
    else:
        allowed_origin = "*"

    qs = urllib.parse.urlencode(params)
    base = (return_to or "/secretariat/courrier").rstrip("?")
    fallback_target = f"{base}?{qs}"
    msg_data = _json.dumps({"type": "google_oauth", **params})

    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="fr">
  <head><meta charset="utf-8"><title>Connexion Google</title></head>
  <body style="font-family:Arial,sans-serif;padding:32px;text-align:center">
    <p style="font-size:18px">{"✅ " if success else "❌ "}{message}</p>
    <p style="color:#6b7280;font-size:14px">Cette fenêtre va se fermer automatiquement…</p>
    <script>
      (function() {{
        var data = {msg_data};
        if (window.opener && !window.opener.closed) {{
          window.opener.postMessage(data, "{allowed_origin}");
          setTimeout(function() {{ window.close(); }}, 800);
        }} else {{
          window.location.replace("{fallback_target}");
        }}
      }})();
    </script>
  </body>
</html>""",
        status_code=200,
    )


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


@router.get("/oauth/status", response_model=OAuthStatusOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def oauth_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    res = await db.execute(
        select(OAuthConnection).where(
            OAuthConnection.organisation_id == tenant_id,
            OAuthConnection.user_id == user.id,
            OAuthConnection.provider == "google",
        )
    )
    connection = res.scalar_one_or_none()
    if connection is None:
        return OAuthStatusOut()
    return OAuthStatusOut(
        configured=connection.status == "connected",
        connected=connection.status == "connected",
        status=connection.status,
        email=connection.email,
        scopes=list(connection.scopes or []),
        expires_at=connection.expires_at,
    )


@router.get("/google/connect", response_model=GoogleConnectOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def google_connect(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> GoogleConnectOut:
    # L'origin du navigateur (frontend) est embarqué dans le state JWT pour que le
    # callback puisse rediriger vers la bonne URL quel que soit l'environnement.
    frontend_origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").split("/api/")[0]
        or None
    )
    authorization_url = await build_google_authorization_url(
        db=db, user=user, organisation_id=tenant_id, frontend_origin=frontend_origin
    )
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="google_oauth_connect_started",
        agent_type="courrier",
        target_type="oauth_connection",
        target_id="google",
        metadata_json={"provider": "google", "scopes": ["gmail.readonly"]},
    )
    await db.commit()
    return GoogleConnectOut(authorization_url=authorization_url)


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    # Tenter d'extraire return_to depuis le state même en cas d'erreur
    _return_to: str | None = None
    if state:
        try:
            _, _, _return_to = validate_google_state(state)
        except Exception:
            pass

    if error:
        msgs = {
            "access_denied": "Accès refusé par Google. Assurez-vous d'être dans la liste des utilisateurs test de l'application OAuth.",
            "redirect_uri_mismatch": "URI de redirection non autorisée dans Google Cloud Console.",
        }
        human_msg = msgs.get(error, f"Erreur Google OAuth : {error}")
        return _google_callback_html(False, human_msg, error_code=error, return_to=_return_to)
    if not code or not state:
        return _google_callback_html(False, "Callback Google incomplet.", return_to=_return_to)
    try:
        user_id, tenant_id, _return_to = validate_google_state(state)
        res = await db.execute(
            select(User).where(
                User.id == user_id,
                User.organisation_id == tenant_id,
                User.active.is_(True),
            )
        )
        user = res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur OAuth invalide.")
        tokens = await exchange_code_for_tokens(code, db)
        access_token = tokens.get("access_token")
        email = await fetch_google_email(access_token) if access_token else None
        connection = await upsert_google_connection(
            db,
            user_id=user.id,
            organisation_id=tenant_id,
            tokens=tokens,
            email=email,
        )
        await db.flush()
        await record_secretariat_audit(
            db,
            organisation_id=tenant_id,
            user_id=user.id,
            action="google_oauth_connected",
            agent_type="courrier",
            target_type="oauth_connection",
            target_id=connection.id,
            metadata_json={"provider": "google", "email": email, "scopes": connection.scopes or []},
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        return _google_callback_html(False, "Connexion Google impossible.", return_to=_return_to)
    return _google_callback_html(True, "Connexion Google effectuée.", return_to=_return_to)


@router.get(
    "/google/status",
    response_model=OAuthStatusOut,
    dependencies=[Depends(has_any_permission(["secretariat.manage_oauth", "secretariat.use_agent_courrier"]))],
)
async def google_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=tenant_id)
    if connection is None:
        return OAuthStatusOut()
    connected = connection.status == "connected"
    return OAuthStatusOut(
        configured=connected,
        connected=connected,
        status=connection.status,
        email=connection.email,
        scopes=list(connection.scopes or []),
        expires_at=connection.expires_at,
        message="Connexion Google active." if connected else "Connexion Google non configurée.",
    )


@router.delete("/google/disconnect", response_model=OAuthStatusOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def google_disconnect(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=tenant_id)
    if connection is None:
        return OAuthStatusOut()
    await disconnect_google_connection(db, connection)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="google_oauth_disconnected",
        agent_type="courrier",
        target_type="oauth_connection",
        target_id=connection.id,
        metadata_json={"provider": "google", "email": connection.email},
    )
    await db.commit()
    return OAuthStatusOut(status="disconnected", email=connection.email, message="Connexion Google désactivée.")


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


@router.get(
    "/documents",
    response_model=list[SecretariatDocumentRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def list_documents(
    document_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    author_id: UUID | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await documents_list(
        db,
        tenant_id,
        document_type=document_type,
        category=category,
        status_value=status_value,
        date_from=date_from,
        date_to=date_to,
        author_id=author_id,
        keyword=keyword,
    )


@router.post(
    "/documents",
    response_model=SecretariatDocumentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def create_document(
    payload: SecretariatDocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocument:
    document = await documents_create(db, user, tenant_id, payload)
    await db.commit()
    return document


@router.get(
    "/documents/{document_id}",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocument:
    return await documents_get(db, tenant_id, document_id)


@router.patch(
    "/documents/{document_id}",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def update_document(
    document_id: int,
    payload: SecretariatDocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocument:
    document = await documents_update(db, user, tenant_id, document_id, payload)
    await db.commit()
    return document


@router.post(
    "/documents/{document_id}/archive",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def archive_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocument:
    document = await documents_archive(db, user, tenant_id, document_id)
    await db.commit()
    return document


@router.post(
    "/documents/{document_id}/versions",
    response_model=SecretariatDocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def add_document_version(
    document_id: int,
    payload: SecretariatDocumentVersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentVersionRead:
    version = await documents_add_version(db, user, tenant_id, document_id, payload)
    await db.commit()
    return version


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[SecretariatDocumentVersionRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def list_document_versions(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatDocumentVersion]:
    await documents_get(db, tenant_id, document_id)
    res = await db.execute(
        select(SecretariatDocumentVersion).where(
            SecretariatDocumentVersion.organisation_id == tenant_id,
            SecretariatDocumentVersion.document_id == document_id,
        ).order_by(SecretariatDocumentVersion.version_number.asc())
    )
    return list(res.scalars().all())


@router.post(
    "/documents/{document_id}/summarize",
    response_model=SecretariatDocumentSummary,
    dependencies=[Depends(has_permission("secretariat.generate_document_summary"))],
)
async def summarize_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentSummary:
    document = await documents_summarize(db, user, tenant_id, document_id)
    await db.commit()
    return SecretariatDocumentSummary(document_id=document.id, summary_text=document.summary_text or "", requires_human_validation=True)


@router.post(
    "/documents/{document_id}/generate-synthesis",
    response_model=SecretariatDocumentSynthesis,
    dependencies=[Depends(has_permission("secretariat.generate_document_summary"))],
)
async def generate_document_synthesis(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentSynthesis:
    document = await documents_generate_synthesis(db, user, tenant_id, document_id)
    await db.commit()
    return SecretariatDocumentSynthesis(document_id=document.id, synthesis_text=document.synthesis_text or "", requires_human_validation=True)


@router.post(
    "/documents/{document_id}/submit-synthesis-approval",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_permission("secretariat.submit_document_synthesis"))],
)
async def submit_document_synthesis_approval(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await documents_submit_synthesis(db, user, tenant_id, document_id)
    await db.commit()
    return approval


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
