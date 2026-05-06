import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { buildBudgetDecisionSummary, formatBudgetDecisionAmount } from '../utils/budgetDecision'
import { generateGroupedRequisitionPDF, generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import { generateRemboursementTransportPDF } from '../utils/pdfGeneratorRemboursement'
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import type { Requisition } from '../types'
import { useConfirm } from '../contexts/ConfirmContext'
import styles from './ExamenDossier.module.css'

type Dossier = {
  id: string
  reference: string
  status: string
  description?: string | null
  commentaires_examen?: string | null
  requisitions: Requisition[]
}

type TransportDocument = {
  id?: string
  numero_remboursement?: string | null
  reference_numero?: string | null
  participants?: any[] | null
  [key: string]: any
}

const statusSteps = ['BROUILLON', 'EN_EXAMEN', 'EXAMINE', 'REJETE']

export default function ExamenDossier() {
  const { dossierId } = useParams()
  const navigate = useNavigate()
  const confirm = useConfirm()
  const [loading, setLoading] = useState(true)
  const [dossier, setDossier] = useState<Dossier | null>(null)
  const [commentaire, setCommentaire] = useState('')
  const [actionLoading, setActionLoading] = useState<'validate' | 'reject' | null>(null)
  const [selectedReqDetail, setSelectedReqDetail] = useState<Requisition | null>(null)
  const [selectedReqLignes, setSelectedReqLignes] = useState<any[]>([])
  const [selectedReqBudgetLines, setSelectedReqBudgetLines] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [rejectTarget, setRejectTarget] = useState<Requisition | null>(null)
  const [rejectComment, setRejectComment] = useState('')
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

  const loadDossier = async () => {
    if (!dossierId) return
    setLoading(true)
    try {
      const res: any = await apiRequest('GET', `/dossiers/${dossierId}`)
      setDossier(res)
      setCommentaire(res?.commentaires_examen || '')
      const transportReqIds = (res?.requisitions || [])
        .filter((req: any) => String(req?.type_requisition || '').toLowerCase() === 'remboursement_transport')
        .map((req: any) => String(req.id))
      if (transportReqIds.length > 0) {
        try {
          const transportResults = await Promise.all(
            transportReqIds.map((reqId: string) =>
              apiRequest('GET', '/remboursements-transport', { params: { requisition_id: reqId, include: 'participants', limit: 1 } })
            )
          )
          const refs: Record<string, TransportDocument> = {}
          transportResults.forEach((result: any, index) => {
            const transport = Array.isArray(result) ? result[0] : (result?.items?.[0] ?? null)
            if (!transport) return
            refs[transportReqIds[index]] = transport
          })
          setTransportsByReqId(refs)
        } catch (transportError) {
          console.error('Error loading transport references:', transportError)
          setTransportsByReqId({})
        }
      } else {
        setTransportsByReqId({})
      }
    } catch (error) {
      console.error('Error loading dossier:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de charger le dossier d'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
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
      await confirm({
        title: 'Erreur',
        description: "Impossible de valider l'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
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
      await confirm({
        title: 'Erreur',
        description: "Impossible de rejeter l'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
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
      await confirm({
        title: 'Erreur',
        description: 'Impossible de générer le PDF.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const loadRequisitionLines = async (reqId: string) => {
    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: reqId } })
    return Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
  }

  const isTransportDocument = (req: Requisition) => {
    return String((req as any).type_requisition || '').toLowerCase() === 'remboursement_transport'
  }

  const getTransportForRequisition = async (req: Requisition) => {
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

  const loadDocumentLines = async (req: Requisition) => {
    if (isTransportDocument(req)) {
      const transport = await getTransportForRequisition(req)
      if (!transport) return []
      if (Array.isArray(transport.participants)) return transport.participants
      const participantsRes: any = await apiRequest('GET', '/participants-transport', {
        params: { remboursement_id: transport.id, limit: 500 },
      })
      return Array.isArray(participantsRes) ? participantsRes : (participantsRes?.items ?? [])
    }
    return loadRequisitionLines(req.id)
  }

  const selectedReqBudgetSummary = buildBudgetDecisionSummary(
    selectedReqBudgetLines,
    selectedReqDetail?.montant_total
  )

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

  const handleViewRequisition = async (req: Requisition) => {
    setSelectedReqDetail(req)
    setDetailLoading(true)
    try {
      const [budgetLines, lignes] = await Promise.all([
        loadRequisitionLines(req.id),
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

  const handlePrintRequisition = async (req: Requisition) => {
    try {
      const lignes = await loadDocumentLines(req)
      if (isTransportDocument(req)) {
        let transport = (req as any).remboursement_transport
        if (!transport) {
          transport = await getTransportForRequisition(req)
        }
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

  const handleDownloadRequisition = async (req: Requisition) => {
    try {
      const lignes = await loadDocumentLines(req)
      if (isTransportDocument(req)) {
        let transport = (req as any).remboursement_transport
        if (!transport) {
          transport = await getTransportForRequisition(req)
        }
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

  const handleRejectRequisition = async (req: Requisition) => {
    try {
      await apiRequest('POST', `/requisitions/${req.id}/reject-examen`, { commentaire: rejectComment.trim() || null })
      await loadDossier()
    } catch (error) {
      console.error('Error rejecting requisition exam:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de rejeter la réquisition.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
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
    const confirmed = await confirm({
      title: 'Retirer la réquisition',
      description: 'Retirer cette réquisition du dossier ?',
      confirmText: 'Retirer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!confirmed) return
    try {
      const res: any = await apiRequest('POST', `/dossiers/${dossierId}/remove-requisitions`, {
        requisition_ids: [requisitionId],
      })
      setDossier(res)
    } catch (error) {
      console.error('Error removing requisition from dossier:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de retirer la réquisition du dossier.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  function getDocumentReference(req: Requisition) {
    if (isTransportDocument(req)) {
      const rt = (req as any).remboursement_transport
      if (rt) {
        return rt.reference_numero || rt.numero_remboursement || req.numero_requisition || '-'
      }
      const transportRef = transportsByReqId[String(req.id)]
      return transportRef?.reference_numero || transportRef?.numero_remboursement || req.numero_requisition
    }
    return req.numero_requisition
  }

  const getDocumentTypeLabel = (req: Requisition) => {
    return isTransportDocument(req) ? 'Remboursement transport' : 'Réquisition'
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
            <div className={styles.infoLabel}>Nombre de documents</div>
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
          <div className={styles.sectionTitle}>Documents à examiner</div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Référence</th>
                <th>Type</th>
                <th>Objet</th>
                <th>Bénéficiaire</th>
                <th className={styles.alignRight}>Montant</th>
                <th className={styles.alignRight}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {dossier.requisitions.map((req) => (
                <tr key={req.id}>
                  <td>{getDocumentReference(req)}</td>
                  <td>{getDocumentTypeLabel(req)}</td>
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
                      {req.annexe?.id && (
                        <button type="button" className={styles.ghostAction} onClick={() => openRequisitionAnnexe(req.annexe)}>
                          Voir pièce jointe
                        </button>
                      )}
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
                <td colSpan={4} className={styles.alignRight}>
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
          <div className={styles.modalContent} style={{maxWidth: '900px'}}>
            <div className={styles.modalHeader}>
              <h2>Détails de {getDocumentTypeLabel(selectedReqDetail).toLowerCase()} {getDocumentReference(selectedReqDetail)}</h2>
              <button type="button" className={styles.closeBtn} onClick={() => setSelectedReqDetail(null)}>
                ✕
              </button>
            </div>
            {detailLoading ? (
              <div className={styles.loading}>Chargement...</div>
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
                      <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{formatCurrency(selectedReqDetail.montant_total)}</strong></p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Statut</label>
                      <p>{String((selectedReqDetail as any).status ?? (selectedReqDetail as any).statut ?? '')}</p>
                    </div>
                    <div className={styles.detailItem}>
                      <label>Date de création</label>
                      <p>{selectedReqDetail.created_at ? new Date(selectedReqDetail.created_at).toLocaleString('fr-FR') : '-'}</p>
                    </div>
                  </div>
                </div>

                <div className={styles.detailSection}>
                  <h3>Snapshot budgétaire à la demande</h3>
                  <div className={styles.budgetDecisionGrid}>
                    <div className={styles.budgetDecisionCard}>
                      <div className={styles.label}>Budget</div>
                      <div className={styles.budgetDecisionValue}>{formatBudgetDecisionAmount(selectedReqBudgetSummary.budget)}</div>
                    </div>
                    <div className={styles.budgetDecisionCard}>
                      <div className={styles.label}>Engagé</div>
                      <div className={styles.budgetDecisionValue}>{formatBudgetDecisionAmount(selectedReqBudgetSummary.engaged)}</div>
                    </div>
                    <div className={styles.budgetDecisionCard}>
                      <div className={styles.label}>Disponible</div>
                      <div className={styles.budgetDecisionValue}>{formatBudgetDecisionAmount(selectedReqBudgetSummary.available)}</div>
                    </div>
                    <div className={styles.budgetDecisionCard}>
                      <div className={styles.label}>Solde après cette demande</div>
                      <div className={styles.budgetDecisionValue}>{formatBudgetDecisionAmount(selectedReqBudgetSummary.remainingAfterRequest)}</div>
                    </div>
                  </div>
                </div>

                <div className={styles.detailSection}>
                  <h3>{isTransportDocument(selectedReqDetail) ? 'Participants au remboursement' : 'Lignes de dépense'}</h3>
                  {isTransportDocument(selectedReqDetail) ? (
                    <table className={styles.detailTable}>
                      <thead>
                        <tr>
                          <th style={{ width: '40px' }}>N°</th>
                          <th>Participant</th>
                          <th>Fonction</th>
                          <th>Type</th>
                          <th className={styles.alignRight}>Montant</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedReqLignes.length === 0 ? (
                          <tr>
                            <td colSpan={5} className={styles.loading}>Aucun participant</td>
                          </tr>
                        ) : (
                          selectedReqLignes.map((participant: any, index: number) => (
                            <tr key={participant.id || `${participant.nom}-${participant.titre_fonction}`}>
                              <td style={{ textAlign: 'center', fontWeight: 600 }}>{index + 1}</td>
                              <td>{participant.nom}</td>
                              <td>{participant.titre_fonction}</td>
                              <td>{participant.type_participant}</td>
                              <td className={styles.alignRight}>
                                <strong>{formatCurrency(participant.montant)}</strong>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  ) : (
                    <table className={styles.detailTable}>
                      <thead>
                        <tr>
                          <th>Poste budgétaire</th>
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
                              <td><span className={styles.rubriqueTag}>{getLignePosteLabel(ligne)}</span></td>
                              <td>{ligne.description}</td>
                              <td className={styles.alignRight}>
                                <strong>{formatCurrency(ligne.montant_total)}</strong>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {rejectTarget && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>Rejeter {getDocumentTypeLabel(rejectTarget).toLowerCase()} {getDocumentReference(rejectTarget)}</h3>
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
