import { useEffect, useMemo, useState } from 'react'
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

type FormState = {
  intitule: string
  numero_compte: string
  rib: string
  identifiant_client: string
  code_swift_bic: string
  compte_comptable_associe: string
  journal_comptable_associe: string
  date_ouverture: string
  agence_bancaire: string
  devise: 'USD' | 'CDF'
  solde_initial: string
  is_active: boolean
  is_principal: boolean
  observations: string
}

type FieldErrors = Partial<Record<keyof FormState | 'banque', string>>

const cleanText = (value: string) => value.trim().replace(/\s+/g, ' ')
const optionalText = (value: string) => cleanText(value) || null

export default function AddBankAccountModal({ banqueId, banqueNom, onClose, onSuccess, account }: Props) {
  const { showError } = useNotification()
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [formData, setFormData] = useState<FormState>({
    intitule: account?.intitule || '',
    numero_compte: account?.numero_compte || '',
    rib: account?.rib || '',
    identifiant_client: account?.identifiant_client || '',
    code_swift_bic: account?.code_swift_bic || '',
    compte_comptable_associe: account?.compte_comptable_associe || '',
    journal_comptable_associe: account?.journal_comptable_associe || '',
    date_ouverture: account?.date_ouverture || '',
    agence_bancaire: account?.agence_bancaire || '',
    devise: (account?.devise as 'USD' | 'CDF') || 'USD',
    solde_initial: String(account?.solde_initial ?? 0),
    is_active: account?.is_active ?? true,
    is_principal: account?.is_principal ?? false,
    observations: account?.observations || '',
  })

  const soldeActuelLabel = useMemo(() => {
    if (account?.solde_actuel != null) return String(account.solde_actuel)
    return cleanText(formData.solde_initial) || '0'
  }, [account?.solde_actuel, formData.solde_initial])

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

  const updateField = <K extends keyof FormState>(field: K, value: FormState[K]) => {
    setFormData((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  const validate = () => {
    const nextErrors: FieldErrors = {}
    const soldeInitial = Number(formData.solde_initial)

    if (!banqueId) nextErrors.banque = 'Banque obligatoire.'
    if (!cleanText(formData.intitule)) nextErrors.intitule = 'Intitulé obligatoire.'
    if (!cleanText(formData.numero_compte)) nextErrors.numero_compte = 'Numéro de compte obligatoire.'
    if (!formData.devise) nextErrors.devise = 'Devise obligatoire.'
    if (formData.solde_initial === '' || Number.isNaN(soldeInitial) || soldeInitial < 0) {
      nextErrors.solde_initial = 'Solde initial numérique supérieur ou égal à zéro.'
    }

    setErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    setLoading(true)
    try {
      const swiftBic = optionalText(formData.code_swift_bic)
      const payload = {
        banque_id: banqueId,
        intitule: cleanText(formData.intitule),
        numero_compte: cleanText(formData.numero_compte),
        rib: optionalText(formData.rib),
        identifiant_client: optionalText(formData.identifiant_client),
        code_swift_bic: swiftBic ? swiftBic.toUpperCase() : null,
        compte_comptable_associe: optionalText(formData.compte_comptable_associe),
        journal_comptable_associe: optionalText(formData.journal_comptable_associe),
        date_ouverture: formData.date_ouverture || null,
        agence_bancaire: optionalText(formData.agence_bancaire),
        devise: formData.devise,
        solde_initial: Number(formData.solde_initial),
        is_active: formData.is_active,
        is_principal: formData.is_principal,
        observations: optionalText(formData.observations),
      }
      if (account?.id) {
        await updateCompteBancaire(account.id, payload)
      } else {
        await createCompteBancaire(payload)
      }
      onSuccess()
      onClose()
    } catch (error: any) {
      console.error('Erreur lors de la sauvegarde du compte bancaire', error)
      showError('Compte bancaire', error?.message || "Erreur lors de l'enregistrement du compte.")
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
            <section className={styles.section}>
              <h3>Identification bancaire</h3>
              <div className={styles.formGrid}>
                <div className={styles.field}>
                  <label>Banque <span>*</span></label>
                  <input type="text" value={banqueNom} disabled />
                  {errors.banque && <p className={styles.error}>{errors.banque}</p>}
                </div>
                <div className={styles.field}>
                  <label>Agence bancaire</label>
                  <input
                    type="text"
                    placeholder="Agence principale"
                    value={formData.agence_bancaire}
                    onChange={(e) => updateField('agence_bancaire', e.target.value)}
                  />
                  <p className={styles.help}>Agence ou guichet qui tient le compte.</p>
                </div>
                <div className={styles.field}>
                  <label>Intitulé du compte <span>*</span></label>
                  <input
                    required
                    type="text"
                    placeholder="ORDRE NATIONAL DES EXPERTS COMPTABLES"
                    value={formData.intitule}
                    onChange={(e) => updateField('intitule', e.target.value)}
                  />
                  {errors.intitule && <p className={styles.error}>{errors.intitule}</p>}
                </div>
                <div className={styles.field}>
                  <label>Identifiant client</label>
                  <input
                    type="text"
                    className={styles.mono}
                    placeholder="10729774"
                    value={formData.identifiant_client}
                    onChange={(e) => updateField('identifiant_client', e.target.value)}
                  />
                  <p className={styles.help}>Référence client fournie par la banque, distincte du numéro de compte.</p>
                </div>
              </div>
            </section>

            <section className={styles.section}>
              <h3>Coordonnées du compte</h3>
              <div className={styles.formGrid}>
                <div className={styles.field}>
                  <label>Numéro de compte <span>*</span></label>
                  <input
                    required
                    type="text"
                    placeholder="10000572352"
                    className={styles.mono}
                    value={formData.numero_compte}
                    onChange={(e) => updateField('numero_compte', e.target.value)}
                  />
                  {errors.numero_compte && <p className={styles.error}>{errors.numero_compte}</p>}
                </div>
                <div className={styles.field}>
                  <label>RIB</label>
                  <input
                    type="text"
                    placeholder="00017110001000057235224"
                    className={styles.mono}
                    value={formData.rib}
                    onChange={(e) => updateField('rib', e.target.value)}
                  />
                  <p className={styles.help}>Renseigner le RIB complet uniquement lorsqu'il est confirmé.</p>
                </div>
                <div className={styles.field}>
                  <label>Code SWIFT/BIC</label>
                  <input
                    type="text"
                    className={styles.mono}
                    placeholder="TRMSCD3L"
                    value={formData.code_swift_bic}
                    onChange={(e) => updateField('code_swift_bic', e.target.value.toUpperCase())}
                  />
                  <p className={styles.help}>Le code est normalisé automatiquement en majuscules.</p>
                </div>
                <div className={styles.field}>
                  <label>Devise <span>*</span></label>
                  <div className={styles.currencyRow}>
                    {(['USD', 'CDF'] as const).map((curr) => (
                      <label key={curr} className={styles.currencyOption}>
                        <input
                          type="radio"
                          name="devise"
                          value={curr}
                          checked={formData.devise === curr}
                          onChange={() => updateField('devise', curr)}
                        />
                        <span className={formData.devise === curr ? styles.currencyActive : styles.currencyInactive}>
                          {curr}
                        </span>
                      </label>
                    ))}
                  </div>
                  {errors.devise && <p className={styles.error}>{errors.devise}</p>}
                </div>
              </div>
            </section>

            <section className={styles.section}>
              <h3>Paramètres comptables</h3>
              <div className={styles.formGrid}>
                <div className={styles.field}>
                  <label>Compte comptable associé</label>
                  <input
                    type="text"
                    className={styles.mono}
                    placeholder="512"
                    value={formData.compte_comptable_associe}
                    onChange={(e) => updateField('compte_comptable_associe', e.target.value)}
                  />
                  <p className={styles.help}>Compte général utilisé pour les écritures de banque.</p>
                </div>
                <div className={styles.field}>
                  <label>Journal comptable associé</label>
                  <input
                    type="text"
                    className={styles.mono}
                    placeholder="BQUSD"
                    value={formData.journal_comptable_associe}
                    onChange={(e) => updateField('journal_comptable_associe', e.target.value)}
                  />
                  <p className={styles.help}>Code du journal comptable lié aux opérations du compte.</p>
                </div>
                <div className={styles.field}>
                  <label>Solde initial <span>*</span></label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={formData.solde_initial}
                    onChange={(e) => updateField('solde_initial', e.target.value)}
                  />
                  {errors.solde_initial && <p className={styles.error}>{errors.solde_initial}</p>}
                </div>
                <div className={styles.field}>
                  <label>Date d'ouverture du compte</label>
                  <input
                    type="date"
                    value={formData.date_ouverture}
                    onChange={(e) => updateField('date_ouverture', e.target.value)}
                  />
                </div>
                <div className={styles.field}>
                  <label>Solde actuel</label>
                  <input type="text" className={styles.mono} value={soldeActuelLabel} disabled />
                  <p className={styles.help}>Calculé depuis le solde initial et les opérations validées.</p>
                </div>
              </div>
            </section>

            <section className={styles.section}>
              <h3>Statut et gestion</h3>
              <div className={styles.formGrid}>
                <label className={styles.switchRow}>
                  <span>
                    Compte actif
                    <small>Disponible dans les opérations bancaires.</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={formData.is_active}
                    onChange={(e) => updateField('is_active', e.target.checked)}
                  />
                  <i aria-hidden="true" />
                </label>
                <label className={styles.switchRow}>
                  <span>
                    Compte principal
                    <small>Un seul compte principal par devise pour l'antenne.</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={formData.is_principal}
                    onChange={(e) => updateField('is_principal', e.target.checked)}
                  />
                  <i aria-hidden="true" />
                </label>
                <div className={`${styles.field} ${styles.fullWidth}`}>
                  <label>Observations</label>
                  <textarea
                    rows={3}
                    placeholder="Informations utiles pour l'identification ou le suivi du compte"
                    value={formData.observations}
                    onChange={(e) => updateField('observations', e.target.value)}
                  />
                </div>
              </div>
            </section>
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
