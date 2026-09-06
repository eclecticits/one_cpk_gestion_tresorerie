import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  BarChart3,
  Car,
  CheckCircle,
  ChevronDown,
  Download,
  Eye,
  FileSearch,
  FileText,
  Paperclip,
  PlusCircle,
  Printer,
  Send,
  ShieldCheck,
  TrendingDown,
  Wallet,
  X,
  XCircle,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { getService, getServiceMembers } from '../api/services'
import BackButton from '../components/BackButton'
import BudgetGauge from '../components/ServicePortal/BudgetGauge'
import styles from './ServicePortal.module.css'
import { isAssistantMember, isLeadershipMember, resolveMemberFunctionLabel } from '../utils/serviceMemberFunctions'
import type { CommissionMember } from '../types'
import { getStatusMeta } from '../utils/statusMapper'
import { usePermissions } from '../hooks/usePermissions'
import PlanDecaissement from '../components/PlanDecaissement'
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'action.
// Les trois bibliotheques ci-dessous etaient importees statiquement en tete de
// fichier, ce qui tirait jspdf (135 ko gz) et xlsx (142 ko gz) dans le chunk de
// la route : 95 % du poids telecharge pour ouvrir un ecran qui n'exporte rien.
let _xlsxPromise: Promise<typeof import('xlsx')> | null = null
function loadXlsx() {
  if (!_xlsxPromise) _xlsxPromise = import('xlsx')
  return _xlsxPromise
}
let _jsPdfPromise: Promise<typeof import('jspdf')> | null = null
function loadJsPdf() {
  if (!_jsPdfPromise) _jsPdfPromise = import('jspdf')
  return _jsPdfPromise
}
let _autoTablePromise: Promise<typeof import('jspdf-autotable')> | null = null
function loadAutoTable() {
  if (!_autoTablePromise) _autoTablePromise = import('jspdf-autotable')
  return _autoTablePromise
}
type PdfGeneratorModule = typeof import('../utils/pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('../utils/pdfGenerator')
  return _pdfGeneratorModulePromise
}
const generateSingleRequisitionPDF: PdfGeneratorModule['generateSingleRequisitionPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateSingleRequisitionPDF(...args)
}
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import type { Service } from '../types'

type ServiceSummary = {
  annee: number | null
  total: number
  total_depenses?: number
  total_recettes?: number
  consomme: number
  en_attente: number
  disponible: number
}

type RequisitionItem = {
  id: string
  numero_requisition: string
  objet: string
  montant_total: number
  status: string
  service_id?: number | null
  type_requisition?: string | null
  dossier_id?: string | null
  examen_status?: string | null
  signed_by_id?: string | null
  signed_at?: string | null
  lignes_count?: number | null
  created_at: string
  updated_at?: string | null
  created_by?: string | null
  decaissement_progressif?: boolean | null
  lignes?: any[] | null
  motif_rejet?: string | null
  annexe?: {
    id: string
    filename?: string | null
    file_type?: string | null
    upload_date?: string | null
  } | null
  demandeur?: { id: string; prenom?: string | null; nom?: string | null } | null
}

type TransportItem = {
  id: string
  numero_remboursement: string
  reference_numero?: string | null
  nature_reunion: string
  lieu: string
  date_reunion: string
  montant_total: number
  status?: string | null
  statut?: string | null
  requisition_id?: string | null
  requisition?: RequisitionItem | null
}

const REJECTION_ALERT_WINDOW_MS = 48 * 60 * 60 * 1000

type BudgetLine = {
  id: number
  code: string
  libelle: string
  montant_prevu: string | number
  montant_disponible?: string | number
}

type BudgetMetrics = {
  allocated: number
  requested: number
  balance: number
}

