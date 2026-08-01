import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Landmark, Save, X } from 'lucide-react'
import { createCompteBancaire, updateCompteBancaire } from '../../api/banques'
import type { CompteBancaire } from '../../types/banque'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './AddBankAccountModal.module.css'

interface Props {
  banqueId: number
  banqueNom: string
  onClose: () => void
  onSuccess: () => void
  account?: CompteBancaire | null
}

export default function AddBankAccountModal({ banqueId, banqueNom, onClose, onSuccess, account }: Props) {
  const { showError } = useNotification()
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState({
    intitule: account?.intitule || '',
    numero_compte: account?.numero_compte || '',
    devise: (account?.devise as 'USD' | 'CDF') || 'USD',
    solde_initial: String(account?.solde_initial ?? 0),
    solde_actuel: account?.solde_actuel == null ? '' : String(account?.solde_actuel),
    is_active: account?.is_active ?? true,
  })

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', handleEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const payload = {
        banque_id: banqueId,
        intitule: formData.intitule.trim(),
        numero_compte: formData.numero_compte.trim(),
        devise: formData.devise,
        solde_initial: Number(formData.solde_initial || 0),
        solde_actuel: formData.solde_actuel === '' ? undefined : Number(formData.solde_actuel),
        is_active: formData.is_active,
      }
      if (account?.id) {
        await updateCompteBancaire(account.id, payload)
      } else {
        await createCompteBancaire(payload)
      }
      onSuccess()
      onClose()
    } catch (error: any) {
      console.error('Erreur lors de la création du compte', error)
      showError('Compte bancaire', error?.message || "Erreur lors de l'ajout du compte.")
    } finally {
      setLoading(false)
    }
  }

  const modal = (
    <div
      className={styles.overlay}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="bank-account-modal-title">
        <div className={styles.header}>
          <div className={styles.title}>
            <Landmark size={20} />
            <div className={styles.titleText}>
              <span id="bank-account-modal-title">
                {account ? 'Modifier le compte bancaire' : 'Nouveau compte bancaire'}
              </span>
              <small>{banqueNom}</small>
            </div>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.body}>
            <div className={styles.formGrid}>
              <div className={styles.field}>
                <label>Intitulé du compte</label>
                <input
                  required
                  type="text"
                  placeholder="Ex: Compte de recouvrement"
                  value={formData.intitule}
                  onChange={(e) => setFormData({ ...formData, intitule: e.target.value })}
                />
              </div>

              <div className={styles.field}>
                <label>Numéro de compte (RIB)</label>
                <input
                  required
                  type="text"
                  placeholder="00012-3456789-01"
                  className={styles.mono}
                  value={formData.numero_compte}
                  onChange={(e) => setFormData({ ...formData, numero_compte: e.target.value })}
                />
              </div>

              <div className={styles.field}>
                <label>Devise</label>
                <div className={styles.currencyRow}>
                  {(['USD', 'CDF'] as const).map((curr) => (
                    <label key={curr} className={styles.currencyOption}>
                      <input
                        type="radio"
                        name="devise"
                        value={curr}
                        checked={formData.devise === curr}
                        onChange={() => setFormData({ ...formData, devise: curr })}
                      />
                      <span className={formData.devise === curr ? styles.currencyActive : styles.currencyInactive}>
                        {curr}
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className={styles.field}>
                <label>Solde initial</label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.solde_initial}
                  onChange={(e) => setFormData({ ...formData, solde_initial: e.target.value })}
                />
              </div>

              <div className={styles.field}>
                <label>Solde actuel</label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.solde_actuel}
                  onChange={(e) => setFormData({ ...formData, solde_actuel: e.target.value })}
                />
              </div>

              <label className={styles.checkbox}>
                <input
                  type="checkbox"
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                />
                Compte actif
              </label>
            </div>
          </div>

          <div className={styles.footer}>
            <button type="button" className={styles.secondaryBtn} onClick={onClose}>
              Annuler
            </button>
            <button type="submit" className={styles.primaryBtn} disabled={loading}>
              {loading ? 'Enregistrement...' : (
                <>
                  <Save size={16} />
                  Enregistrer
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
