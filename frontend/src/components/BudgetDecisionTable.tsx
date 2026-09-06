import { useMemo } from 'react'
import {
  buildBudgetDecisionBreakdown,
  formatBudgetDecisionAmount,
  type BudgetDecisionLine,
} from '../utils/budgetDecision'
import type { Money } from '../utils/amount'
import styles from './BudgetDecisionTable.module.css'

interface BudgetDecisionTableProps {
  lines: BudgetDecisionLine[]
  /** Montant de référence de la demande ; à défaut, la somme des lignes. */
  requestedAmount?: Money
  emptyLabel?: string
}

/**
 * Les repères budgétaires d'une réquisition, poste par poste, totaux en pied.
 * Partagé par la validation, l'examen et le suivi des réquisitions : les trois
 * écrans montraient les mêmes quatre cartes agrégées, qui mélangeaient des
 * enveloppes distinctes dès qu'une demande touchait plusieurs postes.
 */
export default function BudgetDecisionTable({
  lines,
  requestedAmount,
  emptyLabel = 'Aucun poste budgétaire rattaché à cette demande.',
}: BudgetDecisionTableProps) {
  const { rows, totals } = useMemo(
    () => buildBudgetDecisionBreakdown(lines, requestedAmount),
    [lines, requestedAmount]
  )

  if (rows.length === 0) {
    return <p className={styles.empty}>{emptyLabel}</p>
  }

  const renderAmount = (amount?: number | null, negative = false) => {
    if (amount === null || amount === undefined) {
      return <span className={styles.missing} title="Snapshot indisponible">Indisponible</span>
    }
    const isNegative = negative && amount < 0
    return (
      <span className={isNegative ? styles.negative : undefined}>
        {formatBudgetDecisionAmount(amount)}
      </span>
    )
  }

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Poste budgétaire</th>
            <th scope="col" className={styles.num}>Budget</th>
            <th scope="col" className={styles.num}>Engagé</th>
            <th scope="col" className={styles.num}>Disponible</th>
            <th scope="col" className={styles.num}>Demandé</th>
            <th scope="col" className={styles.num}>Solde après</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row" className={styles.posteCell}>{row.label}</th>
              <td className={styles.num}>{renderAmount(row.budget)}</td>
              <td className={styles.num}>{renderAmount(row.engaged)}</td>
              <td className={styles.num}>{renderAmount(row.available)}</td>
              <td className={styles.num}>{formatBudgetDecisionAmount(row.requested)}</td>
              <td className={styles.num}>{renderAmount(row.remainingAfterRequest, true)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" className={styles.posteCell}>Total</th>
            <td className={styles.num}>{renderAmount(totals.budget)}</td>
            <td className={styles.num}>{renderAmount(totals.engaged)}</td>
            <td className={styles.num}>{renderAmount(totals.available)}</td>
            <td className={styles.num}>{formatBudgetDecisionAmount(totals.requested)}</td>
            <td className={styles.num}>{renderAmount(totals.remainingAfterRequest, true)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
