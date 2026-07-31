import { useState } from 'react'
import { X } from 'lucide-react'
import { contrepasserComptaEcriture, validerComptaEcriture } from '../../api/comptabilite'
import { useConfirm, useConfirmWithInput } from '../../contexts/ConfirmContext'
import { toNumber } from '../../utils/amount'
import type { ComptaEcriture, ComptaExercice, ComptaJournal } from '../../types/comptabilite'
import styles from './EcritureDetailModal.module.css'

function formatMontant(value: number | string): string {
  return new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
    toNumber(value)
  )
}

function badgeClass(statut: string): string {
  switch (statut) {
    case 'VALIDEE':
      return styles.badgeValidee
    case 'CLOTUREE':
      return styles.badgeCloturee
    case 'ANNULEE':
      return styles.badgeAnnulee
    default:
      return styles.badgeBrouillon
  }
}

export default function EcritureDetailModal({
  ecriture,
  journaux,
  exercices,
  canValidate,
  onClose,
  onUpdated,
}: {
  ecriture: ComptaEcriture
  journaux: ComptaJournal[]
  exercices: ComptaExercice[]
  canValidate: boolean
  onClose: () => void
  onUpdated: (ecriture: ComptaEcriture) => void
}) {
  const confirm = useConfirm()
  const confirmWithInput = useConfirmWithInput()
  const [busy, setBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const journal = journaux.find(j => j.id === ecriture.journal_id)
  const exercice = exercices.find(e => e.id === ecriture.exercice_id)

  const totalDebit = ecriture.lignes.reduce((sum, l) => sum + toNumber(l.debit), 0)
  const totalCredit = ecriture.lignes.reduce((sum, l) => sum + toNumber(l.credit), 0)

  const handleValider = async () => {
    const ok = await confirm({
      title: 'Valider cette écriture ?',
      description:
        "Une fois validée, l'écriture reçoit un numéro définitif et ne peut plus être modifiée. Seule une contre-passation permettra de l'annuler.",
      confirmText: 'Valider',
    })
    if (!ok) return
    setBusy(true)
    setErrorMessage(null)
    try {
      const updated = await validerComptaEcriture(ecriture.id)
      onUpdated(updated)
    } catch (err: any) {
      setErrorMessage(err?.message || "Impossible de valider l'écriture.")
    } finally {
      setBusy(false)
    }
  }

  const handleContrepasser = async () => {
    const { confirmed, value } = await confirmWithInput({
      title: "Contre-passer cette écriture ?",
      description:
        "Une écriture inverse sera créée en brouillon (à valider séparément) et celle-ci sera marquée annulée. Indiquez le motif.",
      confirmText: 'Contre-passer',
      variant: 'danger',
      inputLabel: 'Motif de la contre-passation *',
      inputPlaceholder: 'Ex: Erreur de compte imputé',
    })
    if (!confirmed) return
    setBusy(true)
    setErrorMessage(null)
    try {
      await contrepasserComptaEcriture(ecriture.id, value)
      // L'écriture originale passe à ANNULEE ; on referme et laisse la liste se rafraîchir.
      onUpdated({ ...ecriture, statut: 'ANNULEE', motif_annulation: value })
    } catch (err: any) {
      setErrorMessage(err?.message || 'Impossible de contre-passer cette écriture.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.overlay} role="presentation" onClick={onClose}>
      <div className={styles.modal} role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <h2>{ecriture.numero || '(brouillon)'}</h2>
            <span className={`${styles.badge} ${badgeClass(ecriture.statut)}`}>{ecriture.statut}</span>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            <X size={20} />
          </button>
        </div>

        <div className={styles.body}>
          <div className={styles.metaGrid}>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Journal</div>
              <div className={styles.metaValue}>{journal ? `${journal.code} — ${journal.libelle}` : ecriture.journal_id}</div>
            </div>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Exercice</div>
              <div className={styles.metaValue}>{exercice ? exercice.code : ecriture.exercice_id}</div>
            </div>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Devise</div>
              <div className={styles.metaValue}>{ecriture.devise}</div>
            </div>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Date d'écriture</div>
              <div className={styles.metaValue}>{ecriture.date_ecriture}</div>
            </div>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Date pièce</div>
              <div className={styles.metaValue}>{ecriture.date_piece || '—'}</div>
            </div>
            <div className={styles.metaItem}>
              <div className={styles.metaLabel}>Référence pièce</div>
              <div className={styles.metaValue}>{ecriture.reference_piece || '—'}</div>
            </div>
            <div className={styles.metaItem} style={{ gridColumn: '1 / -1' }}>
              <div className={styles.metaLabel}>Libellé</div>
              <div className={styles.metaValue}>{ecriture.libelle}</div>
            </div>
          </div>

          <table className={styles.lignesTable}>
            <thead>
              <tr>
                <th>Compte</th>
                <th>Libellé</th>
                <th style={{ textAlign: 'right' }}>Débit</th>
                <th style={{ textAlign: 'right' }}>Crédit</th>
              </tr>
            </thead>
            <tbody>
              {ecriture.lignes.map(l => (
                <tr key={l.id}>
                  <td>
                    {l.compte_numero ? `${l.compte_numero} — ${l.compte_libelle}` : l.compte_id}
                  </td>
                  <td>{l.libelle || '—'}</td>
                  <td className={styles.amountCell}>{toNumber(l.debit) > 0 ? formatMontant(l.debit) : ''}</td>
                  <td className={styles.amountCell}>{toNumber(l.credit) > 0 ? formatMontant(l.credit) : ''}</td>
                </tr>
              ))}
              <tr className={styles.totalRow}>
                <td colSpan={2}>Total</td>
                <td className={styles.amountCell}>{formatMontant(totalDebit)}</td>
                <td className={styles.amountCell}>{formatMontant(totalCredit)}</td>
              </tr>
            </tbody>
          </table>

          {ecriture.statut === 'ANNULEE' && ecriture.motif_annulation && (
            <div className={styles.motifBox}>Motif de contre-passation : {ecriture.motif_annulation}</div>
          )}

          {errorMessage && <div className={styles.errorBox}>{errorMessage}</div>}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.closeAction} onClick={onClose}>
            Fermer
          </button>
          {canValidate && ecriture.statut === 'BROUILLON' && (
            <button type="button" className={styles.validerBtn} disabled={busy} onClick={handleValider}>
              {busy ? 'Validation…' : 'Valider'}
            </button>
          )}
          {canValidate && ecriture.statut === 'VALIDEE' && (
            <button type="button" className={styles.contrepasserBtn} disabled={busy} onClick={handleContrepasser}>
              {busy ? 'Contre-passation…' : 'Contre-passer'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
