import { useCallback, useEffect, useMemo, useState } from 'react'
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import * as XLSX from 'xlsx'
import { PlusCircle, Wallet, CheckCircle, FileText, XCircle, ShieldCheck, Car, Send } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { API_BASE_URL, apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { getService, getServiceMembers } from '../api/services'
import BudgetGauge from '../components/ServicePortal/BudgetGauge'
import styles from './ServicePortal.module.css'
import type { CommissionMember } from '../types'
import { getStatusMeta } from '../utils/statusMapper'
import { generateSingleRequisitionPDF } from '../utils/pdfGenerator'

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
  type_requisition?: string | null
  dossier_id?: string | null
  examen_status?: string | null
  created_at: string
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
  nature_reunion: string
  lieu: string
  date_reunion: string
  montant_total: number
  status?: string | null
  statut?: string | null
  requisition_id?: string | null
  requisition?: RequisitionItem | null
}

type BudgetLine = {
  id: number
  code: string
  libelle: string
  montant_prevu: string | number
  montant_disponible?: string | number
}

export default function ServicePortal() {
  const { user } = useAuth()
  const { serviceId } = useParams()
  const navigate = useNavigate()
  const [summary, setSummary] = useState<ServiceSummary | null>(null)
  const [requisitions, setRequisitions] = useState<RequisitionItem[]>([])
  const [transports, setTransports] = useState<TransportItem[]>([])
  const [rubriques, setRubriques] = useState<BudgetLine[]>([])
  const [members, setMembers] = useState<CommissionMember[]>([])
  const [serviceLabel, setServiceLabel] = useState<string>('Mon espace commission')
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
  const [statusFilter, setStatusFilter] = useState('')
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [sortField, setSortField] = useState<'date' | 'amount'>('date')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  const rejectedCount = useMemo(() => (
    requisitions.filter((r) => String(r.status || '').toUpperCase().includes('REJET')).length
  ), [requisitions])

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
      const [summaryRes, reqRes, transportRes, rubRes, serviceRes, membersRes] = await Promise.all([
        apiRequest<ServiceSummary>('GET', '/budget/summary/mine', { params: { service_id: activeServiceId } }),
        apiRequest<RequisitionItem[]>('GET', '/requisitions/mine', { params: { service_id: activeServiceId, include: 'demandeur,validateur,approbateur,examinateur,caissier' } }),
        apiRequest<TransportItem[]>('GET', '/remboursements-transport', { params: { include: 'requisition', limit: 200, offset: 0 } }),
        apiRequest<{ lignes: BudgetLine[] }>('GET', '/budget/lines/autorisees', { params: { active: true, type: 'DEPENSE', service_id: activeServiceId } }),
        getService(activeServiceId),
        getServiceMembers(activeServiceId),
      ])
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
      setServiceLabel(`${serviceRes.code} · ${serviceRes.libelle}`)
      setMembers(Array.isArray(membersRes) ? membersRes : [])
      setCommissionError(null)
    } catch (error: any) {
      const status = error?.status ?? error?.response?.status
      if (status === 403) {
        setCommissionError("Accès refusé : vous n'êtes pas membre de cette commission.")
      } else if (status === 404) {
        setCommissionError("Commission introuvable ou supprimée.")
      } else {
        setCommissionError("Impossible de charger les données de la commission.")
      }
      setSummary(null)
      setRequisitions([])
      setTransports([])
      setRubriques([])
      setMembers([])
    } finally {
      setLoading(false)
    }
  }, [activeServiceId])

  useEffect(() => {
    loadData()
  }, [loadData])

  const totalDepenses = summary?.total_depenses ?? summary?.total ?? 0
  const totalRecettes = summary?.total_recettes ?? 0
  const consomme = summary?.consomme ?? 0
  const enAttente = summary?.en_attente ?? 0
  const disponible = summary?.disponible ?? 0
  const progress = totalDepenses > 0 ? Math.min(100, Math.round((consomme / totalDepenses) * 100)) : 0
  const leadership = members.filter((m) => m.role_type === 'PRESIDENT' || m.role_type === 'DELEGUE')
  const assistants = members.filter((m) => m.role_type === 'ASSISTANT')
  const experts = members.filter((m) => m.role_type === 'MEMBRE')
  const currentMember = useMemo(
    () => members.find((m) => (m.user_id ? String(m.user_id) === String(user?.id) : false)) || null,
    [members, user?.id]
  )
  const isAdminUser = user?.role === 'admin'
  const canSign = isAdminUser || Boolean(currentMember?.is_signer)
  const tenantName = user?.organisation_name || user?.organisation_slug || 'Organisation'
  const budgetExercise = summary?.annee ? String(summary.annee) : '—'

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

  const getTransportStatus = (transport: TransportItem) => {
    return transport.requisition?.status || transport.status || transport.statut || 'BROUILLON'
  }

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

  const canSubmitToExamen = (req: RequisitionItem) => {
    const status = String(req.status || '').toUpperCase()
    const examenStatus = String(req.examen_status || '').toUpperCase()
    return !req.dossier_id && status === 'SIGNEE_SERVICE' && examenStatus === 'NON_EXAMINE'
  }

  const canSignTransport = (transport: TransportItem) => {
    const req = transport.requisition
    return Boolean(req?.id) && String(req?.status || '').toUpperCase() === 'BROUILLON'
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

  const viewDetails = async (req: RequisitionItem) => {
    setSelectedRequisition(req)
    setShowDetailModal(true)
    setDetailLoading(true)
    setDetailError(null)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const data = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      setSelectedLignes(data || [])
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

  const exportExcel = () => {
    const wb = XLSX.utils.book_new()
    if (documentFilter !== 'transports') {
      const rows = visibleRequisitions.map((req) => ({
        Tenant: tenantName,
        'Exercice budgétaire': budgetExercise,
        Commission: serviceLabel,
        Type: 'Réquisition',
        Numéro: req.numero_requisition,
        Date: formatDate(req.created_at),
        Objet: req.objet,
        Lieu: '',
        Montant: Number(req.montant_total || 0),
        Statut: getStatusMeta(req.status).label,
      }))
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Réquisitions')
    }
    if (documentFilter !== 'requisitions') {
      const rows = visibleTransports.map((transport) => ({
        Tenant: tenantName,
        'Exercice budgétaire': budgetExercise,
        Commission: serviceLabel,
        Type: 'Remboursement transport',
        Numéro: transport.numero_remboursement,
        Date: formatDate(transport.date_reunion),
        Objet: transport.nature_reunion,
        Lieu: transport.lieu,
        Montant: Number(transport.montant_total || 0),
        Statut: getStatusMeta(getTransportStatus(transport)).label,
      }))
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Remboursements')
    }
    const suffix = dateDebut || dateFin ? `${dateDebut || 'debut'}_${dateFin || 'fin'}` : new Date().toISOString().slice(0, 10)
    XLSX.writeFile(wb, `espace_commission_${suffix}.xlsx`)
  }

  const exportPdf = () => {
    const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
    const title = documentFilter === 'requisitions'
      ? 'Réquisitions de la commission'
      : documentFilter === 'transports'
        ? 'Remboursements transport de la commission'
        : 'Espace commission - réquisitions et remboursements'
    doc.setFontSize(14)
    doc.text(title, 14, 14)
    doc.setFontSize(9)
    doc.text(`Tenant : ${tenantName}`, 14, 20)
    doc.text(`Commission : ${serviceLabel}`, 14, 25)
    doc.text(`Exercice budgétaire : ${budgetExercise}`, 14, 30)
    if (dateDebut || dateFin) {
      doc.text(`Période : ${dateDebut || 'début'} au ${dateFin || 'fin'}`, 14, 35)
    }

    const rows = [
      ...(documentFilter !== 'transports'
        ? visibleRequisitions.map((req) => [
            'Réquisition',
            req.numero_requisition,
            formatDate(req.created_at),
            req.objet,
            '',
            Number(req.montant_total || 0).toLocaleString(),
            getStatusMeta(req.status).label,
          ])
        : []),
      ...(documentFilter !== 'requisitions'
        ? visibleTransports.map((transport) => [
            'Transport',
            transport.numero_remboursement,
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
    doc.save(`espace_commission_${suffix}.pdf`)
  }

  if (!activeServiceId) {
    return (
      <div className={styles.emptyState}>
        <h2>Accès indisponible</h2>
        <p>Choisissez un service pour ouvrir son portail.</p>
        <button className={styles.primaryAction} onClick={() => navigate('/services')}>
          Voir mes services
        </button>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>Espace Commission</div>
          <h1>{serviceLabel}</h1>
          <p>Suivi budgétaire et demandes de fonds de votre commission.</p>
        </div>
        <div className={styles.actionButtons}>
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

      <section className={styles.metrics}>
        <div className={styles.metricCard}>
          <BudgetGauge consomme={consomme} engage={enAttente} total={totalDepenses} />
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Dépenses allouées</span>
            <Wallet size={18} />
          </div>
          <div className={styles.metricValue}>{totalDepenses.toLocaleString()} USD</div>
          <div className={styles.metricHint}>Exercice {summary?.annee ?? '—'}</div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Recettes allouées</span>
            <Wallet size={18} />
          </div>
          <div className={styles.metricValue}>{totalRecettes.toLocaleString()} USD</div>
          <div className={styles.metricHint}>Exercice {summary?.annee ?? '—'}</div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Consommé</span>
            <CheckCircle size={18} className={styles.metricIconGreen} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueGreen}`}>
            {consomme.toLocaleString()} USD
          </div>
          <div className={styles.progressTrack}>
            <div className={styles.progressFill} style={{ width: `${progress}%` }} />
          </div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>En attente</span>
            <FileText size={18} className={styles.metricIconAmber} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueAmber}`}>
            {enAttente.toLocaleString()} USD
          </div>
          <div className={styles.metricHint}>Réquisitions en cours</div>
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Disponible</span>
            <Wallet size={18} className={styles.metricIconBlue} />
          </div>
          <div className={`${styles.metricValue} ${styles.metricValueBlue}`}>
            {disponible.toLocaleString()} USD
          </div>
          <div className={styles.metricHint}>Solde restant</div>
        </div>
      </section>

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
              Exporter Excel
            </button>
            <button type="button" className={styles.exportPdfBtn} onClick={exportPdf}>
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
              <span>Réquisitions de la commission</span>
              <span className={styles.panelHeaderMeta}>Service uniquement</span>
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
                    <th>Montant</th>
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
                      <td>{Number(req.montant_total || 0).toLocaleString()} USD</td>
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
                          {canSign && req.status === 'BROUILLON' && (
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
                              {signingId === req.id ? 'Signature…' : 'Valider & Signer (Service)'}
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
                            onClick={(event) => {
                              event.stopPropagation()
                              window.open(`${API_BASE_URL}/requisitions/annexe/${req.annexe?.id}`, '_blank')
                            }}
                            title={req.annexe?.filename || 'Voir la pièce jointe'}
                            aria-label="Voir la pièce jointe"
                          >
                            📎
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
                            🔍
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
                              ❗
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
                          >
                            🖨️
                          </button>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={(event) => {
                              event.stopPropagation()
                              downloadRequisition(req)
                            }}
                            title="Télécharger"
                          >
                            ⬇️
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
                        Aucune réquisition ne correspond aux filtres.
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
                ← Précédent
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
                Suivant →
              </button>
            </div>
          )}
        </div>}

        <div className={styles.panel}>
          <div className={styles.panelHeader}>Mes postes budgétaires autorisés</div>
          {loading ? (
            <div className={styles.panelState}>Chargement…</div>
          ) : (
            <div className={styles.rubriquesList}>
              {rubriques.map((rub) => (
                <div key={rub.id} className={styles.rubriqueRow}>
                  <span className={styles.rubriqueCode}>{rub.code}</span>
                  <span className={styles.rubriqueLabel}>{rub.libelle}</span>
                  <span className={styles.rubriqueAmount}>
                    {Number(rub.montant_prevu || 0).toLocaleString()} USD
                  </span>
                </div>
              ))}
              {rubriques.length === 0 && (
                <div className={styles.panelState}>Aucun poste budgétaire autorisé.</div>
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
                  <th>Montant</th>
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
                      <td>{Number(transport.montant_total || 0).toLocaleString()} USD</td>
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
                            🔍
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
                      Aucun remboursement transport ne correspond aux filtres.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      <section className={styles.panel}>
        <div className={styles.panelHeader}>Gouvernance de la commission</div>
        <div className={styles.govGrid}>
          <div>
            <div className={styles.govTitle}>Bureau</div>
            <div className={styles.govList}>
              {leadership.map((member) => (
                <div key={member.id} className={styles.govRow}>
                  <span className={styles.govAvatar}>{member.full_name?.[0] || '?'}</span>
                  <div>
                    <div className={styles.govName}>{member.full_name}</div>
                  <div className={styles.govMeta}>
                    {member.role_type}
                  </div>
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
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Détails de la réquisition {selectedRequisition.numero_requisition}</h2>
              <button className={styles.closeBtn} onClick={() => setShowDetailModal(false)}>×</button>
            </div>
            {detailError && <div className={styles.modalError}>{detailError}</div>}
            <div className={styles.detailGrid}>
              <div className={styles.detailItem}>
                <label>Objet</label>
                <p>{selectedRequisition.objet}</p>
              </div>
              <div className={styles.detailItem}>
                <label>Montant</label>
                <p>{Number(selectedRequisition.montant_total || 0).toLocaleString()} USD</p>
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
                    onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${selectedRequisition.annexe?.id}`, '_blank')}
                  >
                    📎 Voir la pièce jointe
                  </button>
                </div>
              )}
            </div>
            <div className={styles.detailSection}>
              <h3>Lignes de dépense</h3>
              {detailLoading ? (
                <div className={styles.panelState}>Chargement…</div>
              ) : selectedLignes.length === 0 ? (
                <div className={styles.panelState}>Aucune ligne trouvée.</div>
              ) : (
                <table className={styles.detailTable}>
                  <thead>
                    <tr>
                      <th>Poste</th>
                      <th>Description</th>
                      <th>Qté</th>
                      <th>Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedLignes.map((ligne) => (
                      <tr key={ligne.id}>
                        <td>{ligne.rubrique || ligne.budget_poste_id || '—'}</td>
                        <td>{ligne.description}</td>
                        <td>{ligne.quantite}</td>
                        <td>{Number(ligne.montant_total || 0).toLocaleString()} USD</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
              <button className={styles.closeBtn} onClick={() => setShowRejectModal(false)}>×</button>
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
