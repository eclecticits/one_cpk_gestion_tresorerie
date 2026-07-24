from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import delete, select

from app.api.deps import has_permission
from app.core.tenant_context import set_current_tenant_id
from app.models.organisation import Organisation
from app.models.rbac import Permission, Role, role_permissions
from app.models.user import User
from app.modules.secretariat.permissions import (
    SECRETARIAT_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
    SECRETARIAT_PERMISSIONS,
    SECRETARIAT_ROLE_PERMISSION_MATRIX,
    SECRETARIAT_ROLE_TEMPLATES,
)
from app.modules.secretariat.models import (
    OAuthConnection,
    SecretariatAgent,
    SecretariatAgendaItem,
    SecretariatAgendaReminder,
    SecretariatDocument,
    SecretariatDocumentVersion,
    SecretariatApproval,
    SecretariatAuditLog,
    SecretariatConversation,
    SecretariatMailDraft,
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
    SecretariatMessage,
    SecretariatTask,
)
from app.modules.secretariat.routers.agenda import (
    agenda_overview,
    cancel_agenda_item,
    complete_agenda_item,
    create_agenda_item,
    create_agenda_reminder,
    dismiss_agenda_reminder,
    list_agenda_items,
    list_agenda_reminders,
    update_agenda_item,
)
from app.modules.secretariat.routers.approvals import (
    approve_approval,
    create_approval,
    list_approvals,
    reject_approval,
)
from app.modules.secretariat.routers.core import (
    create_agent,
    create_task,
    list_agents,
    list_audit_logs,
    update_task,
)
from app.modules.secretariat.routers.courrier import (
    approve_courrier_draft,
    classify_courrier_email,
    create_gmail_draft_from_internal_draft,
    draft_courrier_response,
    reject_courrier_draft,
    summarize_courrier_email,
)
from app.modules.secretariat.routers.documents import (
    add_document_version,
    archive_document,
    create_document,
    generate_document_synthesis,
    get_document,
    list_document_versions,
    list_documents,
    submit_document_synthesis_approval,
    summarize_document,
    update_document,
)
from app.modules.secretariat.routers.manager import (
    manager_followup_task,
    manager_overview,
    manager_pending_approvals,
    manager_recommended_actions,
)
from app.modules.secretariat.routers.oauth import google_connect, google_status
from app.modules.secretariat.routers.reunion import (
    add_reunion_participant,
    create_reunion,
    create_reunion_agenda_item,
    generate_reunion_agenda,
    generate_reunion_invitation,
    generate_reunion_minutes,
    list_reunions,
    save_reunion_notes,
    submit_reunion_minutes_approval,
    update_reunion,
)
from app.modules.secretariat.schemas import (
    AgendaItemCreate,
    AgendaItemUpdate,
    AgendaReminderCreate,
    MailDraftRequest,
    ManagerFollowupTaskCreate,
    ManagerOverviewOut,
    MeetingTextGenerationRequest,
    MeetingNotesRequest,
    SecretariatDocumentCreate,
    SecretariatDocumentRead,
    SecretariatDocumentUpdate,
    SecretariatDocumentVersionCreate,
    SecretariatDocumentVersionRead,
    SecretariatAgentCreate,
    SecretariatApprovalCreate,
    SecretariatApprovalDecision,
    SecretariatMeetingCreate,
    SecretariatMeetingParticipantCreate,
    SecretariatMeetingUpdate,
    SecretariatTaskCreate,
    SecretariatTaskUpdate,
    OAuthStatusOut,
)
from app.modules.secretariat.services.ai_service import summarize_email
from app.modules.secretariat.services.gmail_service import create_gmail_draft, list_recent_messages
from app.modules.secretariat.services.oauth_service import (
    _google_scopes,
    disconnect_google_connection,
    encrypt_token,
    refresh_access_token_if_needed,
)
from app.modules.secretariat.services.audit import record_secretariat_audit


async def _cleanup(db_session) -> None:
    set_current_tenant_id(None)
    await db_session.execute(delete(SecretariatAuditLog))
    await db_session.execute(delete(SecretariatApproval))
    await db_session.execute(delete(OAuthConnection))
    await db_session.execute(delete(SecretariatMailDraft))
    await db_session.execute(delete(SecretariatDocumentVersion))
    await db_session.execute(delete(SecretariatDocument))
    await db_session.execute(delete(SecretariatAgendaReminder))
    await db_session.execute(delete(SecretariatAgendaItem))
    await db_session.execute(delete(SecretariatMeetingActionItem))
    await db_session.execute(delete(SecretariatMeetingDecision))
    await db_session.execute(delete(SecretariatMeetingParticipant))
    await db_session.execute(delete(SecretariatMeeting))
    await db_session.execute(delete(SecretariatTask))
    await db_session.execute(delete(SecretariatMessage))
    await db_session.execute(delete(SecretariatConversation))
    await db_session.execute(delete(SecretariatAgent))
    await db_session.commit()


async def _seed_user(
    db_session,
    *,
    with_secretariat_permission: bool = True,
    permission_codes: list[str] | None = None,
) -> tuple[Organisation, User]:
    org = Organisation(nom=f"CPK SEC {uuid.uuid4()}", slug=f"cpk-sec-{uuid.uuid4().hex[:8]}", is_active=True)
    role = Role(code=f"secretariat_role_{uuid.uuid4().hex[:8]}", label="Secrétariat")
    db_session.add_all([org, role])
    await db_session.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"sec-{uuid.uuid4().hex[:8]}@example.com",
        role="reception",
        role_id=role.id,
        organisation_id=org.id,
        active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    if with_secretariat_permission:
        all_permissions = SECRETARIAT_PERMISSIONS
        wanted = set(permission_codes) if permission_codes is not None else {code for code, _ in all_permissions}
        permissions = []
        for code, description in all_permissions:
            if code not in wanted:
                continue
            res = await db_session.execute(select(Permission).where(Permission.code == code))
            permission = res.scalar_one_or_none()
            if permission is None:
                permission = Permission(code=code, description=description)
                db_session.add(permission)
                await db_session.flush()
            permissions.append(permission)
        for permission in permissions:
            await db_session.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission.id))
    await db_session.commit()
    return org, user


async def _seed_secretariat_role_catalog(db_session) -> None:
    for code, description in SECRETARIAT_PERMISSIONS:
        res = await db_session.execute(select(Permission).where(Permission.code == code))
        permission = res.scalar_one_or_none()
        if permission is None:
            permission = Permission(code=code, description=description)
            db_session.add(permission)
            await db_session.flush()

    for role_code, template in SECRETARIAT_ROLE_TEMPLATES.items():
        res = await db_session.execute(select(Role).where(Role.code == role_code))
        role = res.scalar_one_or_none()
        if role is None:
            role = Role(code=role_code, label=str(template["label"]), description=f"Secrétariat - {template['label']}")
            db_session.add(role)
            await db_session.flush()
        for code in template["permissions"]:
            perm_res = await db_session.execute(select(Permission).where(Permission.code == code))
            permission = perm_res.scalar_one()
            link_res = await db_session.execute(
                select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role.id,
                    role_permissions.c.permission_id == permission.id,
                )
            )
            if link_res.first() is None:
                await db_session.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission.id))
    await db_session.commit()


def test_secretariat_admin_role_template_covers_all_secretariat_permissions():
    assert set(SECRETARIAT_ROLE_PERMISSION_MATRIX["administrateur_secretariat"]) == {
        code for code, _ in SECRETARIAT_PERMISSIONS
    }


def test_secretariat_seed_uses_central_permission_catalog():
    assert set(SECRETARIAT_PERMISSION_CODES) == {code for code, _ in SECRETARIAT_PERMISSIONS}
    for code, description in SECRETARIAT_PERMISSIONS:
        assert SECRETARIAT_PERMISSION_DESCRIPTIONS[code] == description


@pytest.mark.asyncio
async def test_secretariat_role_templates_are_seedable(db_session):
    await _cleanup(db_session)
    await _seed_secretariat_role_catalog(db_session)

    roles = (await db_session.execute(select(Role).where(Role.code.in_(SECRETARIAT_ROLE_TEMPLATES.keys())))).scalars().all()
    assert {role.code for role in roles} == set(SECRETARIAT_ROLE_TEMPLATES.keys())


@pytest.mark.asyncio
async def test_secretariat_seed_does_not_create_unknown_permissions(db_session):
    await _cleanup(db_session)
    await _seed_secretariat_role_catalog(db_session)

    codes = {row.code for row in (await db_session.execute(select(Permission))).scalars().all()}
    assert codes.issubset(set(SECRETARIAT_PERMISSION_CODES))


@pytest.mark.asyncio
async def test_secretariat_seed_creates_all_expected_secretariat_roles(db_session):
    await _cleanup(db_session)
    await _seed_secretariat_role_catalog(db_session)

    roles = (await db_session.execute(select(Role).where(Role.code.in_(SECRETARIAT_ROLE_TEMPLATES.keys())))).scalars().all()
    assert {role.code for role in roles} == set(SECRETARIAT_ROLE_TEMPLATES.keys())
    assert {role.label for role in roles} == {str(template["label"]) for template in SECRETARIAT_ROLE_TEMPLATES.values()}


