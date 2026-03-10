import { useEffect, useMemo, useState } from 'react'
import { createOrganisation, listOrganisations, updateOrganisation, type SuperAdminOrganisation } from '../api/superAdmin'
import { useNotification } from '../contexts/NotificationContext'
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
  const { showError, showSuccess } = useNotification()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [orgs, setOrgs] = useState<SuperAdminOrganisation[]>([])
  const [showModal, setShowModal] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ ...DEFAULT_FORM })

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

  useEffect(() => {
    load()
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
        <button className={styles.primaryButton} onClick={() => setShowModal(true)}>
          + Nouvelle organisation
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

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
