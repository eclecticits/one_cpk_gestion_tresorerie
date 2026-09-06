import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Download, Eye, FileText, Paperclip, Pencil, RefreshCw, Search, X } from 'lucide-react'
import { apiRequest } from '../lib/apiClient'
import { getServices } from '../api/services'
// jsPDF/jspdf-autotable/xlsx sont lourds : chargement dynamique au moment de l'action.
type PdfGeneratorModule = typeof import('../utils/pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('../utils/pdfGenerator')
  return _pdfGeneratorModulePromise
}
const generateRequisitionsPDF: PdfGeneratorModule['generateRequisitionsPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateRequisitionsPDF(...args)
}
const generateSingleRequisitionPDF: PdfGeneratorModule['generateSingleRequisitionPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateSingleRequisitionPDF(...args)
}
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
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import BudgetDecisionTable from '../components/BudgetDecisionTable'
import RequisitionEditModal from '../components/RequisitionEditModal'
import { peutModifierRequisition } from '../utils/requisitionLock'
import { refreshRequisitionBonBeforeExamen } from '../utils/requisitionBon'
import type { Service } from '../types'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import RowActionsMenu, { type ActionLigne } from '../components/RowActionsMenu'
import PageHeader from '../components/PageHeader'
import BackButton from '../components/BackButton'
import styles from './DossiersExamen.module.css'

type Dossier = {
  id: string
  reference: string
  status: string
  commentaires_examen?: string | null
  requisitions: RequisitionLite[]
  created_by?: string | null
  created_at: string
}

type RequisitionLite = {
  id?: string
  numero_requisition?: string
  type_requisition?: string
  objet?: string
  montant_total?: number | string
  a_valoir?: boolean | null
  instance_beneficiaire?: string | null
  examen_status?: string
  examen_commentaire?: string | null
  examen_par?: string | null
  examen_le?: string | null
  validee_par?: string | null
  validee_le?: string | null
  approuvee_par?: string | null
  approuvee_le?: string | null
  created_at?: string
  service_id?: number | null
  examinateur?: UserInfo | null
  validateur?: UserInfo | null
  approbateur?: UserInfo | null
  demandeur?: { id?: string; prenom?: string | null; nom?: string | null; email?: string | null }
}

type UserInfo = {
  id?: string
  prenom?: string | null
  nom?: string | null
  email?: string | null
}

type RequisitionItem = {
  id: string
  numero_requisition: string
  type_requisition?: string
  objet: string
  montant_total?: number | string
  a_valoir?: boolean | null
  instance_beneficiaire?: string | null
  examen_status?: string
  examen_commentaire?: string | null
  examen_par?: string | null
  examen_le?: string | null
  validee_par?: string | null
  validee_le?: string | null
  approuvee_par?: string | null
  approuvee_le?: string | null
  created_at?: string
  annexe?: { id: string; filename?: string | null }
  service_id?: number | null
  examinateur?: UserInfo | null
  validateur?: UserInfo | null
  approbateur?: UserInfo | null
  demandeur?: { id?: string; prenom?: string | null; nom?: string | null; email?: string | null }
}

type TransportDocument = {
  id?: string
  numero_remboursement?: string | null
  reference_numero?: string | null
  participants?: any[] | null
  [key: string]: any
}

const statusLabels: Record<string, string> = {
  BROUILLON: 'Brouillon',
  NON_EXAMINE: 'Non examiné',
  EN_EXAMEN: 'En examen',
  TRAITEMENT: 'Traitement',
  EXAMINE: 'Examiné',
  REJETE: 'Rejeté',
}

const ACTIONABLE_EXAM_STATUS = 'EN_EXAMEN'

