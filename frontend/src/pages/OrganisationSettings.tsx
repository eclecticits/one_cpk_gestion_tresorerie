import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { adminSavePrintSettings, adminUploadAsset } from '../api/admin'
import { getOrganisation, getOrganisationSettings, updateOrganisation, updateOrganisationSettings, type Organisation, type WorkflowConfig } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import WorkflowSettings from '../components/settings/WorkflowSettings'
import { getPrintSettings } from '../api/settings'
import { ColorPreview } from '../components/ColorPreview'
import { useNotification } from '../contexts/NotificationContext'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import { getContrastColor } from '../utils/colors'
import { buildUploadUrl } from '../utils/uploads'
import BillingPanel from '../components/Billing/BillingPanel'
import styles from './OrganisationSettings.module.css'
import settingsStyles from './Settings.module.css'

type FormState = {
  nom: string
  devise_preferee: string
  taux_change_interne: string
  logo_url: string
  theme_primary_color: string
  theme_sidebar_color: string
  theme_sidebar_text_color: string
  theme_sidebar_active_color: string
  theme_accent_color: string
  theme_text_color: string
  theme_button_text_color: string
}

export default function OrganisationSettings() {
  const navigate = useNavigate()
  const { showError, showSuccess } = useNotification()
  const { reload: reloadOrgSettings } = useOrganisationSettings()
  const defaultTheme = {
    primary: '#4a9079',
    sidebar: '#3d7a66',
    sidebarText: '#ffffff',
    sidebarActive: '#1a523f',
    accent: '#eab308',
    text: '#2d3748',
    buttonText: '#ffffff',
  }
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [org, setOrg] = useState<Organisation | null>(null)
  const [workflowConfig, setWorkflowConfig] = useState<WorkflowConfig | null>(null)
  const [pivotCurrency, setPivotCurrency] = useState<string>('')
  const { user } = useAuth()
  const [form, setForm] = useState<FormState>({
    nom: '',
    devise_preferee: 'USD',
    taux_change_interne: '',
    logo_url: '',
    theme_primary_color: '#4a9079',
    theme_sidebar_color: '#3d7a66',
    theme_sidebar_text_color: '#ffffff',
    theme_sidebar_active_color: '#1a523f',
    theme_accent_color: '#eab308',
    theme_text_color: '#2d3748',
    theme_button_text_color: '#ffffff',
  })

  useEffect(() => {
    const load = async () => {
      try {
        const [orgRes, settingsRes, printRes] = await Promise.all([
          getOrganisation(),
          getOrganisationSettings(),
          getPrintSettings().catch(() => null),
        ])
        setOrg(orgRes)
        setWorkflowConfig(settingsRes.workflow_config ?? null)
        // La devise de référence de l'app est la DEVISE PIVOT (print settings).
        // Par défaut (aucun réglage), le pivot est USD.
        setPivotCurrency(printRes?.default_currency || 'USD')
        const sidebarColor = settingsRes.theme_sidebar_color || '#3d7a66'
        const sidebarText = settingsRes.theme_sidebar_text_color || getContrastColor(sidebarColor)
        setForm({
          nom: orgRes.nom || '',
          devise_preferee: orgRes.devise_preferee || 'USD',
          taux_change_interne: orgRes.taux_change_interne ? String(orgRes.taux_change_interne) : '',
          logo_url: orgRes.logo_url || '',
          theme_primary_color: settingsRes.theme_primary_color || '#4a9079',
          theme_sidebar_color: sidebarColor,
          theme_sidebar_text_color: sidebarText,
          theme_sidebar_active_color: settingsRes.theme_sidebar_active_color || '#1a523f',
          theme_accent_color: settingsRes.theme_accent_color || '#eab308',
          theme_text_color: settingsRes.theme_text_color || '#2d3748',
          theme_button_text_color: settingsRes.theme_button_text_color || '#ffffff',
        })
      } catch (error: any) {
        console.error('Erreur chargement organisation:', error)
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
      await updateOrganisationSettings({
        currency_code: form.devise_preferee || 'USD',
        theme_primary_color: form.theme_primary_color,
        theme_sidebar_color: form.theme_sidebar_color,
        theme_sidebar_text_color: form.theme_sidebar_text_color,
        theme_sidebar_active_color: form.theme_sidebar_active_color,
        theme_accent_color: form.theme_accent_color,
        theme_text_color: form.theme_text_color,
        theme_button_text_color: form.theme_button_text_color,
      })
      await reloadOrgSettings()
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
      <button
        type="button"
        className={settingsStyles.backButton}
        onClick={() => navigate('/settings?tab=general&sub=identite')}
      >
        <ArrowLeft size={15} />
        <span>Retour aux paramètres</span>
      </button>
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
              <img src={buildUploadUrl(form.logo_url)} alt="Logo organisation" className={styles.logoPreview} />
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
          <h2>Thème du site</h2>
          <div className={styles.sectionTitle}>Navigation (Menu)</div>
          <label className={styles.label}>Fond du menu</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_sidebar_color}
              onChange={(e) => {
                const nextColor = e.target.value
                const autoTextColor = getContrastColor(nextColor)
                setForm((prev) => ({
                  ...prev,
                  theme_sidebar_color: nextColor,
                  theme_sidebar_text_color: autoTextColor,
                }))
              }}
            />
            <span className={styles.colorValue}>{form.theme_sidebar_color}</span>
          </div>
          <ColorPreview
            label="Menu actif"
            bgColor={form.theme_sidebar_color}
            type="sidebar"
            textColor={form.theme_sidebar_text_color}
          />

          <label className={styles.label}>Texte du menu</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_sidebar_text_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_sidebar_text_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_sidebar_text_color}</span>
          </div>
          <ColorPreview
            label="Item de menu"
            bgColor={form.theme_sidebar_color}
            type="sidebar"
            textColor={form.theme_sidebar_text_color}
          />

          <label className={styles.label}>Fond actif du menu</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_sidebar_active_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_sidebar_active_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_sidebar_active_color}</span>
          </div>
          <ColorPreview
            label="Item sélectionné"
            bgColor={form.theme_sidebar_active_color}
            type="sidebar"
            textColor={form.theme_sidebar_text_color}
          />

          <div className={styles.sectionTitle}>Contenu principal</div>
          <label className={styles.label}>Texte principal</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_text_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_text_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_text_color}</span>
          </div>
          <ColorPreview label="Texte principal" bgColor={form.theme_text_color} type="text" />

          <label className={styles.label}>Couleur d'accentuation (boutons, liens)</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_primary_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_primary_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_primary_color}</span>
          </div>
          <ColorPreview
            label="Valider la dépense"
            bgColor={form.theme_primary_color}
            type="button"
            textColor={form.theme_button_text_color}
          />

          <label className={styles.label}>Couleur d'accent secondaire</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_accent_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_accent_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_accent_color}</span>
          </div>
          <ColorPreview
            label="Badge secondaire"
            bgColor={form.theme_accent_color}
            type="button"
            textColor={form.theme_button_text_color}
          />

          <label className={styles.label}>Texte des boutons</label>
          <div className={styles.colorRow}>
            <input
              className={styles.colorInput}
              type="color"
              value={form.theme_button_text_color}
              onChange={(e) => setForm((prev) => ({ ...prev, theme_button_text_color: e.target.value }))}
            />
            <span className={styles.colorValue}>{form.theme_button_text_color}</span>
          </div>
          <ColorPreview
            label="Bouton"
            bgColor={form.theme_primary_color}
            type="button"
            textColor={form.theme_button_text_color}
          />

          <button
            type="button"
            className={styles.resetThemeBtn}
            onClick={() =>
              setForm((prev) => ({
                ...prev,
                theme_primary_color: defaultTheme.primary,
                theme_sidebar_color: defaultTheme.sidebar,
                theme_sidebar_text_color: defaultTheme.sidebarText,
                theme_sidebar_active_color: defaultTheme.sidebarActive,
                theme_accent_color: defaultTheme.accent,
                theme_text_color: defaultTheme.text,
                theme_button_text_color: defaultTheme.buttonText,
              }))
            }
          >
            Remettre par défaut
          </button>
        </div>
      </div>

      <div className={settingsStyles.section}>
        <div className={settingsStyles.sectionHeader}>
          <div>
            <h2>Abonnement & Facturation</h2>
            <div className={settingsStyles.mutedText}>
              Votre plan, vos échéances et vos moyens de paiement.
            </div>
          </div>
        </div>
        <BillingPanel />
      </div>

      <div className={settingsStyles.section}>
        <WorkflowSettings
          initialConfig={workflowConfig}
          canEdit={(user?.role || '').toLowerCase() === 'super_admin'}
          currency={pivotCurrency || 'USD'}
        />
      </div>

      <div className={styles.actions}>
        <button className={styles.saveBtn} onClick={handleSave} disabled={saving}>
          {saving ? 'Enregistrement...' : 'Enregistrer'}
        </button>
      </div>
    </div>
  )
}
