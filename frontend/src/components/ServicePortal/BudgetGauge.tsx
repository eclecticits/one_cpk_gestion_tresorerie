import { CircularProgressbar, buildStyles } from 'react-circular-progressbar'
import 'react-circular-progressbar/dist/styles.css'
import styles from './BudgetGauge.module.css'

type Props = {
  consomme: number
  engage: number
  total: number
}

const getColor = (percentage: number) => {
  if (percentage >= 90) return '#ef4444'
  if (percentage >= 70) return '#f97316'
  return '#22c55e'
}

export default function BudgetGauge({ consomme, engage, total }: Props) {
  const pctConsomme = total > 0 ? (consomme / total) * 100 : 0
  const pctEngage = total > 0 ? (engage / total) * 100 : 0
  const pctTotal = Math.min(100, Math.round(pctConsomme + pctEngage))
  const color = getColor(pctTotal)
  const libre = Math.max(0, total - (consomme + engage))

  return (
    <div className={styles.gauge}>
      <CircularProgressbar
        value={pctTotal}
        text={`${pctTotal}%`}
        styles={buildStyles({
          pathColor: color,
          textColor: '#1e293b',
          trailColor: '#f1f5f9',
          textSize: '18px',
        })}
      />
      <div className={styles.legend}>
        <span className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotGreen}`} />
          Payé: {consomme.toLocaleString()} USD
        </span>
        <span className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotOrange}`} />
          Engagé: {engage.toLocaleString()} USD
        </span>
        <span className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotBlue}`} />
          Disponible: {libre.toLocaleString()} USD
        </span>
      </div>
      <div className={styles.miniProgress}>
        <div className={styles.miniHeader}>
          <span>Utilisation réelle</span>
          <span>{pctTotal}%</span>
        </div>
        <div className={styles.miniTrack}>
          <div className={styles.miniPaid} style={{ width: `${Math.min(100, pctConsomme)}%` }} title="Payé" />
          <div className={styles.miniEngaged} style={{ width: `${Math.min(100 - pctConsomme, pctEngage)}%` }} title="Engagé" />
        </div>
        <div className={styles.miniFooter}>
          Libre: {libre.toLocaleString()} USD
        </div>
      </div>
      <p className={styles.label}>Payé + Engagé</p>
    </div>
  )
}
