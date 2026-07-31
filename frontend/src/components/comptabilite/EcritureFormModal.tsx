import { useMemo, useState } from 'react'
import { format } from 'date-fns'
import { Check, AlertTriangle, X, Trash2 } from 'lucide-react'
import { createComptaEcriture } from '../../api/comptabilite'
import { toNumber } from '../../utils/amount'
import type { ComptaCompte, ComptaEcriture, ComptaExercice, ComptaJournal } from '../../types/comptabilite'
import styles from './EcritureFormModal.module.css'

interface LigneDraft {
  key: string
  compte_id: number | null
  compteSearch: string
  showDropdown: boolean
  libelle: string
  debit: string
  credit: string
}

let ligneKeySeq = 0
function newLigne(): LigneDraft {
  ligneKeySeq += 1
  return {
    key: `l${ligneKeySeq}`,
    compte_id: null,
    compteSearch: '',
    showDropdown: false,
    libelle: '',
    debit: '',
    credit: '',
  }
}

function formatMontant(value: number): string {
  return new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
}

export default function EcritureFormModal({
  journaux,
  exercices,
  comptes,
  onClose,
  onCreated,
}: {
  journaux: ComptaJournal[]
  exercices: ComptaExercice[]
  comptes: ComptaCompte[]
  onClose: () => void
  onCreated: (ecriture: ComptaEcriture) => void
}) {
  const today = useMemo(() => format(new Date(), 'yyyy-MM-dd'), [])
  const exerciceOuvert = useMemo(
    () => exercices.find(e => String(e.statut).toUpperCase() === 'OUVERT') ?? exercices[0] ?? null,
    [exercices]
  )

  const [journalId, setJournalId] = useState<string>(journaux[0] ? String(journaux[0].id) : '')
  const [exerciceId, setExerciceId] = useState<string>(exerciceOuvert ? String(exerciceOuvert.id) : '')
  const [dateEcriture, setDateEcriture] = useState(today)
  const [datePiece, setDatePiece] = useState('')
  const [referencePiece, setReferencePiece] = useState('')
  const [libelle, setLibelle] = useState('')
  const [devise, setDevise] = useState(exerciceOuvert?.devise_tenue || 'USD')
  const [lignes, setLignes] = useState<LigneDraft[]>([newLigne(), newLigne()])
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const activeComptes = useMemo(() => comptes.filter(c => c.actif), [comptes])

  const filterComptes = (query: string): ComptaCompte[] => {
    const q = query.trim().toLowerCase()
    if (!q) return activeComptes.slice(0, 30)
    return activeComptes
      .filter(c => c.numero.toLowerCase().includes(q) || c.libelle.toLowerCase().includes(q))
      .slice(0, 30)
  }

  const updateLigne = (key: string, patch: Partial<LigneDraft>) => {
    setLignes(prev => prev.map(l => (l.key === key ? { ...l, ...patch } : l)))
  }

  const selectCompte = (key: string, compte: ComptaCompte) => {
    updateLigne(key, {
      compte_id: compte.id,
      compteSearch: `${compte.numero} — ${compte.libelle}`,
      showDropdown: false,
    })
  }

  const addLigne = () => setLignes(prev => [...prev, newLigne()])
  const removeLigne = (key: string) =>
    setLignes(prev => (prev.length <= 2 ? prev : prev.filter(l => l.key !== key)))

  const totalDebit = lignes.reduce((sum, l) => sum + toNumber(l.debit), 0)
  const totalCredit = lignes.reduce((sum, l) => sum + toNumber(l.credit), 0)
  const diff = Math.round((totalDebit - totalCredit) * 100) / 100
  const isBalanced = Math.abs(diff) < 0.005 && totalDebit > 0

  const isLigneValid = (l: LigneDraft) => {
    const hasCompte = l.compte_id != null
    const d = toNumber(l.debit)
    const c = toNumber(l.credit)
    const exclusive = (d > 0 && c === 0) || (c > 0 && d === 0)
    return hasCompte && exclusive
  }

  const allLignesValid = lignes.every(isLigneValid)
  const canSave =
    Boolean(journalId) &&
    Boolean(exerciceId) &&
    Boolean(dateEcriture) &&
    libelle.trim().length > 0 &&
    lignes.length >= 2 &&
    allLignesValid &&
    isBalanced &&
    !submitting

  const handleDebitChange = (key: string, value: string) => {
    if (value.trim() === '') {
      updateLigne(key, { debit: value })
      return
    }
    updateLigne(key, { debit: value, credit: '' })
  }

  const handleCreditChange = (key: string, value: string) => {
    if (value.trim() === '') {
      updateLigne(key, { credit: value })
      return
    }
    updateLigne(key, { credit: value, debit: '' })
  }

  const handleSubmit = async () => {
    if (!canSave) return
    setSubmitting(true)
    setErrorMessage(null)
    try {
      const ecriture = await createComptaEcriture({
        journal_id: Number(journalId),
        exercice_id: Number(exerciceId),
        date_ecriture: dateEcriture,
        date_piece: datePiece || null,
        reference_piece: referencePiece.trim() || null,
        libelle: libelle.trim(),
        devise,
        lignes: lignes.map(l => ({
          compte_id: l.compte_id as number,
          libelle: l.libelle.trim() || null,
          debit: toNumber(l.debit).toFixed(2),
          credit: toNumber(l.credit).toFixed(2),
        })),
      })
      onCreated(ecriture)
    } catch (err: any) {
      setErrorMessage(err?.message || "Impossible d'enregistrer l'écriture.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} role="presentation" onClick={onClose}>
      <div className={styles.modal} role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>Nouvelle écriture</h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            <X size={20} />
          </button>
        </div>

        <div className={styles.body}>
          <div className={styles.headerGrid}>
            <div className={styles.field}>
              <label htmlFor="ecr-journal">Journal *</label>
              <select id="ecr-journal" value={journalId} onChange={e => setJournalId(e.target.value)}>
                {journaux.map(j => (
                  <option key={j.id} value={j.id}>
                    {j.code} — {j.libelle}
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label htmlFor="ecr-exercice">Exercice *</label>
              <select id="ecr-exercice" value={exerciceId} onChange={e => setExerciceId(e.target.value)}>
                {exercices.map(ex => (
                  <option key={ex.id} value={ex.id}>
                    {ex.code} ({ex.statut})
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label htmlFor="ecr-date">Date d'écriture *</label>
              <input
                id="ecr-date"
                type="date"
                value={dateEcriture}
                onChange={e => setDateEcriture(e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label htmlFor="ecr-devise">Devise *</label>
              <select id="ecr-devise" value={devise} onChange={e => setDevise(e.target.value)}>
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div className={styles.field}>
              <label htmlFor="ecr-date-piece">Date pièce</label>
              <input
                id="ecr-date-piece"
                type="date"
                value={datePiece}
                onChange={e => setDatePiece(e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label htmlFor="ecr-reference">Référence pièce</label>
              <input
                id="ecr-reference"
                type="text"
                value={referencePiece}
                onChange={e => setReferencePiece(e.target.value)}
                placeholder="Ex: FACT-2026-014"
              />
            </div>
            <div className={`${styles.field} ${styles.libelleField}`}>
              <label htmlFor="ecr-libelle">Libellé *</label>
              <input
                id="ecr-libelle"
                type="text"
                value={libelle}
                onChange={e => setLibelle(e.target.value)}
                placeholder="Ex: Cotisation membre — juillet 2026"
              />
            </div>
          </div>

          <div className={styles.lignesHeader}>
            <h3>Lignes</h3>
            <button type="button" className={styles.addLineBtn} onClick={addLigne}>
              + Ajouter une ligne
            </button>
          </div>

          <div className={styles.lignesTable}>
            <div className={styles.lignesTableHead}>
              <span>#</span>
              <span>Compte</span>
              <span>Libellé</span>
              <span>Débit</span>
              <span>Crédit</span>
              <span />
            </div>
            {lignes.map((l, idx) => {
              const valid = isLigneValid(l)
              const suggestions = l.showDropdown ? filterComptes(l.compteSearch) : []
              return (
                <div
                  key={l.key}
                  className={`${styles.ligneRow} ${!valid ? styles.ligneRowInvalid : ''}`}
                >
                  <span className={styles.ligneIndex}>{idx + 1}</span>
                  <div className={styles.compteSearchWrap}>
                    <input
                      type="text"
                      value={l.compteSearch}
                      onChange={e => {
                        updateLigne(l.key, {
                          compteSearch: e.target.value,
                          compte_id: null,
                          showDropdown: true,
                        })
                      }}
                      onFocus={() => updateLigne(l.key, { showDropdown: true })}
                      onBlur={() => {
                        window.setTimeout(() => updateLigne(l.key, { showDropdown: false }), 120)
                      }}
                      placeholder="N° ou libellé du compte"
                      aria-label={`Compte de la ligne ${idx + 1}`}
                    />
                    {l.showDropdown && (
                      <div className={styles.compteDropdown} onMouseDown={e => e.preventDefault()}>
                        {suggestions.length === 0 ? (
                          <div className={styles.compteDropdownEmpty}>Aucun compte trouvé.</div>
                        ) : (
                          suggestions.map(c => (
                            <div
                              key={c.id}
                              className={styles.compteDropdownItem}
                              onClick={() => selectCompte(l.key, c)}
                            >
                              <span className={styles.compteDropdownNumero}>{c.numero}</span>
                              <span className={styles.compteDropdownLibelle}>{c.libelle}</span>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                  <div className={styles.ligneLibelle}>
                    <input
                      type="text"
                      value={l.libelle}
                      onChange={e => updateLigne(l.key, { libelle: e.target.value })}
                      placeholder="(optionnel)"
                      aria-label={`Libellé de la ligne ${idx + 1}`}
                    />
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={styles.montantInput}
                    value={l.debit}
                    onChange={e => handleDebitChange(l.key, e.target.value)}
                    placeholder="0.00"
                    aria-label={`Débit de la ligne ${idx + 1}`}
                  />
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={styles.montantInput}
                    value={l.credit}
                    onChange={e => handleCreditChange(l.key, e.target.value)}
                    placeholder="0.00"
                    aria-label={`Crédit de la ligne ${idx + 1}`}
                  />
                  <button
                    type="button"
                    className={styles.removeLineBtn}
                    onClick={() => removeLigne(l.key)}
                    disabled={lignes.length <= 2}
                    aria-label={`Retirer la ligne ${idx + 1}`}
                    title="Retirer la ligne"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              )
            })}
          </div>

          <div className={styles.balanceBar}>
            <div className={styles.balanceTotals}>
              <span>
                Total débit : <strong>{formatMontant(totalDebit)}</strong>
              </span>
              <span>
                Total crédit : <strong>{formatMontant(totalCredit)}</strong>
              </span>
            </div>
            {isBalanced ? (
              <span className={`${styles.balanceStatus} ${styles.balanceOk}`}>
                <Check size={15} /> Équilibrée
              </span>
            ) : (
              <span className={`${styles.balanceStatus} ${styles.balanceKo}`}>
                <AlertTriangle size={15} /> Écart de {formatMontant(Math.abs(diff))}
              </span>
            )}
          </div>

          {errorMessage && <div className={styles.errorBox}>{errorMessage}</div>}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.cancelBtn} onClick={onClose}>
            Annuler
          </button>
          <button type="button" className={styles.saveBtn} disabled={!canSave} onClick={handleSubmit}>
            {submitting ? 'Enregistrement…' : 'Enregistrer (brouillon)'}
          </button>
        </div>
      </div>
    </div>
  )
}
