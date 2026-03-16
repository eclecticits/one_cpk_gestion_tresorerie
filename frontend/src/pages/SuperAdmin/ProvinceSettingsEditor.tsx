import { useEffect, useState } from 'react'
import { Save, Database, Zap } from 'lucide-react'
import { getOrganisationSettings, updateOrganisationSettings, type OrganisationSettings } from '../../api/superAdmin'
import styles from './ProvinceSettingsEditor.module.css'

type ProvinceSettingsEditorProps = {
  provinceId: number
  onSaved?: (settings: OrganisationSettings) => void
}

export default function ProvinceSettingsEditor({ provinceId, onSaved }: ProvinceSettingsEditorProps) {
  const [settings, setSettings] = useState<OrganisationSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const res = await getOrganisationSettings(provinceId)
        if (active) {
          setSettings(res)
          setHasChanges(false)
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [provinceId])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const updated = await updateOrganisationSettings(provinceId, settings)
      setSettings(updated)
      setHasChanges(false)
      onSaved?.(updated)
    } finally {
      setSaving(false)
    }
  }

  if (loading || !settings) {
    return <div className={styles.loading}>Chargement des dépendances...</div>
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div>
          <h2>Configuration des Dépendances</h2>
          <p>Ajustez les quotas et modules pour cette province</p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className={styles.saveButton}
          type="button"
        >
          <Save size={18} />
          {saving ? 'Enregistrement...' : 'Sauvegarder'}
        </button>
        {hasChanges && (
          <button
            onClick={async () => {
              setLoading(true)
              try {
                const res = await getOrganisationSettings(provinceId)
                setSettings(res)
                setHasChanges(false)
              } finally {
                setLoading(false)
              }
            }}
            disabled={saving || loading}
            className={styles.cancelButton}
            type="button"
          >
            Annuler
          </button>
        )}
      </div>

      <div className={styles.grid}>
        <section className={styles.section}>
          <h3>
            <Database size={16} /> Quotas & limites
          </h3>
          <label className={styles.rangeField}>
            <span>
              Limite d'utilisateurs <strong>{settings.max_users}</strong>
            </span>
            <input
              type="range"
              min={1}
              max={100}
              value={settings.max_users}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  max_users: Number.parseInt(e.target.value, 10),
                })
              }
              onInput={() => setHasChanges(true)}
            />
          </label>
          <label className={styles.rangeField}>
            <span>
              Stockage (MB) <strong>{settings.storage_quota_mb} MB</strong>
            </span>
            <input
              type="range"
              min={512}
              max={10240}
              step={512}
              value={settings.storage_quota_mb}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  storage_quota_mb: Number.parseInt(e.target.value, 10),
                })
              }
              onInput={() => setHasChanges(true)}
            />
          </label>
        </section>

        <section className={styles.section}>
          <h3>
            <Zap size={16} /> Activation des modules
          </h3>
          <ToggleCard
            title="Intelligence artificielle"
            description="Analyse prédictive Gemma 2"
            checked={settings.is_ai_enabled}
            onChange={(val) => {
              setSettings({ ...settings, is_ai_enabled: val })
              setHasChanges(true)
            }}
          />
          <ToggleCard
            title="Mobile Money"
            description="Encaissements FedaPay"
            checked={settings.is_mobile_money_enabled}
            onChange={(val) => {
              setSettings({ ...settings, is_mobile_money_enabled: val })
              setHasChanges(true)
            }}
          />
          <ToggleCard
            title="Journaux d'audit"
            description="Traçabilité haute sécurité"
            checked={settings.is_audit_logs_enabled}
            onChange={(val) => {
              setSettings({ ...settings, is_audit_logs_enabled: val })
              setHasChanges(true)
            }}
          />
        </section>
      </div>
    </div>
  )
}

type ToggleCardProps = {
  title: string
  description: string
  checked: boolean
  onChange: (value: boolean) => void
}

function ToggleCard({ title, description, checked, onChange }: ToggleCardProps) {
  return (
    <div className={`${styles.toggleCard} ${checked ? styles.toggleActive : ''}`}>
      <div>
        <p className={styles.toggleTitle}>{title}</p>
        <p className={styles.toggleDescription}>{description}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`${styles.toggleButton} ${checked ? styles.toggleOn : styles.toggleOff}`}
        aria-pressed={checked}
      >
        <span className={`${styles.toggleKnob} ${checked ? styles.knobOn : styles.knobOff}`} />
      </button>
    </div>
  )
}
