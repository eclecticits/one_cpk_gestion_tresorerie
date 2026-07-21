import { useMemo, useState } from 'react'
import {
  updateWorkflowConfig,
  type WorkflowConfig,
  type WorkflowStepKey,
} from '../../api/organisation'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './WorkflowSettings.module.css'

const PRESETS: Record<string, Record<WorkflowStepKey, boolean>> = {
  complet: { signature_service: true, examen: true, validation_1: true, validation_2: true },
  standard: { signature_service: true, examen: false, validation_1: true, validation_2: true },
  simplifie: { signature_service: false, examen: false, validation_1: true, validation_2: true },
  express: { signature_service: false, examen: false, validation_1: true, validation_2: false },
}

const PRESET_LABELS: Record<string, string> = {
  complet: 'Complet',
  standard: 'Standard',
  simplifie: 'Simplifié',
  express: 'Express',
  personnalise: 'Personnalisé',
}

const STEP_LABELS: { key: WorkflowStepKey; label: string; hint: string; locked?: boolean }[] = [
  { key: 'signature_service', label: 'Signature service / commission', hint: 'Le service signe avant tout.' },
  { key: 'examen', label: "Examen", hint: "Soumission puis visa d'examen." },
  { key: 'validation_1', label: '1ʳᵉ validation (autorisation)', hint: 'Toujours obligatoire.', locked: true },
  { key: 'validation_2', label: '2ᵉ validation (visa final)', hint: 'Deuxième contrôle / visa.' },
]

const STEP_ORDER: WorkflowStepKey[] = ['signature_service', 'examen', 'validation_1', 'validation_2']

function detectPreset(steps: Record<WorkflowStepKey, boolean>, hasSeuil: boolean): string {
  if (hasSeuil) return 'personnalise'
  for (const [name, def] of Object.entries(PRESETS)) {
    if (STEP_ORDER.every((k) => def[k] === steps[k])) return name
  }
  return 'personnalise'
}

interface Props {
  initialConfig: WorkflowConfig | null
  canEdit: boolean
  /** Devise principale du tenant (ex. CDF, USD), affichée pour le seuil. */
  currency?: string
}

export default function WorkflowSettings({ initialConfig, canEdit, currency = 'USD' }: Props) {
  const { showError, showSuccess } = useNotification()
  const [saving, setSaving] = useState(false)

  const initial = useMemo<WorkflowConfig>(() => {
    const base: WorkflowConfig = {
      preset: 'complet',
      steps: {
        signature_service: { enabled: true },
        examen: { enabled: true },
        validation_1: { enabled: true },
        validation_2: { enabled: true },
      },
    }
    if (initialConfig?.steps) {
      for (const k of STEP_ORDER) {
        base.steps[k] = { ...base.steps[k], ...initialConfig.steps[k] }
      }
      base.preset = initialConfig.preset || base.preset
    }
    return base
  }, [initialConfig])

  const [steps, setSteps] = useState(() => ({
    signature_service: initial.steps.signature_service.enabled,
    examen: initial.steps.examen.enabled,
    validation_1: true,
    validation_2: initial.steps.validation_2.enabled,
  }))
  const [seuil, setSeuil] = useState<string>(
    initial.steps.validation_2.seuil_montant ? String(initial.steps.validation_2.seuil_montant) : ''
  )

  const preset = detectPreset(steps, !!seuil && steps.validation_2)

  const applyPreset = (name: string) => {
    if (!canEdit) return
    const def = PRESETS[name]
    if (!def) return
    setSteps({ ...def, validation_1: true })
    setSeuil('')
  }

  const toggle = (key: WorkflowStepKey) => {
    if (!canEdit || key === 'validation_1') return
    setSteps((s) => ({ ...s, [key]: !s[key] }))
  }

  const save = async () => {
    setSaving(true)
    try {
      const config: WorkflowConfig = {
        preset,
        steps: {
          signature_service: { enabled: steps.signature_service },
          examen: { enabled: steps.examen },
          validation_1: { enabled: true },
          validation_2: {
            enabled: steps.validation_2,
            ...(seuil && steps.validation_2 ? { seuil_montant: Number(seuil) } : {}),
          },
        },
      }
      await updateWorkflowConfig(config)
      showSuccess('Circuit de validation enregistré', 'Il s’appliquera aux nouvelles réquisitions.')
    } catch (e: any) {
      showError('Erreur', e?.message || "Impossible d'enregistrer le circuit.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.workflowCard}>
      <div className={styles.head}>
        <h2>Circuit de validation</h2>
        <p>
          Active ou désactive les étapes de validation des sorties de fonds. Le changement s’applique
          aux réquisitions <strong>créées après</strong> l’enregistrement (les dossiers en cours ne
          bougent pas).
        </p>
      </div>

      {!canEdit && (
        <div className={styles.lockNotice}>
          Seul le super administrateur peut modifier ce circuit. Affichage en lecture seule.
        </div>
      )}

      <div className={styles.presets}>
        <span className={styles.presetsLabel}>Modèle :</span>
        {Object.keys(PRESETS).map((name) => (
          <button
            key={name}
            type="button"
            className={`${styles.presetBtn} ${preset === name ? styles.presetActive : ''}`}
            onClick={() => applyPreset(name)}
            disabled={!canEdit}
          >
            {PRESET_LABELS[name]}
          </button>
        ))}
        {preset === 'personnalise' && <span className={styles.presetTag}>{PRESET_LABELS.personnalise}</span>}
      </div>

      <div className={styles.steps}>
        {STEP_LABELS.map(({ key, label, hint, locked }) => (
          <div key={key} className={styles.step}>
            <label className={styles.switch}>
              <input
                type="checkbox"
                checked={steps[key]}
                disabled={!canEdit || locked}
                onChange={() => toggle(key)}
              />
              <span className={styles.slider} />
            </label>
            <div className={styles.stepText}>
              <span className={styles.stepLabel}>
                {label}
                {locked && <span className={styles.badge}>obligatoire</span>}
              </span>
              <span className={styles.stepHint}>{hint}</span>
            </div>
            {key === 'validation_2' && steps.validation_2 && (
              <div className={styles.seuil}>
                <label>Seuil ({currency})</label>
                <input
                  type="number"
                  min={0}
                  placeholder="ex. 5000000"
                  value={seuil}
                  disabled={!canEdit}
                  onChange={(e) => setSeuil(e.target.value)}
                />
                <span className={styles.seuilHint}>
                  2ᵉ validation requise seulement au-dessus de ce montant, exprimé en {currency} (devise pivot — la devise de référence de l’application). Vide = toujours.
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {canEdit && (
        <div className={styles.actions}>
          <button type="button" className={styles.saveBtn} onClick={save} disabled={saving}>
            {saving ? 'Enregistrement…' : 'Enregistrer le circuit'}
          </button>
        </div>
      )}
    </div>
  )
}
