import { useEffect, useRef, useState } from 'react'
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
  const [storageUnit, setStorageUnit] = useState<'MB' | 'GB'>('GB')
  const lastMaxUsersRef = useRef<number>(5)
  const lastStorageMbRef = useRef<number>(1024)

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const res = await getOrganisationSettings(provinceId)
        if (active) {
          setSettings(res)
          setHasChanges(false)
          if (res.max_users > 0) {
            lastMaxUsersRef.current = res.max_users
          }
          if (res.storage_quota_mb > 0) {
            lastStorageMbRef.current = res.storage_quota_mb
            setStorageUnit(res.storage_quota_mb >= 1024 && res.storage_quota_mb % 1024 === 0 ? 'GB' : 'MB')
          }
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

  const usersUnlimited = settings.max_users === 0
  const storageUnlimited = settings.storage_quota_mb === 0
  const storageValue =
    storageUnlimited ? '' : storageUnit === 'GB' ? (settings.storage_quota_mb / 1024).toString() : settings.storage_quota_mb.toString()

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
          <div className={styles.quotaRow}>
            <div className={styles.quotaHeader}>
              <span>Limite d'utilisateurs</span>
              <span className={styles.quotaValue}>{usersUnlimited ? 'Illimité' : settings.max_users}</span>
            </div>
            <div className={styles.quotaControls}>
              <input
                type="number"
                min={1}
                value={usersUnlimited ? '' : settings.max_users}
                onChange={(e) => {
                  const value = e.target.value === '' ? 1 : Number.parseInt(e.target.value, 10)
                  if (Number.isFinite(value)) {
                    lastMaxUsersRef.current = Math.max(1, value)
                    setSettings({ ...settings, max_users: lastMaxUsersRef.current })
                    setHasChanges(true)
                  }
                }}
                disabled={usersUnlimited}
              />
              <label className={styles.inlineToggle}>
                <input
                  type="checkbox"
                  checked={usersUnlimited}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSettings({ ...settings, max_users: 0 })
                    } else {
                      setSettings({ ...settings, max_users: Math.max(1, lastMaxUsersRef.current) })
                    }
                    setHasChanges(true)
                  }}
                />
                Illimité
              </label>
            </div>
          </div>

          <div className={styles.quotaRow}>
            <div className={styles.quotaHeader}>
              <span>Stockage</span>
              <span className={styles.quotaValue}>
                {storageUnlimited
                  ? 'Illimité'
                  : storageUnit === 'GB'
                    ? `${(settings.storage_quota_mb / 1024).toFixed(2).replace(/\\.00$/, '')} GB`
                    : `${settings.storage_quota_mb} MB`}
              </span>
            </div>
            <div className={styles.quotaControls}>
              <input
                type="number"
                min={storageUnit === 'GB' ? 0.1 : 128}
                step={storageUnit === 'GB' ? 0.1 : 128}
                value={storageValue}
                onChange={(e) => {
                  const raw = Number(e.target.value)
                  if (!Number.isFinite(raw)) return
                  const nextMb = storageUnit === 'GB' ? Math.round(raw * 1024) : Math.round(raw)
                  lastStorageMbRef.current = Math.max(1, nextMb)
                  setSettings({ ...settings, storage_quota_mb: lastStorageMbRef.current })
                  setHasChanges(true)
                }}
                disabled={storageUnlimited}
              />
              <select
                value={storageUnit}
                onChange={(e) => {
                  const nextUnit = e.target.value === 'MB' ? 'MB' : 'GB'
                  setStorageUnit(nextUnit)
                }}
                disabled={storageUnlimited}
              >
                <option value="MB">MB</option>
                <option value="GB">GB</option>
              </select>
              <label className={styles.inlineToggle}>
                <input
                  type="checkbox"
                  checked={storageUnlimited}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSettings({ ...settings, storage_quota_mb: 0 })
                    } else {
                      setSettings({ ...settings, storage_quota_mb: Math.max(1, lastStorageMbRef.current) })
                    }
                    setHasChanges(true)
                  }}
                />
                Illimité
              </label>
            </div>
          </div>
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
