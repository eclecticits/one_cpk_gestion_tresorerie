import { useEffect, useMemo, useState } from 'react'
import { Building2, Plus, CreditCard, Pencil, Ban } from 'lucide-react'
import {
  createBanque,
  listBanques,
  listComptesBancaires,
  updateBanque,
  updateCompteBancaire,
} from '../../api/banques'
import type { Banque, CompteBancaire } from '../../types/banque'
import { useNotification } from '../../contexts/NotificationContext'
import AddBankAccountModal from '../modals/AddBankAccountModal'
import styles from './BankSettings.module.css'

type BankFormState = {
  nom: string
  code: string
  is_active: boolean
}

const emptyBankForm: BankFormState = { nom: '', code: '', is_active: true }

export default function BankSettings() {
  const { showSuccess, showError, showWarning } = useNotification()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [banques, setBanques] = useState<Banque[]>([])
  const [comptes, setComptes] = useState<CompteBancaire[]>([])
  const [showBankForm, setShowBankForm] = useState(false)
  const [editingBankId, setEditingBankId] = useState<number | null>(null)
  const [bankForm, setBankForm] = useState<BankFormState>(emptyBankForm)
  const [activeBankForAccount, setActiveBankForAccount] = useState<Banque | null>(null)
  const [editingAccount, setEditingAccount] = useState<CompteBancaire | null>(null)

  const comptesByBank = useMemo(() => {
    const map = new Map<number, CompteBancaire[]>()
    comptes.forEach((compte) => {
      const bankId = Number(compte.banque_id)
      if (!map.has(bankId)) map.set(bankId, [])
      map.get(bankId)!.push(compte)
    })
    return map
  }, [comptes])

  const loadAll = async () => {
    try {
      setLoading(true)
      const [banquesRes, comptesRes] = await Promise.all([listBanques(), listComptesBancaires()])
      setBanques(Array.isArray(banquesRes) ? banquesRes : [])
      setComptes(Array.isArray(comptesRes) ? comptesRes : [])
    } catch (error: any) {
      console.error('Erreur chargement banques:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const resetBankForm = () => {
    setEditingBankId(null)
    setBankForm(emptyBankForm)
  }

  const resetAccountForm = () => {
    setEditingAccount(null)
    setActiveBankForAccount(null)
  }

  const handleSaveBank = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!bankForm.nom.trim()) {
      showWarning('Banques', 'Veuillez saisir le nom de la banque.')
      return
    }
    try {
      setSaving(true)
      const payload = {
        nom: bankForm.nom.trim(),
        code: bankForm.code.trim() || null,
        is_active: bankForm.is_active,
      }
      if (editingBankId) {
        await updateBanque(editingBankId, payload)
        showSuccess('Banques', 'Banque mise à jour.')
      } else {
        await createBanque(payload)
        showSuccess('Banques', 'Banque ajoutée.')
      }
      resetBankForm()
      setShowBankForm(false)
      await loadAll()
    } catch (error: any) {
      console.error('Erreur sauvegarde banque:', error)
      showError('Banques', error?.message || 'Impossible de sauvegarder la banque.')
    } finally {
      setSaving(false)
    }
  }

  const handleEditBank = (banque: Banque) => {
    setEditingBankId(banque.id)
    setBankForm({
      nom: banque.nom || '',
      code: banque.code || '',
      is_active: banque.is_active ?? true,
    })
    setShowBankForm(true)
  }

  const handleToggleBank = async (banque: Banque) => {
    try {
      setSaving(true)
      await updateBanque(banque.id, { is_active: !banque.is_active })
      await loadAll()
    } catch (error: any) {
      console.error('Erreur update banque:', error)
      showError('Banques', error?.message || 'Impossible de modifier le statut de la banque.')
    } finally {
      setSaving(false)
    }
  }

  const openAccountForm = (banque: Banque) => {
    setActiveBankForAccount(banque)
    setEditingAccount(null)
  }

  const handleEditAccount = (compte: CompteBancaire) => {
    setEditingAccount(compte)
    setActiveBankForAccount(compte.banque || banques.find((b) => b.id === compte.banque_id) || null)
  }

  const handleToggleAccount = async (compte: CompteBancaire) => {
    try {
      setSaving(true)
      await updateCompteBancaire(compte.id, { is_active: !compte.is_active })
      await loadAll()
    } catch (error: any) {
      console.error('Erreur update compte:', error)
      showError('Comptes bancaires', error?.message || 'Impossible de modifier le statut du compte.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div className={styles.title}>
          <Building2 size={20} />
          Gestion bancaire
        </div>
        <button
          type="button"
          className={styles.primaryBtn}
          onClick={() => {
            setShowBankForm(true)
            resetBankForm()
          }}
        >
          <Plus size={16} />
          Ajouter une banque
        </button>
      </div>

      {showBankForm && (
        <div className={styles.card}>
          <form onSubmit={handleSaveBank} className={styles.form}>
            <div className={styles.formRow}>
              <div className={styles.field}>
                <label>Nom *</label>
                <input
                  type="text"
                  value={bankForm.nom}
                  onChange={(e) => setBankForm({ ...bankForm, nom: e.target.value })}
                  placeholder="Ex: Rawbank"
                  required
                />
              </div>
              <div className={styles.field}>
                <label>Code SWIFT</label>
                <input
                  type="text"
                  value={bankForm.code}
                  onChange={(e) => setBankForm({ ...bankForm, code: e.target.value })}
                  placeholder="Optionnel"
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <label className={styles.checkbox}>
                <input
                  type="checkbox"
                  checked={bankForm.is_active}
                  onChange={(e) => setBankForm({ ...bankForm, is_active: e.target.checked })}
                />
                Banque active
              </label>
            </div>
            <div className={styles.actions}>
              <button type="submit" className={styles.primaryBtn} disabled={saving}>
                {saving ? 'Sauvegarde...' : editingBankId ? 'Mettre à jour' : 'Enregistrer'}
              </button>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => {
                  resetBankForm()
                  setShowBankForm(false)
                }}
              >
                Annuler
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className={styles.loading}>Chargement...</div>
      ) : banques.length === 0 ? (
        <div className={styles.empty}>Aucune banque enregistrée.</div>
      ) : (
        <div className={styles.grid}>
          {banques.map((banque) => {
            const accounts = comptesByBank.get(banque.id) || []
            return (
              <div key={banque.id} className={styles.bankCard}>
                <div className={styles.bankHeader}>
                  <div>
                    <div className={styles.bankName}>{banque.nom}</div>
                    <div className={styles.bankMeta}>
                      {banque.code ? `SWIFT: ${banque.code}` : 'SWIFT: —'}
                      <span className={banque.is_active ? styles.statusActive : styles.statusInactive}>
                        {banque.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                  <div className={styles.bankActions}>
                    <button
                      type="button"
                      className={styles.linkBtn}
                      onClick={() => openAccountForm(banque)}
                    >
                      <Plus size={14} />
                      Ajouter un compte
                    </button>
                    <button
                      type="button"
                      className={styles.ghostBtn}
                      onClick={() => handleEditBank(banque)}
                    >
                      <Pencil size={14} />
                      Modifier
                    </button>
                    <button
                      type="button"
                      className={styles.ghostBtn}
                      onClick={() => handleToggleBank(banque)}
                    >
                      <Ban size={14} />
                      {banque.is_active ? 'Désactiver' : 'Activer'}
                    </button>
                  </div>
                </div>

                {activeBankForAccount?.id === banque.id && (
                  <AddBankAccountModal
                    banqueId={banque.id}
                    banqueNom={banque.nom}
                    account={editingAccount}
                    onClose={resetAccountForm}
                    onSuccess={loadAll}
                  />
                )}

                <div className={styles.accountList}>
                  {accounts.length === 0 ? (
                    <div className={styles.emptySmall}>Aucun compte bancaire.</div>
                  ) : (
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Compte</th>
                          <th>Devise</th>
                          <th>Solde actuel</th>
                          <th>Statut</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {accounts.map((compte) => (
                          <tr key={compte.id}>
                            <td>
                              <div className={styles.accountName}>
                                <CreditCard size={14} />
                                <div>
                                  <div className={styles.accountTitle}>{compte.intitule}</div>
                                  <div className={styles.accountNumber}>{compte.numero_compte}</div>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span
                                className={
                                  compte.devise === 'USD' ? styles.badgeUsd : styles.badgeCdf
                                }
                              >
                                {compte.devise}
                              </span>
                            </td>
                            <td>{compte.solde_actuel ?? '-'}</td>
                            <td>
                              <span className={compte.is_active ? styles.statusActive : styles.statusInactive}>
                                {compte.is_active ? 'Actif' : 'Inactif'}
                              </span>
                            </td>
                            <td>
                              <div className={styles.rowActions}>
                                <button type="button" className={styles.linkBtn} onClick={() => handleEditAccount(compte)}>
                                  Modifier
                                </button>
                                <button type="button" className={styles.linkBtn} onClick={() => handleToggleAccount(compte)}>
                                  {compte.is_active ? 'Désactiver' : 'Activer'}
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
