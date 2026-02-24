import { useCallback, useEffect, useMemo, useState } from 'react'
import { PlusCircle, Wallet, CheckCircle, FileText, XCircle, ShieldCheck } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { getService, getServiceMembers } from '../api/services'
import BudgetGauge from '../components/ServicePortal/BudgetGauge'
import styles from './ServicePortal.module.css'
import type { CommissionMember } from '../types'
import { getStatusMeta } from '../utils/statusMapper'

type ServiceSummary = {
  annee: number | null
  total: number
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
    } catch {
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

  const total = summary?.total ?? 0
  const consomme = summary?.consomme ?? 0
  const enAttente = summary?.en_attente ?? 0
  const disponible = summary?.disponible ?? 0
  const progress = total > 0 ? Math.min(100, Math.round((consomme / total) * 100)) : 0
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
        <button
          className={styles.primaryAction}
          onClick={() => navigate(`/requisitions?service_id=${activeServiceId}&new=1`)}
        >
          <PlusCircle size={20} />
          Nouvelle réquisition
        </button>
      </div>

      {rejectedCount > 0 && (
        <div className={styles.alert}>
          <XCircle size={18} />
          <span>Vous avez {rejectedCount} réquisition(s) rejetée(s). Consultez les motifs.</span>
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
          <BudgetGauge consomme={consomme} engage={enAttente} total={total} />
        </div>
        <div className={styles.metricCard}>
          <div className={styles.metricHeader}>
            <span>Budget alloué</span>
            <Wallet size={18} />
          </div>
          <div className={styles.metricValue}>{total.toLocaleString()} USD</div>
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
            <span>Mes dernières réquisitions</span>
            <span className={styles.panelHeaderMeta}>Service uniquement</span>
          </div>
          {loading ? (
            <div className={styles.panelState}>Chargement…</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>N°</th>
                  <th>Objet</th>
                  <th>Montant</th>
                  <th>Statut</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {requisitions.slice(0, 8).map((req) => (
                  <tr key={req.id}>
                    <td>{req.numero_requisition}</td>
                    <td title={req.objet}>{req.objet}</td>
                    <td>{Number(req.montant_total || 0).toLocaleString()} USD</td>
                    <td>
                      <div className={styles.reqActionArea}>
                        {(() => {
                          const meta = getStatusMeta(req.status)
                          return (
                            <span className={styles.statusBadge} title={meta.description || meta.label}>
                              {meta.label}
                            </span>
                          )
                        })()}
                        {canSign && req.status === 'EN_ATTENTE_COMMISSION' && (
                          <button
                            type="button"
                            className={styles.btnSign}
                            onClick={() => handleSign(req.id)}
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
                  </tr>
                ))}
                {requisitions.length === 0 && (
                  <tr>
                    <td colSpan={5} className={styles.panelState}>
                      Aucune réquisition pour ce service.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeader}>Mes rubriques autorisées</div>
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
                <div className={styles.panelState}>Aucune rubrique autorisée.</div>
              )}
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

    </div>
  )
}