export default function ServicePortal() {
  const { user } = useAuth()
  const { hasPermission, isAdmin } = usePermissions()
  const { serviceId } = useParams()
  const navigate = useNavigate()
  const [summary, setSummary] = useState<ServiceSummary | null>(null)
  const [requisitions, setRequisitions] = useState<RequisitionItem[]>([])
  const [transports, setTransports] = useState<TransportItem[]>([])
  const [rubriques, setRubriques] = useState<BudgetLine[]>([])
  const [members, setMembers] = useState<CommissionMember[]>([])
  const [serviceInfo, setServiceInfo] = useState<Service | null>(null)
  const [serviceLabel, setServiceLabel] = useState<string>('Mon unité opérationnelle')
  const [loading, setLoading] = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [submittingExamenId, setSubmittingExamenId] = useState<string | null>(null)
  const [signError, setSignError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [commissionError, setCommissionError] = useState<string | null>(null)
  const [reqPage, setReqPage] = useState(1)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRequisition, setSelectedRequisition] = useState<RequisitionItem | null>(null)
  const [selectedLignes, setSelectedLignes] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [selectedRejectMotif, setSelectedRejectMotif] = useState<string>('')
  const [selectedRejectTitle, setSelectedRejectTitle] = useState<string>('')
  const [documentFilter, setDocumentFilter] = useState<'all' | 'requisitions' | 'transports'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [budgetSearch, setBudgetSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [sortField, setSortField] = useState<'date' | 'amount'>('date')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  // Le bandeau de graphiques occupe ~180 px au-dessus du tableau de travail.
  // Il reste ouvert par defaut, mais son repli est memorise d'une visite a
  // l'autre : c'est l'agent qui decide de ce qu'il veut voir chaque jour.
  const [insightsOpen, setInsightsOpen] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('servicePortal.insights') !== 'closed'
    } catch {
      return true
    }
  })

  const toggleInsights = () => {
    setInsightsOpen((open) => {
      const next = !open
      try {
        window.localStorage.setItem('servicePortal.insights', next ? 'open' : 'closed')
      } catch {
        /* Navigation privee : le repli reste valable pour la session. */
      }
      return next
    })
  }

  const isRejectedRecently = useCallback((status: unknown, rejectedAt?: string | null) => {
    const normalizedStatus = String(status || '').toUpperCase()
    if (!normalizedStatus.includes('REJET')) return false
    if (!rejectedAt) return false
    const rejectedTs = new Date(rejectedAt).getTime()
    if (Number.isNaN(rejectedTs)) return false
    return Date.now() - rejectedTs <= REJECTION_ALERT_WINDOW_MS
  }, [])

  const rejectedCount = useMemo(() => {
    const rejectedRequisitions = requisitions.filter((req) =>
      isRejectedRecently(req.status, req.updated_at)
    ).length
    const rejectedTransports = transports.filter((transport) =>
      isRejectedRecently(getTransportStatus(transport), transport.requisition?.updated_at)
    ).length
    return rejectedRequisitions + rejectedTransports
  }, [requisitions, transports, isRejectedRecently])

  const activeServiceId = useMemo(() => {
    if (serviceId) {
      const parsed = Number(serviceId)
      return Number.isFinite(parsed) ? parsed : null
    }
    const ids =
      user?.service_ids && user.service_ids.length > 0
        ? user.service_ids
        : user?.service_id
          ? [user.service_id]
          : []
    return ids.length === 1 ? ids[0] : null
  }, [serviceId, user?.service_id, user?.service_ids])

  const loadData = useCallback(async () => {
    if (!activeServiceId) return
    setLoading(true)
    try {
      const serviceRes = await getService(activeServiceId)
      const [summaryResult, reqResult, transportResult, rubResult, membersResult] = await Promise.allSettled([
        apiRequest<ServiceSummary>('GET', '/budget/summary/mine', { params: { service_id: activeServiceId } }),
        apiRequest<RequisitionItem[]>('GET', '/requisitions/mine', { params: { service_id: activeServiceId, include: 'demandeur,validateur,approbateur,examinateur,caissier,annexe' } }),
        apiRequest<TransportItem[]>('GET', '/remboursements-transport', { params: { include: 'requisition', limit: 200, offset: 0 } }),
        apiRequest<{ lignes: BudgetLine[] }>('GET', '/budget/lines/autorisees', { params: { active: true, type: 'DEPENSE', service_id: activeServiceId } }),
        getServiceMembers(activeServiceId),
      ])

      const summaryRes = summaryResult.status === 'fulfilled' ? summaryResult.value : null
      const reqRes = reqResult.status === 'fulfilled' ? reqResult.value : []
      const transportRes = transportResult.status === 'fulfilled' ? transportResult.value : []
      const rubRes = rubResult.status === 'fulfilled' ? rubResult.value : { lignes: [] }
      const membersRes = membersResult.status === 'fulfilled' ? membersResult.value : []

      setSummary(summaryRes)
      const safeReqs = Array.isArray(reqRes) ? reqRes : []
      const filteredReqs = safeReqs.filter((req: any) => {
        const reqServiceId = req?.service_id ?? req?.service?.id ?? req?.serviceId
        const isTransportBackingReq = String(req?.type_requisition || '').toLowerCase() === 'remboursement_transport'
        return reqServiceId ? String(reqServiceId) === String(activeServiceId) && !isTransportBackingReq : false
      })
      const safeTransports = Array.isArray(transportRes) ? transportRes : []
      const filteredTransports = safeTransports.filter((transport: any) => {
        const reqServiceId = transport?.requisition?.service_id ?? transport?.requisition?.service?.id
        return reqServiceId ? String(reqServiceId) === String(activeServiceId) : false
      })
      setRequisitions(filteredReqs)
      setTransports(filteredTransports)
      setRubriques(Array.isArray(rubRes?.lignes) ? rubRes.lignes : [])
      setServiceInfo(serviceRes)
      setServiceLabel(`${serviceRes.code} · ${serviceRes.libelle}`)
      setMembers(Array.isArray(membersRes) ? membersRes : [])
      setCommissionError(null)
    } catch (error: any) {
      const status = error?.status ?? error?.response?.status
      if (status === 403) {
        setCommissionError("Accès refusé : vous n'êtes pas membre de cette unité opérationnelle.")
      } else if (status === 404) {
        setCommissionError("Unité opérationnelle introuvable ou supprimée.")
      } else {
        setCommissionError("Impossible de charger les données de l'unité opérationnelle.")
      }
      setSummary(null)
      setRequisitions([])
      setTransports([])
      setRubriques([])
      setMembers([])
      setServiceInfo(null)
    } finally {
      setLoading(false)
    }
  }, [activeServiceId])

  useEffect(() => {
    loadData()
  }, [loadData])

  const totalDepenses = summary?.total_depenses ?? summary?.total ?? 0
  const consomme = summary?.consomme ?? 0
  const enAttente = summary?.en_attente ?? 0
  const disponible = summary?.disponible ?? 0
  const progress = totalDepenses > 0 ? Math.min(100, Math.round((consomme / totalDepenses) * 100)) : 0
  const engagedProgress = totalDepenses > 0 ? Math.min(100, Math.round((enAttente / totalDepenses) * 100)) : 0
  const availableProgress = totalDepenses > 0 ? Math.min(100, Math.round((disponible / totalDepenses) * 100)) : 0
  const leadership = members.filter((m) => isLeadershipMember(m) && !isAssistantMember(m))
  const assistants = members.filter((m) => isAssistantMember(m))
  const experts = members.filter((m) => !isLeadershipMember(m) && !isAssistantMember(m))
  const currentMember = useMemo(
    () => members.find((m) => (m.user_id ? String(m.user_id) === String(user?.id) : false)) || null,
    [members, user?.id]
  )
  const isAdminUser = user?.role === 'admin'
  const canSign = isAdminUser || Boolean(currentMember?.is_signer)
  const tenantName = user?.organisation_name || user?.organisation_slug || 'Organisation'
  const budgetExercise = summary?.annee ? String(summary.annee) : '—'
  const serviceResponsible = serviceInfo?.responsable
    ? `${serviceInfo.responsable.prenom || ''} ${serviceInfo.responsable.nom || ''}`.trim() || serviceInfo.responsable.email || 'Responsable'
    : currentMember?.full_name || 'Aucun responsable assigné'

  const normalizeStatusValue = (value: any) => {
    const upper = String(value || '').toUpperCase()
    if (upper === 'VALIDEE' || upper === 'VALIDE_TECHNIQUE') return 'AUTORISEE'
    if (upper === 'DECAISSE') return 'PAYEE'
    if (upper === 'REJETTE') return 'REJETEE'
    return upper
  }

  const statusOptions = [
    { value: '', label: 'Tous les statuts' },
    { value: 'BROUILLON', label: 'Brouillon' },
    { value: 'SIGNEE_SERVICE', label: 'Signé service' },
    { value: 'EN_ATTENTE', label: 'En attente validation 1/2' },
    { value: 'AUTORISEE', label: 'Validation 1/2' },
    { value: 'APPROUVEE', label: 'Validation 2/2' },
    { value: 'PAYEE', label: 'Payé' },
    { value: 'REJETEE', label: 'Rejeté' },
  ]

  const dateInRange = (rawDate: string | null | undefined) => {
    if (!dateDebut && !dateFin) return true
    if (!rawDate) return false
    const value = new Date(rawDate)
    const start = dateDebut ? new Date(dateDebut) : null
    const end = dateFin ? new Date(dateFin) : null
    if (start) start.setHours(0, 0, 0, 0)
    if (end) end.setHours(23, 59, 59, 999)
    return (!start || value >= start) && (!end || value <= end)
  }

  const sortByCurrent = <T,>(items: T[], getDate: (item: T) => string | undefined, getAmount: (item: T) => number) => {
    return [...items].sort((a, b) => {
      const aValue = sortField === 'date' ? new Date(getDate(a) || 0).getTime() : getAmount(a)
      const bValue = sortField === 'date' ? new Date(getDate(b) || 0).getTime() : getAmount(b)
      return sortDirection === 'asc' ? aValue - bValue : bValue - aValue
    })
  }

  const textValue = (value: unknown) => String(value || '').toLowerCase()

  function getTransportStatus(transport: TransportItem) {
    return transport.requisition?.status || transport.status || transport.statut || 'BROUILLON'
  }

  const transportPendingCount = transports.filter((transport) => {
    const status = normalizeStatusValue(getTransportStatus(transport))
    return status !== 'PAYEE' && !status.includes('REJET')
  }).length

  const toAmount = (value: unknown) => {
    const numeric = Number(value ?? 0)
    return Number.isFinite(numeric) ? numeric : 0
  }

  const getBudgetMetrics = (
    lines: Array<{
      budget_poste_id?: number | null
      montant_total?: number | string
      montant_alloue_snapshot?: number | string | null
      montant_disponible_snapshot?: number | string | null
    }> = [],
    requestedAmount?: number | string
  ): BudgetMetrics => {
    const snapshotAllocated = lines.reduce((sum, line) => sum + toAmount(line.montant_alloue_snapshot), 0)
    const snapshotBalance = lines.reduce((sum, line) => sum + toAmount(line.montant_disponible_snapshot), 0)
    const uniqueBudgetIds = [...new Set(lines.map((line) => line.budget_poste_id).filter((id): id is number => typeof id === 'number'))]
    const matchedRubriques = uniqueBudgetIds
      .map((budgetId) => rubriques.find((rubrique) => rubrique.id === budgetId))
      .filter((rubrique): rubrique is BudgetLine => Boolean(rubrique))

    const allocated = snapshotAllocated || matchedRubriques.reduce((sum, rubrique) => sum + toAmount(rubrique.montant_prevu), 0)
    const explicitBalance = snapshotBalance || matchedRubriques.reduce((sum, rubrique) => sum + toAmount(rubrique.montant_disponible), 0)
    const requested = requestedAmount !== undefined
      ? toAmount(requestedAmount)
      : lines.reduce((sum, line) => sum + toAmount(line.montant_total), 0)
    
    // Si on a des snapshots, on les utilise en priorité, même s'ils valent 0.
    // Sauf si on n'a vraiment aucune info snapshot (null ou undefined), alors on fallback sur les rubriques actuelles.
    const hasSnapshot = lines.length > 0 && lines.every(l => l.montant_alloue_snapshot !== undefined && l.montant_alloue_snapshot !== null)
    
    const balance = hasSnapshot 
      ? snapshotBalance 
      : (matchedRubriques.length > 0 ? explicitBalance : 0)

    return { allocated, requested, balance }
  }

  const selectedRequisitionBudgetMetrics = useMemo(
    () => getBudgetMetrics(selectedLignes, selectedRequisition?.montant_total),
    [selectedLignes, selectedRequisition?.montant_total, rubriques]
  )

  const filteredRequisitions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    const filtered = requisitions.filter((req) => {
      const status = normalizeStatusValue(req.status)
      const matchesStatus = !statusFilter || status === statusFilter
      const matchesSearch =
        !query ||
        textValue(req.numero_requisition).includes(query) ||
        textValue(req.objet).includes(query) ||
        textValue(`${req.demandeur?.prenom || ''} ${req.demandeur?.nom || ''}`).includes(query)
      return matchesStatus && matchesSearch && dateInRange(req.created_at)
    })
    return sortByCurrent(filtered, (req) => req.created_at, (req) => Number(req.montant_total || 0))
  }, [requisitions, searchQuery, statusFilter, dateDebut, dateFin, sortField, sortDirection])

  const filteredTransports = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    const filtered = transports.filter((transport) => {
      const status = normalizeStatusValue(getTransportStatus(transport))
      const matchesStatus = !statusFilter || status === statusFilter
      const matchesSearch =
        !query ||
        textValue(transport.numero_remboursement).includes(query) ||
        textValue(transport.nature_reunion).includes(query) ||
        textValue(transport.lieu).includes(query)
      return matchesStatus && matchesSearch && dateInRange(transport.date_reunion)
    })
    return sortByCurrent(filtered, (transport) => transport.date_reunion, (transport) => Number(transport.montant_total || 0))
  }, [transports, searchQuery, statusFilter, dateDebut, dateFin, sortField, sortDirection])

  const visibleRequisitions = documentFilter === 'transports' ? [] : filteredRequisitions
  const visibleTransports = documentFilter === 'requisitions' ? [] : filteredTransports
  const visibleFilterLabel = documentFilter === 'requisitions'
    ? `${visibleRequisitions.length} réquisition(s)`
    : documentFilter === 'transports'
      ? `${visibleTransports.length} remboursement(s) transport`
      : `${visibleRequisitions.length} réquisition(s) · ${visibleTransports.length} remboursement(s) transport`

  useEffect(() => {
    setReqPage(1)
  }, [searchQuery, statusFilter, dateDebut, dateFin, sortField, sortDirection, documentFilter])

  const monthlyActivity = useMemo(() => {
    const map = new Map<string, { label: string; depenses: number; recettes: number }>()
    const push = (date: string | undefined, amount: number, kind: 'depenses' | 'recettes') => {
      if (!date) return
      const parsed = new Date(date)
      if (Number.isNaN(parsed.getTime())) return
      const key = `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}`
      const label = parsed.toLocaleDateString('fr-FR', { month: 'short' })
      const current = map.get(key) || { label, depenses: 0, recettes: 0 }
      current[kind] += amount
      map.set(key, current)
    }
    requisitions.forEach((req) => push(req.created_at, Number(req.montant_total || 0), 'depenses'))
    transports.forEach((transport) => push(transport.date_reunion, Number(transport.montant_total || 0), 'depenses'))
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-6).map(([, value]) => value)
  }, [requisitions, transports])

  const maxMonthlyAmount = useMemo(
    () => Math.max(1, ...monthlyActivity.map((item) => Math.max(item.depenses, item.recettes))),
    [monthlyActivity]
  )

  const statusBreakdown = useMemo(() => {
    const map = new Map<string, number>()
    requisitions.forEach((req) => {
      const label = getStatusMeta(req.status).label
      map.set(label, (map.get(label) || 0) + 1)
    })
    return [...map.entries()].map(([label, count]) => ({ label, count }))
  }, [requisitions])

  const budgetLinesWithUsage = useMemo(() => {
    return [...rubriques]
      .sort((a, b) => Number(b.montant_prevu || 0) - Number(a.montant_prevu || 0))
      .map((rubrique) => {
        const planned = Number(rubrique.montant_prevu || 0)
        const available = Number(rubrique.montant_disponible ?? planned)
        const consumed = Math.max(0, planned - available)
        const percent = planned > 0 ? Math.min(100, Math.round((consumed / planned) * 100)) : 0
        return { ...rubrique, planned, available, consumed, percent }
      })
  }, [rubriques])

  const topBudgetLines = useMemo(() => budgetLinesWithUsage.slice(0, 5), [budgetLinesWithUsage])

  const filteredRubriques = useMemo(() => {
    const query = budgetSearch.trim().toLowerCase()
    if (!query) return topBudgetLines
    return budgetLinesWithUsage.filter((rubrique) =>
      String(rubrique.code || '').toLowerCase().includes(query) ||
      String(rubrique.libelle || '').toLowerCase().includes(query)
    )
  }, [budgetLinesWithUsage, budgetSearch, topBudgetLines])

  const canSubmitToExamen = (req: RequisitionItem) => {
    const status = String(req.status || '').toUpperCase()
    const examenStatus = String(req.examen_status || '').toUpperCase()
    const hasEligibleExamenStatus = examenStatus === 'NON_EXAMINE' || examenStatus === 'REJETE'
    const hasLines = req.lignes_count == null ? true : req.lignes_count > 0
    return (
      !req.dossier_id &&
      Boolean(req.service_id) &&
      status === 'SIGNEE_SERVICE' &&
      hasEligibleExamenStatus &&
      Boolean(req.signed_by_id) &&
      Boolean(req.signed_at) &&
      hasLines
    )
  }

  const canSignRequisition = (req: RequisitionItem) => {
    const status = String(req.status || '').toUpperCase()
    const hasLines = req.lignes_count == null ? true : req.lignes_count > 0
    return status === 'BROUILLON' && Boolean(req.service_id) && hasLines
  }

  const canSignTransport = (transport: TransportItem) => {
    const req = transport.requisition
    return Boolean(req?.id) && !!req && canSignRequisition(req)
  }

  const canSubmitTransportToExamen = (transport: TransportItem) => {
    return transport.requisition ? canSubmitToExamen(transport.requisition) : false
  }

  const handleSign = async (requisitionId: string) => {
    setSigningId(requisitionId)
    setSignError(null)
    setActionMessage(null)
    try {
      await apiRequest('PATCH', `/requisitions/${requisitionId}/sign`)
      await loadData()
    } catch (err: any) {
      setSignError(err?.message || 'Signature impossible.')
    } finally {
      setSigningId(null)
    }
  }

  const handleSubmitExamen = async (req: RequisitionItem) => {
    setSubmittingExamenId(req.id)
    setSignError(null)
    setActionMessage(null)
    try {
      await apiRequest('POST', `/requisitions/${req.id}/submit-examen`)
      setActionMessage("La réquisition a été envoyée à l'examen.")
      await loadData()
    } catch (err: any) {
      setSignError(err?.message || "Impossible de soumettre la réquisition à l'examen.")
    } finally {
      setSubmittingExamenId(null)
    }
  }

  const handleSignTransport = async (transport: TransportItem) => {
    const requisitionId = transport.requisition?.id || transport.requisition_id
    if (!requisitionId) return
    setSigningId(requisitionId)
    setSignError(null)
    setActionMessage(null)
    try {
      await apiRequest('PATCH', `/requisitions/${requisitionId}/sign`)
      setActionMessage('Le remboursement transport a été signé par le service.')
      await loadData()
    } catch (err: any) {
      setSignError(err?.message || 'Signature du remboursement impossible.')
    } finally {
      setSigningId(null)
    }
  }

  const handleSubmitTransportExamen = async (transport: TransportItem) => {
    const requisitionId = transport.requisition?.id || transport.requisition_id
    if (!requisitionId) return
    setSubmittingExamenId(requisitionId)
    setSignError(null)
    setActionMessage(null)
    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/submit-examen`)
      setActionMessage("Le remboursement transport a été envoyé à l'examen.")
      await loadData()
    } catch (err: any) {
      setSignError(err?.message || "Impossible de soumettre le remboursement transport à l'examen.")
    } finally {
      setSubmittingExamenId(null)
    }
  }

  const handleViewAllRequisitions = () => {
    if (!activeServiceId) return
    navigate(`/requisitions?service_id=${activeServiceId}`)
  }

  const openRequisitionAnnexe = async (annexe?: { id: string; filename?: string | null } | null) => {
    if (!annexe?.id) return
    try {
      if (annexe.filename) {
        await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
      } else {
        await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
      }
    } catch (error: any) {
      setSignError(error?.message || "Impossible d'ouvrir la pièce jointe.")
    }
  }

  const viewDetails = async (req: RequisitionItem) => {
    setSelectedRequisition(req)
    setShowDetailModal(true)
    setDetailLoading(true)
    setDetailError(null)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const data = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      setSelectedLignes(data || [])
      // Les lignes (avec budget_poste_id) doivent vivre sur la réquisition pour que
      // le Plan de décaissement détecte le multi-postes et propose la répartition.
      setSelectedRequisition((prev) => (prev ? { ...prev, lignes: data || [] } : { ...req, lignes: data || [] }))
    } catch (error: any) {
      setDetailError(error?.message || 'Impossible de charger les détails.')
    } finally {
      setDetailLoading(false)
    }
  }

  const printRequisition = async (req: RequisitionItem) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      if (!lignesData || lignesData.length === 0) return
      await generateSingleRequisitionPDF(req as any, lignesData, 'print', `${user?.prenom} ${user?.nom}`)
    } catch {
      setDetailError("Impossible d'imprimer la réquisition.")
    }
  }

  const downloadRequisition = async (req: RequisitionItem) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      if (!lignesData || lignesData.length === 0) return
      await generateSingleRequisitionPDF(req as any, lignesData, 'download', `${user?.prenom} ${user?.nom}`)
    } catch {
      setDetailError("Impossible de télécharger la réquisition.")
    }
  }

  const openRejectMotif = (req: RequisitionItem) => {
    setSelectedRejectTitle(req.numero_requisition)
    setSelectedRejectMotif(req.motif_rejet?.trim() || 'Motif non renseigné.')
    setShowRejectModal(true)
  }

  const resetFilters = () => {
    setDocumentFilter('all')
    setSearchQuery('')
    setStatusFilter('')
    setDateDebut('')
    setDateFin('')
    setSortField('date')
    setSortDirection('desc')
  }

  const formatDate = (value?: string | null) => {
    if (!value) return ''
    try {
      return new Date(value).toLocaleDateString()
    } catch {
      return ''
    }
  }

  const exportExcel = async () => {
    const XLSX = await loadXlsx()
    const wb = XLSX.utils.book_new()
    if (documentFilter !== 'transports') {
      const rows = visibleRequisitions.map((req) => {
        const isTransport = String(req.type_requisition).toLowerCase() === 'remboursement_transport'
        let displayRef = req.numero_requisition
        if (isTransport) {
          const rt = (req as any).remboursement_transport
          if (rt) {
            displayRef = rt.reference_numero || rt.numero_remboursement || req.numero_requisition
          }
        }

        return {
          Tenant: tenantName,
          'Exercice budgétaire': budgetExercise,
          'Unité opérationnelle': serviceLabel,
          Type: isTransport ? 'Remboursement' : 'Réquisition',
          Numéro: displayRef,
          Date: formatDate(req.created_at),
          Objet: req.objet,
          Lieu: '',
          Montant: Number(req.montant_total || 0),
          Statut: getStatusMeta(req.status).label,
        }
      })
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Réquisitions')
    }
    if (documentFilter !== 'requisitions') {
      const rows = visibleTransports.map((transport) => ({
        Tenant: tenantName,
        'Exercice budgétaire': budgetExercise,
        'Unité opérationnelle': serviceLabel,
        Type: 'Remboursement transport',
        Numéro: transport.reference_numero || transport.numero_remboursement,
        Date: formatDate(transport.date_reunion),
        Objet: transport.nature_reunion,
        Lieu: transport.lieu,
        Montant: Number(transport.montant_total || 0),
        Statut: getStatusMeta(getTransportStatus(transport)).label,
      }))
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Remboursements')
    }
    const suffix = dateDebut || dateFin ? `${dateDebut || 'debut'}_${dateFin || 'fin'}` : new Date().toISOString().slice(0, 10)
    XLSX.writeFile(wb, `espace_unite_operationnelle_${suffix}.xlsx`)
  }

  const exportPdf = async () => {
    const [{ jsPDF }, { default: autoTable }] = await Promise.all([loadJsPdf(), loadAutoTable()])
    const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
    const title = documentFilter === 'requisitions'
      ? "Réquisitions de l'unité opérationnelle"
      : documentFilter === 'transports'
        ? "Remboursements transport de l'unité opérationnelle"
        : "Espace unité opérationnelle - réquisitions et remboursements"
    doc.setFontSize(14)
    doc.text(title, 14, 14)
    doc.setFontSize(9)
    doc.text(`Tenant : ${tenantName}`, 14, 20)
    doc.text(`Unité opérationnelle : ${serviceLabel}`, 14, 25)
    doc.text(`Exercice budgétaire : ${budgetExercise}`, 14, 30)
    if (dateDebut || dateFin) {
      doc.text(`Période : ${dateDebut || 'début'} au ${dateFin || 'fin'}`, 14, 35)
    }

    const rows = [
      ...(documentFilter !== 'transports'
        ? visibleRequisitions.map((req) => {
            const isTransport = String(req.type_requisition).toLowerCase() === 'remboursement_transport'
            let displayRef = req.numero_requisition
            if (isTransport) {
              const rt = (req as any).remboursement_transport
              if (rt) {
                displayRef = rt.reference_numero || rt.numero_remboursement || req.numero_requisition
              }
            }
            return [
              isTransport ? 'Remboursement' : 'Réquisition',
              displayRef,
              formatDate(req.created_at),
              req.objet,
              '',
              Number(req.montant_total || 0).toLocaleString(),
              getStatusMeta(req.status).label,
            ]
          })
        : []),
      ...(documentFilter !== 'requisitions'
        ? visibleTransports.map((transport) => [
            'Remboursement',
            transport.reference_numero || transport.numero_remboursement,
            formatDate(transport.date_reunion),
            transport.nature_reunion,
            transport.lieu,
            Number(transport.montant_total || 0).toLocaleString(),
            getStatusMeta(getTransportStatus(transport)).label,
          ])
        : []),
    ]

    autoTable(doc, {
      startY: dateDebut || dateFin ? 41 : 36,
      head: [['Type', 'Numéro', 'Date', 'Objet / Nature', 'Lieu', 'Montant USD', 'Statut']],
      body: rows,
      styles: { fontSize: 8, cellPadding: 2 },
      headStyles: { fillColor: [37, 99, 235] },
      columnStyles: {
        3: { cellWidth: 80 },
      },
    })
    const suffix = dateDebut || dateFin ? `${dateDebut || 'debut'}_${dateFin || 'fin'}` : new Date().toISOString().slice(0, 10)
    doc.save(`espace_unite_operationnelle_${suffix}.pdf`)
  }

  if (!activeServiceId) {
    return (
      <div className={styles.emptyState}>
        <h2>Accès indisponible</h2>
        <p>Choisissez une unité opérationnelle pour ouvrir son espace de travail.</p>
        <button className={styles.primaryAction} onClick={() => navigate('/services')}>
          Voir mes unités opérationnelles
        </button>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.headerInfo}>
            <div className={styles.kicker}>Unité opérationnelle · {tenantName}</div>
            <div className={styles.identityLine}>
              <h1>{serviceInfo?.libelle || serviceLabel}</h1>
              {serviceInfo?.code && <span className={styles.unitCodeBadge}>{serviceInfo.code}</span>}
              <span className={`${styles.unitStatusBadge} ${serviceInfo?.is_active === false ? styles.unitInactive : styles.unitActive}`}>
                {serviceInfo?.is_active === false ? 'Inactive' : 'Active'}
              </span>
            </div>
            <div className={styles.identityMeta}>
              <span>Exercice {budgetExercise}</span>
              <span>Responsable : {serviceResponsible}</span>
              <span>Budget total : {Number(totalDepenses || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</span>
            </div>
          </div>
          <div className={styles.actionButtons}>
            <BackButton fallback="/services" />
            <button
              className={styles.primaryAction}
              onClick={() => navigate(`/requisitions?service_id=${activeServiceId}&new=1`)}
            >
              <PlusCircle size={20} />
              Nouvelle réquisition
            </button>
            <button
              className={styles.secondaryAction}
              onClick={() =>
                navigate(`/remboursement-transport?new=1&service_id=${activeServiceId}`, {
                  state: { fromCommission: activeServiceId },
                })
              }
            >
              <Car size={18} />
              Remboursement transport
            </button>
            <button type="button" className={styles.secondaryAction} onClick={exportPdf}>
              <Printer size={18} />
              Imprimer le rapport
            </button>
          </div>
        </div>
      </div>

      {commissionError && (
        <div className={styles.alert}>
          <XCircle size={18} />
          <span>{commissionError}</span>
        </div>
      )}
      {rejectedCount > 0 && (
        <div className={styles.alert}>
          <XCircle size={18} />
          <span>Vous avez {rejectedCount} réquisition(s) rejetée(s).</span>
        </div>
      )}
      {signError && (
        <div className={styles.alert}>
          <XCircle size={18} />
          <span>{signError}</span>
        </div>
      )}
      {actionMessage && (
        <div className={styles.successAlert}>
          <CheckCircle size={18} />
          <span>{actionMessage}</span>
        </div>
      )}

      <section className={styles.kpiGrid}>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Budget alloué</span>
            <Wallet size={18} />
          </div>
          <div className={styles.metricValue}>{totalDepenses.toLocaleString('fr-FR')} USD</div>
          <div className={styles.metricHint}>Exercice {summary?.annee ?? '—'}</div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Budget consommé</span>
            <TrendingDown size={18} className={styles.metricIconGreen} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueGreen}`}>{consomme.toLocaleString('fr-FR')} USD</div>
          <div className={styles.metricHint}>{progress}% du budget</div>
          <div className={styles.progressTrack}><div className={styles.progressFill} style={{ width: `${progress}%` }} /></div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Budget disponible</span>
            <Wallet size={18} className={styles.metricIconBlue} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueBlue}`}>{disponible.toLocaleString('fr-FR')} USD</div>
          <div className={styles.metricHint}>{availableProgress}% restant</div>
          <div className={styles.progressTrack}><div className={styles.progressFillBlue} style={{ width: `${availableProgress}%` }} /></div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Réquisitions en attente</span>
            <FileText size={18} className={styles.metricIconAmber} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueAmber}`}>{enAttente.toLocaleString('fr-FR')} USD</div>
          <div className={styles.metricHint}>{engagedProgress}% engagé</div>
          <div className={styles.progressTrack}><div className={styles.progressFillAmber} style={{ width: `${engagedProgress}%` }} /></div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Taux d'exécution</span>
            <CheckCircle size={18} className={styles.metricIconGreen} />
          </div>
          <div className={styles.metricValue}>{progress}%</div>
          <div className={styles.metricHint}>Payé sur budget alloué</div>
          <div className={styles.progressTrack}><div className={styles.progressFill} style={{ width: `${progress}%` }} /></div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.metricHeader}>
            <span>Remboursements en attente</span>
            <Car size={18} className={styles.metricIconBlue} />
          </div>
          <div className={styles.metricValue}>{transportPendingCount}</div>
          <div className={styles.metricHint}>{transports.length} remboursement(s) au total</div>
          <div className={styles.progressTrack}><div className={styles.progressFillBlue} style={{ width: `${transports.length ? Math.round((transportPendingCount / transports.length) * 100) : 0}%` }} /></div>
        </div>
      </section>

      <button
        type="button"
        className={`${styles.insightsToggle} ${insightsOpen ? styles.insightsToggleOpen : ''}`}
        onClick={toggleInsights}
        aria-expanded={insightsOpen}
        aria-controls="service-portal-insights"
      >
        <ChevronDown size={14} aria-hidden="true" />
        {insightsOpen ? 'Masquer les graphiques' : 'Afficher les graphiques'}
      </button>

      {insightsOpen && (
      <section className={styles.insightsGrid} id="service-portal-insights">
        <div className={`${styles.insightPanel} ${styles.gaugePanel}`}>
          <div className={styles.insightHeader}>
            <div>
              <h2>Santé budgétaire</h2>
              <p>Payé, engagé et disponible</p>
            </div>
          </div>
          <BudgetGauge consomme={consomme} engage={enAttente} total={totalDepenses} />
        </div>
        <div className={styles.insightPanel}>
          <div className={styles.insightHeader}>
            <div>
              <h2>Activité mensuelle</h2>
              <p>Dépenses sur les 6 derniers mois visibles</p>
            </div>
          </div>
          <div className={styles.barChart}>
            {monthlyActivity.length === 0 ? (
              <div className={styles.chartEmpty}>Aucune activité mensuelle disponible.</div>
            ) : monthlyActivity.map((item) => (
              <div key={item.label} className={styles.barItem}>
                <div className={styles.barTrack}>
                  <span style={{ height: `${Math.max(4, (item.depenses / maxMonthlyAmount) * 100)}%` }} />
                </div>
                <small>{item.label}</small>
              </div>
            ))}
          </div>
        </div>
        <div className={styles.insightPanel}>
          <div className={styles.insightHeader}>
            <div>
              <h2>État des réquisitions</h2>
              <p>Répartition par statut</p>
            </div>
          </div>
          <div className={styles.statusBars}>
            {statusBreakdown.length === 0 ? (
              <div className={styles.chartEmpty}>Aucune réquisition à analyser.</div>
            ) : statusBreakdown.map((item) => (
              <div key={item.label} className={styles.statusBarRow}>
                <span>{item.label}</span>
                <div><i style={{ width: `${Math.max(8, (item.count / requisitions.length) * 100)}%` }} /></div>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>
      )}

      <section className={styles.filtersPanel}>
        <div className={styles.filtersHeader}>
          <div>
            <h2>Filtres et exports</h2>
            <p>
              {visibleFilterLabel}
            </p>
          </div>
          <div className={styles.exportActions}>
            <button type="button" className={styles.exportExcelBtn} onClick={exportExcel}>
              <Download size={14} aria-hidden="true" />
              Exporter Excel
            </button>
            <button type="button" className={styles.exportPdfBtn} onClick={exportPdf}>
              <FileText size={14} aria-hidden="true" />
              Exporter PDF
            </button>
          </div>
        </div>
        <div className={styles.filtersGrid}>
          <label className={styles.filterField}>
            <span>Type</span>
            <select value={documentFilter} onChange={(event) => setDocumentFilter(event.target.value as any)}>
              <option value="all">Réquisitions + remboursements transport</option>
              <option value="requisitions">Réquisitions uniquement</option>
              <option value="transports">Remboursements transport uniquement</option>
            </select>
          </label>
          <label className={styles.filterField}>
            <span>Recherche</span>
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Numéro, objet, nature, lieu..."
            />
          </label>
          <label className={styles.filterField}>
            <span>Statut</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {statusOptions.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.filterField}>
            <span>Date début</span>
            <input type="date" value={dateDebut} onChange={(event) => setDateDebut(event.target.value)} />
          </label>
          <label className={styles.filterField}>
            <span>Date fin</span>
            <input type="date" value={dateFin} onChange={(event) => setDateFin(event.target.value)} />
          </label>
          <label className={styles.filterField}>
            <span>Trier par</span>
            <select value={sortField} onChange={(event) => setSortField(event.target.value as any)}>
              <option value="date">Date</option>
              <option value="amount">Montant</option>
            </select>
          </label>
          <label className={styles.filterField}>
            <span>Ordre</span>
            <select value={sortDirection} onChange={(event) => setSortDirection(event.target.value as any)}>
              <option value="desc">Décroissant</option>
              <option value="asc">Croissant</option>
            </select>
          </label>
          <button type="button" className={styles.clearFiltersBtn} onClick={resetFilters}>
            Réinitialiser
          </button>
        </div>
      </section>

      <section className={styles.grid}>
        {documentFilter !== 'transports' && <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div className={styles.panelHeaderTitle}>
              <span>Réquisitions de l'unité opérationnelle</span>
              <span className={styles.panelHeaderMeta}>Unité uniquement</span>
            </div>
            <div className={styles.panelActions}>
              <button type="button" className={styles.panelLink} onClick={handleViewAllRequisitions}>
                Voir la liste
              </button>
            </div>
          </div>
          {loading ? (
            <div className={styles.panelState}>Chargement…</div>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>N°</th>
                    <th>Objet</th>
                    <th className={styles.amountCell}>Montant</th>
                    <th>Statut</th>
                    <th>Date</th>
                    <th>Pièce jointe</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRequisitions
                    .slice((reqPage - 1) * 20, reqPage * 20)
                    .map((req) => (
                    <tr key={req.id}>
                      <td>{req.numero_requisition}</td>
                      <td title={req.objet}>{req.objet}</td>
                      <td className={styles.amountCell}>{Number(req.montant_total || 0).toLocaleString()} USD</td>
                      <td>
                        <div className={styles.reqActionArea}>
                          {(() => {
                            const meta = getStatusMeta(req.status)
                            const motif = String(req.status || '').toUpperCase().includes('REJET')
                              ? (req.motif_rejet?.trim() || 'Motif non renseigné.')
                              : ''
                            return (
                              <span
                                className={styles.statusBadge}
                                title={motif ? `${meta.label} · ${motif}` : (meta.description || meta.label)}
                              >
                                {meta.label}
                              </span>
                            )
                          })()}
                          {canSign && canSignRequisition(req) && (
                            <button
                              type="button"
                              className={styles.btnSign}
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                handleSign(req.id)
                              }}
                              disabled={signingId === req.id}
                            >
                              <ShieldCheck size={16} />
                              {signingId === req.id ? 'Signature…' : 'Signer (service)'}
                            </button>
                          )}
                          <div className={styles.stepper}>
                            <div className={styles.stepActive} title="Brouillon" />
                            <div className={(req.status !== 'BROUILLON') ? styles.stepActive : styles.step} title="Signée Service" />
                            <div className={(req.status === 'EN_ATTENTE' || req.status === 'AUTORISEE' || req.status === 'APPROUVEE' || req.status === 'PAYEE') ? styles.stepActive : styles.step} title="Examen Admin" />
                            <div className={(req.status === 'AUTORISEE' || req.status === 'APPROUVEE' || req.status === 'PAYEE') ? styles.stepActive : styles.step} title="Validation 1/2" />
                            <div className={(req.status === 'APPROUVEE' || req.status === 'PAYEE') ? styles.stepActive : styles.step} title="Validation 2/2" />
                          </div>
                        </div>
                      </td>
                      <td>{req.created_at ? new Date(req.created_at).toLocaleDateString() : '—'}</td>
                      <td>
                        {req.annexe?.id ? (
                          <button
                            type="button"
                            className={styles.attachmentBtn}
                            onClick={async (event) => {
                              event.stopPropagation()
                              await openRequisitionAnnexe(req.annexe)
                            }}
                            title={req.annexe?.filename || 'Voir la pièce jointe'}
                            aria-label="Voir la pièce jointe"
                          >
                            <Paperclip size={14} aria-hidden="true" />
                            Voir
                          </button>
                        ) : (
                          <span className={styles.attachmentEmpty}>—</span>
                        )}
                      </td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={(event) => {
                              event.stopPropagation()
                              viewDetails(req)
                            }}
                            title="Voir les détails"
                          >
                            <Eye size={15} aria-hidden="true" />
                          </button>
                          {String(req.status || '').toUpperCase().includes('REJET') && (
                            <button
                              type="button"
                              className={styles.actionBtn}
                              onClick={(event) => {
                                event.stopPropagation()
                                openRejectMotif(req)
                              }}
                              title="Voir le motif de rejet"
                            >
                              <AlertCircle size={15} aria-hidden="true" />
                            </button>
                          )}
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={(event) => {
                              event.stopPropagation()
                              printRequisition(req)
                            }}
                            title="Imprimer"
                            aria-label="Imprimer"
                          >
                            <Printer size={15} aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={(event) => {
                              event.stopPropagation()
                              downloadRequisition(req)
                            }}
                            title="Télécharger"
                            aria-label="Télécharger"
                          >
                            <Download size={15} aria-hidden="true" />
                          </button>
                          {canSubmitToExamen(req) && (
                            <button
                              type="button"
                              className={styles.submitExamenBtn}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleSubmitExamen(req)
                              }}
                              disabled={submittingExamenId === req.id}
                              title="Soumettre à l'examen"
                              aria-label="Soumettre à l'examen"
                            >
                              <Send size={14} />
                              {submittingExamenId === req.id ? 'Envoi…' : 'Soumettre à l’examen'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {visibleRequisitions.length === 0 && (
                    <tr>
                      <td colSpan={7} className={styles.panelState}>
                        <div className={styles.emptyPanelState}>
                          <FileSearch size={28} aria-hidden="true" />
                          <strong>Aucune réquisition ne correspond aux filtres.</strong>
                          <span>Essayez d'élargir la période ou de réinitialiser les critères.</span>
                          <button
                            type="button"
                            className={styles.primaryAction}
                            onClick={() => navigate(`/requisitions?service_id=${activeServiceId}&new=1`)}
                          >
                            <PlusCircle size={16} aria-hidden="true" />
                            Créer une réquisition
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {!loading && visibleRequisitions.length > 20 && (
            <div className={styles.pagination}>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setReqPage((p) => Math.max(1, p - 1))}
                disabled={reqPage <= 1}
              >
                Précédent
              </button>
              <span className={styles.pageInfo}>
                Page {reqPage} / {Math.max(1, Math.ceil(visibleRequisitions.length / 20))}
              </span>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setReqPage((p) => Math.min(Math.ceil(visibleRequisitions.length / 20), p + 1))}
                disabled={reqPage >= Math.ceil(visibleRequisitions.length / 20)}
              >
                Suivant
              </button>
            </div>
          )}
        </div>}

        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <div className={styles.panelHeaderTitle}>
              <span>Postes budgétaires autorisés</span>
              <span className={styles.panelHeaderMeta}>{rubriques.length} poste(s)</span>
            </div>
          </div>
          {loading ? (
            <div className={styles.panelState}>Chargement…</div>
          ) : (
            <div className={styles.rubriquesList}>
              <label className={styles.budgetSearch}>
                <FileSearch size={15} aria-hidden="true" />
                <input
                  type="search"
                  value={budgetSearch}
                  onChange={(event) => setBudgetSearch(event.target.value)}
                  placeholder="Rechercher un poste"
                />
              </label>
              {filteredRubriques.map((rub) => (
                <div key={rub.id} className={styles.rubriqueRow}>
                  <span className={styles.rubriqueCode}>{rub.code}</span>
                  <span className={styles.rubriqueLabel} title={rub.libelle}>{rub.libelle}</span>
                  <span className={styles.rubriqueAmount}>
                    {rub.available.toLocaleString('fr-FR')} USD dispo.
                    <em>{rub.percent}% consommé</em>
                  </span>
                  <span className={styles.rubriqueProgress}>
                    <i style={{ width: `${rub.percent}%` }} />
                  </span>
                </div>
              ))}
              {filteredRubriques.length === 0 && (
                <div className={styles.emptyPanelState}>
                  <BarChart3 size={28} aria-hidden="true" />
                  <strong>{rubriques.length === 0 ? 'Aucun poste budgétaire autorisé.' : 'Aucun poste ne correspond à la recherche.'}</strong>
                  <span>{rubriques.length === 0 ? 'Les postes assignés à cette unité apparaîtront ici.' : 'Essayez un autre code ou libellé.'}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {documentFilter !== 'requisitions' && <section className={`${styles.panel} ${styles.transportPanel}`}>
        <div className={styles.panelHeader}>
          <div className={styles.panelHeaderTitle}>
            <span>Remboursements transport</span>
            <span className={styles.panelHeaderMeta}>Workflow séparé, mêmes validations</span>
          </div>
          <div className={styles.panelActions}>
            <button
              type="button"
              className={styles.panelLink}
              onClick={() =>
                navigate(`/remboursement-transport?service_id=${activeServiceId}`, {
                  state: { fromCommission: activeServiceId },
                })
              }
            >
              Voir la liste
            </button>
          </div>
        </div>
        {loading ? (
          <div className={styles.panelState}>Chargement…</div>
        ) : (
          <div className={`${styles.tableScroll} ${styles.transportTableScroll}`}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>N°</th>
                  <th>Nature</th>
                  <th>Lieu</th>
                  <th className={styles.amountCell}>Montant</th>
                  <th>Statut</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleTransports.map((transport) => {
                  const req = transport.requisition
                  const status = getTransportStatus(transport)
                  const meta = getStatusMeta(status)
                  const requisitionId = req?.id || transport.requisition_id || ''
                  return (
                    <tr key={transport.id}>
                      <td>{transport.numero_remboursement}</td>
                      <td title={transport.nature_reunion}>{transport.nature_reunion}</td>
                      <td title={transport.lieu}>{transport.lieu}</td>
                      <td className={styles.amountCell}>{Number(transport.montant_total || 0).toLocaleString()} USD</td>
                      <td>
                        <span
                          className={styles.statusBadge}
                          title={meta.description || meta.label}
                        >
                          {meta.label}
                        </span>
                      </td>
                      <td>{transport.date_reunion ? new Date(transport.date_reunion).toLocaleDateString() : '—'}</td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={(event) => {
                              event.stopPropagation()
                              navigate(`/remboursement-transport?service_id=${activeServiceId}`)
                            }}
                            title="Ouvrir le remboursement"
                            aria-label="Ouvrir le remboursement"
                          >
                            <Eye size={15} aria-hidden="true" />
                          </button>
                          {canSignTransport(transport) && (
                            <button
                              type="button"
                              className={styles.transportWorkflowBtn}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleSignTransport(transport)
                              }}
                              disabled={signingId === requisitionId}
                              title="Valider et signer le remboursement"
                              aria-label="Valider et signer le remboursement"
                            >
                              <ShieldCheck size={14} />
                              {signingId === requisitionId ? 'Signature…' : 'Signer'}
                            </button>
                          )}
                          {canSubmitTransportToExamen(transport) && (
                            <button
                              type="button"
                              className={styles.submitExamenBtn}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleSubmitTransportExamen(transport)
                              }}
                              disabled={submittingExamenId === requisitionId}
                              title="Soumettre à l'examen"
                              aria-label="Soumettre à l'examen"
                            >
                              <Send size={14} />
                              {submittingExamenId === requisitionId ? 'Envoi…' : 'Soumettre'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {visibleTransports.length === 0 && (
                  <tr>
                    <td colSpan={7} className={styles.panelState}>
                      <div className={styles.emptyPanelState}>
                        <Car size={28} aria-hidden="true" />
                        <strong>Aucun remboursement transport ne correspond aux filtres.</strong>
                        <span>Les demandes de transport de cette unité seront listées ici.</span>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      <section className={styles.panel}>
        <div className={styles.panelHeader}>Gouvernance de l'unité opérationnelle</div>
        <div className={styles.govGrid}>
          <div>
            <div className={styles.govTitle}>Bureau</div>
            <div className={styles.govList}>
              {leadership.map((member) => (
                <div key={member.id} className={styles.govRow}>
                  <span className={styles.govAvatar}>{member.full_name?.[0] || '?'}</span>
                  <div>
                    <div className={styles.govName}>{member.full_name}</div>
                  <div className={styles.govMeta}>{resolveMemberFunctionLabel(member)}</div>
                  {member.is_signer && (
                    <span className={styles.signerBadge}>
                      <ShieldCheck size={12} /> Signataire
                    </span>
                  )}
                </div>
              </div>
            ))}
              {!loading && leadership.length === 0 && (
                <div className={styles.panelState}>Aucun président ou délégué enregistré.</div>
              )}
            </div>
          </div>

          <div>
            <div className={styles.govTitle}>Membres & Experts ({experts.length})</div>
            <div className={styles.govCompact}>
              {experts.map((member) => (
                <div key={member.id} className={styles.govChip}>
                  {member.full_name}
                </div>
              ))}
              {!loading && experts.length === 0 && (
                <div className={styles.panelState}>Aucun membre déclaré.</div>
              )}
            </div>

            <div className={styles.govTitle} style={{ marginTop: '12px' }}>
              Assistants ({assistants.length})
            </div>
            <div className={styles.govCompact}>
              {assistants.map((member) => (
                <div key={member.id} className={styles.govChip}>
                  {member.full_name}
                </div>
              ))}
              {!loading && assistants.length === 0 && (
                <div className={styles.panelState}>Aucun assistant déclaré.</div>
              )}
            </div>
          </div>
        </div>
      </section>

      {showDetailModal && selectedRequisition && (
        <div className={`${styles.modal} ${styles.detailModalOverlay}`}>
          <div className={`${styles.modalContent} ${styles.detailModalContent}`}>
            <div className={styles.modalHeader}>
              <h2>Détails de la réquisition {selectedRequisition.numero_requisition}</h2>
              <button className={styles.closeBtn} onClick={() => setShowDetailModal(false)} aria-label="Fermer"><X size={20} /></button>
            </div>
            <div className={styles.detailContent}>
              {detailError && <div className={styles.modalError}>{detailError}</div>}
              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Objet</label>
                    <p>{selectedRequisition.objet}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant</label>
                    <p><strong className={styles.detailAmount}>{Number(selectedRequisition.montant_total || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant alloué (plafond ligne budgétaire)</label>
                    <p>{selectedRequisitionBudgetMetrics.allocated.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant demandé</label>
                    <p>{selectedRequisitionBudgetMetrics.requested.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Solde</label>
                    <p>{selectedRequisitionBudgetMetrics.balance.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Date</label>
                    <p>{selectedRequisition.created_at ? new Date(selectedRequisition.created_at).toLocaleString() : '—'}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Statut</label>
                    <p>{getStatusMeta(selectedRequisition.status).label}</p>
                  </div>
                  {selectedRequisition.motif_rejet && (
                    <div className={styles.detailItem}>
                      <label>Motif de rejet</label>
                      <p>{selectedRequisition.motif_rejet}</p>
                    </div>
                  )}
                  {selectedRequisition.annexe?.id && (
                    <div className={styles.detailItem}>
                      <label>Pièce jointe</label>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={async () => await openRequisitionAnnexe(selectedRequisition.annexe)}
                      >
                        <Paperclip size={14} aria-hidden="true" />
                        Voir la pièce jointe
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className={styles.detailSection}>
                <h3>Lignes de dépense</h3>
                {detailLoading ? (
                  <div className={styles.panelState}>Chargement…</div>
                ) : selectedLignes.length === 0 ? (
                  <div className={styles.panelState}>Aucune ligne trouvée.</div>
                ) : (
                  <div className={styles.detailTableWrap}>
                    <table className={styles.detailTable}>
                      <thead>
                        <tr>
                          <th>Poste</th>
                          <th>Description</th>
                          <th className={styles.numCell}>Qté</th>
                          <th className={styles.numCell}>Montant</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedLignes.map((ligne) => (
                          <tr key={ligne.id}>
                            <td>{ligne.rubrique || ligne.budget_poste_id || '—'}</td>
                            <td>{ligne.description}</td>
                            <td className={styles.numCell}>{ligne.quantite}</td>
                            <td className={styles.numCell}>{Number(ligne.montant_total || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} USD</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              {selectedRequisition.decaissement_progressif && (
                <PlanDecaissement
                  requisition={{
                    ...(selectedRequisition as any),
                    created_by: selectedRequisition.created_by ?? selectedRequisition.demandeur?.id,
                    lignes: selectedLignes,
                  } as any}
                  currentUserId={user?.id}
                  canAuthorize={hasPermission('can_authorize_disbursement')}
                  isAdmin={isAdmin}
                  onChanged={() => viewDetails(selectedRequisition)}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {showRejectModal && (
        <div className={styles.modal}>
          <div className={styles.modalContentSmall}>
            <div className={styles.modalHeader}>
              <h2>Motif de rejet · {selectedRejectTitle}</h2>
              <button className={styles.closeBtn} onClick={() => setShowRejectModal(false)} aria-label="Fermer"><X size={20} /></button>
            </div>
            <div className={styles.modalBody}>
              <p>{selectedRejectMotif}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
