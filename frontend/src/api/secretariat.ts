import { apiRequest } from '../lib/apiClient'

export type SecretariatAgentType = 'courrier' | 'reunion' | 'agenda' | 'documents' | 'manager'

export interface SecretariatAgent {
  id: number
  name: string
  type: SecretariatAgentType
  status: 'active' | 'inactive'
  config_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface SecretariatTask {
  id: number
  agent_id: number
  user_id: string
  title: string
  description?: string | null
  status: 'pending' | 'in_progress' | 'completed' | 'rejected' | 'cancelled'
  priority: 'low' | 'normal' | 'high' | 'urgent'
  due_at?: string | null
  metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface SecretariatOAuthStatus {
  provider: string
  configured: boolean
  connected: boolean
  status: string
  email?: string | null
  scopes: string[]
  expires_at?: string | null
  message: string
}

export interface GoogleConnectResponse {
  authorization_url: string
}

export interface CourrierEmailSummary {
  id: string
  thread_id?: string | null
  from?: string | null
  to?: string | null
  subject?: string | null
  snippet?: string | null
  received_at?: string | null
  labels: string[]
  has_attachments: boolean
}

export interface CourrierEmailDetail {
  id: string
  thread_id?: string | null
  headers: Record<string, string>
  subject?: string | null
  from?: string | null
  to?: string | null
  cc?: string | null
  date?: string | null
  snippet?: string | null
  body?: string | null
  labels: string[]
  attachments: { filename?: string | null; mime_type?: string | null; size?: number | null; attachment_id?: string | null }[]
}

export interface MailSummary {
  message_id: string
  summary: string
  key_points: string[]
  detected_request?: string | null
  suggested_priority: 'low' | 'normal' | 'high' | 'urgent'
  requires_response: boolean
}

export interface MailClassification {
  message_id: string
  category: string
  priority: 'low' | 'normal' | 'high' | 'urgent'
  confidence: number
  reason: string
  recommended_action: 'répondre' | 'classer' | 'transférer' | 'traiter_plus_tard' | 'demander_validation'
}

export interface MailDraftResponse {
  message_id: string
  draft_id?: number | null
  subject: string
  draft_body: string
  requires_human_validation: boolean
}

export interface MailDraft {
  id: number
  gmail_message_id: string
  gmail_thread_id?: string | null
  source_gmail_message_id?: string | null
  recipient_email?: string | null
  gmail_draft_id?: string | null
  gmail_draft_created_at?: string | null
  subject: string
  body: string
  status: 'draft' | 'approved' | 'rejected' | 'gmail_draft_created' | 'cancelled'
  ai_metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface GmailDraftCreateResult {
  draft_id: number
  gmail_draft_id: string
  gmail_thread_id?: string | null
  status: 'gmail_draft_created'
  message: string
}

export interface SecretariatApproval {
  id: number
  requested_by_user_id: string
  approved_by_user_id?: string | null
  agent_type: string
  approval_type: string
  target_type: string
  target_id: string
  title: string
  description?: string | null
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  priority: 'low' | 'normal' | 'high' | 'urgent'
  decision_comment?: string | null
  metadata_json?: Record<string, any> | null
  requested_at: string
  decided_at?: string | null
  created_at: string
  updated_at: string
}

export interface SecretariatApprovalInput {
  agent_type: string
  approval_type: string
  target_type: string
  target_id: string
  title: string
  description?: string | null
  priority?: 'low' | 'normal' | 'high' | 'urgent'
  metadata_json?: Record<string, any> | null
}

export interface ManagerTaskStats {
  pending: number
  in_progress: number
  completed: number
  rejected: number
  urgent: number
}

export interface ManagerDraftStats {
  internal_drafts: number
  approved: number
  rejected: number
  gmail_draft_created: number
}

export interface ManagerApprovalStats {
  pending: number
  approved: number
  rejected: number
  cancelled: number
  urgent: number
}

export interface ManagerAgendaStats {
  today: number
  overdue: number
  urgent: number
  reminders_pending: number
}

export interface ManagerDocumentRecentItem {
  id: number
  title: string
  document_type: string
  status: string
  created_at: string
}

export interface ManagerDocumentStats {
  pending_approval: number
  syntheses_to_validate: number
  recent_created: ManagerDocumentRecentItem[]
}

export interface ManagerOAuthStatus {
  gmail_connected: boolean
  email?: string | null
  has_gmail_readonly: boolean
  has_gmail_compose: boolean
}

export interface ManagerRecommendedAction {
  type: string
  title: string
  priority: 'low' | 'normal' | 'high' | 'urgent'
  target_id: string
}

export interface ManagerOverview {
  tasks: ManagerTaskStats
  mail_drafts: ManagerDraftStats
  approvals: ManagerApprovalStats
  documents: ManagerDocumentStats
  agenda: ManagerAgendaStats
  oauth: ManagerOAuthStatus
  recommended_actions: ManagerRecommendedAction[]
}

export interface ManagerApprovalItem {
  id: number
  type: string
  title: string
  status: string
  priority: 'low' | 'normal' | 'high' | 'urgent'
  created_at: string
  target_id: string
}

export interface ManagerWorkload {
  by_agent: Record<string, ManagerTaskStats>
  urgent_tasks: SecretariatTask[]
  recent_completed: SecretariatTask[]
}

export interface ManagerFollowupTaskInput {
  title: string
  description?: string | null
  priority?: 'low' | 'normal' | 'high' | 'urgent'
  due_at?: string | null
  target_type?: string | null
  target_id?: string | null
}

export interface SecretariatMeetingParticipant {
  id: number
  meeting_id: number
  name: string
  email?: string | null
  role?: string | null
  attendance_status: 'invited' | 'present' | 'absent' | 'excused'
  metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface SecretariatMeetingDecision {
  id: number
  meeting_id: number
  decision_text: string
  responsible_name?: string | null
  due_date?: string | null
  status: 'open' | 'in_progress' | 'completed' | 'cancelled'
  created_at: string
  updated_at: string
}

export interface SecretariatMeetingActionItem {
  id: number
  meeting_id: number
  title: string
  description?: string | null
  responsible_name?: string | null
  due_date?: string | null
  priority: 'low' | 'normal' | 'high' | 'urgent'
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled'
  created_at: string
  updated_at: string
}

export interface SecretariatMeeting {
  id: number
  created_by_user_id: string
  title: string
  meeting_type: string
  location?: string | null
  meeting_date?: string | null
  start_time?: string | null
  end_time?: string | null
  status: 'draft' | 'planned' | 'held' | 'minutes_draft' | 'minutes_rejected' | 'approved' | 'cancelled'
  agenda_text?: string | null
  invitation_draft?: string | null
  minutes_draft?: string | null
  approved_minutes?: string | null
  metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface SecretariatMeetingDetail extends SecretariatMeeting {
  participants: SecretariatMeetingParticipant[]
  decisions: SecretariatMeetingDecision[]
  action_items: SecretariatMeetingActionItem[]
}

export interface SecretariatMeetingInput {
  title: string
  meeting_type?: string
  location?: string | null
  meeting_date?: string | null
  start_time?: string | null
  end_time?: string | null
}

export interface SecretariatMeetingParticipantInput {
  name: string
  email?: string | null
  role?: string | null
  attendance_status?: SecretariatMeetingParticipant['attendance_status']
}

export interface MeetingGeneratedText {
  meeting_id: number
  text: string
}

export interface MeetingSubmitApprovalResult {
  meeting_id: number
  approval_id: number
  status: 'pending'
}

export type AgendaItemType = 'meeting' | 'deadline' | 'followup' | 'approval' | 'mail' | 'document' | 'task' | 'other'
export type AgendaItemStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled' | 'overdue'
export type AgendaReminderStatus = 'pending' | 'shown' | 'dismissed' | 'cancelled'

export interface AgendaItem {
  id: number
  created_by_user_id: string
  assigned_to_user_id?: string | null
  title: string
  description?: string | null
  item_type: AgendaItemType
  priority: 'low' | 'normal' | 'high' | 'urgent'
  status: AgendaItemStatus
  start_at?: string | null
  due_at?: string | null
  completed_at?: string | null
  target_type?: string | null
  target_id?: string | null
  metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface AgendaItemInput {
  title: string
  description?: string | null
  item_type?: AgendaItemType
  priority?: 'low' | 'normal' | 'high' | 'urgent'
  status?: AgendaItemStatus
  start_at?: string | null
  due_at?: string | null
  target_type?: string | null
  target_id?: string | null
  metadata_json?: Record<string, any> | null
}

export interface AgendaReminder {
  id: number
  agenda_item_id: number
  reminder_at: string
  status: AgendaReminderStatus
  message?: string | null
  created_at: string
  updated_at: string
}

export interface AgendaReminderInput {
  reminder_at: string
  message?: string | null
}

export interface AgendaOverview {
  today: number
  this_week: number
  overdue: number
  upcoming: number
  completed: number
  urgent: number
  reminders_pending: number
}

export type SecretariatDocumentType = 'courrier' | 'PV' | 'rapport' | 'note' | 'invitation' | 'decision' | 'budget' | 'justificatif' | 'autre'
export type SecretariatDocumentStatus = 'draft' | 'active' | 'archived' | 'pending_approval' | 'approved' | 'rejected'

export interface SecretariatDocument {
  id: number
  created_by_user_id: string
  title: string
  document_type: SecretariatDocumentType
  category?: string | null
  status: SecretariatDocumentStatus
  source?: string | null
  description?: string | null
  keywords_json?: string[] | null
  has_file: boolean
  file_name?: string | null
  mime_type?: string | null
  file_size?: number | null
  extracted_text?: string | null
  summary_text?: string | null
  synthesis_text?: string | null
  metadata_json?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface SecretariatDocumentVersion {
  id: number
  document_id: number
  version_number: number
  file_name?: string | null
  extracted_text?: string | null
  summary_text?: string | null
  synthesis_text?: string | null
  created_by_user_id: string
  created_at: string
}

export interface SecretariatDocumentInput {
  title: string
  document_type: SecretariatDocumentType
  category?: string | null
  source?: string | null
  description?: string | null
  keywords_json?: string[] | null
  file_name?: string | null
  mime_type?: string | null
  file_size?: number | null
  extracted_text?: string | null
  metadata_json?: Record<string, any> | null
}

export interface SecretariatDocumentSummaryResult {
  document_id: number
  summary_text: string
  requires_human_validation: boolean
}

export interface SecretariatDocumentSynthesisResult {
  document_id: number
  synthesis_text: string
  requires_human_validation: boolean
}

export interface SecretariatDocumentVersionInput {
  file_name?: string | null
  extracted_text?: string | null
  summary_text?: string | null
  synthesis_text?: string | null
}

export const getSecretariatAgents = () => apiRequest<SecretariatAgent[]>('GET', '/secretariat/agents')
export const createSecretariatAgent = (input: Partial<SecretariatAgent>) => apiRequest<SecretariatAgent>('POST', '/secretariat/agents', input)
export const getSecretariatTasks = () => apiRequest<SecretariatTask[]>('GET', '/secretariat/tasks')
export const createSecretariatTask = (input: Partial<SecretariatTask>) => apiRequest<SecretariatTask>('POST', '/secretariat/tasks', input)
export const getSecretariatOAuthStatus = () => apiRequest<SecretariatOAuthStatus>('GET', '/secretariat/oauth/status')
export const getGoogleStatus = () => apiRequest<SecretariatOAuthStatus>('GET', '/secretariat/google/status')
export const startGoogleConnect = () => apiRequest<GoogleConnectResponse>('GET', '/secretariat/google/connect')
export const disconnectGoogle = () => apiRequest<SecretariatOAuthStatus>('DELETE', '/secretariat/google/disconnect')
export const listCourrierEmails = () => apiRequest<CourrierEmailSummary[]>('GET', '/secretariat/courrier/emails')
export const getCourrierEmail = (messageId: string) => apiRequest<CourrierEmailDetail>('GET', `/secretariat/courrier/emails/${encodeURIComponent(messageId)}`)
export const summarizeCourrierEmail = (messageId: string) => apiRequest<MailSummary>('POST', `/secretariat/courrier/emails/${encodeURIComponent(messageId)}/summarize`)
export const classifyCourrierEmail = (messageId: string) => apiRequest<MailClassification>('POST', `/secretariat/courrier/emails/${encodeURIComponent(messageId)}/classify`)
export const draftCourrierResponse = (messageId: string, input: { tone: string; instructions?: string | null }) =>
  apiRequest<MailDraftResponse>('POST', `/secretariat/courrier/emails/${encodeURIComponent(messageId)}/draft-response`, input)
export const saveCourrierDraft = (messageId: string, input: { subject: string; body: string; ai_metadata_json?: Record<string, any> | null }) =>
  apiRequest<MailDraft>('POST', `/secretariat/courrier/emails/${encodeURIComponent(messageId)}/drafts`, input)
export const createGmailDraft = (draftId: number) => apiRequest<GmailDraftCreateResult>('POST', `/secretariat/courrier/drafts/${draftId}/create-gmail-draft`)
export const listApprovals = () => apiRequest<SecretariatApproval[]>('GET', '/secretariat/approvals')
export const getApproval = (id: number) => apiRequest<SecretariatApproval>('GET', `/secretariat/approvals/${id}`)
export const createApproval = (input: SecretariatApprovalInput) => apiRequest<SecretariatApproval>('POST', '/secretariat/approvals', input)
export const approveApproval = (id: number, comment?: string | null) =>
  apiRequest<SecretariatApproval>('POST', `/secretariat/approvals/${id}/approve`, { comment: comment || null })
export const rejectApproval = (id: number, comment?: string | null) =>
  apiRequest<SecretariatApproval>('POST', `/secretariat/approvals/${id}/reject`, { comment: comment || null })
export const cancelApproval = (id: number) => apiRequest<SecretariatApproval>('POST', `/secretariat/approvals/${id}/cancel`)
export const getManagerOverview = () => apiRequest<ManagerOverview>('GET', '/secretariat/manager/overview')
export const getManagerPendingApprovals = () => apiRequest<ManagerApprovalItem[]>('GET', '/secretariat/manager/pending-approvals')
export const getManagerWorkload = () => apiRequest<ManagerWorkload>('GET', '/secretariat/manager/workload')
export const getManagerRecommendedActions = () => apiRequest<ManagerRecommendedAction[]>('GET', '/secretariat/manager/recommended-actions')
export const createManagerFollowupTask = (input: ManagerFollowupTaskInput) =>
  apiRequest<SecretariatTask>('POST', '/secretariat/manager/followup-task', input)
export const listMeetings = () => apiRequest<SecretariatMeeting[]>('GET', '/secretariat/reunions')
export const createMeeting = (input: SecretariatMeetingInput) => apiRequest<SecretariatMeetingDetail>('POST', '/secretariat/reunions', input)
export const getMeeting = (id: number) => apiRequest<SecretariatMeetingDetail>('GET', `/secretariat/reunions/${id}`)
export const updateMeeting = (id: number, input: Partial<SecretariatMeetingInput>) => apiRequest<SecretariatMeetingDetail>('PATCH', `/secretariat/reunions/${id}`, input)
export const addMeetingParticipant = (id: number, input: SecretariatMeetingParticipantInput) =>
  apiRequest<SecretariatMeetingParticipant>('POST', `/secretariat/reunions/${id}/participants`, input)
export const removeMeetingParticipant = (id: number, participantId: number) =>
  apiRequest<void>('DELETE', `/secretariat/reunions/${id}/participants/${participantId}`)
export const generateMeetingAgenda = (id: number, instructions?: string | null) =>
  apiRequest<MeetingGeneratedText>('POST', `/secretariat/reunions/${id}/generate-agenda`, { instructions: instructions || null })
export const generateMeetingInvitation = (id: number, instructions?: string | null) =>
  apiRequest<MeetingGeneratedText>('POST', `/secretariat/reunions/${id}/generate-invitation`, { instructions: instructions || null })
export const saveMeetingNotes = (id: number, notes: string) =>
  apiRequest<SecretariatMeetingDetail>('POST', `/secretariat/reunions/${id}/save-notes`, { notes })
export const extractMeetingDecisions = (id: number) =>
  apiRequest<SecretariatMeetingDecision[]>('POST', `/secretariat/reunions/${id}/extract-decisions`)
export const extractMeetingActionItems = (id: number) =>
  apiRequest<SecretariatMeetingActionItem[]>('POST', `/secretariat/reunions/${id}/extract-action-items`)
export const generateMeetingMinutes = (id: number, instructions?: string | null) =>
  apiRequest<MeetingGeneratedText>('POST', `/secretariat/reunions/${id}/generate-minutes`, { instructions: instructions || null })
export const submitMeetingMinutesApproval = (id: number) =>
  apiRequest<MeetingSubmitApprovalResult>('POST', `/secretariat/reunions/${id}/submit-minutes-approval`)
export const listAgendaItems = (params: Record<string, string> = {}) => {
  const query = new URLSearchParams(params)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest<AgendaItem[]>('GET', `/secretariat/agenda/items${suffix}`)
}
export const createAgendaItem = (input: AgendaItemInput) => apiRequest<AgendaItem>('POST', '/secretariat/agenda/items', input)
export const updateAgendaItem = (id: number, input: Partial<AgendaItemInput>) => apiRequest<AgendaItem>('PATCH', `/secretariat/agenda/items/${id}`, input)
export const completeAgendaItem = (id: number) => apiRequest<AgendaItem>('POST', `/secretariat/agenda/items/${id}/complete`)
export const cancelAgendaItem = (id: number) => apiRequest<AgendaItem>('POST', `/secretariat/agenda/items/${id}/cancel`)
export const listAgendaReminders = (params: Record<string, string> = {}) => {
  const query = new URLSearchParams(params)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest<AgendaReminder[]>('GET', `/secretariat/agenda/reminders${suffix}`)
}
export const createAgendaReminder = (itemId: number, input: AgendaReminderInput) =>
  apiRequest<AgendaReminder>('POST', `/secretariat/agenda/items/${itemId}/reminders`, input)
export const dismissAgendaReminder = (id: number) => apiRequest<AgendaReminder>('POST', `/secretariat/agenda/reminders/${id}/dismiss`)
export const getAgendaOverview = () => apiRequest<AgendaOverview>('GET', '/secretariat/agenda/overview')

export const listDocuments = (params: Record<string, string> = {}) => {
  const query = new URLSearchParams(params)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest<SecretariatDocument[]>('GET', `/secretariat/documents${suffix}`)
}
export const createDocument = (input: SecretariatDocumentInput) => apiRequest<SecretariatDocument>('POST', '/secretariat/documents', input)
export const updateDocument = (id: number, input: Partial<SecretariatDocumentInput>) =>
  apiRequest<SecretariatDocument>('PATCH', `/secretariat/documents/${id}`, input)
export const archiveDocument = (id: number) => apiRequest<SecretariatDocument>('POST', `/secretariat/documents/${id}/archive`)
export const getDocument = (id: number) => apiRequest<SecretariatDocument>('GET', `/secretariat/documents/${id}`)
export const addDocumentVersion = (id: number, input: SecretariatDocumentVersionInput) =>
  apiRequest<SecretariatDocumentVersion>('POST', `/secretariat/documents/${id}/versions`, input)
export const listDocumentVersions = (id: number) => apiRequest<SecretariatDocumentVersion[]>('GET', `/secretariat/documents/${id}/versions`)
export const summarizeDocument = (id: number) => apiRequest<SecretariatDocumentSummaryResult>('POST', `/secretariat/documents/${id}/summarize`)
export const generateDocumentSynthesis = (id: number) =>
  apiRequest<SecretariatDocumentSynthesisResult>('POST', `/secretariat/documents/${id}/generate-synthesis`)
export const submitDocumentSynthesisApproval = (id: number) =>
  apiRequest<SecretariatApproval>('POST', `/secretariat/documents/${id}/submit-synthesis-approval`)

// ── Manager Agent Chat (Agentor pattern) ────────────────────────────────────

export interface AgentChatMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string
}

export interface AgentChatRequest {
  message: string
  conversation_history?: AgentChatMessage[]
}

export interface AgentChatResponse {
  response: string
  actions_taken: string[]
  tool_results: Array<{ outil: string; resultat: any }>
}

export const managerAgentChat = (input: AgentChatRequest) =>
  apiRequest<AgentChatResponse>('POST', '/secretariat/ai/manager/chat', input)