@pytest.mark.asyncio
async def test_secretariat_seed_role_permissions_match_matrix_exactly(db_session):
    await _cleanup(db_session)
    await _seed_secretariat_role_catalog(db_session)

    for role_code, expected_permissions in SECRETARIAT_ROLE_PERMISSION_MATRIX.items():
        role = (await db_session.execute(select(Role).where(Role.code == role_code))).scalar_one()
        rows = await db_session.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role.id)
        )
        assigned = {code for (code,) in rows.all()}
        assert assigned == set(expected_permissions)


@pytest.mark.asyncio
async def test_secretariat_create_and_list_agents(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    agent = await create_agent(
        SecretariatAgentCreate(name="Agent Courrier", type="courrier", status="inactive"),
        db_session,
        user,
        org.id,
    )
    agents = await list_agents(db_session, org.id)

    assert agent.id is not None
    assert [row.name for row in agents] == ["Agent Courrier"]
    assert agents[0].organisation_id == org.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_agents_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, _ = await _seed_user(db_session)
    org_b = Organisation(nom=f"CN SEC {uuid.uuid4()}", slug=f"cn-sec-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org_b)
    await db_session.flush()

    set_current_tenant_id(org_a.id)
    db_session.add(SecretariatAgent(organisation_id=org_a.id, name="Agent A", type="courrier", status="inactive"))
    await db_session.commit()

    set_current_tenant_id(org_b.id)
    db_session.add(SecretariatAgent(organisation_id=org_b.id, name="Agent B", type="courrier", status="inactive"))
    await db_session.commit()

    rows_b = (await db_session.execute(select(SecretariatAgent))).scalars().all()
    assert [row.name for row in rows_b] == ["Agent B"]

    set_current_tenant_id(org_a.id)
    rows_a = (await db_session.execute(select(SecretariatAgent))).scalars().all()
    assert [row.name for row in rows_a] == ["Agent A"]
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.view")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_secretariat_permission_catalog_is_complete(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session)
    codes = {code for code, _ in SECRETARIAT_PERMISSIONS}

    assert "menu_secretariat" in codes
    assert {
        "secretariat.view",
        "secretariat.use_agent_courrier",
        "secretariat.use_agent_reunion",
        "secretariat.use_agent_agenda",
        "secretariat.use_agent_documents",
        "secretariat.use_agent_manager",
        "secretariat.manage_oauth",
        "secretariat.view_audit_logs",
        "secretariat.view_manager_dashboard",
        "secretariat.manage_tasks",
        "secretariat.manage_meetings",
        "secretariat.generate_meeting_documents",
        "secretariat.submit_meeting_minutes",
        "secretariat.view_documents",
        "secretariat.manage_documents",
        "secretariat.generate_document_summary",
        "secretariat.submit_document_synthesis",
        "secretariat.view_approvals",
        "secretariat.view_pending_approvals",
        "secretariat.create_approval",
        "secretariat.approve_action",
        "secretariat.reject_action",
        "secretariat.cancel_approval",
    }.issubset(codes)

    dependency = has_permission("secretariat.view")
    assert await dependency(user, db_session) == user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_code,expected,unexpected",
    [
        (
            "agent_courrier",
            {
                "menu_secretariat",
                "secretariat.view",
                "secretariat.use_agent_courrier",
                "secretariat.read_mail",
                "secretariat.generate_mail_summary",
                "secretariat.generate_mail_draft",
                "secretariat.create_gmail_draft",
            },
            {"secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_meetings", "secretariat.use_agent_manager"},
        ),
        (
            "agent_reunion",
            {
                "menu_secretariat",
                "secretariat.view",
                "secretariat.use_agent_reunion",
                "secretariat.manage_meetings",
                "secretariat.generate_meeting_documents",
                "secretariat.submit_meeting_minutes",
            },
            {"secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_documents", "secretariat.use_agent_manager"},
        ),
        (
            "agent_agenda",
            {
                "menu_secretariat",
                "secretariat.view",
                "secretariat.use_agent_agenda",
                "secretariat.view_agenda",
                "secretariat.manage_agenda",
                "secretariat.manage_agenda_reminders",
            },
            {"secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_meetings", "secretariat.use_agent_manager"},
        ),
        (
            "agent_documents",
            {
                "menu_secretariat",
                "secretariat.view",
                "secretariat.use_agent_documents",
                "secretariat.view_documents",
                "secretariat.manage_documents",
                "secretariat.generate_document_summary",
                "secretariat.submit_document_synthesis",
            },
            {"secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_meetings", "secretariat.use_agent_manager"},
        ),
        (
            "validateur",
            {
                "menu_secretariat",
                "secretariat.view",
                "secretariat.view_approvals",
                "secretariat.view_pending_approvals",
                "secretariat.approve_action",
                "secretariat.reject_action",
            },
            {"secretariat.manage_oauth", "secretariat.manage_meetings", "secretariat.manage_documents", "secretariat.use_agent_manager"},
        ),
        (
            "auditeur",
            {"menu_secretariat", "secretariat.view", "secretariat.view_audit_logs"},
            {"secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_meetings", "secretariat.use_agent_manager"},
        ),
    ],
)
async def test_secretariat_role_permission_matrix_respects_boundaries(db_session, role_code, expected, unexpected):
    await _cleanup(db_session)
    org = Organisation(nom=f"CPK {role_code}", slug=f"{role_code}-{uuid.uuid4().hex[:8]}", is_active=True)
    role = Role(code=f"{role_code}_{uuid.uuid4().hex[:8]}", label=role_code.replace("_", " ").title())
    db_session.add_all([org, role])
    await db_session.flush()

    user = User(
        id=uuid.uuid4(),
        email=f"{role_code}-{uuid.uuid4().hex[:8]}@example.com",
        role=role_code,
        role_id=role.id,
        organisation_id=org.id,
        active=True,
        is_email_verified=True,
    )
    db_session.add(user)

    for code in SECRETARIAT_ROLE_PERMISSION_MATRIX[role_code]:
        res = await db_session.execute(select(Permission).where(Permission.code == code))
        permission = res.scalar_one_or_none()
        if permission is None:
            permission = Permission(code=code, description=code)
            db_session.add(permission)
            await db_session.flush()
        await db_session.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission.id))

    await db_session.commit()

    for code in expected:
        dependency = has_permission(code)
        assert await dependency(user, db_session) == user

    for code in unexpected:
        dependency = has_permission(code)
        with pytest.raises(HTTPException):
            await dependency(user, db_session)


