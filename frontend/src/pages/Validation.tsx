import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Sparkles, Search, Printer, Download, Eye, Check, ShieldCheck, Ban, Lock, Banknote, Smartphone, CreditCard, Landmark, Loader2, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import { usePermissions } from '../hooks/usePermissions'
import { apiRequest, ApiError } from '../lib/apiClient'
import { scoreRequisitions } from '../api/ai'
import { useNotification } from '../contexts/NotificationContext'
import { format } from 'date-fns'
import { formatAmount, toNumber } from '../utils/amount'
import { buildBudgetDecisionSummary, formatBudgetDecisionAmount } from '../utils/budgetDecision'
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import type { Money } from '../types'
import RowActionsMenu, { type ActionLigne } from '../components/RowActionsMenu'
import RequisitionActionModal from '../components/RequisitionActionModal'
import RemboursementActionModal from '../components/RemboursementActionModal'
type PdfGeneratorRemboursementModule = typeof import('../utils/pdfGeneratorRemboursement')
let _pdfGeneratorRemboursementModulePromise: Promise<PdfGeneratorRemboursementModule> | null = null
function loadPdfGeneratorRemboursementModule(): Promise<PdfGeneratorRemboursementModule> {
  if (!_pdfGeneratorRemboursementModulePromise) _pdfGeneratorRemboursementModulePromise = import('../utils/pdfGeneratorRemboursement')
  return _pdfGeneratorRemboursementModulePromise
}
const generateRemboursementTransportPDF: PdfGeneratorRemboursementModule['generateRemboursementTransportPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorRemboursementModule()
  return mod.generateRemboursementTransportPDF(...args)
}
import { uploadRemboursementTransportPdf } from '../api/remboursementsTransport'
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'action.
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
import styles from './Validation.module.css'

interface Requisition {
  id: string
  numero_requisition: string
  objet: string
  type_requisition: string
  montant_total: Money
  service_id?: number | null
  statut?: string
  status?: string
  created_at: string
  created_by: string
  validee_par?: string | null
  mode_paiement: string
  annexe?: {
    id?: string
    file_path: string
    filename: string
  } | null
  demandeur?: UserInfo | null
  validateur?: UserInfo | null
  approbateur?: UserInfo | null
  remboursement_transport?: {
    id?: string
    numero_remboursement?: string | null
    reference_numero?: string | null
  } | null
}

interface UserInfo {
  id: string
  prenom?: string | null
  nom?: string | null
  email?: string | null
}

interface RemboursementTransport {
  id: string
  numero_remboursement: string
  pdf_path?: string | null
  instance: string
  type_reunion: 'bureau' | 'commission' | 'conseil' | 'atelier'
  nature_reunion: string
  nature_travail: string[]
  lieu: string
  date_reunion: string
  heure_debut?: string
  heure_fin?: string
  montant_total: Money
  requisition_id?: string
  requisition?: { numero_requisition: string }
  created_at: string
  created_by: string
}

interface DossierRequisition {
  id: string
  reference: string
  status: string
  created_at: string
  requisitions: Array<any>
}

interface Participant {
  id?: string
  nom: string
  titre_fonction: string
  montant: Money
  type_participant: 'principal' | 'assistant'
}


