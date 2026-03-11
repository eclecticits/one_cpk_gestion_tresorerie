import type { TenantMetric } from '../../api/superAdmin'
import styles from './TenantActivityMap.module.css'

export default function TenantActivityMap({ tenants }: { tenants: TenantMetric[] }) {
  if (!tenants.length) return null

  const maxVolume = Math.max(...tenants.map((t) => Number(t.volume_encaisse_30j || 0)), 1)

  return (
    <div className={styles.card}>
      <div className={styles.title}>Activité des tenants (30 derniers jours)</div>
      {tenants.map((tenant) => {
        const ratio = Math.min(100, (Number(tenant.volume_encaisse_30j || 0) / maxVolume) * 100)
        const failures = Number(tenant.echecs_paiement_24h || 0)
        const fillClass = failures > 10 ? styles.fillDanger : failures > 0 ? styles.fillWarn : styles.fill
        const lastActivity = tenant.derniere_activite
          ? new Date(tenant.derniere_activite).toLocaleString()
          : 'Aucune activité'

        return (
          <div className={styles.row} key={tenant.org_id}>
            <div className={styles.name}>{tenant.org_nom}</div>
            <div className={styles.bar}>
              <div className={`${styles.fill} ${fillClass}`} style={{ width: `${ratio}%` }} />
            </div>
            <div className={styles.meta}>{lastActivity}</div>
          </div>
        )
      })}
    </div>
  )
}
