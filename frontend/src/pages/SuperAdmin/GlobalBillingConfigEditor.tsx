import { useEffect, useMemo, useState } from 'react'
import { Save } from 'lucide-react'
import {
  getGlobalBillingConfig,
  updateGlobalBillingConfig,
  applyGlobalBillingConfig,
  type BillingConfig,
} from '../../api/superAdmin'
import { useNotification } from '../../contexts/NotificationContext'
import { useConfirm } from '../../contexts/ConfirmContext'
import styles from './BillingConfigEditor.module.css'

type BankConfig = NonNullable<NonNullable<BillingConfig['payment_methods']>['bank']>
type MobileMoneyConfig = NonNullable<NonNullable<BillingConfig['payment_methods']>['mobile_money']>
type AggregatorConfig = NonNullable<NonNullable<BillingConfig['platform_payments']>['epaielink']>

// Le montant d'une transaction est contraint a USD/CDF par le modele
// PaymentTransaction : proposer autre chose ferait echouer le paiement.
const CURRENCIES = ['USD', 'CDF'] as const

// _interval_to_months() cote backend ne reconnait que ces valeurs et retombe
// silencieusement sur 1 mois pour tout le reste.
const INTERVALS = [
  { value: 'monthly', label: 'Mensuel (1 mois)' },
  { value: 'quarterly', label: 'Trimestriel (3 mois)' },
  { value: 'semiannual', label: 'Semestriel (6 mois)' },
  { value: 'yearly', label: 'Annuel (12 mois)' },
] as const

const defaultConfig: BillingConfig = {
  plan: { name: '', price: null, currency: 'USD', interval: 'monthly' },
  payment_methods: {
    bank: {
      enabled: true,
      bank_name: '',
      account_name: '',
      account_number: '',
      swift_code: '',
    },
    mobile_money: {
      enabled: true,
      provider: '',
      merchant_number: '',
      instructions: '',
    },
  },
  platform_payments: {
    epaielink: { site_id: '', api_key: '', notify_url: '', return_url: '' },
  },
  support_contact: '',
  billing_portal_url: '',
}

function normalize(res: BillingConfig | null | undefined): BillingConfig {
  return {
    ...defaultConfig,
    ...res,
    plan: { ...defaultConfig.plan, ...(res?.plan || {}) },
    payment_methods: {
      bank: { ...defaultConfig.payment_methods?.bank, ...(res?.payment_methods?.bank || {}) },
      mobile_money: {
        ...defaultConfig.payment_methods?.mobile_money,
        ...(res?.payment_methods?.mobile_money || {}),
      },
    },
    platform_payments: {
      epaielink: {
        ...defaultConfig.platform_payments?.epaielink,
        ...(res?.platform_payments?.epaielink || {}),
        // La cle n'est jamais renvoyee par le backend : le champ reste vide et
        // ne sera envoye que si le super admin en saisit une nouvelle.
        api_key: '',
      },
    },
  }
}

type Props = {
  /** Nombre de tenants, pour annoncer la portee de « Appliquer à tous ». */
  tenantCount?: number
}

