import { useEffect, useRef, useState } from 'react'
import { Save, Database, Zap, Users, FileText, Wallet, Settings2 } from 'lucide-react'
import {
  getOrganisationSettings,
  updateOrganisationSettings,
  type OrganisationSettings,
  type ModulesConfig,
  type RHModuleConfig,
  type SecretariatModuleConfig,
  type TresorerieModuleConfig,
} from '../../api/superAdmin'
import styles from './ProvinceSettingsEditor.module.css'

// ── Valeurs par défaut des modules ───────────────────────────────────────────

const DEFAULT_TRESORERIE: TresorerieModuleConfig = {
  enabled: true,
  requisitions: true,
  payments: true,
  exports: true,
  budget_tracking: true,
  reconciliation: true,
}

const DEFAULT_RH: RHModuleConfig = {
  enabled: false,
  max_employees: 0,
  leave_management: true,
  contract_tracking: true,
  payroll: false,
  recruitment: false,
  performance_reviews: false,
  training: false,
}

const DEFAULT_SECRETARIAT: SecretariatModuleConfig = {
  enabled: false,
  documents: true,
  meetings: true,
  agenda: true,
  ai_mail: true,
  approvals: true,
  max_documents: 0,
  max_meetings_per_month: 0,
}

function mergeModules(saved: ModulesConfig | null): ModulesConfig {
  return {
    tresorerie: { ...DEFAULT_TRESORERIE, ...(saved?.tresorerie ?? {}) },
    rh: { ...DEFAULT_RH, ...(saved?.rh ?? {}) },
    secretariat: { ...DEFAULT_SECRETARIAT, ...(saved?.secretariat ?? {}) },
  }
}

// ── Types locaux ─────────────────────────────────────────────────────────────

type ProvinceSettingsEditorProps = {
  provinceId: number
  onSaved?: (settings: OrganisationSettings) => void
}

type ActiveTab = 'quotas' | 'systeme' | 'tresorerie' | 'rh' | 'secretariat' | 'theme'

// ── Composant principal ───────────────────────────────────────────────────────

