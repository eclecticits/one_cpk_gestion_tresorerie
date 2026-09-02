import { useCallback, useEffect, useState } from 'react'
import ResponsiveModal from './ResponsiveModal'
import { useToast } from '../hooks/useToast'
import { toNumber } from '../utils/amount'
import { ApiError } from '../lib/apiClient'
import {
  cancelRetourCaisse,
  createRetourCaisse,
  listRetoursForSortie,
  type RetourCaisse,
  type TypeRetourCaisse,
} from '../api/retoursCaisse'
import styles from './RetourCaisseModal.module.css'

/** Champs de la sortie de fonds d'origine nécessaires au retour. */
export interface RetourSortieSource {
  id: string
  montant_paye: number | string
  devise?: string | null
  canal?: string | null
  type_sortie?: string | null
  reference_numero?: string | null
  beneficiaire?: string | null
  motif?: string | null
}

interface RetourCaisseModalProps {
  isOpen: boolean
  sortie: RetourSortieSource | null
  onClose: () => void
  onSuccess?: () => void
}

const TYPE_OPTIONS: { value: TypeRetourCaisse; label: string }[] = [
  { value: 'reliquat_avance', label: "Reliquat d'avance à valoir" },
  { value: 'correction', label: 'Correction d’une sortie erronée' },
  { value: 'trop_percu', label: 'Trop-perçu rendu par le bénéficiaire' },
]

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  TYPE_OPTIONS.map((o) => [o.value, o.label]),
)

// Fenêtre d'annulation alignée sur le backend (30 minutes).
const CANCEL_WINDOW_MS = 30 * 60 * 1000