export default function GlobalBillingConfigEditor({ tenantCount }: Props) {
  const [config, setConfig] = useState<BillingConfig>(defaultConfig)
  const [apiKeyStored, setApiKeyStored] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyMode, setApplyMode] = useState<'fill' | 'overwrite'>('fill')
  const [dirty, setDirty] = useState(false)
  const { showSuccess, showError } = useNotification()
  const confirm = useConfirm()

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const res = await getGlobalBillingConfig()
        if (active) {
          setConfig(normalize(res))
          setApiKeyStored(!!res?.platform_payments?.epaielink?.api_key_set)
          setDirty(false)
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [])

  // Mises a jour ciblees : evite de repeter le spread complet a chaque champ.
  const patch = (values: Partial<BillingConfig>) => {
    setConfig((prev) => ({ ...prev, ...values }))
    setDirty(true)
  }
  const patchPlan = (values: Partial<NonNullable<BillingConfig['plan']>>) => {
    setConfig((prev) => ({ ...prev, plan: { ...prev.plan, ...values } }))
    setDirty(true)
  }
  const patchBank = (values: Partial<BankConfig>) => {
    setConfig((prev) => ({
      ...prev,
      payment_methods: { ...prev.payment_methods, bank: { ...prev.payment_methods?.bank, ...values } },
    }))
    setDirty(true)
  }
  const patchMomo = (values: Partial<MobileMoneyConfig>) => {
    setConfig((prev) => ({
      ...prev,
      payment_methods: {
        ...prev.payment_methods,
        mobile_money: { ...prev.payment_methods?.mobile_money, ...values },
      },
    }))
    setDirty(true)
  }
  const patchAggregator = (values: Partial<AggregatorConfig>) => {
    setConfig((prev) => ({
      ...prev,
      platform_payments: {
        ...prev.platform_payments,
        epaielink: { ...prev.platform_payments?.epaielink, ...values },
      },
    }))
    setDirty(true)
  }

  const aggregator = config.platform_payments?.epaielink
  const hasSiteId = !!aggregator?.site_id?.trim()
  const hasApiKey = apiKeyStored || !!aggregator?.api_key?.trim()
  const hasPlanPrice = config.plan?.price != null && config.plan.price > 0

  // Ce qui bloque reellement l'encaissement, dit avant que le super admin
  // ne decouvre l'erreur par un paiement echoue.
  const blockers = useMemo(() => {
    const items: string[] = []
    if (!config.plan?.name?.trim()) items.push('Nom du plan manquant')
    if (!hasPlanPrice) items.push('Prix du plan non défini')
    if (!hasSiteId) items.push("Identifiant de site de l'agrégateur manquant")
    if (!hasApiKey) items.push("Clé d'API de l'agrégateur manquante")
    return items
  }, [config.plan?.name, hasPlanPrice, hasSiteId, hasApiKey])

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload: BillingConfig = { ...config }
      // Ne pas transmettre une cle vide : le backend interpreterait mal
      // l'intention. Champ vide = « garder la cle existante ».
      if (!aggregator?.api_key?.trim()) {
        payload.platform_payments = {
          epaielink: { ...aggregator, api_key: undefined },
        }
      }
      const res = await updateGlobalBillingConfig(payload)
      setConfig(normalize(res))
      setApiKeyStored(!!res?.platform_payments?.epaielink?.api_key_set)
      setDirty(false)
      showSuccess('Configuration globale sauvegardée', 'Les valeurs par défaut sont à jour.')
      return true
    } catch (err: any) {
      showError('Sauvegarde impossible', err?.message || 'Erreur inconnue')
      return false
    } finally {
      setSaving(false)
    }
  }

  const handleApplyToAll = async () => {
    const overwrite = applyMode === 'overwrite'
    const scope =
      tenantCount && tenantCount > 0
        ? `${tenantCount} organisation${tenantCount > 1 ? 's' : ''}`
        : 'toutes les organisations'
    const confirmed = await confirm({
      title: overwrite ? `Écraser la configuration de ${scope} ?` : `Compléter ${scope} ?`,
      description: overwrite
        ? `Chaque organisation perdra sa configuration locale (plan, portail, moyens de paiement) au profit de la configuration globale. Action irréversible.`
        : `Les valeurs absentes seront renseignées depuis la configuration globale. Les valeurs déjà définies localement par une organisation ne seront pas modifiées.`,
      confirmText: overwrite ? 'Écraser' : 'Compléter',
      cancelText: 'Annuler',
      variant: overwrite ? 'danger' : 'default',
    })
    if (!confirmed) return
    setApplying(true)
    try {
      const saved = dirty ? await handleSave() : true
      if (!saved) return
      const res = await applyGlobalBillingConfig(overwrite)
      const applied = res?.applied ?? 0
      showSuccess(
        'Configuration appliquée',
        applied === 0
          ? 'Aucune organisation ne nécessitait de mise à jour.'
          : `${applied} organisation${applied > 1 ? 's' : ''} mise${applied > 1 ? 's' : ''} à jour.`
      )
    } catch (err: any) {
      showError('Application impossible', err?.message || 'Erreur inconnue')
    } finally {
      setApplying(false)
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement configuration globale...</div>
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div>
          <h2>Facturation globale (console)</h2>
          <p>Valeurs par défaut appliquées aux organisations qui n'ont pas de réglage propre.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className={styles.saveButton} onClick={handleSave} disabled={saving}>
            <Save size={18} />
            {saving ? 'Enregistrement...' : 'Sauvegarder'}
          </button>
          <div className={styles.applyGroup}>
            <select
              className={styles.applySelect}
              value={applyMode}
              onChange={(e) => setApplyMode(e.target.value as 'fill' | 'overwrite')}
              disabled={applying}
            >
              <option value="fill">Compléter les valeurs manquantes</option>
              <option value="overwrite">Écraser la configuration locale</option>
            </select>
            <button
              type="button"
              className={applyMode === 'overwrite' ? styles.dangerButton : styles.secondaryButton}
              onClick={handleApplyToAll}
              disabled={saving || applying}
            >
              {applying ? 'Application...' : 'Appliquer à tous'}
            </button>
          </div>
        </div>
      </div>

      {blockers.length > 0 && (
        <div className={styles.blockers}>
          <strong>Encaissement impossible en l'état :</strong>
          <ul>
            {blockers.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.grid}>
        <section className={styles.section}>
          <h3>Plan</h3>
          <p className={styles.sectionHint}>Montant prélevé à chaque échéance d'abonnement.</p>
          <div className={styles.fieldRow}>
            <label>
              Nom
              <input
                type="text"
                value={config.plan?.name || ''}
                onChange={(e) => patchPlan({ name: e.target.value })}
                placeholder="Premium Provincial"
              />
            </label>
            <label>
              Prix
              <input
                type="number"
                step="0.01"
                min="0"
                value={config.plan?.price ?? ''}
                onChange={(e) =>
                  patchPlan({ price: e.target.value === '' ? null : Number(e.target.value) })
                }
              />
            </label>
          </div>
          <div className={styles.fieldRow}>
            <label>
              Devise
              <select
                value={config.plan?.currency || 'USD'}
                onChange={(e) => patchPlan({ currency: e.target.value })}
              >
                {CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Cycle
              <select
                value={config.plan?.interval || 'monthly'}
                onChange={(e) => patchPlan({ interval: e.target.value })}
              >
                {INTERVALS.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className={`${styles.section} ${styles.sectionPrimary}`}>
          <h3>Agrégateur de paiement</h3>
          <p className={styles.sectionHint}>
            Identifiants ePaieLink de la plateforme. Sans eux, ni le paiement par carte ni le Mobile
            Money ne peuvent aboutir.
          </p>
          <div className={styles.fieldRow}>
            <label>
              Identifiant de site
              <input
                type="text"
                value={aggregator?.site_id || ''}
                onChange={(e) => patchAggregator({ site_id: e.target.value })}
                placeholder="site_xxxxx"
              />
            </label>
            <label>
              Clé d'API
              <input
                type="password"
                autoComplete="new-password"
                value={aggregator?.api_key || ''}
                onChange={(e) => patchAggregator({ api_key: e.target.value })}
                placeholder={apiKeyStored ? '•••••••• (enregistrée)' : 'Aucune clé enregistrée'}
              />
              <span className={styles.fieldHint}>
                {apiKeyStored
                  ? 'Laissez vide pour conserver la clé actuelle.'
                  : "Aucune clé enregistrée pour le moment."}
              </span>
            </label>
          </div>
          <div className={styles.fieldRow}>
            <label>
              URL de notification (webhook)
              <input
                type="text"
                value={aggregator?.notify_url || ''}
                onChange={(e) => patchAggregator({ notify_url: e.target.value })}
                placeholder="https://api.onec-rdc.org/api/v1/online-payments/webhook/epaielink"
              />
            </label>
            <label>
              URL de retour
              <input
                type="text"
                value={aggregator?.return_url || ''}
                onChange={(e) => patchAggregator({ return_url: e.target.value })}
                placeholder="https://pay.onec-rdc.org/retour"
              />
            </label>
          </div>
        </section>

        <section className={styles.section}>
          <h3>Contact et portail</h3>
          <p className={styles.sectionHint}>
            Affichés aux organisations quand le paiement en ligne n'est pas disponible.
          </p>
          <label>
            URL portail
            <input
              type="text"
              value={config.billing_portal_url || ''}
              onChange={(e) => patch({ billing_portal_url: e.target.value })}
              placeholder="https://pay.onec-rdc.org"
            />
          </label>
          <label>
            Contact support
            <input
              type="text"
              value={config.support_contact || ''}
              onChange={(e) => patch({ support_contact: e.target.value })}
              placeholder="support@onec-rdc.org"
            />
          </label>
        </section>

        <section className={styles.section}>
          <h3>Mobile Money</h3>
          <p className={styles.sectionHint}>
            Le débit passe par l'agrégateur. Le numéro marchand n'est utilisé que sur la page de
            paiement hébergée, jamais affiché dans l'application des organisations.
          </p>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={config.payment_methods?.mobile_money?.enabled ?? true}
              onChange={(e) => patchMomo({ enabled: e.target.checked })}
            />
            Activer Mobile Money
          </label>
          <div className={styles.fieldRow}>
            <label>
              Opérateur
              <input
                type="text"
                value={config.payment_methods?.mobile_money?.provider || ''}
                onChange={(e) => patchMomo({ provider: e.target.value })}
                placeholder="mpesa"
              />
            </label>
            <label>
              Numéro marchand
              <input
                type="text"
                value={config.payment_methods?.mobile_money?.merchant_number || ''}
                onChange={(e) => patchMomo({ merchant_number: e.target.value })}
              />
            </label>
          </div>
          <label>
            Instructions
            <textarea
              rows={3}
              value={config.payment_methods?.mobile_money?.instructions || ''}
              onChange={(e) => patchMomo({ instructions: e.target.value })}
              placeholder="Texte affiché au-dessus du champ de saisie du numéro."
            />
          </label>
        </section>

        <section className={styles.section}>
          <h3>Virement bancaire</h3>
          <p className={styles.sectionHint}>
            Coordonnées présentées sur la page de paiement hébergée, où l'organisation dépose sa
            preuve de virement. Elles ne sont jamais affichées dans l'application.
          </p>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={config.payment_methods?.bank?.enabled ?? true}
              onChange={(e) => patchBank({ enabled: e.target.checked })}
            />
            Activer le virement bancaire
          </label>
          <div className={styles.fieldRow}>
            <label>
              Banque
              <input
                type="text"
                value={config.payment_methods?.bank?.bank_name || ''}
                onChange={(e) => patchBank({ bank_name: e.target.value })}
              />
            </label>
            <label>
              Nom du compte
              <input
                type="text"
                value={config.payment_methods?.bank?.account_name || ''}
                onChange={(e) => patchBank({ account_name: e.target.value })}
              />
            </label>
          </div>
          <div className={styles.fieldRow}>
            <label>
              Numéro de compte
              <input
                type="text"
                value={config.payment_methods?.bank?.account_number || ''}
                onChange={(e) => patchBank({ account_number: e.target.value })}
              />
            </label>
            <label>
              SWIFT
              <input
                type="text"
                value={config.payment_methods?.bank?.swift_code || ''}
                onChange={(e) => {
                  const value = e.target.value.trim()
                  patchBank({ swift_code: value === '' ? null : value })
                }}
              />
            </label>
          </div>
        </section>
      </div>

      {dirty && <div className={styles.dirtyHint}>Modifications en attente de sauvegarde.</div>}
    </div>
  )
}
