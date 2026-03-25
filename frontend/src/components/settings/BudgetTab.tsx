import { useEffect, useState } from 'react'
import { ListChecks } from 'lucide-react'
import ServiceAccessManager from './ServiceAccessManager'
import type { Service } from '../../types'
import { getServiceRubriques } from '../../api/services'
import styles from './BudgetTab.module.css'

type Props = {
  services: Service[]
  activeServiceId: number | null
  setActiveServiceId: (id: number) => void
}

export default function BudgetTab({
  services,
  activeServiceId,
  setActiveServiceId,
}: Props) {
  const [rubriqueCounts, setRubriqueCounts] = useState<Record<number, number>>({})
  const [loadingCounts, setLoadingCounts] = useState(false)

  useEffect(() => {
    if (!services.length) {
      setRubriqueCounts({})
      return
    }
    let cancelled = false
    const loadCounts = async () => {
      setLoadingCounts(true)
      try {
        const entries = await Promise.all(
          services.map(async (service) => {
            try {
              const rubs = await getServiceRubriques(service.id)
              return [service.id, Array.isArray(rubs) ? rubs.length : 0] as const
            } catch {
              return [service.id, 0] as const
            }
          })
        )
        if (!cancelled) {
          const next: Record<number, number> = {}
          entries.forEach(([id, count]) => {
            next[id] = count
          })
          setRubriqueCounts(next)
        }
      } finally {
        if (!cancelled) setLoadingCounts(false)
      }
    }
    loadCounts()
    return () => {
      cancelled = true
    }
  }, [services])

  return (
    <div className={styles.wrapper}>
      <section className={styles.whitelistCard}>
        <div className={styles.whitelistHeader}>
          <h3>
            <ListChecks size={18} /> Répartition des droits budgétaires
          </h3>
          <p className={styles.importText} style={{ marginTop: 4 }}>
            Définissez les postes budgétaires autorisés pour chaque commission.
          </p>
        </div>
        <div className={styles.whitelistGrid}>
          <div className={styles.serviceList}>
            {services.map((service) => (
              <button
                key={service.id}
                type="button"
                className={`${styles.serviceItem} ${activeServiceId === service.id ? styles.serviceItemActive : ''}`}
                onClick={() => setActiveServiceId(service.id)}
              >
                <span className={styles.serviceCode}>{service.code}</span>
                <span className={styles.serviceLabel}>{service.libelle}</span>
                <span className={styles.serviceMeta}>
                  {loadingCounts ? 'Chargement…' : `${rubriqueCounts[service.id] ?? 0} postes budgétaires`}
                </span>
              </button>
            ))}
            {services.length === 0 && (
              <div className={styles.emptyState}>Aucun service disponible.</div>
            )}
          </div>
          <ServiceAccessManager
            serviceId={activeServiceId}
            serviceLabel={
              services.find((s) => s.id === activeServiceId)
                ? `${services.find((s) => s.id === activeServiceId)?.code} - ${services.find((s) => s.id === activeServiceId)?.libelle}`
                : undefined
            }
          />
        </div>
      </section>
    </div>
  )
}
