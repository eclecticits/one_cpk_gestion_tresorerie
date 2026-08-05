import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Building2, ChevronRight, ListChecks, Search } from 'lucide-react'
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
  const [serviceSearch, setServiceSearch] = useState('')
  const [serviceStatusFilter, setServiceStatusFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)

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

  const supportsStatusFilter = services.some((service) => typeof service.is_active === 'boolean')

  const filteredServices = useMemo(() => {
    const query = serviceSearch.trim().toLowerCase()
    return services
      .filter((service) => {
        const matchesQuery = !query
          || String(service.code || '').toLowerCase().includes(query)
          || String(service.libelle || '').toLowerCase().includes(query)
        const matchesStatus = serviceStatusFilter === 'all'
          || (serviceStatusFilter === 'active' && service.is_active)
          || (serviceStatusFilter === 'inactive' && !service.is_active)
        return matchesQuery && matchesStatus
      })
      .sort((a, b) => String(a.libelle || '').localeCompare(String(b.libelle || ''), 'fr', { sensitivity: 'base' }))
  }, [services, serviceSearch, serviceStatusFilter])

  const selectedService = services.find((service) => service.id === activeServiceId) || null

  const confirmDiscardChanges = () => {
    if (!hasUnsavedChanges) return true
    return window.confirm("Des modifications n'ont pas été enregistrées.\nVoulez-vous quitter sans enregistrer ?")
  }

  const selectService = (serviceId: number) => {
    if (!confirmDiscardChanges()) return
    setActiveServiceId(serviceId)
  }

  const goToServicesAndCommissions = () => {
    if (!confirmDiscardChanges()) return
    window.location.href = '/settings?tab=services&sub=commissions'
  }

  return (
    <div className={styles.wrapper}>
      <header className={styles.pageHeader}>
        <div>
          <nav className={styles.breadcrumb} aria-label="Fil d'Ariane">
            <span>Administration</span>
            <ChevronRight size={14} aria-hidden="true" />
            <button type="button" onClick={goToServicesAndCommissions}>
              Services &amp; Commissions
            </button>
            <ChevronRight size={14} aria-hidden="true" />
            <strong>Structure budgétaire</strong>
          </nav>
          <div className={styles.titleRow}>
            <ListChecks size={20} aria-hidden="true" />
            <div>
              <h2>Structure budgétaire</h2>
              <p>Définissez les postes budgétaires autorisés pour chaque unité.</p>
            </div>
          </div>
        </div>
        <button type="button" className={styles.backButton} onClick={goToServicesAndCommissions}>
          <ArrowLeft size={16} aria-hidden="true" />
          Retour aux services et commissions
        </button>
      </header>

      <section className={styles.structureShell}>
        <aside className={styles.unitsPanel} aria-label="Unités">
          <div className={styles.unitsHeader}>
            <div>
              <h3>Unités</h3>
              <span>{filteredServices.length} sur {services.length}</span>
            </div>
          </div>

          <div className={styles.unitsTools}>
            <label className={styles.searchBox}>
              <Search size={15} aria-hidden="true" />
              <input
                type="search"
                value={serviceSearch}
                onChange={(event) => setServiceSearch(event.target.value)}
                placeholder="Rechercher code ou nom"
                aria-label="Rechercher une unité par code ou nom"
              />
            </label>
            {supportsStatusFilter && (
              <div className={styles.segmented} aria-label="Filtrer les unités par statut">
                <button
                  type="button"
                  className={serviceStatusFilter === 'all' ? styles.segmentedActive : ''}
                  onClick={() => setServiceStatusFilter('all')}
                >
                  Toutes
                </button>
                <button
                  type="button"
                  className={serviceStatusFilter === 'active' ? styles.segmentedActive : ''}
                  onClick={() => setServiceStatusFilter('active')}
                >
                  Actives
                </button>
                <button
                  type="button"
                  className={serviceStatusFilter === 'inactive' ? styles.segmentedActive : ''}
                  onClick={() => setServiceStatusFilter('inactive')}
                >
                  Inactives
                </button>
              </div>
            )}
          </div>

          <div className={styles.serviceList}>
            {filteredServices.map((service) => (
              <button
                key={service.id}
                type="button"
                className={`${styles.serviceItem} ${activeServiceId === service.id ? styles.serviceItemActive : ''}`}
                onClick={() => selectService(service.id)}
                aria-current={activeServiceId === service.id ? 'true' : undefined}
              >
                <span className={styles.serviceIcon} aria-hidden="true">
                  <Building2 size={15} />
                </span>
                <span className={styles.serviceMain}>
                  <span className={styles.serviceTopLine}>
                    <span className={styles.serviceCode}>{service.code}</span>
                    {typeof service.is_active === 'boolean' && (
                      <span className={`${styles.statusPill} ${service.is_active ? styles.statusActive : styles.statusInactive}`}>
                        {service.is_active ? 'Actif' : 'Inactif'}
                      </span>
                    )}
                  </span>
                  <span className={styles.serviceLabel} title={service.libelle}>{service.libelle}</span>
                  <span className={styles.serviceMeta}>
                    {loadingCounts ? 'Chargement...' : `${rubriqueCounts[service.id] ?? 0} postes autorisés`}
                  </span>
                </span>
              </button>
            ))}
            {services.length === 0 && (
              <div className={styles.emptyState}>Aucune unité disponible.</div>
            )}
            {services.length > 0 && filteredServices.length === 0 && (
              <div className={styles.emptyState}>Aucun résultat de recherche.</div>
            )}
          </div>
        </aside>

        <ServiceAccessManager
          serviceId={activeServiceId}
          serviceLabel={selectedService ? `${selectedService.code} - ${selectedService.libelle}` : undefined}
          serviceCode={selectedService?.code}
          serviceActive={selectedService?.is_active}
          onDirtyChange={setHasUnsavedChanges}
          onExit={goToServicesAndCommissions}
        />
      </section>
    </div>
  )
}
