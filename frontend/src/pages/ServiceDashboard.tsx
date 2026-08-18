import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, BarChart3, Building2, FileText, Mail, TrendingDown, TrendingUp } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { getServiceConsumption, getServices } from '../api/services'
import type { Service, ServiceConsumption } from '../types'
import { toNumber } from '../utils/amount'
import styles from './ServiceDashboard.module.css'
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'export.
type PdfGeneratorModule = typeof import('../utils/pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('../utils/pdfGenerator')
  return _pdfGeneratorModulePromise
}
const generateServiceBudgetReportPDF: PdfGeneratorModule['generateServiceBudgetReportPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateServiceBudgetReportPDF(...args)
}
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
    if (upper === 'ADMIN' || upper === 'ADM') return styles.badgeSlate
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
    `${new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(toNumber(value))} USD`

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
        if (!cancelled) setError(err?.message || 'Erreur de chargement des unités opérationnelles.')
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
      notifySuccess('Ouverture unité opérationnelle', `${service.code} - ${service.libelle}`)
    } else {
      notifySuccess('Ouverture unité opérationnelle', 'Unité sélectionnée.')
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
        title={isServiceUser ? 'Mes unités opérationnelles' : 'Unités opérationnelles'}
        subtitle={
          isServiceUser
            ? 'Sélectionnez une unité pour ouvrir son espace de travail.'
            : 'Suivi des dépenses et recettes par direction, service ou commission.'
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
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSelected}
                  className={`${styles.card} ${isSelected ? styles.cardActive : ''}`}
                  onClick={() => setSelectedServiceId(service.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setSelectedServiceId(service.id)
                    }
                  }}
                >
                  <div className={styles.cardHeader}>
                    <div className={styles.cardIdentity}>
                      <div className={styles.cardIcon}>
                        <Building2 size={16} />
                      </div>
                      <span className={styles.codeBadge}>{service.code}</span>
                    </div>
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
                  </div>
                  <div className={styles.cardTitle} title={service.libelle}>{service.libelle}</div>
                  <div className={styles.cardMeta}>
                    <span className={`${styles.badge} ${getServiceBadgeClass(service.code)}`}>
                      {service.code}
                    </span>
                  </div>
                  <div className={styles.responsable}>
                    {responsable ? (
                      <div className={styles.responsableInfo}>
                        <div className={styles.responsableAvatar}>{responsableLabel ? responsableLabel[0] : '?'}</div>
                        <div>
                          <div className={styles.responsableName} title={responsableLabel}>
                            Responsable : {responsableLabel}
                          </div>
                          {responsable.email && (
                            <div className={styles.responsableEmail} title={responsable.email}>
                              <Mail size={12} /> {responsable.email}
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className={styles.responsableEmpty}>Responsable : Aucun responsable assigné</div>
                    )}
                  </div>
                  <div className={styles.cardMetrics}>
                    <div className={styles.kpiTile}>
                      <TrendingDown size={14} aria-hidden="true" />
                      <span>Dépenses</span>
                      <strong>{formatUsd(stats?.total_depenses ?? 0)}</strong>
                    </div>
                    <div className={styles.kpiTile}>
                      <TrendingUp size={14} aria-hidden="true" />
                      <span>Recettes</span>
                      <strong>{formatUsd(stats?.total_recettes ?? 0)}</strong>
                    </div>
                    <div className={styles.kpiTile}>
                      <FileText size={14} aria-hidden="true" />
                      <span>Réquisitions</span>
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
                      {isServiceUser ? "Ouvrir l'unité" : 'Voir le détail'}
                      <ArrowRight size={15} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              )
            })}
            {services.length === 0 && <div className={styles.state}>Aucune unité opérationnelle disponible.</div>}
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
                        <div className={styles.emptyBudgetState}>
                          <BarChart3 size={28} aria-hidden="true" />
                          <strong>Aucun mouvement budgétaire enregistré pour cette unité.</strong>
                          <span>Les consommations apparaîtront ici dès que des opérations seront validées.</span>
                        </div>
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
