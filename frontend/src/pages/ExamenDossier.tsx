import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { generateGroupedRequisitionPDF, generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import type { Requisition } from '../types'
import styles from './ExamenDossier.module.css'

type Dossier = {
  id: string
  reference: string
  status: string
  description?: string | null
  commentaires_examen?: string | null
  requisitions: Requisition[]
}

const statusSteps = ['BROUILLON', 'EN_EXAMEN', 'EXAMINE', 'REJETE']

export default function ExamenDossier() {
  const { dossierId } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [dossier, setDossier] = useState<Dossier | null>(null)
  const [commentaire, setCommentaire] = useState('')
  const [actionLoading, setActionLoading] = useState<'validate' | 'reject' | null>(null)
  const [selectedReqDetail, setSelectedReqDetail] = useState<Requisition | null>(null)
  const [selectedReqLignes, setSelectedReqLignes] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [rejectTarget, setRejectTarget] = useState<Requisition | null>(null)
  const [rejectComment, setRejectComment] = useState('')

  const loadDossier = async () => {
    if (!dossierId) return
    setLoading(true)
    try {
      const res: any = await apiRequest('GET', `/dossiers/${dossierId}`)
      setDossier(res)
      setCommentaire(res?.commentaires_examen || '')
    } catch (error) {
      console.error('Error loading dossier:', error)
      window.alert("Impossible de charger le dossier d'examen.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDossier()
  }, [dossierId])

  const handleValidate = async () => {
    if (!dossierId) return
    setActionLoading('validate')
    try {
      const res: any = await apiRequest('POST', `/dossiers/${dossierId}/validate-examen`, {
        commentaires_examen: commentaire || null,
      })
      setDossier(res)
    } catch (error) {
      console.error('Error validating exam:', error)
      window.alert("Impossible de valider l'examen.")
    } finally {
      setActionLoading(null)
    }
  }

  const handleSubmitExamen = async () => {
    if (!dossierId) return
    setActionLoading('validate')
    try {
      const res: any = await apiRequest('POST', `/dossiers/${dossierId}/submit-examen`)
      setDossier(res)
    } catch (error) {
      console.error('Error submitting exam:', error)
      window.alert("Impossible de soumettre le dossier à l'examen.")
    } finally {
      setActionLoading(null)
    }
  }

  const handleReject = async () => {
    if (!dossierId) return
    setActionLoading('reject')
    try {
      const res: any = await apiRequest('POST', `/dossiers/${dossierId}/reject-examen`, {
        commentaires_examen: commentaire || null,
      })
      setDossier(res)
    } catch (error) {
      console.error('Error rejecting exam:', error)
      window.alert("Impossible de rejeter l'examen.")
    } finally {
      setActionLoading(null)
    }
  }

  const handleDownloadPdf = async () => {
    if (!dossier) return
    try {
      await generateGroupedRequisitionPDF(dossier)
    } catch (error) {
      console.error('Error generating grouped PDF:', error)
      window.alert('Impossible de générer le PDF.')
    }
  }

  const loadRequisitionLines = async (reqId: string) => {
    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: reqId } })
    return Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
  }

  const handleViewRequisition = async (req: Requisition) => {
    setSelectedReqDetail(req)
    setDetailLoading(true)
    try {
      const lignes = await loadRequisitionLines(req.id)
      setSelectedReqLignes(lignes)
    } catch (error) {
      console.error('Error loading requisition details:', error)
      setSelectedReqLignes([])
    } finally {
      setDetailLoading(false)
    }
  }

  const handlePrintRequisition = async (req: Requisition) => {
    try {
      const lignes = await loadRequisitionLines(req.id)
      await generateSingleRequisitionPDF(req as any, lignes, 'print', '')
    } catch (error) {
      console.error('Error printing requisition:', error)
      window.alert('Impossible d’imprimer la réquisition.')
    }
  }

  const handleDownloadRequisition = async (req: Requisition) => {
    try {
      const lignes = await loadRequisitionLines(req.id)
      await generateSingleRequisitionPDF(req as any, lignes, 'download', '')
    } catch (error) {
      console.error('Error downloading requisition:', error)
      window.alert('Impossible de télécharger la réquisition.')
    }
  }

  const handleRejectRequisition = async (req: Requisition) => {
    try {
      await apiRequest('POST', `/requisitions/${req.id}/reject-examen`, { commentaire: rejectComment.trim() || null })
      await loadDossier()
    } catch (error) {
      console.error('Error rejecting requisition exam:', error)
      window.alert("Impossible de rejeter la réquisition.")
    }
  }

  const openRejectModal = (req: Requisition) => {
    setRejectTarget(req)
    setRejectComment('')
  }

  const closeRejectModal = () => {
    setRejectTarget(null)
    setRejectComment('')
  }

  const handleRemoveRequisition = async (requisitionId: string) => {
    if (!dossierId) return
    const confirmed = window.confirm('Retirer cette réquisition du dossier ?')
    if (!confirmed) return
    try {
      const res: any = await apiRequest('POST', `/dossiers/${dossierId}/remove-requisitions`, {
        requisition_ids: [requisitionId],
      })
      setDossier(res)
    } catch (error) {
      console.error('Error removing requisition from dossier:', error)
      window.alert("Impossible de retirer la réquisition du dossier.")
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  if (!dossier) {
    return <div className={styles.loading}>Dossier introuvable.</div>
  }

  const currentStatus = String(dossier.status || '').toUpperCase()

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <button type="button" className={styles.backBtn} onClick={() => navigate(-1)}>
            ← Retour
          </button>
          <div>
            <div className={styles.headerTitle}>Dossier d'examen</div>
            <div className={styles.headerRef}>{dossier.reference}</div>
          </div>
        </div>
        <div className={styles.statusBar}>
          {statusSteps.map((step) => (
            <span
              key={step}
              className={`${styles.statusStep} ${step === currentStatus ? styles.statusStepActive : ''}`}
            >
              {step.replace('_', ' ')}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.actionBar}>
        {currentStatus === 'BROUILLON' && (
          <button
            type="button"
            className={styles.primaryAction}
            onClick={handleSubmitExamen}
            disabled={actionLoading !== null}
          >
            {actionLoading === 'validate' ? "Soumission..." : "Soumettre à l'examen"}
          </button>
        )}
        {currentStatus === 'EN_EXAMEN' && (
          <>
            <button
              type="button"
              className={styles.primaryAction}
              onClick={handleValidate}
              disabled={actionLoading !== null}
            >
              {actionLoading === 'validate' ? "Validation..." : "Approuver l'examen"}
            </button>
            <button
              type="button"
              className={styles.secondaryAction}
              onClick={handleReject}
              disabled={actionLoading !== null}
            >
              {actionLoading === 'reject' ? 'Rejet...' : 'Rejeter'}
            </button>
          </>
        )}
        <button type="button" className={styles.ghostAction} onClick={handleDownloadPdf}>
          Télécharger PDF
        </button>
      </div>

      <div className={styles.sheet}>
        <div className={styles.sheetHeader}>
          <div>
            <div className={styles.label}>Référence Dossier</div>
            <div className={styles.value}>{dossier.reference}</div>
          </div>
          <div className={styles.badge}>{currentStatus.replace('_', ' ')}</div>
        </div>

        <div className={styles.infoGrid}>
          <div>
            <div className={styles.infoLabel}>Nombre de réquisitions</div>
            <div className={styles.infoValue}>{dossier.requisitions.length}</div>
          </div>
          <div>
            <div className={styles.infoLabel}>Montant total</div>
            <div className={styles.infoValue}>
              {dossier.requisitions
                .reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
                .toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
            </div>
          </div>
        </div>

        <div className={styles.tableSection}>
          <div className={styles.sectionTitle}>Réquisitions à examiner</div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Référence</th>
                <th>Objet</th>
                <th>Bénéficiaire</th>
                <th className={styles.alignRight}>Montant</th>
                <th className={styles.alignRight}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {dossier.requisitions.map((req) => (
                <tr key={req.id}>
                  <td>{req.numero_requisition}</td>
                  <td>{req.objet}</td>
                  <td>{req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : '—'}</td>
                  <td className={styles.alignRight}>
                    {Number(req.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                  </td>
                  <td className={styles.alignRight}>
                    <div className={styles.inlineActions}>
                      <button type="button" className={styles.ghostAction} onClick={() => handleViewRequisition(req)}>
                        Voir détails
                      </button>
                      <button type="button" className={styles.ghostAction} onClick={() => handlePrintRequisition(req)}>
                        Imprimer PDF
                      </button>
                      <button type="button" className={styles.ghostAction} onClick={() => handleDownloadRequisition(req)}>
                        Télécharger PDF
                      </button>
                      <button type="button" className={styles.dangerAction} onClick={() => openRejectModal(req)}>
                        Rejeter
                      </button>
                      {currentStatus === 'BROUILLON' && (
                        <button
                          type="button"
                          className={styles.ghostAction}
                          onClick={() => handleRemoveRequisition(String(req.id))}
                        >
                          Retirer
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3} className={styles.alignRight}>
                  Total
                </td>
                <td className={styles.alignRight}>
                  {dossier.requisitions
                    .reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
                    .toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        <div className={styles.commentSection}>
          <label className={styles.label}>Commentaire de l'examen</label>
          <textarea
            className={styles.textarea}
            rows={4}
            value={commentaire}
            onChange={(e) => setCommentaire(e.target.value)}
            placeholder="Ajouter une remarque sur la conformité du dossier..."
          />
        </div>
      </div>

      {selectedReqDetail && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>Détails de la réquisition {selectedReqDetail.numero_requisition}</h3>
              <button type="button" className={styles.closeBtn} onClick={() => setSelectedReqDetail(null)}>
                ✕
              </button>
            </div>
            {detailLoading ? (
              <div className={styles.loading}>Chargement...</div>
            ) : (
              <div className={styles.detailGrid}>
                <div>
                  <div className={styles.label}>Objet</div>
                  <div className={styles.value}>{selectedReqDetail.objet}</div>
                </div>
                <div>
                  <div className={styles.label}>Montant</div>
                  <div className={styles.value}>
                    {Number(selectedReqDetail.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                  </div>
                </div>
                <div>
                  <div className={styles.label}>Statut</div>
                  <div className={styles.value}>{String((selectedReqDetail as any).status ?? (selectedReqDetail as any).statut ?? '')}</div>
                </div>
                <div>
                  <div className={styles.label}>Créé le</div>
                  <div className={styles.value}>{selectedReqDetail.created_at ? new Date(selectedReqDetail.created_at).toLocaleString('fr-FR') : '-'}</div>
                </div>
              </div>
            )}
            {!detailLoading && (
              <div className={styles.tableSection}>
                <div className={styles.sectionTitle}>Lignes de dépense</div>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Rubrique</th>
                      <th>Description</th>
                      <th className={styles.alignRight}>Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedReqLignes.length === 0 ? (
                      <tr>
                        <td colSpan={3} className={styles.loading}>Aucune ligne</td>
                      </tr>
                    ) : (
                      selectedReqLignes.map((ligne: any) => (
                        <tr key={ligne.id || `${ligne.rubrique}-${ligne.description}`}>
                          <td>{ligne.rubrique}</td>
                          <td>{ligne.description}</td>
                          <td className={styles.alignRight}>
                            {Number(ligne.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
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

      {rejectTarget && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>Rejeter la réquisition {rejectTarget.numero_requisition}</h3>
              <button type="button" className={styles.closeBtn} onClick={closeRejectModal}>
                ✕
              </button>
            </div>
            <div className={styles.commentSection}>
              <label className={styles.label}>Motif (optionnel)</label>
              <textarea
                className={styles.textarea}
                rows={4}
                value={rejectComment}
                onChange={(event) => setRejectComment(event.target.value)}
                placeholder="Ajoutez un motif de rejet..."
              />
            </div>
            <div className={styles.modalActions}>
              <button type="button" className={styles.secondaryAction} onClick={closeRejectModal}>
                Annuler
              </button>
              <button
                type="button"
                className={styles.dangerAction}
                onClick={async () => {
                  await handleRejectRequisition(rejectTarget)
                  closeRejectModal()
                }}
              >
                Confirmer le rejet
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
