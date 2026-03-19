import { useMemo, useState } from 'react'
import { confirmTreasuryClassification } from '../../api/treasury'
import styles from './BatchReview.module.css'

type BatchTx = {
  label: string
  amount: number
  ai_classification?: {
    compte?: string
    categorie?: string
    explication?: string
    taux_confiance?: number
    error?: string
    source?: 'memory' | 'ai'
  }
}

interface BatchReviewProps {
  results: BatchTx[]
  onConfirmAll?: () => void
}

export default function BatchReview({ results, onConfirmAll }: BatchReviewProps) {
  const [confirming, setConfirming] = useState<Record<number, boolean>>({})
  const [confirmed, setConfirmed] = useState<Record<number, boolean>>({})

  const canConfirmAll = useMemo(
    () =>
      results.some(
        (tx, idx) =>
          !confirmed[idx] &&
          tx.ai_classification?.compte &&
          !tx.ai_classification?.error
      ),
    [results, confirmed]
  )

  const confirmOne = async (tx: BatchTx, idx: number) => {
    if (!tx.ai_classification?.compte || tx.ai_classification?.error) return
    setConfirming((prev) => ({ ...prev, [idx]: true }))
    try {
      await confirmTreasuryClassification({
        label: tx.label,
        account: tx.ai_classification.compte,
        confidence_score: tx.ai_classification.taux_confiance ?? 1,
      })
      setConfirmed((prev) => ({ ...prev, [idx]: true }))
    } finally {
      setConfirming((prev) => ({ ...prev, [idx]: false }))
    }
  }

  const confirmAll = async () => {
    if (!canConfirmAll) return
    if (onConfirmAll) {
      onConfirmAll()
      return
    }
    const pending = results
      .map((tx, idx) => ({ tx, idx }))
      .filter(
        ({ tx, idx }) =>
          !confirmed[idx] && tx.ai_classification?.compte && !tx.ai_classification?.error
      )
    for (const { tx, idx } of pending) {
      await confirmOne(tx, idx)
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h3>Revue de classification SYSCEBNL</h3>
        <span className={styles.subtitle}>Vérifiez chaque proposition avant validation</span>
      </div>

      <div className={styles.list}>
        {results.map((tx, idx) => (
          <div
            key={`${tx.label}-${idx}`}
            className={`${styles.row} ${
              tx.ai_classification?.source === 'memory'
                ? styles.rowMemory
                : tx.ai_classification?.source === 'ai'
                ? styles.rowAi
                : ''
            } ${confirmed[idx] ? styles.rowConfirmed : ''}`}
          >
            <div className={styles.rowInfo}>
              <p className={styles.label}>{tx.label}</p>
              <p className={styles.amount}>{Number(tx.amount || 0).toLocaleString()} FC</p>
            </div>
            <div className={styles.rowActions}>
              <div className={styles.classification}>
                <span className={styles.compteBadge}>
                  Compte {tx.ai_classification?.compte || '—'}
                </span>
                {tx.ai_classification?.source && (
                  <span className={styles.sourceTag}>
                    {tx.ai_classification.source === 'memory' ? 'Mémoire' : 'IA'}
                  </span>
                )}
                <p className={styles.explication}>
                  {tx.ai_classification?.explication || tx.ai_classification?.error || 'Analyse indisponible.'}
                </p>
              </div>
              <button
                className={styles.confirmBtn}
                type="button"
                aria-label="Confirmer"
                onClick={() => confirmOne(tx, idx)}
                disabled={confirming[idx] || confirmed[idx] || !tx.ai_classification?.compte}
                title={confirmed[idx] ? 'Déjà confirmé' : 'Confirmer'}
              >
                {confirmed[idx] ? '✓' : confirming[idx] ? '…' : '✓'}
              </button>
            </div>
          </div>
        ))}
      </div>

      <button type="button" className={styles.confirmAll} onClick={confirmAll} disabled={!canConfirmAll}>
        Valider et Inscrire au Grand Livre
      </button>
    </div>
  )
}
