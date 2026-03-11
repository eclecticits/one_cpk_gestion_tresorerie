import styles from './PlatformHealth.module.css'
import type { PlatformSummary } from '../../api/superAdmin'

export default function PlatformHealth({ stats }: { stats: PlatformSummary | null }) {
  if (!stats) return null

  return (
    <div className={styles.grid}>
      <div className={`${styles.card} ${styles.accentGreen}`}>
        <div className={styles.label}>Total encaissé (24h)</div>
        <div className={styles.value}>${stats.total_volume_usd.toLocaleString()}</div>
        <div className={styles.subtext}>{stats.total_transactions} transactions</div>
      </div>
      <div className={`${styles.card} ${styles.accentBlue}`}>
        <div className={styles.label}>Tenants actifs</div>
        <div className={styles.value}>{stats.active_tenants} / {stats.total_tenants}</div>
        <div className={styles.subtext}>parc SaaS</div>
      </div>
      <div className={`${styles.card} ${styles.accentPurple}`}>
        <div className={styles.label}>Succès Webhook</div>
        <div className={styles.value}>{stats.webhook_success_rate}%</div>
        <div className={styles.subtext}>24h</div>
      </div>
      <div className={`${styles.card} ${styles.accentOrange}`}>
        <div className={styles.label}>Erreurs API (24h)</div>
        <div className={styles.value}>{stats.api_errors}</div>
        <div className={styles.subtext}>à instrumenter</div>
      </div>
    </div>
  )
}
