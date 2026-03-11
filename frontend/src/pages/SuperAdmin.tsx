import { useEffect, useMemo, useState } from 'react'
import {
  createOrganisation,
  listOrganisations,
  updateOrganisation,
  getPlatformSummary,
  getTenantMetrics,
  refreshMetrics,
  listOrgUsers,
  impersonateUser,
  getMonitoringEvents,
  runMonthlyReport,
  getMonthlyReportStatus,
  type SuperAdminOrganisation,
  type PlatformSummary,
  type TenantMetric,
  type ExpiringOrg,
  type OrgUserLite,
  type SystemEventItem,
} from '../api/superAdmin'
import { useNotification } from '../contexts/NotificationContext'
import { useAuth } from '../contexts/AuthContext'
import { getAccessToken, setAccessToken } from '../lib/apiClient'
import PlatformHealth from '../components/admin/PlatformHealth'
import TenantActivityMap from '../components/admin/TenantActivityMap'
import styles from './SuperAdmin.module.css'

const DEFAULT_FORM = {
  nom: '',
  slug: '',
  plan_type: 'FREE',
  status_abonnement: 'TRIAL',
  trial_days: 30,
  limite_utilisateurs: 2,
  admin_email: '',
  admin_password: '',
}

export default function SuperAdmin() {
  const { showError, showSuccess, showWarning } = useNotification()
  const { reloadProfile } = useAuth()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [orgs, setOrgs] = useState<SuperAdminOrganisation[]>([])
  const [summary, setSummary] = useState<PlatformSummary | null>(null)
  const [metrics, setMetrics] = useState<TenantMetric[]>([])
  const [expiring, setExpiring] = useState<ExpiringOrg[]>([])
  const [events, setEvents] = useState<SystemEventItem[]>([])
  const [anomalies, setAnomalies] = useState<any[]>([])
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [showImpersonate, setShowImpersonate] = useState(false)
  const [impersonateUsers, setImpersonateUsers] = useState<OrgUserLite[]>([])
  const [impersonateOrg, setImpersonateOrg] = useState<SuperAdminOrganisation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ ...DEFAULT_FORM })
  const now = new Date()
  const [reportMonth, setReportMonth] = useState(now.getMonth() + 1)
  const [reportYear, setReportYear] = useState(now.getFullYear())
  const [monthlyStatus, setMonthlyStatus] = useState<any | null>(null)

  const totalOrgs = useMemo(() => orgs.length, [orgs])

  const load = async () => {
    try {
      setLoading(true)
      const data = await listOrganisations()
      setOrgs(data)
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impossible de charger les organisations.')
    } finally {
      setLoading(false)
    }
  }

  const loadMonitoring = async () => {
    try {
      setLoadingMetrics(true)
      const [summaryRes, tenantsRes, eventsRes] = await Promise.all([
        getPlatformSummary(),
        getTenantMetrics(),
        getMonitoringEvents(20),
      ])
      setSummary(summaryRes)
      setMetrics(tenantsRes.metrics || [])
      setExpiring(tenantsRes.expiring || [])
      setAnomalies(tenantsRes.anomalies || [])
      setEvents(eventsRes.events || [])
    } catch (err: any) {
      showWarning('Monitoring incomplet', err?.message || 'Impossible de charger les métriques.')
    } finally {
      setLoadingMetrics(false)
    }
  }

  const loadMonthlyStatus = async () => {
    try {
      const res = await getMonthlyReportStatus()
      setMonthlyStatus(res)
    } catch {
      setMonthlyStatus(null)
    }
  }

  useEffect(() => {
    load()
    loadMonitoring()
    loadMonthlyStatus()
  }, [])

  const handleCreate = async () => {
    setError(null)
    if (!form.nom || !form.slug || !form.admin_email || !form.admin_password) {
      setError('Merci de remplir tous les champs requis.')
      return
    }
    try {
      setSaving(true)
      const created = await createOrganisation({
        ...form,
        trial_days: Number(form.trial_days || 0),
        limite_utilisateurs: Number(form.limite_utilisateurs || 0) || 2,
      })
      setOrgs((prev) => [created, ...prev])
      setShowModal(false)
      setForm({ ...DEFAULT_FORM })
      showSuccess('Organisation créée', `Le tenant ${created.nom} est prêt.`)
    } catch (err: any) {
      setError(err?.message || 'Création impossible.')
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (org: SuperAdminOrganisation) => {
    const nextActive = !org.is_active
    try {
      const updated = await updateOrganisation(org.id, {
        is_active: nextActive,
        status_abonnement: nextActive ? 'ACTIVE' : 'SUSPENDED',
      })
      setOrgs((prev) => prev.map((item) => (item.id === org.id ? updated : item)))
      showSuccess(
        nextActive ? 'Organisation réactivée' : 'Organisation suspendue',
        `${updated.nom} est maintenant ${nextActive ? 'active' : 'suspendue'}.`,
      )
    } catch (err: any) {
      showError('Erreur', err?.message || 'Mise à jour impossible.')
    }
  }

  const openImpersonate = async (org: SuperAdminOrganisation) => {
    try {
      const res = await listOrgUsers(org.id)
      setImpersonateUsers(res.users || [])
      setImpersonateOrg(org)
      setShowImpersonate(true)
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impossible de charger les utilisateurs.')
    }
  }

  const runImpersonate = async (user: OrgUserLite) => {
    try {
      const current = getAccessToken()
      if (current) {
        window.sessionStorage.setItem('super_admin_token', current)
      }
      const res = await impersonateUser(user.id)
      setAccessToken(res.access_token)
      await reloadProfile()
      window.location.href = '/dashboard'
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impersonation impossible.')
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <h1>Console Super Admin</h1>
          <p>{totalOrgs} organisations en production · supervision des plans et accès.</p>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.secondaryButton}
            onClick={async () => {
              try {
                const res = await refreshMetrics()
                await loadMonitoring()
                const msg = res?.alerts_sent
                  ? `Métriques à jour. Alertes envoyées: ${res.alerts_sent}.`
                  : 'Les métriques SaaS ont été mises à jour.'
                showSuccess('Monitoring rafraîchi', msg)
              } catch (err: any) {
                showError('Erreur', err?.message || 'Impossible de rafraîchir le monitoring.')
              }
            }}
            disabled={loadingMetrics}
          >
            {loadingMetrics ? 'Mise à jour...' : 'Rafraîchir monitoring'}
          </button>
          <button className={styles.primaryButton} onClick={() => setShowModal(true)}>
            + Nouvelle organisation
          </button>
        </div>
      </div>

      <PlatformHealth stats={summary} />

      <div className={styles.monitoringGrid}>
        <TenantActivityMap tenants={metrics.slice(0, 10)} />
        <div className={styles.card}>
          <div className={styles.cardTitle}>Abonnements à échéance (≤ 5 jours)</div>
          {expiring.length === 0 ? (
            <div className={styles.emptyState}>Aucune organisation en fin d’essai imminente.</div>
          ) : (
            <div className={styles.expiringList}>
              {expiring.map((org) => (
                <div key={org.id} className={styles.expiringItem}>
                  <div>
                    <strong>{org.nom}</strong> <span className={styles.muted}>({org.slug})</span>
                  </div>
                  <div className={styles.expiringMeta}>
                    {org.plan_type} · {org.status_abonnement}
                  </div>
                  <div className={styles.expiringMeta}>
                    Expire le {org.date_expiration_abonnement ? new Date(org.date_expiration_abonnement).toLocaleDateString() : '—'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Rapport mensuel consolidé</div>
        <div className={styles.reportRow}>
          <label className={styles.field}>
            Mois
            <input
              type="number"
              min={1}
              max={12}
              value={reportMonth}
              onChange={(e) => setReportMonth(Number(e.target.value))}
            />
          </label>
          <label className={styles.field}>
            Année
            <input
              type="number"
              min={2020}
              value={reportYear}
              onChange={(e) => setReportYear(Number(e.target.value))}
            />
          </label>
          <button
            className={styles.primaryButton}
            onClick={async () => {
              try {
                const res = await runMonthlyReport(reportMonth, reportYear)
                showSuccess('Rapport généré', res.path || 'Rapport mensuel prêt.')
              } catch (err: any) {
                showError('Erreur', err?.message || 'Génération impossible.')
              }
            }}
          >
            Générer PDF
          </button>
        </div>
        {monthlyStatus?.enabled !== undefined && (
          <div className={styles.expiringMeta}>
            Scheduler: {monthlyStatus.enabled ? 'activé' : 'désactivé'} · prochaine exécution: {monthlyStatus.next_run || '—'}
          </div>
        )}
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Alertes & anomalies</div>
        {anomalies.length === 0 ? (
          <div className={styles.emptyState}>Aucune anomalie détectée.</div>
        ) : (
          <div className={styles.expiringList}>
            {anomalies.map((a, idx) => (
              <div key={`${a.type}-${a.organisation_id}-${idx}`} className={styles.expiringItem}>
                <div><strong>{a.type}</strong> · org #{a.organisation_id}</div>
                <div className={styles.expiringMeta}>Occurrences : {a.count}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Derniers événements système</div>
        {events.length === 0 ? (
          <div className={styles.emptyState}>Aucun événement signalé.</div>
        ) : (
          <div className={styles.eventsList}>
            {events.map((ev) => (
              <div key={ev.id} className={styles.eventRow}>
                <div className={styles.eventLevel}>{ev.level}</div>
                <div>
                  <div className={styles.eventMessage}>{ev.message || ev.code}</div>
                  <div className={styles.expiringMeta}>{ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={styles.card}>
        {orgs.length === 0 ? (
          <div className={styles.emptyState}>Aucune organisation créée pour le moment.</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Organisation</th>
                <th>Plan</th>
                <th>Utilisateurs</th>
                <th>Statut</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id}>
                  <td>
                    <strong>{org.nom}</strong> <span style={{ color: '#94a3b8' }}>({org.slug})</span>
                  </td>
                  <td>
                    <span className={`${styles.badge} ${styles.badgePlan}`}>{org.plan_type}</span>
                  </td>
                  <td>{org.user_count}</td>
                  <td>
                    <span
                      className={`${styles.badge} ${org.is_active ? styles.badgeActive : styles.badgeSuspended}`}
                    >
                      {org.is_active ? 'Actif' : 'Suspendu'} · {org.status_abonnement}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      className={`${styles.actionBtn} ${org.is_active ? styles.actionBtnDanger : styles.actionBtnSuccess}`}
                      onClick={() => toggleActive(org)}
                    >
                      {org.is_active ? 'Suspendre' : 'Réactiver'}
                    </button>
                    <button
                      className={styles.actionBtn}
                      onClick={() => openImpersonate(org)}
                      style={{ marginLeft: '10px' }}
                    >
                      Se connecter
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showImpersonate && impersonateOrg && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <h2>Se connecter en tant que...</h2>
            <p>Organisation : {impersonateOrg.nom}</p>
            <div className={styles.expiringList}>
              {impersonateUsers.length === 0 ? (
                <div className={styles.emptyState}>Aucun utilisateur trouvé.</div>
              ) : (
                impersonateUsers.map((u) => (
                  <div key={u.id} className={styles.expiringItem}>
                    <div><strong>{u.prenom || ''} {u.nom || ''}</strong> — {u.email}</div>
                    <div className={styles.expiringMeta}>{u.role || 'user'} · {u.active ? 'actif' : 'inactif'}</div>
                    <button className={styles.primaryButton} onClick={() => runImpersonate(u)}>
                      Impersonner
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowImpersonate(false)}>
                Fermer
              </button>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <h2>Provisionner un nouveau tenant</h2>
            <p>Création de l’organisation + admin initial + caisse centrale.</p>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                Nom organisation*
                <input
                  value={form.nom}
                  onChange={(e) => setForm((prev) => ({ ...prev, nom: e.target.value }))}
                  placeholder="CPHK"
                />
              </label>
              <label className={styles.field}>
                Slug*
                <input
                  value={form.slug}
                  onChange={(e) => setForm((prev) => ({ ...prev, slug: e.target.value }))}
                  placeholder="cphk"
                />
              </label>
              <label className={styles.field}>
                Plan
                <select
                  value={form.plan_type}
                  onChange={(e) => setForm((prev) => ({ ...prev, plan_type: e.target.value }))}
                >
                  <option value="FREE">FREE</option>
                  <option value="BASIC">BASIC</option>
                  <option value="PREMIUM">PREMIUM</option>
                  <option value="ENTERPRISE">ENTERPRISE</option>
                </select>
              </label>
              <label className={styles.field}>
                Statut abonnement
                <select
                  value={form.status_abonnement}
                  onChange={(e) => setForm((prev) => ({ ...prev, status_abonnement: e.target.value }))}
                >
                  <option value="TRIAL">TRIAL</option>
                  <option value="ACTIVE">ACTIVE</option>
                  <option value="PAST_DUE">PAST_DUE</option>
                  <option value="CANCELED">CANCELED</option>
                </select>
              </label>
              <label className={styles.field}>
                Jours d'essai
                <input
                  type="number"
                  min={0}
                  value={form.trial_days}
                  onChange={(e) => setForm((prev) => ({ ...prev, trial_days: Number(e.target.value) }))}
                />
              </label>
              <label className={styles.field}>
                Limite utilisateurs
                <input
                  type="number"
                  min={1}
                  value={form.limite_utilisateurs}
                  onChange={(e) => setForm((prev) => ({ ...prev, limite_utilisateurs: Number(e.target.value) }))}
                />
              </label>
              <label className={styles.field}>
                Email admin*
                <input
                  type="email"
                  value={form.admin_email}
                  onChange={(e) => setForm((prev) => ({ ...prev, admin_email: e.target.value }))}
                  placeholder="admin@cphk.cd"
                />
              </label>
              <label className={styles.field}>
                Mot de passe admin*
                <input
                  type="password"
                  value={form.admin_password}
                  onChange={(e) => setForm((prev) => ({ ...prev, admin_password: e.target.value }))}
                />
              </label>
            </div>
            {error && <div className={styles.error}>{error}</div>}
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowModal(false)} disabled={saving}>
                Annuler
              </button>
              <button className={styles.primaryButton} onClick={handleCreate} disabled={saving}>
                {saving ? 'Création...' : 'Créer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
