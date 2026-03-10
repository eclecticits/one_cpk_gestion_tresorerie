import { useEffect, useState } from 'react'
import { adminSavePrintSettings, adminUploadAsset } from '../api/admin'
import { getOrganisation, updateOrganisation, type Organisation } from '../api/organisation'
import { useNotification } from '../contexts/NotificationContext'
import styles from './OrganisationSettings.module.css'

type FormState = {
  nom: string
  devise_preferee: string
  taux_change_interne: string
  logo_url: string
}

export default function OrganisationSettings() {
  const { showError, showSuccess } = useNotification()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [org, setOrg] = useState<Organisation | null>(null)
  const [form, setForm] = useState<FormState>({
    nom: '',
    devise_preferee: 'USD',
    taux_change_interne: '',
    logo_url: '',
  })

  useEffect(() => {
    const load = async () => {
      try {
        const res = await getOrganisation()
        setOrg(res)
        setForm({
          nom: res.nom || '',
          devise_preferee: res.devise_preferee || 'USD',
          taux_change_interne: res.taux_change_interne ? String(res.taux_change_interne) : '',
          logo_url: res.logo_url || '',
        })
      } catch (error: any) {
        showError('Erreur', error.message || "Impossible de charger l'organisation.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const handleLogoUpload = async (file: File) => {
    if (!file) return
    try {
      setUploading(true)
      const res = await adminUploadAsset('logo', file)
      const nextLogo = res.url
      setForm((prev) => ({ ...prev, logo_url: nextLogo }))
      const updated = await updateOrganisation({ logo_url: nextLogo })
      setOrg(updated)
      await adminSavePrintSettings({
        organization_name: updated.nom,
        logo_url: nextLogo,
      })
      showSuccess('Logo mis à jour', 'Le logo de votre organisation a été enregistré.')
    } catch (error: any) {
      showError('Erreur', error.message || 'Upload impossible.')
    } finally {
      setUploading(false)
    }
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      const taux = form.taux_change_interne ? Number(form.taux_change_interne) : null
      const updated = await updateOrganisation({
        nom: form.nom,
        devise_preferee: form.devise_preferee || null,
        taux_change_interne: taux,
      })
      setOrg(updated)
      await adminSavePrintSettings({
        organization_name: updated.nom,
        logo_url: form.logo_url || '',
        exchange_rate: taux ?? undefined,
        exchange_rate_cdf: taux ?? undefined,
      })
      showSuccess('Organisation mise à jour', 'Les paramètres ont été enregistrés.')
    } catch (error: any) {
      showError('Erreur', error.message || "Impossible d'enregistrer.")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1>Paramètres Organisation</h1>
          <p>Identité visuelle, devise et taux de change interne.</p>
        </div>
        {org && (
          <div className={styles.planCard}>
            <div className={styles.planLabel}>Abonnement</div>
            <div className={styles.planValue}>
              {org.plan_type} · {org.status_abonnement}
            </div>
            {org.date_expiration_abonnement && (
              <div className={styles.planMeta}>Expire le {new Date(org.date_expiration_abonnement).toLocaleDateString()}</div>
            )}
            <div className={styles.planMeta}>Limite utilisateurs : {org.limite_utilisateurs}</div>
          </div>
        )}
      </div>

      <div className={styles.grid}>
        <div className={styles.card}>
          <h2>Identité</h2>
          <label className={styles.label}>Nom de l'organisation</label>
          <input
            className={styles.input}
            value={form.nom}
            onChange={(e) => setForm((prev) => ({ ...prev, nom: e.target.value }))}
            placeholder="Nom officiel"
          />

          <label className={styles.label}>Logo</label>
          <div className={styles.logoRow}>
            {form.logo_url ? (
              <img src={form.logo_url} alt="Logo organisation" className={styles.logoPreview} />
            ) : (
              <div className={styles.logoPlaceholder}>Aucun logo</div>
            )}
            <label className={styles.uploadBtn}>
              {uploading ? 'Upload...' : 'Téléverser'}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleLogoUpload(file)
                }}
              />
            </label>
          </div>
        </div>

        <div className={styles.card}>
          <h2>Paramètres financiers</h2>
          <label className={styles.label}>Devise par défaut</label>
          <select
            className={styles.select}
            value={form.devise_preferee}
            onChange={(e) => setForm((prev) => ({ ...prev, devise_preferee: e.target.value }))}
          >
            <option value="USD">USD</option>
            <option value="CDF">CDF</option>
            <option value="EUR">EUR</option>
            <option value="XOF">XOF</option>
          </select>

          <label className={styles.label}>Taux de change interne</label>
          <input
            className={styles.input}
            type="number"
            step="0.01"
            value={form.taux_change_interne}
            onChange={(e) => setForm((prev) => ({ ...prev, taux_change_interne: e.target.value }))}
            placeholder="Ex: 2800"
          />
        </div>
      </div>

      <div className={styles.actions}>
        <button className={styles.saveBtn} onClick={handleSave} disabled={saving}>
          {saving ? 'Enregistrement...' : 'Enregistrer'}
        </button>
      </div>
    </div>
  )
}
