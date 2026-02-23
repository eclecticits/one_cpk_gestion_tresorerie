import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import { getServiceConsumption, getServices } from '../api/services'
import type { Service, ServiceConsumption } from '../types'
import { toNumber } from '../utils/amount'
import styles from './ServiceDashboard.module.css'
import { generateServiceBudgetReportPDF } from '../utils/pdfGenerator'
import { getPrintSettings } from '../api/settings'
import { useAuth } from '../contexts/AuthContext'

export default function ServiceDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [services, setServices] = useState<Service[]>([])
  const [statsMap, setStatsMap] = useState<Record<number, ServiceConsumption>>({})
  const [selectedServiceId, setSelectedServiceId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fiscalYear, setFiscalYear] = useState<number | null>(null)
  const isServiceUser = Boolean(user?.service_ids?.length || user?.service_id)

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
        title={isServiceUser ? 'Mes commissions' : 'Analyse par service'}
        subtitle={isServiceUser ? 'Sélectionnez une commission pour ouvrir son portail.' : 'Suivi des dépenses et recettes par commission / service.'}
      />

      {loading && <div className={styles.state}>Chargement...</div>}
      {!loading && error && <div className={styles.stateError}>{error}</div>}

      {!loading && !error && (
        <>
          <section className={styles.cards}>
            {services.map((service) => {
              const stats = statsMap[service.id]
              return (
                <button
                  key={service.id}
                  type="button"
                  className={`${styles.card} ${
                    selectedServiceId === service.id ? styles.cardActive : ''
                  }`}
                  onClick={() => {
                    if (isServiceUser) {
                      navigate(`/services/mon-espace/${service.id}`)
                    } else {
                      setSelectedServiceId(service.id)
                    }
                  }}
                >
                  <div className={styles.cardTitle}>
                    {service.code} · {service.libelle}
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
                </button>
              )
            })}
            {services.length === 0 && <div className={styles.state}>Aucun service disponible.</div>}
          </section>

          {!isServiceUser && (
          <section className={styles.detail}>
            <div className={styles.detailHeader}>
              <h2>
                {selectedService
                  ? `Consommation par rubrique — ${selectedService.code}`
                  : 'Consommation par rubrique'}
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
                    <th>Rubrique</th>
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
