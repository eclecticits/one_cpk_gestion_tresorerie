import { useEffect, useMemo, useState } from 'react'
import {
  createOrganisation,
  reserveOrganisation,
  listOrganisations,
  updateOrganisation,
  getPlatformSummary,
  getTenantMetrics,
  getTreasuryStats,
  refreshMetrics,
  listOrgUsers,
  impersonateUser,
  getMonitoringEvents,
  runMonthlyReport,
  getMonthlyReportStatus,
  simulatePayment,
  grantTrial,
  listBankProofs,
  approveBankProof,
  rejectBankProof,
  getGoogleOAuthSettings,
  updateGoogleOAuthSettings,
  type SuperAdminOrganisation,
  type PlatformSummary,
  type TenantMetric,
  type TreasuryStat,
  type ExpiringOrg,
  type OrgUserLite,
  type SystemEventItem,
  type GoogleOAuthSettingsOut,
  type GoogleOAuthSettingsUpdate,
} from '../api/superAdmin'
import { listPlans, type Plan } from '../api/onboarding'
import ProvinceSettingsEditor from './SuperAdmin/ProvinceSettingsEditor'
import BillingConfigEditor from './SuperAdmin/BillingConfigEditor'
import TenantBankProofs from './SuperAdmin/TenantBankProofs'
import TenantPaymentHistory from './SuperAdmin/TenantPaymentHistory'
import GlobalBillingConfigEditor from './SuperAdmin/GlobalBillingConfigEditor'
import { AIProvidersPanel } from './AIProvidersPage'
import { useNotification } from '../contexts/NotificationContext'
import { useConfirmWithInput } from '../contexts/ConfirmContext'
import { useAuth } from '../contexts/AuthContext'
import { getAccessToken, setAccessToken, setImpersonationReturnToken } from '../lib/apiClient'
import PlatformHealth from '../components/admin/PlatformHealth'
import TenantActivityMap from '../components/admin/TenantActivityMap'
import styles from './SuperAdmin.module.css'

function UriToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      title={enabled ? 'Desactiver' : 'Activer'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
        borderRadius: 12, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 700,
        background: enabled ? '#dcfce7' : '#f3f4f6',
        color: enabled ? '#15803d' : '#9ca3af',
        transition: 'all .15s',
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: enabled ? '#16a34a' : '#d1d5db',
        display: 'inline-block', transition: 'background .15s',
      }} />
      {enabled ? 'Actif' : 'Inactif'}
    </button>
  )
}