export default function ProvinceSettingsEditor({ provinceId, onSaved }: ProvinceSettingsEditorProps) {
  const [settings, setSettings] = useState<OrganisationSettings | null>(null)
  const [modules, setModules] = useState<ModulesConfig>(mergeModules(null))
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<ActiveTab>('quotas')
  const [storageUnit, setStorageUnit] = useState<'MB' | 'GB'>('GB')
  const lastMaxUsersRef = useRef<number>(5)
  const lastStorageMbRef = useRef<number>(1024)

  const load = async () => {
    setLoading(true)
    try {
      const res = await getOrganisationSettings(provinceId)
      setSettings(res)
      setModules(mergeModules(res.modules_config))
      setHasChanges(false)
      if (res.max_users > 0) lastMaxUsersRef.current = res.max_users
      if (res.storage_quota_mb > 0) {
        lastStorageMbRef.current = res.storage_quota_mb
        setStorageUnit(res.storage_quota_mb >= 1024 && res.storage_quota_mb % 1024 === 0 ? 'GB' : 'MB')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    const loadOnce = async () => {
      setLoading(true)
      try {
        const res = await getOrganisationSettings(provinceId)
        if (!active) return
        setSettings(res)
        setModules(mergeModules(res.modules_config))
        setHasChanges(false)
        if (res.max_users > 0) lastMaxUsersRef.current = res.max_users
        if (res.storage_quota_mb > 0) {
          lastStorageMbRef.current = res.storage_quota_mb
          setStorageUnit(res.storage_quota_mb >= 1024 && res.storage_quota_mb % 1024 === 0 ? 'GB' : 'MB')
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    void loadOnce()
    return () => { active = false }
  }, [provinceId])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const updated = await updateOrganisationSettings(provinceId, {
        ...settings,
        modules_config: modules,
      })
      setSettings(updated)
      setModules(mergeModules(updated.modules_config))
      setHasChanges(false)
      onSaved?.(updated)
    } finally {
      setSaving(false)
    }
  }

  const patch = (partial: Partial<OrganisationSettings>) => {
    setSettings(s => s ? { ...s, ...partial } : s)
    setHasChanges(true)
  }

  const patchMod = <K extends keyof ModulesConfig>(
    key: K,
    partial: Partial<ModulesConfig[K]>,
  ) => {
    setModules(m => ({ ...m, [key]: { ...m[key], ...partial } as ModulesConfig[K] }))
    setHasChanges(true)
  }

  if (loading || !settings) {
    return <div className={styles.loading}>Chargement de la configuration...</div>
  }

  const usersUnlimited = settings.max_users === 0
  const storageUnlimited = settings.storage_quota_mb === 0
  const storageValue = storageUnlimited
    ? ''
    : storageUnit === 'GB'
      ? (settings.storage_quota_mb / 1024).toString()
      : settings.storage_quota_mb.toString()

  const TABS: { id: ActiveTab; label: string; icon: React.ReactNode; badge?: string }[] = [
    { id: 'quotas',      label: 'Quotas',       icon: <Database size={14} /> },
    { id: 'systeme',     label: 'Système',       icon: <Zap size={14} /> },
    { id: 'tresorerie',  label: 'Trésorerie',    icon: <Wallet size={14} />, badge: modules.tresorerie?.enabled ? 'ON' : 'OFF' },
    { id: 'rh',          label: 'R.H.',          icon: <Users size={14} />, badge: modules.rh?.enabled ? 'ON' : 'OFF' },
    { id: 'secretariat', label: 'Secrétariat',   icon: <FileText size={14} />, badge: modules.secretariat?.enabled ? 'ON' : 'OFF' },
    { id: 'theme',       label: 'Thème',         icon: <Settings2 size={14} /> },
  ]

  return (
    <div className={styles.card}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h2>Configuration des Dépendances</h2>
          <p>Quotas, modules et fonctionnalités pour cette province</p>
        </div>
        <div className={styles.headerActions}>
          {hasChanges && (
            <button onClick={load} disabled={saving || loading} className={styles.cancelButton} type="button">
              Annuler
            </button>
          )}
          <button onClick={handleSave} disabled={saving || !hasChanges} className={styles.saveButton} type="button">
            <Save size={16} />
            {saving ? 'Enregistrement...' : 'Sauvegarder'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.tab} ${activeTab === tab.id ? styles.tabActive : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon}
            {tab.label}
            {tab.badge && (
              <span className={tab.badge === 'ON' ? styles.badgeOn : styles.badgeOff}>
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab: Quotas ── */}
      {activeTab === 'quotas' && (
        <div className={styles.tabContent}>
          <QuotaRow
            label="Limite d'utilisateurs"
            hint="Nombre maximum d'utilisateurs actifs"
            value={settings.max_users}
            unlimited={usersUnlimited}
            min={1}
            onChangeValue={v => { lastMaxUsersRef.current = v; patch({ max_users: v }) }}
            onChangeUnlimited={u => patch({ max_users: u ? 0 : Math.max(1, lastMaxUsersRef.current) })}
          />
          <div className={styles.storageRow}>
            <div className={styles.quotaHeader}>
              <span>Stockage</span>
              <span className={styles.quotaValue}>
                {storageUnlimited
                  ? 'Illimité'
                  : storageUnit === 'GB'
                    ? `${(settings.storage_quota_mb / 1024).toFixed(2).replace(/\.00$/, '')} GB`
                    : `${settings.storage_quota_mb} MB`}
              </span>
            </div>
            <div className={styles.quotaControls}>
              <input
                type="number"
                className={styles.numInput}
                min={storageUnit === 'GB' ? 0.1 : 128}
                step={storageUnit === 'GB' ? 0.5 : 128}
                value={storageValue}
                disabled={storageUnlimited}
                onChange={e => {
                  const raw = Number(e.target.value)
                  if (!Number.isFinite(raw)) return
                  const mb = storageUnit === 'GB' ? Math.round(raw * 1024) : Math.round(raw)
                  lastStorageMbRef.current = Math.max(1, mb)
                  patch({ storage_quota_mb: lastStorageMbRef.current })
                }}
              />
              <select
                className={styles.unitSelect}
                value={storageUnit}
                disabled={storageUnlimited}
                onChange={e => setStorageUnit(e.target.value === 'MB' ? 'MB' : 'GB')}
              >
                <option value="GB">GB</option>
                <option value="MB">MB</option>
              </select>
              <label className={styles.inlineToggle}>
                <input
                  type="checkbox"
                  checked={storageUnlimited}
                  onChange={e => patch({ storage_quota_mb: e.target.checked ? 0 : Math.max(1, lastStorageMbRef.current) })}
                />
                Illimité
              </label>
            </div>
          </div>

          <div className={styles.localeGrid}>
            <label className={styles.field}>
              <span>Début exercice fiscal</span>
              <select
                className={styles.select}
                value={settings.fiscal_year_start}
                onChange={e => patch({ fiscal_year_start: Number(e.target.value) })}
              >
                {['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'].map((m, i) => (
                  <option key={i} value={i + 1}>{m}</option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              <span>Devise</span>
              <select
                className={styles.select}
                value={settings.currency_code}
                onChange={e => patch({ currency_code: e.target.value })}
              >
                {['CDF','USD','EUR','XOF','XAF','GBP','GHS','NGN','KES','ZAR'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      )}

      {/* ── Tab: Système ── */}
      {activeTab === 'systeme' && (
        <div className={styles.tabContent}>
          <p className={styles.sectionDesc}>
            Fonctionnalités transversales disponibles pour toute l'organisation.
          </p>
          <ToggleCard
            title="Intelligence Artificielle"
            description="Analyse prédictive, suggestions automatisées (Gemma 2, Claude, OpenAI…)"
            checked={settings.is_ai_enabled}
            onChange={v => patch({ is_ai_enabled: v })}
            color="#7c3aed"
          />
          <ToggleCard
            title="Mobile Money"
            description="Encaissements et paiements via FedaPay"
            checked={settings.is_mobile_money_enabled}
            onChange={v => patch({ is_mobile_money_enabled: v })}
            color="#16a34a"
          />
          <ToggleCard
            title="Journaux d'audit"
            description="Traçabilité haute sécurité de toutes les actions utilisateurs"
            checked={settings.is_audit_logs_enabled}
            onChange={v => patch({ is_audit_logs_enabled: v })}
            color="#0ea5e9"
          />
        </div>
      )}

      {/* ── Tab: Trésorerie ── */}
      {activeTab === 'tresorerie' && (
        <ModuleTab
          title="Module Trésorerie"
          description="Gestion financière — encaissements, réquisitions, budget, rapprochement."
          color="#0ea5e9"
          enabled={modules.tresorerie?.enabled ?? true}
          onToggle={v => patchMod('tresorerie', { enabled: v })}
          alwaysOn
        >
          <div className={styles.subGrid}>
            <SubToggle label="Réquisitions" desc="Demandes de fonds, bons de commande" checked={modules.tresorerie?.requisitions ?? true} onChange={v => patchMod('tresorerie', { requisitions: v })} disabled={!modules.tresorerie?.enabled} />
            <SubToggle label="Paiements" desc="Sorties de fonds, virements" checked={modules.tresorerie?.payments ?? true} onChange={v => patchMod('tresorerie', { payments: v })} disabled={!modules.tresorerie?.enabled} />
            <SubToggle label="Suivi budgétaire" desc="Allocation et contrôle du budget" checked={modules.tresorerie?.budget_tracking ?? true} onChange={v => patchMod('tresorerie', { budget_tracking: v })} disabled={!modules.tresorerie?.enabled} />
            <SubToggle label="Rapprochement bancaire" desc="Correspondance relevés / comptabilité" checked={modules.tresorerie?.reconciliation ?? true} onChange={v => patchMod('tresorerie', { reconciliation: v })} disabled={!modules.tresorerie?.enabled} />
            <SubToggle label="Exports" desc="Export CSV/Excel/PDF des données" checked={modules.tresorerie?.exports ?? true} onChange={v => patchMod('tresorerie', { exports: v })} disabled={!modules.tresorerie?.enabled} />
          </div>
        </ModuleTab>
      )}

      {/* ── Tab: RH ── */}
      {activeTab === 'rh' && (
        <ModuleTab
          title="Module Ressources Humaines"
          description="Gestion du personnel : employés, congés, contrats, paie, recrutement."
          color="#f59e0b"
          enabled={modules.rh?.enabled ?? false}
          onToggle={v => patchMod('rh', { enabled: v })}
        >
          <QuotaRow
            label="Limite d'employés"
            hint="0 = illimité"
            value={modules.rh?.max_employees ?? 0}
            unlimited={(modules.rh?.max_employees ?? 0) === 0}
            min={1}
            disabled={!modules.rh?.enabled}
            onChangeValue={v => patchMod('rh', { max_employees: v })}
            onChangeUnlimited={u => patchMod('rh', { max_employees: u ? 0 : 100 })}
          />
          <div className={styles.subGrid}>
            <SubToggle label="Gestion des congés" desc="Demandes, validation, soldes, calendrier" checked={modules.rh?.leave_management ?? true} onChange={v => patchMod('rh', { leave_management: v })} disabled={!modules.rh?.enabled} />
            <SubToggle label="Suivi des contrats" desc="CDD, CDI, alertes d'expiration" checked={modules.rh?.contract_tracking ?? true} onChange={v => patchMod('rh', { contract_tracking: v })} disabled={!modules.rh?.enabled} />
            <SubToggle label="Module Paie" desc="Calcul salaires, fiches de paie" checked={modules.rh?.payroll ?? false} onChange={v => patchMod('rh', { payroll: v })} disabled={!modules.rh?.enabled} />
            <SubToggle label="Recrutement" desc="Offres d'emploi, candidatures, entretiens" checked={modules.rh?.recruitment ?? false} onChange={v => patchMod('rh', { recruitment: v })} disabled={!modules.rh?.enabled} />
            <SubToggle label="Évaluations de performance" desc="Objectifs, entretiens annuels" checked={modules.rh?.performance_reviews ?? false} onChange={v => patchMod('rh', { performance_reviews: v })} disabled={!modules.rh?.enabled} />
            <SubToggle label="Formation" desc="Plan de formation, suivi des sessions" checked={modules.rh?.training ?? false} onChange={v => patchMod('rh', { training: v })} disabled={!modules.rh?.enabled} />
          </div>
        </ModuleTab>
      )}

      {/* ── Tab: Secrétariat ── */}
      {activeTab === 'secretariat' && (
        <ModuleTab
          title="Module Secrétariat"
          description="Gestion documentaire, réunions, agenda, courrier IA, approbations."
          color="#7c3aed"
          enabled={modules.secretariat?.enabled ?? false}
          onToggle={v => patchMod('secretariat', { enabled: v })}
        >
          <div className={styles.subGrid}>
            <SubToggle label="Gestion documentaire" desc="Archivage, catégories, recherche, versions" checked={modules.secretariat?.documents ?? true} onChange={v => patchMod('secretariat', { documents: v })} disabled={!modules.secretariat?.enabled} />
            <SubToggle label="Réunions & PV" desc="Planification, ordre du jour, procès-verbaux IA" checked={modules.secretariat?.meetings ?? true} onChange={v => patchMod('secretariat', { meetings: v })} disabled={!modules.secretariat?.enabled} />
            <SubToggle label="Agenda & échéances" desc="Rappels, tâches, suivi des deadlines" checked={modules.secretariat?.agenda ?? true} onChange={v => patchMod('secretariat', { agenda: v })} disabled={!modules.secretariat?.enabled} />
            <SubToggle label="Analyse courrier IA" desc="Résumé, classification et réponse automatique des mails" checked={modules.secretariat?.ai_mail ?? true} onChange={v => patchMod('secretariat', { ai_mail: v })} disabled={!modules.secretariat?.enabled} />
            <SubToggle label="Workflow d'approbations" desc="Validation des documents et décisions" checked={modules.secretariat?.approvals ?? true} onChange={v => patchMod('secretariat', { approvals: v })} disabled={!modules.secretariat?.enabled} />
          </div>
          <div className={styles.quotasMinor}>
            <QuotaRow
              label="Limite de documents"
              hint="0 = illimité"
              value={modules.secretariat?.max_documents ?? 0}
              unlimited={(modules.secretariat?.max_documents ?? 0) === 0}
              min={10}
              disabled={!modules.secretariat?.enabled}
              onChangeValue={v => patchMod('secretariat', { max_documents: v })}
              onChangeUnlimited={u => patchMod('secretariat', { max_documents: u ? 0 : 500 })}
            />
            <QuotaRow
              label="Réunions par mois"
              hint="0 = illimité"
              value={modules.secretariat?.max_meetings_per_month ?? 0}
              unlimited={(modules.secretariat?.max_meetings_per_month ?? 0) === 0}
              min={1}
              disabled={!modules.secretariat?.enabled}
              onChangeValue={v => patchMod('secretariat', { max_meetings_per_month: v })}
              onChangeUnlimited={u => patchMod('secretariat', { max_meetings_per_month: u ? 0 : 10 })}
            />
          </div>
        </ModuleTab>
      )}

      {/* ── Tab: Thème ── */}
      {activeTab === 'theme' && (
        <div className={styles.tabContent}>
          <p className={styles.sectionDesc}>Couleurs de l'interface pour cette province.</p>
          <div className={styles.colorGrid}>
            <ColorField label="Couleur principale" value={settings.theme_primary_color} onChange={v => patch({ theme_primary_color: v })} />
            <ColorField label="Sidebar fond" value={settings.theme_sidebar_color} onChange={v => patch({ theme_sidebar_color: v })} />
            <ColorField label="Sidebar texte" value={settings.theme_sidebar_text_color} onChange={v => patch({ theme_sidebar_text_color: v })} />
            <ColorField label="Sidebar actif" value={settings.theme_sidebar_active_color} onChange={v => patch({ theme_sidebar_active_color: v })} />
            <ColorField label="Accent" value={settings.theme_accent_color} onChange={v => patch({ theme_accent_color: v })} />
            <ColorField label="Texte" value={settings.theme_text_color} onChange={v => patch({ theme_text_color: v })} />
            <ColorField label="Texte boutons" value={settings.theme_button_text_color} onChange={v => patch({ theme_button_text_color: v })} />
          </div>
          <div className={styles.themePreview} style={{
            background: settings.theme_sidebar_color,
            borderRadius: 12,
            padding: '16px 20px',
            marginTop: 16,
            display: 'flex',
            gap: 12,
            alignItems: 'center',
          }}>
            <div style={{ width: 12, height: 12, borderRadius: 3, background: settings.theme_primary_color }} />
            <span style={{ color: settings.theme_sidebar_text_color, fontWeight: 600, fontSize: 13 }}>Aperçu sidebar</span>
            <div style={{ marginLeft: 'auto', background: settings.theme_accent_color, borderRadius: 6, padding: '2px 10px' }}>
              <span style={{ color: settings.theme_button_text_color, fontSize: 12, fontWeight: 700 }}>Bouton</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sous-composants ───────────────────────────────────────────────────────────

interface QuotaRowProps {
  label: string
  hint?: string
  value: number
  unlimited: boolean
  min?: number
  disabled?: boolean
  onChangeValue: (v: number) => void
  onChangeUnlimited: (u: boolean) => void
}

function QuotaRow({ label, hint, value, unlimited, min = 1, disabled, onChangeValue, onChangeUnlimited }: QuotaRowProps) {
  return (
    <div className={`${styles.quotaRow} ${disabled ? styles.disabled : ''}`}>
      <div className={styles.quotaHeader}>
        <div>
          <span>{label}</span>
          {hint && <span className={styles.hint}>{hint}</span>}
        </div>
        <span className={styles.quotaValue}>{unlimited ? 'Illimité' : value}</span>
      </div>
      <div className={styles.quotaControls}>
        <input
          type="number"
          className={styles.numInput}
          min={min}
          value={unlimited ? '' : value}
          disabled={unlimited || disabled}
          onChange={e => {
            const v = parseInt(e.target.value, 10)
            if (Number.isFinite(v)) onChangeValue(Math.max(min, v))
          }}
        />
        <label className={styles.inlineToggle}>
          <input type="checkbox" checked={unlimited} disabled={disabled} onChange={e => onChangeUnlimited(e.target.checked)} />
          Illimité
        </label>
      </div>
    </div>
  )
}

interface ToggleCardProps {
  title: string
  description: string
  checked: boolean
  onChange: (v: boolean) => void
  color?: string
}

function ToggleCard({ title, description, checked, onChange, color = '#00a09d' }: ToggleCardProps) {
  return (
    <div className={`${styles.toggleCard} ${checked ? styles.toggleActive : ''}`}
      style={checked ? { borderColor: `${color}44`, background: `${color}08` } : undefined}>
      <div className={styles.toggleLeft}>
        <div className={styles.toggleDot} style={{ background: checked ? color : '#d1d5db' }} />
        <div>
          <p className={styles.toggleTitle}>{title}</p>
          <p className={styles.toggleDescription}>{description}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`${styles.toggleButton} ${checked ? styles.toggleOn : styles.toggleOff}`}
        style={checked ? { background: color } : undefined}
        aria-pressed={checked}
      >
        <span className={`${styles.toggleKnob} ${checked ? styles.knobOn : styles.knobOff}`} />
      </button>
    </div>
  )
}

interface ModuleTabProps {
  title: string
  description: string
  color: string
  enabled: boolean
  onToggle: (v: boolean) => void
  alwaysOn?: boolean
  children?: React.ReactNode
}

function ModuleTab({ title, description, color, enabled, onToggle, alwaysOn, children }: ModuleTabProps) {
  return (
    <div className={styles.tabContent}>
      <div className={styles.moduleHeader} style={{ borderLeft: `4px solid ${color}` }}>
        <div>
          <h3 className={styles.moduleTitle} style={{ color }}>{title}</h3>
          <p className={styles.sectionDesc}>{description}</p>
        </div>
        {!alwaysOn && (
          <div className={styles.moduleToggleWrap}>
            <span className={styles.moduleToggleLabel}>{enabled ? 'Activé' : 'Désactivé'}</span>
            <button
              type="button"
              onClick={() => onToggle(!enabled)}
              className={`${styles.toggleButton} ${enabled ? styles.toggleOn : styles.toggleOff}`}
              style={enabled ? { background: color } : undefined}
              aria-pressed={enabled}
            >
              <span className={`${styles.toggleKnob} ${enabled ? styles.knobOn : styles.knobOff}`} />
            </button>
          </div>
        )}
      </div>
      {!enabled && !alwaysOn ? (
        <div className={styles.disabledOverlay}>
          Module désactivé — activez-le pour configurer ses fonctionnalités.
        </div>
      ) : (
        children
      )}
    </div>
  )
}

interface SubToggleProps {
  label: string
  desc: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}

function SubToggle({ label, desc, checked, onChange, disabled }: SubToggleProps) {
  return (
    <div className={`${styles.subToggle} ${disabled ? styles.disabled : ''} ${checked && !disabled ? styles.subToggleOn : ''}`}>
      <label className={styles.subToggleLabel}>
        <input
          type="checkbox"
          className={styles.subCheckbox}
          checked={checked}
          disabled={disabled}
          onChange={e => onChange(e.target.checked)}
        />
        <div>
          <span className={styles.subToggleTitle}>{label}</span>
          <span className={styles.subToggleDesc}>{desc}</span>
        </div>
      </label>
    </div>
  )
}

interface ColorFieldProps {
  label: string
  value: string
  onChange: (v: string) => void
}

function ColorField({ label, value, onChange }: ColorFieldProps) {
  return (
    <label className={styles.colorField}>
      <span className={styles.colorLabel}>{label}</span>
      <div className={styles.colorInputRow}>
        <input type="color" className={styles.colorPicker} value={value} onChange={e => onChange(e.target.value)} />
        <input
          type="text"
          className={styles.colorText}
          value={value}
          maxLength={7}
          onChange={e => {
            const v = e.target.value
            if (/^#[0-9a-fA-F]{0,6}$/.test(v)) onChange(v)
          }}
        />
      </div>
    </label>
  )
}