export default function DossiersExamen() {
  const navigate = useNavigate()
  const confirm = useConfirm()
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [dossiers, setDossiers] = useState<Dossier[]>([])
  const [requisitions, setRequisitions] = useState<RequisitionItem[]>([])
  const [transportsByReqId, setTransportsByReqId] = useState<Record<string, TransportDocument>>({})

  const formatCurrency = (amount: any) => {
    return Number(amount || 0).toLocaleString('fr-FR', {
      style: 'currency',
      currency: 'USD',
    })
  }

  const getLignePosteLabel = (ligne: any) => {
    if (!ligne) return 'N/A'
    if (ligne.rubrique_libelle) return `${ligne.rubrique_code || ''} - ${ligne.rubrique_libelle}`
    if (ligne.rubrique) return ligne.rubrique
    return 'N/A'
  }

  const [selectedReqDetail, setSelectedReqDetail] = useState<RequisitionItem | null>(null)
  const [selectedReqLignes, setSelectedReqLignes] = useState<any[]>([])
  const [selectedReqBudgetLines, setSelectedReqBudgetLines] = useState<any[]>([])
  const [requisitionAModifier, setRequisitionAModifier] = useState<any | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [commentMode, setCommentMode] = useState<'validate' | 'reject' | null>(null)
  const [commentReq, setCommentReq] = useState<RequisitionItem | null>(null)
  const [commentText, setCommentText] = useState('')
  const [previewReq, setPreviewReq] = useState<RequisitionItem | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [dossierStatusFilter, setDossierStatusFilter] = useState('all')
  const [requisitionStatusFilter, setRequisitionStatusFilter] = useState('EN_EXAMEN')
  const [serviceFilter, setServiceFilter] = useState('all')
  const [demandeurFilter, setDemandeurFilter] = useState('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [services, setServices] = useState<Service[]>([])
  const [dossierPage, setDossierPage] = useState(0)
  const [requisitionPage, setRequisitionPage] = useState(0)
  const pageSize = 20

  const [selectedDossiers, setSelectedDossiers] = useState<Set<string>>(new Set())
  const [selectedRequisitions, setSelectedRequisitions] = useState<Set<string>>(new Set())
  const [bulkAction, setBulkAction] = useState<'validate' | 'reject' | null>(null)
  const [bulkComment, setBulkComment] = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [exporting, setExporting] = useState<'pdf' | 'excel' | null>(null)

  const parseDateValue = (value?: string) => {
    if (!value) return 0
    const parsed = Date.parse(value)
    if (!Number.isNaN(parsed)) return parsed
    const match = value.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/)
    if (!match) return 0
    const [, day, month, year, hh = '0', mm = '0', ss = '0'] = match
    const asDate = new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hh),
      Number(mm),
      Number(ss)
    )
    const ts = asDate.getTime()
    return Number.isNaN(ts) ? 0 : ts
  }

  const getDemandeurName = (demandeur?: { prenom?: string | null; nom?: string | null }) => {
    return [demandeur?.prenom, demandeur?.nom].filter(Boolean).join(' ').toLowerCase()
  }

  const getServiceLabel = (serviceId?: number | null) => {
    if (!serviceId) return ''
    const service = services.find((s) => s.id === serviceId)
    if (!service) return `Service ${serviceId}`
    return service.libelle || service.code || `Service ${serviceId}`
  }

  const getExamStatus = (req: RequisitionLite) => String(req.examen_status || '').toUpperCase()

  const isRequisitionActionable = (req: RequisitionLite) => getExamStatus(req) === ACTIONABLE_EXAM_STATUS

  const getDossierExamSummary = (dossier: Dossier) => {
    const requisitionList = dossier.requisitions || []
    const waiting = requisitionList.filter(isRequisitionActionable).length
    const approved = requisitionList.filter((req) => getExamStatus(req) === 'EXAMINE').length
    const rejected = requisitionList.filter((req) => getExamStatus(req) === 'REJETE').length
    const blocked = requisitionList.length - waiting - approved - rejected
    return {
      total: requisitionList.length,
      waiting,
      approved,
      rejected,
      blocked,
      actionable: String(dossier.status || '').toUpperCase() === 'EN_EXAMEN' && waiting === requisitionList.length && requisitionList.length > 0,
    }
  }

  const buildReqSearchText = (req: RequisitionLite) => {
    const documentRef = req.id ? getDocumentReference(req) : req.numero_requisition
    return [
      documentRef,
      req.objet,
      req.examen_status,
      getDocumentTypeLabel(req),
      getDemandeurName(req.demandeur),
    ]
      .join(' ')
      .toLowerCase()
  }

  const loadDossiers = async () => {
    setLoading(true)
    try {
      const res: any = await apiRequest('GET', '/dossiers', {
        params: {
          include_requisitions: true,
          include_users: 'demandeur,validateur,approbateur,examinateur',
          order: 'created_at.desc',
          limit: 200,
        },
      })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setDossiers(items)
      const enExam: any = await apiRequest('GET', '/requisitions', {
        params: {
          dossier_is_null: true,
          include: 'demandeur,validateur,approbateur,examinateur',
          order: 'created_at.desc',
          limit: 500,
        },
      })
      const listB = Array.isArray(enExam) ? enExam : (enExam?.items ?? [])
      setRequisitions(listB)
      try {
        const transportsRes: any = await apiRequest('GET', '/remboursements-transport', {
          params: { include: 'participants', limit: 200 },
        })
        const transports = Array.isArray(transportsRes) ? transportsRes : (transportsRes?.items ?? [])
        const transportRefs: Record<string, TransportDocument> = {}
        transports.forEach((transport: any) => {
          if (!transport?.requisition_id) return
          transportRefs[String(transport.requisition_id)] = transport
        })
        setTransportsByReqId(transportRefs)
      } catch (transportError) {
        console.error(
          'Error loading transport references:',
          transportError instanceof Error ? transportError.message : transportError
        )
        setTransportsByReqId({})
      }
      setSelectedDossiers(new Set())
      setSelectedRequisitions(new Set())
    } catch (error) {
      console.error('Error loading dossiers:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de charger les dossiers d'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    } finally {
      setLoading(false)
    }
  }

  function getDocumentReference(req: RequisitionLite) {
    if (isTransportDocument(req)) {
      const rt = (req as any).remboursement_transport
      if (rt) {
        return rt.reference_numero || rt.numero_remboursement || req.numero_requisition || '-'
      }
      if (req.id) {
        const transportRef = transportsByReqId[String(req.id)]
        return transportRef?.reference_numero || transportRef?.numero_remboursement || req.numero_requisition || '-'
      }
    }
    return req.numero_requisition || '-'
  }

  function isTransportDocument(req: RequisitionLite) {
    return String(req.type_requisition || '').toLowerCase() === 'remboursement_transport'
  }

  function getDocumentTypeLabel(req: RequisitionLite) {
    return isTransportDocument(req) ? 'Remboursement transport' : 'Réquisition'
  }

  const getTransportForRequisition = async (req: RequisitionLite) => {
    if (!req.id) return null
    const existing = transportsByReqId[String(req.id)]
    if (existing) return existing
    const res: any = await apiRequest('GET', '/remboursements-transport', {
      params: { requisition_id: req.id, include: 'participants', limit: 1 },
    })
    const transport = Array.isArray(res) ? res[0] : (res?.items?.[0] ?? null)
    if (transport) {
      setTransportsByReqId((prev) => ({ ...prev, [String(req.id)]: transport }))
    }
    return transport
  }

  const loadDocumentLines = async (req: RequisitionItem) => {
    if (isTransportDocument(req)) {
      const transport = await getTransportForRequisition(req)
      if (!transport) return []
      if (Array.isArray(transport.participants)) return transport.participants
      const participantsRes: any = await apiRequest('GET', '/participants-transport', {
        params: { remboursement_id: transport.id, limit: 500 },
      })
      return Array.isArray(participantsRes) ? participantsRes : (participantsRes?.items ?? [])
    }
    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
    return Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
  }

  const loadRequisitionBudgetLines = async (reqId: string) => {
    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: reqId } })
    return Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
  }

  const loadServices = async () => {
    try {
      const res = await getServices({ active: true })
      const items = Array.isArray(res) ? res : []
      setServices(items.sort((a, b) => (a.libelle || '').localeCompare(b.libelle || '')))
    } catch (error) {
      console.error('Error loading services:', error)
    }
  }

  useEffect(() => {
    loadDossiers()
    loadServices()
  }, [])

  const openCommentModal = (mode: 'validate' | 'reject', req: RequisitionItem) => {
    setCommentMode(mode)
    setCommentReq(req)
    setCommentText('')
  }

  const closeCommentModal = () => {
    setCommentMode(null)
    setCommentReq(null)
    setCommentText('')
  }

  const confirmCommentAction = async () => {
    if (!commentMode || !commentReq) return
    const commentaire = commentText.trim() || null
    try {
      if (commentMode === 'validate') {
        // Le mail au Bureau part depuis validate-examen avec le bon stocké : on
        // le régénère d'abord pour qu'il porte le nom de l'examinateur.
        if (!isTransportDocument(commentReq)) {
          await refreshRequisitionBonBeforeExamen(commentReq, user)
        }
        await apiRequest('POST', `/requisitions/${commentReq.id}/validate-examen`, { commentaire })
      } else {
        await apiRequest('POST', `/requisitions/${commentReq.id}/reject-examen`, { commentaire })
      }
      closeCommentModal()
      await loadDossiers()
    } catch (error) {
      console.error('Error examen action:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de terminer l'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const viewDetails = async (req: RequisitionItem) => {
    setSelectedReqDetail(req)
    setDetailLoading(true)
    try {
      const [budgetLines, lignes] = await Promise.all([
        loadRequisitionBudgetLines(req.id),
        loadDocumentLines(req),
      ])
      setSelectedReqBudgetLines(budgetLines)
      setSelectedReqLignes(lignes)
    } catch (error) {
      console.error('Error loading requisition details:', error)
      setSelectedReqBudgetLines([])
      setSelectedReqLignes([])
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetails = () => {
    setSelectedReqDetail(null)
    setSelectedReqLignes([])
    setSelectedReqBudgetLines([])
    setDetailLoading(false)
  }

  const openRequisitionAnnexe = async (annexe?: { id: string; filename?: string | null } | null) => {
    if (!annexe?.id) return
    try {
      if (annexe.filename) {
        await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
      } else {
        await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
      }
    } catch (error) {
      console.error('Error opening annex:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible d'ouvrir la pièce jointe.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const printRequisition = async (req: RequisitionItem) => {
    try {
      const lignes = await loadDocumentLines(req)
      if (isTransportDocument(req)) {
        const transport = await getTransportForRequisition(req)
        if (!transport) throw new Error('Remboursement transport introuvable')
        await generateRemboursementTransportPDF(transport, lignes, 'print', '')
        return
      }
      await generateSingleRequisitionPDF(req as any, lignes, 'print', '')
    } catch (error) {
      console.error('Error printing requisition:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible d’imprimer la réquisition.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const downloadRequisition = async (req: RequisitionItem) => {
    try {
      const lignes = await loadDocumentLines(req)
      if (isTransportDocument(req)) {
        const transport = await getTransportForRequisition(req)
        if (!transport) throw new Error('Remboursement transport introuvable')
        await generateRemboursementTransportPDF(transport, lignes, 'download', '')
        return
      }
      await generateSingleRequisitionPDF(req as any, lignes, 'download', '')
    } catch (error) {
      console.error('Error downloading requisition:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible de télécharger la réquisition.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const openPreview = async (req: RequisitionItem) => {
    setPreviewReq(req)
    setPreviewLoading(true)
    try {
      const lignes = await loadDocumentLines(req)
      let blob: any
      if (isTransportDocument(req)) {
        let transport = (req as any).remboursement_transport
        if (!transport) {
          transport = await getTransportForRequisition(req)
        }
        if (!transport) throw new Error('Remboursement transport introuvable')
        blob = await generateRemboursementTransportPDF(transport, lignes, 'blob', '')
      } else {
        blob = await generateSingleRequisitionPDF(req as any, lignes, 'blob', '')
      }
      if (blob) {
        const url = URL.createObjectURL(blob)
        setPreviewUrl(url)
      }
    } catch (error) {
      console.error('Error previewing requisition:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible de prévisualiser la réquisition.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    } finally {
      setPreviewLoading(false)
    }
  }

  const closePreview = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(null)
    setPreviewReq(null)
    setPreviewLoading(false)
  }

  const toggleDossier = (id: string) => {
    const dossier = dossiers.find((item) => item.id === id)
    if (!dossier || !getDossierExamSummary(dossier).actionable) return
    setSelectedDossiers((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleRequisition = (id: string) => {
    const requisition = requisitions.find((item) => item.id === id)
    if (!requisition || !isRequisitionActionable(requisition)) return
    setSelectedRequisitions((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const startTs = useMemo(() => (dateStart ? new Date(`${dateStart}T00:00:00`).getTime() : null), [dateStart])
  const endTs = useMemo(() => (dateEnd ? new Date(`${dateEnd}T23:59:59`).getTime() : null), [dateEnd])

  const matchesDateRange = (value?: string) => {
    if (!startTs && !endTs) return true
    const ts = parseDateValue(value)
    if (!ts) return false
    if (startTs && ts < startTs) return false
    if (endTs && ts > endTs) return false
    return true
  }

  const matchesRequisitionFilters = useCallback((req: RequisitionLite) => {
    const exam = getExamStatus(req)
    if (requisitionStatusFilter !== 'all' && exam !== requisitionStatusFilter) return false
    if (!matchesDateRange(req.created_at)) return false
    if (serviceFilter !== 'all' && String(req.service_id ?? '') !== serviceFilter) return false
    const demandeurNeedle = demandeurFilter.trim().toLowerCase()
    if (demandeurNeedle && !getDemandeurName(req.demandeur).includes(demandeurNeedle)) return false
    const needle = searchQuery.trim().toLowerCase()
    if (!needle) return true
    return buildReqSearchText(req).includes(needle)
  }, [requisitionStatusFilter, startTs, endTs, serviceFilter, demandeurFilter, searchQuery, services, transportsByReqId])

  const filteredDossiers = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase()
    const demandeurNeedle = demandeurFilter.trim().toLowerCase()
    const requisitionExamFilter = requisitionStatusFilter !== 'all'
    const list = dossiers.filter((dossier) => {
      const status = String(dossier.status || '').toUpperCase()
      const dossierRequisitions = dossier.requisitions || []
      if (dossierStatusFilter !== 'all' && status !== dossierStatusFilter) return false
      if (!matchesDateRange(dossier.created_at)) return false
      if (requisitionExamFilter) {
        const matchExam = dossierRequisitions.some(
          (req) => getExamStatus(req) === requisitionStatusFilter
        )
        if (!matchExam) return false
      }
      if (serviceFilter !== 'all') {
        const matchService = dossierRequisitions.some(
          (req) => String(req.service_id ?? '') === serviceFilter
        )
        if (!matchService) return false
      }
      if (demandeurNeedle) {
        const matchDemandeur = dossierRequisitions.some((req) =>
          getDemandeurName(req.demandeur).includes(demandeurNeedle)
        )
        if (!matchDemandeur) return false
      }
      if (!needle) return true
      const dossierMatch = [dossier.reference, status, dossier.created_by || '']
        .join(' ')
        .toLowerCase()
        .includes(needle)
      if (dossierMatch) return true
      return dossierRequisitions.some((req) => {
        return buildReqSearchText(req).includes(needle)
      })
    })
    return [...list].sort((a, b) => parseDateValue(b.created_at) - parseDateValue(a.created_at))
  }, [
    dossiers,
    searchQuery,
    dossierStatusFilter,
    requisitionStatusFilter,
    serviceFilter,
    demandeurFilter,
    startTs,
    endTs,
  ])

  const filteredRequisitions = useMemo(() => {
    const list = requisitions.filter((req) => matchesRequisitionFilters(req))
    return [...list].sort((a, b) => parseDateValue(b.created_at) - parseDateValue(a.created_at))
  }, [
    requisitions,
    matchesRequisitionFilters,
    requisitionStatusFilter,
    serviceFilter,
    demandeurFilter,
    startTs,
    endTs,
  ])

  const dossierTotalPages = Math.max(1, Math.ceil(filteredDossiers.length / pageSize))
  const requisitionTotalPages = Math.max(1, Math.ceil(filteredRequisitions.length / pageSize))
  const pagedDossiers = filteredDossiers.slice(dossierPage * pageSize, (dossierPage + 1) * pageSize)
  const pagedRequisitions = filteredRequisitions.slice(
    requisitionPage * pageSize,
    (requisitionPage + 1) * pageSize
  )

  useEffect(() => {
    setDossierPage(0)
    setRequisitionPage(0)
    setSelectedDossiers(new Set())
    setSelectedRequisitions(new Set())
  }, [searchQuery, dossierStatusFilter, requisitionStatusFilter, serviceFilter, demandeurFilter, dateStart, dateEnd])

  const actionableDossiers = useMemo(
    () => filteredDossiers.filter((dossier) => getDossierExamSummary(dossier).actionable),
    [filteredDossiers]
  )
  const actionableRequisitions = useMemo(
    () => filteredRequisitions.filter(isRequisitionActionable),
    [filteredRequisitions]
  )
  const selectedActionableDossierIds = useMemo(
    () => actionableDossiers.filter((dossier) => selectedDossiers.has(dossier.id)).map((dossier) => dossier.id),
    [actionableDossiers, selectedDossiers]
  )
  const selectedActionableRequisitionIds = useMemo(
    () => actionableRequisitions.filter((req) => selectedRequisitions.has(req.id)).map((req) => req.id),
    [actionableRequisitions, selectedRequisitions]
  )
  const allDossiersSelected =
    actionableDossiers.length > 0 && actionableDossiers.every((d) => selectedDossiers.has(d.id))
  const allRequisitionsSelected =
    actionableRequisitions.length > 0 && actionableRequisitions.every((r) => selectedRequisitions.has(r.id))
  const selectedCount = selectedActionableDossierIds.length + selectedActionableRequisitionIds.length
  const hasFilters =
    searchQuery.trim() !== '' ||
    dossierStatusFilter !== 'all' ||
    requisitionStatusFilter !== 'all' ||
    serviceFilter !== 'all' ||
    demandeurFilter.trim() !== '' ||
    dateStart !== '' ||
    dateEnd !== ''

  const resetFilters = () => {
    setSearchQuery('')
    setDossierStatusFilter('all')
    setRequisitionStatusFilter(ACTIONABLE_EXAM_STATUS)
    setServiceFilter('all')
    setDemandeurFilter('')
    setDateStart('')
    setDateEnd('')
  }

  const totalDossierAmount = useMemo(
    () =>
      filteredDossiers.reduce(
        (sum, dossier) =>
          sum +
          (dossier.requisitions || []).reduce((reqSum, req) => reqSum + Number(req.montant_total || 0), 0),
        0
      ),
    [filteredDossiers]
  )

  const totalIndividualAmount = useMemo(
    () => filteredRequisitions.reduce((sum, req) => sum + Number(req.montant_total || 0), 0),
    [filteredRequisitions]
  )

  const handleExportPDF = async () => {
    if (exporting) return
    setExporting('pdf')
    try {
      const requisitionsFromDossiers = filteredDossiers.flatMap((dossier) =>
        (dossier.requisitions || []).filter((req) => matchesRequisitionFilters(req))
      )
      const merged = [...filteredRequisitions, ...requisitionsFromDossiers]
      const seen = new Set<string>()
      const unique = merged.filter((req) => {
        const key = String(req.id || req.numero_requisition || '')
        if (!key) return false
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      if (unique.length === 0) {
        await confirm({
          title: 'Information',
          description: 'Aucune réquisition correspondant aux filtres.',
          confirmText: 'OK',
          hideCancel: true,
          variant: 'default',
        })
        return
      }

      const fallbackDate = new Date().toISOString().slice(0, 10)
      const createdDates = unique
        .map((req) => req.created_at)
        .filter(Boolean)
        .map((value) => new Date(String(value)).toISOString().slice(0, 10))
      const sortedDates = createdDates.length ? [...createdDates].sort() : []
      const minDate = sortedDates.length ? sortedDates[0] : fallbackDate
      const maxDate = sortedDates.length ? sortedDates[sortedDates.length - 1] : fallbackDate
      const dateDebut = dateStart || minDate
      const dateFin = dateEnd || maxDate

      const dataForPDF = await Promise.all(
        unique.map(async (req) => {
          let posteBudgetaire = ''
          try {
            const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
            const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
            posteBudgetaire = lignesData
              ? [...new Set(lignesData.map((l: any) => l.rubrique))].join(', ')
              : ''
          } catch {
            posteBudgetaire = ''
          }
          return { ...req, poste_budgetaire: posteBudgetaire }
        })
      )

      await generateRequisitionsPDF(dataForPDF as any[], dateDebut, dateFin, '')
    } catch (error) {
      console.error('Error exporting requisitions PDF:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible d'exporter le PDF.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    } finally {
      setExporting(null)
    }
  }

  const handleExportExcel = async () => {
    if (exporting) return
    setExporting('excel')
    try {
      const XLSX = await import('xlsx')
      const dossierRefByReqId = new Map<string, string>()
      filteredDossiers.forEach((dossier) => {
        ;(dossier.requisitions || []).forEach((req) => {
          if (req.id) dossierRefByReqId.set(req.id, dossier.reference)
        })
      })

      const requisitionsFromDossiers = filteredDossiers.flatMap((dossier) =>
        (dossier.requisitions || []).filter((req) => matchesRequisitionFilters(req))
      )
      const merged = [...filteredRequisitions, ...requisitionsFromDossiers]
      const seen = new Set<string>()
      const unique = merged.filter((req) => {
        const key = String(req.id || req.numero_requisition || '')
        if (!key) return false
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      if (unique.length === 0) {
        await confirm({
          title: 'Information',
          description: 'Aucune réquisition correspondant aux filtres.',
          confirmText: 'OK',
          hideCancel: true,
          variant: 'default',
        })
        return
      }

      const formatDate = (value?: string) => {
        if (!value) return ''
        const parsed = new Date(value)
        if (Number.isNaN(parsed.getTime())) return ''
        return parsed.toLocaleDateString('fr-FR')
      }

      const formatDateTime = (value?: string | null) => {
        if (!value) return 'Non renseignée'
        const parsed = new Date(value)
        if (Number.isNaN(parsed.getTime())) return 'Non renseignée'
        return parsed.toLocaleString('fr-FR', {
          day: '2-digit',
          month: '2-digit',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
      }

      const userLabel = (person?: UserInfo | null, fallback?: string | null) => {
        const name = person
          ? `${person.prenom || ''} ${person.nom || ''}`.trim()
          : ''
        return name || person?.email || fallback || 'Non renseigné'
      }

      const buildValidationComment = (req: RequisitionLite) => {
        const entries: string[] = []
        if (req.examen_commentaire || req.examen_par || req.examen_le) {
          entries.push([
            'Examen',
            `Auteur : ${userLabel(req.examinateur, req.examen_par)}`,
            `Date et heure : ${formatDateTime(req.examen_le)}`,
            `Commentaire : ${(req.examen_commentaire || 'Aucun commentaire').trim()}`,
          ].join('\n'))
        }
        if (req.validee_par || req.validee_le) {
          entries.push([
            'Validation technique',
            `Auteur : ${userLabel(req.validateur, req.validee_par)}`,
            `Date et heure : ${formatDateTime(req.validee_le)}`,
          ].join('\n'))
        }
        if (req.approuvee_par || req.approuvee_le) {
          entries.push([
            'Approbation / visa',
            `Auteur : ${userLabel(req.approbateur, req.approuvee_par)}`,
            `Date et heure : ${formatDateTime(req.approuvee_le)}`,
          ].join('\n'))
        }
        return entries.join('\n\n')
      }

      const rows = unique.map((req) => {
        const dossierRef = req.id ? dossierRefByReqId.get(req.id) : ''
        const exam = String(req.examen_status || '').toUpperCase()
        const demandeurLabel = req.demandeur
          ? `${req.demandeur.prenom || ''} ${req.demandeur.nom || ''}`.trim()
          : ''
        return {
          Dossier: dossierRef || '',
          'Type': getDocumentTypeLabel(req),
          'Référence': getDocumentReference(req),
          'Date création': formatDate(req.created_at),
          Objet: req.objet || '',
          'Montant (USD)': Number(req.montant_total || 0),
          'À valoir': req.a_valoir ? (req.instance_beneficiaire || '') : 'Non',
          'Statut examen': statusLabels[exam] || exam || 'Non examiné',
          Service: getServiceLabel(req.service_id),
          Demandeur: demandeurLabel,
        }
      })

      const ws = XLSX.utils.json_to_sheet(rows)
      // Annotation Excel native : le triangle rouge apparaît sur l'objet de la
      // réquisition, comme pour les commentaires des lignes budgétaires.
      unique.forEach((req, index) => {
        const commentaire = buildValidationComment(req).trim()
        if (!commentaire) return
        const cellRef = `E${index + 2}`
        const cell = ws[cellRef] || (ws[cellRef] = { t: 's', v: '' })
        cell.c = [{ a: 'ONEC', t: commentaire }]
      })
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Examen Réquisitions')

      const suffix = dateStart || dateEnd
        ? `_${dateStart || 'debut'}_${dateEnd || 'fin'}`
        : `_${new Date().toISOString().slice(0, 10)}`
      XLSX.writeFile(wb, `examen_requisitions${suffix}.xlsx`)
    } catch (error) {
      console.error('Error exporting Excel:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible d'exporter le fichier Excel.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    } finally {
      setExporting(null)
    }
  }

  const openBulkAction = (action: 'validate' | 'reject') => {
    if (selectedCount === 0) {
      void confirm({
        title: 'Information',
        description: 'Aucun dossier ou document en examen sélectionné.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'default',
      })
      return
    }
    setBulkAction(action)
    setBulkComment('')
  }

  const closeBulkAction = () => {
    setBulkAction(null)
    setBulkComment('')
  }

  const confirmBulkAction = async () => {
    if (!bulkAction) return
    const commentaire = bulkComment.trim() || null
    const dossierIds = selectedActionableDossierIds
    const requisitionIds = selectedActionableRequisitionIds
    setBulkLoading(true)
    try {
      await Promise.all([
        ...dossierIds.map((id) =>
          apiRequest('POST', `/dossiers/${id}/${bulkAction}-examen`, { commentaires_examen: commentaire })
        ),
        ...requisitionIds.map((id) =>
          apiRequest('POST', `/requisitions/${id}/${bulkAction}-examen`, { commentaire })
        ),
      ])
      closeBulkAction()
      await loadDossiers()
    } catch (error) {
      console.error('Error bulk examen action:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible d'appliquer l'action à la sélection.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    } finally {
      setBulkLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <PageHeader
          title="Validation des examens"
          subtitle="Contrôle des dossiers et documents passés à l'étape d'examen"
          actions={
            <div className={styles.headerActions}>
              <BackButton fallback="/validation" />
              <button type="button" className={styles.secondaryBtn} onClick={loadDossiers} disabled={loading}>
                <RefreshCw size={14} />
                Rafraîchir
              </button>
            </div>
          }
        />

        <div className={styles.kpiGrid}>
          <div className={styles.kpiCard}>
            <div className={styles.kpiLabel}>Dossiers filtrés</div>
            <div className={styles.kpiValue}>{filteredDossiers.length}</div>
            <div className={styles.kpiHint}>{formatCurrency(totalDossierAmount)}</div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiLabel}>Documents individuels</div>
            <div className={styles.kpiValue}>{filteredRequisitions.length}</div>
            <div className={styles.kpiHint}>{formatCurrency(totalIndividualAmount)}</div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiLabel}>À traiter</div>
            <div className={styles.kpiValue}>{actionableDossiers.length + actionableRequisitions.length}</div>
            <div className={styles.kpiHint}>éléments en examen</div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiLabel}>Sélection</div>
            <div className={styles.kpiValue}>{selectedCount}</div>
            <div className={styles.kpiHint}>actionnable</div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiLabel}>Montant cumulé</div>
            <div className={styles.kpiValue}>{formatCurrency(totalDossierAmount + totalIndividualAmount)}</div>
            <div className={styles.kpiHint}>dossiers + documents</div>
          </div>
        </div>

      <div className={styles.controlPanel}>
        <div className={styles.panelRow}>
          <div className={styles.searchWrap}>
            <Search size={16} className={styles.searchIcon} />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Rechercher un dossier ou une réquisition..."
              className={styles.searchInput}
              aria-label="Rechercher un dossier ou une réquisition"
            />
          </div>

          <button
            type="button"
            className={styles.filterReset}
            onClick={resetFilters}
            disabled={!hasFilters}
          >
            Réinitialiser
          </button>

          <div className={styles.statusbar}>
            <span className={`${styles.statusStep} ${styles.statusStepMuted}`}>Brouillon</span>
            <span className={`${styles.statusStep} ${styles.statusStepActive}`}>Examen</span>
            <span className={`${styles.statusStep} ${styles.statusStepMuted}`}>Bureau</span>
          </div>
        </div>
        <div className={styles.filterRow}>
          <div className={styles.filterGroup}>
            <label className={styles.filterLabel}>Statut du dossier</label>
            <select
              value={dossierStatusFilter}
              onChange={(event) => setDossierStatusFilter(event.target.value)}
              className={styles.filterSelect}
            >
              <option value="all">Tous</option>
              <option value="BROUILLON">Brouillon</option>
              <option value="EN_EXAMEN">En examen</option>
              <option value="TRAITEMENT">Traitement</option>
              <option value="REJETE">Rejeté</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label className={styles.filterLabel}>Statut du document</label>
            <select
              value={requisitionStatusFilter}
              onChange={(event) => setRequisitionStatusFilter(event.target.value)}
              className={styles.filterSelect}
            >
              <option value="all">Tous</option>
              <option value="NON_EXAMINE">Non examiné</option>
              <option value="EN_EXAMEN">En examen</option>
              <option value="EXAMINE">Examiné</option>
              <option value="REJETE">Rejeté</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label className={styles.filterLabel}>Service</label>
            <select
              value={serviceFilter}
              onChange={(event) => setServiceFilter(event.target.value)}
              className={styles.filterSelect}
            >
              <option value="all">Tous</option>
              {services.map((service) => (
                <option key={service.id} value={String(service.id)}>
                  {service.libelle || service.code || `Service ${service.id}`}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label className={styles.filterLabel}>Demandeur</label>
            <input
              type="text"
              value={demandeurFilter}
              onChange={(event) => setDemandeurFilter(event.target.value)}
              placeholder="Nom ou prénom..."
              className={styles.filterInput}
            />
          </div>
          <div className={`${styles.filterGroup} ${styles.filterGroupDates}`}>
            <label className={styles.filterLabel}>Plage de dates</label>
            <div className={styles.filterDateRange}>
              <input
                type="date"
                value={dateStart}
                onChange={(event) => setDateStart(event.target.value)}
                className={styles.filterInput}
                aria-label="Date de début"
              />
              <span className={styles.filterDateSep}>→</span>
              <input
                type="date"
                value={dateEnd}
                onChange={(event) => setDateEnd(event.target.value)}
                className={styles.filterInput}
                aria-label="Date de fin"
              />
            </div>
          </div>
        </div>
      </div>

      <div className={styles.actionBar}>
        <button
          type="button"
          className={styles.actionPrimary}
          onClick={() => openBulkAction('validate')}
          disabled={selectedCount === 0 || bulkLoading}
        >
          <Check size={14} />
          Valider la sélection
          {selectedCount > 0 && <span className={styles.actionCount}>{selectedCount}</span>}
        </button>
        <button
          type="button"
          className={styles.actionGhost}
          onClick={() => openBulkAction('reject')}
          disabled={selectedCount === 0 || bulkLoading}
        >
          <X size={14} />
          Rejeter
        </button>
        <button type="button" className={styles.actionGhost} onClick={loadDossiers} disabled={loading}>
          <RefreshCw size={14} />
          Rafraîchir
        </button>
        <button
          type="button"
          className={styles.actionGhost}
          onClick={handleExportPDF}
          disabled={exporting !== null}
        >
          <FileText size={14} />
          {exporting === 'pdf' ? 'Export PDF…' : 'Exporter PDF'}
        </button>
        <button
          type="button"
          className={styles.actionGhost}
          onClick={handleExportExcel}
          disabled={exporting !== null}
        >
          <Download size={14} />
          {exporting === 'excel' ? 'Export Excel…' : 'Exporter Excel'}
        </button>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Dossiers d'examen</div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead className={styles.thead}>
              <tr>
                <th className={styles.checkboxCell}>
                  <input
                    type="checkbox"
                    className={styles.checkbox}
                    checked={allDossiersSelected}
                    onChange={(event) => {
                      if (event.target.checked) {
                        setSelectedDossiers(new Set(actionableDossiers.map((d) => d.id)))
                      } else {
                        setSelectedDossiers(new Set())
                      }
                    }}
                    aria-label="Sélectionner tous les dossiers"
                  />
                </th>
                <th>Référence</th>
                <th>Statut</th>
                <th>Réquisitions</th>
                <th className={styles.amountHeader}>Montant total</th>
                <th>Créé le</th>
                <th className={styles.actionsHeader}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className={styles.empty}>Chargement...</td>
                </tr>
              ) : pagedDossiers.length === 0 ? (
                <tr>
                  <td colSpan={7} className={styles.empty}>Aucun dossier trouvé</td>
                </tr>
              ) : (
                pagedDossiers.map((dossier) => {
                  const total = (dossier.requisitions || []).reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
                  const status = String(dossier.status || '').toUpperCase()
                  const examSummary = getDossierExamSummary(dossier)
                  return (
                    <tr key={dossier.id} className={`${styles.tableRow} ${!examSummary.actionable ? styles.tableRowMuted : ''}`}>
                      <td className={styles.checkboxCell}>
                        <input
                          type="checkbox"
                          className={styles.checkbox}
                          checked={selectedDossiers.has(dossier.id)}
                          onChange={() => toggleDossier(dossier.id)}
                          disabled={!examSummary.actionable}
                          aria-label={`Sélectionner ${dossier.reference}`}
                        />
                      </td>
                      <td className={styles.refCell}>{dossier.reference}</td>
                      <td>
                        <span
                          className={`${styles.badgePill} ${
                            status === 'EXAMINE'
                              ? styles.statusApproved
                              : status === 'EN_EXAMEN'
                              ? styles.statusWaiting
                              : status === 'REJETE'
                              ? styles.statusRejected
                              : styles.statusDraft
                          }`}
                        >
                          {statusLabels[status] || status}
                        </span>
                      </td>
                      <td>
                        <div className={styles.requisitionCount}>{examSummary.total}</div>
                        <div className={styles.requisitionStatusHint}>
                          {examSummary.waiting} en examen
                          {examSummary.approved > 0 ? ` • ${examSummary.approved} examinée${examSummary.approved > 1 ? 's' : ''}` : ''}
                          {examSummary.rejected > 0 ? ` • ${examSummary.rejected} rejetée${examSummary.rejected > 1 ? 's' : ''}` : ''}
                        </div>
                      </td>
                      <td className={styles.amount}>
                        {total.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                      </td>
                      <td>{new Date(dossier.created_at).toLocaleDateString('fr-FR')}</td>
                      <td className={styles.actionsCell}>
                        <div className={styles.actionGroup}>
                          <RowActionsMenu
                            libelle={`Actions pour le dossier ${dossier.reference}`}
                            items={[
                              {
                                cle: 'ouvrir',
                                libelle: 'Ouvrir le dossier',
                                icone: <Eye size={15} />,
                                onSelect: () => navigate(`/requisitions/examen/${dossier.id}`),
                              },
                            ]}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
        {filteredDossiers.length > pageSize && (
          <div className={styles.pagination}>
            <button
              type="button"
              className={styles.pageButton}
              onClick={() => setDossierPage((prev) => Math.max(0, prev - 1))}
              disabled={dossierPage === 0}
            >
              Précédent
            </button>
            <span className={styles.pageInfo}>
              Page {dossierPage + 1} / {dossierTotalPages}
            </span>
            <button
              type="button"
              className={styles.pageButton}
              onClick={() => setDossierPage((prev) => Math.min(dossierTotalPages - 1, prev + 1))}
              disabled={dossierPage >= dossierTotalPages - 1}
            >
              Suivant
            </button>
          </div>
        )}
      </div>

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Documents individuels à examiner</div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead className={styles.thead}>
              <tr>
                <th className={styles.checkboxCell}>
                  <input
                    type="checkbox"
                    className={styles.checkbox}
                    checked={allRequisitionsSelected}
                    onChange={(event) => {
                      if (event.target.checked) {
                        setSelectedRequisitions(new Set(actionableRequisitions.map((r) => r.id)))
                      } else {
                        setSelectedRequisitions(new Set())
                      }
                    }}
                    aria-label="Sélectionner toutes les réquisitions"
                  />
                </th>
                <th>Référence</th>
                <th>Type</th>
                <th>Objet</th>
                <th>Statut examen</th>
                <th className={styles.amountHeader}>Montant</th>
                <th>Créé le</th>
                <th className={styles.actionsHeader}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className={styles.empty}>Chargement...</td>
                </tr>
              ) : pagedRequisitions.length === 0 ? (
                <tr>
                  <td colSpan={8} className={styles.empty}>Aucun document à examiner</td>
                </tr>
              ) : (
                pagedRequisitions.map((req) => {
                  const exam = getExamStatus(req)
                  const actionable = isRequisitionActionable(req)
                  // Les fonctions et leurs arguments sont inchangés : seul
                  // l'endroit où on les atteint change. La consultation entre
                  // dans le menu elle aussi, pour ne pas mêler dans la même
                  // cellule un bouton et un menu à viser différemment.
                  const actionsLigne: ActionLigne[] = [
                    {
                      cle: 'detail',
                      libelle: 'Voir les détails',
                      icone: <Search size={15} />,
                      onSelect: () => viewDetails(req),
                    },
                    {
                      cle: 'apercu',
                      libelle: 'Prévisualiser le bon',
                      icone: <Eye size={15} />,
                      onSelect: () => openPreview(req),
                    },
                    {
                      cle: 'imprimer',
                      libelle: 'Imprimer',
                      icone: <FileText size={15} />,
                      onSelect: () => printRequisition(req),
                    },
                    {
                      cle: 'telecharger',
                      libelle: 'Télécharger',
                      icone: <Download size={15} />,
                      onSelect: () => downloadRequisition(req),
                    },
                  ]
                  if (req.annexe?.id) {
                    actionsLigne.push({
                      cle: 'annexe',
                      libelle: 'Voir la pièce jointe',
                      description: req.annexe.filename || undefined,
                      icone: <Paperclip size={15} />,
                      onSelect: () => openRequisitionAnnexe(req.annexe),
                    })
                  }
                  if (exam === 'EN_EXAMEN') {
                    actionsLigne.push({
                      cle: 'valider',
                      libelle: "Valider l'examen",
                      icone: <Check size={15} />,
                      onSelect: () => openCommentModal('validate', req),
                    })
                    actionsLigne.push({
                      cle: 'rejeter',
                      libelle: "Rejeter l'examen",
                      icone: <X size={15} />,
                      destructive: true,
                      onSelect: () => openCommentModal('reject', req),
                    })
                  }
                  return (
                    <tr key={req.id} className={`${styles.tableRow} ${!actionable ? styles.tableRowMuted : ''}`}>
                      <td className={styles.checkboxCell}>
                        <input
                          type="checkbox"
                          className={styles.checkbox}
                          checked={selectedRequisitions.has(req.id)}
                          onChange={() => toggleRequisition(req.id)}
                          disabled={!actionable}
                          aria-label={`Sélectionner ${req.numero_requisition}`}
                        />
                      </td>
                      <td className={styles.refCell}>{getDocumentReference(req)}</td>
                      <td>{getDocumentTypeLabel(req)}</td>
                      <td className={styles.objetCell}>{req.objet}</td>
                      <td>
                        <span
                          className={`${styles.badgePill} ${
                            exam === 'EXAMINE'
                              ? styles.statusApproved
                              : exam === 'EN_EXAMEN'
                              ? styles.statusWaiting
                              : exam === 'REJETE'
                              ? styles.statusRejected
                              : styles.statusDraft
                          }`}
                        >
                          {statusLabels[exam] || exam || 'Non examiné'}
                        </span>
                      </td>
                      <td className={styles.amount}>
                        {Number(req.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                      </td>
                      <td>{req.created_at ? new Date(req.created_at).toLocaleDateString('fr-FR') : '-'}</td>
                      <td className={styles.actionsCell}>
                        <div className={styles.actionGroup}>
                          <RowActionsMenu
                            libelle={`Actions pour ${getDocumentReference(req)}`}
                            items={actionsLigne}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
        {filteredRequisitions.length > pageSize && (
          <div className={styles.pagination}>
            <button
              type="button"
              className={styles.pageButton}
              onClick={() => setRequisitionPage((prev) => Math.max(0, prev - 1))}
              disabled={requisitionPage === 0}
            >
              Précédent
            </button>
            <span className={styles.pageInfo}>
              Page {requisitionPage + 1} / {requisitionTotalPages}
            </span>
            <button
              type="button"
              className={styles.pageButton}
              onClick={() => setRequisitionPage((prev) => Math.min(requisitionTotalPages - 1, prev + 1))}
              disabled={requisitionPage >= requisitionTotalPages - 1}
            >
              Suivant
            </button>
          </div>
        )}
      </div>
      </div>

      {requisitionAModifier && (
        <RequisitionEditModal
          requisition={requisitionAModifier}
          utilisateurId={user?.id}
          onClose={() => setRequisitionAModifier(null)}
          onSaved={async () => {
            await loadDossiers()
            await viewDetails(requisitionAModifier)
          }}
        />
      )}

      {selectedReqDetail && (
        <div className={`${styles.modal} ${styles.detailModalOverlay}`}>
          <div className={`${styles.modalContent} ${styles.detailModalContent}`}>
            <div className={styles.modalHeader}>
              <h2>Détails de {getDocumentTypeLabel(selectedReqDetail).toLowerCase()} {getDocumentReference(selectedReqDetail)}</h2>
              <div className={styles.modalHeaderActions}>
                {!isTransportDocument(selectedReqDetail) &&
                  peutModifierRequisition(selectedReqDetail as any, user?.id) && (
                    <button
                      type="button"
                      className={styles.editReqBtn}
                      onClick={() => setRequisitionAModifier(selectedReqDetail)}
                    >
                      <Pencil size={14} aria-hidden="true" />
                      Modifier
                    </button>
                  )}
                <button type="button" className={styles.closeBtn} onClick={closeDetails} aria-label="Fermer">
                  <X size={16} />
                </button>
              </div>
            </div>
            {detailLoading ? (
              <div className={styles.empty}>Chargement...</div>
            ) : (
              <div className={styles.detailContent}>
                <div className={styles.detailSection}>
                  <h3>Informations générales</h3>
                  <div className={styles.detailGrid}>
                    <div className={styles.detailItem}>
                      <label>Référence</label>
                      <p><strong>{getDocumentReference(selectedReqDetail)}</strong></p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Objet</label>
                      <p>{selectedReqDetail.objet}</p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Montant Total</label>
                      <p><strong className={styles.detailAmount}>{formatCurrency(selectedReqDetail.montant_total)}</strong></p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Statut examen</label>
                      <p>{selectedReqDetail.examen_status || 'NON_EXAMINE'}</p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Date de création</label>
                      <p>{selectedReqDetail.created_at ? new Date(selectedReqDetail.created_at).toLocaleString('fr-FR') : '-'}</p>
                    </div>
                  </div>
                </div>

                <div className={styles.detailSection}>
                  <h3>Snapshot budgétaire à la demande</h3>
                  <BudgetDecisionTable
                    lines={selectedReqBudgetLines}
                    requestedAmount={selectedReqDetail?.montant_total}
                  />
                </div>

                <div className={styles.detailSection}>
                  <h3>{isTransportDocument(selectedReqDetail) ? 'Participants au remboursement' : 'Lignes de dépense'}</h3>
                  {isTransportDocument(selectedReqDetail) ? (
                    <div className={styles.detailTableWrap}>
                      <table className={styles.detailTable}>
                        <thead>
                          <tr>
                            <th style={{ width: '40px' }}>N°</th>
                            <th>Participant</th>
                            <th>Fonction</th>
                            <th>Type</th>
                            <th className={styles.amountHeader}>Montant</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedReqLignes.length === 0 ? (
                            <tr>
                              <td colSpan={5} className={styles.empty}>Aucun participant</td>
                            </tr>
                          ) : (
                            selectedReqLignes.map((participant: any, index: number) => (
                              <tr key={participant.id || `${participant.nom}-${participant.titre_fonction}`}>
                                <td style={{ textAlign: 'center', fontWeight: 600 }}>{index + 1}</td>
                                <td>{participant.nom}</td>
                                <td>{participant.titre_fonction}</td>
                                <td>{participant.type_participant}</td>
                                <td className={styles.amount}>
                                  <strong>{formatCurrency(participant.montant)}</strong>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className={styles.detailTableWrap}>
                      <table className={styles.detailTable}>
                        <thead>
                          <tr>
                            <th>Poste budgétaire</th>
                            <th>Description</th>
                            <th>Qté</th>
                            <th className={styles.amountHeader}>Montant</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedReqLignes.length === 0 ? (
                            <tr>
                              <td colSpan={4} className={styles.empty}>Aucune ligne</td>
                            </tr>
                          ) : (
                            selectedReqLignes.map((ligne: any) => (
                              <tr key={ligne.id || `${ligne.rubrique}-${ligne.description}`}>
                                <td><span className={styles.rubriqueTag}>{getLignePosteLabel(ligne)}</span></td>
                                <td>{ligne.description}</td>
                                <td>{ligne.quantite}</td>
                                <td className={styles.amount}>
                                  <strong>{formatCurrency(ligne.montant_total)}</strong>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {commentMode && commentReq && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>
                {commentMode === 'validate' ? 'Valider l’examen' : 'Rejeter l’examen'} · {getDocumentReference(commentReq)}
              </h3>
              <button type="button" className={styles.closeBtn} onClick={closeCommentModal} aria-label="Fermer">
                <X size={16} />
              </button>
            </div>
            <div className={styles.modalLabel}>Commentaire (optionnel)</div>
            <textarea
              className={styles.textarea}
              rows={3}
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
              placeholder="Ajoutez votre remarque..."
            />
            <div className={styles.modalActions}>
              <button type="button" className={styles.secondaryBtn} onClick={closeCommentModal}>
                Annuler
              </button>
              <button type="button" className={styles.primaryBtn} onClick={confirmCommentAction}>
                {commentMode === 'validate' ? 'Valider' : 'Rejeter'}
              </button>
            </div>
          </div>
        </div>
      )}

      {bulkAction && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>
                {bulkAction === 'validate' ? 'Valider la sélection' : 'Rejeter la sélection'} · {selectedCount} élément(s)
              </h3>
              <button type="button" className={styles.closeBtn} onClick={closeBulkAction} aria-label="Fermer">
                <X size={16} />
              </button>
            </div>
            <div className={styles.modalLabel}>Commentaire (optionnel)</div>
            <textarea
              className={styles.textarea}
              rows={3}
              value={bulkComment}
              onChange={(event) => setBulkComment(event.target.value)}
              placeholder="Ajoutez une remarque globale..."
            />
            <div className={styles.modalActions}>
              <button type="button" className={styles.secondaryBtn} onClick={closeBulkAction} disabled={bulkLoading}>
                Annuler
              </button>
              <button type="button" className={styles.primaryBtn} onClick={confirmBulkAction} disabled={bulkLoading}>
                {bulkLoading ? 'Traitement...' : bulkAction === 'validate' ? 'Valider' : 'Rejeter'}
              </button>
            </div>
          </div>
        </div>
      )}

      {previewReq && (
        <div className={styles.modal}>
          <div className={styles.previewContent}>
            <div className={styles.modalHeader}>
              <h3>Prévisualisation · {getDocumentReference(previewReq)}</h3>
              <button type="button" className={styles.closeBtn} onClick={closePreview} aria-label="Fermer">
                <X size={16} />
              </button>
            </div>
            {previewLoading && <div className={styles.empty}>Chargement...</div>}
            {!previewLoading && previewUrl && (
              <iframe title="Prévisualisation PDF" src={previewUrl} className={styles.previewFrame} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
