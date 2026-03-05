import { TrendingDown } from 'lucide-react'
import styles from './TopExpenses.module.css'
import { toNumber } from '../utils/amount'

type ExpenseItem = {
  motif: string
  total: number | string
}

export default function TopExpenses({ expenses, devise }: { expenses: ExpenseItem[]; devise: string }) {
  const total = expenses.reduce((acc, curr) => acc + toNumber(curr.total), 0)

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h3>
          <TrendingDown size={14} /> Dépenses principales
        </h3>
        <span>TOTAL: {total.toLocaleString('fr-FR')} {devise}</span>
      </div>
      <div className={styles.body}>
        {expenses.slice(0, 5).map((exp, index) => {
          const amount = toNumber(exp.total)
          const percentage = total > 0 ? (amount / total) * 100 : 0
          return (
            <div key={`${exp.motif}-${index}`} className={styles.row}>
              <div className={styles.rowTop}>
                <span title={exp.motif} className={styles.label}>
                  {exp.motif || 'Sans motif'}
                </span>
                <span className={styles.amount}>
                  {amount.toLocaleString('fr-FR')} {devise}
                </span>
              </div>
              <div className={styles.bar}>
                <div className={styles.barFill} style={{ width: `${percentage}%` }} />
              </div>
            </div>
          )
        })}

        {expenses.length === 0 && (
          <div className={styles.empty}>Aucune dépense enregistrée ce mois-ci.</div>
        )}
      </div>
    </div>
  )
}
