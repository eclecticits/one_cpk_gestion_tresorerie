import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, X } from 'lucide-react'
import { apiRequest } from '../../lib/apiClient'
import styles from './QuickRequisitionModal.module.css'

type BudgetLine = {
  id: number
  code: string
  libelle: string
  montant_disponible?: string | number
}

type Props = {
  isOpen: boolean
  onClose: () => void
  rubriques: BudgetLine[]
  serviceId: number
  onSuccess?: () => void
}

export default function QuickRequisitionModal({ isOpen, onClose, rubriques, serviceId, onSuccess }: Props) {
  const [objet, setObjet] = useState('')
  const [budgetPosteId, setBudgetPosteId] = useState<number | null>(null)
  const [description, setDescription] = useState('')
  const [quantite, setQuantite] = useState(1)
  const [montantUnitaire, setMontantUnitaire] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const selectedRubrique = useMemo(
    () => rubriques.find((r) => r.id === budgetPosteId) || null,
    [rubriques, budgetPosteId]
  )

  const montantTotal = Math.max(0, quantite * montantUnitaire)
  const disponible = selectedRubrique ? Number(selectedRubrique.montant_disponible || 0) : 0
  const soldeApres = selectedRubrique ? disponible - montantTotal : 0
  const isOverBudget = selectedRubrique ? montantTotal > disponible : false

  useEffect(() => {
    if (!isOpen) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleClose()
    }

    document.addEventListener('keydown', handleEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen])

  if (!isOpen) return null

  const reset = () => {
    setObjet('')
    setBudgetPosteId(null)
    setDescription('')
    setQuantite(1)
    setMontantUnitaire(0)
    setError('')
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleSubmit = async () => {
    if (!objet.trim() || !budgetPosteId || !description.trim() || montantTotal <= 0) {
      setError('Veuillez compléter tous les champs obligatoires.')
      return
    }
    if (isOverBudget) {
      setError('Budget insuffisant pour ce poste budgétaire.')
      return
    }
    setSaving(true)
    setError('')
    try {
      // Réquisition et ligne dans le même appel : un refus sur la ligne ne doit
      // pas laisser une réquisition vide derrière lui.
      await apiRequest('POST', '/requisitions', {
        objet: objet.trim(),
        mode_paiement: 'cash',
        type_requisition: 'classique',
        montant_total: montantTotal,
        service_id: serviceId,
        lignes: [
          {
            budget_poste_id: budgetPosteId,
            rubrique: selectedRubrique ? `${selectedRubrique.code} - ${selectedRubrique.libelle}` : '',
            description: description.trim(),
            quantite,
            montant_unitaire: montantUnitaire,
            montant_total: montantTotal,
            devise: 'USD',
          },
        ],
      })
      if (onSuccess) onSuccess()
      handleClose()
    } catch (err: any) {
      setError(err?.message || 'Impossible de créer la réquisition.')
    } finally {
      setSaving(false)
    }
  }

  const modal = (
    <div
      className={styles.overlay}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleClose()
      }}
    >
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="quick-requisition-title">
        <div className={styles.header}>
          <h2 id="quick-requisition-title">Nouvelle réquisition</h2>
          <button type="button" onClick={handleClose} className={styles.closeBtn} aria-label="Fermer">
            <X size={18} />
          </button>
        </div>

        <div className={styles.body}>
          {error && <div className={styles.error}>{error}</div>}
          <div className={styles.field}>
            <label>Objet *</label>
            <input
              type="text"
              value={objet}
              onChange={(e) => setObjet(e.target.value)}
              placeholder="Ex: Achat matériel formation"
            />
          </div>
          <div className={styles.field}>
            <label>Poste budgétaire *</label>
            <select
              value={budgetPosteId ?? ''}
              onChange={(e) => setBudgetPosteId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Sélectionner un poste budgétaire</option>
              {rubriques.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code} - {r.libelle}
                </option>
              ))}
            </select>
            {selectedRubrique && (
              <div className={styles.helper}>
                Disponible: {disponible.toLocaleString()} USD
              </div>
            )}
          </div>
          <div className={styles.field}>
            <label>Description *</label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Décrivez l’objet de la dépense"
            />
          </div>
          <div className={styles.row}>
            <div className={styles.field}>
              <label>Quantité *</label>
              <input
                type="number"
                value={quantite}
                min={1}
                onChange={(e) => setQuantite(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
            <div className={styles.field}>
              <label>Montant unitaire (USD) *</label>
              <input
                type="number"
                value={montantUnitaire}
                min={0}
                onChange={(e) => setMontantUnitaire(Math.max(0, Number(e.target.value) || 0))}
              />
            </div>
          </div>

          <div className={styles.totalRow}>
            <span>Total</span>
            <strong>{montantTotal.toLocaleString()} USD</strong>
          </div>

          {selectedRubrique && (
            <div className={`${styles.balanceBox} ${soldeApres < 0 ? styles.balanceBoxAlert : ''}`}>
              <div className={styles.balanceRow}>
                <span>Solde actuel</span>
                <strong>{disponible.toLocaleString()} USD</strong>
              </div>
              <div className={styles.balanceRow}>
                <span>Solde après opération</span>
                <strong className={soldeApres < 0 ? styles.balanceNegative : styles.balancePositive}>
                  {soldeApres.toLocaleString()} USD
                </strong>
              </div>
              {soldeApres < 0 && (
                <div className={styles.balanceHint}>
                  ⚠️ Dépassement de {Math.abs(soldeApres).toLocaleString()} USD.
                </div>
              )}
            </div>
          )}

          {isOverBudget && (
            <div className={styles.budgetAlert}>
              <AlertTriangle size={16} />
              Budget insuffisant : il vous reste {disponible.toLocaleString()} USD.
            </div>
          )}
        </div>

        <div className={styles.actions}>
          <button type="button" className={styles.secondary} onClick={handleClose}>
            Annuler
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={handleSubmit}
            disabled={saving || isOverBudget || montantTotal <= 0}
          >
            {saving ? 'Envoi…' : 'Soumettre'}
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}