function GoogleOAuthPanel() {
  const { showError, showSuccess } = useNotification()
  const [cfg, setCfg] = useState<GoogleOAuthSettingsOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [redirectUriProd, setRedirectUriProd] = useState('')
  const [redirectUriProdEnabled, setRedirectUriProdEnabled] = useState(true)
  const [redirectUriLocal, setRedirectUriLocal] = useState('')
  const [redirectUriLocalEnabled, setRedirectUriLocalEnabled] = useState(false)

  useEffect(() => {
    getGoogleOAuthSettings()
      .then((data) => {
        setCfg(data)
        setClientId(data.google_client_id ?? '')
        setRedirectUriProd(data.google_oauth_redirect_uri ?? '')
        setRedirectUriProdEnabled(data.google_oauth_redirect_uri_enabled)
        setRedirectUriLocal(data.google_oauth_redirect_uri_local ?? '')
        setRedirectUriLocalEnabled(data.google_oauth_redirect_uri_local_enabled)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload: GoogleOAuthSettingsUpdate = {
        google_oauth_redirect_uri: redirectUriProd.trim() || null,
        google_oauth_redirect_uri_enabled: redirectUriProdEnabled,
        google_oauth_redirect_uri_local: redirectUriLocal.trim() || null,
        google_oauth_redirect_uri_local_enabled: redirectUriLocalEnabled,
      }
      if (clientId.trim()) payload.google_client_id = clientId.trim()
      if (clientSecret.trim()) payload.google_client_secret = clientSecret.trim()
      const updated = await updateGoogleOAuthSettings(payload)
      setCfg(updated)
      setRedirectUriProdEnabled(updated.google_oauth_redirect_uri_enabled)
      setRedirectUriLocalEnabled(updated.google_oauth_redirect_uri_local_enabled)
      setClientSecret('')
      showSuccess('Google OAuth', 'Configuration sauvegardee.')
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impossible de sauvegarder.')
    } finally {
      setSaving(false)
    }
  }

  const sourceLabel = cfg?.source === 'database' ? 'Base de donnees' : cfg?.source === 'environment' ? '.env (fallback)' : 'Non configure'
  const sourceBg = cfg?.source === 'database' ? '#dcfce7' : cfg?.source === 'environment' ? '#fef9c3' : '#fee2e2'
  const sourceColor = cfg?.source === 'database' ? '#166534' : cfg?.source === 'environment' ? '#854d0e' : '#991b1b'

  const fieldStyle = (disabled: boolean): React.CSSProperties => ({
    width: '100%', padding: '8px 10px',
    border: `1px solid ${disabled ? '#e5e7eb' : '#d1d5db'}`,
    borderRadius: 6, fontSize: 13, boxSizing: 'border-box',
    background: disabled ? '#f9fafb' : '#fff',
    color: disabled ? '#9ca3af' : '#111827',
    transition: 'all .15s',
  })
  const labelStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 }

  // URI active resolue selon la meme logique que le backend
  const activeUri = redirectUriProdEnabled && redirectUriProd
    ? 'production'
    : redirectUriLocalEnabled && redirectUriLocal
      ? 'local'
      : 'none'

  if (loading) return <div style={{ color: '#6b7280', fontSize: 13, padding: 8 }}>Chargement...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, background: sourceBg, color: sourceColor }}>
          {sourceLabel}
        </span>
        {cfg?.google_client_secret_configured && (
          <span style={{ fontSize: 12, color: '#16a34a' }}>&#10003; Secret configure</span>
        )}
        <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 'auto' }}>
          URI active :{' '}
          <strong style={{ color: activeUri === 'none' ? '#dc2626' : '#4338ca' }}>
            {activeUri === 'production' ? 'Production' : activeUri === 'local' ? 'Local (dev)' : 'Aucune'}
          </strong>
        </span>
      </div>

      <p style={{ fontSize: 13, color: '#6b7280', margin: '0 0 16px' }}>
        Les credentials sont chiffres en base et prennent priorite sur le fichier <code>.env</code>.
        Activez ou desactivez chaque URI independamment. La Production est prioritaire sur le Local si les deux sont actifs.
      </p>

      <div style={{ display: 'grid', gap: 14 }}>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>Client ID</label>
          <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)}
            placeholder="xxxx.apps.googleusercontent.com" style={fieldStyle(false)} />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
            Client Secret{' '}
            {cfg?.google_client_secret_configured && <span style={{ color: '#16a34a', fontWeight: 400 }}>(configure — laisser vide pour conserver)</span>}
          </label>
          <input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)}
            placeholder={cfg?.google_client_secret_configured ? '••••••••••••••••' : 'GOCSPX-...'}
            style={fieldStyle(false)} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ border: `1.5px solid ${redirectUriProdEnabled ? '#a5b4fc' : '#e5e7eb'}`, borderRadius: 8, padding: '10px 12px', background: redirectUriProdEnabled ? '#f5f3ff' : '#fafafa', transition: 'all .15s' }}>
            <label style={labelStyle}>
              <span>Redirect URI — Production</span>
              <UriToggle enabled={redirectUriProdEnabled} onChange={setRedirectUriProdEnabled} />
            </label>
            <input type="text" value={redirectUriProd} onChange={(e) => setRedirectUriProd(e.target.value)}
              disabled={!redirectUriProdEnabled}
              placeholder="https://api.onec-rdc.org/api/v1/secretariat/google/callback"
              style={fieldStyle(!redirectUriProdEnabled)} />
          </div>
          <div style={{ border: `1.5px solid ${redirectUriLocalEnabled ? '#a5b4fc' : '#e5e7eb'}`, borderRadius: 8, padding: '10px 12px', background: redirectUriLocalEnabled ? '#f5f3ff' : '#fafafa', transition: 'all .15s' }}>
            <label style={labelStyle}>
              <span>Redirect URI — Local (dev)</span>
              <UriToggle enabled={redirectUriLocalEnabled} onChange={setRedirectUriLocalEnabled} />
            </label>
            <input type="text" value={redirectUriLocal} onChange={(e) => setRedirectUriLocal(e.target.value)}
              disabled={!redirectUriLocalEnabled}
              placeholder="http://cpk.localhost:8000/api/v1/secretariat/google/callback"
              style={fieldStyle(!redirectUriLocalEnabled)} />
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{ padding: '8px 18px', background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 6, cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600, opacity: saving ? 0.7 : 1 }}
        >
          {saving ? 'Sauvegarde...' : 'Sauvegarder'}
        </button>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>
          Source : <strong>{sourceLabel}</strong>
        </span>
      </div>
    </div>
  )
}

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
  const confirmWithInput = useConfirmWithInput()
  const { reloadProfile } = useAuth()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [orgs, setOrgs] = useState<SuperAdminOrganisation[]>([])
  const [summary, setSummary] = useState<PlatformSummary | null>(null)
  const [metrics, setMetrics] = useState<TenantMetric[]>([])
  const [expiring, setExpiring] = useState<ExpiringOrg[]>([])
  const [events, setEvents] = useState<SystemEventItem[]>([])
  const [anomalies, setAnomalies] = useState<any[]>([])
  const [treasuryStats, setTreasuryStats] = useState<TreasuryStat[]>([])
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [loadingProofs, setLoadingProofs] = useState(false)
  const [bankProofs, setBankProofs] = useState<any[]>([])
  const [showModal, setShowModal] = useState(false)
  const [showImpersonate, setShowImpersonate] = useState(false)
  const [impersonateUsers, setImpersonateUsers] = useState<OrgUserLite[]>([])
  const [impersonateOrg, setImpersonateOrg] = useState<SuperAdminOrganisation | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [settingsOrg, setSettingsOrg] = useState<SuperAdminOrganisation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ ...DEFAULT_FORM })
  const [plans, setPlans] = useState<Plan[]>([])
  const [simulatingOrgId, setSimulatingOrgId] = useState<number | null>(null)
  const [showGrantTrial, setShowGrantTrial] = useState(false)
  const [grantTrialOrg, setGrantTrialOrg] = useState<SuperAdminOrganisation | null>(null)
  const [grantTrialForm, setGrantTrialForm] = useState({ plan_type: 'FREE', duration_days: 30 })
  const [grantingTrialOrgId, setGrantingTrialOrgId] = useState<number | null>(null)
  const [simulationResult, setSimulationResult] = useState<{
    orgName: string
    adminEmail: string
    reference: string
    tempPassword?: string
  } | null>(null)
  const [reserveForm, setReserveForm] = useState({
    nom: '',
    slug: '',
    admin_email: '',
    admin_phone: '',
    plan_id: 0,
    max_users: 5,
    storage_quota_mb: 1024,
    is_ai_enabled: false,
    is_mobile_money_enabled: true,
    is_audit_logs_enabled: true,
    fiscal_year_start: 1,
    currency_code: 'USD',
  })
  const now = new Date()
  const [reportMonth, setReportMonth] = useState(now.getMonth() + 1)
  const [reportYear, setReportYear] = useState(now.getFullYear())
  const [monthlyStatus, setMonthlyStatus] = useState<any | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'organisations' | 'facturation' | 'integrations'>('overview')

  const totalOrgs = useMemo(() => orgs.length, [orgs])

  const load = async () => {
    try {
      setLoading(true)
      const data = await listOrganisations()
      setOrgs(data)
    } catch (err: any) {
      console.error('Erreur chargement organisations:', err)
    } finally {
      setLoading(false)
    }
  }

  const loadPlans = async () => {
    try {
      const res = await listPlans()
      setPlans(res || [])
      if (res?.length && !reserveForm.plan_id) {
        setReserveForm((prev) => ({ ...prev, plan_id: res[0].id }))
      }
    } catch {
      setPlans([])
    }
  }
  const loadMonitoring = async () => {
    try {
      setLoadingMetrics(true)
      const [summaryRes, tenantsRes, eventsRes, treasuryRes] = await Promise.all([
        getPlatformSummary(),
        getTenantMetrics(),
        getMonitoringEvents(20),
        getTreasuryStats(),
      ])
      setSummary(summaryRes)
      setMetrics(tenantsRes.metrics || [])
      setExpiring(tenantsRes.expiring || [])
      setAnomalies(tenantsRes.anomalies || [])
      setEvents(eventsRes.events || [])
      setTreasuryStats(treasuryRes.items || [])
    } catch (err: any) {
      console.error('Monitoring incomplet:', err)
    } finally {
      setLoadingMetrics(false)
    }
  }

  const loadBankProofs = async () => {
    try {
      setLoadingProofs(true)
      const res = await listBankProofs(60)
      setBankProofs(res.items || [])
    } catch (err: any) {
      console.error('Chargement preuves banque:', err)
    } finally {
      setLoadingProofs(false)
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
    loadPlans()
    loadBankProofs()
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

  const handleReserve = async () => {
    setError(null)
    if (!reserveForm.nom || !reserveForm.slug || !reserveForm.admin_email || !reserveForm.plan_id) {
      setError('Merci de remplir tous les champs requis.')
      return
    }
    try {
      setSaving(true)
      const created = await reserveOrganisation({
        nom: reserveForm.nom,
        slug: reserveForm.slug,
        admin_email: reserveForm.admin_email,
        admin_phone: reserveForm.admin_phone || null,
        plan_id: reserveForm.plan_id,
        max_users: reserveForm.max_users,
        storage_quota_mb: reserveForm.storage_quota_mb,
        is_ai_enabled: reserveForm.is_ai_enabled,
        is_mobile_money_enabled: reserveForm.is_mobile_money_enabled,
        is_audit_logs_enabled: reserveForm.is_audit_logs_enabled,
        fiscal_year_start: reserveForm.fiscal_year_start,
        currency_code: reserveForm.currency_code,
      })
      setOrgs((prev) => [created, ...prev])
      setReserveForm({
        nom: '',
        slug: '',
        admin_email: '',
        admin_phone: '',
        plan_id: reserveForm.plan_id,
        max_users: reserveForm.max_users,
        storage_quota_mb: reserveForm.storage_quota_mb,
        is_ai_enabled: reserveForm.is_ai_enabled,
        is_mobile_money_enabled: reserveForm.is_mobile_money_enabled,
        is_audit_logs_enabled: reserveForm.is_audit_logs_enabled,
        fiscal_year_start: reserveForm.fiscal_year_start,
        currency_code: reserveForm.currency_code,
      })
      showSuccess('Province réservée', `${created.nom} est prête pour activation.`)
    } catch (err: any) {
      setError(err?.message || 'Réservation impossible.')
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

  const openSettings = async (org: SuperAdminOrganisation) => {
    setSettingsOrg(org)
    setShowSettings(true)
  }

  const runImpersonate = async (user: OrgUserLite) => {
    try {
      const current = getAccessToken()
      if (current) {
        setImpersonationReturnToken(current)
      }
      const res = await impersonateUser(user.id)
      setAccessToken(res.access_token)
      await reloadProfile()
      window.location.href = '/dashboard'
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impersonation impossible.')
    }
  }

  const handleSimulatePayment = async (org: SuperAdminOrganisation) => {
    const adminPrompt = await confirmWithInput({
      title: 'Simulation de paiement',
      description: 'Email admin pour la simulation de paiement.',
      confirmText: 'Continuer',
      cancelText: 'Annuler',
      inputLabel: 'Email admin',
      inputPlaceholder: `admin.${org.slug}@onec.local`,
      inputInitialValue: `admin.${org.slug}@onec.local`,
      inputRequired: true,
      inputMultiline: false,
    })
    if (!adminPrompt.confirmed) return
    const adminEmail = adminPrompt.value.trim()
    if (!adminEmail) {
      showWarning('Email requis', "Veuillez saisir l\'email admin.")
      return
    }

    const monthsPrompt = await confirmWithInput({
      title: 'Simulation de paiement',
      description: 'Nombre de mois payés (1, 3, 6, 12).',
      confirmText: 'Lancer',
      cancelText: 'Annuler',
      inputLabel: 'Mois',
      inputPlaceholder: '1',
      inputInitialValue: '1',
      inputRequired: true,
      inputMultiline: false,
    })
    if (!monthsPrompt.confirmed) return
    const monthsValue = Number(monthsPrompt.value || 1)
    if (!Number.isFinite(monthsValue) || monthsValue <= 0) {
      showWarning('Valeur invalide', 'Veuillez saisir un nombre de mois valide.')
      return
    }
    const billingMonths = Math.max(1, Math.floor(monthsValue))
    try {
      setSimulatingOrgId(org.id)
      const res = await simulatePayment(org.id, { admin_email: adminEmail, billing_months: billingMonths })
      const passwordNotice = res.temp_password
        ? `Mot de passe temporaire: ${res.temp_password}.`
        : 'Mot de passe temporaire généré.'
      showSuccess(
        'Paiement simulé',
        `Activation OK pour ${org.nom}. Admin: ${res.admin_email}. Référence: ${res.reference}. ${passwordNotice}`,
      )
      setSimulationResult({
        orgName: org.nom,
        adminEmail: res.admin_email,
        reference: res.reference,
        tempPassword: res.temp_password,
      })
      await load()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Simulation impossible.')
    } finally {
      setSimulatingOrgId(null)
    }
  }

  const handleGrantTrial = async () => {
    if (!grantTrialOrg) return
    if (grantTrialForm.duration_days < 1 || grantTrialForm.duration_days > 365) {
      showError('Valeur invalide', 'La durée doit être entre 1 et 365 jours.')
      return
    }
    try {
      setGrantingTrialOrgId(grantTrialOrg.id)
      const res = await grantTrial(grantTrialOrg.id, grantTrialForm)
      showSuccess(
        'Essai accordé',
        `${grantTrialOrg.nom} — plan ${res.plan_type} pour ${res.duration_days} jours, expire le ${new Date(res.expires_at).toLocaleDateString()}.`,
      )
      setShowGrantTrial(false)
      await load()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Attribution impossible.')
    } finally {
      setGrantingTrialOrgId(null)
    }
  }

  const handleApproveProof = async (txId: string) => {
    const result = await confirmWithInput({
      title: 'Valider la preuve bancaire',
      description: 'Tapez VALIDER pour activer immédiatement l\'abonnement.',
      inputPlaceholder: 'VALIDER',
      confirmText: 'Valider',
      variant: 'danger',
    })
    if (!result.confirmed || result.value.toUpperCase() !== 'VALIDER') {
      return
    }
    try {
      await approveBankProof(txId)
      showSuccess('Paiement validé', 'La preuve bancaire a été approuvée.')
      await loadBankProofs()
      await load()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Validation impossible.')
    }
  }

  const handleRejectProof = async (txId: string) => {
    const result = await confirmWithInput({
      title: 'Rejeter la preuve bancaire',
      description: 'Tapez REJETER pour marquer ce paiement comme échoué.',
      inputPlaceholder: 'REJETER',
      confirmText: 'Rejeter',
      variant: 'danger',
    })
    if (!result.confirmed || result.value.toUpperCase() !== 'REJETER') {
      return
    }
    try {
      await rejectBankProof(txId)
      showWarning('Preuve rejetée', 'La transaction est marquée comme échouée.')
      await loadBankProofs()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Rejet impossible.')
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.page}>

      {/* ── En-tête sticky ── */}
      <header className={styles.pageHeader}>
        <div className={styles.pageHeaderLeft}>
          <div className={styles.pageIcon}>🛡️</div>
          <div>
            <p className={styles.pageTitle}>Console Super Admin</p>
            <p className={styles.pageSub}>{totalOrgs} organisations · plateforme ONEC-RDC</p>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.secondaryButton}
            onClick={async () => {
              try {
                const res = await refreshMetrics()
                await loadMonitoring()
                showSuccess('Monitoring', res?.alerts_sent ? `${res.alerts_sent} alerte(s) envoyée(s).` : 'Métriques mises à jour.')
              } catch (err: any) {
                showError('Erreur', err?.message || 'Impossible de rafraîchir.')
              }
            }}
            disabled={loadingMetrics}>
            {loadingMetrics ? '⟳ Mise à jour...' : '⟳ Rafraîchir'}
          </button>
          <button className={styles.btnPrimary} onClick={() => setShowModal(true)}>
            + Nouveau tenant
          </button>
        </div>
      </header>

      {/* ── Barre d\'onglets ── */}
      <nav className={styles.tabBar}>
        {([
          { key: 'overview',      label: 'Vue d\'ensemble', icon: '◈', count: null },
          { key: 'organisations', label: 'Organisations',   icon: '⊞', count: totalOrgs },
          { key: 'facturation',   label: 'Facturation',     icon: '⬡', count: null },
          { key: 'integrations',  label: 'Intégrations',    icon: '⬢', count: null },
        ] as const).map(({ key, label, icon, count }) => (
          <button key={key}
            className={`${styles.tabBtn} ${activeTab === key ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab(key)}>
            <span>{icon}</span> {label}
            {count !== null && <span className={styles.tabCount}>{count}</span>}
          </button>
        ))}
      </nav>

      <div className={styles.pageBody}>

      {/* ══════════════════════════════════════════
          Onglet : Vue d\'ensemble
      ══════════════════════════════════════════ */}
      {activeTab === 'overview' && (
        <>
          {/* KPI cards */}
          <div className={styles.kpiGrid}>
            <div className={styles.kpiCard}>
              <div className={`${styles.kpiIcon} ${styles.kpiIconBlue}`}>🏢</div>
              <div>
                <div className={styles.kpiValue}>{summary?.total_tenants ?? totalOrgs}</div>
                <div className={styles.kpiLabel}>Organisations</div>
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={`${styles.kpiIcon} ${styles.kpiIconGreen}`}>✅</div>
              <div>
                <div className={styles.kpiValue}>{summary?.active_tenants ?? orgs.filter(o => o.is_active).length}</div>
                <div className={styles.kpiLabel}>Actives</div>
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={`${styles.kpiIcon} ${styles.kpiIconPurple}`}>💰</div>
              <div>
                <div className={styles.kpiValue}>{summary ? `$${Number(summary.total_volume_usd).toLocaleString()}` : '—'}</div>
                <div className={styles.kpiLabel}>Volume total</div>
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={`${styles.kpiIcon} ${styles.kpiIconOrange}`}>🔄</div>
              <div>
                <div className={styles.kpiValue}>{summary?.total_transactions?.toLocaleString() ?? '—'}</div>
                <div className={styles.kpiLabel}>Transactions</div>
              </div>
            </div>
            <div className={styles.kpiCard}>
              <div className={`${styles.kpiIcon} ${styles.kpiIconRed}`}>⚠️</div>
              <div>
                <div className={styles.kpiValue} style={{ color: (summary?.api_errors ?? 0) > 0 ? 'var(--sa-danger)' : 'inherit' }}>
                  {summary?.api_errors ?? 0}
                </div>
                <div className={styles.kpiLabel}>Erreurs API</div>
              </div>
            </div>
          </div>

          <PlatformHealth stats={summary} />

          <div className={styles.monitoringGrid}>
            <TenantActivityMap tenants={metrics.slice(0, 10)} />
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={styles.cardTitle}>⏰ Abonnements expirant</span>
                <span className={styles.muted} style={{ fontSize: 11 }}>≤ 5 jours</span>
              </div>
              <div className={styles.cardBody}>
                {expiring.length === 0 ? (
                  <div className={styles.emptyState}>Aucun abonnement imminent.</div>
                ) : (
                  <div className={styles.listStack}>
                    {expiring.map((org) => (
                      <div key={org.id} className={styles.listItem}>
                        <div className={styles.listItemRow}>
                          <strong style={{ fontSize: 13 }}>{org.nom}</strong>
                          <span className={styles.badge + ' ' + (org.status_abonnement === 'ACTIVE' ? styles.badgeActive : styles.badgeTrial)}>{org.status_abonnement}</span>
                        </div>
                        <div className={styles.listMeta}>
                          {org.plan_type} · expire le {org.date_expiration_abonnement ? new Date(org.date_expiration_abonnement).toLocaleDateString('fr-FR') : '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
            <div className={styles.card}>
              <div className={styles.cardHeader}><span className={styles.cardTitle}>💵 Trésorerie par tenant</span></div>
              <div className={styles.cardBody}>
                {treasuryStats.length === 0 ? (
                  <div className={styles.emptyState}>Aucune donnée.</div>
                ) : (
                  <table className={styles.table}>
                    <thead><tr><th>Organisation</th><th style={{ textAlign: 'right' }}>Encaissé</th><th style={{ textAlign: 'right' }}>Tx</th></tr></thead>
                    <tbody>
                      {treasuryStats.map((row) => (
                        <tr key={row.organisation_id}>
                          <td><strong>{row.organisation_name}</strong><div style={{ fontSize: 11, color: 'var(--sa-muted)' }}>{row.organisation_slug}</div></td>
                          <td style={{ textAlign: 'right', fontWeight: 700 }}>{Number(row.total_encaisse || 0).toLocaleString()}</td>
                          <td style={{ textAlign: 'right', color: 'var(--sa-muted)' }}>{row.success_tx}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            <div className={styles.card}>
              <div className={styles.cardHeader}><span className={styles.cardTitle}>⚡ Anomalies détectées</span></div>
              <div className={styles.cardBody}>
                {anomalies.length === 0 ? (
                  <div className={styles.emptyState}>Aucune anomalie.</div>
                ) : (
                  <div className={styles.listStack}>
                    {anomalies.map((a, idx) => (
                      <div key={`${a.type}-${idx}`} className={styles.listItem}>
                        <div className={styles.listItemRow}>
                          <strong style={{ fontSize: 12 }}>{a.type}</strong>
                          <span className={`${styles.badge} ${styles.badgeSuspended}`}>{a.count}×</span>
                        </div>
                        <div className={styles.listMeta}>Organisation #{a.organisation_id}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className={styles.card}>
            <div className={styles.cardHeader}><span className={styles.cardTitle}>📋 Événements système</span></div>
            <div className={styles.cardBody}>
              {events.length === 0 ? (
                <div className={styles.emptyState}>Aucun événement signalé.</div>
              ) : (
                <div className={styles.eventsList}>
                  {events.map((ev) => (
                    <div key={ev.id} className={styles.eventRow} data-level={ev.level}>
                      <div className={styles.eventLevel}>{ev.level}</div>
                      <div>
                        <div className={styles.eventMessage}>{ev.message || ev.code}</div>
                        <div className={styles.eventTime}>{ev.created_at ? new Date(ev.created_at).toLocaleString('fr-FR') : ''}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ══════════════════════════════════════════
          Onglet : Organisations
      ══════════════════════════════════════════ */}
      {activeTab === 'organisations' && (
        <>
          {/* ── Liste des organisations ── */}
          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>
              🏢 Gestion des organisations
              <button className={styles.primaryButton} style={{ marginLeft: 'auto', fontSize: 12, padding: '6px 14px' }}
                onClick={() => setShowModal(true)}>
                + Nouveau tenant
              </button>
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
                      <th>Abonnement</th>
                      <th>Expiration</th>
                      <th>Accès</th>
                      <th style={{ textAlign: 'center' }}>Actif</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orgs.map((org) => (
                      <tr key={org.id}>
                        <td>
                          <div><strong>{org.nom}</strong></div>
                          <div style={{ color: '#94a3b8', fontSize: 11 }}>{org.slug}.onec-rdc.org</div>
                        </td>
                        <td>
                          <span className={`${styles.badge} ${styles.badgePlan}`}>{org.plan_type}</span>
                        </td>
                        <td style={{ textAlign: 'center' }}>{org.user_count}</td>
                        <td>
                          <span className={`${styles.badge} ${org.status_abonnement === 'ACTIVE' ? styles.badgeActive : styles.badgeSuspended}`}>
                            {org.status_abonnement}
                          </span>
                        </td>
                        <td style={{ fontSize: 12, color: '#64748b' }}>
                          {org.date_expiration_abonnement
                            ? new Date(org.date_expiration_abonnement).toLocaleDateString('fr-FR')
                            : '—'}
                        </td>
                        <td style={{ fontSize: 12, color: '#64748b' }}>
                          {org.created_at ? new Date(org.created_at).toLocaleDateString('fr-FR') : '—'}
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            onClick={() => toggleActive(org)}
                            title={org.is_active ? 'Cliquer pour suspendre' : 'Cliquer pour activer'}
                            style={{
                              width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer',
                              background: org.is_active ? '#16a34a' : '#d1d5db',
                              position: 'relative', transition: 'background 0.2s', flexShrink: 0,
                            }}
                          >
                            <span style={{
                              position: 'absolute', top: 2,
                              left: org.is_active ? 22 : 2,
                              width: 20, height: 20, borderRadius: '50%', background: '#fff',
                              transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,.3)',
                            }} />
                          </button>
                        </td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <button className={styles.actionBtn} onClick={() => openImpersonate(org)}
                            title="Se connecter en tant qu\'un utilisateur de ce tenant">
                            👤 Connexion
                          </button>
                          <button className={styles.actionBtn} onClick={() => openSettings(org)} style={{ marginLeft: 6 }}
                            title="Configurer les modules et paramètres">
                            ⚙️ Config
                          </button>
                          <button className={styles.actionBtn}
                            onClick={() => { setGrantTrialOrg(org); setGrantTrialForm({ plan_type: 'FREE', duration_days: 30 }); setShowGrantTrial(true) }}
                            style={{ marginLeft: 6 }} disabled={grantingTrialOrgId === org.id}
                            title="Attribuer ou prolonger un essai gratuit">
                            {grantingTrialOrgId === org.id ? '...' : '🎁 Essai'}
                          </button>
                          {org.status_abonnement !== 'ACTIVE' && (
                            <button className={styles.actionBtn} onClick={() => handleSimulatePayment(org)}
                              style={{ marginLeft: 6 }} disabled={simulatingOrgId === org.id}
                              title="Simuler un paiement pour activer l\'abonnement">
                              {simulatingOrgId === org.id ? '...' : '💳 Paiement'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* ── Réserver une nouvelle province ── */}
          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>📋 Pré‑configurer une province</div>
            <div className={styles.card}>
              <div className={styles.formGrid} style={{ marginBottom: '16px' }}>
                <label className={styles.field}>
                  Nom province*
                  <input value={reserveForm.nom}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, nom: e.target.value }))}
                    placeholder="Tshopo" />
                </label>
                <label className={styles.field}>
                  Sous‑domaine*
                  <input value={reserveForm.slug}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, slug: e.target.value }))}
                    placeholder="tshopo" />
                </label>
                <label className={styles.field}>
                  Email officiel*
                  <input value={reserveForm.admin_email}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, admin_email: e.target.value }))}
                    placeholder="admin@province.cd" />
                </label>
                <label className={styles.field}>
                  Téléphone
                  <input value={reserveForm.admin_phone}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, admin_phone: e.target.value }))}
                    placeholder="+243 ..." />
                </label>
                <label className={styles.field}>
                  Plan*
                  <select value={reserveForm.plan_id}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, plan_id: Number(e.target.value) }))}>
                    {plans.map((plan) => (
                      <option key={plan.id} value={plan.id}>
                        {plan.name} — {Number(plan.monthly_price_usd).toLocaleString()} USD/mois
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  Limite d\'utilisateurs
                  <input type="number" value={reserveForm.max_users} min={1}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, max_users: Number(e.target.value) }))} />
                </label>
                <label className={styles.field}>
                  Stockage (MB)
                  <input type="number" value={reserveForm.storage_quota_mb} min={128}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, storage_quota_mb: Number(e.target.value) }))} />
                </label>
                <label className={styles.field}>
                  Mois fiscal (1-12)
                  <input type="number" value={reserveForm.fiscal_year_start} min={1} max={12}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, fiscal_year_start: Number(e.target.value) }))} />
                </label>
                <label className={styles.field}>
                  Devise
                  <input value={reserveForm.currency_code}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, currency_code: e.target.value.toUpperCase() }))} />
                </label>
              </div>
              <div className={styles.formGrid}>
                <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={reserveForm.is_ai_enabled}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, is_ai_enabled: e.target.checked }))} />
                  Activer l\'analyse IA
                </label>
                <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={reserveForm.is_mobile_money_enabled}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, is_mobile_money_enabled: e.target.checked }))} />
                  Paiements mobiles
                </label>
                <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={reserveForm.is_audit_logs_enabled}
                    onChange={(e) => setReserveForm((prev) => ({ ...prev, is_audit_logs_enabled: e.target.checked }))} />
                  Journaux d\'audit
                </label>
              </div>
              <div className={styles.modalActions} style={{ justifyContent: 'flex-end' }}>
                <button className={styles.primaryButton} onClick={handleReserve} disabled={saving}>
                  {saving ? 'Enregistrement...' : 'Réserver & inviter'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ══════════════════════════════════════════
          Onglet : Facturation
      ══════════════════════════════════════════ */}
      {activeTab === 'facturation' && (
        <>
          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>💰 Configuration facturation globale</div>
            <GlobalBillingConfigEditor />
          </div>

          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>📋 Rapport mensuel consolidé</div>
            <div className={styles.card}>
              <div className={styles.reportRow}>
                <label className={styles.field}>
                  Mois
                  <input type="number" min={1} max={12} value={reportMonth}
                    onChange={(e) => setReportMonth(Number(e.target.value))} />
                </label>
                <label className={styles.field}>
                  Année
                  <input type="number" min={2020} value={reportYear}
                    onChange={(e) => setReportYear(Number(e.target.value))} />
                </label>
                <button className={styles.primaryButton} onClick={async () => {
                  try {
                    const res = await runMonthlyReport(reportMonth, reportYear)
                    showSuccess('Rapport généré', res.path || 'Rapport mensuel prêt.')
                  } catch (err: any) {
                    showError('Erreur', err?.message || 'Génération impossible.')
                  }
                }}>
                  Générer PDF
                </button>
              </div>
              {monthlyStatus?.enabled !== undefined && (
                <div className={styles.expiringMeta}>
                  Scheduler : {monthlyStatus.enabled ? 'activé' : 'désactivé'} · prochaine exécution : {monthlyStatus.next_run || '—'}
                </div>
              )}
            </div>
          </div>

          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>🏦 Preuves de virement bancaire</div>
            <div className={styles.card}>
              {loadingProofs ? (
                <div className={styles.emptyState}>Chargement...</div>
              ) : bankProofs.length === 0 ? (
                <div className={styles.emptyState}>Aucune preuve en attente.</div>
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Session</th><th>Tenant</th><th>Montant</th><th>Statut</th>
                      <th>Preuve</th><th>Reçu le</th><th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bankProofs.map((proof) => (
                      <tr key={proof.id}>
                        <td>{proof.id}</td>
                        <td>{proof.tenant_id}</td>
                        <td>{Number(proof.amount || 0).toLocaleString()} {proof.currency || 'USD'}</td>
                        <td>{proof.status || '—'}</td>
                        <td>
                          {proof.proof_url
                            ? <a className={styles.link} href={proof.proof_url} target="_blank" rel="noreferrer">Ouvrir</a>
                            : '—'}
                        </td>
                        <td>{proof.proof_uploaded_at ? new Date(proof.proof_uploaded_at).toLocaleString() : '—'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button className={styles.actionBtn} onClick={() => handleApproveProof(proof.id)}
                            disabled={(proof.status || '').toLowerCase() === 'success'}>
                            Valider
                          </button>
                          <button className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                            onClick={() => handleRejectProof(proof.id)} style={{ marginLeft: '10px' }}
                            disabled={(proof.status || '').toLowerCase() === 'failed'}>
                            Rejeter
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}

      {/* ══════════════════════════════════════════
          Onglet : Intégrations
      ══════════════════════════════════════════ */}
      {activeTab === 'integrations' && (
        <>
          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>🤖 Fournisseurs IA</div>
            <AIProvidersPanel />
          </div>

          <div className={styles.subSection}>
            <div className={styles.subSectionTitle}>🔑 Google OAuth — Credentials plateforme</div>
            <div className={styles.card}>
              <GoogleOAuthPanel />
            </div>
          </div>
        </>
      )}

      </div>{/* /pageBody */}

      {showImpersonate && impersonateOrg && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHead}>
              <h2>👤 Connexion en tant que...</h2>
              <p>Organisation : <strong>{impersonateOrg.nom}</strong></p>
            </div>
            <div className={styles.modalScroll}>
              {impersonateUsers.length === 0 ? (
                <div className={styles.emptyState}>Aucun utilisateur trouvé.</div>
              ) : (
                <div className={styles.listStack}>
                  {impersonateUsers.map((u) => (
                    <div key={u.id} className={styles.listItem}>
                      <div className={styles.listItemRow}>
                        <div>
                          <div style={{ fontWeight: 600 }}>{u.prenom || ''} {u.nom || ''}</div>
                          <div className={styles.listMeta}>{u.email} · {u.role || 'user'}</div>
                        </div>
                        <button className={styles.btnPrimary} onClick={() => runImpersonate(u)}>
                          Entrer
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowImpersonate(false)}>Fermer</button>
            </div>
          </div>
        </div>
      )}

      {simulationResult && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHead}>
              <h2>✅ Paiement simulé</h2>
              <p>{simulationResult.orgName} · {simulationResult.adminEmail}</p>
            </div>
            <div className={styles.modalScroll}>
              <div className={styles.formGrid}>
                <label className={styles.field}>Référence<input value={simulationResult.reference} readOnly /></label>
                <label className={styles.field}>Mot de passe temporaire<input value={simulationResult.tempPassword || 'Généré'} readOnly /></label>
              </div>
            </div>
            <div className={styles.modalActions}>
              {simulationResult.tempPassword && (
                <button className={styles.btnSecondary} onClick={async () => {
                  try { await navigator.clipboard.writeText(simulationResult.tempPassword || ''); showSuccess('Copié', 'Mot de passe copié.') }
                  catch (err: any) { showError('Erreur', err?.message) }
                }}>📋 Copier le mot de passe</button>
              )}
              <button className={styles.secondaryButton} onClick={() => setSimulationResult(null)}>Fermer</button>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHead}>
              <h2>+ Provisionner un tenant</h2>
              <p>Création de l\'organisation, admin initial et caisse centrale.</p>
            </div>
            <div className={styles.modalScroll}>
              <div className={styles.formGrid}>
                <label className={styles.field}>Nom organisation*<input value={form.nom} onChange={(e) => setForm((p) => ({ ...p, nom: e.target.value }))} placeholder="CPHK" /></label>
                <label className={styles.field}>Slug (sous-domaine)*<input value={form.slug} onChange={(e) => setForm((p) => ({ ...p, slug: e.target.value }))} placeholder="cphk" /></label>
                <label className={styles.field}>Plan<select value={form.plan_type} onChange={(e) => setForm((p) => ({ ...p, plan_type: e.target.value }))}>
                  <option value="FREE">FREE</option><option value="BASIC">BASIC</option><option value="PREMIUM">PREMIUM</option><option value="ENTERPRISE">ENTERPRISE</option>
                </select></label>
                <label className={styles.field}>Statut<select value={form.status_abonnement} onChange={(e) => setForm((p) => ({ ...p, status_abonnement: e.target.value }))}>
                  <option value="TRIAL">TRIAL</option><option value="ACTIVE">ACTIVE</option><option value="PAST_DUE">PAST_DUE</option><option value="CANCELED">CANCELED</option>
                </select></label>
                <label className={styles.field}>Jours d\'essai<input type="number" min={0} value={form.trial_days} onChange={(e) => setForm((p) => ({ ...p, trial_days: Number(e.target.value) }))} /></label>
                <label className={styles.field}>Limite utilisateurs<input type="number" min={1} value={form.limite_utilisateurs} onChange={(e) => setForm((p) => ({ ...p, limite_utilisateurs: Number(e.target.value) }))} /></label>
                <label className={styles.field}>Email admin*<input type="email" value={form.admin_email} onChange={(e) => setForm((p) => ({ ...p, admin_email: e.target.value }))} placeholder="admin@cphk.cd" /></label>
                <label className={styles.field}>Mot de passe admin*<input type="password" value={form.admin_password} onChange={(e) => setForm((p) => ({ ...p, admin_password: e.target.value }))} /></label>
              </div>
              {error && <div className={styles.error}>{error}</div>}
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowModal(false)} disabled={saving}>Annuler</button>
              <button className={styles.btnPrimary} onClick={handleCreate} disabled={saving}>{saving ? 'Création...' : 'Créer le tenant'}</button>
            </div>
          </div>
        </div>
      )}

      {showGrantTrial && grantTrialOrg && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHead}>
              <h2>🎁 Attribuer un essai</h2>
              <p>Organisation : <strong>{grantTrialOrg.nom}</strong></p>
            </div>
            <div className={styles.modalScroll}>
              <div className={styles.formGrid}>
                <label className={styles.field}>Plan
                  <select value={grantTrialForm.plan_type} onChange={(e) => setGrantTrialForm((p) => ({ ...p, plan_type: e.target.value }))}>
                    <option value="FREE">FREE — accès gratuit limité</option>
                    <option value="STANDARD">STANDARD — essai complet</option>
                    <option value="PREMIUM">PREMIUM — essai premium</option>
                  </select>
                </label>
                <label className={styles.field}>Durée (jours)
                  <input type="number" min={1} max={365} value={grantTrialForm.duration_days}
                    onChange={(e) => setGrantTrialForm((p) => ({ ...p, duration_days: Number(e.target.value) }))} />
                </label>
              </div>
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowGrantTrial(false)}>Annuler</button>
              <button className={styles.btnPrimary} onClick={handleGrantTrial} disabled={grantingTrialOrgId === grantTrialOrg.id}>
                {grantingTrialOrgId === grantTrialOrg.id ? 'Attribution...' : 'Attribuer'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSettings && settingsOrg && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal} style={{ width: 'min(860px, 96vw)' }}>
            <div className={styles.modalHead}>
              <h2>⚙️ Configuration — {settingsOrg.nom}</h2>
              <p>Modules, facturation et historique des paiements.</p>
            </div>
            <div className={styles.modalScroll}>
              <ProvinceSettingsEditor provinceId={settingsOrg.id}
                onSaved={() => showSuccess('Configuration mise à jour', `${settingsOrg.nom} est configurée.`)} />
              <BillingConfigEditor orgId={settingsOrg.id} />
              <TenantBankProofs tenantId={settingsOrg.slug} />
              <TenantPaymentHistory orgId={settingsOrg.id} />
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setShowSettings(false)}>Fermer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
