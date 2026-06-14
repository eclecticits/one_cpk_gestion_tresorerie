from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SecretariatBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SecretariatAgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    type: str = Field(pattern="^(courrier|reunion|agenda|documents|manager)$")
    status: str = Field(default="inactive", pattern="^(active|inactive)$")
    config_json: dict | None = None


class SecretariatAgentOut(SecretariatBaseOut):
    id: int
    name: str
    type: str
    status: str
    config_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class SecretariatConversationCreate(BaseModel):
    agent_id: int
    title: str = Field(min_length=2, max_length=180)
    status: str = "open"


class SecretariatConversationOut(SecretariatBaseOut):
    id: int
    user_id: UUID
    agent_id: int
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class SecretariatMessageCreate(BaseModel):
    content: str = Field(min_length=1)
    metadata_json: dict | None = None


class SecretariatMessageOut(SecretariatBaseOut):
    id: int
    conversation_id: int
    sender_type: str
    content: str
    metadata_json: dict | None = None
    created_at: datetime


class SecretariatTaskCreate(BaseModel):
    agent_id: int
    title: str = Field(min_length=2, max_length=180)
    description: str | None = None
    status: str = Field(default="pending", pattern="^(pending|in_progress|completed|rejected|cancelled)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    due_at: datetime | None = None
    metadata_json: dict | None = None


class SecretariatTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(pending|in_progress|completed|rejected|cancelled)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    due_at: datetime | None = None
    metadata_json: dict | None = None


class SecretariatTaskOut(SecretariatBaseOut):
    id: int
    agent_id: int
    user_id: UUID
    title: str
    description: str | None = None
    status: str
    priority: str
    due_at: datetime | None = None
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class SecretariatAuditLogOut(SecretariatBaseOut):
    id: int
    user_id: UUID | None = None
    agent_type: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    status: str
    metadata_json: dict | None = None
    created_at: datetime


class OAuthStatusOut(BaseModel):
    provider: str = "google"
    configured: bool = False
    connected: bool = False
    status: str = "not_configured"
    email: str | None = None
    scopes: list[str] = []
    expires_at: datetime | None = None
    message: str = "Gmail non connecté. Cliquez sur 'Connecter Gmail' pour autoriser l'accès."


class GoogleConnectOut(BaseModel):
    authorization_url: str


class GmailMessageSummaryOut(BaseModel):
    id: str
    thread_id: str | None = None
    from_: str | None = Field(default=None, validation_alias="from", serialization_alias="from")
    to: str | None = None
    subject: str | None = None
    snippet: str | None = None
    received_at: datetime | None = None
    labels: list[str] = []
    has_attachments: bool = False


class GmailAttachmentMetadataOut(BaseModel):
    filename: str | None = None
    mime_type: str | None = None
    size: int | None = None
    attachment_id: str | None = None


class GmailMessageDetailOut(BaseModel):
    id: str
    thread_id: str | None = None
    headers: dict[str, str] = {}
    subject: str | None = None
    from_: str | None = Field(default=None, validation_alias="from", serialization_alias="from")
    to: str | None = None
    cc: str | None = None
    date: str | None = None
    snippet: str | None = None
    body: str | None = None
    labels: list[str] = []
    attachments: list[GmailAttachmentMetadataOut] = []


class MailSummaryOut(BaseModel):
    message_id: str
    summary: str
    key_points: list[str] = []
    detected_request: str | None = None
    suggested_priority: str = Field(pattern="^(low|normal|high|urgent)$")
    requires_response: bool


class MailClassificationOut(BaseModel):
    message_id: str
    category: str = Field(pattern="^(administratif|financier|réunion|réquisition|cotisation|tableau|forco|juridique|technique|autre)$")
    priority: str = Field(pattern="^(low|normal|high|urgent)$")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    recommended_action: str = Field(pattern="^(répondre|classer|transférer|traiter_plus_tard|demander_validation)$")


class MailDraftRequest(BaseModel):
    tone: str = Field(default="administratif", pattern="^(administratif|cordial|ferme|institutionnel)$")
    instructions: str | None = None


class MailDraftResponseOut(BaseModel):
    message_id: str
    draft_id: int | None = None
    subject: str
    draft_body: str
    requires_human_validation: bool = True


class MailDraftSaveRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    ai_metadata_json: dict | None = None


class MailDraftOut(SecretariatBaseOut):
    id: int
    gmail_message_id: str
    gmail_thread_id: str | None = None
    source_gmail_message_id: str | None = None
    recipient_email: str | None = None
    gmail_draft_id: str | None = None
    gmail_draft_created_at: datetime | None = None
    subject: str
    body: str
    status: str
    ai_metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class GmailDraftCreateOut(BaseModel):
    draft_id: int
    gmail_draft_id: str
    gmail_thread_id: str | None = None
    status: str = "gmail_draft_created"
    message: str = "Brouillon Gmail créé avec succès. Aucun mail n’a été envoyé."


APPROVAL_TYPE_PATTERN = "^(mail_draft_approval|gmail_draft_creation|followup_task|meeting_minutes_validation|agenda_event_creation|document_generation|document_synthesis_validation|manager_recommendation)$"


class SecretariatApprovalCreate(BaseModel):
    agent_type: str = Field(pattern="^(courrier|reunion|agenda|documents|manager|system)$")
    approval_type: str = Field(pattern=APPROVAL_TYPE_PATTERN)
    target_type: str = Field(min_length=2, max_length=80)
    target_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    metadata_json: dict | None = None


class SecretariatApprovalDecision(BaseModel):
    comment: str | None = None


class SecretariatApprovalOut(SecretariatBaseOut):
    id: int
    requested_by_user_id: UUID
    approved_by_user_id: UUID | None = None
    agent_type: str
    approval_type: str
    target_type: str
    target_id: str
    title: str
    description: str | None = None
    status: str
    priority: str
    decision_comment: str | None = None
    metadata_json: dict | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


MEETING_STATUS_PATTERN = "^(draft|planned|held|minutes_draft|minutes_rejected|approved|cancelled)$"
ATTENDANCE_STATUS_PATTERN = "^(invited|present|absent|excused)$"
DECISION_STATUS_PATTERN = "^(open|in_progress|completed|cancelled)$"
ACTION_STATUS_PATTERN = "^(pending|in_progress|completed|cancelled)$"
PRIORITY_PATTERN = "^(low|normal|high|urgent)$"
AGENDA_ITEM_TYPE_PATTERN = "^(meeting|deadline|followup|approval|mail|document|task|other)$"
AGENDA_ITEM_STATUS_PATTERN = "^(pending|in_progress|completed|cancelled|overdue)$"
AGENDA_REMINDER_STATUS_PATTERN = "^(pending|shown|dismissed|cancelled)$"
DOCUMENT_TYPE_PATTERN = "^(courrier|PV|rapport|note|invitation|decision|budget|justificatif|autre)$"
DOCUMENT_STATUS_PATTERN = "^(draft|active|archived|pending_approval|approved|rejected)$"


class AgendaItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_user_id: UUID | None = None
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    item_type: str = Field(default="other", pattern=AGENDA_ITEM_TYPE_PATTERN)
    priority: str = Field(default="normal", pattern=PRIORITY_PATTERN)
    status: str = Field(default="pending", pattern=AGENDA_ITEM_STATUS_PATTERN)
    start_at: datetime | None = None
    due_at: datetime | None = None
    target_type: str | None = Field(default=None, max_length=80)
    target_id: str | None = Field(default=None, max_length=120)
    metadata_json: dict | None = None


class AgendaItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_user_id: UUID | None = None
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    item_type: str | None = Field(default=None, pattern=AGENDA_ITEM_TYPE_PATTERN)
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    status: str | None = Field(default=None, pattern=AGENDA_ITEM_STATUS_PATTERN)
    start_at: datetime | None = None
    due_at: datetime | None = None
    target_type: str | None = Field(default=None, max_length=80)
    target_id: str | None = Field(default=None, max_length=120)
    metadata_json: dict | None = None


class AgendaItemRead(SecretariatBaseOut):
    id: int
    created_by_user_id: UUID
    assigned_to_user_id: UUID | None = None
    title: str
    description: str | None = None
    item_type: str
    priority: str
    status: str
    start_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    target_type: str | None = None
    target_id: str | None = None
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class AgendaReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder_at: datetime
    message: str | None = None


class AgendaReminderRead(SecretariatBaseOut):
    id: int
    agenda_item_id: int
    reminder_at: datetime
    status: str
    message: str | None = None
    created_at: datetime
    updated_at: datetime


class AgendaOverview(BaseModel):
    today: int = 0
    this_week: int = 0
    overdue: int = 0
    upcoming: int = 0
    completed: int = 0
    urgent: int = 0
    reminders_pending: int = 0


class SecretariatDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=255)
    document_type: str = Field(pattern=DOCUMENT_TYPE_PATTERN)
    category: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=120)
    description: str | None = None
    keywords_json: list[str] | None = None
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    file_size: int | None = Field(default=None, ge=0)
    extracted_text: str | None = None
    metadata_json: dict | None = None


class SecretariatDocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=2, max_length=255)
    document_type: str | None = Field(default=None, pattern=DOCUMENT_TYPE_PATTERN)
    category: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=120)
    description: str | None = None
    keywords_json: list[str] | None = None
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    file_size: int | None = Field(default=None, ge=0)
    extracted_text: str | None = None
    metadata_json: dict | None = None


class SecretariatDocumentRead(SecretariatBaseOut):
    id: int
    created_by_user_id: UUID
    title: str
    document_type: str
    category: str | None = None
    status: str
    source: str | None = None
    description: str | None = None
    keywords_json: list[str] | None = None
    has_file: bool = False
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    extracted_text: str | None = None
    summary_text: str | None = None
    synthesis_text: str | None = None
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class SecretariatDocumentSummary(BaseModel):
    document_id: int
    summary_text: str
    requires_human_validation: bool = True


class SecretariatDocumentSynthesis(BaseModel):
    document_id: int
    synthesis_text: str
    requires_human_validation: bool = True


class SecretariatDocumentVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str | None = Field(default=None, max_length=255)
    extracted_text: str | None = None
    summary_text: str | None = None
    synthesis_text: str | None = None


class SecretariatDocumentVersionRead(SecretariatBaseOut):
    id: int
    document_id: int
    version_number: int
    file_name: str | None = None
    extracted_text: str | None = None
    summary_text: str | None = None
    synthesis_text: str | None = None
    created_by_user_id: UUID
    created_at: datetime


class SecretariatMeetingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=255)
    meeting_type: str = Field(default="administrative", min_length=2, max_length=80)
    location: str | None = Field(default=None, max_length=255)
    meeting_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None


class SecretariatMeetingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=2, max_length=255)
    meeting_type: str | None = Field(default=None, min_length=2, max_length=80)
    location: str | None = Field(default=None, max_length=255)
    meeting_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None


class SecretariatMeetingParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    email: str | None = Field(default=None, max_length=320)
    role: str | None = Field(default=None, max_length=120)
    attendance_status: str = Field(default="invited", pattern=ATTENDANCE_STATUS_PATTERN)
    metadata_json: dict | None = None


class SecretariatMeetingParticipantOut(SecretariatBaseOut):
    id: int
    meeting_id: int
    name: str
    email: str | None = None
    role: str | None = None
    attendance_status: str
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class SecretariatMeetingDecisionOut(SecretariatBaseOut):
    id: int
    meeting_id: int
    decision_text: str
    responsible_name: str | None = None
    due_date: date | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class SecretariatMeetingActionItemOut(SecretariatBaseOut):
    id: int
    meeting_id: int
    title: str
    description: str | None = None
    responsible_name: str | None = None
    due_date: date | None = None
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


class SecretariatMeetingOut(SecretariatBaseOut):
    id: int
    created_by_user_id: UUID
    title: str
    meeting_type: str
    location: str | None = None
    meeting_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    status: str
    agenda_text: str | None = None
    invitation_draft: str | None = None
    minutes_draft: str | None = None
    approved_minutes: str | None = None
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class SecretariatMeetingDetailOut(SecretariatMeetingOut):
    participants: list[SecretariatMeetingParticipantOut] = []
    decisions: list[SecretariatMeetingDecisionOut] = []
    action_items: list[SecretariatMeetingActionItemOut] = []


class MeetingTextGenerationRequest(BaseModel):
    instructions: str | None = None


class MeetingNotesRequest(BaseModel):
    notes: str = Field(min_length=1)


class MeetingGeneratedTextOut(BaseModel):
    meeting_id: int
    text: str


class MeetingSubmitApprovalOut(BaseModel):
    meeting_id: int
    approval_id: int
    status: str = "pending"


class ManagerTaskStats(BaseModel):
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    rejected: int = 0
    urgent: int = 0


class ManagerDraftStats(BaseModel):
    internal_drafts: int = 0
    approved: int = 0
    rejected: int = 0
    gmail_draft_created: int = 0


class ManagerApprovalStats(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    cancelled: int = 0
    urgent: int = 0


class ManagerOAuthStatus(BaseModel):
    gmail_connected: bool = False
    email: str | None = None
    has_gmail_readonly: bool = False
    has_gmail_compose: bool = False


class ManagerDocumentRecentItem(BaseModel):
    id: int
    title: str
    document_type: str
    status: str
    created_at: datetime


class ManagerDocumentStats(BaseModel):
    pending_approval: int = 0
    syntheses_to_validate: int = 0
    recent_created: list[ManagerDocumentRecentItem] = Field(default_factory=list)


class ManagerAgendaStats(BaseModel):
    today: int = 0
    overdue: int = 0
    urgent: int = 0
    reminders_pending: int = 0


class ManagerRecommendedAction(BaseModel):
    type: str
    title: str
    priority: str = Field(pattern="^(low|normal|high|urgent)$")
    target_id: str


class ManagerOverviewOut(BaseModel):
    tasks: ManagerTaskStats
    mail_drafts: ManagerDraftStats
    approvals: ManagerApprovalStats = ManagerApprovalStats()
    documents: ManagerDocumentStats = ManagerDocumentStats()
    agenda: ManagerAgendaStats = ManagerAgendaStats()
    oauth: ManagerOAuthStatus
    recommended_actions: list[ManagerRecommendedAction] = []


class ManagerApprovalItem(BaseModel):
    id: int
    type: str
    title: str
    status: str
    priority: str = "normal"
    created_at: datetime
    target_id: str


class ManagerWorkloadOut(BaseModel):
    by_agent: dict[str, ManagerTaskStats]
    urgent_tasks: list[SecretariatTaskOut] = []
    recent_completed: list[SecretariatTaskOut] = []


class ManagerFollowupTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    due_at: datetime | None = None
    target_type: str | None = None
    target_id: str | None = None
