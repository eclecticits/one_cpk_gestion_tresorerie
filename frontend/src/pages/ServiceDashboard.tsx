import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, Mail } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { getServiceConsumption, getServices } from '../api/services'
import type { Service, ServiceConsumption } from '../types'
import { toNumber } from '../utils/amount'
import styles from './ServiceDashboard.module.css'
import { generateServiceBudgetReportPDF } from '../utils/pdfGenerator'
import { getPrintSettings } from '../api/settings'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../hooks/useToast'

export default function ServiceDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [services, setServices] = useState<Service[]>([])
  const [statsMap, setStatsMap] = useState<Record<number, ServiceConsumption>>({})
  const [selectedServiceId, setSelectedServiceId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fiscalYear, setFiscalYear] = useState<number | null>(null)
  const detailRef = useRef<HTMLDivElement | null>(null)
  const isServiceUser = Boolean(user?.service_ids?.length || user?.service_id) && user?.role !== 'admin' && user?.role !== 'super_admin'
  const { notifySuccess } = useToast()

  const getServiceBadgeClass = (code: string) => {
    const upper = code.toUpperCase()
    if (upper === 'FORCO') return styles.badgeBlue
    if (upper === 'STAGE') return styles.badgePurple
    if (upper === 'ADMIN') return styles.badgeSlate
    if (upper === 'FARC') return styles.badgeEmerald
    if (upper === 'TABLEAU') return styles.badgeIndigo
    return styles.badgeDefault
  }

  const getBudgetStatus = (rate: number, hasBudget: boolean) => {
    if (!hasBudget) return { label: 'Aucun budget', className: styles.badgeMuted, pulse: false }
    if (rate >= 90) return { label: 'Critique', className: styles.badgeDanger, pulse: true }
    if (rate >= 70) return { label: 'Attention', className: styles.badgeWarn, pulse: false }
    return { label: 'Sain', className: styles.badgeSafe, pulse: false }
  }

  const formatUsd = (value: string | number | null | undefined) =>
    new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(value))

  const reloadAll = async (includeInactive: boolean = true) => {
    const serviceList = await getServices(includeInactive ? undefined : { active: true })
    const safeServices = Array.isArray(serviceList) ? serviceList : []
    setServices(safeServices)

    const statsEntries = await Promise.all(
      safeServices.map(async (service) => {
        const stats = await getServiceConsumption(service.id)
        return [service.id, stats] as const
      })
    )
    const nextMap: Record<number, ServiceConsumption> = {}
    statsEntries.forEach(([id, stats]) => {
      nextMap[id] = stats
    })
    setStatsMap(nextMap)
    setSelectedServiceId((prev) => prev ?? safeServices[0]?.id ?? null)
  }

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        if (cancelled) return
        await reloadAll(true)
        try {
          const settings = await getPrintSettings()
          if (!cancelled && settings?.fiscal_year) {
            setFiscalYear(Number(settings.fiscal_year))
          }
        } catch {
          if (!cancelled) setFiscalYear(null)
        }
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Erreur de chargement des services.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const selectedStats = selectedServiceId ? statsMap[selectedServiceId] : null
  const selectedService = useMemo(
    () => services.find((service) => service.id === selectedServiceId) || null,
    [services, selectedServiceId]
  )

  const getResponsableLabel = (service: Service) => {
    const responsable = service.responsable
    if (!responsable) return ''
    return `${responsable.prenom || ''} ${responsable.nom || ''}`.trim() || responsable.email || 'Responsable'
  }

  const openServiceDetail = (serviceId: number) => {
    navigate(`/services/mon-espace/${serviceId}`)
    const service = services.find((item) => item.id === serviceId)
    if (service) {
      notifySuccess('Ouverture commission', `${service.code} - ${service.libelle}`)
    } else {
      notifySuccess('Ouverture commission', 'Commission sélectionnée.')
    }
  }

  const handlePrintServiceReport = async () => {
    if (!selectedService || !selectedStats) return
    const lignes = selectedStats.detail_par_rubrique.map((row) => ({
      code: row.code || '',
      libelle: row.libelle || '',
      montant_prevu: 0,
      montant_engage: 0,
      montant_paye: row.total_paye || 0,
      montant_disponible: 0,
      pourcentage_consomme: 0,
    }))
    await generateServiceBudgetReportPDF({
      lignes,
      annee: fiscalYear ?? new Date().getFullYear(),
      vue: 'DEPENSE',
      serviceLabel: `${selectedService.code} - ${selectedService.libelle}`,
      totals: {
        recettes: Number(selectedStats.total_recettes || 0),
        depenses: Number(selectedStats.total_depenses || 0),
        solde: Number(selectedStats.total_recettes || 0) - Number(selectedStats.total_depenses || 0),
      },
    })
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title={isServiceUser ? 'Mes commissions' : 'Services & Commissions'}
        subtitle={
          isServiceUser
            ? 'Sélectionnez une commission pour ouvrir son portail.'
            : 'Suivi des dépenses et recettes par commission / service.'
        }
      />

      {loading && (
        <section className={styles.cards}>
          {Array.from({ length: 6 }).map((_, idx) => (
            <div key={`service-skeleton-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonHeader}>
                <div className={styles.skeletonIcon} />
                <div className={styles.skeletonDot} />
              </div>
              <div className={styles.skeletonTitle} />
              <div className={styles.skeletonMeta} />
              <div className={styles.skeletonRow} />
              <div className={styles.skeletonRow} />
            </div>
          ))}
        </section>
      )}
      {!loading && error && <div className={styles.stateError}>{error}</div>}

      {!loading && !error && (
        <>
          <section className={styles.cards}>
            {services.map((service) => {
              const stats = statsMap[service.id]
              const responsable = service.responsable
              const responsableLabel = getResponsableLabel(service)
              const isSelected = selectedServiceId === service.id
              return (
                <div
                  key={service.id}
                  className={`${styles.card} ${isSelected ? styles.cardActive : ''}`}
                  onClick={() => openServiceDetail(service.id)}
                >
                  <div className={styles.cardHeader}>
                    <div className={styles.cardIcon}>
                      <Building2 size={20} />
                    </div>
                    <span className={styles.codeBadge}>ID {service.code}</span>
                  </div>
                  <div className={styles.cardTitle}>{service.libelle}</div>
                  <div className={styles.cardMeta}>
                    {(() => {
                      const totalBudget = Number(stats?.total_budget_prevu ?? 0)
                      const totalDepenses = Number(stats?.total_depenses ?? 0)
                      const rate = totalBudget > 0 ? (totalDepenses / totalBudget) * 100 : 0
                      const status = getBudgetStatus(rate, totalBudget > 0)
                      return (
                        <span className={`${styles.badge} ${status.className} ${status.pulse ? styles.badgePulse : ''}`}>
                          {status.label}
                        </span>
                      )
                    })()}
                    <span className={`${styles.badge} ${getServiceBadgeClass(service.code)}`}>
                      {service.code}
                    </span>
                  </div>
                  <div className={styles.responsable}>
                    <div className={styles.responsableLabel}>Responsable</div>
                    {responsable ? (
                      <div className={styles.responsableInfo}>
                        <div className={styles.responsableAvatar}>{responsableLabel ? responsableLabel[0] : '?'}</div>
                        <div>
                          <div className={styles.responsableName}>{responsableLabel}</div>
                          {responsable.email && (
                            <div className={styles.responsableEmail}>
                              <Mail size={12} /> {responsable.email}
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className={styles.responsableEmpty}>Aucun responsable assigné</div>
                    )}
                  </div>
                  <div className={styles.cardMetrics}>
                    <div>
                      <span>Dépenses</span>
                      <strong>{formatUsd(stats?.total_depenses ?? 0)}</strong>
                    </div>
                    <div>
                      <span>Recettes</span>
                      <strong>{formatUsd(stats?.total_recettes ?? 0)}</strong>
                    </div>
                    <div>
                      <span>Réquisitions en attente</span>
                      <strong>{stats?.requisitions_en_attente ?? 0}</strong>
                    </div>
                  </div>
                  <div className={styles.cardActions}>
                    <button
                      type="button"
                      className={styles.openButton}
                      onClick={(event) => {
                        event.stopPropagation()
                        openServiceDetail(service.id)
                      }}
                    >
                      {isServiceUser ? 'Ouvrir la commission' : 'Voir le détail'}
                    </button>
                  </div>
                </div>
              )
            })}
            {services.length === 0 && <div className={styles.state}>Aucun service disponible.</div>}
          </section>

          {!isServiceUser && (
          <section className={styles.detail} ref={detailRef}>
            <div className={styles.detailHeader}>
              <h2>
                {selectedService
                  ? `Consommation par poste budgétaire — ${selectedService.code}`
                  : 'Consommation par poste budgétaire'}
              </h2>
              {selectedStats && (
                <div className={styles.totals}>
                  <span>Dépenses: {formatUsd(selectedStats.total_depenses)}</span>
                  <span>Recettes: {formatUsd(selectedStats.total_recettes)}</span>
                  <button
                    type="button"
                    className={styles.printButton}
                    onClick={handlePrintServiceReport}
                    disabled={!selectedServiceId}
                  >
                    Imprimer rapport service
                  </button>
                </div>
              )}
            </div>

            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Poste budgétaire</th>
                    <th>Payé (USD)</th>
                  </tr>
                </thead>
                <tbody>
                  {(selectedStats?.detail_par_rubrique ?? []).map((row, idx) => (
                    <tr key={`${row.budget_poste_id ?? idx}-${idx}`}>
                      <td>{row.code || '-'}</td>
                      <td>{row.libelle || '-'}</td>
                      <td>{formatUsd(row.total_paye)}</td>
                    </tr>
                  ))}
                  {(selectedStats?.detail_par_rubrique ?? []).length === 0 && (
                    <tr>
                      <td colSpan={3} className={styles.emptyCell}>
                        Aucun mouvement enregistré pour ce service.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
          )}
        </>
      )}

    </div>
  )
}
