import { useCallback, useEffect, useMemo, useState } from 'react'
import { PlusCircle, Wallet, CheckCircle, FileText, XCircle, ShieldCheck, Car } from 'lucide-react'
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
  const [rubriques, setRubriques] = useState<BudgetLine[]>([])
  const [members, setMembers] = useState<CommissionMember[]>([])
  const [serviceLabel, setServiceLabel] = useState<string>('Mon espace commission')
  const [loading, setLoading] = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [signError, setSignError] = useState<string | null>(null)
  const [commissionError, setCommissionError] = useState<string | null>(null)
  const [reqPage, setReqPage] = useState(1)
  const [postePage, setPostePage] = useState(1)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRequisition, setSelectedRequisition] = useState<RequisitionItem | null>(null)
  const [selectedLignes, setSelectedLignes] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [selectedRejectMotif, setSelectedRejectMotif] = useState<string>('')
  const [selectedRejectTitle, setSelectedRejectTitle] = useState<string>('')

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
      const [summaryRes, reqRes, rubRes, serviceRes, membersRes] = await Promise.all([
        apiRequest<ServiceSummary>('GET', '/budget/summary/mine', { params: { service_id: activeServiceId } }),
        apiRequest<RequisitionItem[]>('GET', '/requisitions/mine', { params: { service_id: activeServiceId } }),
        apiRequest<{ lignes: BudgetLine[] }>('GET', '/budget/lines/autorisees', { params: { active: true, type: 'DEPENSE', service_id: activeServiceId } }),
        getService(activeServiceId),
        getServiceMembers(activeServiceId),
      ])
      setSummary(summaryRes)
      const safeReqs = Array.isArray(reqRes) ? reqRes : []
      const filteredReqs = safeReqs.filter((req: any) => {
        const reqServiceId = req?.service_id ?? req?.service?.id ?? req?.serviceId
        return reqServiceId ? String(reqServiceId) === String(activeServiceId) : false
      })
      setRequisitions(filteredReqs)
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
  const canSign = Boolean(currentMember?.is_signer)

  const handleSign = async (requisitionId: string) => {
    setSigningId(requisitionId)
    setSignError(null)
    try {
      await apiRequest('PATCH', `/requisitions/${requisitionId}/sign`)
      await loadData()
    } catch (err: any) {
      setSignError(err?.message || 'Signature impossible.')
    } finally {
      setSigningId(null)
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

      <section className={styles.grid}>
        <div className={styles.panel}>
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
                  {requisitions
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
                          {canSign && req.status === 'EN_ATTENTE_COMMISSION' && (
                            <button
                              type="button"
                              className={styles.btnSign}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleSign(req.id)
                              }}
                              disabled={signingId === req.id}
                            >
                              <ShieldCheck size={16} />
                              {signingId === req.id ? 'Signature…' : 'Approuver & Signer'}
                            </button>
                          )}
                          <div className={styles.stepper}>
                            <div className={styles.stepActive} />
                            <div className={(req.status !== 'EN_ATTENTE_COMMISSION') ? styles.stepActive : styles.step} />
                            <div className={(req.status === 'AUTORISEE' || req.status === 'APPROUVEE' || req.status === 'PAYEE') ? styles.stepActive : styles.step} />
                            <div className={(req.status === 'APPROUVEE' || req.status === 'PAYEE') ? styles.stepActive : styles.step} />
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
                        </div>
                      </td>
                    </tr>
                  ))}
                  {requisitions.length === 0 && (
                    <tr>
                      <td colSpan={7} className={styles.panelState}>
                        Aucune réquisition pour ce service.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          {!loading && requisitions.length > 20 && (
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
                Page {reqPage} / {Math.max(1, Math.ceil(requisitions.length / 20))}
              </span>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setReqPage((p) => Math.min(Math.ceil(requisitions.length / 20), p + 1))}
                disabled={reqPage >= Math.ceil(requisitions.length / 20)}
              >
                Suivant →
              </button>
            </div>
          )}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>Mes postes budgétaires autorisés</div>
          {loading ? (
            <div className={styles.panelState}>Chargement…</div>
          ) : (
            <div className={styles.rubriquesList}>
              {rubriques
                .slice((postePage - 1) * 20, postePage * 20)
                .map((rub) => (
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
          {!loading && rubriques.length > 20 && (
            <div className={styles.pagination}>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setPostePage((p) => Math.max(1, p - 1))}
                disabled={postePage <= 1}
              >
                ← Précédent
              </button>
              <span className={styles.pageInfo}>
                Page {postePage} / {Math.max(1, Math.ceil(rubriques.length / 20))}
              </span>
              <button
                type="button"
                className={styles.pageBtn}
                onClick={() => setPostePage((p) => Math.min(Math.ceil(rubriques.length / 20), p + 1))}
                disabled={postePage >= Math.ceil(rubriques.length / 20)}
              >
                Suivant →
              </button>
            </div>
          )}
        </div>
      </section>

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
