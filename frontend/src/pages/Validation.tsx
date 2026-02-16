import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { apiRequest, API_BASE_URL, ApiError } from '../lib/apiClient'
import { scoreRequisitions } from '../api/ai'
import { useNotification } from '../contexts/NotificationContext'
import { format } from 'date-fns'
import { formatAmount, toNumber } from '../utils/amount'
import type { Money } from '../types'
import RequisitionActionModal from '../components/RequisitionActionModal'
import RemboursementActionModal from '../components/RemboursementActionModal'
import { generateRemboursementTransportPDF } from '../utils/pdfGeneratorRemboursement'
import { generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import styles from './Validation.module.css'

interface Requisition {
  id: string
  numero_requisition: string
  objet: string
  type_requisition: string
  montant_total: Money
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
  demandeur?: {
    prenom: string
    nom: string
  }
}

interface RemboursementTransport {
  id: string
  numero_remboursement: string
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

interface Participant {
  id?: string
  nom: string
  titre_fonction: string
  montant: Money
  type_participant: 'principal' | 'assistant'
}

export default function Validation() {
  const { user } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const { showSuccess, showError } = useNotification()
  const [requisitions, setRequisitions] = useState<any[]>([])
  const [aiScores, setAiScores] = useState<Record<string, any>>({})
  const [aiPopoverId, setAiPopoverId] = useState<string | null>(null)
  const aiCacheRef = useRef<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const [showActionModal, setShowActionModal] = useState(false)
  const [currentAction, setCurrentAction] = useState<'reject' | 'authorize' | 'vise'>('authorize')
  const [selectedRequisition, setSelectedRequisition] = useState<Requisition | null>(null)
  const [remboursementNumber, setRemboursementNumber] = useState<string>('')
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [remboursementActionLoadingId, setRemboursementActionLoadingId] = useState<string | null>(null)

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])
  const [showReqDetailModal, setShowReqDetailModal] = useState(false)
  const [selectedReqDetail, setSelectedReqDetail] = useState<Requisition | null>(null)
  const [selectedReqLines, setSelectedReqLines] = useState<any[]>([])
  const [reqDetailLoading, setReqDetailLoading] = useState(false)

  const canValidate = hasPermission('validation')
  const pendingStatuses = ['EN_ATTENTE', 'A_VALIDER', 'brouillon', 'AUTORISEE', 'VALIDEE']
  const authorizeStatuses = new Set(['EN_ATTENTE', 'A_VALIDER', 'brouillon'])
  const viseStatuses = new Set(['AUTORISEE', 'VALIDEE'])

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
    } else {
      setLoading(false)
    }
  }, [canValidate, filterType])

  useEffect(() => {
    setAiPopoverId(null)
  }, [filterType, searchQuery])

  const loadRequisitions = async () => {
    setLoading(true)
    try {
      const params: any = {
        order: 'created_at.desc',
        include: 'demandeur',
        limit: 200,
        status_in: pendingStatuses.join(',')
      }
      if (filterType !== 'all') params.type_requisition = filterType

      const res: any = await apiRequest('GET', '/requisitions', { params })
      const items = Array.isArray(res) ? res : (res as any)?.items ?? (res as any)?.data ?? []
      setRequisitions(items as any)
    } catch (error) {
      console.error('Error loading requisitions:', error)
      showError('Erreur de chargement', 'Impossible de charger les réquisitions en attente.')
    } finally {
      setLoading(false)
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
        'Réquisition autorisée',
        `La réquisition ${requisition.numero_requisition} a été autorisée (1/2).\n\nElle attend une seconde validation.`
      )

      loadRequisitions()
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
        'Réquisition approuvée',
        `La réquisition ${requisition.numero_requisition} a été visée (2/2).\n\nElle est maintenant approuvée.`
      )

      loadRequisitions()
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
      await apiRequest('POST', `/requisitions/${selectedRequisition.id}/reject`, {
        motif_rejet: motif || 'Rejetée sans motif'
      })

      showSuccess(
        'Réquisition rejetée',
        `La réquisition ${selectedRequisition.numero_requisition} a été rejetée.\n\nMotif : ${motif || 'Non spécifié'}`
      )

      handleModalClose()
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

  const handleViewRemboursementDetails = async (requisition: Requisition) => {
    setRemboursementActionLoadingId(requisition.id)
    try {
      const remboursement = await loadRemboursementByRequisition(requisition.id)
      if (!remboursement) {
        showError('Remboursement introuvable', 'Aucun remboursement lié à cette réquisition.')
        return
      }
      const participants = await loadParticipants(remboursement.id)
      setSelectedRemboursementDetails(remboursement)
      setSelectedParticipants(participants)
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
      await generateRemboursementTransportPDF(
        remboursement,
        participants || [],
        'print',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error) {
      console.error('Error printing remboursement:', error)
      showError('Erreur', 'Impossible d’imprimer le remboursement.')
    } finally {
      setRemboursementActionLoadingId(null)
    }
  }

  const handleViewRequisitionDetails = async (requisition: Requisition) => {
    setSelectedReqDetail(requisition)
    setShowReqDetailModal(true)
    setReqDetailLoading(true)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', {
        params: { requisition_id: requisition.id }
      })
      const lignesData = Array.isArray(lignesRes)
        ? lignesRes
        : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      setSelectedReqLines(lignesData || [])
    } catch (error: any) {
      console.error('Error loading requisition details:', error)
      showError('Erreur', error?.message || 'Impossible de charger les détails de la réquisition.')
    } finally {
      setReqDetailLoading(false)
    }
  }

  const handlePrintRequisition = async (requisition: Requisition) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', {
        params: { requisition_id: requisition.id }
      })
      const lignesData = Array.isArray(lignesRes)
        ? lignesRes
        : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

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
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', {
        params: { requisition_id: requisition.id }
      })
      const lignesData = Array.isArray(lignesRes)
        ? lignesRes
        : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

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
      await generateRemboursementTransportPDF(
        remboursement,
        participants || [],
        'download',
        `${user?.prenom} ${user?.nom}`
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
    const searchLower = searchQuery.toLowerCase()
    return (
      (req.numero_requisition || '').toLowerCase().includes(searchLower) ||
      (req.objet || '').toLowerCase().includes(searchLower) ||
      (req.demandeur?.nom || '').toLowerCase().includes(searchLower) ||
      (req.demandeur?.prenom || '').toLowerCase().includes(searchLower)
    )
  })

  const getStatutBadge = (statut: string) => {
    const badges = {
      EN_ATTENTE: { label: 'En attente', class: styles.statutBrouillon },
      A_VALIDER: { label: 'En attente', class: styles.statutBrouillon },
      VALIDEE: { label: 'Autorisée (1/2)', class: styles.statutValidee },
      AUTORISEE: { label: 'Autorisée (1/2)', class: styles.statutValidee },
      REJETEE: { label: 'Rejetée', class: styles.statutRejetee },
      brouillon: { label: 'En attente', class: styles.statutBrouillon },
      validee_tresorerie: { label: 'Validée (Trésorerie)', class: styles.statutValidee },
      approuvee: { label: 'Approuvée', class: styles.statutApprouvee },
      APPROUVEE: { label: 'Approuvée', class: styles.statutApprouvee },
      payee: { label: 'Payée', class: styles.statutPayee },
      rejetee: { label: 'Rejetée', class: styles.statutRejetee }
    }
    const badge = badges[statut as keyof typeof badges] || { label: statut, class: '' }
    return <span className={`${styles.badge} ${badge.class}`}>{badge.label}</span>
  }

  const getTypeBadge = (type: string) => {
    const types = {
      classique: { label: 'Classique', class: styles.typeClassique },
      mini: { label: 'Mini', class: styles.typeMini },
      remboursement_transport: { label: 'Remboursement Transport', class: styles.typeRemboursement }
    }
    const badge = types[type as keyof typeof types] || { label: type, class: '' }
    return <span className={`${styles.badge} ${badge.class}`}>{badge.label}</span>
  }

  const filteredIds = useMemo(
    () => filteredRequisitions.map((req) => String(req.id)).filter(Boolean),
    [filteredRequisitions]
  )

  useEffect(() => {
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
  }, [filteredIds, canValidate])

  const getAiBadge = (reqId: string) => {
    const score = aiScores[String(reqId)]
    if (!score) {
      return (
        <span className={`${styles.aiBadge} ${styles.aiBadgeLoading}`} title="Analyse IA en cours">
          🛡️ IA…
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
          🛡️ IA {score.risk_score}
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

  useEffect(() => {
    if (!selectedReqDetail) return
    const reqId = String(selectedReqDetail.id)
    if (aiCacheRef.current[reqId]) return

    let cancelled = false
    const loadScore = async () => {
      try {
        const res = await scoreRequisitions({ requisition_ids: [reqId] })
        if (cancelled || !res?.length) return
        const next = { ...aiCacheRef.current, [reqId]: res[0] }
        aiCacheRef.current = next
        setAiScores(next)
      } catch (error) {
        console.error('Error loading AI score:', error)
      }
    }
    loadScore()
    return () => {
      cancelled = true
    }
  }, [selectedReqDetail])

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
          <label>Rechercher</label>
          <input
            type="text"
            placeholder="N° réquisition, objet, demandeur..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <label>Type</label>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="all">Tous les types</option>
            <option value="classique">Classique</option>
            <option value="mini">Mini</option>
            <option value="remboursement_transport">Remboursement Transport</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>Statut</label>
          <select value="EN_ATTENTE" disabled>
            <option value="EN_ATTENTE">En attente</option>
          </select>
        </div>
      </div>

      <div className={styles.searchSticky}>
        <div className={styles.searchBox}>
          <span className={styles.searchIcon}>🔍</span>
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
              ✕
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
          <table className={styles.table}>
            <thead>
              <tr>
                <th>N° Réquisition</th>
                <th>Type</th>
                <th>Objet</th>
                <th>Demandeur</th>
                <th>Montant</th>
                <th>Mode paiement</th>
                <th>Statut</th>
                <th>Date création</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRequisitions.map((req) => {
                const statusValue = (req as any).status ?? req.statut
                const canAct = pendingStatuses.includes(statusValue || 'EN_ATTENTE')
                const isBusy = actionLoadingId === req.id
                const isAuthorizedBySelf = Boolean((req as any).validee_par && user?.id && String((req as any).validee_par) === String(user.id))
              const isRemboursementTransport = req.type_requisition === 'remboursement_transport'
              return (
                <tr key={req.id}>
                    <td><strong>{req.numero_requisition}</strong></td>
                    <td>{getTypeBadge(req.type_requisition)}</td>
                    <td className={styles.objetCell}>{req.objet}</td>
                    <td>{req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : 'N/A'}</td>
                    <td>
                      <div className={styles.amountRow}>
                        <strong>${formatAmount(req.montant_total)}</strong>
                        {getAiBadge(req.id)}
                      </div>
                    </td>
                    <td>
                      <span className={styles.modePaiementBadge}>
                        {req.mode_paiement === 'cash' && '💵 Cash'}
                        {req.mode_paiement === 'mobile_money' && '📱 Mobile Money'}
                        {req.mode_paiement === 'virement' && '🏦 Virement'}
                      </span>
                    </td>
                    <td>{getStatutBadge(statusValue || 'EN_ATTENTE')}</td>
                    <td>{format(new Date(req.created_at), 'dd/MM/yyyy HH:mm')}</td>
                    <td>
                      <div className={styles.actions}>
                        {req.type_requisition !== 'remboursement_transport' && (
                          <>
                            <button
                              onClick={() => handleViewRequisitionDetails(req)}
                              className={styles.detailBtn}
                              title="Voir les détails de la réquisition"
                            >
                              🔍 Détails
                            </button>
                            <button
                              onClick={() => handlePrintRequisition(req)}
                              className={styles.printBtn}
                              title="Imprimer la réquisition"
                            >
                              🖨️ Imprimer
                            </button>
                            <button
                              onClick={() => handleDownloadRequisition(req)}
                              className={styles.downloadBtn}
                              title="Télécharger la réquisition"
                            >
                              ⬇️ Télécharger
                            </button>
                          </>
                        )}
                        {req.annexe?.id && (
                          <button
                            onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${req.annexe?.id}`, '_blank')}
                            className={styles.detailBtn}
                            title={req.annexe?.filename ? `Voir ${req.annexe.filename}` : 'Voir la pièce jointe'}
                          >
                            👁️ Voir la pièce jointe
                          </button>
                        )}
                        {req.type_requisition === 'remboursement_transport' && (
                          <>
                            <button
                              onClick={() => handleViewRemboursementDetails(req)}
                              className={styles.detailBtn}
                              title="Voir les détails du remboursement"
                              disabled={remboursementActionLoadingId === req.id}
                            >
                              {remboursementActionLoadingId === req.id ? '⏳ Chargement...' : '🔍 Détails'}
                            </button>
                            <button
                              onClick={() => handlePrintRemboursement(req)}
                              className={styles.printBtn}
                              title="Imprimer le remboursement"
                              disabled={remboursementActionLoadingId === req.id}
                            >
                              🖨️ Imprimer
                            </button>
                            <button
                              onClick={() => handleDownloadRemboursement(req)}
                              className={styles.downloadBtn}
                              title="Télécharger le remboursement"
                              disabled={remboursementActionLoadingId === req.id}
                            >
                              ⬇️ Télécharger
                            </button>
                          </>
                        )}
                        {canAct && (
                          <>
                            {authorizeStatuses.has(String(statusValue)) && (
                              <button
                                onClick={() => handleAction('authorize', req)}
                                className={styles.validateBtn}
                                title={isRemboursementTransport ? 'Autoriser (validation 1/2)' : 'Autoriser'}
                                disabled={isBusy}
                              >
                                {isBusy && currentAction === 'authorize' ? '⏳ Autorisation...' : '✅ Autoriser'}
                              </button>
                            )}
                            {authorizeStatuses.has(String(statusValue)) && isRemboursementTransport && (
                              <span className={styles.workflowHint}>Étape 1/2 : avis technique</span>
                            )}
                            {viseStatuses.has(String(statusValue)) && (
                              <>
                                <button
                                  onClick={() => handleAction('vise', req)}
                                  className={isAuthorizedBySelf ? styles.viseDisabledBtn : styles.approveBtn}
                                  title={
                                    isAuthorizedBySelf
                                      ? "Sécurité : Vous avez déjà effectué la première validation. Un autre utilisateur doit viser cette dépense."
                                      : isRemboursementTransport
                                      ? 'Viser (validation 2/2)'
                                      : 'Viser pour paiement'
                                  }
                                  disabled={isBusy || isAuthorizedBySelf}
                                >
                                  {isBusy && currentAction === 'vise'
                                    ? '⏳ Visa...'
                                    : isAuthorizedBySelf
                                    ? '🔒 Attente second validateur'
                                    : '✅ Viser pour paiement'}
                                </button>
                                {isAuthorizedBySelf && (
                                  <span className={styles.viseHint}>
                                    🔒 Sécurité : validation croisée requise.
                                  </span>
                                )}
                                {!isAuthorizedBySelf && isRemboursementTransport && (
                                  <span className={styles.workflowHint}>Étape 2/2 : validation finale</span>
                                )}
                              </>
                            )}
                            <button
                              onClick={() => handleAction('reject', req)}
                              className={styles.rejectBtn}
                              title="Rejeter"
                              disabled={isBusy}
                            >
                              {isBusy && currentAction === 'reject' ? '⏳ Rejet...' : '⛔ Rejeter'}
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className={styles.mobileCards}>
        {filteredRequisitions.length === 0 ? (
          <div className={styles.emptyCards}>Aucune réquisition en attente de validation</div>
        ) : (
          filteredRequisitions.map((req) => {
            const statusValue = (req as any).status ?? req.statut
            const isRemboursementTransport = req.type_requisition === 'remboursement_transport'
            const onOpenDetails = () =>
              isRemboursementTransport
                ? handleViewRemboursementDetails(req)
                : handleViewRequisitionDetails(req)

            return (
              <div
                key={`card-${req.id}`}
                className={styles.card}
                data-statut={String(statusValue || 'EN_ATTENTE').toLowerCase()}
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
                    <div className={styles.cardTitle}>{req.numero_requisition}</div>
                    <div className={styles.cardSub}>{format(new Date(req.created_at), 'dd/MM/yyyy HH:mm')}</div>
                  </div>
                  <div className={styles.cardHeaderRight}>
                    {getStatutBadge(statusValue || 'EN_ATTENTE')}
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
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Détails du remboursement {selectedRemboursementDetails.numero_remboursement}</h2>
              <button onClick={() => setShowDetailModal(false)} className={styles.closeBtn}>×</button>
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
                    <p><strong>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Participants</h3>
                <table className={styles.detailTable}>
                  <thead>
                    <tr>
                      <th>Nom</th>
                      <th>Titre/Fonction</th>
                      <th>Type</th>
                      <th>Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedParticipants.map((participant) => (
                      <tr key={participant.id ?? `${participant.nom}-${participant.titre_fonction}`}>
                        <td>{participant.nom}</td>
                        <td>{participant.titre_fonction}</td>
                        <td>
                          <span className={`${styles.participantType} ${participant.type_participant === 'assistant' ? styles.participantTypeAssistant : ''}`}>
                            {participant.type_participant === 'principal' ? 'Principal' : 'Assistant'}
                          </span>
                        </td>
                        <td><strong>{formatCurrency(participant.montant)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={3} style={{textAlign: 'right', fontWeight: 600}}>Total général:</td>
                      <td><strong>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {showReqDetailModal && selectedReqDetail && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Détails de la réquisition {selectedReqDetail.numero_requisition}</h2>
              <button onClick={() => setShowReqDetailModal(false)} className={styles.closeBtn}>×</button>
            </div>

            <div className={styles.detailContent}>
              {(() => {
                const aiScore = aiScores[String(selectedReqDetail.id)]
                const risk = aiScore?.risk_score ?? null
                const reasons = Array.isArray(aiScore?.reasons) ? aiScore.reasons : []
                const reasonText = reasons.length > 0 ? reasons.join(' ') : ''
                const progressClass =
                  risk !== null && risk >= 71
                    ? styles.aiProgressHigh
                    : risk !== null && risk >= 41
                    ? styles.aiProgressMedium
                    : styles.aiProgressLow

                return (
                  <div className={styles.detailSection}>
                    <h3>Analyse de conformité IA</h3>
                    {!aiScore ? (
                      <p className={styles.aiHint}>Analyse IA en cours...</p>
                    ) : (
                      <div className={styles.aiPanel}>
                        <div className={styles.aiPanelHeader}>
                          <span className={styles.aiPanelTitle}>Score global</span>
                          <span className={styles.aiPanelScore}>🛡️ {risk}/100</span>
                        </div>
                        <div className={styles.aiProgressTrack}>
                          <div
                            className={`${styles.aiProgressFill} ${progressClass}`}
                            style={{ width: `${risk}%` }}
                          />
                        </div>
                        <div className={styles.aiPanelMeta}>
                          <span>Échantillon: {aiScore.sample_size ?? 0}</span>
                          {aiScore.z_score !== null && aiScore.z_score !== undefined && (
                            <span>Écart: {Math.abs(Number(aiScore.z_score)).toFixed(1)} σ</span>
                          )}
                          {aiScore.duplicate_candidates > 0 && (
                            <span>Doublons potentiels: {aiScore.duplicate_candidates}</span>
                          )}
                        </div>
                        <div className={styles.aiPanelBody}>
                          <p>{aiScore.explanation}</p>
                          {reasonText && <p className={styles.aiPanelReasons}>{reasonText}</p>}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()}

              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  {(() => {
                    const statusValue = String((selectedReqDetail as any).status ?? (selectedReqDetail as any).statut ?? '').toUpperCase()
                    const isRejected = statusValue === 'REJETEE'
                    const isAuthorized = statusValue === 'AUTORISEE' || statusValue === 'VALIDEE'
                    const isApproved = statusValue === 'APPROUVEE' || statusValue === 'PAYEE'
                    return (
                      <>
                        {isRejected && selectedReqDetail.validateur && (
                          <div className={styles.detailItem}>
                            <label>Rejeté par</label>
                            <p>
                              {`${selectedReqDetail.validateur.prenom || ''} ${selectedReqDetail.validateur.nom || ''}`.trim() || 'N/A'}
                            </p>
                          </div>
                        )}
                        {!isRejected && isAuthorized && selectedReqDetail.validateur && (
                          <div className={styles.detailItem}>
                            <label>Autorisateur (1/2)</label>
                            <p>
                              {`${selectedReqDetail.validateur.prenom || ''} ${selectedReqDetail.validateur.nom || ''}`.trim() || 'N/A'}
                            </p>
                          </div>
                        )}
                        {!isRejected && isApproved && selectedReqDetail.validateur && (
                          <div className={styles.detailItem}>
                            <label>Autorisateur (1/2)</label>
                            <p>
                              {`${selectedReqDetail.validateur.prenom || ''} ${selectedReqDetail.validateur.nom || ''}`.trim() || 'N/A'}
                            </p>
                          </div>
                        )}
                        {!isRejected && isApproved && selectedReqDetail.approbateur && (
                          <div className={styles.detailItem}>
                            <label>Viseur (2/2)</label>
                            <p>
                              {`${selectedReqDetail.approbateur.prenom || ''} ${selectedReqDetail.approbateur.nom || ''}`.trim() || 'N/A'}
                            </p>
                          </div>
                        )}
                      </>
                    )
                  })()}
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedReqDetail.numero_requisition}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Objet</label>
                    <p>{selectedReqDetail.objet}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Demandeur</label>
                    <p>{selectedReqDetail.demandeur ? `${selectedReqDetail.demandeur.prenom} ${selectedReqDetail.demandeur.nom}` : 'N/A'}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong>{formatCurrency(selectedReqDetail.montant_total)}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Lignes de dépense</h3>
                {reqDetailLoading ? (
                  <p>Chargement...</p>
                ) : (
                  <table className={styles.detailTable}>
                    <thead>
                      <tr>
                        <th>Rubrique</th>
                        <th>Description</th>
                        <th>Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedReqLines.map((ligne) => (
                        <tr key={ligne.id || `${ligne.rubrique}-${ligne.libelle}`}>
                          <td>{ligne.rubrique || '-'}</td>
                          <td>{ligne.libelle || ligne.description || '-'}</td>
                          <td><strong>{formatCurrency(ligne.montant || ligne.total || 0)}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
