import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest, API_BASE_URL } from '../lib/apiClient'
import { generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import styles from './DossiersExamen.module.css'

type Dossier = {
  id: string
  reference: string
  status: string
  commentaires_examen?: string | null
  requisitions: Array<{ montant_total?: number | string }>
  created_at: string
}

type RequisitionItem = {
  id: string
  numero_requisition: string
  objet: string
  montant_total?: number | string
  examen_status?: string
  created_at?: string
  annexe?: { id: string }
}

const statusLabels: Record<string, string> = {
  BROUILLON: 'Brouillon',
  EN_EXAMEN: 'En examen',
  EXAMINE: 'Examiné',
  REJETE: 'Rejeté',
}

export default function DossiersExamen() {
  const [loading, setLoading] = useState(true)
  const [dossiers, setDossiers] = useState<Dossier[]>([])
  const [requisitions, setRequisitions] = useState<RequisitionItem[]>([])
  const [selectedReqDetail, setSelectedReqDetail] = useState<RequisitionItem | null>(null)
  const [selectedReqLignes, setSelectedReqLignes] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [commentMode, setCommentMode] = useState<'validate' | 'reject' | null>(null)
  const [commentReq, setCommentReq] = useState<RequisitionItem | null>(null)
  const [commentText, setCommentText] = useState('')
  const [previewReq, setPreviewReq] = useState<RequisitionItem | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const loadDossiers = async () => {
    setLoading(true)
    try {
      const res: any = await apiRequest('GET', '/dossiers', { params: { include_requisitions: true } })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setDossiers(items)
      const [nonExam, enExam] = await Promise.all([
        apiRequest('GET', '/requisitions', { params: { examen_status: 'NON_EXAMINE', dossier_is_null: true, limit: 200 } }),
        apiRequest('GET', '/requisitions', { params: { examen_status: 'EN_EXAMEN', dossier_is_null: true, limit: 200 } }),
      ])
      const listA = Array.isArray(nonExam) ? nonExam : (nonExam?.items ?? [])
      const listB = Array.isArray(enExam) ? enExam : (enExam?.items ?? [])
      const merged = [...listA, ...listB]
      const uniq = new Map(merged.map((r: any) => [r.id, r]))
      setRequisitions(Array.from(uniq.values()))
    } catch (error) {
      console.error('Error loading dossiers:', error)
      window.alert("Impossible de charger les dossiers d'examen.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDossiers()
  }, [])

  const submitExamen = async (reqId: string) => {
    try {
      await apiRequest('POST', `/requisitions/${reqId}/submit-examen`)
      await loadDossiers()
    } catch (error) {
      console.error('Error submitting examen:', error)
      window.alert("Impossible de soumettre la réquisition à l'examen.")
    }
  }

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
        await apiRequest('POST', `/requisitions/${commentReq.id}/validate-examen`, { commentaire })
      } else {
        await apiRequest('POST', `/requisitions/${commentReq.id}/reject-examen`, { commentaire })
      }
      closeCommentModal()
      await loadDossiers()
    } catch (error) {
      console.error('Error examen action:', error)
      window.alert("Impossible de terminer l'examen.")
    }
  }

  const viewDetails = async (req: RequisitionItem) => {
    setSelectedReqDetail(req)
    setDetailLoading(true)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
      setSelectedReqLignes(lignes)
    } catch (error) {
      console.error('Error loading requisition details:', error)
      setSelectedReqLignes([])
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetails = () => {
    setSelectedReqDetail(null)
    setSelectedReqLignes([])
    setDetailLoading(false)
  }

  const printRequisition = async (req: RequisitionItem) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
      await generateSingleRequisitionPDF(req as any, lignes, 'print', '')
    } catch (error) {
      console.error('Error printing requisition:', error)
      window.alert('Impossible d’imprimer la réquisition.')
    }
  }

  const downloadRequisition = async (req: RequisitionItem) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
      await generateSingleRequisitionPDF(req as any, lignes, 'download', '')
    } catch (error) {
      console.error('Error downloading requisition:', error)
      window.alert('Impossible de télécharger la réquisition.')
    }
  }

  const openPreview = async (req: RequisitionItem) => {
    setPreviewReq(req)
    setPreviewLoading(true)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? [])
      const blob: any = await generateSingleRequisitionPDF(req as any, lignes, 'blob', '')
      if (blob) {
        const url = URL.createObjectURL(blob)
        setPreviewUrl(url)
      }
    } catch (error) {
      console.error('Error previewing requisition:', error)
      window.alert('Impossible de prévisualiser la réquisition.')
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

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.title}>Dossiers d'examen</div>
          <div className={styles.subtitle}>Suivi des regroupements soumis à examen</div>
        </div>
        <button type="button" className={styles.refreshBtn} onClick={loadDossiers} disabled={loading}>
          Rafraîchir
        </button>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Référence</th>
              <th>Statut</th>
              <th>Réquisitions</th>
              <th>Montant total</th>
              <th>Créé le</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Chargement...</td>
              </tr>
            ) : dossiers.length === 0 ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Aucun dossier trouvé</td>
              </tr>
            ) : (
              dossiers.map((dossier) => {
                const total = (dossier.requisitions || []).reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
                const status = String(dossier.status || '').toUpperCase()
                return (
                  <tr key={dossier.id}>
                    <td className={styles.refCell}>{dossier.reference}</td>
                    <td>
                      <span className={`${styles.status} ${styles[`status_${status}`] || ''}`}>
                        {statusLabels[status] || status}
                      </span>
                    </td>
                    <td>{(dossier.requisitions || []).length}</td>
                    <td className={styles.amount}>
                      {total.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                    </td>
                    <td>{new Date(dossier.created_at).toLocaleDateString('fr-FR')}</td>
                    <td className={styles.actionsCell}>
                      <div className={styles.actions}>
                        <Link to={`/requisitions/examen/${dossier.id}`} className={styles.openLink}>
                          Ouvrir
                        </Link>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.sectionTitle}>Réquisitions individuelles à examiner</div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Référence</th>
              <th>Objet</th>
              <th>Statut examen</th>
              <th>Montant</th>
              <th>Créé le</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Chargement...</td>
              </tr>
            ) : requisitions.length === 0 ? (
              <tr>
                <td colSpan={6} className={styles.empty}>Aucune réquisition à examiner</td>
              </tr>
            ) : (
              requisitions.map((req) => {
                const exam = String(req.examen_status || '').toUpperCase()
                return (
                  <tr key={req.id}>
                    <td className={styles.refCell}>{req.numero_requisition}</td>
                    <td>{req.objet}</td>
                    <td>{statusLabels[exam] || exam || 'Non examiné'}</td>
                    <td className={styles.amount}>
                      {Number(req.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                    </td>
                    <td>{req.created_at ? new Date(req.created_at).toLocaleDateString('fr-FR') : '-'}</td>
                    <td className={styles.actionsCell}>
                      <div className={styles.actions}>
                        <button type="button" className={styles.openLink} onClick={() => viewDetails(req)}>
                          Voir
                        </button>
                        <button type="button" className={styles.openLink} onClick={() => printRequisition(req)}>
                          Imprimer
                        </button>
                        <button type="button" className={styles.openLink} onClick={() => downloadRequisition(req)}>
                          Télécharger
                        </button>
                        <button type="button" className={styles.openLink} onClick={() => openPreview(req)}>
                          Prévisualiser
                        </button>
                        {req.annexe?.id && (
                          <button
                            type="button"
                            className={styles.openLink}
                            onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${req.annexe?.id}`, '_blank')}
                          >
                            PJ
                          </button>
                        )}
                        {exam === 'NON_EXAMINE' && (
                          <button type="button" className={styles.openLink} onClick={() => submitExamen(req.id)}>
                            Soumettre
                          </button>
                        )}
                        {exam === 'EN_EXAMEN' && (
                          <>
                            <button type="button" className={styles.openLink} onClick={() => openCommentModal('validate', req)}>
                              Valider
                            </button>
                            <button type="button" className={styles.rejectBtn} onClick={() => openCommentModal('reject', req)}>
                              Rejeter
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {selectedReqDetail && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>Détails de la réquisition {selectedReqDetail.numero_requisition}</h3>
              <button type="button" className={styles.closeBtn} onClick={closeDetails}>
                ✕
              </button>
            </div>
            {detailLoading ? (
              <div className={styles.empty}>Chargement...</div>
            ) : (
              <>
                <div className={styles.modalGrid}>
                  <div>
                    <div className={styles.modalLabel}>Objet</div>
                    <div className={styles.modalValue}>{selectedReqDetail.objet}</div>
                  </div>
                  <div>
                    <div className={styles.modalLabel}>Montant total</div>
                    <div className={styles.modalValue}>
                      {Number(selectedReqDetail.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                    </div>
                  </div>
                  <div>
                    <div className={styles.modalLabel}>Statut examen</div>
                    <div className={styles.modalValue}>{selectedReqDetail.examen_status || 'NON_EXAMINE'}</div>
                  </div>
                  <div>
                    <div className={styles.modalLabel}>Créé le</div>
                    <div className={styles.modalValue}>
                      {selectedReqDetail.created_at ? new Date(selectedReqDetail.created_at).toLocaleString('fr-FR') : '-'}
                    </div>
                  </div>
                </div>
                <div className={styles.modalTableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Rubrique</th>
                        <th>Description</th>
                        <th>Qté</th>
                        <th>Montant</th>
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
                            <td>{ligne.rubrique}</td>
                            <td>{ligne.description}</td>
                            <td>{ligne.quantite}</td>
                            <td className={styles.amount}>
                              {Number(ligne.montant_total || 0).toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {commentMode && commentReq && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>
                {commentMode === 'validate' ? 'Valider l’examen' : 'Rejeter l’examen'} · {commentReq.numero_requisition}
              </h3>
              <button type="button" className={styles.closeBtn} onClick={closeCommentModal}>
                ✕
              </button>
            </div>
            <div className={styles.modalLabel}>Commentaire (optionnel)</div>
            <textarea
              className={styles.textarea}
              rows={4}
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

      {previewReq && (
        <div className={styles.modal}>
          <div className={styles.previewContent}>
            <div className={styles.modalHeader}>
              <h3>Prévisualisation · {previewReq.numero_requisition}</h3>
              <button type="button" className={styles.closeBtn} onClick={closePreview}>
                ✕
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