function formatMoney(n: number, devise: string): string {
  return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)} ${devise}`
}

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return '—'
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

function isRetourCancelable(item: RetourCaisse): boolean {
  if (String(item.statut || '').toUpperCase() !== 'VALIDE') return false
  const created = new Date(item.created_at).getTime()
  if (!Number.isFinite(created)) return false
  return Date.now() - created <= CANCEL_WINDOW_MS
}

export default function RetourCaisseModal({ isOpen, sortie, onClose, onSuccess }: RetourCaisseModalProps) {
  const { notifySuccess, notifyError, notifyWarning } = useToast()
  const [montant, setMontant] = useState('')
  const [typeRetour, setTypeRetour] = useState<TypeRetourCaisse>('reliquat_avance')
  const [motif, setMotif] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [reste, setReste] = useState<number | null>(null)
  const [totalRetourne, setTotalRetourne] = useState(0)
  const [items, setItems] = useState<RetourCaisse[]>([])
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [cancelMotif, setCancelMotif] = useState('')
  const [cancelSubmitting, setCancelSubmitting] = useState(false)

  const sortieId = sortie?.id
  const devise = (sortie?.devise || 'USD') as string
  const montantPaye = toNumber(sortie?.montant_paye ?? 0)

  const loadSummary = useCallback(async () => {
    if (!sortieId) return
    setLoadingSummary(true)
    try {
      const res = await listRetoursForSortie(sortieId)
      setReste(res.reste_a_justifier != null ? toNumber(res.reste_a_justifier) : Math.max(0, montantPaye))
      setTotalRetourne(res.total_retourne != null ? toNumber(res.total_retourne) : 0)
      setItems(Array.isArray(res.items) ? res.items : [])
    } catch {
      setReste(Math.max(0, montantPaye))
      setItems([])
    } finally {
      setLoadingSummary(false)
    }
  }, [sortieId, montantPaye])

  // Réinitialise le formulaire et (re)charge le résumé + l'historique à l'ouverture.
  useEffect(() => {
    if (!isOpen || !sortieId) return
    setMontant('')
    setTypeRetour('reliquat_avance')
    setMotif('')
    setCancellingId(null)
    setCancelMotif('')
    loadSummary()
  }, [isOpen, sortieId, loadSummary])

  if (!sortie) return null

  const montantNum = toNumber(montant || 0)
  const maxReste = reste == null ? montantPaye : reste
  const soldeEntierementJustifie = reste != null && reste <= 0
  const montantValide = montantNum > 0 && montantNum <= maxReste + 1e-6
  const canSubmit = montantValide && !submitting && !soldeEntierementJustifie

  const handleSubmit = async () => {
    if (!montantValide) {
      notifyWarning('Montant invalide', `Le montant doit être compris entre 0 et ${formatMoney(maxReste, devise)}.`)
      return
    }
    setSubmitting(true)
    try {
      const res = await createRetourCaisse({
        sortie_fonds_id: sortie.id,
        montant: montantNum,
        type_retour: typeRetour,
        motif: motif.trim() || undefined,
      })
      notifySuccess(
        'Retour enregistré',
        `Retour de ${formatMoney(montantNum, devise)} en caisse${res.reference_numero ? ` (${res.reference_numero})` : ''}.`,
      )
      setMontant('')
      setMotif('')
      await loadSummary()
      onSuccess?.()
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.payload?.detail || e.message : e?.message || 'Erreur inconnue'
      notifyError('Retour impossible', String(detail))
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (item: RetourCaisse) => {
    setCancelSubmitting(true)
    try {
      await cancelRetourCaisse(item.id, cancelMotif.trim() || undefined)
      notifySuccess('Retour annulé', `Le retour ${item.reference_numero ?? ''} a été annulé et la caisse rétablie.`)
      setCancellingId(null)
      setCancelMotif('')
      await loadSummary()
      onSuccess?.()
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.payload?.detail || e.message : e?.message || 'Erreur inconnue'
      notifyError('Annulation impossible', String(detail))
    } finally {
      setCancelSubmitting(false)
    }
  }

  const footer = (
    <div className={styles.footerActions}>
      <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={submitting || cancelSubmitting}>
        Fermer
      </button>
      <button type="button" className={styles.btnPrimary} onClick={handleSubmit} disabled={!canSubmit}>
        {submitting ? 'Enregistrement…' : 'Enregistrer le retour'}
      </button>
    </div>
  )

  return (
    <ResponsiveModal isOpen={isOpen} onClose={onClose} title="Retour en trésorerie" size="md" footer={footer}>
      <div className={styles.body}>
        <div className={styles.sourceCard}>
          <div className={styles.sourceRow}>
            <span>Sortie d’origine</span>
            <strong>{sortie.reference_numero || '—'}</strong>
          </div>
          <div className={styles.sourceRow}>
            <span>Bénéficiaire</span>
            <strong>{sortie.beneficiaire || '—'}</strong>
          </div>
          <div className={styles.sourceRow}>
            <span>Montant décaissé</span>
            <strong>{formatMoney(montantPaye, devise)}</strong>
          </div>
          <div className={styles.sourceRow}>
            <span>Déjà rendu</span>
            <strong>{formatMoney(totalRetourne, devise)}</strong>
          </div>
          <div className={`${styles.sourceRow} ${styles.highlight}`}>
            <span>Reste à justifier</span>
            <strong>{loadingSummary ? '…' : formatMoney(maxReste, devise)}</strong>
          </div>
        </div>

        {soldeEntierementJustifie ? (
          <p className={styles.warn}>Cette sortie est entièrement justifiée : aucun reliquat à rendre.</p>
        ) : (
          <>
            <label className={styles.field}>
              <span className={styles.label}>Montant rendu ({devise}) *</span>
              <input
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                className={styles.input}
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder={`Max ${formatMoney(maxReste, devise)}`}
                autoFocus
              />
            </label>

            <label className={styles.field}>
              <span className={styles.label}>Type de retour</span>
              <select
                className={styles.input}
                value={typeRetour}
                onChange={(e) => setTypeRetour(e.target.value as TypeRetourCaisse)}
              >
                {TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.field}>
              <span className={styles.label}>Motif (facultatif)</span>
              <textarea
                className={styles.textarea}
                rows={3}
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                placeholder="Ex : reliquat mission Goma"
              />
            </label>

            <p className={styles.hint}>
              La caisse doit être ouverte. Le retour crédite la caisse et réduit la dépense imputée au budget.
            </p>
          </>
        )}

        {/* Historique des retours de cette sortie */}
        <div className={styles.history}>
          <div className={styles.historyHeader}>
            <span>Historique des retours</span>
            {items.length > 0 && <span className={styles.historyCount}>{items.length}</span>}
          </div>

          {loadingSummary && items.length === 0 ? (
            <p className={styles.historyEmpty}>Chargement…</p>
          ) : items.length === 0 ? (
            <p className={styles.historyEmpty}>Aucun retour enregistré pour cette sortie.</p>
          ) : (
            <ul className={styles.historyList}>
              {items.map((item) => {
                const annulee = String(item.statut || '').toUpperCase() === 'ANNULEE'
                const cancelable = isRetourCancelable(item)
                const isConfirming = cancellingId === item.id
                return (
                  <li key={item.id} className={`${styles.historyItem} ${annulee ? styles.historyItemCancelled : ''}`}>
                    <div className={styles.historyMain}>
                      <div className={styles.historyLine}>
                        <strong className={styles.historyRef}>{item.reference_numero || '—'}</strong>
                        <span className={styles.historyAmount}>{formatMoney(toNumber(item.montant), item.devise)}</span>
                      </div>
                      <div className={styles.historyMeta}>
                        <span>{formatDateTime(item.date_retour || item.created_at)}</span>
                        <span>·</span>
                        <span>{TYPE_LABELS[item.type_retour] || item.type_retour}</span>
                      </div>
                      {item.motif && <div className={styles.historyMotif}>{item.motif}</div>}
                    </div>

                    <div className={styles.historyAside}>
                      {annulee ? (
                        <span className={styles.badgeCancelled}>Annulé</span>
                      ) : cancelable ? (
                        <button
                          type="button"
                          className={styles.linkCancel}
                          onClick={() => {
                            setCancellingId(item.id)
                            setCancelMotif('')
                          }}
                          disabled={cancelSubmitting}
                        >
                          Annuler
                        </button>
                      ) : (
                        <span className={styles.badgeLocked} title="Annulation impossible après 30 minutes">
                          Verrouillé
                        </span>
                      )}
                    </div>

                    {isConfirming && (
                      <div className={styles.cancelBox}>
                        <input
                          type="text"
                          className={styles.input}
                          value={cancelMotif}
                          onChange={(e) => setCancelMotif(e.target.value)}
                          placeholder="Motif d’annulation (facultatif)"
                        />
                        <div className={styles.cancelActions}>
                          <button
                            type="button"
                            className={styles.btnSecondary}
                            onClick={() => setCancellingId(null)}
                            disabled={cancelSubmitting}
                          >
                            Abandonner
                          </button>
                          <button
                            type="button"
                            className={styles.btnDanger}
                            onClick={() => handleCancel(item)}
                            disabled={cancelSubmitting}
                          >
                            {cancelSubmitting ? 'Annulation…' : 'Confirmer l’annulation'}
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </ResponsiveModal>
  )
}
