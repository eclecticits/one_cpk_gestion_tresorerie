import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, ChevronRight, Download, Eye, FileText, Paperclip, RefreshCw, Search, X } from 'lucide-react'
import { apiRequest, API_BASE_URL } from '../lib/apiClient'
import { generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import styles from './DossiersExamen.module.css'

type Dossier = {
  id: string
  reference: string
  status: string
  commentaires_examen?: string | null
  requisitions: Array<{ montant_total?: number | string }>
  created_by?: string | null
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
  TRAITEMENT: 'Traitement',
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
  const [searchQuery, setSearchQuery] = useState('')
  const [dossierPage, setDossierPage] = useState(0)
  const [requisitionPage, setRequisitionPage] = useState(0)
  const pageSize = 20

  const [selectedDossiers, setSelectedDossiers] = useState<Set<string>>(new Set())
  const [selectedRequisitions, setSelectedRequisitions] = useState<Set<string>>(new Set())
  const [bulkAction, setBulkAction] = useState<'validate' | 'reject' | null>(null)
  const [bulkComment, setBulkComment] = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)

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

  const loadDossiers = async () => {
    setLoading(true)
    try {
      const res: any = await apiRequest('GET', '/dossiers', { params: { include_requisitions: true, status: 'EN_EXAMEN' } })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setDossiers(items)
      const enExam: any = await apiRequest('GET', '/requisitions', {
        params: { examen_status: 'EN_EXAMEN', dossier_is_null: true, limit: 200 },
      })
      const listB = Array.isArray(enExam) ? enExam : (enExam?.items ?? [])
      setRequisitions(listB)
      setSelectedDossiers(new Set())
      setSelectedRequisitions(new Set())
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

  const toggleDossier = (id: string) => {
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

  const filteredDossiers = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase()
    const list = needle
      ? dossiers.filter((dossier) => {
          const status = String(dossier.status || '')
          return [dossier.reference, status, dossier.created_by || '']
            .join(' ')
            .toLowerCase()
            .includes(needle)
        })
      : dossiers
    return [...list].sort((a, b) => parseDateValue(b.created_at) - parseDateValue(a.created_at))
  }, [dossiers, searchQuery])

  const filteredRequisitions = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase()
    const list = needle
      ? requisitions.filter((req) => {
          return [req.numero_requisition, req.objet, req.examen_status || '']
            .join(' ')
            .toLowerCase()
            .includes(needle)
        })
      : requisitions
    return [...list].sort((a, b) => parseDateValue(b.created_at) - parseDateValue(a.created_at))
  }, [requisitions, searchQuery])

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
  }, [searchQuery])

  const allDossiersSelected = filteredDossiers.length > 0 && filteredDossiers.every((d) => selectedDossiers.has(d.id))
  const allRequisitionsSelected =
    filteredRequisitions.length > 0 && filteredRequisitions.every((r) => selectedRequisitions.has(r.id))
  const selectedCount = selectedDossiers.size + selectedRequisitions.size

  const openBulkAction = (action: 'validate' | 'reject') => {
    if (selectedCount === 0) {
      window.alert('Aucun dossier ou réquisition sélectionné.')
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
    const dossierIds = Array.from(selectedDossiers)
    const requisitionIds = Array.from(selectedRequisitions)
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
      window.alert("Impossible d'appliquer l'action à la sélection.")
    } finally {
      setBulkLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.controlPanel}>
        <div className={styles.panelRow}>
          <div className={styles.breadcrumb}>
            <span className={styles.crumb}>Réquisitions</span>
            <ChevronRight size={14} className={styles.crumbDivider} />
            <span className={styles.crumbCurrent}>Examen des dossiers</span>
          </div>

          <div className={styles.searchWrap}>
            <Search size={16} className={styles.searchIcon} />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Rechercher un dossier ou une réquisition..."
              className={styles.searchInput}
            />
          </div>

          <div className={styles.statusbar}>
            <span className={`${styles.statusStep} ${styles.statusStepMuted}`}>Brouillon</span>
            <span className={`${styles.statusStep} ${styles.statusStepActive}`}>Examen</span>
            <span className={`${styles.statusStep} ${styles.statusStepMuted}`}>Bureau</span>
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
                        setSelectedDossiers(new Set(filteredDossiers.map((d) => d.id)))
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
                  return (
                    <tr key={dossier.id} className={styles.tableRow}>
                      <td className={styles.checkboxCell}>
                        <input
                          type="checkbox"
                          className={styles.checkbox}
                          checked={selectedDossiers.has(dossier.id)}
                          onChange={() => toggleDossier(dossier.id)}
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
                      <td>{(dossier.requisitions || []).length}</td>
                      <td className={styles.amount}>
                        {total.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}
                      </td>
                      <td>{new Date(dossier.created_at).toLocaleDateString('fr-FR')}</td>
                      <td className={styles.actionsCell}>
                        <div className={styles.actionGroup}>
                          <Link
                            to={`/requisitions/examen/${dossier.id}`}
                            className={styles.iconButton}
                            title="Ouvrir le dossier"
                            aria-label="Ouvrir le dossier"
                          >
                            <Eye size={16} />
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
        <div className={styles.sectionTitle}>Réquisitions individuelles à examiner</div>
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
                        setSelectedRequisitions(new Set(filteredRequisitions.map((r) => r.id)))
                      } else {
                        setSelectedRequisitions(new Set())
                      }
                    }}
                    aria-label="Sélectionner toutes les réquisitions"
                  />
                </th>
                <th>Référence</th>
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
                  <td colSpan={7} className={styles.empty}>Chargement...</td>
                </tr>
              ) : pagedRequisitions.length === 0 ? (
                <tr>
                  <td colSpan={7} className={styles.empty}>Aucune réquisition à examiner</td>
                </tr>
              ) : (
                pagedRequisitions.map((req) => {
                  const exam = String(req.examen_status || '').toUpperCase()
                  return (
                    <tr key={req.id} className={styles.tableRow}>
                      <td className={styles.checkboxCell}>
                        <input
                          type="checkbox"
                          className={styles.checkbox}
                          checked={selectedRequisitions.has(req.id)}
                          onChange={() => toggleRequisition(req.id)}
                          aria-label={`Sélectionner ${req.numero_requisition}`}
                        />
                      </td>
                      <td className={styles.refCell}>{req.numero_requisition}</td>
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
                          <button
                            type="button"
                            className={styles.iconButton}
                            onClick={() => viewDetails(req)}
                            title="Voir les détails"
                            aria-label="Voir les détails"
                          >
                            <Eye size={16} />
                          </button>
                          <button
                            type="button"
                            className={styles.iconButton}
                            onClick={() => printRequisition(req)}
                            title="Imprimer"
                            aria-label="Imprimer"
                          >
                            <FileText size={16} />
                          </button>
                          <button
                            type="button"
                            className={styles.iconButton}
                            onClick={() => downloadRequisition(req)}
                            title="Télécharger"
                            aria-label="Télécharger"
                          >
                            <Download size={16} />
                          </button>
                          <button
                            type="button"
                            className={styles.iconButton}
                            onClick={() => openPreview(req)}
                            title="Prévisualiser"
                            aria-label="Prévisualiser"
                          >
                            <Eye size={16} />
                          </button>
                          {req.annexe?.id && (
                            <button
                              type="button"
                              className={styles.iconButton}
                              onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${req.annexe?.id}`, '_blank')}
                              title="Voir la pièce jointe"
                              aria-label="Voir la pièce jointe"
                            >
                              <Paperclip size={16} />
                            </button>
                          )}
                          {exam === 'NON_EXAMINE' && (
                            <button
                              type="button"
                              className={styles.textButton}
                              onClick={() => submitExamen(req.id)}
                              title="Soumettre à l'examen"
                              aria-label="Soumettre à l'examen"
                            >
                              Soumettre
                            </button>
                          )}
                          {exam === 'EN_EXAMEN' && (
                            <>
                              <button
                                type="button"
                                className={styles.textButton}
                                onClick={() => openCommentModal('validate', req)}
                                title="Valider l'examen"
                                aria-label="Valider l'examen"
                              >
                                Valider
                              </button>
                              <button
                                type="button"
                                className={styles.rejectBtn}
                                onClick={() => openCommentModal('reject', req)}
                                title="Rejeter l'examen"
                                aria-label="Rejeter l'examen"
                              >
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
                    <thead className={styles.thead}>
                      <tr>
                        <th>Rubrique</th>
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

      {bulkAction && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>
                {bulkAction === 'validate' ? 'Valider la sélection' : 'Rejeter la sélection'} · {selectedCount} élément(s)
              </h3>
              <button type="button" className={styles.closeBtn} onClick={closeBulkAction}>
                ✕
              </button>
            </div>
            <div className={styles.modalLabel}>Commentaire (optionnel)</div>
            <textarea
              className={styles.textarea}
              rows={4}
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