export default function Validation() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { settings: orgSettings } = useOrganisationSettings()
  const aiEnabled = Boolean(orgSettings?.is_ai_enabled)
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const { showSuccess, showError } = useNotification()
  const [requisitions, setRequisitions] = useState<any[]>([])
  const [aiScores, setAiScores] = useState<Record<string, any>>({})
  const [aiPopoverId, setAiPopoverId] = useState<string | null>(null)
  const aiCacheRef = useRef<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState<string>('all')
  // La page s'ouvre sur ce qui attend une decision, pas sur l'historique
  // complet. EN_ATTENTE est bien le statut d'arrivee des requisitions
  // listees ici : submit_requisition_examen_logic le pose, et les dossiers
  // (qui passent en EN_ATTENTE_COMMISSION) sont ecartes de ce tableau par
  // le filtre `if (req.dossier_id) return false`.
  const [filterStatus, setFilterStatus] = useState<string>('EN_ATTENTE')
  const [pageSize, setPageSize] = useState<number>(20)
  const [pageIndex, setPageIndex] = useState<number>(0)
  const [hasMore, setHasMore] = useState<boolean>(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [dossiers, setDossiers] = useState<DossierRequisition[]>([])
  const [dossiersLoading, setDossiersLoading] = useState(false)
  const [dossierFilterStatus, setDossierFilterStatus] = useState<'EN_EXAMEN' | 'TRAITEMENT' | 'all'>('EN_EXAMEN')
  const [dossierSearch, setDossierSearch] = useState('')
  const [selectedDossier, setSelectedDossier] = useState<DossierRequisition | null>(null)

  const [showActionModal, setShowActionModal] = useState(false)
  const [currentAction, setCurrentAction] = useState<'reject' | 'authorize' | 'vise'>('authorize')
  const [selectedRequisition, setSelectedRequisition] = useState<Requisition | null>(null)
  const [remboursementNumber, setRemboursementNumber] = useState<string>('')
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [remboursementActionLoadingId, setRemboursementActionLoadingId] = useState<string | null>(null)

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])
  const [selectedRemboursementBudgetLines, setSelectedRemboursementBudgetLines] = useState<any[]>([])

  const openRequisitionAnnexe = async (annexe?: { id: string; filename?: string | null } | null) => {
    if (!annexe?.id) return
    try {
      if (annexe.filename) {
        await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
      } else {
        await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
      }
    } catch (error: any) {
      showError('Pièce jointe', error?.message || "Impossible d'ouvrir la pièce jointe.")
    }
  }

  const openRemboursementPdf = async (remboursement?: { id?: string; pdf_path?: string | null } | null) => {
    if (!remboursement?.id || !remboursement?.pdf_path) return
    await openAuthenticatedFile(`/remboursements-transport/${remboursement.id}/pdf`)
  }

  const canValidate = hasPermission('validation')
  const pendingStatuses = ['EN_ATTENTE_COMMISSION', 'EN_ATTENTE', 'AUTORISEE', 'APPROUVEE', 'PENDING_VALIDATION_IMPORT']
  const statusFilterMap: Record<string, string[]> = {
    all: [
      'EN_ATTENTE_COMMISSION',
      'EN_ATTENTE',
      'AUTORISEE',
      'APPROUVEE',
      'PAYEE',
      'REJETEE',
      'PENDING_VALIDATION_IMPORT'
    ],
    EN_ATTENTE_COMMISSION: ['EN_ATTENTE_COMMISSION'],
    EN_ATTENTE: ['EN_ATTENTE'],
    AUTORISEE: ['AUTORISEE'],
    APPROUVEE: ['APPROUVEE'],
    PAYEE: ['PAYEE'],
    REJETEE: ['REJETEE'],
    PENDING_VALIDATION_IMPORT: ['PENDING_VALIDATION_IMPORT']
  }
  const authorizeStatuses = new Set(['EN_ATTENTE', 'EN_ATTENTE_COMMISSION'])
  const viseStatuses = new Set(['AUTORISEE'])

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (error instanceof ApiError) {
      return error.message || fallback
    }
    if (typeof (error as any)?.message === 'string') {
      return (error as any).message || fallback
    }
    return fallback
  }

  useEffect(() => {
    if (canValidate) {
      loadRequisitions()
      loadDossiers()
    } else {
      setLoading(false)
    }
  }, [canValidate, filterType, filterStatus, pageSize, pageIndex])

  useEffect(() => {
    setPageIndex(0)
  }, [filterType, filterStatus, pageSize])

  useEffect(() => {
    setAiPopoverId(null)
  }, [filterType, searchQuery])

  const loadRequisitions = async () => {
    setLoading(true)
    try {
      const params: any = {
        order: 'created_at.desc',
        limit: pageSize,
        offset: pageIndex * pageSize,
        examen_status: 'EXAMINE',
      }
      const allowedStatuses = statusFilterMap[filterStatus] || []
      if (filterStatus === 'all') {
        params.status_in = allowedStatuses.join(',')
      } else if (allowedStatuses.length === 1) {
        params.status = allowedStatuses[0]
      } else if (allowedStatuses.length > 1) {
        params.status_in = allowedStatuses.join(',')
      } else {
        params.status_in = pendingStatuses.join(',')
      }
      if (filterType !== 'all') params.type_requisition = filterType

      const res: any = await apiRequest('GET', '/requisitions', {
        params: { ...params, include: 'demandeur,validateur,approbateur,examinateur,caissier,annexe' }
      })
      const items = Array.isArray(res) ? res : (res as any)?.items ?? (res as any)?.data ?? []
      setRequisitions(items as any)
      setHasMore(Array.isArray(items) && items.length === pageSize)
    } catch (error) {
      console.error('Error loading requisitions:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadDossiers = async () => {
    setDossiersLoading(true)
    try {
      const res: any = await apiRequest('GET', '/dossiers', {
        params: { include_requisitions: true, order: 'created_at.desc', limit: 200 },
      })
      const items = Array.isArray(res) ? res : (res as any)?.items ?? (res as any)?.data ?? []
      setDossiers(items as any)
    } catch (error) {
      console.error('Error loading dossiers:', error)
    } finally {
      setDossiersLoading(false)
    }
  }

  const handleAction = async (action: 'reject' | 'authorize' | 'vise', requisition: Requisition) => {
    setCurrentAction(action)
    setSelectedRequisition(requisition)

    if (requisition.type_requisition === 'remboursement_transport') {
      try {
        const res: any = await apiRequest('GET', '/remboursements-transport', { params: { requisition_id: requisition.id, limit: 1 } })
        const data = Array.isArray(res) ? res[0] : res
        if (data?.numero_remboursement) setRemboursementNumber(data.numero_remboursement)
      } catch {}
    }

    if (action === 'authorize') return handleAuthorizeImmediate(requisition)
    if (action === 'vise') return handleViseImmediate(requisition)
    setShowActionModal(true)
  }

  const handleAuthorizeImmediate = async (requisition: Requisition) => {
    setActionLoadingId(requisition.id)
    try {
      await apiRequest('POST', `/requisitions/${requisition.id}/validate`)

      showSuccess(
        'Réquisition validée (1/2)',
        `La réquisition ${requisition.numero_requisition} a été validée (1/2).\n\nElle attend la validation finale (2/2).`
      )

      loadRequisitions()
      loadDossiers()
    } catch (error) {
      console.error('Error validating requisition:', error)
      showError('Erreur de validation', getErrorMessage(error, 'Impossible d’autoriser la réquisition. Veuillez réessayer.'))
    } finally {
      setActionLoadingId(null)
    }
  }

  const handleViseImmediate = async (requisition: Requisition) => {
    setActionLoadingId(requisition.id)
    try {
      await apiRequest('POST', `/requisitions/${requisition.id}/vise`)

      showSuccess(
        'Réquisition validée (2/2)',
        `La réquisition ${requisition.numero_requisition} a été validée (2/2).\n\nStatut : Validation 2/2.`
      )

      loadRequisitions()
      loadDossiers()
    } catch (error) {
      console.error('Error approving requisition:', error)
      showError('Erreur de validation', getErrorMessage(error, 'Impossible de viser la réquisition. Veuillez réessayer.'))
    } finally {
      setActionLoadingId(null)
    }
  }

  const handleModalClose = () => {
    setShowActionModal(false)
    setSelectedRequisition(null)
    loadRequisitions()
  }

  const handleConfirm = async (motif?: string) => {
    if (!selectedRequisition) return

    setActionLoadingId(selectedRequisition.id)
    try {
      if (!motif || !motif.trim()) {
        showError('Motif requis', 'Veuillez renseigner le motif du rejet.')
        return
      }
      await apiRequest('POST', `/requisitions/${selectedRequisition.id}/reject`, {
        motif_rejet: motif.trim()
      })

      showSuccess(
        'Réquisition rejetée',
        `La réquisition ${selectedRequisition.numero_requisition} a été rejetée.\n\nMotif : ${motif || 'Non spécifié'}`
      )

      handleModalClose()
      loadDossiers()
    } catch (error) {
      console.error('Error rejecting requisition:', error)
      showError('Erreur de traitement', getErrorMessage(error, 'Une erreur est survenue lors du rejet de la réquisition.'))
    } finally {
      setActionLoadingId(null)
    }
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const loadRemboursementByRequisition = async (requisitionId: string) => {
    const res: any = await apiRequest('GET', '/remboursements-transport', {
      params: { requisition_id: requisitionId, include: 'requisition', limit: 1 }
    })
    const data = Array.isArray(res) ? res[0] : (res as any)?.items?.[0] ?? (res as any)?.data?.[0] ?? res
    return data as RemboursementTransport | undefined
  }

  const loadParticipants = async (remboursementId: string) => {
    const participantsRes: any = await apiRequest('GET', '/participants-transport', {
      params: { remboursement_id: remboursementId, limit: 500 }
    })
    return Array.isArray(participantsRes)
      ? participantsRes
      : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []
  }

  const loadRequisitionLines = async (requisitionId: string) => {
    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', {
      params: { requisition_id: requisitionId }
    })
    return Array.isArray(lignesRes)
      ? lignesRes
      : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
  }

  const handleViewRemboursementDetails = async (requisition: Requisition) => {
    setRemboursementActionLoadingId(requisition.id)
    try {
      const [remboursement, budgetLines] = await Promise.all([
        loadRemboursementByRequisition(requisition.id),
        loadRequisitionLines(requisition.id),
      ])
      if (!remboursement) {
        showError('Remboursement introuvable', 'Aucun remboursement lié à cette réquisition.')
        return
      }
      const participants = await loadParticipants(remboursement.id)
      setSelectedRemboursementDetails(remboursement)
      setSelectedParticipants(participants)
      setSelectedRemboursementBudgetLines(Array.isArray(budgetLines) ? budgetLines : [])
      setShowDetailModal(true)
    } catch (error) {
      console.error('Error loading remboursement details:', error)
      showError('Erreur', 'Impossible de charger les détails du remboursement.')
    } finally {
      setRemboursementActionLoadingId(null)
    }
  }

  const handlePrintRemboursement = async (requisition: Requisition) => {
    setRemboursementActionLoadingId(requisition.id)
    try {
      const remboursement = await loadRemboursementByRequisition(requisition.id)
      if (!remboursement) {
        showError('Remboursement introuvable', 'Aucun remboursement lié à cette réquisition.')
        return
      }
      const participants = await loadParticipants(remboursement.id)
      const handleUpload = async (blob: Blob, filename: string) => {
        try {
          await uploadRemboursementTransportPdf(remboursement.id, blob, filename)
        } catch (error) {
          console.error('Error uploading remboursement PDF:', error)
        }
      }
      await generateRemboursementTransportPDF(
        remboursement,
        participants || [],
        'print',
        `${user?.prenom} ${user?.nom}`,
        'a4',
        handleUpload
      )
    } catch (error) {
      console.error('Error printing remboursement:', error)
      showError('Erreur', 'Impossible d’imprimer le remboursement.')
    } finally {
      setRemboursementActionLoadingId(null)
    }
  }

  const handleViewRequisitionDetails = (requisition: Requisition) => {
    navigate(`/validation/requisition/${requisition.id}`, { state: { requisition } })
  }

  const handlePrintRequisition = async (requisition: Requisition) => {
    try {
      const lignesData = await loadRequisitionLines(requisition.id)

      if (!lignesData || lignesData.length === 0) {
        showError('Erreur', 'Aucune ligne de dépense trouvée pour cette réquisition.')
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'print',
        `${user?.prenom || ''} ${user?.nom || ''}`.trim()
      )
    } catch (error: any) {
      console.error('Error printing requisition:', error)
      showError('Erreur', error?.message || 'Impossible d’imprimer la réquisition.')
    }
  }

  const handleDownloadRequisition = async (requisition: Requisition) => {
    try {
      const lignesData = await loadRequisitionLines(requisition.id)

      if (!lignesData || lignesData.length === 0) {
        showError('Erreur', 'Aucune ligne de dépense trouvée pour cette réquisition.')
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'download',
        `${user?.prenom || ''} ${user?.nom || ''}`.trim()
      )
    } catch (error: any) {
      console.error('Error downloading requisition:', error)
      showError('Erreur', error?.message || 'Impossible de télécharger la réquisition.')
    }
  }

  const handleDownloadRemboursement = async (requisition: Requisition) => {
    setRemboursementActionLoadingId(requisition.id)
    try {
      const remboursement = await loadRemboursementByRequisition(requisition.id)
      if (!remboursement) {
        showError('Remboursement introuvable', 'Aucun remboursement lié à cette réquisition.')
        return
      }
      const participants = await loadParticipants(remboursement.id)
      const handleUpload = async (blob: Blob, filename: string) => {
        try {
          await uploadRemboursementTransportPdf(remboursement.id, blob, filename)
        } catch (error) {
          console.error('Error uploading remboursement PDF:', error)
        }
      }
      await generateRemboursementTransportPDF(
        remboursement,
        participants || [],
        'download',
        `${user?.prenom} ${user?.nom}`,
        'a4',
        handleUpload
      )
    } catch (error) {
      console.error('Error downloading remboursement:', error)
      showError('Erreur', 'Impossible de télécharger le remboursement.')
    } finally {
      setRemboursementActionLoadingId(null)
    }
  }

  const safeRequisitions = Array.isArray(requisitions) ? requisitions : []
  const filteredRequisitions = safeRequisitions.filter(req => {
    if (req.dossier_id) return false
    const searchLower = searchQuery.toLowerCase()
    const statusValue = String((req as any).status ?? req.statut ?? '').toUpperCase()
    if (filterStatus !== 'all') {
      const allowed = (statusFilterMap[filterStatus] || []).map((s) => s.toUpperCase())
      if (!allowed.includes(statusValue)) {
        return false
      }
    }
    return (
      getDocumentReference(req).toLowerCase().includes(searchLower) ||
      (req.numero_requisition || '').toLowerCase().includes(searchLower) ||
      (req.objet || '').toLowerCase().includes(searchLower) ||
      (req.demandeur?.nom || '').toLowerCase().includes(searchLower) ||
      (req.demandeur?.prenom || '').toLowerCase().includes(searchLower)
    )
  })

  const getStatutBadge = (statut: string) => {
    const badges = {
      EN_ATTENTE_COMMISSION: { label: 'Attente signature commission', class: styles.statutBrouillon },
      EN_ATTENTE: { label: 'En attente', class: styles.statutBrouillon },
      AUTORISEE: { label: 'Validée 1/2', class: styles.statutValidee },
      APPROUVEE: { label: 'Validation 2/2', class: styles.statutApprouvee },
      PAYEE: { label: 'Payée', class: styles.statutPayee },
      REJETEE: { label: 'Rejetée', class: styles.statutRejetee },
      PENDING_VALIDATION_IMPORT: { label: 'Import à valider', class: styles.statutBrouillon }
    }
    const badge = badges[statut as keyof typeof badges] || { label: statut, class: '' }
    return <span className={`${styles.badge} ${badge.class}`}>{badge.label}</span>
  }

  const getTypeBadge = (type: string) => {
    const types = {
      classique: { label: 'Classique', class: styles.typeClassique },
      remboursement_transport: { label: 'Remb. Transp.', class: styles.typeRemboursement }
    }
    const badge = types[type as keyof typeof types] || { label: type, class: '' }
    return <span className={`${styles.badge} ${badge.class}`}>{badge.label}</span>
  }

  function getDocumentReference(req: Requisition | any) {
    const transport = req?.remboursement_transport
    if (String(req?.type_requisition || '').toLowerCase() === 'remboursement_transport') {
      return transport?.reference_numero || transport?.numero_remboursement || req?.numero_requisition || '-'
    }
    return req?.numero_requisition || '-'
  }

  const filteredIds = useMemo(
    () => filteredRequisitions.map((req) => String(req.id)).filter(Boolean),
    [filteredRequisitions]
  )

  const selectedRemboursementBudgetSummary = useMemo(
    () => buildBudgetDecisionSummary(selectedRemboursementBudgetLines, selectedRemboursementDetails?.montant_total),
    [selectedRemboursementBudgetLines, selectedRemboursementDetails]
  )

  const filteredDossiers = useMemo(() => {
    const needle = dossierSearch.trim().toLowerCase()
    return dossiers.filter((dossier) => {
      if (dossierFilterStatus !== 'all' && String(dossier.status || '').toUpperCase() !== dossierFilterStatus) {
        return false
      }
      if (!needle) return true
      return dossier.reference.toLowerCase().includes(needle)
    })
  }, [dossiers, dossierFilterStatus, dossierSearch])

  const dossierRefMap = useMemo(() => {
    const map = new Map<string, string>()
    dossiers.forEach((dossier) => {
      map.set(String(dossier.id), dossier.reference)
    })
    return map
  }, [dossiers])

  useEffect(() => {
    if (!aiEnabled) return
    if (!canValidate || filteredIds.length === 0) return
    const missing = filteredIds.filter((id) => id && !aiCacheRef.current[id])
    if (missing.length === 0) return

    let cancelled = false
    const loadScores = async () => {
      try {
        const res = await scoreRequisitions({ requisition_ids: missing })
        if (cancelled) return
        const next = { ...aiCacheRef.current }
        res.forEach((score) => {
          next[String(score.requisition_id)] = score
        })
        aiCacheRef.current = next
        setAiScores(next)
      } catch (error) {
        console.error('Error loading AI scores:', error)
      }
    }
    loadScores()
    return () => {
      cancelled = true
    }
  }, [filteredIds, canValidate, aiEnabled])

  const getAiBadge = (reqId: string) => {
    if (!aiEnabled) return null
    const score = aiScores[String(reqId)]
    if (!score) {
      return (
        <span className={`${styles.aiBadge} ${styles.aiBadgeLoading}`} title="Analyse IA en cours">
          <Sparkles size={12} />IA…
        </span>
      )
    }

    const levelClass =
      score.risk_score >= 71
        ? styles.aiBadgeHigh
        : score.risk_score >= 41
        ? styles.aiBadgeMedium
        : styles.aiBadgeLow

    const baseLines = [
      `Score ${score.risk_score}/100`,
      `Basé sur ${score.sample_size ?? 0} réquisition(s) comparables`,
    ]
    if (score.mean_amount) {
      baseLines.push(`Moyenne: ${formatCurrency(score.mean_amount)}`)
    }
    if (score.z_score !== null && score.z_score !== undefined) {
      baseLines.push(`Écart: ${Math.abs(Number(score.z_score)).toFixed(1)} écarts-types`)
    }
    const reasonText = Array.isArray(score.reasons) && score.reasons.length > 0 ? score.reasons.join(' ') : ''
    const body = `${baseLines.join(' • ')}${reasonText ? ` • ${reasonText}` : ''}`

    return (
      <span className={styles.aiBadgeWrapper}>
        <button
          type="button"
          className={`${styles.aiBadge} ${levelClass}`}
          onClick={(e) => {
            e.stopPropagation()
            setAiPopoverId((prev) => (prev === reqId ? null : reqId))
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setAiPopoverId((prev) => (prev === reqId ? null : reqId))
            }
          }}
          aria-expanded={aiPopoverId === reqId}
          title={body}
        >
          <Sparkles size={12} />IA {score.risk_score}
        </button>
        {aiPopoverId === reqId && (
          <div className={styles.aiPopover} role="dialog">
            <div className={styles.aiPopoverTitle}>Scoring IA</div>
            <div className={styles.aiPopoverBody}>{body}</div>
          </div>
        )}
      </span>
    )
  }

  if (permissionsLoading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  if (!canValidate) {
    return (
      <div className={styles.noAccess}>
        <h2>Accès non autorisé</h2>
        <p>Vous n'êtes pas autorisé à valider des réquisitions.</p>
        <p>Contactez un administrateur si vous pensez que c'est une erreur.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonGrid}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`val-skel-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
              <div className={styles.skeletonLine} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Validation des réquisitions</h1>
          <p>Approuver ou rejeter les réquisitions en attente</p>
        </div>
      </div>

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <label htmlFor="validation-search">Rechercher</label>
          <input
            id="validation-search"
            type="text"
            aria-label="Rechercher une réquisition par numéro, objet ou demandeur"
            placeholder="N° réquisition, objet, demandeur..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <label htmlFor="validation-type">Type</label>
          <select id="validation-type" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="all">Tous les types</option>
            <option value="classique">Classique</option>
            <option value="remboursement_transport">Remboursement Transport</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label htmlFor="validation-statut">Statut réquisition</label>
          <select id="validation-statut" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="all">Tous</option>
            <option value="EN_ATTENTE_COMMISSION">Attente signature commission</option>
            <option value="EN_ATTENTE">En attente</option>
            <option value="AUTORISEE">Validée 1/2</option>
            <option value="APPROUVEE">Validation 2/2</option>
            <option value="PAYEE">Payée</option>
            <option value="REJETEE">Rejetée</option>
            <option value="PENDING_VALIDATION_IMPORT">Import à valider</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label htmlFor="validation-taille">Affichage</label>
          <select id="validation-taille" value={String(pageSize)} onChange={(e) => setPageSize(Number(e.target.value))}>
            <option value="10">10</option>
            <option value="20">20</option>
            <option value="50">50</option>
          </select>
        </div>
      </div>

      <div className={styles.sectionBar}>
        <div className={styles.sectionTitle}>Dossiers en traitement</div>
        <div className={styles.dossierFilters}>
          <div className={styles.dossierFilterGroup}>
            <label htmlFor="dossier-search">Rechercher dossier</label>
            <input
              id="dossier-search"
              type="text"
              aria-label="Rechercher un dossier par référence"
              placeholder="Référence dossier..."
              value={dossierSearch}
              onChange={(e) => setDossierSearch(e.target.value)}
            />
          </div>
          <div className={styles.dossierFilterGroup}>
            <label htmlFor="dossier-statut">Statut dossier</label>
            <select
              id="dossier-statut"
              value={dossierFilterStatus}
              onChange={(e) => setDossierFilterStatus(e.target.value as 'EN_EXAMEN' | 'TRAITEMENT' | 'all')}
            >
              <option value="EN_EXAMEN">En examen</option>
              <option value="TRAITEMENT">Traitement</option>
              <option value="all">Tous</option>
            </select>
          </div>
        </div>
      </div>
      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colDossierRef}>Référence</th>
              <th className={styles.colDossierCount}>Réquisitions</th>
              <th className={styles.colDossierAmount}>Montant total</th>
              <th className={styles.colDossierStatus}>Statut</th>
              <th className={styles.colDossierDate}>Créé le</th>
              <th className={styles.colActions}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {dossiersLoading ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Chargement...</td>
              </tr>
            ) : filteredDossiers.length === 0 ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Aucun dossier en traitement</td>
              </tr>
            ) : (
              filteredDossiers.map((dossier) => {
                const total = (dossier.requisitions || []).reduce(
                  (sum, r) => sum + Number(r.montant_total || 0),
                  0
                )
                return (
                  <tr key={dossier.id}>
                    <td className={styles.colDossierRef}><strong>{dossier.reference}</strong></td>
                    <td className={styles.colDossierCount}>{(dossier.requisitions || []).length}</td>
                    <td className={styles.colDossierAmount}>
                      {total.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                    </td>
                    <td className={styles.colDossierStatus}>
                      <span className={`${styles.badge} ${styles.statutTraitement}`}>Traitement</span>
                    </td>
                    <td className={styles.colDossierDate}>{format(new Date(dossier.created_at), 'dd/MM/yyyy')}</td>
                    <td className={styles.colActions}>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={`${styles.detailBtn} ${styles.actionIconBtn}`}
                          title="Voir le dossier"
                          aria-label="Voir le dossier"
                          onClick={() => setSelectedDossier(dossier)}
                        >
                          <Search size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.searchSticky}>
        <div className={styles.searchBox}>
          <span className={styles.searchIcon}><Search size={16} /></span>
          <input
            type="text"
            placeholder="Rechercher une réquisition..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInputMobile}
          />
          {searchQuery && (
            <button
              type="button"
              className={styles.searchClear}
              onClick={() => setSearchQuery('')}
              aria-label="Effacer la recherche"
            >
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {filteredRequisitions.length === 0 ? (
        <div className={styles.empty}>
          <p>Aucune réquisition en attente de validation</p>
        </div>
      ) : (
        <div className={styles.tableContainer}>
          {/* La colonne Montant s'elargit quand le scoring IA est actif :
              la pastille partage la cellule avec le montant. */}
          <table className={`${styles.table} ${aiEnabled ? styles.tableWithAi : ''}`}>
            <thead>
              <tr>
                <th className={styles.colNumero}>Référence</th>
                <th className={styles.colType}>Type</th>
                <th className={styles.colObjet}>Objet</th>
                <th className={styles.colDemandeur}>Demandeur</th>
                <th className={styles.colMontant}>Montant</th>
                <th className={styles.colModePaiement}>Mode paiement</th>
                <th className={styles.colStatut}>Statut</th>
                <th className={styles.colDate}>Date création</th>
                <th className={styles.colActions}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRequisitions.map((req) => {
                const statusValue = String((req as any).status ?? req.statut ?? '').toUpperCase()
                const canAct = !['PAYEE', 'REJETEE'].includes(statusValue || '')
                const isBusy = actionLoadingId === req.id
                const isAuthorizedBySelf = Boolean((req as any).validee_par && user?.id && String((req as any).validee_par) === String(user.id))
                const isRemboursementTransport = req.type_requisition === 'remboursement_transport'
                const remboursementOccupe = remboursementActionLoadingId === req.id
                const detailLibelle = isRemboursementTransport
                  ? 'Voir les détails du remboursement'
                  : 'Voir les détails de la réquisition'
                // Sept boutons dans une cellule immobilisaient 224 px sur
                // chaque ligne pour des actions dont une seule sert souvent.
                // Les fonctions et leurs arguments sont inchanges : seul
                // l'endroit ou on les atteint change.
                const actionsLigne: ActionLigne[] = []
                // La consultation ouvre le menu, elle aussi : une cellule qui
                // melange un bouton et un menu oblige a viser deux cibles de
                // nature differente sur chaque ligne. Elle vient en tete, a
                // l'endroit ou le menu pose deja le focus a l'ouverture.
                actionsLigne.push({
                  cle: 'detail',
                  libelle: detailLibelle,
                  icone: isRemboursementTransport && remboursementOccupe
                    ? <Loader2 size={15} className={styles.spin} />
                    : <Search size={15} />,
                  disabled: isRemboursementTransport && remboursementOccupe,
                  onSelect: () =>
                    isRemboursementTransport
                      ? handleViewRemboursementDetails(req)
                      : handleViewRequisitionDetails(req),
                })
                actionsLigne.push({
                  cle: 'imprimer',
                  libelle: isRemboursementTransport ? 'Imprimer le remboursement' : 'Imprimer la réquisition',
                  icone: <Printer size={15} />,
                  disabled: isRemboursementTransport && remboursementOccupe,
                  onSelect: () =>
                    isRemboursementTransport ? handlePrintRemboursement(req) : handlePrintRequisition(req),
                })
                actionsLigne.push({
                  cle: 'telecharger',
                  libelle: isRemboursementTransport ? 'Télécharger le remboursement' : 'Télécharger la réquisition',
                  icone: <Download size={15} />,
                  disabled: isRemboursementTransport && remboursementOccupe,
                  onSelect: () =>
                    isRemboursementTransport ? handleDownloadRemboursement(req) : handleDownloadRequisition(req),
                })
                if (req.annexe?.id) {
                  actionsLigne.push({
                    cle: 'annexe',
                    libelle: 'Voir la pièce jointe',
                    description: req.annexe.filename || undefined,
                    icone: <Eye size={15} />,
                    onSelect: () => openRequisitionAnnexe(req.annexe),
                  })
                }
                if (canAct && authorizeStatuses.has(String(statusValue))) {
                  actionsLigne.push({
                    cle: 'valider1',
                    libelle: 'Validation 1/2',
                    // Le repere de circuit etait un <span> pose dans la
                    // cellule ; il accompagne desormais l'action qu'il decrit.
                    description: isRemboursementTransport ? 'Étape 1 : validation technique' : undefined,
                    icone: isBusy && currentAction === 'authorize'
                      ? <Loader2 size={15} className={styles.spin} />
                      : <Check size={15} />,
                    disabled: isBusy,
                    onSelect: () => handleAction('authorize', req),
                  })
                }
                if (canAct && viseStatuses.has(String(statusValue))) {
                  actionsLigne.push({
                    cle: 'valider2',
                    libelle: isRemboursementTransport ? 'Validation 2/2' : 'Viser pour paiement (2/2)',
                    description: isAuthorizedBySelf
                      ? 'Sécurité : vous avez déjà effectué la première validation, un autre utilisateur doit viser cette dépense.'
                      : isRemboursementTransport
                        ? 'Étape 2 : validation finale'
                        : undefined,
                    icone: isBusy && currentAction === 'vise'
                      ? <Loader2 size={15} className={styles.spin} />
                      : isAuthorizedBySelf
                        ? <Lock size={15} />
                        : <ShieldCheck size={15} />,
                    disabled: isBusy || isAuthorizedBySelf,
                    onSelect: () => handleAction('vise', req),
                  })
                }
                if (canAct) {
                  actionsLigne.push({
                    cle: 'rejeter',
                    libelle: 'Rejeter',
                    icone: isBusy && currentAction === 'reject'
                      ? <Loader2 size={15} className={styles.spin} />
                      : <Ban size={15} />,
                    disabled: isBusy,
                    destructive: true,
                    onSelect: () => handleAction('reject', req),
                  })
                }
              return (
                <tr key={req.id}>
                    <td className={styles.colNumero}>
                      <div className={styles.numeroCell}>
                        <strong>{getDocumentReference(req)}</strong>
                        {req.dossier_id && dossierRefMap.has(String(req.dossier_id)) && (
                          <span className={styles.dossierTag} title="Dossier rattaché">
                            {dossierRefMap.get(String(req.dossier_id))}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className={styles.colType}>{getTypeBadge(req.type_requisition)}</td>
                    <td className={styles.colObjet} title={req.objet}>{req.objet}</td>
                    <td className={styles.colDemandeur}>{req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : 'N/A'}</td>
                    <td className={styles.colMontant}>
                      <div className={styles.amountRow}>
                        <strong>${formatAmount(req.montant_total)}</strong>
                        {getAiBadge(req.id)}
                      </div>
                    </td>
                    <td className={styles.colModePaiement}>
                      <span
                        className={styles.modePaiementBadge}
                        title={
                          req.mode_paiement === 'cash'
                            ? 'Cash'
                            : req.mode_paiement === 'mobile_money'
                            ? 'Mobile Money'
                            : 'Opération bancaire'
                        }
                      >
                        {req.mode_paiement === 'cash' && <><Banknote size={12} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Cash</>}
                        {req.mode_paiement === 'mobile_money' && <><Smartphone size={12} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />MM</>}
                        {req.mode_paiement === 'card' && <><CreditCard size={12} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Visa</>}
                        {req.mode_paiement === 'virement' && <><Landmark size={12} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Op. banc.</>}
                      </span>
                    </td>
                    <td className={styles.colStatut}>{getStatutBadge(statusValue || 'EN_ATTENTE_COMMISSION')}</td>
                    <td className={styles.colDate}>{format(new Date(req.created_at), 'dd/MM/yyyy HH:mm')}</td>
                    <td className={styles.colActions}>
                      <div className={styles.actions}>
                        <RowActionsMenu
                          libelle={`Actions pour ${getDocumentReference(req)}`}
                          items={actionsLigne}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination unique, rendue meme quand la page est vide : sinon,
          arrive sur une page sans resultat, on ne peut plus revenir. */}
      <div className={styles.pagination}>
        <button
          type="button"
          className={styles.secondaryAction}
          onClick={() => setPageIndex((prev) => Math.max(0, prev - 1))}
          disabled={pageIndex === 0 || loading}
        >
          Précédent
        </button>
        <span className={styles.pageInfo}>Page {pageIndex + 1}</span>
        <button
          type="button"
          className={styles.secondaryAction}
          onClick={() => setPageIndex((prev) => prev + 1)}
          disabled={!hasMore || loading}
        >
          Suivant
        </button>
      </div>

      <div className={styles.mobileCards}>
        {filteredRequisitions.length === 0 ? (
          <div className={styles.emptyCards}>Aucune réquisition en attente de validation</div>
        ) : (
          filteredRequisitions.map((req) => {
            const statusValue = (req as any).status ?? req.statut
            const isRemboursementTransport = req.type_requisition === 'remboursement_transport'
            const canAct = pendingStatuses.includes(statusValue || 'EN_ATTENTE_COMMISSION')
            const isBusy = actionLoadingId === req.id
            const isAuthorizedBySelf = Boolean((req as any).validee_par && user?.id && String((req as any).validee_par) === String(user.id))
            const onOpenDetails = () =>
              isRemboursementTransport
                ? handleViewRemboursementDetails(req)
                : handleViewRequisitionDetails(req)

            return (
              <div
                key={`card-${req.id}`}
                className={styles.card}
                data-statut={String(statusValue || 'EN_ATTENTE_COMMISSION').toLowerCase()}
                role="button"
                tabIndex={0}
                onClick={onOpenDetails}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onOpenDetails()
                  }
                }}
              >
                <div className={styles.cardHeader}>
                  <div>
                    <div className={styles.cardTitle}>{getDocumentReference(req)}</div>
                    <div className={styles.cardSub}>{format(new Date(req.created_at), 'dd/MM/yyyy HH:mm')}</div>
                  </div>
                  <div className={styles.cardHeaderRight}>
                    {getStatutBadge(statusValue || 'EN_ATTENTE_COMMISSION')}
                  </div>
                </div>

                <div className={styles.cardBody}>
                  <div className={styles.cardAmountRow}>
                    <div className={styles.cardAmount}>{formatAmount(req.montant_total)}</div>
                    {getAiBadge(req.id)}
                  </div>
                  <div className={styles.cardGrid}>
                    <div>
                      <div className={styles.cardLabel}>Type</div>
                      <div className={styles.cardValue}>{getTypeBadge(req.type_requisition)}</div>
                    </div>
                    <div>
                      <div className={styles.cardLabel}>Demandeur</div>
                      <div className={styles.cardValue}>
                        {req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : 'N/A'}
                      </div>
                    </div>
                    <div className={styles.cardFull}>
                      <div className={styles.cardLabel}>Objet</div>
                      <div className={styles.cardValue}>{req.objet}</div>
                    </div>
                  </div>
                </div>

                <div className={styles.cardFooter}>
                  <span className={styles.cardHint}>Touchez pour voir le détail</span>
                  <span className={styles.cardChevron}>›</span>
                </div>

                {canAct && (
                  <div className={styles.cardActions}>
                    {authorizeStatuses.has(String(statusValue)) && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleAction('authorize', req)
                        }}
                        className={styles.validateBtn}
                        disabled={isBusy}
                      >
                        {isBusy && currentAction === 'authorize' ? 'Validation...' : <><Check size={14} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Valider</>}
                      </button>
                    )}
                    {viseStatuses.has(String(statusValue)) && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleAction('vise', req)
                        }}
                        className={isAuthorizedBySelf ? styles.viseDisabledBtn : styles.approveBtn}
                        disabled={isBusy || isAuthorizedBySelf}
                      >
                        {isBusy && currentAction === 'vise'
                          ? 'Validation 2/2...'
                          : isAuthorizedBySelf
                          ? <><Lock size={14} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Attente validation 2/2</>
                          : <><ShieldCheck size={14} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Validation 2/2</>}
                      </button>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleAction('reject', req)
                      }}
                      className={styles.rejectBtn}
                      disabled={isBusy}
                    >
                      {isBusy && currentAction === 'reject' ? 'Rejet...' : <><Ban size={14} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Rejeter</>}
                    </button>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {showActionModal && selectedRequisition && (
        selectedRequisition.type_requisition === 'remboursement_transport' ? (
          <RemboursementActionModal
            show={showActionModal}
            action={currentAction as 'reject'}
            remboursementNumber={remboursementNumber}
            requisitionNumber={selectedRequisition.numero_requisition}
            onConfirm={handleConfirm}
            onCancel={handleModalClose}
            userName={selectedRequisition.demandeur ? `${selectedRequisition.demandeur.prenom} ${selectedRequisition.demandeur.nom}` : undefined}
          />
        ) : (
          <RequisitionActionModal
            show={showActionModal}
            action={currentAction as 'reject'}
            requisitionNumber={selectedRequisition.numero_requisition}
            onConfirm={handleConfirm}
            onCancel={handleModalClose}
            userName={selectedRequisition.demandeur ? `${selectedRequisition.demandeur.prenom} ${selectedRequisition.demandeur.nom}` : undefined}
          />
        )
      )}

      {showDetailModal && selectedRemboursementDetails && (
        <div className={`${styles.modal} ${styles.detailModalOverlay}`}>
          <div className={`${styles.modalContent} ${styles.detailModalContent}`}>
            <div className={styles.modalHeader}>
              <h2>Détails du remboursement {selectedRemboursementDetails.numero_remboursement}</h2>
              <button onClick={() => setShowDetailModal(false)} className={styles.closeBtn} aria-label="Fermer"><X size={20} /></button>
            </div>

            <div className={styles.detailContent}>
              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedRemboursementDetails.numero_remboursement}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Date de réunion</label>
                    <p>{format(new Date(selectedRemboursementDetails.date_reunion), 'dd/MM/yyyy')}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Nature de réunion</label>
                    <p>{selectedRemboursementDetails.nature_reunion}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Lieu</label>
                    <p>{selectedRemboursementDetails.lieu}</p>
                  </div>
                  {selectedRemboursementDetails.heure_debut && (
                    <div className={styles.detailItem}>
                      <label>Heure de début</label>
                      <p>{selectedRemboursementDetails.heure_debut}</p>
                    </div>
                  )}
                  {selectedRemboursementDetails.heure_fin && (
                    <div className={styles.detailItem}>
                      <label>Heure de fin</label>
                      <p>{selectedRemboursementDetails.heure_fin}</p>
                    </div>
                  )}
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong className={styles.detailAmount}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></p>
                  </div>
                  {selectedRemboursementDetails.pdf_path && (
                    <div className={styles.detailItem}>
                      <label>Document officiel</label>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => openRemboursementPdf(selectedRemboursementDetails)}
                      >
                        Voir le PDF du remboursement
                      </button>
                    </div>
                  )}
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Repères budgétaires</h3>
                <div className={styles.budgetDecisionGrid}>
                  <div className={styles.budgetDecisionCard}>
                    <label>Budget</label>
                    <p><strong>{formatBudgetDecisionAmount(selectedRemboursementBudgetSummary.budget)}</strong></p>
                  </div>
                  <div className={styles.budgetDecisionCard}>
                    <label>Engagé</label>
                    <p><strong>{formatBudgetDecisionAmount(selectedRemboursementBudgetSummary.engaged)}</strong></p>
                  </div>
                  <div className={styles.budgetDecisionCard}>
                    <label>Disponible</label>
                    <p><strong>{formatBudgetDecisionAmount(selectedRemboursementBudgetSummary.available)}</strong></p>
                  </div>
                  <div className={styles.budgetDecisionCard}>
                    <label>Solde après cette demande</label>
                    <p><strong>{formatBudgetDecisionAmount(selectedRemboursementBudgetSummary.remainingAfterRequest)}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Participants</h3>
                <div className={styles.detailTableWrap}>
                  <table className={styles.detailTable}>
                    <thead>
                      <tr>
                        <th style={{ width: '40px' }}>N°</th>
                        <th>Nom</th>
                        <th>Titre/Fonction</th>
                        <th>Type</th>
                        <th className={styles.numCell}>Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedParticipants.map((participant, index) => (
                        <tr key={participant.id ?? `${participant.nom}-${participant.titre_fonction}`}>
                          <td style={{ textAlign: 'center', fontWeight: 600 }}>{index + 1}</td>
                          <td>{participant.nom}</td>
                          <td>{participant.titre_fonction}</td>
                          <td>
                            <span className={`${styles.participantType} ${participant.type_participant === 'assistant' ? styles.participantTypeAssistant : ''}`}>
                              {participant.type_participant === 'principal' ? 'Principal' : 'Assistant'}
                            </span>
                          </td>
                          <td className={styles.numCell}><strong>{formatCurrency(participant.montant)}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={4} className={styles.numCell} style={{fontWeight: 600}}>Total général</td>
                        <td className={styles.numCell}>
                          <strong className={styles.detailAmount}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong>
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {selectedDossier && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Dossier {selectedDossier.reference}</h2>
              <button onClick={() => setSelectedDossier(null)} className={styles.closeBtn} aria-label="Fermer"><X size={20} /></button>
            </div>
            <div className={styles.detailContent}>
              <div className={styles.detailSection}>
                <h3>Réquisitions du dossier</h3>
                <div className={styles.detailTableWrap}>
                  <table className={styles.detailTable}>
                    <thead>
                      <tr>
                        <th>Référence</th>
                        <th>Objet</th>
                        <th>Montant</th>
                        <th className={styles.detailActionsCol}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedDossier.requisitions || []).map((req, idx) => (
                        <tr key={`${req.montant_total}-${idx}`}>
                          <td>{getDocumentReference(req)}</td>
                          <td>{(req as any).objet || '-'}</td>
                          <td><strong>{formatCurrency((req as any).montant_total || 0)}</strong></td>
                          <td className={styles.detailActionsCol}>
                          <div className={styles.actions}>
                            {(req as any).type_requisition !== 'remboursement_transport' && (
                              <>
                                <button
                                  type="button"
                                  className={`${styles.detailBtn} ${styles.actionIconBtn}`}
                                  onClick={() => handleViewRequisitionDetails(req as any)}
                                  title="Voir les détails de la réquisition"
                                  aria-label="Voir les détails de la réquisition"
                                >
                                  <Search size={16} />
                                </button>
                                <button
                                  type="button"
                                  className={`${styles.printBtn} ${styles.actionIconBtn}`}
                                  onClick={() => handlePrintRequisition(req as any)}
                                  title="Imprimer la réquisition"
                                  aria-label="Imprimer la réquisition"
                                >
                                  <Printer size={16} />
                                </button>
                                <button
                                  type="button"
                                  className={`${styles.downloadBtn} ${styles.actionIconBtn}`}
                                  onClick={() => handleDownloadRequisition(req as any)}
                                  title="Télécharger la réquisition"
                                  aria-label="Télécharger la réquisition"
                                >
                                  <Download size={16} />
                                </button>
                              </>
                            )}
                            {(req as any).annexe?.id && (
                              <button
                                type="button"
                                onClick={() => openRequisitionAnnexe((req as any).annexe)}
                                className={`${styles.detailBtn} ${styles.actionIconBtn}`}

                                title="Voir la pièce jointe"
                                aria-label="Voir la pièce jointe"
                              >
                                <Eye size={16} />
                              </button>
                            )}
                            {authorizeStatuses.has(String((req as any).status ?? (req as any).statut)) && (
                              <button
                                type="button"
                                className={`${styles.validateBtn} ${styles.actionIconBtn}`}
                                onClick={() => handleAction('authorize', req as any)}
                              >
                                <Check size={16} />
                              </button>
                            )}
                            {viseStatuses.has(String((req as any).status ?? (req as any).statut)) && (
                              <button
                                type="button"
                                className={`${styles.approveBtn} ${styles.actionIconBtn}`}
                                onClick={() => handleAction('vise', req as any)}
                              >
                                <ShieldCheck size={16} />
                              </button>
                            )}
                            <button
                              type="button"
                              className={`${styles.rejectBtn} ${styles.actionIconBtn}`}
                              onClick={() => handleAction('reject', req as any)}
                            >
                              <Ban size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    </tbody>
                  </table>
                </div>
                <div className={styles.dossierFooter}>
                  <span>Total</span>
                  <strong>
                    {selectedDossier.requisitions
                      .reduce((sum, r) => sum + Number((r as any).montant_total || 0), 0)
                      .toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                  </strong>
                </div>
                <div className={styles.dossierActions}>
                  <Link to={`/requisitions/examen/${selectedDossier.id}`} className={styles.secondaryAction}>
                    Ouvrir le dossier
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
