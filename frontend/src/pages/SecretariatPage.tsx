import { ReactNode, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bot, CalendarDays, CheckCircle2, ClipboardList, FileText, Mail, MessageSquare, Paperclip, RefreshCw, Settings2, ShieldCheck, Table2, UsersRound } from 'lucide-react'
import SecretariatAgentChat from '../components/SecretariatAgentChat'
import AiContentBanner from '../components/AiContentBanner'
import BackButton from '../components/BackButton'
import { ApiError } from '../lib/apiClient'
import {
  cancelAgendaItem,
  disconnectGoogle,
  approveApproval,
  cancelApproval,
  classifyCourrierEmail,
  addMeetingParticipant,
  completeAgendaItem,
  createApproval,
  createAgendaItem,
  createAgendaReminder,
  createGmailDraft,
  createMeeting,
  archiveDocument,
  addDocumentVersion,
  dismissAgendaReminder,
  draftCourrierResponse,
  generateDocumentSynthesis,
  extractMeetingActionItems,
  extractMeetingDecisions,
  generateMeetingAgenda,
  generateMeetingInvitation,
  generateMeetingMinutes,
  getDocument,
  getCourrierEmail,
  getGoogleStatus,
  getAgendaOverview,
  getManagerOverview,
  getManagerPendingApprovals,
  getManagerRecommendedActions,
  getManagerWorkload,
  listApprovals,
  listAgendaItems,
  listAgendaReminders,
  listDocumentVersions,
  listDocuments,
  rejectApproval,
  getMeeting,
  listMeetings,
  removeMeetingParticipant,
  saveCourrierDraft,
  summarizeDocument,
  saveMeetingNotes,
  createManagerFollowupTask,
  createDocument,
  getSecretariatAgents,
  getSecretariatTasks,
  listCourrierEmails,
  startGoogleConnect,
  submitDocumentSynthesisApproval,
  submitMeetingMinutesApproval,
  summarizeCourrierEmail,
  type CourrierEmailDetail,
  type AgendaItem,
  type AgendaItemType,
  type AgendaOverview,
  type AgendaReminder,
  type SecretariatDocument,
  type SecretariatDocumentInput,
  type SecretariatDocumentVersion,
  type CourrierEmailSummary,
  type MailClassification,
  type MailDraft,
  type MailDraftResponse,
  type MailSummary,
  type GmailDraftCreateResult,
  type ManagerApprovalItem,
  type ManagerOverview,
  type ManagerRecommendedAction,
  type ManagerWorkload,
  type SecretariatApproval,
  type SecretariatAgent,
  type SecretariatMeeting,
  type SecretariatMeetingDetail,
  type SecretariatOAuthStatus,
  type SecretariatTask,
} from '../api/secretariat'
import styles from './SecretariatPage.module.css'

type SecretariatPageKind = 'dashboard' | 'courrier' | 'reunion' | 'agenda' | 'documents' | 'manager' | 'approvals' | 'settings'

interface Feature {
  icon: ReactNode
  title: string
  text: string
  status?: string
}

const pageConfig: Record<SecretariatPageKind, {
  title: string
  description: string
  icon: ReactNode
  agentType?: string
  features: Feature[]
}> = {
  dashboard: {
    title: 'Tableau de bord',
    description: 'Vue de préparation du futur secrétariat augmenté par agents IA, avec suivi des agents, des tâches et des connexions à venir.',
    icon: <Bot size={19} />,
    features: [
      { icon: <Bot size={18} />, title: 'Agents IA', text: 'Base fonctionnelle prête pour déclarer et suivre les agents du secrétariat.', status: 'Préparé' },
      { icon: <ClipboardList size={18} />, title: 'Tâches', text: 'Suivi centralisé des tâches créées par les agents ou les utilisateurs.', status: 'Disponible' },
      { icon: <ShieldCheck size={18} />, title: 'Audit', text: 'Journalisation dédiée des actions sensibles du module.', status: 'Disponible' },
    ],
  },
  courrier: {
    title: 'Agent Courrier',
    description: 'Agent destiné à consulter les courriers Gmail récents, préparer des réponses internes et créer des brouillons Gmail après approbation centralisée. Aucun mail n\'est envoyé.',
    icon: <Mail size={19} />,
    agentType: 'courrier',
    features: [
      { icon: <Mail size={18} />, title: 'Connexion Gmail', text: 'Connexion OAuth Google côté backend uniquement.', status: 'Disponible' },
      { icon: <MessageSquare size={18} />, title: 'Lecture des mails', text: 'Liste et détail des mails récents via Gmail API readonly.', status: 'Disponible' },
      { icon: <Bot size={18} />, title: 'Résumé automatique', text: 'Non intégré dans cette phase.', status: 'Non disponible' },
      { icon: <FileText size={18} />, title: 'Brouillons assistés', text: 'Brouillon Gmail possible après approbation centralisée.', status: 'Disponible' },
      { icon: <CheckCircle2 size={18} />, title: 'Envoi après validation', text: 'Aucun envoi de mail dans cette phase.', status: 'Désactivé' },
    ],
  },
  reunion: {
    title: 'Agent Réunion',
    description: 'Agent destiné à préparer les réunions administratives, structurer les notes, extraire décisions et tâches, puis soumettre le PV à validation.',
    icon: <UsersRound size={19} />,
    agentType: 'reunion',
    features: [
      { icon: <ClipboardList size={18} />, title: 'Ordres du jour', text: 'Préparation assistée des points à traiter.', status: 'Disponible' },
      { icon: <FileText size={18} />, title: 'Comptes rendus', text: 'Projet de PV soumis au workflow centralisé.', status: 'Disponible' },
      { icon: <CheckCircle2 size={18} />, title: 'Actions de suivi', text: 'Extraction des décisions et tâches depuis les notes saisies.', status: 'Disponible' },
    ],
  },
  agenda: {
    title: 'Agent Agenda',
    description: 'Agenda interne du Secrétariat pour suivre échéances, rappels, réunions, validations et actions administratives, sans connexion Google Calendar.',
    icon: <CalendarDays size={19} />,
    agentType: 'agenda',
    features: [
      { icon: <CalendarDays size={18} />, title: 'Échéances', text: 'Suivi interne des dates administratives et actions à faire.', status: 'Disponible' },
      { icon: <ClipboardList size={18} />, title: 'Rappels internes', text: 'Rappels visibles dans l\'application uniquement.', status: 'Disponible' },
      { icon: <ShieldCheck size={18} />, title: 'Sans intégration externe', text: 'Aucun Google Calendar, Meet ou envoi mail.', status: 'Verrouillé' },
    ],
  },
  documents: {
    title: 'Agent Documents',
    description: 'Agent prévu pour classer, résumer et préparer les documents administratifs du secrétariat.',
    icon: <FileText size={19} />,
    agentType: 'documents',
    features: [
      { icon: <FileText size={18} />, title: 'Classement', text: 'Préparation des catégories documentaires.', status: 'Prévu' },
      { icon: <Bot size={18} />, title: 'Résumé', text: 'Synthèse assistée des documents après cadrage IA.', status: 'Prévu' },
      { icon: <ShieldCheck size={18} />, title: 'Traçabilité', text: 'Journalisation des consultations et actions sensibles.', status: 'Prévu' },
    ],
  },
  manager: {
    title: 'Agent Manager',
    description: 'Agent d\'orchestration chargé de coordonner les agents spécialisés, les tâches et les validations humaines.',
    icon: <Bot size={19} />,
    agentType: 'manager',
    features: [
      { icon: <Bot size={18} />, title: 'Orchestration des agents', text: 'Coordination future des agents courrier, réunion, agenda et documents.', status: 'Prévu' },
      { icon: <ClipboardList size={18} />, title: 'Suivi des tâches', text: 'Pilotage des tâches et statuts opérationnels.', status: 'Préparé' },
      { icon: <CheckCircle2 size={18} />, title: 'Validation humaine', text: 'Point de contrôle obligatoire avant les actions sensibles.', status: 'Prévu' },
      { icon: <ShieldCheck size={18} />, title: 'Journalisation des actions', text: 'Historique dédié pour audit et supervision.', status: 'Disponible' },
    ],
  },
  approvals: {
    title: 'Validations',
    description: 'Workflow centralisé d\'approbation humaine pour les actions sensibles du secrétariat.',
    icon: <ShieldCheck size={19} />,
    features: [
      { icon: <ShieldCheck size={18} />, title: 'Validation humaine', text: 'Approbation ou rejet explicite avant exécution des actions sensibles.', status: 'Disponible' },
      { icon: <ClipboardList size={18} />, title: 'Suivi centralisé', text: 'Vue unifiée des demandes liées aux agents et brouillons.', status: 'Disponible' },
      { icon: <FileText size={18} />, title: 'Traçabilité', text: 'Décisions journalisées sans contenu mail complet.', status: 'Disponible' },
    ],
  },
  settings: {
    title: 'Paramètres IA',
    description: 'Espace de préparation des paramètres IA et connexions externes. Aucune clé API ni connexion OAuth n\'est configurée dans cette phase.',
    icon: <Settings2 size={19} />,
    features: [
      { icon: <Settings2 size={18} />, title: 'Configuration IA', text: 'Paramètres réservés pour la phase d\'intégration IA.', status: 'Non configuré' },
      { icon: <Mail size={18} />, title: 'OAuth Google', text: 'Table prête côté backend, connexion non activée.', status: 'Non configuré' },
      { icon: <ShieldCheck size={18} />, title: 'Secrets', text: 'Aucun secret applicatif n\'est stocké dans le frontend.', status: 'Conforme' },
    ],
  },
}

