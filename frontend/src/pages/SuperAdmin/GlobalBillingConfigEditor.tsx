import { useEffect, useState } from 'react'
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

export default function GlobalBillingConfigEditor() {
  const [config, setConfig] = useState<BillingConfig>(defaultConfig)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [applying, setApplying] = useState(false)
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
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await updateGlobalBillingConfig(config)
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
    const confirmed = await confirm({
      title: 'Appliquer à tous les tenants ?',
      description:
        "Cette action écrase la configuration locale de chaque tenant par la facturation globale (plan, portail, moyens de paiement).",
      confirmText: 'Appliquer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!confirmed) return
    setApplying(true)
    try {
      const saved = dirty ? await handleSave() : true
      if (!saved) return
      const res = await applyGlobalBillingConfig(true)
      showSuccess('Configuration appliquée', `${res?.applied ?? 0} tenants mis à jour.`)
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
          <p>Source de vérité par défaut appliquée à tous les tenants.</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" className={styles.saveButton} onClick={handleSave} disabled={saving}>
            <Save size={18} />
            {saving ? 'Enregistrement...' : 'Sauvegarder'}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={handleApplyToAll}
            disabled={saving || applying}
          >
            {applying ? 'Application...' : 'Appliquer à tous'}
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
              placeholder="https://pay.onec-rdc.org"
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
