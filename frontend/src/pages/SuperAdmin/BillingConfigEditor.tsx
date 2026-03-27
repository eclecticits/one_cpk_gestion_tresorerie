import { useEffect, useState } from 'react'
import { Save, RotateCcw } from 'lucide-react'
import { getBillingConfig, updateBillingConfig, resetBillingConfig, type BillingConfig } from '../../api/superAdmin'
import { useConfirmWithInput } from '../../contexts/ConfirmContext'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './BillingConfigEditor.module.css'

type BillingConfigEditorProps = {
  orgId: number
}

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
  support_contact: '',
  billing_portal_url: '',
}

export default function BillingConfigEditor({ orgId }: BillingConfigEditorProps) {
  const [config, setConfig] = useState<BillingConfig>(defaultConfig)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const confirmWithInput = useConfirmWithInput()
  const { showSuccess, showError } = useNotification()

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const res = await getBillingConfig(orgId)
        if (active) {
          setConfig({
            ...defaultConfig,
            ...res,
            plan: { ...defaultConfig.plan, ...(res?.plan || {}) },
            payment_methods: {
              bank: { ...defaultConfig.payment_methods?.bank, ...(res?.payment_methods?.bank || {}) },
              mobile_money: { ...defaultConfig.payment_methods?.mobile_money, ...(res?.payment_methods?.mobile_money || {}) },
            },
          })
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
  }, [orgId])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await updateBillingConfig(orgId, config)
      setConfig({
        ...defaultConfig,
        ...res,
        plan: { ...defaultConfig.plan, ...(res?.plan || {}) },
        payment_methods: {
          bank: { ...defaultConfig.payment_methods?.bank, ...(res?.payment_methods?.bank || {}) },
          mobile_money: { ...defaultConfig.payment_methods?.mobile_money, ...(res?.payment_methods?.mobile_money || {}) },
        },
      })
      setDirty(false)
      showSuccess('Configuration sauvegardée', 'Les paramètres de facturation ont été mis à jour.')
    } catch (err: any) {
      showError('Sauvegarde impossible', err?.message || 'Erreur inconnue')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    const result = await confirmWithInput({
      title: 'Réinitialiser la facturation',
      description: 'Tapez RESET pour revenir à la configuration globale par défaut.',
      inputPlaceholder: 'RESET',
      confirmText: 'Réinitialiser',
      variant: 'danger',
    })
    if (!result.confirmed || result.value.toUpperCase() !== 'RESET') {
      return
    }
    setSaving(true)
    try {
      await resetBillingConfig(orgId)
      const res = await getBillingConfig(orgId)
      setConfig({
        ...defaultConfig,
        ...res,
        plan: { ...defaultConfig.plan, ...(res?.plan || {}) },
        payment_methods: {
          bank: { ...defaultConfig.payment_methods?.bank, ...(res?.payment_methods?.bank || {}) },
          mobile_money: { ...defaultConfig.payment_methods?.mobile_money, ...(res?.payment_methods?.mobile_money || {}) },
        },
      })
      setDirty(false)
      showSuccess('Configuration réinitialisée', 'La province hérite désormais des valeurs globales.')
    } catch (err: any) {
      showError('Réinitialisation impossible', err?.message || 'Erreur inconnue')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className={styles.loading}>Chargement facturation...</div>
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div>
          <h2>Facturation & Paiement (SaaS)</h2>
          <p>Configurez le prix et les instructions de paiement pour ce tenant.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className={styles.saveButton} onClick={handleSave} disabled={saving}>
            <Save size={18} />
            {saving ? 'Enregistrement...' : 'Sauvegarder'}
          </button>
          <button type="button" className={styles.secondaryButton} onClick={handleReset} disabled={saving}>
            <RotateCcw size={18} />
            Réinitialiser (hérite global)
          </button>
        </div>
      </div>

      <div className={styles.grid}>
        <section className={styles.section}>
          <h3>Plan</h3>
          <div className={styles.fieldRow}>
            <label>
              Nom
              <input
                type="text"
                value={config.plan?.name || ''}
                onChange={(e) => {
                  setConfig((prev) => ({ ...prev, plan: { ...prev.plan, name: e.target.value } }))
                  setDirty(true)
                }}
                placeholder="Premium Provincial"
              />
            </label>
            <label>
              Prix
              <input
                type="number"
                step="0.01"
                value={config.plan?.price ?? ''}
                onChange={(e) => {
                  const value = e.target.value === '' ? null : Number(e.target.value)
                  setConfig((prev) => ({ ...prev, plan: { ...prev.plan, price: value } }))
                  setDirty(true)
                }}
              />
            </label>
          </div>
          <div className={styles.fieldRow}>
            <label>
              Devise
              <input
                type="text"
                value={config.plan?.currency || ''}
                onChange={(e) => {
                  setConfig((prev) => ({ ...prev, plan: { ...prev.plan, currency: e.target.value } }))
                  setDirty(true)
                }}
                placeholder="USD"
              />
            </label>
            <label>
              Cycle
              <input
                type="text"
                value={config.plan?.interval || ''}
                onChange={(e) => {
                  setConfig((prev) => ({ ...prev, plan: { ...prev.plan, interval: e.target.value } }))
                  setDirty(true)
                }}
                placeholder="monthly"
              />
            </label>
          </div>
        </section>

        <section className={styles.section}>
          <h3>Portail</h3>
          <label>
            URL portail
            <input
              type="text"
              value={config.billing_portal_url || ''}
              onChange={(e) => {
                setConfig((prev) => ({ ...prev, billing_portal_url: e.target.value }))
                setDirty(true)
              }}
              placeholder="https://console-saas/tenants/slug/billing"
            />
          </label>
          <label>
            Support contact
            <input
              type="text"
              value={config.support_contact || ''}
              onChange={(e) => {
                setConfig((prev) => ({ ...prev, support_contact: e.target.value }))
                setDirty(true)
              }}
              placeholder="support@onec-rdc.org"
            />
          </label>
        </section>

        <section className={styles.section}>
          <h3>Virement bancaire</h3>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={config.payment_methods?.bank?.enabled ?? true}
              onChange={(e) => {
                setConfig((prev) => ({
                  ...prev,
                  payment_methods: {
                    ...prev.payment_methods,
                    bank: { ...prev.payment_methods?.bank, enabled: e.target.checked },
                  },
                }))
                setDirty(true)
              }}
            />
            Activer le virement bancaire
          </label>
          <div className={styles.fieldRow}>
            <label>
              Banque
              <input
                type="text"
                value={config.payment_methods?.bank?.bank_name || ''}
                onChange={(e) => {
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      bank: { ...prev.payment_methods?.bank, bank_name: e.target.value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
            <label>
              Nom du compte
              <input
                type="text"
                value={config.payment_methods?.bank?.account_name || ''}
                onChange={(e) => {
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      bank: { ...prev.payment_methods?.bank, account_name: e.target.value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
          </div>
          <div className={styles.fieldRow}>
            <label>
              Numéro de compte
              <input
                type="text"
                value={config.payment_methods?.bank?.account_number || ''}
                onChange={(e) => {
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      bank: { ...prev.payment_methods?.bank, account_number: e.target.value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
            <label>
              SWIFT
              <input
                type="text"
                value={config.payment_methods?.bank?.swift_code || ''}
                onChange={(e) => {
                  const value = e.target.value.trim()
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      bank: { ...prev.payment_methods?.bank, swift_code: value === '' ? null : value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
          </div>
        </section>

        <section className={styles.section}>
          <h3>Mobile Money</h3>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={config.payment_methods?.mobile_money?.enabled ?? true}
              onChange={(e) => {
                setConfig((prev) => ({
                  ...prev,
                  payment_methods: {
                    ...prev.payment_methods,
                    mobile_money: { ...prev.payment_methods?.mobile_money, enabled: e.target.checked },
                  },
                }))
                setDirty(true)
              }}
            />
            Activer Mobile Money
          </label>
          <div className={styles.fieldRow}>
            <label>
              Opérateur
              <input
                type="text"
                value={config.payment_methods?.mobile_money?.provider || ''}
                onChange={(e) => {
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      mobile_money: { ...prev.payment_methods?.mobile_money, provider: e.target.value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
            <label>
              Numéro marchand
              <input
                type="text"
                value={config.payment_methods?.mobile_money?.merchant_number || ''}
                onChange={(e) => {
                  setConfig((prev) => ({
                    ...prev,
                    payment_methods: {
                      ...prev.payment_methods,
                      mobile_money: { ...prev.payment_methods?.mobile_money, merchant_number: e.target.value },
                    },
                  }))
                  setDirty(true)
                }}
              />
            </label>
          </div>
          <label>
            Instructions
            <textarea
              rows={3}
              value={config.payment_methods?.mobile_money?.instructions || ''}
              onChange={(e) => {
                setConfig((prev) => ({
                  ...prev,
                  payment_methods: {
                    ...prev.payment_methods,
                    mobile_money: { ...prev.payment_methods?.mobile_money, instructions: e.target.value },
                  },
                }))
                setDirty(true)
              }}
            />
          </label>
        </section>
      </div>

      {dirty && <div className={styles.dirtyHint}>Modifications en attente de sauvegarde.</div>}
    </div>
  )
}