@pytest.mark.asyncio
async def test_secretariat_create_task(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    agent = SecretariatAgent(organisation_id=org.id, name="Agent Manager", type="manager", status="inactive")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    task = await create_task(
        SecretariatTaskCreate(agent_id=agent.id, title="Préparer la réunion", priority="high"),
        db_session,
        user,
        org.id,
    )

    assert task.id is not None
    assert task.organisation_id == org.id
    assert task.status == "pending"
    assert task.priority == "high"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_task_write_permissions_require_manage_tasks(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view"])

    dependency = has_permission("secretariat.manage_tasks")
    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_secretariat_view_does_not_grant_sensitive_actions(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view"])

    for code in ("secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_meetings"):
        dependency = has_permission(code)
        with pytest.raises(HTTPException) as exc_info:
            await dependency(user, db_session)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_secretariat_agent_permission_does_not_grant_administration(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.use_agent_courrier"])

    for code in ("secretariat.approve_action", "secretariat.manage_oauth", "secretariat.manage_agents"):
        dependency = has_permission(code)
        with pytest.raises(HTTPException) as exc_info:
            await dependency(user, db_session)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_update_task_function_keeps_tenant_scope(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    agent = SecretariatAgent(organisation_id=org.id, name="Agent Manager", type="manager", status="inactive")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = await create_task(
        SecretariatTaskCreate(agent_id=agent.id, title="Préparer la réunion", priority="high"),
        db_session,
        user,
        org.id,
    )

    updated = await update_task(task.id, SecretariatTaskUpdate(status="in_progress"), db_session, user, org.id)

    assert updated.status == "in_progress"
    assert updated.organisation_id == org.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_audit_logs_permission_and_read(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    db_session.add(
        SecretariatAuditLog(
            organisation_id=org.id,
            user_id=user.id,
            agent_type="manager",
            action="task.create",
            target_type="secretariat_task",
            target_id="1",
            status="success",
        )
    )
    await db_session.commit()

    dependency = has_permission("secretariat.view_audit_logs")
    assert await dependency(user, db_session) == user

    logs = await list_audit_logs(db_session, org.id)
    assert len(logs) == 1
    assert logs[0].action == "task.create"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_google_status_without_connection(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    status = await google_status(db_session, user, org.id)

    assert status.provider == "google"
    assert status.connected is False
    assert status.status == "not_configured"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_courrier_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.use_agent_courrier")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_oauth_connections_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    db_session.add(
        OAuthConnection(
            organisation_id=org_a.id,
            user_id=user_a.id,
            provider="google",
            email="a@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            status="connected",
        )
    )
    await db_session.commit()

    set_current_tenant_id(org_b.id)
    db_session.add(
        OAuthConnection(
            organisation_id=org_b.id,
            user_id=user_b.id,
            provider="google",
            email="b@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            status="connected",
        )
    )
    await db_session.commit()

    rows_b = (await db_session.execute(select(OAuthConnection))).scalars().all()
    assert [row.email for row in rows_b] == ["b@example.com"]

    set_current_tenant_id(org_a.id)
    db_session.expire_all()
    rows_a = (await db_session.execute(select(OAuthConnection))).scalars().all()
    assert [row.email for row in rows_a] == ["a@example.com"]
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_oauth_active_connection_is_unique_per_tenant_user_provider(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    db_session.add(
        OAuthConnection(
            organisation_id=org.id,
            user_id=user.id,
            provider="google",
            email="a@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            status="connected",
        )
    )
    await db_session.commit()
    db_session.add(
        OAuthConnection(
            organisation_id=org.id,
            user_id=user.id,
            provider="google",
            email="b@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            status="connected",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_list_emails_without_google_connection_returns_controlled_error(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    with pytest.raises(HTTPException) as exc_info:
        await list_recent_messages(db_session, user, org.id)

    assert exc_info.value.status_code == 409
    assert "Connexion Google" in exc_info.value.detail
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_google_connect_start_creates_audit_log(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    async def _fake_auth_url(**kwargs):
        return "https://accounts.google.com/o/oauth2/v2/auth?mock=1"

    monkeypatch.setattr(
        "app.modules.secretariat.routers.oauth.build_google_authorization_url",
        _fake_auth_url,
    )

    from types import SimpleNamespace
    fake_request = SimpleNamespace(headers={})
    res = await google_connect(fake_request, db_session, user, org.id)
    logs = await list_audit_logs(db_session, org.id)

    assert res.authorization_url.startswith("https://accounts.google.com")
    assert any(log.action == "google_oauth_connect_started" for log in logs)
    set_current_tenant_id(None)


def test_google_scopes_are_limited_to_allowed_values(monkeypatch):
    monkeypatch.setattr(
        "app.modules.secretariat.services.oauth_service.settings.google_oauth_scopes",
        "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/drive",
    )

    assert _google_scopes() == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]


@pytest.mark.asyncio
async def test_expired_google_connection_without_refresh_token_is_marked_expired(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    connection = OAuthConnection(
        organisation_id=org.id,
        user_id=user.id,
        provider="google",
        email="reader@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        status="connected",
        access_token_encrypted=encrypt_token("access-token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db_session.add(connection)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await refresh_access_token_if_needed(db_session, connection)

    assert exc_info.value.status_code == 401
    assert connection.status == "expired"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_google_disconnect_clears_tokens_and_status(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    connection = OAuthConnection(
        organisation_id=org.id,
        user_id=user.id,
        provider="google",
        email="reader@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        status="connected",
        access_token_encrypted=encrypt_token("access-token"),
        refresh_token_encrypted=encrypt_token("refresh-token"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(connection)
    await db_session.commit()

    disconnected = await disconnect_google_connection(db_session, connection)

    assert disconnected.status == "disconnected"
    assert disconnected.access_token_encrypted is None
    assert disconnected.refresh_token_encrypted is None
    assert disconnected.expires_at is None
    set_current_tenant_id(None)


def test_oauth_status_response_does_not_expose_tokens():
    assert "access_token" not in OAuthStatusOut.model_fields
    assert "refresh_token" not in OAuthStatusOut.model_fields


@pytest.mark.asyncio
async def test_secretariat_audit_metadata_is_sanitized(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    await record_secretariat_audit(
        db_session,
        organisation_id=org.id,
        user_id=user.id,
        action="audit_sanitization_probe",
        agent_type="manager",
        target_type="secretariat_task",
        target_id="42",
        metadata_json={
            "status": "ok",
            "content": "ne doit pas être stocké",
            "summary_text": "Résumé complet à supprimer",
            "nested": {"refresh_token": "secret-refresh", "count": 3},
            "timestamps": [datetime.now(timezone.utc)],
        },
    )
    await db_session.commit()
    logs = await list_audit_logs(db_session, org.id)

    assert len(logs) == 1
    metadata = logs[0].metadata_json or {}
    assert metadata["status"] == "ok"
    assert metadata["nested"] == {"count": 3}
    assert "content" not in metadata
    assert "summary_text" not in metadata
    assert "refresh_token" not in str(metadata).lower()
    set_current_tenant_id(None)


def _mock_mail(message_id: str = "gmail-1") -> dict:
    return {
        "id": message_id,
        "thread_id": "thread-1",
        "headers": {"from": "a@example.com", "to": "b@example.com", "subject": "Demande"},
        "subject": "Demande",
        "from": "a@example.com",
        "to": "b@example.com",
        "cc": None,
        "date": "Wed, 03 Jun 2026 10:00:00 +0000",
        "snippet": "Merci de traiter cette demande.",
        "body": "Bonjour, merci de traiter cette demande administrative. Cordialement.",
        "labels": ["INBOX"],
        "attachments": [],
    }


@pytest.mark.asyncio
async def test_summarize_mail_with_mocks_creates_audit_log(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    async def fake_mail(db, user, tenant_id, message_id):
        return _mock_mail(message_id)

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.gmail_get_message_detail", fake_mail)

    async def fake_summary(detail, **kwargs):
        return {
            "summary": "Demande administrative à traiter.",
            "key_points": ["Demande reçue"],
            "detected_request": "Traiter la demande",
            "suggested_priority": "normal",
            "requires_response": True,
        }

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.ai_summarize_email", fake_summary)

    result = await summarize_courrier_email("gmail-1", db_session, user, org.id)
    logs = await list_audit_logs(db_session, org.id)

    assert result["summary"] == "Demande administrative à traiter."
    assert any(log.action == "courrier_email_summarized" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_classify_mail_with_mocks(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    async def fake_mail(db, user, tenant_id, message_id):
        return _mock_mail(message_id)

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.gmail_get_message_detail", fake_mail)

    async def fake_classification(detail, **kwargs):
        return {
            "category": "administratif",
            "priority": "normal",
            "confidence": 0.9,
            "reason": "Le mail contient une demande administrative.",
            "recommended_action": "répondre",
        }

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.ai_classify_email", fake_classification)

    result = await classify_courrier_email("gmail-1", db_session, user, org.id)

    assert result["category"] == "administratif"
    assert result["priority"] == "normal"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_generate_draft_response_with_mocks(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    async def fake_mail(db, user, tenant_id, message_id):
        return _mock_mail(message_id)

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.gmail_get_message_detail", fake_mail)

    async def fake_draft(detail, *, tone, instructions=None, **kwargs):
        return {
            "subject": "Re: Demande",
            "draft_body": "Bonjour,\n\nNous accusons réception de votre demande.\n\nCordialement.",
            "requires_human_validation": True,
        }

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.ai_generate_email_response", fake_draft)

    result = await draft_courrier_response(
        "gmail-1",
        MailDraftRequest(tone="institutionnel", instructions="Réponse courte"),
        db_session,
        user,
        org.id,
    )
    drafts = (await db_session.execute(select(SecretariatMailDraft))).scalars().all()

    assert result.subject == "Re: Demande"
    assert result.requires_human_validation is True
    assert len(drafts) == 1
    assert drafts[0].status == "draft"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_ai_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.generate_mail_draft")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_ai_service_returns_controlled_error_without_openai_key(db_session, monkeypatch):
    # Sans fournisseur IA configuré, l'appel doit renvoyer une erreur 503 contrôlée.
    from app.core.ai.base import AIUnavailableError
    from app.core.ai.service import NO_PROVIDER_MESSAGE

    async def _no_provider(*args, **kwargs):
        raise AIUnavailableError(NO_PROVIDER_MESSAGE)

    monkeypatch.setattr(
        "app.modules.secretariat.services.ai_service.get_ai_service_for_org", _no_provider
    )

    with pytest.raises(HTTPException) as exc_info:
        await summarize_email(_mock_mail(), db=db_session, organisation_id=1)

    assert exc_info.value.status_code == 503
    assert "fournisseur IA" in exc_info.value.detail


async def _seed_internal_draft(db_session, org, user, *, status: str = "approved") -> SecretariatMailDraft:
    draft = SecretariatMailDraft(
        organisation_id=org.id,
        user_id=user.id,
        gmail_message_id="gmail-1",
        gmail_thread_id="thread-1",
        source_gmail_message_id="gmail-1",
        recipient_email="sender@example.com",
        subject="Re: Demande",
        body="Bonjour, nous accusons réception.",
        status=status,
    )
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)
    return draft


@pytest.mark.asyncio
async def test_create_gmail_draft_refused_if_internal_draft_not_approved(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    draft = await _seed_internal_draft(db_session, org, user, status="draft")

    with pytest.raises(HTTPException) as exc_info:
        await create_gmail_draft_from_internal_draft(draft.id, db_session, user, org.id)

    assert exc_info.value.status_code == 409
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_create_gmail_draft_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.create_gmail_draft")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_generate_mail_draft_permission_cannot_create_gmail_draft(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.generate_mail_draft"])
    dependency = has_permission("secretariat.create_gmail_draft")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


def test_create_gmail_draft_route_does_not_accept_generate_permission():
    import app.modules.secretariat.routes as routes

    route = next(
        route
        for route in routes.router.routes
        if getattr(route, "path", "") == "/courrier/drafts/{draft_id}/create-gmail-draft"
    )
    closure_values = []
    for dependency in route.dependencies:
        for cell in getattr(dependency.dependency, "__closure__", None) or []:
            closure_values.append(cell.cell_contents)

    assert "secretariat.create_gmail_draft" in closure_values
    assert "secretariat.generate_mail_draft" not in {str(value) for value in closure_values}


@pytest.mark.asyncio
async def test_create_gmail_draft_refused_without_compose_scope(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    db_session.add(
        OAuthConnection(
            organisation_id=org.id,
            user_id=user.id,
            provider="google",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            access_token_encrypted="token",
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await create_gmail_draft(db_session, user, org.id, to="a@example.com", subject="Objet", body="Texte")

    assert exc_info.value.status_code == 403
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_create_gmail_draft_success_with_mock_creates_audit_log(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    draft = await _seed_internal_draft(db_session, org, user, status="approved")

    async def fake_create(db, user, tenant_id, *, to, subject, body, thread_id=None, in_reply_to_message_id=None):
        assert to == "sender@example.com"
        assert subject == "Re: Demande"
        return {
            "gmail_draft_id": "draft-123",
            "gmail_message_id": "msg-123",
            "thread_id": thread_id,
            "status": "gmail_draft_created",
        }

    async def fake_approved_request(*args, **kwargs):
        return SimpleNamespace(id=1)

    monkeypatch.setattr("app.modules.secretariat.routers.courrier.approval_find_approved_request", fake_approved_request)
    monkeypatch.setattr("app.modules.secretariat.routers.courrier.gmail_create_draft", fake_create)

    result = await create_gmail_draft_from_internal_draft(draft.id, db_session, user, org.id)
    logs = await list_audit_logs(db_session, org.id)

    assert result.gmail_draft_id == "draft-123"
    assert result.status == "gmail_draft_created"
    assert any(log.action == "courrier_gmail_draft_created" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_direct_draft_approval_endpoint_is_disabled(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    draft = await _seed_internal_draft(db_session, org, user, status="draft")

    with pytest.raises(HTTPException) as approve_exc:
        await approve_courrier_draft(draft.id, db_session, user, org.id)
    await db_session.refresh(draft)
    assert approve_exc.value.status_code == 410
    assert draft.status == "draft"

    with pytest.raises(HTTPException) as reject_exc:
        await reject_courrier_draft(draft.id, db_session, user, org.id)
    await db_session.refresh(draft)
    assert reject_exc.value.status_code == 410
    assert draft.status == "draft"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_gmail_drafts_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    await _seed_internal_draft(db_session, org_a, user_a, status="approved")

    set_current_tenant_id(org_b.id)
    await _seed_internal_draft(db_session, org_b, user_b, status="approved")
    rows_b = (await db_session.execute(select(SecretariatMailDraft))).scalars().all()
    assert len(rows_b) == 1
    assert rows_b[0].organisation_id == org_b.id

    set_current_tenant_id(org_a.id)
    rows_a = (await db_session.execute(select(SecretariatMailDraft))).scalars().all()
    assert len(rows_a) == 1
    assert rows_a[0].organisation_id == org_a.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_overview_respects_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    agent_a = SecretariatAgent(organisation_id=org_a.id, name="Manager A", type="manager", status="active")
    db_session.add(agent_a)
    await db_session.flush()
    db_session.add(
        SecretariatTask(
            organisation_id=org_a.id,
            agent_id=agent_a.id,
            user_id=user_a.id,
            title="Tâche A",
            status="pending",
            priority="urgent",
        )
    )
    await _seed_internal_draft(db_session, org_a, user_a, status="draft")

    set_current_tenant_id(org_b.id)
    agent_b = SecretariatAgent(organisation_id=org_b.id, name="Manager B", type="manager", status="active")
    db_session.add(agent_b)
    await db_session.flush()
    db_session.add(
        SecretariatTask(
            organisation_id=org_b.id,
            agent_id=agent_b.id,
            user_id=user_b.id,
            title="Tâche B",
            status="completed",
            priority="normal",
        )
    )
    await _seed_internal_draft(db_session, org_b, user_b, status="gmail_draft_created")

    overview_b = await manager_overview(db_session, user_b, org_b.id)

    assert overview_b["tasks"]["pending"] == 0
    assert overview_b["tasks"]["completed"] == 1
    assert overview_b["mail_drafts"]["internal_drafts"] == 0
    assert overview_b["mail_drafts"]["gmail_draft_created"] == 1
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_overview_response_model_includes_documents_defaults(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    overview = await manager_overview(db_session, user, org.id)
    model = ManagerOverviewOut.model_validate(overview)

    assert model.documents.pending_approval == overview["documents"]["pending_approval"]
    assert model.documents.syntheses_to_validate == overview["documents"]["syntheses_to_validate"]
    assert model.documents.recent_created == []
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_pending_approvals_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    await _seed_internal_draft(db_session, org_a, user_a, status="draft")
    await create_approval(
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id="1",
            title="Validation A",
        ),
        db_session,
        user_a,
        org_a.id,
    )

    set_current_tenant_id(org_b.id)
    draft_b = await _seed_internal_draft(db_session, org_b, user_b, status="approved")
    approval_b = await create_approval(
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="gmail_draft_creation",
            target_type="secretariat_mail_draft",
            target_id=str(draft_b.id),
            title="Validation B",
        ),
        db_session,
        user_b,
        org_b.id,
    )
    rows = await manager_pending_approvals(db_session, user_b, org_b.id)

    assert len(rows) == 1
    assert rows[0]["id"] == approval_b.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_recommended_actions_without_gmail_connected(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    draft = await _seed_internal_draft(db_session, org, user, status="approved")

    rows = await manager_recommended_actions(db_session, user, org.id)

    assert any(row["type"] == "create_gmail_draft" and row["target_id"] == str(draft.id) for row in rows)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_create_followup_task_and_audit_log(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    task = await manager_followup_task(
        ManagerFollowupTaskCreate(
            title="Relancer validation",
            description="Contrôler le brouillon avant création Gmail.",
            priority="high",
            target_type="mail_draft",
            target_id="42",
        ),
        db_session,
        user,
        org.id,
    )
    logs = await list_audit_logs(db_session, org.id)

    assert task.id is not None
    assert task.organisation_id == org.id
    assert task.priority == "high"
    assert task.metadata_json["source"] == "agent_manager"
    assert any(log.action == "manager_followup_task_created" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_manager_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.manage_tasks")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_approval_request_creates_audit_log(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    approval = await create_approval(
        SecretariatApprovalCreate(
            agent_type="manager",
            approval_type="manager_recommendation",
            target_type="secretariat_task",
            target_id="42",
            title="Valider la recommandation",
            priority="high",
            metadata_json={"content": "ne doit pas être stocké", "target": "42"},
        ),
        db_session,
        user,
        org.id,
    )
    logs = await list_audit_logs(db_session, org.id)

    assert approval.id is not None
    assert approval.status == "pending"
    assert approval.metadata_json == {"target": "42"}
    assert any(log.action == "approval_requested" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_approvals_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    await create_approval(
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id="1",
            title="Approbation A",
        ),
        db_session,
        user_a,
        org_a.id,
    )

    set_current_tenant_id(org_b.id)
    approval_b = await create_approval(
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id="2",
            title="Approbation B",
        ),
        db_session,
        user_b,
        org_b.id,
    )
    rows_b = await list_approvals(db_session, user_b, org_b.id)

    assert len(rows_b) == 1
    assert rows_b[0].id == approval_b.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_secretariat_approvals_are_globally_tenant_scoped(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    approval_a = SecretariatApproval(
        organisation_id=org_a.id,
        requested_by_user_id=user_a.id,
        agent_type="manager",
        approval_type="manager_recommendation",
        target_type="secretariat_task",
        target_id="1",
        title="Tenant A",
        status="pending",
        priority="normal",
    )
    db_session.add(approval_a)
    await db_session.commit()

    set_current_tenant_id(org_b.id)
    approval_b = SecretariatApproval(
        organisation_id=org_b.id,
        requested_by_user_id=user_b.id,
        agent_type="manager",
        approval_type="manager_recommendation",
        target_type="secretariat_task",
        target_id="2",
        title="Tenant B",
        status="pending",
        priority="normal",
    )
    db_session.add(approval_b)
    await db_session.commit()

    rows_b = (await db_session.execute(select(SecretariatApproval))).scalars().all()
    assert [row.title for row in rows_b] == ["Tenant B"]

    set_current_tenant_id(org_a.id)
    rows_a = (await db_session.execute(select(SecretariatApproval))).scalars().all()
    assert [row.title for row in rows_a] == ["Tenant A"]
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_approval_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, with_secretariat_permission=False)
    dependency = has_permission("secretariat.approve_action")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_reject_approval_with_comment_updates_mail_draft(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    draft = await _seed_internal_draft(db_session, org, user, status="draft")
    approval = await create_approval(
        SecretariatApprovalCreate(
            agent_type="courrier",
            approval_type="mail_draft_approval",
            target_type="secretariat_mail_draft",
            target_id=str(draft.id),
            title="Valider le brouillon",
        ),
        db_session,
        user,
        org.id,
    )

    rejected = await reject_approval(
        approval.id,
        SecretariatApprovalDecision(comment="À reformuler"),
        db_session,
        user,
        org.id,
    )
    await db_session.refresh(draft)

    assert rejected.status == "rejected"
    assert rejected.decision_comment == "À reformuler"
    assert draft.status == "rejected"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_double_approval_is_impossible(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    org_id = org.id
    set_current_tenant_id(org_id)
    approval = await create_approval(
        SecretariatApprovalCreate(
            agent_type="manager",
            approval_type="manager_recommendation",
            target_type="secretariat_task",
            target_id="1",
            title="Valider",
        ),
        db_session,
        user,
        org_id,
    )
    approval_id = approval.id
    db_session.expire_all()
    await approve_approval(
        approval_id,
        payload=SecretariatApprovalDecision(comment="OK"),
        db=db_session,
        user=user,
        tenant_id=org_id,
    )
    second_approval_id = approval_id

    with pytest.raises(HTTPException) as exc_info:
        await approve_approval(
            second_approval_id,
            payload=SecretariatApprovalDecision(comment="Encore"),
            db=db_session,
            user=user,
            tenant_id=org_id,
        )

    assert exc_info.value.status_code == 409
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_approval_from_other_tenant_is_not_visible(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    org_a_id = org_a.id
    org_b_id = org_b.id

    set_current_tenant_id(org_a_id)
    approval_a = await create_approval(
        SecretariatApprovalCreate(
            agent_type="manager",
            approval_type="manager_recommendation",
            target_type="secretariat_task",
            target_id="1",
            title="Tenant A",
        ),
        db_session,
        user_a,
        org_a_id,
    )
    approval_a_id = approval_a.id

    set_current_tenant_id(org_b_id)
    db_session.expire_all()
    with pytest.raises(HTTPException) as exc_info:
        await approve_approval(
            approval_a_id,
            payload=SecretariatApprovalDecision(comment="Non"),
            db=db_session,
            user=user_b,
            tenant_id=org_b_id,
        )

    assert exc_info.value.status_code == 404
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_create_and_audit_log(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    meeting = await create_reunion(
        SecretariatMeetingCreate(title="Réunion administrative", meeting_type="administrative"),
        db_session,
        user,
        org.id,
    )
    logs = await list_audit_logs(db_session, org.id)

    assert meeting.id is not None
    assert meeting.organisation_id == org.id
    assert meeting.status == "draft"
    assert any(log.action == "reunion_created" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunions_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    await create_reunion(SecretariatMeetingCreate(title="Réunion A"), db_session, user_a, org_a.id)
    set_current_tenant_id(org_b.id)
    meeting_b = await create_reunion(SecretariatMeetingCreate(title="Réunion B"), db_session, user_b, org_b.id)

    rows_b = await list_reunions(db_session, org_b.id)
    assert len(rows_b) == 1
    assert rows_b[0].id == meeting_b.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_agenda_generation_with_mock_ai(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="Réunion budget"), db_session, user, org.id)
    meeting_id = meeting.id

    async def fake_json(system_prompt, user_input, schema_name, schema, **kwargs):
        return {"text": "1. Ouverture\n2. Point budgétaire\n3. Suites à donner"}

    monkeypatch.setattr("app.modules.secretariat.services.reunion_agent._responses_json", fake_json)
    result = await generate_reunion_agenda(meeting_id, MeetingTextGenerationRequest(), db_session, user, org.id)

    assert "Point budgétaire" in result.text
    db_session.expire_all()
    refreshed = await db_session.get(SecretariatMeeting, meeting_id)
    assert refreshed is not None
    assert refreshed.agenda_text == result.text
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_minutes_generation_with_mock_ai(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="Réunion PV"), db_session, user, org.id)
    meeting_id = meeting.id

    async def fake_json(system_prompt, user_input, schema_name, schema, **kwargs):
        return {"text": "Projet de PV simple avec faits, décisions et tâches."}

    monkeypatch.setattr("app.modules.secretariat.services.reunion_agent._responses_json", fake_json)
    result = await generate_reunion_minutes(meeting_id, MeetingTextGenerationRequest(), db_session, user, org.id)

    assert "Projet de PV" in result.text
    db_session.expire_all()
    refreshed = await db_session.get(SecretariatMeeting, meeting_id)
    assert refreshed is not None
    assert refreshed.status == "minutes_draft"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_submit_reunion_minutes_creates_approval(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(
        SecretariatMeetingCreate(title="Réunion à valider"),
        db_session,
        user,
        org.id,
    )
    meeting_id = meeting.id
    meeting.minutes_draft = "Projet de PV"
    meeting.status = "minutes_draft"
    await db_session.flush()

    result = await submit_reunion_minutes_approval(meeting_id, db_session, user, org.id)
    approvals = await list_approvals(db_session, user, org.id)

    assert result.status == "pending"
    assert any(approval.approval_type == "meeting_minutes_validation" and approval.target_id == str(meeting_id) for approval in approvals)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_permission_is_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view"])
    dependency = has_permission("secretariat.manage_meetings")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_reunion_minutes_updates_meeting(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    org_id = org.id
    set_current_tenant_id(org_id)
    meeting = await create_reunion(
        SecretariatMeetingCreate(title="PV approbation"),
        db_session,
        user,
        org_id,
    )
    meeting_id = meeting.id
    meeting.minutes_draft = "PV validable"
    meeting.status = "minutes_draft"
    await db_session.flush()
    approval_result = await submit_reunion_minutes_approval(meeting_id, db_session, user, org.id)

    await approve_approval(
        approval_result.approval_id,
        payload=SecretariatApprovalDecision(comment="OK"),
        db=db_session,
        user=user,
        tenant_id=org_id,
    )
    db_session.expire_all()
    refreshed = await db_session.get(SecretariatMeeting, meeting_id)
    logs = await list_audit_logs(db_session, org_id)

    assert refreshed is not None
    assert refreshed.status == "approved"
    assert refreshed.approved_minutes == "PV validable"
    assert any(log.action == "reunion_minutes_approved" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reject_reunion_minutes_does_not_validate_meeting(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    org_id = org.id
    set_current_tenant_id(org_id)
    meeting = await create_reunion(
        SecretariatMeetingCreate(title="PV rejet"),
        db_session,
        user,
        org_id,
    )
    meeting_id = meeting.id
    meeting.minutes_draft = "PV à corriger"
    meeting.status = "minutes_draft"
    await db_session.flush()
    approval_result = await submit_reunion_minutes_approval(meeting_id, db_session, user, org.id)

    await reject_approval(
        approval_result.approval_id,
        payload=SecretariatApprovalDecision(comment="À corriger"),
        db=db_session,
        user=user,
        tenant_id=org_id,
    )
    db_session.expire_all()
    refreshed = await db_session.get(SecretariatMeeting, meeting_id)
    logs = await list_audit_logs(db_session, org_id)

    assert refreshed is not None
    assert refreshed.status == "minutes_rejected"
    assert refreshed.approved_minutes is None
    assert any(log.action == "reunion_minutes_rejected" for log in logs)
    set_current_tenant_id(None)


def test_reunion_public_schemas_reject_sensitive_fields():
    with pytest.raises(ValidationError):
        SecretariatMeetingCreate.model_validate({"title": "Réunion", "status": "approved"})

    with pytest.raises(ValidationError):
        SecretariatMeetingUpdate.model_validate({"status": "approved"})

    with pytest.raises(ValidationError):
        SecretariatMeetingUpdate.model_validate({"approved_minutes": "PV approuvé hors workflow"})

    with pytest.raises(ValidationError):
        SecretariatMeetingUpdate.model_validate({"minutes_draft": "PV saisi hors route métier"})


@pytest.mark.asyncio
async def test_patch_reunion_cannot_approve_or_modify_sensitive_fields(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="Réunion verrouillée"), db_session, user, org.id)

    with pytest.raises(ValidationError):
        SecretariatMeetingUpdate.model_validate({"status": "approved"})
    with pytest.raises(ValidationError):
        SecretariatMeetingUpdate.model_validate({"approved_minutes": "PV forcé"})

    updated = await update_reunion(
        meeting.id,
        SecretariatMeetingUpdate(title="Réunion verrouillée modifiée"),
        db_session,
        user,
        org.id,
    )

    assert updated.title == "Réunion verrouillée modifiée"
    assert updated.status == "draft"
    assert updated.approved_minutes is None
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reject_reunion_minutes_after_previous_approval_keeps_previous_minutes_clear(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="PV versionné"), db_session, user, org.id)
    meeting.minutes_draft = "PV version 1"
    meeting.status = "minutes_draft"
    await db_session.flush()

    first = await submit_reunion_minutes_approval(meeting.id, db_session, user, org.id)
    await approve_approval(
        first.approval_id,
        payload=SecretariatApprovalDecision(comment="OK v1"),
        db=db_session,
        user=user,
        tenant_id=org.id,
    )
    await db_session.refresh(meeting)
    assert meeting.status == "approved"
    assert meeting.approved_minutes == "PV version 1"

    meeting.minutes_draft = "PV version 2 rejetée"
    meeting.status = "minutes_draft"
    await db_session.flush()
    second = await submit_reunion_minutes_approval(meeting.id, db_session, user, org.id)
    await reject_approval(
        second.approval_id,
        payload=SecretariatApprovalDecision(comment="KO v2"),
        db=db_session,
        user=user,
        tenant_id=org.id,
    )
    await db_session.refresh(meeting)

    assert meeting.status == "minutes_rejected"
    assert meeting.minutes_draft == "PV version 2 rejetée"
    assert meeting.approved_minutes == "PV version 1"
    logs = await list_audit_logs(db_session, org.id)
    assert any(log.action == "reunion_minutes_rejected" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_minutes_double_approval_is_impossible(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="PV double décision"), db_session, user, org.id)
    meeting.minutes_draft = "PV à décider"
    meeting.status = "minutes_draft"
    await db_session.flush()
    approval_result = await submit_reunion_minutes_approval(meeting.id, db_session, user, org.id)

    await approve_approval(
        approval_result.approval_id,
        payload=SecretariatApprovalDecision(comment="OK"),
        db=db_session,
        user=user,
        tenant_id=org.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        await approve_approval(
            approval_result.approval_id,
            payload=SecretariatApprovalDecision(comment="Encore"),
            db=db_session,
            user=user,
            tenant_id=org.id,
        )

    assert exc_info.value.status_code == 409
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_route_permissions_are_required(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view"])

    for permission_code in [
        "secretariat.manage_meetings",
        "secretariat.generate_meeting_documents",
        "secretariat.submit_meeting_minutes",
    ]:
        dependency = has_permission(permission_code)
        with pytest.raises(HTTPException) as exc_info:
            await dependency(user, db_session)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_reunion_children_are_tenant_scoped(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    meeting_a = await create_reunion(SecretariatMeetingCreate(title="Réunion A"), db_session, user_a, org_a.id)
    participant = await add_reunion_participant(
        meeting_a.id,
        SecretariatMeetingParticipantCreate(name="Participant A"),
        db_session,
        user_a,
        org_a.id,
    )
    db_session.add_all(
        [
            SecretariatMeetingDecision(organisation_id=org_a.id, meeting_id=meeting_a.id, decision_text="Décision A"),
            SecretariatMeetingActionItem(organisation_id=org_a.id, meeting_id=meeting_a.id, title="Action A"),
        ]
    )
    await db_session.flush()

    set_current_tenant_id(org_b.id)
    with pytest.raises(HTTPException) as meeting_exc:
        await update_reunion(meeting_a.id, SecretariatMeetingUpdate(title="Tentative B"), db_session, user_b, org_b.id)
    with pytest.raises(HTTPException) as participant_exc:
        await add_reunion_participant(
            meeting_a.id,
            SecretariatMeetingParticipantCreate(name="Participant B"),
            db_session,
            user_b,
            org_b.id,
        )
    hidden_participants = (await db_session.execute(select(SecretariatMeetingParticipant))).scalars().all()
    hidden_decisions = (await db_session.execute(select(SecretariatMeetingDecision))).scalars().all()
    hidden_actions = (await db_session.execute(select(SecretariatMeetingActionItem))).scalars().all()

    assert participant.id is not None
    assert meeting_exc.value.status_code == 404
    assert participant_exc.value.status_code == 404
    assert hidden_participants == []
    assert hidden_decisions == []
    assert hidden_actions == []
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_minutes_approval_from_other_tenant_is_invisible_and_not_actionable(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="PV tenant A"), db_session, user_a, org_a.id)
    meeting.minutes_draft = "PV tenant A"
    meeting.status = "minutes_draft"
    await db_session.flush()
    approval_result = await submit_reunion_minutes_approval(meeting.id, db_session, user_a, org_a.id)

    set_current_tenant_id(org_b.id)
    rows_b = await list_approvals(db_session, user_b, org_b.id)
    with pytest.raises(HTTPException) as exc_info:
        await approve_approval(
            approval_result.approval_id,
            payload=SecretariatApprovalDecision(comment="Non"),
            db=db_session,
            user=user_b,
            tenant_id=org_b.id,
        )

    assert rows_b == []
    assert exc_info.value.status_code == 404
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_audit_logs_do_not_store_full_generated_content(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="Réunion audit"), db_session, user, org.id)
    notes = "NOTES_COMPLETES_CONFIDENTIELLES"
    agenda = "ORDRE_DU_JOUR_COMPLET_CONFIDENTIEL"
    invitation = "INVITATION_COMPLETE_CONFIDENTIELLE"
    minutes = "PV_COMPLET_CONFIDENTIEL"

    async def fake_json(system_prompt, user_input, schema_name, schema, **kwargs):
        if schema_name == "reunion_agenda":
            return {"text": agenda}
        if schema_name == "reunion_invitation":
            return {"text": invitation}
        return {"text": minutes}

    monkeypatch.setattr("app.modules.secretariat.services.reunion_agent._responses_json", fake_json)
    await generate_reunion_agenda(meeting.id, MeetingTextGenerationRequest(), db_session, user, org.id)
    await generate_reunion_invitation(meeting.id, MeetingTextGenerationRequest(), db_session, user, org.id)
    await save_reunion_notes(meeting.id, MeetingNotesRequest(notes=notes), db_session, user, org.id)
    await generate_reunion_minutes(meeting.id, MeetingTextGenerationRequest(), db_session, user, org.id)

    logs = await list_audit_logs(db_session, org.id)
    metadata_text = " ".join(str(log.metadata_json or {}) for log in logs)
    assert notes not in metadata_text
    assert agenda not in metadata_text
    assert invitation not in metadata_text
    assert minutes not in metadata_text
    assert any(log.action == "reunion_notes_saved" and (log.metadata_json or {}).get("notes_length") == len(notes) for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_item_create_and_audit_log(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    item = await create_agenda_item(
        AgendaItemCreate(title="Dépôt rapport", item_type="deadline", priority="high"),
        db_session,
        user,
        org.id,
    )
    logs = await list_audit_logs(db_session, org.id)

    assert item.id is not None
    assert item.organisation_id == org.id
    assert item.status == "pending"
    assert any(log.action == "agenda_item_created" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_items_are_scoped_by_organisation_id(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)

    set_current_tenant_id(org_a.id)
    await create_agenda_item(AgendaItemCreate(title="Échéance A"), db_session, user_a, org_a.id)
    set_current_tenant_id(org_b.id)
    item_b = await create_agenda_item(AgendaItemCreate(title="Échéance B"), db_session, user_b, org_b.id)

    rows_b = await list_agenda_items(
        status_value=None,
        priority=None,
        item_type=None,
        assigned_to_user_id=None,
        date_from=None,
        date_to=None,
        db=db_session,
        tenant_id=org_b.id,
    )
    assert len(rows_b) == 1
    assert rows_b[0].id == item_b.id
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_update_requires_manage_agenda_permission(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view_agenda"])
    dependency = has_permission("secretariat.manage_agenda")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user, db_session)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_agenda_complete_and_cancel_work(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    item = await create_agenda_item(AgendaItemCreate(title="Action à terminer"), db_session, user, org.id)

    completed = await complete_agenda_item(item.id, db_session, user, org.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None

    with pytest.raises(HTTPException) as exc_info:
        await cancel_agenda_item(item.id, db_session, user, org.id)
    assert exc_info.value.status_code == 409

    cancellable = await create_agenda_item(AgendaItemCreate(title="Action annulable"), db_session, user, org.id)
    cancelled = await cancel_agenda_item(cancellable.id, db_session, user, org.id)
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is None
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_patch_refuses_status_transition_and_logs_block(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    item = await create_agenda_item(AgendaItemCreate(title="Transition bloquée"), db_session, user, org.id)

    with pytest.raises(HTTPException) as exc_info:
        await update_agenda_item(item.id, AgendaItemUpdate(status="completed"), db_session, user, org.id)
    await db_session.flush()
    logs = await list_audit_logs(db_session, org.id)
    updated_item = await create_agenda_item(AgendaItemCreate(title="Contrôle statut"), db_session, user, org.id)

    assert exc_info.value.status_code == 400
    assert any(log.action == "agenda_transition_blocked" for log in logs)
    assert updated_item.status == "pending"
    assert item.status == "pending"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_create_blocks_forbidden_statuses(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)

    with pytest.raises(HTTPException) as exc_info:
        await create_agenda_item(AgendaItemCreate(title="Création invalide", status="completed"), db_session, user, org.id)

    assert exc_info.value.status_code == 400
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_overview_is_pure_and_counts_overdue_dynamically(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    now = datetime.now(timezone.utc)
    pending = await create_agenda_item(AgendaItemCreate(title="Retard dynamique", due_at=now - timedelta(days=1)), db_session, user, org.id)
    completed = await create_agenda_item(AgendaItemCreate(title="PV terminé", due_at=now - timedelta(days=2)), db_session, user, org.id)
    await complete_agenda_item(completed.id, db_session, user, org.id)

    overview = await agenda_overview(db_session, user, org.id)
    rows = await list_agenda_items(
        status_value=None,
        priority=None,
        item_type=None,
        assigned_to_user_id=None,
        date_from=None,
        date_to=None,
        db=db_session,
        tenant_id=org.id,
    )

    assert overview["overdue"] >= 1
    assert overview["completed"] >= 1
    assert any(item.id == pending.id and item.status == "pending" for item in rows)
    assert any(item.id == completed.id and item.status == "completed" for item in rows)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_reunion_agenda_item_reuses_existing_and_rejects_other_tenant(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)
    meeting = await create_reunion(SecretariatMeetingCreate(title="Réunion unique", meeting_date=datetime.now(timezone.utc).date()), db_session, user_a, org_a.id)

    response_first = Response()
    item_first = await create_reunion_agenda_item(meeting.id, response_first, db_session, user_a, org_a.id)
    response_second = Response()
    item_second = await create_reunion_agenda_item(meeting.id, response_second, db_session, user_a, org_a.id)
    rows = await db_session.execute(
        select(SecretariatAgendaItem).where(
            SecretariatAgendaItem.organisation_id == org_a.id,
            SecretariatAgendaItem.target_type == "secretariat_meeting",
            SecretariatAgendaItem.target_id == str(meeting.id),
            SecretariatAgendaItem.item_type == "meeting",
        )
    )
    items = list(rows.scalars().all())

    assert item_first.id == item_second.id
    assert response_second.status_code == 200
    assert response_second.headers.get("X-Agenda-Message") == "Une échéance Agenda existe déjà pour cette réunion."
    assert len(items) == 1

    set_current_tenant_id(org_b.id)
    with pytest.raises(HTTPException) as exc_info:
        await create_reunion_agenda_item(meeting.id, Response(), db_session, user_b, org_b.id)
    assert exc_info.value.status_code == 404
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_assigned_user_must_belong_to_tenant(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)

    item = await create_agenda_item(
        AgendaItemCreate(title="Assignation valide", assigned_to_user_id=user_a.id),
        db_session,
        user_a,
        org_a.id,
    )
    assert item.assigned_to_user_id == user_a.id

    with pytest.raises(HTTPException) as exc_info:
        await create_agenda_item(
            AgendaItemCreate(title="Assignation invalide", assigned_to_user_id=user_b.id),
            db_session,
            user_a,
            org_a.id,
        )

    assert exc_info.value.status_code == 400
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_reminder_is_tenant_scoped_and_dismiss_refuses_other_tenant(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)
    item = await create_agenda_item(AgendaItemCreate(title="Rappel tenant A"), db_session, user_a, org_a.id)
    reminder = await create_agenda_reminder(
        item.id,
        AgendaReminderCreate(reminder_at=datetime.now(timezone.utc) + timedelta(hours=1), message="Rappel interne"),
        db_session,
        user_a,
        org_a.id,
    )

    set_current_tenant_id(org_b.id)
    reminders_b = await list_agenda_reminders(None, db_session, org_b.id)
    with pytest.raises(HTTPException) as exc_info:
        await dismiss_agenda_reminder(reminder.id, db_session, user_b, org_b.id)

    assert reminders_b == []
    assert exc_info.value.status_code == 404
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agenda_overview_counts_pending_overdue_urgent(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    now = datetime.now(timezone.utc)
    await create_agenda_item(AgendaItemCreate(title="Aujourd'hui", due_at=now + timedelta(hours=1)), db_session, user, org.id)
    await create_agenda_item(AgendaItemCreate(title="Urgent", priority="urgent", due_at=now + timedelta(days=2)), db_session, user, org.id)
    await create_agenda_item(AgendaItemCreate(title="Retard", due_at=now - timedelta(days=1)), db_session, user, org.id)

    overview = await agenda_overview(db_session, user, org.id)

    assert overview["today"] >= 1
    assert overview["overdue"] >= 1
    assert overview["urgent"] >= 1
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agent_manager_includes_agenda_counters(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    await create_agenda_item(AgendaItemCreate(title="Échéance manager", priority="urgent", due_at=datetime.now(timezone.utc) - timedelta(hours=1)), db_session, user, org.id)

    overview = await manager_overview(db_session, user, org.id)

    assert overview["agenda"]["overdue"] >= 1
    assert overview["agenda"]["urgent"] >= 1
    assert any(action["type"].startswith("agenda_") for action in overview["recommended_actions"])
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_document_create_and_list_are_tenant_scoped(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)
    doc_a = await create_document(
        SecretariatDocumentCreate(title="Doc A", document_type="rapport", file_name="doc-a.pdf", extracted_text="Texte A", keywords_json=["alpha"]),
        db_session,
        user_a,
        org_a.id,
    )
    set_current_tenant_id(org_b.id)
    doc_b = await create_document(
        SecretariatDocumentCreate(title="Doc B", document_type="note", extracted_text="Texte B", keywords_json=["beta"]),
        db_session,
        user_b,
        org_b.id,
    )

    set_current_tenant_id(org_a.id)
    rows_a = await list_documents(
        document_type=None,
        category=None,
        status_value=None,
        date_from=None,
        date_to=None,
        author_id=None,
        keyword=None,
        db=db_session,
        tenant_id=org_a.id,
    )
    set_current_tenant_id(org_b.id)
    rows_b = await list_documents(
        document_type=None,
        category=None,
        status_value=None,
        date_from=None,
        date_to=None,
        author_id=None,
        keyword=None,
        db=db_session,
        tenant_id=org_b.id,
    )

    assert {row.id for row in rows_a} == {doc_a.id}
    assert {row.id for row in rows_b} == {doc_b.id}
    assert SecretariatDocumentRead.model_validate(doc_a).has_file is True
    set_current_tenant_id(None)


def test_document_schemas_reject_status_and_file_path():
    with pytest.raises(ValidationError):
        SecretariatDocumentCreate(title="Doc", document_type="rapport", extracted_text="Texte", status="draft")
    with pytest.raises(ValidationError):
        SecretariatDocumentCreate(title="Doc", document_type="rapport", extracted_text="Texte", file_path="/tmp/doc.pdf")
    with pytest.raises(ValidationError):
        SecretariatDocumentUpdate(status="approved")
    with pytest.raises(ValidationError):
        SecretariatDocumentUpdate(file_path="/tmp/doc.pdf")
    with pytest.raises(ValidationError):
        SecretariatDocumentVersionCreate(file_path="/tmp/v1.pdf")
    assert "file_path" not in SecretariatDocumentRead.model_fields
    assert "file_path" not in SecretariatDocumentVersionRead.model_fields


@pytest.mark.asyncio
async def test_document_update_keeps_status_controlled(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Doc verrouillé", document_type="rapport", extracted_text="Texte"),
        db_session,
        user,
        org.id,
    )

    updated = await update_document(
        doc.id,
        SecretariatDocumentUpdate(title="Doc verrouillé modifié", description="Nouvelle description"),
        db_session,
        user,
        org.id,
    )

    assert updated.status == "draft"
    assert updated.title == "Doc verrouillé modifié"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_document_permission_dependencies(db_session):
    await _cleanup(db_session)
    _, user = await _seed_user(db_session, permission_codes=["secretariat.view_documents"])

    for permission_code in [
        "secretariat.manage_documents",
        "secretariat.generate_document_summary",
        "secretariat.submit_document_synthesis",
    ]:
        dependency = has_permission(permission_code)
        with pytest.raises(HTTPException) as exc_info:
            await dependency(user, db_session)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_document_versions_are_tenant_scoped(db_session):
    await _cleanup(db_session)
    org_a, user_a = await _seed_user(db_session)
    org_b, user_b = await _seed_user(db_session)
    set_current_tenant_id(org_a.id)
    doc_a = await create_document(
        SecretariatDocumentCreate(title="Doc version A", document_type="rapport", extracted_text="Texte A"),
        db_session,
        user_a,
        org_a.id,
    )
    version_a = await add_document_version(
        doc_a.id,
        SecretariatDocumentVersionCreate(file_name="v2.pdf", extracted_text="Texte A2"),
        db_session,
        user_a,
        org_a.id,
    )
    set_current_tenant_id(org_b.id)
    doc_b = await create_document(
        SecretariatDocumentCreate(title="Doc version B", document_type="note", extracted_text="Texte B"),
        db_session,
        user_b,
        org_b.id,
    )
    await add_document_version(
        doc_b.id,
        SecretariatDocumentVersionCreate(file_name="v2b.pdf", extracted_text="Texte B2"),
        db_session,
        user_b,
        org_b.id,
    )

    set_current_tenant_id(org_a.id)
    rows_a = await list_document_versions(doc_a.id, db_session, org_a.id)
    set_current_tenant_id(org_b.id)
    rows_b = await list_document_versions(doc_b.id, db_session, org_b.id)

    assert len(rows_a) == 2
    assert any(row.id == version_a.id for row in rows_a)
    assert len(rows_b) == 2
    assert "file_path" not in SecretariatDocumentVersionRead.model_fields
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_document_workflow_creates_approval_and_applies_status(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    org_id = org.id
    set_current_tenant_id(org_id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Synthèse PV", document_type="PV", extracted_text="Le conseil a validé le principe."),
        db_session,
        user,
        org_id,
    )
    doc_id = doc.id

    async def fake_ai_summarize_document(document, **kwargs):
        return {
            "summary_text": "Résumé factice.",
            "key_points": ["Point 1"],
            "requires_human_validation": True,
        }

    async def fake_ai_generate_document_synthesis(document, **kwargs):
        return {
            "object": "Objet factice",
            "context": "Contexte factice",
            "key_points": ["Point 1"],
            "decisions_or_requests": ["Décision 1"],
            "actions_to_follow": ["Action 1"],
            "risks_or_observations": ["Risque 1"],
            "proposed_next_steps": ["Suite 1"],
            "missing_information": [],
            "requires_human_validation": True,
        }

    monkeypatch.setattr("app.modules.secretariat.services.documents_agent.ai_summarize_document", fake_ai_summarize_document)
    monkeypatch.setattr("app.modules.secretariat.services.documents_agent.ai_generate_document_synthesis", fake_ai_generate_document_synthesis)
    summary = await summarize_document(doc_id, db_session, user, org_id)
    db_session.expire_all()
    synthesis = await generate_document_synthesis(doc_id, db_session, user, org_id)
    assert doc.status == "draft"
    approval = await submit_document_synthesis_approval(doc_id, db_session, user, org_id)
    approval_id = approval.id
    db_session.expire_all()
    approved = await approve_approval(approval_id, db=db_session, user=user, tenant_id=org_id)
    refreshed = await get_document(doc_id, db_session, org_id)
    logs = await list_audit_logs(db_session, org_id)

    assert summary.summary_text
    assert synthesis.synthesis_text
    assert approval.approval_type == "document_synthesis_validation"
    assert approval.target_type == "secretariat_document"
    assert approved.status == "approved"
    assert refreshed.status == "approved"
    assert any(log.action == "document_summarized" for log in logs)
    assert any(log.action == "document_synthesis_generated" for log in logs)
    assert any(log.action == "document_synthesis_submitted_for_approval" for log in logs)
    assert any(log.action == "document_synthesis_approved" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_document_rejection_does_not_validate_document(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    org_id = org.id
    set_current_tenant_id(org_id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Synthèse rejetée", document_type="note", extracted_text="Texte à valider"),
        db_session,
        user,
        org_id,
    )
    doc_id = doc.id
    async def fake_ai_generate_document_synthesis(document, **kwargs):
        return {
            "object": "Objet factice",
            "context": "Contexte factice",
            "key_points": ["Point 1"],
            "decisions_or_requests": ["Décision 1"],
            "actions_to_follow": ["Action 1"],
            "risks_or_observations": ["Risque 1"],
            "proposed_next_steps": ["Suite 1"],
            "missing_information": [],
            "requires_human_validation": True,
        }

    monkeypatch.setattr("app.modules.secretariat.services.documents_agent.ai_generate_document_synthesis", fake_ai_generate_document_synthesis)
    await generate_document_synthesis(doc_id, db_session, user, org_id)
    db_session.expire_all()
    approval = await submit_document_synthesis_approval(doc_id, db_session, user, org_id)
    approval_id = approval.id
    rejected = await reject_approval(approval_id, db=db_session, user=user, tenant_id=org_id)
    rejected_status = rejected.status
    db_session.expire_all()
    refreshed = await db_session.get(SecretariatDocument, doc_id)

    assert rejected_status == "rejected"
    assert refreshed.status == "rejected"
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_archived_document_blocks_ai_and_submission(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Doc archivé", document_type="rapport", extracted_text="Texte"),
        db_session,
        user,
        org.id,
    )
    await archive_document(doc.id, db_session, user, org.id)

    with pytest.raises(HTTPException):
        await summarize_document(doc.id, db_session, user, org.id)
    with pytest.raises(HTTPException):
        await generate_document_synthesis(doc.id, db_session, user, org.id)
    with pytest.raises(HTTPException):
        await submit_document_synthesis_approval(doc.id, db_session, user, org.id)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_pending_approval_document_blocks_generic_changes(db_session):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Doc en validation", document_type="rapport", extracted_text="Texte"),
        db_session,
        user,
        org.id,
    )
    async def fake_documents_synthesis(db, user, tenant_id, document_id):
        document = await get_document(document_id, db, tenant_id)
        document.synthesis_text = "Synthèse factice."
        return document

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.modules.secretariat.routers.documents.documents_generate_synthesis", fake_documents_synthesis)
    await generate_document_synthesis(doc.id, db_session, user, org.id)
    await submit_document_synthesis_approval(doc.id, db_session, user, org.id)
    assert doc.status == "pending_approval"

    with pytest.raises(HTTPException):
        await update_document(doc.id, SecretariatDocumentUpdate(title="Changement"), db_session, user, org.id)
    with pytest.raises(HTTPException):
        await add_document_version(
            doc.id,
            SecretariatDocumentVersionCreate(file_name="v2.pdf", extracted_text="Texte V2"),
            db_session,
            user,
            org.id,
        )
    monkeypatch.undo()
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_document_audit_logs_do_not_store_full_content(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    text = "Contenu sensible document"
    doc = await create_document(
        SecretariatDocumentCreate(title="Doc audit", document_type="courrier", extracted_text=text, description=text),
        db_session,
        user,
        org.id,
    )
    async def fake_ai_summarize_document(document, **kwargs):
        return {
            "summary_text": "Résumé factice.",
            "key_points": ["Point 1"],
            "requires_human_validation": True,
        }

    monkeypatch.setattr("app.modules.secretariat.services.documents_agent.ai_summarize_document", fake_ai_summarize_document)
    await summarize_document(doc.id, db_session, user, org.id)
    logs = await list_audit_logs(db_session, org.id)
    metadata_text = " ".join(str(log.metadata_json or {}) for log in logs)

    assert text not in metadata_text
    assert "file_path" not in metadata_text.lower()
    assert any(log.action == "document_created" for log in logs)
    assert any(log.action == "document_summarized" for log in logs)
    set_current_tenant_id(None)


@pytest.mark.asyncio
async def test_agent_manager_includes_document_counters(db_session, monkeypatch):
    await _cleanup(db_session)
    org, user = await _seed_user(db_session)
    set_current_tenant_id(org.id)
    doc = await create_document(
        SecretariatDocumentCreate(title="Doc manager", document_type="rapport", extracted_text="Texte"),
        db_session,
        user,
        org.id,
    )
    async def fake_ai_generate_document_synthesis(document, **kwargs):
        return {
            "object": "Objet factice",
            "context": "Contexte factice",
            "key_points": ["Point 1"],
            "decisions_or_requests": ["Décision 1"],
            "actions_to_follow": ["Action 1"],
            "risks_or_observations": ["Risque 1"],
            "proposed_next_steps": ["Suite 1"],
            "missing_information": [],
            "requires_human_validation": True,
        }

    monkeypatch.setattr("app.modules.secretariat.services.documents_agent.ai_generate_document_synthesis", fake_ai_generate_document_synthesis)
    await generate_document_synthesis(doc.id, db_session, user, org.id)
    await submit_document_synthesis_approval(doc.id, db_session, user, org.id)
    overview = await manager_overview(db_session, user, org.id)

    assert overview["documents"]["pending_approval"] >= 1
    assert overview["documents"]["syntheses_to_validate"] >= 1
    assert "file_path" not in str(overview).lower()
    assert any(action["type"].startswith("documents_") for action in overview["recommended_actions"])
    set_current_tenant_id(None)


def test_documents_module_has_no_public_download_or_external_integration():
    import inspect
    import app.modules.secretariat.routes as routes_module
    import app.modules.secretariat.services.documents_agent as documents_agent

    routes_source = inspect.getsource(routes_module).lower()
    service_source = inspect.getsource(documents_agent).lower()
    assert "/documents/{document_id}/download" not in routes_source
    assert "google drive" not in service_source
    assert "sharepoint" not in service_source
    assert "dropbox" not in service_source
    assert "gmail" not in service_source


def test_secretariat_agenda_has_no_calendar_or_meet_integration():
    import inspect
    import app.modules.secretariat.services.agenda_agent as agenda_agent

    source = inspect.getsource(agenda_agent).lower()
    assert "google calendar" not in source
    assert "google meet" not in source
    assert "calendar.events" not in source
    assert "gmail" not in source


def test_gmail_service_does_not_call_send_endpoint():
    import inspect
    import app.modules.secretariat.services.gmail_service as gmail_service

    source = inspect.getsource(gmail_service)
    assert "/send" not in source
    assert "drafts/send" not in source


def test_secretariat_documentation_files_exist_and_cover_key_topics():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        docs = {
            "secretariat_admin.md": ["workflow d'approbation", "roles et permissions", "audit logs"],
            "secretariat_user.md": ["agent courrier", "agent réunion", "validations"],
            "secretariat_developer.md": ["postgresql réel", "test_database_url", "permissions"],
            "secretariat_preprod_checklist.md": ["migrations", "build frontend", "file_path"],
        }
        for filename, needles in docs.items():
            content = (docs_dir / filename).read_text(encoding="utf-8").lower()
            for needle in needles:
                assert needle in content


def test_secretariat_frontend_does_not_expose_tokens_or_file_paths():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    frontend_dir = repo_root / "frontend"
    if frontend_dir.exists():
        api_source = (frontend_dir / "src/api/secretariat.ts").read_text(encoding="utf-8").lower()
        page_source = (frontend_dir / "src/pages/SecretariatPage.tsx").read_text(encoding="utf-8").lower()

        forbidden = {
            "access_token",
            "refresh_token",
            "file_path",
            "gmail.send",
            "users.messages.send",
            "drafts.send",
            "google drive",
            "sharepoint",
            "dropbox",
        }
        for source in (api_source, page_source):
            for token in forbidden:
                assert token not in source
