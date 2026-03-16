import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowUpRight, Landmark, Users } from 'lucide-react'

import { getGlobalStats, type GlobalStat } from '../api/superAdmin'
import styles from './GlobalMonitoring.module.css'

export default function GlobalMonitoring() {
  const [stats, setStats] = useState<GlobalStat[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const res = await getGlobalStats()
        if (mounted) {
          setStats(res || [])
        }
      } catch {
        if (mounted) {
          setStats([])
        }
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  const totalEncaisse = useMemo(() => {
    return stats.reduce((sum, row) => sum + Number(row.balance || 0), 0)
  }, [stats])

  const activeCount = useMemo(() => {
    return stats.filter((row) => row.is_active).length
  }, [stats])

  if (loading) {
    return <div className={styles.page}>Chargement...</div>
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Pilotage National IntelliOffice</h1>
        <p className={styles.subtitle}>Supervision consolidée des Conseils Provinciaux</p>
      </div>

      <div className={styles.cardGrid}>
        <StatCard
          title="Total encaissé (RDC)"
          value={`${totalEncaisse.toLocaleString()} FC`}
          icon={<Landmark size={20} />}
        />
        <StatCard
          title="Provinces actives"
          value={activeCount.toString()}
          icon={<Users size={20} />}
        />
        <StatCard
          title="Alertes budgétaires"
          value="—"
          icon={<AlertCircle size={20} />}
        />
      </div>

      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead className={styles.thead}>
            <tr>
              <th className={styles.th}>Province</th>
              <th className={styles.th}>Statut</th>
              <th className={styles.th}>Flux trésorerie</th>
              <th className={styles.th}>Consommation budget</th>
              <th className={styles.th}>Action</th>
            </tr>
          </thead>
          <tbody>
            {stats.length === 0 && (
              <tr>
                <td className={styles.td} colSpan={5}>
                  <div className={styles.emptyState}>Aucune organisation trouvée.</div>
                </td>
              </tr>
            )}
            {stats.map((cp) => (
              <tr key={cp.id} className={styles.rowHover}>
                <td className={styles.td}>
                  <strong>{cp.name}</strong>
                </td>
                <td className={styles.td}>
                  <span
                    className={`${styles.statusBadge} ${
                      cp.is_active ? styles.statusActive : styles.statusPending
                    }`}
                  >
                    {cp.is_active ? 'Actif' : 'En attente'}
                  </span>
                </td>
                <td className={styles.td}>{Number(cp.balance || 0).toLocaleString()} FC</td>
                <td className={styles.td}>
                  <div className={styles.progressWrap}>
                    <div className={styles.progressTrack}>
                      <div className={styles.progressFill} style={{ width: `${cp.usage || 0}%` }} />
                    </div>
                    <span className={styles.progressValue}>{cp.usage || 0}%</span>
                  </div>
                </td>
                <td className={styles.td}>
                  <button type="button" className={styles.actionBtn} title="Voir détail">
                    <ArrowUpRight size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StatCard({
  title,
  value,
  icon,
}: {
  title: string
  value: string
  icon: React.ReactNode
}) {
  return (
    <div className={styles.statCard}>
      <div className={styles.statIcon}>{icon}</div>
      <div>
        <div className={styles.statTitle}>{title}</div>
        <div className={styles.statValue}>{value}</div>
      </div>
    </div>
  )
}
