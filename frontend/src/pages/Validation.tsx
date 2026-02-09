import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { apiRequest, API_BASE_URL } from '../lib/apiClient'
import { useNotification } from '../contexts/NotificationContext'
import { format } from 'date-fns'
import { formatAmount, toNumber } from '../utils/amount'
import type { Money } from '../types'
import RequisitionActionModal from '../components/RequisitionActionModal'
import RemboursementActionModal from '../components/RemboursementActionModal'
import { generateRemboursementTransportPDF } from '../utils/pdfGeneratorRemboursement'
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
  mode_paiement: string
  annexe?: {
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
  const { showSuccess, showError } = useNotification()
  const [requisitions, setRequisitions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const [showActionModal, setShowActionModal] = useState(false)
  const [currentAction, setCurrentAction] = useState<'reject' | 'validate'>('validate')
  const [selectedRequisition, setSelectedRequisition] = useState<Requisition | null>(null)
  const [remboursementNumber, setRemboursementNumber] = useState<string>('')
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [remboursementActionLoadingId, setRemboursementActionLoadingId] = useState<string | null>(null)

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])

  const canValidate = user?.role === 'tresorerie' || user?.role === 'admin'
  const pendingStatuses = ['EN_ATTENTE', 'A_VALIDER', 'brouillon']

  useEffect(() => {
    if (canValidate) {
      loadRequisitions()
    } else {
      setLoading(false)
    }
  }, [canValidate, filterType])

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

  const handleAction = async (action: 'reject' | 'validate', requisition: Requisition) => {
    setCurrentAction(action)
    setSelectedRequisition(requisition)

    if (requisition.type_requisition === 'remboursement_transport') {
      try {
        const res: any = await apiRequest('GET', '/remboursements-transport', { params: { requisition_id: requisition.id, limit: 1 } })
        const data = Array.isArray(res) ? res[0] : res
        if (data?.numero_remboursement) setRemboursementNumber(data.numero_remboursement)
      } catch {}
    }

    if (action === 'validate') return handleValidateImmediate(requisition)
    setShowActionModal(true)
  }

  const handleValidateImmediate = async (requisition: Requisition) => {
    setActionLoadingId(requisition.id)
    try {
      await apiRequest('POST', `/requisitions/${requisition.id}/validate`)

      showSuccess(
        'Réquisition validée',
        `La réquisition ${requisition.numero_requisition} a été validée avec succès.\n\nElle est maintenant disponible pour les sorties de fonds.`
      )

      loadRequisitions()
    } catch (error) {
      console.error('Error validating requisition:', error)
      showError('Erreur de validation', 'Impossible de valider la réquisition. Veuillez réessayer.')
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
      showError('Erreur de traitement', 'Une erreur est survenue lors du rejet de la réquisition.')
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
      VALIDEE: { label: 'Validée', class: styles.statutValidee },
      REJETEE: { label: 'Rejetée', class: styles.statutRejetee },
      brouillon: { label: 'En attente', class: styles.statutBrouillon },
      validee_tresorerie: { label: 'Validée (Trésorerie)', class: styles.statutValidee },
      approuvee: { label: 'Approuvée', class: styles.statutApprouvee },
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
    return <div className={styles.loading}>Chargement...</div>
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
                return (
                  <tr key={req.id}>
                    <td><strong>{req.numero_requisition}</strong></td>
                    <td>{getTypeBadge(req.type_requisition)}</td>
                    <td className={styles.objetCell}>{req.objet}</td>
                    <td>{req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : 'N/A'}</td>
                    <td><strong>${formatAmount(req.montant_total)}</strong></td>
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
                              {remboursementActionLoadingId === req.id ? 'Chargement...' : 'Voir détails'}
                            </button>
                            <button
                              onClick={() => handlePrintRemboursement(req)}
                              className={styles.printBtn}
                              title="Imprimer le remboursement"
                              disabled={remboursementActionLoadingId === req.id}
                            >
                              Imprimer
                            </button>
                            <button
                              onClick={() => handleDownloadRemboursement(req)}
                              className={styles.downloadBtn}
                              title="Télécharger le remboursement"
                              disabled={remboursementActionLoadingId === req.id}
                            >
                              Télécharger
                            </button>
                          </>
                        )}
                        {canAct && (
                          <>
                            <button
                              onClick={() => handleAction('validate', req)}
                              className={styles.validateBtn}
                              title="Valider"
                              disabled={isBusy}
                            >
                              {isBusy && currentAction === 'validate' ? 'Validation...' : '✓ Valider'}
                            </button>
                            <button
                              onClick={() => handleAction('reject', req)}
                              className={styles.rejectBtn}
                              title="Rejeter"
                              disabled={isBusy}
                            >
                              {isBusy && currentAction === 'reject' ? 'Rejet...' : '✗ Rejeter'}
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

    </div>
  )
}