export default function SecretariatPage({ kind }: { kind: SecretariatPageKind }) {
  const config = pageConfig[kind]
  const [searchParams, setSearchParams] = useSearchParams()
  const [agents, setAgents] = useState<SecretariatAgent[]>([])
  const [tasks, setTasks] = useState<SecretariatTask[]>([])
  const [googleStatus, setGoogleStatus] = useState<SecretariatOAuthStatus | null>(null)
  const [googleCallbackMsg, setGoogleCallbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [emails, setEmails] = useState<CourrierEmailSummary[]>([])
  const [selectedEmailId, setSelectedEmailId] = useState<string | null>(null)
  const [selectedEmail, setSelectedEmail] = useState<CourrierEmailDetail | null>(null)
  const [emailAnalyses, setEmailAnalyses] = useState<Record<string, {
    summary: MailSummary | null
    classification: MailClassification | null
    draftResponse: MailDraftResponse | null
    savedDraft: MailDraft | null
    gmailDraftResult: GmailDraftCreateResult | null
    draftSubject: string
    draftBody: string
    draftTone: string
    draftInstructions: string
    analysisLoading: boolean
  }>>({})
  const [mailError, setMailError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [mailLoading, setMailLoading] = useState(false)
  const [aiLoading, setAiLoading] = useState<string | null>(null)
  const [managerOverview, setManagerOverview] = useState<ManagerOverview | null>(null)
  const [managerApprovals, setManagerApprovals] = useState<ManagerApprovalItem[]>([])
  const [managerWorkload, setManagerWorkload] = useState<ManagerWorkload | null>(null)
  const [managerActions, setManagerActions] = useState<ManagerRecommendedAction[]>([])
  const [managerError, setManagerError] = useState<string | null>(null)
  const [managerLoading, setManagerLoading] = useState(false)
  const [approvals, setApprovals] = useState<SecretariatApproval[]>([])
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const [approvalLoading, setApprovalLoading] = useState(false)
  const [decisionComments, setDecisionComments] = useState<Record<number, string>>({})
  const [followupTitle, setFollowupTitle] = useState('')
  const [followupDescription, setFollowupDescription] = useState('')
  const [followupPriority, setFollowupPriority] = useState<'low' | 'normal' | 'high' | 'urgent'>('normal')
  const [followupTargetType, setFollowupTargetType] = useState('')
  const [followupTargetId, setFollowupTargetId] = useState('')
  const [meetings, setMeetings] = useState<SecretariatMeeting[]>([])
  const [selectedMeeting, setSelectedMeeting] = useState<SecretariatMeetingDetail | null>(null)
  const [meetingLoading, setMeetingLoading] = useState(false)
  const [meetingError, setMeetingError] = useState<string | null>(null)
  const [meetingForm, setMeetingForm] = useState({
    title: '',
    meeting_type: 'administrative',
    meeting_date: '',
    start_time: '',
    end_time: '',
    location: '',
  })
  const [participantForm, setParticipantForm] = useState({ name: '', email: '', role: '' })
  const [meetingNotes, setMeetingNotes] = useState('')
  const [meetingInstructions, setMeetingInstructions] = useState('')
  const [agendaItems, setAgendaItems] = useState<AgendaItem[]>([])
  const [agendaReminders, setAgendaReminders] = useState<AgendaReminder[]>([])
  const [agendaOverview, setAgendaOverview] = useState<AgendaOverview | null>(null)
  const [agendaLoading, setAgendaLoading] = useState(false)
  const [agendaError, setAgendaError] = useState<string | null>(null)
  const [agendaForm, setAgendaForm] = useState({
    title: '',
    description: '',
    item_type: 'deadline' as AgendaItemType,
    priority: 'normal' as AgendaItem['priority'],
    start_at: '',
    due_at: '',
    target_type: '',
    target_id: '',
  })
  const [reminderForm, setReminderForm] = useState<Record<number, { reminder_at: string; message: string }>>({})
  const [documents, setDocuments] = useState<SecretariatDocument[]>([])
  const [selectedDocument, setSelectedDocument] = useState<SecretariatDocument | null>(null)
  const [selectedDocumentVersions, setSelectedDocumentVersions] = useState<SecretariatDocumentVersion[]>([])
  const [documentLoading, setDocumentLoading] = useState(false)
  const [documentError, setDocumentError] = useState<string | null>(null)
  const [documentForm, setDocumentForm] = useState({
    title: '',
    document_type: 'autre' as SecretariatDocumentInput['document_type'],
    category: '',
    source: '',
    description: '',
    keywords: '',
    extracted_text: '',
  })
  const [documentVersionForm, setDocumentVersionForm] = useState({
    file_name: '',
    extracted_text: '',
    summary_text: '',
    synthesis_text: '',
  })

  // Lire le résultat du callback OAuth Google (?google=connected|error&google_error=...)
  useEffect(() => {
    if (kind !== 'courrier') return
    const gParam = searchParams.get('google')
    const gError = searchParams.get('google_error')
    if (gParam === 'connected') {
      setGoogleCallbackMsg({ type: 'success', text: 'Gmail connecté avec succès.' })
      setSearchParams({}, { replace: true })
    } else if (gParam === 'error') {
      const errorMsgs: Record<string, string> = {
        access_denied: 'Accès refusé par Google. Ajoutez votre email dans la liste des utilisateurs test de l\'application OAuth dans Google Cloud Console.',
        redirect_uri_mismatch: 'URI de redirection non autorisée. Ajoutez l\'URI locale dans Google Cloud Console → Identifiants → URI de redirection autorisées.',
      }
      const msg = gError ? (errorMsgs[gError] ?? `Erreur Google : ${gError}`) : 'Connexion Google refusée.'
      setGoogleCallbackMsg({ type: 'error', text: msg })
      setSearchParams({}, { replace: true })
    }
  }, [kind, searchParams, setSearchParams])

  const load = async () => {
    setLoading(true)
    try {
      const [agentRows, taskRows, statusRow] = await Promise.all([
        getSecretariatAgents().catch(() => []),
        kind === 'dashboard' || kind === 'manager' ? getSecretariatTasks().catch(() => []) : Promise.resolve([]),
        kind === 'courrier' ? getGoogleStatus().catch(() => null) : Promise.resolve(null),
      ])
      setAgents(agentRows)
      setTasks(taskRows)
      setGoogleStatus(statusRow)
      if (kind === 'courrier' && statusRow?.connected) {
        await Promise.all([loadEmails(), loadApprovalRows()])
      } else if (kind === 'courrier') {
        setEmails([])
        setSelectedEmail(null)
        setSelectedEmailId(null)
        setApprovals([])
        setEmailAnalyses({})
      }
      if (kind === 'manager') {
        await loadManager()
      }
      if (kind === 'reunion') {
        await Promise.all([loadMeetings(), loadApprovalRows()])
      }
      if (kind === 'agenda') {
        await loadAgenda()
      }
      if (kind === 'documents') {
        await Promise.all([loadDocuments(), loadApprovalRows()])
      }
      if (kind === 'approvals') {
        await loadApprovalRows()
      }
    } finally {
      setLoading(false)
    }
  }

  const apiErrorMessage = (error: unknown, fallback: string) => {
    if (error instanceof ApiError) return error.message
    return fallback
  }

  const loadEmails = async () => {
    setMailLoading(true)
    setMailError(null)
    try {
      const rows = await listCourrierEmails()
      setEmails(rows)
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de charger les mails Gmail.'))
      setEmails([])
    } finally {
      setMailLoading(false)
    }
  }

  const loadManager = async () => {
    setManagerLoading(true)
    setManagerError(null)
    try {
      const [overview, pendingApprovals, workload, actions, approvalRows] = await Promise.all([
        getManagerOverview(),
        getManagerPendingApprovals(),
        getManagerWorkload(),
        getManagerRecommendedActions(),
        listApprovals().catch(() => []),
      ])
      setManagerOverview(overview)
      setManagerApprovals(pendingApprovals)
      setManagerWorkload(workload)
      setManagerActions(actions)
      setApprovals(approvalRows)
    } catch (error) {
      setManagerError(apiErrorMessage(error, 'Impossible de charger le tableau de bord Agent Manager.'))
      setManagerOverview(null)
      setManagerApprovals([])
      setManagerWorkload(null)
      setManagerActions([])
    } finally {
      setManagerLoading(false)
    }
  }

  const loadApprovalRows = async () => {
    setApprovalLoading(true)
    setApprovalError(null)
    try {
      setApprovals(await listApprovals())
    } catch (error) {
      setApprovalError(apiErrorMessage(error, 'Impossible de charger les validations.'))
      setApprovals([])
    } finally {
      setApprovalLoading(false)
    }
  }

  const loadMeetings = async () => {
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      const rows = await listMeetings()
      setMeetings(rows)
      if (selectedMeeting) {
        const detail = await getMeeting(selectedMeeting.id)
        setSelectedMeeting(detail)
        setMeetingNotes(String(detail.metadata_json?.discussion_notes || ''))
      } else if (rows[0]) {
        const detail = await getMeeting(rows[0].id)
        setSelectedMeeting(detail)
        setMeetingNotes(String(detail.metadata_json?.discussion_notes || ''))
      }
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Impossible de charger les réunions.'))
      setMeetings([])
      setSelectedMeeting(null)
    } finally {
      setMeetingLoading(false)
    }
  }

  const loadAgenda = async () => {
    setAgendaLoading(true)
    setAgendaError(null)
    try {
      const [overview, items, reminders] = await Promise.all([
        getAgendaOverview(),
        listAgendaItems(),
        listAgendaReminders({ status: 'pending' }),
      ])
      setAgendaOverview(overview)
      setAgendaItems(items)
      setAgendaReminders(reminders)
    } catch (error) {
      setAgendaError(apiErrorMessage(error, 'Impossible de charger l\'agenda.'))
      setAgendaItems([])
      setAgendaReminders([])
      setAgendaOverview(null)
    } finally {
      setAgendaLoading(false)
    }
  }

  const loadDocuments = async () => {
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      const rows = await listDocuments()
      setDocuments(rows)
      if (selectedDocument) {
        const detail = await getDocument(selectedDocument.id)
        setSelectedDocument(detail)
        setSelectedDocumentVersions(await listDocumentVersions(detail.id))
      } else if (rows[0]) {
        const detail = await getDocument(rows[0].id)
        setSelectedDocument(detail)
        setSelectedDocumentVersions(await listDocumentVersions(detail.id))
      } else {
        setSelectedDocument(null)
        setSelectedDocumentVersions([])
      }
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de charger les documents.'))
      setDocuments([])
      setSelectedDocument(null)
      setSelectedDocumentVersions([])
    } finally {
      setDocumentLoading(false)
    }
  }

  const refreshMeeting = async (meetingId: number) => {
    const detail = await getMeeting(meetingId)
    setSelectedMeeting(detail)
    setMeetingNotes(String(detail.metadata_json?.discussion_notes || ''))
    setMeetings(await listMeetings())
    await loadApprovalRows()
  }

  const handleConnectGoogle = async () => {
    setMailError(null)
    // Ouvrir about:blank MAINTENANT (synchrone, avant tout await)
    // pour contourner le bloqueur de popups du navigateur
    const popup = window.open(
      'about:blank',
      'google_oauth_popup',
      'width=520,height=680,top=80,left=80,scrollbars=yes,resizable=yes',
    )
    try {
      const res = await startGoogleConnect()

      if (!popup || popup.closed) {
        // Popup bloquée malgré tout — fallback redirect
        window.location.href = res.authorization_url
        return
      }

      // Naviguer la popup vers l'URL OAuth
      popup.location.href = res.authorization_url

      const handleMessage = (event: MessageEvent) => {
        if (event.data?.type !== 'google_oauth') return
        window.removeEventListener('message', handleMessage)
        clearInterval(closedPoll)

        if (event.data.google === 'connected') {
          setGoogleCallbackMsg({ type: 'success', text: 'Gmail connecté avec succès.' })
          getGoogleStatus()
            .then(s => {
              setGoogleStatus(s)
              if (s?.connected) {
                void loadEmails()
                void loadApprovalRows()
              }
            })
            .catch(() => null)
        } else {
          const errorMsgs: Record<string, string> = {
            access_denied: 'Accès refusé par Google. Ajoutez votre email dans la liste des utilisateurs test de l\'application OAuth dans Google Cloud Console.',
            redirect_uri_mismatch: 'URI de redirection non autorisée. Ajoutez l\'URI locale dans Google Cloud Console → Identifiants → URI de redirection autorisées.',
          }
          const code: string = event.data.google_error ?? ''
          const msg = code ? (errorMsgs[code] ?? `Erreur Google : ${code}`) : 'Connexion Google refusée.'
          setGoogleCallbackMsg({ type: 'error', text: msg })
        }
      }

      window.addEventListener('message', handleMessage)

      // Nettoyage si l'utilisateur ferme la popup sans finaliser
      const closedPoll = setInterval(() => {
        if (popup.closed) {
          clearInterval(closedPoll)
          window.removeEventListener('message', handleMessage)
        }
      }, 600)
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de démarrer la connexion Google.'))
    }
  }

  const handleDisconnectGoogle = async () => {
    setMailError(null)
    try {
      const status = await disconnectGoogle()
      setGoogleStatus(status)
      setEmails([])
      setSelectedEmail(null)
      setSelectedEmailId(null)
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de déconnecter Google.'))
    }
  }

  const handleSelectEmail = async (messageId: string) => {
    setSelectedEmailId(messageId)
    setSelectedEmail(null)
    setMailError(null)
    try {
      setMailLoading(true)
      setSelectedEmail(await getCourrierEmail(messageId))
      if (!emailAnalyses[messageId]) {
        void autoAnalyzeEmail(messageId)
      }
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de charger le détail du mail.'))
    } finally {
      setMailLoading(false)
    }
  }

  const defaultEmailState = () => ({
    summary: null as MailSummary | null,
    classification: null as MailClassification | null,
    draftResponse: null as MailDraftResponse | null,
    savedDraft: null as MailDraft | null,
    gmailDraftResult: null as GmailDraftCreateResult | null,
    draftSubject: '',
    draftBody: '',
    draftTone: 'administratif',
    draftInstructions: '',
    analysisLoading: false,
  })

  const getEmailState = (id: string) => emailAnalyses[id] ?? defaultEmailState()

  const updateEmailState = (id: string, updates: Partial<ReturnType<typeof defaultEmailState>>) => {
    setEmailAnalyses(prev => ({ ...prev, [id]: { ...(prev[id] ?? defaultEmailState()), ...updates } }))
  }

  const suggestToneFromClassification = (cls: MailClassification): string => {
    if (cls.category === 'juridique') return 'ferme'
    if (['financier', 'forco', 'cotisation'].includes(cls.category)) return 'institutionnel'
    if (cls.recommended_action === 'demander_validation') return 'institutionnel'
    return 'administratif'
  }

  const autoAnalyzeEmail = async (messageId: string) => {
    updateEmailState(messageId, { analysisLoading: true })
    try {
      const [summary, classification] = await Promise.all([
        summarizeCourrierEmail(messageId),
        classifyCourrierEmail(messageId),
      ])
      updateEmailState(messageId, {
        summary,
        classification,
        draftTone: suggestToneFromClassification(classification),
        analysisLoading: false,
      })
    } catch {
      updateEmailState(messageId, { analysisLoading: false })
    }
  }

  const handleSummarizeEmail = async () => {
    if (!selectedEmailId) return
    setAiLoading('summary')
    setMailError(null)
    try {
      updateEmailState(selectedEmailId, { summary: await summarizeCourrierEmail(selectedEmailId) })
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de résumer ce mail.'))
    } finally {
      setAiLoading(null)
    }
  }

  const handleClassifyEmail = async () => {
    if (!selectedEmailId) return
    setAiLoading('classification')
    setMailError(null)
    try {
      const classification = await classifyCourrierEmail(selectedEmailId)
      updateEmailState(selectedEmailId, {
        classification,
        draftTone: suggestToneFromClassification(classification),
      })
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de classifier ce mail.'))
    } finally {
      setAiLoading(null)
    }
  }

  const handlePrepareResponse = async () => {
    if (!selectedEmailId) return
    setAiLoading('draft')
    setMailError(null)
    try {
      const eState = getEmailState(selectedEmailId)
      const draft = await draftCourrierResponse(selectedEmailId, { tone: eState.draftTone, instructions: eState.draftInstructions || null })
      updateEmailState(selectedEmailId, {
        draftResponse: draft,
        draftSubject: draft.subject,
        draftBody: draft.draft_body,
        savedDraft: draft.draft_id ? {
          id: draft.draft_id,
          gmail_message_id: selectedEmailId,
          subject: draft.subject,
          body: draft.draft_body,
          status: 'draft',
          created_at: '',
          updated_at: '',
        } : null,
      })
      await loadApprovalRows()
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de préparer une réponse.'))
    } finally {
      setAiLoading(null)
    }
  }

  const handleSaveDraft = async () => {
    if (!selectedEmailId) return
    setAiLoading('save-draft')
    setMailError(null)
    try {
      const eState = getEmailState(selectedEmailId)
      const saved = await saveCourrierDraft(selectedEmailId, {
        subject: eState.draftSubject,
        body: eState.draftBody,
        ai_metadata_json: { source: 'secretariat_agent_courrier', requires_human_validation: true },
      })
      updateEmailState(selectedEmailId, { savedDraft: saved })
      await loadApprovalRows()
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible d\'enregistrer le brouillon interne.'))
    } finally {
      setAiLoading(null)
    }
  }

  const handleRequestDraftApproval = async () => {
    if (!currentDraft?.id) return
    setAiLoading('request-approval')
    setMailError(null)
    try {
      await createApproval({
        agent_type: 'courrier',
        approval_type: 'mail_draft_approval',
        target_type: 'secretariat_mail_draft',
        target_id: String(currentDraft.id),
        title: `Valider le projet de réponse : ${currentDraft.subject}`,
        description: 'Validation humaine requise avant toute action Gmail future.',
        priority: 'normal',
        metadata_json: { draft_id: currentDraft.id, message_id: currentDraft.gmail_message_id },
      })
      await loadApprovalRows()
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de créer la demande de validation.'))
    } finally {
      setAiLoading(null)
    }
  }

  const goToValidations = () => {
    window.location.href = '/secretariat/validations'
  }

  const handleCreateGmailDraft = async () => {
    if (!currentDraft?.id || !selectedEmailId) return
    setAiLoading('create-gmail-draft')
    setMailError(null)
    try {
      const result = await createGmailDraft(currentDraft.id)
      updateEmailState(selectedEmailId, {
        gmailDraftResult: result,
        savedDraft: {
          ...currentDraft,
          gmail_draft_id: result.gmail_draft_id,
          gmail_thread_id: result.gmail_thread_id || currentDraft.gmail_thread_id,
          status: result.status,
        },
      })
    } catch (error) {
      setMailError(apiErrorMessage(error, 'Impossible de créer le brouillon Gmail.'))
    } finally {
      setAiLoading(null)
    }
  }

  const handleCreateFollowupTask = async () => {
    if (!followupTitle.trim()) return
    setManagerLoading(true)
    setManagerError(null)
    try {
      await createManagerFollowupTask({
        title: followupTitle.trim(),
        description: followupDescription.trim() || null,
        priority: followupPriority,
        target_type: followupTargetType.trim() || null,
        target_id: followupTargetId.trim() || null,
      })
      setFollowupTitle('')
      setFollowupDescription('')
      setFollowupPriority('normal')
      setFollowupTargetType('')
      setFollowupTargetId('')
      await loadManager()
    } catch (error) {
      setManagerError(apiErrorMessage(error, 'Impossible de créer la tâche de suivi.'))
    } finally {
      setManagerLoading(false)
    }
  }

  const handleApprovalDecision = async (approvalId: number, decision: 'approve' | 'reject' | 'cancel') => {
    setApprovalLoading(true)
    setApprovalError(null)
    try {
      const comment = decisionComments[approvalId] || null
      if (decision === 'approve') {
        await approveApproval(approvalId, comment)
      } else if (decision === 'reject') {
        await rejectApproval(approvalId, comment)
      } else {
        await cancelApproval(approvalId)
      }
      setDecisionComments((current) => ({ ...current, [approvalId]: '' }))
      if (kind === 'manager') {
        await loadManager()
      } else {
        await loadApprovalRows()
      }
    } catch (error) {
      setApprovalError(apiErrorMessage(error, 'Impossible de traiter cette validation.'))
    } finally {
      setApprovalLoading(false)
    }
  }

  const handleCreateMeeting = async () => {
    if (!meetingForm.title.trim()) return
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      const detail = await createMeeting({
        title: meetingForm.title.trim(),
        meeting_type: meetingForm.meeting_type.trim() || 'administrative',
        meeting_date: meetingForm.meeting_date || null,
        start_time: meetingForm.start_time || null,
        end_time: meetingForm.end_time || null,
        location: meetingForm.location.trim() || null,
      })
      setMeetingForm({ title: '', meeting_type: 'administrative', meeting_date: '', start_time: '', end_time: '', location: '' })
      setSelectedMeeting(detail)
      setMeetings(await listMeetings())
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Impossible de créer la réunion.'))
    } finally {
      setMeetingLoading(false)
    }
  }

  const handleSelectMeeting = async (meetingId: number) => {
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      await refreshMeeting(meetingId)
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Impossible de charger la réunion.'))
    } finally {
      setMeetingLoading(false)
    }
  }

  const handleAddParticipant = async () => {
    if (!selectedMeeting || !participantForm.name.trim()) return
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      await addMeetingParticipant(selectedMeeting.id, {
        name: participantForm.name.trim(),
        email: participantForm.email.trim() || null,
        role: participantForm.role.trim() || null,
        attendance_status: 'invited',
      })
      setParticipantForm({ name: '', email: '', role: '' })
      await refreshMeeting(selectedMeeting.id)
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Impossible d\'ajouter le participant.'))
    } finally {
      setMeetingLoading(false)
    }
  }

  const handleRemoveParticipant = async (participantId: number) => {
    if (!selectedMeeting) return
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      await removeMeetingParticipant(selectedMeeting.id, participantId)
      await refreshMeeting(selectedMeeting.id)
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Impossible de retirer le participant.'))
    } finally {
      setMeetingLoading(false)
    }
  }

  const handleMeetingAction = async (action: 'agenda' | 'invitation' | 'notes' | 'decisions' | 'actions' | 'minutes' | 'submit') => {
    if (!selectedMeeting) return
    setMeetingLoading(true)
    setMeetingError(null)
    try {
      if (action === 'agenda') await generateMeetingAgenda(selectedMeeting.id, meetingInstructions || null)
      if (action === 'invitation') await generateMeetingInvitation(selectedMeeting.id, meetingInstructions || null)
      if (action === 'notes') await saveMeetingNotes(selectedMeeting.id, meetingNotes)
      if (action === 'decisions') await extractMeetingDecisions(selectedMeeting.id)
      if (action === 'actions') await extractMeetingActionItems(selectedMeeting.id)
      if (action === 'minutes') await generateMeetingMinutes(selectedMeeting.id, meetingInstructions || null)
      if (action === 'submit') await submitMeetingMinutesApproval(selectedMeeting.id)
      await refreshMeeting(selectedMeeting.id)
    } catch (error) {
      setMeetingError(apiErrorMessage(error, 'Action réunion impossible.'))
    } finally {
      setMeetingLoading(false)
    }
  }

  const handleCreateAgendaItem = async () => {
    if (!agendaForm.title.trim()) return
    setAgendaLoading(true)
    setAgendaError(null)
    try {
      await createAgendaItem({
        title: agendaForm.title.trim(),
        description: agendaForm.description.trim() || null,
        item_type: agendaForm.item_type,
        priority: agendaForm.priority,
        start_at: agendaForm.start_at || null,
        due_at: agendaForm.due_at || null,
        target_type: agendaForm.target_type.trim() || null,
        target_id: agendaForm.target_id.trim() || null,
      })
      setAgendaForm({
        title: '',
        description: '',
        item_type: 'deadline',
        priority: 'normal',
        start_at: '',
        due_at: '',
        target_type: '',
        target_id: '',
      })
      await loadAgenda()
    } catch (error) {
      setAgendaError(apiErrorMessage(error, 'Impossible de créer l\'échéance.'))
    } finally {
      setAgendaLoading(false)
    }
  }

  const handleAgendaItemAction = async (itemId: number, action: 'complete' | 'cancel') => {
    setAgendaLoading(true)
    setAgendaError(null)
    try {
      if (action === 'complete') await completeAgendaItem(itemId)
      if (action === 'cancel') await cancelAgendaItem(itemId)
      await loadAgenda()
    } catch (error) {
      setAgendaError(apiErrorMessage(error, 'Action agenda impossible.'))
    } finally {
      setAgendaLoading(false)
    }
  }

  const refreshDocument = async (documentId: number) => {
    const detail = await getDocument(documentId)
    setSelectedDocument(detail)
    setSelectedDocumentVersions(await listDocumentVersions(documentId))
    setDocuments(await listDocuments())
  }

  const handleSelectDocument = async (documentId: number) => {
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await refreshDocument(documentId)
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de charger le document.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleCreateDocument = async () => {
    if (!documentForm.title.trim()) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      const created = await createDocument({
        title: documentForm.title.trim(),
        document_type: documentForm.document_type,
        category: documentForm.category.trim() || null,
        source: documentForm.source.trim() || null,
        description: documentForm.description.trim() || null,
        keywords_json: documentForm.keywords.split(',').map((item) => item.trim()).filter(Boolean),
        extracted_text: documentForm.extracted_text.trim() || null,
      })
      setDocumentForm({
        title: '',
        document_type: 'autre',
        category: '',
        source: '',
        description: '',
        keywords: '',
        extracted_text: '',
      })
      await handleSelectDocument(created.id)
      await loadDocuments()
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de créer le document.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleArchiveDocument = async () => {
    if (!selectedDocument) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await archiveDocument(selectedDocument.id)
      await refreshDocument(selectedDocument.id)
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible d\'archiver le document.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleDocumentSummary = async () => {
    if (!selectedDocument) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await summarizeDocument(selectedDocument.id)
      await refreshDocument(selectedDocument.id)
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de résumer le document.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleDocumentSynthesis = async () => {
    if (!selectedDocument) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await generateDocumentSynthesis(selectedDocument.id)
      await refreshDocument(selectedDocument.id)
      await loadApprovalRows()
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de générer la fiche synthèse.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleSubmitDocumentSynthesis = async () => {
    if (!selectedDocument) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await submitDocumentSynthesisApproval(selectedDocument.id)
      await refreshDocument(selectedDocument.id)
      await loadApprovalRows()
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible de soumettre la fiche synthèse.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleAddDocumentVersion = async () => {
    if (!selectedDocument) return
    if (!documentVersionForm.file_name.trim() && !documentVersionForm.extracted_text.trim() && !documentVersionForm.summary_text.trim() && !documentVersionForm.synthesis_text.trim()) return
    setDocumentLoading(true)
    setDocumentError(null)
    try {
      await addDocumentVersion(selectedDocument.id, {
        file_name: documentVersionForm.file_name.trim() || null,
        extracted_text: documentVersionForm.extracted_text.trim() || null,
        summary_text: documentVersionForm.summary_text.trim() || null,
        synthesis_text: documentVersionForm.synthesis_text.trim() || null,
      })
      setDocumentVersionForm({
        file_name: '',
        extracted_text: '',
        summary_text: '',
        synthesis_text: '',
      })
      await refreshDocument(selectedDocument.id)
    } catch (error) {
      setDocumentError(apiErrorMessage(error, 'Impossible d\'ajouter une version.'))
    } finally {
      setDocumentLoading(false)
    }
  }

  const handleCreateReminder = async (itemId: number) => {
    const form = reminderForm[itemId]
    if (!form?.reminder_at) return
    setAgendaLoading(true)
    setAgendaError(null)
    try {
      await createAgendaReminder(itemId, { reminder_at: form.reminder_at, message: form.message.trim() || null })
      setReminderForm((current) => ({ ...current, [itemId]: { reminder_at: '', message: '' } }))
      await loadAgenda()
    } catch (error) {
      setAgendaError(apiErrorMessage(error, 'Impossible de créer le rappel.'))
    } finally {
      setAgendaLoading(false)
    }
  }

  const handleDismissReminder = async (reminderId: number) => {
    setAgendaLoading(true)
    setAgendaError(null)
    try {
      await dismissAgendaReminder(reminderId)
      await loadAgenda()
    } catch (error) {
      setAgendaError(apiErrorMessage(error, 'Impossible d\'ignorer le rappel.'))
    } finally {
      setAgendaLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [kind])

  const emailState = selectedEmailId ? getEmailState(selectedEmailId) : null
  const mailSummary = emailState?.summary ?? null
  const mailClassification = emailState?.classification ?? null
  const draftResponse = emailState?.draftResponse ?? null
  const currentDraft = emailState?.savedDraft ?? null
  const gmailDraftResult = emailState?.gmailDraftResult ?? null
  const draftSubject = emailState?.draftSubject ?? ''
  const draftBody = emailState?.draftBody ?? ''
  const draftTone = emailState?.draftTone ?? 'administratif'
  const draftInstructions = emailState?.draftInstructions ?? ''
  const emailAnalysisLoading = emailState?.analysisLoading ?? false

  const activeAgents = useMemo(() => agents.filter((agent) => agent.status === 'active').length, [agents])
  const pendingTasks = useMemo(() => tasks.filter((task) => task.status === 'pending' || task.status === 'in_progress').length, [tasks])
  const managerPendingTasks = managerOverview?.tasks.pending ?? 0
  const managerPendingDrafts = managerOverview?.mail_drafts.internal_drafts ?? 0
  const managerPendingApprovals = managerOverview?.approvals.pending ?? approvals.filter((approval) => approval.status === 'pending').length
  const managerGmailDrafts = managerOverview?.mail_drafts.gmail_draft_created ?? 0
  const managerUrgentTasks = managerOverview?.tasks.urgent ?? 0
  const managerDocuments = managerOverview?.documents ?? {
    pending_approval: 0,
    syntheses_to_validate: 0,
    recent_created: [],
  }
  const managerDocumentsPending = managerDocuments.pending_approval
  const managerDocumentsToValidate = managerDocuments.syntheses_to_validate
  const matchingAgent = useMemo(() => agents.find((agent) => agent.type === config.agentType), [agents, config.agentType])
  const currentDraftApproval = useMemo(
    () => currentDraft
      ? approvals.find((approval) =>
          approval.target_type === 'secretariat_mail_draft'
          && approval.target_id === String(currentDraft.id)
          && approval.approval_type === 'mail_draft_approval'
        ) || null
      : null,
    [approvals, currentDraft],
  )
  const selectedMeetingApproval = useMemo(
    () => selectedMeeting
      ? approvals.find((approval) =>
          approval.target_type === 'secretariat_meeting'
          && approval.target_id === String(selectedMeeting.id)
          && approval.approval_type === 'meeting_minutes_validation'
        ) || null
      : null,
    [approvals, selectedMeeting],
  )
  const selectedDocumentApproval = useMemo(
    () => selectedDocument
      ? approvals.find((approval) =>
          approval.target_type === 'secretariat_document'
          && approval.target_id === String(selectedDocument.id)
          && approval.approval_type === 'document_synthesis_validation'
        ) || null
      : null,
    [approvals, selectedDocument],
  )
  const documentPendingApprovalCount = useMemo(
    () => documents.filter((document) => document.status === 'pending_approval').length,
    [documents],
  )
  const documentSynthesesToValidateCount = useMemo(
    () => approvals.filter((approval) =>
      approval.status === 'pending'
      && approval.target_type === 'secretariat_document'
      && approval.approval_type === 'document_synthesis_validation'
    ).length,
    [approvals],
  )
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const tomorrowStart = new Date(todayStart)
  tomorrowStart.setDate(todayStart.getDate() + 1)
  const weekEnd = new Date(todayStart)
  weekEnd.setDate(todayStart.getDate() + 7)
  const activeAgendaItems = agendaItems.filter((item) => item.status !== 'completed' && item.status !== 'cancelled')
  const agendaToday = activeAgendaItems.filter((item) => item.due_at && new Date(item.due_at) >= todayStart && new Date(item.due_at) < tomorrowStart)
  const agendaWeek = activeAgendaItems.filter((item) => item.due_at && new Date(item.due_at) >= todayStart && new Date(item.due_at) < weekEnd)
  const agendaOverdue = activeAgendaItems.filter((item) => item.status === 'overdue' || (!!item.due_at && new Date(item.due_at) < now))
  const agendaUpcoming = activeAgendaItems.filter((item) => item.due_at && new Date(item.due_at) >= tomorrowStart)
  const agendaCompleted = agendaItems.filter((item) => item.status === 'completed')
  const statusText =
    kind === 'manager' && managerOverview
      ? 'Pilotage actif'
      : kind === 'courrier' && googleStatus?.connected
        ? 'Gmail connecté'
        : matchingAgent?.status === 'active'
          ? 'Actif'
          : 'Non configuré'
  const hasGmailComposeScope = !!googleStatus?.scopes?.includes('https://www.googleapis.com/auth/gmail.compose')

  return (
    <div className={styles.page}>
      {/* Agent Manager flottant — disponible sur toutes les vues du secrétariat */}
      <SecretariatAgentChat />

      <AiContentBanner />

      <div className={styles.controlPanel}>
        <div className={styles.topRow}>
          <div>
            <div className={styles.breadcrumb}>Secrétariat / {config.title}</div>
            <h1 className={styles.title}>
              <span className={styles.iconBox}>{config.icon}</span>
              {config.title}
            </h1>
          </div>
          <div className={styles.actions}>
            <BackButton fallback="/secretariat" />
            <button type="button" className={styles.secondaryButton} onClick={() => void load()}>
              <RefreshCw size={15} />
              Actualiser
            </button>
            {kind === 'courrier' && googleStatus?.connected ? (
              <button type="button" className={styles.secondaryButton} onClick={() => void handleDisconnectGoogle()}>
                Déconnecter
              </button>
            ) : kind === 'courrier' ? (
              <button type="button" className={styles.secondaryButton} onClick={() => void handleConnectGoogle()}>
                <Mail size={15} />
                Connecter Gmail
              </button>
            ) : kind === 'manager' ? (
              <button type="button" className={styles.disabledButton} disabled>
                Pilotage actif
              </button>
            ) : kind === 'approvals' ? (
              <button type="button" className={styles.disabledButton} disabled>
                Validation humaine
              </button>
            ) : kind === 'agenda' ? (
              <button type="button" className={styles.disabledButton} disabled>
                Agenda interne
              </button>
            ) : kind === 'dashboard' ? null : (
              <button type="button" className={styles.disabledButton} disabled>
                Phase 2
              </button>
            )}
          </div>
        </div>
      </div>

      <div className={styles.content}>
        {(kind === 'dashboard' || kind === 'manager') && (
          <div className={styles.metrics}>
            <div className={styles.metric}>
              <div className={styles.metricValue}>{agents.length}</div>
              <div className={styles.metricLabel}>Agents déclarés</div>
            </div>
            <div className={styles.metric}>
              <div className={styles.metricValue}>{activeAgents}</div>
              <div className={styles.metricLabel}>Agents actifs</div>
            </div>
            <div className={styles.metric}>
              <div className={styles.metricValue}>{pendingTasks}</div>
              <div className={styles.metricLabel}>Tâches à suivre</div>
            </div>
          </div>
        )}

        <div className={styles.intro}>
          <section className={styles.panel}>
            <p className={styles.description}>{config.description}</p>
          </section>
          <aside className={styles.statusPanel}>
            <span className={styles.statusLabel}>État</span>
            <span className={styles.statusValue}>{kind === 'dashboard' ? 'Base prête' : statusText}</span>
            <span className={styles.pill}>
              {kind === 'courrier' && googleStatus?.email
                ? googleStatus.email
                : kind === 'manager' && managerOverview?.oauth.email
                  ? managerOverview.oauth.email
                : loading
                  ? 'Chargement...'
                  : 'Aucune intégration externe active'}
            </span>
          </aside>
        </div>

        {kind === 'dashboard' && (
          <section style={{ marginBottom: '24px' }}>
            <h2 className={styles.sectionTitle} style={{ marginBottom: '14px' }}>Accéder aux agents</h2>
            <div className={styles.grid}>
              {([
                { title: 'Agent Courrier', desc: 'Courriers Gmail, brouillons assistés IA, validation', path: '/secretariat/courrier', icon: <Mail size={18} /> },
                { title: 'Agent Réunion', desc: 'Préparation, PV, décisions et actions de suivi', path: '/secretariat/reunion', icon: <UsersRound size={18} /> },
                { title: 'Agent Agenda', desc: 'Échéances, rappels et agenda interne', path: '/secretariat/agenda', icon: <CalendarDays size={18} /> },
                { title: 'Agent Documents', desc: 'Classement, résumés et fiches synthèse', path: '/secretariat/documents', icon: <FileText size={18} /> },
                { title: 'Agent Tableau', desc: 'Analyse des dossiers experts-comptables, anomalies, PV Commission', path: '/secretariat/tableau', icon: <Table2 size={18} /> },
                { title: 'Agent Manager', desc: 'Coordination, tâches et pilotage global', path: '/secretariat/manager', icon: <Bot size={18} /> },
                { title: 'Validations', desc: 'Approbation humaine des actions sensibles', path: '/secretariat/validations', icon: <ShieldCheck size={18} /> },
              ] as Array<{ title: string; desc: string; path: string; icon: ReactNode }>).map((agent) => (
                <Link
                  key={agent.path}
                  to={agent.path}
                  className={styles.featureCard}
                  style={{ textDecoration: 'none', display: 'block' }}
                >
                  <div className={styles.featureHeader}>
                    {agent.icon}
                    <span>{agent.title}</span>
                  </div>
                  <p className={styles.featureText}>{agent.desc}</p>
                  <span className={styles.pill}>Ouvrir →</span>
                </Link>
              ))}
            </div>
          </section>
        )}

        {kind === 'approvals' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Demandes d\'approbation</h2>
                <p className={styles.sectionSubtitle}>
                  Les actions sensibles restent bloquées tant qu'une décision humaine n\'est pas enregistrée.
                </p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => void loadApprovalRows()} disabled={approvalLoading}>
                <RefreshCw size={15} />
                Recharger
              </button>
            </div>
            {approvalError && <div className={styles.errorBox}>{approvalError}</div>}
            {approvalLoading && approvals.length === 0 ? (
              <div className={styles.emptyBox}>Chargement des validations...</div>
            ) : approvals.length === 0 ? (
              <div className={styles.emptyBox}>Aucune demande d\'approbation.</div>
            ) : (
              <div className={styles.approvalTable}>
                {approvals.map((approval) => (
                  <article className={styles.approvalRow} key={approval.id}>
                    <div className={styles.approvalMain}>
                      <strong>{approval.title}</strong>
                      <span>{approval.approval_type} · {approval.agent_type} · {formatDate(approval.requested_at)}</span>
                      {approval.description && <p>{approval.description}</p>}
                    </div>
                    <div className={styles.approvalMeta}>
                      <span className={styles.pill}>{approval.priority}</span>
                      <span className={styles.pill}>{approval.status}</span>
                      <span>Demandeur : {approval.requested_by_user_id.slice(0, 8)}</span>
                    </div>
                    <textarea
                      value={decisionComments[approval.id] || ''}
                      onChange={(event) => setDecisionComments((current) => ({ ...current, [approval.id]: event.target.value }))}
                      placeholder="Commentaire de décision"
                      disabled={approval.status !== 'pending'}
                    />
                    <div className={styles.aiActions}>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => void handleApprovalDecision(approval.id, 'approve')}
                        disabled={approval.status !== 'pending' || approvalLoading}
                      >
                        Approuver
                      </button>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => void handleApprovalDecision(approval.id, 'reject')}
                        disabled={approval.status !== 'pending' || approvalLoading}
                      >
                        Rejeter
                      </button>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => void handleApprovalDecision(approval.id, 'cancel')}
                        disabled={approval.status !== 'pending' || approvalLoading}
                      >
                        Annuler
                      </button>
                    </div>
                    {approval.decision_comment && <p className={styles.decisionNote}>Décision : {approval.decision_comment}</p>}
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {kind === 'manager' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Pilotage Secrétariat</h2>
                <p className={styles.sectionSubtitle}>
                  Coordination des tâches, validations humaines et brouillons Gmail créés. Aucun envoi automatique.
                </p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => void loadManager()} disabled={managerLoading}>
                <RefreshCw size={15} />
                Recharger
              </button>
            </div>
            {managerError && <div className={styles.errorBox}>{managerError}</div>}
            {!managerOverview ? (
              <div className={styles.emptyBox}>{managerLoading ? 'Chargement du tableau de bord...' : 'Aucune donnée Manager disponible.'}</div>
            ) : (
              <>
                <div className={styles.metrics}>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerPendingTasks}</div>
                    <div className={styles.metricLabel}>Tâches en attente</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerPendingDrafts}</div>
                    <div className={styles.metricLabel}>Brouillons à approuver</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerPendingApprovals}</div>
                    <div className={styles.metricLabel}>Validations pending</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerGmailDrafts}</div>
                    <div className={styles.metricLabel}>Brouillons Gmail créés</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerUrgentTasks}</div>
                    <div className={styles.metricLabel}>Tâches urgentes</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerDocumentsPending}</div>
                    <div className={styles.metricLabel}>Documents en validation</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerDocumentsToValidate}</div>
                    <div className={styles.metricLabel}>Synthèses à valider</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerOverview.agenda.today}</div>
                    <div className={styles.metricLabel}>Agenda aujourd'hui</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerOverview.agenda.overdue}</div>
                    <div className={styles.metricLabel}>Agenda en retard</div>
                  </div>
                  <div className={styles.metric}>
                    <div className={styles.metricValue}>{managerOverview.agenda.reminders_pending}</div>
                    <div className={styles.metricLabel}>Rappels pending</div>
                  </div>
                </div>
                <div className={styles.managerGrid}>
                  <section className={styles.managerPanel}>
                    <h3>Connexion Gmail</h3>
                    <div className={styles.detailRows}>
                      <span>État</span><strong>{managerOverview.oauth.gmail_connected ? 'Connecté' : 'Non connecté'}</strong>
                      <span>Compte</span><strong>{managerOverview.oauth.email || '-'}</strong>
                      <span>Lecture</span><strong>{managerOverview.oauth.has_gmail_readonly ? 'Autorisé' : 'Non autorisé'}</strong>
                      <span>Brouillons</span><strong>{managerOverview.oauth.has_gmail_compose ? 'Autorisé' : 'Reconnecter Gmail'}</strong>
                    </div>
                    {!managerOverview.oauth.has_gmail_compose && (
                      <div className={styles.warningBox}>Le scope gmail.compose est requis pour créer des brouillons Gmail après validation.</div>
                    )}
                  </section>
                  <section className={styles.managerPanel}>
                    <h3>Actions recommandées</h3>
                    <div className={styles.managerList}>
                      {(managerActions.length ? managerActions : managerOverview.recommended_actions).length === 0 ? (
                        <span className={styles.emptyInline}>Aucune action prioritaire.</span>
                      ) : (
                        (managerActions.length ? managerActions : managerOverview.recommended_actions).map((action) => (
                          <div className={styles.managerItem} key={`${action.type}-${action.target_id}`}>
                            <div>
                              <strong>{action.title}</strong>
                              <span>{action.type}</span>
                            </div>
                            <span className={styles.pill}>{action.priority}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                  <section className={styles.managerPanel}>
                    <h3>Validations en attente</h3>
                    <div className={styles.managerList}>
                      {(approvals.filter((approval) => approval.status === 'pending').length ? approvals.filter((approval) => approval.status === 'pending') : managerApprovals).length === 0 ? (
                        <span className={styles.emptyInline}>Aucun brouillon en attente.</span>
                      ) : (
                        (approvals.filter((approval) => approval.status === 'pending').length ? approvals.filter((approval) => approval.status === 'pending') : managerApprovals).map((approval) => (
                          <div className={styles.managerItem} key={`${(approval as any).type || (approval as any).approval_type}-${approval.id}`}>
                            <div>
                              <strong>{approval.title}</strong>
                              <span>{approval.status} · {formatDate(approval.created_at)} · {(approval as any).type || (approval as any).approval_type}</span>
                            </div>
                            <span className={styles.pill}>#{approval.target_id}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                  <section className={styles.managerPanel}>
                    <h3>Tâches urgentes</h3>
                    <div className={styles.managerList}>
                      {!managerWorkload?.urgent_tasks.length ? (
                        <span className={styles.emptyInline}>Aucune tâche urgente.</span>
                      ) : (
                        managerWorkload.urgent_tasks.map((task) => (
                          <div className={styles.managerItem} key={task.id}>
                            <div>
                              <strong>{task.title}</strong>
                              <span>{task.status} · {formatDate(task.created_at)}</span>
                            </div>
                            <span className={styles.pill}>{task.priority}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </section>
                </div>
                <section className={styles.followupPanel}>
                  <div>
                    <h3>Créer une tâche de suivi</h3>
                    <p>L'Agent Manager crée uniquement une tâche interne. Les validations et actions sensibles restent manuelles.</p>
                  </div>
                  <div className={styles.followupForm}>
                    <input value={followupTitle} onChange={(event) => setFollowupTitle(event.target.value)} placeholder="Titre de la tâche" />
                    <select value={followupPriority} onChange={(event) => setFollowupPriority(event.target.value as typeof followupPriority)}>
                      <option value="low">Faible</option>
                      <option value="normal">Normale</option>
                      <option value="high">Haute</option>
                      <option value="urgent">Urgente</option>
                    </select>
                    <input value={followupTargetType} onChange={(event) => setFollowupTargetType(event.target.value)} placeholder="Type cible optionnel" />
                    <input value={followupTargetId} onChange={(event) => setFollowupTargetId(event.target.value)} placeholder="ID cible optionnel" />
                    <textarea value={followupDescription} onChange={(event) => setFollowupDescription(event.target.value)} placeholder="Description optionnelle" />
                  </div>
                  <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateFollowupTask()} disabled={!followupTitle.trim() || managerLoading}>
                    Créer la tâche
                  </button>
                </section>
              </>
            )}
          </section>
        )}

        {kind === 'agenda' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Agenda interne</h2>
                <p className={styles.sectionSubtitle}>
                  Échéances, rappels et actions administratives visibles dans l\'application. Aucun Google Calendar, Meet ou envoi mail.
                </p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => void loadAgenda()} disabled={agendaLoading}>
                <RefreshCw size={15} />
                Recharger
              </button>
            </div>
            {agendaError && <div className={styles.errorBox}>{agendaError}</div>}
            <div className={styles.metrics}>
              <div className={styles.metric}><div className={styles.metricValue}>{agendaOverview?.today ?? 0}</div><div className={styles.metricLabel}>Aujourd'hui</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{agendaOverview?.this_week ?? 0}</div><div className={styles.metricLabel}>Cette semaine</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{agendaOverview?.overdue ?? 0}</div><div className={styles.metricLabel}>En retard</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{agendaOverview?.urgent ?? 0}</div><div className={styles.metricLabel}>Urgentes</div></div>
            </div>
            <div className={styles.managerGrid}>
              <section className={styles.managerPanel}>
                <h3>Créer une échéance</h3>
                <div className={styles.followupForm}>
                  <input value={agendaForm.title} onChange={(event) => setAgendaForm((current) => ({ ...current, title: event.target.value }))} placeholder="Titre" />
                  <select value={agendaForm.item_type} onChange={(event) => setAgendaForm((current) => ({ ...current, item_type: event.target.value as AgendaItemType }))}>
                    <option value="deadline">Échéance</option>
                    <option value="meeting">Réunion</option>
                    <option value="followup">Relance</option>
                    <option value="approval">Validation</option>
                    <option value="mail">Courrier</option>
                    <option value="document">Document</option>
                    <option value="task">Tâche</option>
                    <option value="other">Autre</option>
                  </select>
                  <select value={agendaForm.priority} onChange={(event) => setAgendaForm((current) => ({ ...current, priority: event.target.value as AgendaItem['priority'] }))}>
                    <option value="low">Faible</option>
                    <option value="normal">Normale</option>
                    <option value="high">Haute</option>
                    <option value="urgent">Urgente</option>
                  </select>
                  <input type="datetime-local" value={agendaForm.start_at} onChange={(event) => setAgendaForm((current) => ({ ...current, start_at: event.target.value }))} />
                  <input type="datetime-local" value={agendaForm.due_at} onChange={(event) => setAgendaForm((current) => ({ ...current, due_at: event.target.value }))} />
                  <div className={styles.sectionSubtitle}>Assignation responsable disponible dans une prochaine version.</div>
                  <input value={agendaForm.target_type} onChange={(event) => setAgendaForm((current) => ({ ...current, target_type: event.target.value }))} placeholder="Type cible optionnel" />
                  <input value={agendaForm.target_id} onChange={(event) => setAgendaForm((current) => ({ ...current, target_id: event.target.value }))} placeholder="ID cible optionnel" />
                  <textarea value={agendaForm.description} onChange={(event) => setAgendaForm((current) => ({ ...current, description: event.target.value }))} placeholder="Description optionnelle" />
                </div>
                <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateAgendaItem()} disabled={!agendaForm.title.trim() || agendaLoading}>
                  Créer échéance
                </button>
              </section>
              <section className={styles.managerPanel}>
                <h3>Rappels internes</h3>
                <div className={styles.managerList}>
                  {agendaReminders.length === 0 ? (
                    <span className={styles.emptyInline}>{agendaLoading ? 'Chargement...' : 'Aucun rappel en attente.'}</span>
                  ) : agendaReminders.map((reminder) => (
                    <div className={styles.managerItem} key={reminder.id}>
                      <div>
                        <strong>{formatDate(reminder.reminder_at)}</strong>
                        <span>{reminder.message || `Échéance #${reminder.agenda_item_id}`}</span>
                      </div>
                      <button type="button" className={styles.secondaryButton} onClick={() => void handleDismissReminder(reminder.id)} disabled={agendaLoading}>
                        Ignorer
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            {[
              ['Aujourd\'hui', agendaToday],
              ['Cette semaine', agendaWeek],
              ['En retard', agendaOverdue],
              ['À venir', agendaUpcoming],
              ['Terminé', agendaCompleted],
            ].map(([title, rows]) => (
              <section className={styles.managerPanel} key={title as string}>
                <h3>{title as string}</h3>
                <div className={styles.managerList}>
                  {(rows as AgendaItem[]).length === 0 ? (
                    <span className={styles.emptyInline}>Aucune échéance.</span>
                  ) : (rows as AgendaItem[]).map((item) => (
                    <div className={styles.managerItem} key={`${title}-${item.id}`}>
                      <div>
                        <strong>{item.title}</strong>
                        <span>{item.item_type} · {item.status} · {item.due_at ? formatDate(item.due_at) : 'Sans date limite'}</span>
                        {item.description && <span>{item.description}</span>}
                      </div>
                      <div className={styles.aiActions}>
                        <span className={styles.pill}>{item.priority}</span>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleAgendaItemAction(item.id, 'complete')} disabled={agendaLoading || item.status === 'completed'}>
                          Terminer
                        </button>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleAgendaItemAction(item.id, 'cancel')} disabled={agendaLoading || item.status === 'cancelled'}>
                          Annuler
                        </button>
                      </div>
                      <div className={styles.followupForm}>
                        <input
                          type="datetime-local"
                          value={reminderForm[item.id]?.reminder_at || ''}
                          onChange={(event) => setReminderForm((current) => ({ ...current, [item.id]: { ...(current[item.id] || { message: '' }), reminder_at: event.target.value } }))}
                        />
                        <input
                          value={reminderForm[item.id]?.message || ''}
                          onChange={(event) => setReminderForm((current) => ({ ...current, [item.id]: { ...(current[item.id] || { reminder_at: '' }), message: event.target.value } }))}
                          placeholder="Message de rappel"
                        />
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateReminder(item.id)} disabled={agendaLoading || !reminderForm[item.id]?.reminder_at}>
                          Créer rappel
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </section>
        )}

        {kind === 'reunion' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Réunions administratives</h2>
                <p className={styles.sectionSubtitle}>
                  Préparation, notes, décisions, tâches et projet de PV. Aucun e-mail ni calendrier n\'est créé.
                </p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => void Promise.all([loadMeetings(), loadApprovalRows()])} disabled={meetingLoading || approvalLoading}>
                <RefreshCw size={15} />
                Recharger
              </button>
            </div>
            {meetingError && <div className={styles.errorBox}>{meetingError}</div>}
            <div className={styles.managerGrid}>
              <section className={styles.managerPanel}>
                <h3>Créer une réunion</h3>
                <div className={styles.followupForm}>
                  <input value={meetingForm.title} onChange={(event) => setMeetingForm((current) => ({ ...current, title: event.target.value }))} placeholder="Titre" />
                  <input value={meetingForm.meeting_type} onChange={(event) => setMeetingForm((current) => ({ ...current, meeting_type: event.target.value }))} placeholder="Type" />
                  <input type="date" value={meetingForm.meeting_date} onChange={(event) => setMeetingForm((current) => ({ ...current, meeting_date: event.target.value }))} />
                  <input type="time" value={meetingForm.start_time} onChange={(event) => setMeetingForm((current) => ({ ...current, start_time: event.target.value }))} />
                  <input type="time" value={meetingForm.end_time} onChange={(event) => setMeetingForm((current) => ({ ...current, end_time: event.target.value }))} />
                  <input value={meetingForm.location} onChange={(event) => setMeetingForm((current) => ({ ...current, location: event.target.value }))} placeholder="Lieu" />
                </div>
                <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateMeeting()} disabled={!meetingForm.title.trim() || meetingLoading}>
                  Créer réunion
                </button>
              </section>
              <section className={styles.managerPanel}>
                <h3>Liste des réunions</h3>
                <div className={styles.managerList}>
                  {meetings.length === 0 ? (
                    <span className={styles.emptyInline}>{meetingLoading ? 'Chargement...' : 'Aucune réunion.'}</span>
                  ) : meetings.map((meeting) => (
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      key={meeting.id}
                      onClick={() => void handleSelectMeeting(meeting.id)}
                    >
                      {meeting.title} · {meeting.status}
                    </button>
                  ))}
                </div>
              </section>
            </div>

            {!selectedMeeting ? (
              <div className={styles.emptyBox}>Sélectionnez ou créez une réunion.</div>
            ) : (
              <div className={styles.managerGrid}>
                <section className={styles.managerPanel}>
                  <h3>{selectedMeeting.title}</h3>
                  <div className={styles.detailRows}>
                    <span>Statut</span><strong>{selectedMeeting.status}</strong>
                    <span>Type</span><strong>{selectedMeeting.meeting_type}</strong>
                    <span>Date</span><strong>{selectedMeeting.meeting_date || '-'}</strong>
                    <span>Heure</span><strong>{selectedMeeting.start_time || '-'} - {selectedMeeting.end_time || '-'}</strong>
                    <span>Lieu</span><strong>{selectedMeeting.location || '-'}</strong>
                    <span>Validation</span><strong>{selectedMeetingApproval?.status || 'Non soumise'}</strong>
                  </div>
                  <div className={styles.warningBox}>Le PV doit être validé via le workflow centralisé avant d'être considéré comme approuvé. Aucun envoi n\'est disponible.</div>
                  {selectedMeeting.status === 'minutes_rejected' && (
                    <div className={styles.errorBox}>Dernier projet de PV rejeté.</div>
                  )}
                </section>

                <section className={styles.managerPanel}>
                  <h3>Participants prévus</h3>
                  <div className={styles.followupForm}>
                    <input value={participantForm.name} onChange={(event) => setParticipantForm((current) => ({ ...current, name: event.target.value }))} placeholder="Nom" />
                    <input value={participantForm.email} onChange={(event) => setParticipantForm((current) => ({ ...current, email: event.target.value }))} placeholder="Email optionnel" />
                    <input value={participantForm.role} onChange={(event) => setParticipantForm((current) => ({ ...current, role: event.target.value }))} placeholder="Rôle optionnel" />
                  </div>
                  <button type="button" className={styles.secondaryButton} onClick={() => void handleAddParticipant()} disabled={!participantForm.name.trim() || meetingLoading}>
                    Ajouter participant
                  </button>
                  <div className={styles.managerList}>
                    {selectedMeeting.participants.length === 0 ? (
                      <span className={styles.emptyInline}>Aucun participant.</span>
                    ) : selectedMeeting.participants.map((participant) => (
                      <div className={styles.managerItem} key={participant.id}>
                        <div>
                          <strong>{participant.name}</strong>
                          <span>{participant.role || '-'} · {participant.attendance_status}</span>
                        </div>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleRemoveParticipant(participant.id)} disabled={meetingLoading}>
                          Retirer
                        </button>
                      </div>
                    ))}
                  </div>
                </section>

                <section className={styles.managerPanel}>
                  <h3>Ordre du jour et invitation</h3>
                  <textarea value={meetingInstructions} onChange={(event) => setMeetingInstructions(event.target.value)} placeholder="Instructions optionnelles pour l'IA" />
                  <div className={styles.aiActions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('agenda')} disabled={meetingLoading}>
                      Générer ordre du jour
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('invitation')} disabled={meetingLoading}>
                      Générer invitation
                    </button>
                  </div>
                  {selectedMeeting.agenda_text && <pre className={styles.mailBody}>{selectedMeeting.agenda_text}</pre>}
                  {selectedMeeting.invitation_draft && <pre className={styles.mailBody}>{selectedMeeting.invitation_draft}</pre>}
                </section>

                <section className={styles.managerPanel}>
                  <h3>Notes et extraction</h3>
                  <textarea value={meetingNotes} onChange={(event) => setMeetingNotes(event.target.value)} placeholder="Points discutés et notes de réunion" />
                  <div className={styles.aiActions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('notes')} disabled={!meetingNotes.trim() || meetingLoading}>
                      Enregistrer notes
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('decisions')} disabled={meetingLoading}>
                      Extraire décisions
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('actions')} disabled={meetingLoading}>
                      Extraire tâches
                    </button>
                  </div>
                </section>

                <section className={styles.managerPanel}>
                  <h3>Décisions</h3>
                  <div className={styles.managerList}>
                    {selectedMeeting.decisions.length === 0 ? (
                      <span className={styles.emptyInline}>Aucune décision extraite.</span>
                    ) : selectedMeeting.decisions.map((decision) => (
                      <div className={styles.managerItem} key={decision.id}>
                        <div>
                          <strong>{decision.decision_text}</strong>
                          <span>{decision.responsible_name || 'Responsable non précisé'} · {decision.due_date || 'Échéance non précisée'}</span>
                        </div>
                        <span className={styles.pill}>{decision.status}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className={styles.managerPanel}>
                  <h3>Tâches de suivi</h3>
                  <div className={styles.managerList}>
                    {selectedMeeting.action_items.length === 0 ? (
                      <span className={styles.emptyInline}>Aucune tâche extraite.</span>
                    ) : selectedMeeting.action_items.map((item) => (
                      <div className={styles.managerItem} key={item.id}>
                        <div>
                          <strong>{item.title}</strong>
                          <span>{item.responsible_name || 'Responsable non précisé'} · {item.due_date || 'Échéance non précisée'}</span>
                        </div>
                        <span className={styles.pill}>{item.priority}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className={styles.managerPanel}>
                  <h3>Projet de PV</h3>
                  <div className={styles.aiActions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('minutes')} disabled={meetingLoading}>
                      Générer projet PV
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleMeetingAction('submit')} disabled={!selectedMeeting.minutes_draft || meetingLoading}>
                      Soumettre à validation
                    </button>
                  </div>
                  {selectedMeeting.minutes_draft && <pre className={styles.mailBody}>{selectedMeeting.minutes_draft}</pre>}
                  {selectedMeeting.status === 'minutes_rejected' && selectedMeeting.approved_minutes && (
                    <div className={styles.warningBox}>PV précédemment approuvé disponible. Le nouveau projet a été rejeté.</div>
                  )}
                  {selectedMeeting.approved_minutes && selectedMeeting.status !== 'minutes_rejected' && <div className={styles.successBox}>PV approuvé disponible.</div>}
                </section>
              </div>
            )}
          </section>
        )}

        {kind === 'documents' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Documents internes</h2>
                <p className={styles.sectionSubtitle}>
                  Classement, résumé et fiche synthèse pour documents accessibles au tenant. Aucun partage externe ni téléchargement public.
                </p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => void loadDocuments()} disabled={documentLoading}>
                <RefreshCw size={15} />
                Recharger
              </button>
            </div>
            {documentError && <div className={styles.errorBox}>{documentError}</div>}
            <div className={styles.metrics}>
              <div className={styles.metric}><div className={styles.metricValue}>{documentPendingApprovalCount}</div><div className={styles.metricLabel}>En validation</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{documentSynthesesToValidateCount}</div><div className={styles.metricLabel}>Synthèses à valider</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{documents.length}</div><div className={styles.metricLabel}>Documents chargés</div></div>
              <div className={styles.metric}><div className={styles.metricValue}>{selectedDocumentVersions.length}</div><div className={styles.metricLabel}>Versions</div></div>
            </div>
            <div className={styles.managerGrid}>
              <section className={styles.managerPanel}>
                <h3>Créer un document</h3>
                <div className={styles.followupForm}>
                  <input value={documentForm.title} onChange={(event) => setDocumentForm((current) => ({ ...current, title: event.target.value }))} placeholder="Titre" />
                  <select value={documentForm.document_type} onChange={(event) => setDocumentForm((current) => ({ ...current, document_type: event.target.value as SecretariatDocumentInput['document_type'] }))}>
                    <option value="courrier">Courrier</option>
                    <option value="PV">PV</option>
                    <option value="rapport">Rapport</option>
                    <option value="note">Note</option>
                    <option value="invitation">Invitation</option>
                    <option value="decision">Décision</option>
                    <option value="budget">Budget</option>
                    <option value="justificatif">Justificatif</option>
                    <option value="autre">Autre</option>
                  </select>
                  <input value={documentForm.category} onChange={(event) => setDocumentForm((current) => ({ ...current, category: event.target.value }))} placeholder="Catégorie" />
                  <input value={documentForm.source} onChange={(event) => setDocumentForm((current) => ({ ...current, source: event.target.value }))} placeholder="Source optionnelle" />
                  <input value={documentForm.keywords} onChange={(event) => setDocumentForm((current) => ({ ...current, keywords: event.target.value }))} placeholder="Mots-clés séparés par virgules" />
                  <textarea value={documentForm.description} onChange={(event) => setDocumentForm((current) => ({ ...current, description: event.target.value }))} placeholder="Description" />
                  <textarea value={documentForm.extracted_text} onChange={(event) => setDocumentForm((current) => ({ ...current, extracted_text: event.target.value }))} placeholder="Texte extrait ou saisi manuellement" />
                </div>
                <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateDocument()} disabled={!documentForm.title.trim() || documentLoading}>
                  Créer document
                </button>
              </section>
              <section className={styles.managerPanel}>
                <h3>Liste des documents</h3>
                <div className={styles.managerList}>
                  {documents.length === 0 ? (
                    <span className={styles.emptyInline}>{documentLoading ? 'Chargement...' : 'Aucun document.'}</span>
                  ) : documents.map((document) => (
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      key={document.id}
                      onClick={() => void handleSelectDocument(document.id)}
                    >
                      {document.title} · {document.document_type} · {document.status}
                    </button>
                  ))}
                </div>
              </section>
            </div>
            {!selectedDocument ? (
              <div className={styles.emptyBox}>Sélectionnez ou créez un document.</div>
            ) : (
              <div className={styles.managerGrid}>
                <section className={styles.managerPanel}>
                  <h3>{selectedDocument.title}</h3>
                  <div className={styles.detailRows}>
                    <span>Type</span><strong>{selectedDocument.document_type}</strong>
                    <span>Catégorie</span><strong>{selectedDocument.category || '-'}</strong>
                    <span>Statut</span><strong>{selectedDocument.status}</strong>
                    <span>Source</span><strong>{selectedDocument.source || '-'}</strong>
                    <span>Fichier attaché</span><strong>{selectedDocument.has_file ? 'Oui' : 'Non'}</strong>
                    <span>Nom du fichier</span><strong>{selectedDocument.file_name || '-'}</strong>
                    <span>Type MIME</span><strong>{selectedDocument.mime_type || '-'}</strong>
                    <span>Taille</span><strong>{selectedDocument.file_size != null ? `${selectedDocument.file_size} octets` : '-'}</strong>
                    <span>Validation</span><strong>{selectedDocumentApproval?.status || 'Non soumise'}</strong>
                  </div>
                  <div className={styles.warningBox}>Le résumé et la synthèse sont des aides de travail. La validation finale passe par le workflow centralisé.</div>
                  {selectedDocument.status === 'rejected' && <div className={styles.errorBox}>Dernière synthèse rejetée.</div>}
                </section>
                <section className={styles.managerPanel}>
                  <h3>Résumé et synthèse</h3>
                  <div className={styles.aiActions}>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleDocumentSummary()} disabled={documentLoading}>
                      Résumer
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleDocumentSynthesis()} disabled={documentLoading}>
                      Générer fiche synthèse
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleSubmitDocumentSynthesis()} disabled={!selectedDocument.synthesis_text || documentLoading}>
                      Soumettre à validation
                    </button>
                    <button type="button" className={styles.secondaryButton} onClick={() => void handleArchiveDocument()} disabled={documentLoading || selectedDocument.status === 'archived'}>
                      Archiver
                    </button>
                  </div>
                  {selectedDocument.summary_text && <pre className={styles.mailBody}>{selectedDocument.summary_text}</pre>}
                  {selectedDocument.synthesis_text && <pre className={styles.mailBody}>{selectedDocument.synthesis_text}</pre>}
                </section>
                <section className={styles.managerPanel}>
                  <h3>Ajouter une version</h3>
                  <div className={styles.followupForm}>
                    <input value={documentVersionForm.file_name} onChange={(event) => setDocumentVersionForm((current) => ({ ...current, file_name: event.target.value }))} placeholder="Nom du fichier" />
                    <textarea value={documentVersionForm.extracted_text} onChange={(event) => setDocumentVersionForm((current) => ({ ...current, extracted_text: event.target.value }))} placeholder="Texte extrait" />
                    <textarea value={documentVersionForm.summary_text} onChange={(event) => setDocumentVersionForm((current) => ({ ...current, summary_text: event.target.value }))} placeholder="Résumé" />
                    <textarea value={documentVersionForm.synthesis_text} onChange={(event) => setDocumentVersionForm((current) => ({ ...current, synthesis_text: event.target.value }))} placeholder="Fiche synthèse" />
                  </div>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAddDocumentVersion()}
                    disabled={
                      documentLoading
                      || (!documentVersionForm.file_name.trim()
                        && !documentVersionForm.extracted_text.trim()
                        && !documentVersionForm.summary_text.trim()
                        && !documentVersionForm.synthesis_text.trim())
                    }
                  >
                    Ajouter version
                  </button>
                </section>
                <section className={styles.managerPanel}>
                  <h3>Versions</h3>
                  <div className={styles.managerList}>
                    {selectedDocumentVersions.length === 0 ? (
                      <span className={styles.emptyInline}>Aucune version enregistrée.</span>
                    ) : selectedDocumentVersions.map((version) => (
                      <div className={styles.managerItem} key={version.id}>
                        <div>
                          <strong>Version {version.version_number}</strong>
                          <span>{formatDate(version.created_at)} · {version.file_name || 'Sans fichier'}</span>
                        </div>
                        <span className={styles.pill}># {version.id}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </section>
        )}

        {kind === 'courrier' && (
          <section className={styles.mailWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Courriers récents</h2>
                <p className={styles.sectionSubtitle}>
                  Lecture Gmail, réponse interne et brouillon Gmail possible après approbation centralisée. Aucun envoi disponible.
                </p>
              </div>
              {googleStatus?.connected && (
                <button type="button" className={styles.secondaryButton} onClick={() => void loadEmails()}>
                  <RefreshCw size={15} />
                  Recharger les mails
                </button>
              )}
            </div>
            {googleCallbackMsg && (
              <div className={googleCallbackMsg.type === 'success' ? styles.successBox : styles.errorBox}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 12 }}>
                <span style={{ fontSize: 16 }}>{googleCallbackMsg.type === 'success' ? '✓' : '⚠'}</span>
                <span>{googleCallbackMsg.text}</span>
                <button onClick={() => setGoogleCallbackMsg(null)}
                  style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'inherit' }}>✕</button>
              </div>
            )}
            {mailError && <div className={styles.errorBox}>{mailError}</div>}
            {!googleStatus?.connected ? (
              <div className={styles.emptyBox}>
                Gmail n\'est pas connecté. Utilisez le bouton “Connecter Gmail” pour autoriser la lecture seule des mails récents.
              </div>
            ) : (
              <>
              {!hasGmailComposeScope && (
                <div className={styles.warningBox}>
                  Le compte Google est connecté en lecture seule. Reconnectez Gmail pour autoriser la création de brouillons avec le scope gmail.compose.
                </div>
              )}
              <div className={styles.mailGrid}>
                <div className={styles.mailList}>
                  {mailLoading && emails.length === 0 ? (
                    <div className={styles.emptyBox}>Chargement des mails...</div>
                  ) : emails.length === 0 ? (
                    <div className={styles.emptyBox}>Aucun mail récent à afficher.</div>
                  ) : (
                    emails.map((email) => (
                      <button
                        type="button"
                        key={email.id}
                        className={`${styles.mailItem} ${selectedEmailId === email.id ? styles.mailItemActive : ''}`}
                        onClick={() => void handleSelectEmail(email.id)}
                      >
                        <span className={styles.mailMeta}>
                          <strong>{email.from || 'Expéditeur inconnu'}</strong>
                          <span className={styles.mailBadges}>
                            {emailAnalyses[email.id]?.analysisLoading && (
                              <span className={styles.analysisDot} title="Analyse en cours" />
                            )}
                            {emailAnalyses[email.id]?.classification && (
                              <span className={`${styles.priorityBadge} ${styles[`priority_${emailAnalyses[email.id].classification!.priority}`]}`}>
                                {emailAnalyses[email.id].classification!.priority}
                              </span>
                            )}
                            {emailAnalyses[email.id]?.classification && (
                              <span className={styles.categoryBadge}>
                                {emailAnalyses[email.id].classification!.category}
                              </span>
                            )}
                          </span>
                          <span>{formatDate(email.received_at)}</span>
                        </span>
                        <span className={styles.mailSubject}>
                          {email.subject || '(Sans objet)'}
                          {email.has_attachments && <Paperclip size={14} />}
                        </span>
                        <span className={styles.mailSnippet}>{email.snippet || 'Aucun extrait disponible.'}</span>
                        <span className={styles.mailLabels}>{(email.labels || []).slice(0, 3).join(' · ')}</span>
                      </button>
                    ))
                  )}
                </div>
                <div className={styles.mailDetail}>
                  {!selectedEmailId ? (
                    <div className={styles.emptyBox}>Sélectionnez un mail pour consulter son détail.</div>
                  ) : !selectedEmail ? (
                    <div className={styles.emptyBox}>Chargement du détail...</div>
                  ) : (
                    <>
                      <div className={styles.detailHeader}>
                        <span className={styles.pill}>Lecture seule</span>
                        <h2>{selectedEmail.subject || '(Sans objet)'}</h2>
                        <p>{selectedEmail.from || 'Expéditeur inconnu'}</p>
                      </div>
                      <div className={styles.detailRows}>
                        <span>À</span><strong>{selectedEmail.to || '-'}</strong>
                        <span>Cc</span><strong>{selectedEmail.cc || '-'}</strong>
                        <span>Date</span><strong>{selectedEmail.date || '-'}</strong>
                      </div>
                      <pre className={styles.mailBody}>{selectedEmail.body || selectedEmail.snippet || 'Aucun contenu texte disponible.'}</pre>
                      {selectedEmail.attachments.length > 0 && (
                        <div className={styles.attachments}>
                          <strong>Pièces jointes</strong>
                          {selectedEmail.attachments.map((attachment) => (
                            <span key={attachment.attachment_id || attachment.filename}>
                              <Paperclip size={14} />
                              {attachment.filename || 'Pièce jointe'} · metadata uniquement
                            </span>
                          ))}
                        </div>
                      )}
                      {emailAnalysisLoading && (
                        <div className={styles.analysisBar}>
                          <span className={styles.analysisDot} />
                          Analyse automatique en cours (résumé + classification)…
                        </div>
                      )}
                      {mailClassification && !emailAnalysisLoading && (
                        <div className={styles.suggestionBar}>
                          <span className={`${styles.priorityBadge} ${styles[`priority_${mailClassification.priority}`]}`}>
                            {mailClassification.priority}
                          </span>
                          <span className={styles.categoryBadge}>{mailClassification.category}</span>
                          <span className={styles.actionBadge}>{mailClassification.recommended_action}</span>
                          <span className={styles.confidencePill}>{Math.round(mailClassification.confidence * 100)}% confiance</span>
                        </div>
                      )}
                      <div className={styles.aiActions}>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleSummarizeEmail()} disabled={!!aiLoading || emailAnalysisLoading}>
                          Résumer
                        </button>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleClassifyEmail()} disabled={!!aiLoading || emailAnalysisLoading}>
                          Reclassifier
                        </button>
                        <button type="button" className={styles.secondaryButton} onClick={() => void handlePrepareResponse()} disabled={!!aiLoading || emailAnalysisLoading}>
                          Préparer une réponse
                        </button>
                      </div>
                      {aiLoading && <div className={styles.emptyBox}>Analyse en cours...</div>}
                      <div className={styles.aiGrid}>
                        {mailSummary && (
                          <section className={styles.aiPanel}>
                            <h3>Résumé</h3>
                            <p>{mailSummary.summary}</p>
                            <strong>Points clés</strong>
                            <ul>
                              {mailSummary.key_points.map((point) => <li key={point}>{point}</li>)}
                            </ul>
                            <span className={styles.pill}>Priorité suggérée : {mailSummary.suggested_priority}</span>
                            <span className={styles.pill}>{mailSummary.requires_response ? 'Réponse recommandée' : 'Réponse non obligatoire'}</span>
                            {mailSummary.detected_request && <p>Demande détectée : {mailSummary.detected_request}</p>}
                          </section>
                        )}
                        {mailClassification && (
                          <section className={styles.aiPanel}>
                            <h3>Classification</h3>
                            <div className={styles.detailRows}>
                              <span>Catégorie</span><strong>{mailClassification.category}</strong>
                              <span>Priorité</span><strong>{mailClassification.priority}</strong>
                              <span>Confiance</span><strong>{Math.round(mailClassification.confidence * 100)}%</strong>
                              <span>Action</span><strong>{mailClassification.recommended_action}</strong>
                            </div>
                            <p>{mailClassification.reason}</p>
                          </section>
                        )}
                      </div>
                      <section className={styles.draftPanel}>
                        <div>
                          <h3>Projet de réponse interne</h3>
                          <p>Brouillon Gmail possible après approbation centralisée. Aucun envoi disponible.</p>
                        </div>
                        <div className={styles.draftControls}>
                          <label>
                            Ton
                            <select value={draftTone} onChange={(event) => selectedEmailId && updateEmailState(selectedEmailId, { draftTone: event.target.value })}>
                              <option value="administratif">Administratif</option>
                              <option value="cordial">Cordial</option>
                              <option value="ferme">Ferme</option>
                              <option value="institutionnel">Institutionnel</option>
                            </select>
                          </label>
                          <label>
                            Instructions
                            <input value={draftInstructions} onChange={(event) => selectedEmailId && updateEmailState(selectedEmailId, { draftInstructions: event.target.value })} placeholder="Précisions optionnelles" />
                          </label>
                        </div>
                        <input className={styles.draftSubject} value={draftSubject} onChange={(event) => selectedEmailId && updateEmailState(selectedEmailId, { draftSubject: event.target.value })} placeholder="Objet du projet de réponse" />
                        <textarea className={styles.draftBody} value={draftBody} onChange={(event) => selectedEmailId && updateEmailState(selectedEmailId, { draftBody: event.target.value })} placeholder="Le projet de réponse généré apparaîtra ici." />
                        <div className={styles.aiActions}>
                          <button type="button" className={styles.secondaryButton} onClick={() => void handleSaveDraft()} disabled={!draftSubject || !draftBody || !!aiLoading}>
                            Enregistrer le brouillon interne
                          </button>
                          <button type="button" className={styles.secondaryButton} onClick={() => void handleRequestDraftApproval()} disabled={!currentDraft?.id || !!currentDraftApproval || !!aiLoading}>
                            Demander validation
                          </button>
                          <button type="button" className={styles.secondaryButton} onClick={goToValidations} disabled={!currentDraftApproval}>
                            Voir validations
                          </button>
                          <button
                            type="button"
                            className={styles.secondaryButton}
                            onClick={() => void handleCreateGmailDraft()}
                            disabled={!currentDraft?.id || currentDraft.status !== 'approved' || !hasGmailComposeScope || !!aiLoading}
                          >
                            Créer le brouillon dans Gmail
                          </button>
                          <button type="button" className={styles.disabledButton} disabled>
                            Envoyer non disponible
                          </button>
                          {currentDraft && <span className={styles.pill}>Statut : {currentDraft.status}</span>}
                        </div>
                        <div className={styles.warningBox}>
                          La validation se fait via le workflow centralisé.
                          {currentDraftApproval
                            ? ` Statut validation : ${currentDraftApproval.status}.`
                            : currentDraft?.id
                              ? ' Aucune demande active affichée pour ce brouillon.'
                              : ''}
                        </div>
                        {draftResponse?.requires_human_validation && <span className={styles.pill}>Validation humaine obligatoire</span>}
                        {gmailDraftResult && <div className={styles.successBox}>{gmailDraftResult.message}</div>}
                      </section>
                    </>
                  )}
                </div>
              </div>
              </>
            )}
          </section>
        )}

        {kind !== 'dashboard' && (
          <div className={styles.grid}>
            {config.features.map((feature) => (
              <article className={styles.featureCard} key={feature.title}>
                <div className={styles.featureHeader}>
                  {feature.icon}
                  <span>{feature.title}</span>
                </div>
                <p className={styles.featureText}>{feature.text}</p>
                <span className={styles.pill}>{feature.status || 'Prévu'}</span>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function formatDate(value?: string | null): string {
  if (!value) return ''
  try {
    return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
  } catch {
    return value
  }
}
