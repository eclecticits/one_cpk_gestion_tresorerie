import { useEffect, useState, useMemo, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { getDashboardStats } from '../api/dashboard'
import { getCashForecast } from '../api/ai'
import { getRapportCloture } from '../api/reports'
import { getBudgetSummary } from '../api/budget'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { format, startOfDay, endOfDay, startOfWeek, endOfWeek, startOfMonth, endOfMonth, startOfYear, endOfYear, subDays, addDays } from 'date-fns'
import styles from './Dashboard.module.css'
import { ApiError } from '../lib/apiClient'
import { toNumber } from '../utils/amount'
import { generateCloturePDF } from '../utils/pdfClotureGenerator'
import type { Money } from '../types'
import type { DashboardStatsResponse } from '../types/dashboard'
import type { CashForecast } from '../api/ai'

type PeriodType = 'today' | 'week' | 'month' | 'year' | 'custom'

interface Stats {
  totalEncaissements: number
  totalSorties: number
  requisitionsEnAttente: number
  solde: number
  soldeActuel: number
  encaissementsJour: number
  sortiesJour: number
  soldeJour: number
  maxCaisseAmount: number
  caisseOverlimit: boolean
}

interface DailyStats {
  date: string
  encaissements: number
  sorties: number
  solde: number
}

interface BudgetSummary {
  annee: number | null
  recettes: { prevu: number; reel: number }
  depenses: { prevu: number; reel: number; engage?: number; paye?: number }
}

const sortDailyStatsDesc = (items: DailyStats[]) => {
  return [...items].sort((a, b) => {
    const aTime = new Date(a.date).getTime()
    const bTime = new Date(b.date).getTime()
    return bTime - aTime
  })
}

export default function Dashboard() {
  const { user } = useAuth()
  const location = useLocation()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const [stats, setStats] = useState<Stats>({
    totalEncaissements: 0,
    totalSorties: 0,
    requisitionsEnAttente: 0,
    solde: 0,
    soldeActuel: 0,
    encaissementsJour: 0,
    sortiesJour: 0,
    soldeJour: 0,
    maxCaisseAmount: 0,
    caisseOverlimit: false,
  })
  const [dailyStats, setDailyStats] = useState<DailyStats[]>([])
  const [forecast, setForecast] = useState<CashForecast | null>(null)
  const [forecastMode, setForecastMode] = useState<'baseline' | 'stress'>('baseline')
  const [forecastError, setForecastError] = useState<string | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [fabOpen, setFabOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [budgetSummary, setBudgetSummary] = useState<BudgetSummary | null>(null)
  const [periodType, setPeriodType] = useState<PeriodType>('month')
  const [customDateDebut, setCustomDateDebut] = useState('')
  const [customDateFin, setCustomDateFin] = useState('')
  const [clotureDate, setClotureDate] = useState(() => format(new Date(), 'yyyy-MM-dd'))
  const [clotureLoading, setClotureLoading] = useState(false)
  const [clotureError, setClotureError] = useState<string | null>(null)

  const canView = useCallback((permission: string) => hasPermission(permission), [hasPermission])

  const hasEncaissements = useMemo(() => canView('encaissements'), [canView])
  const hasSorties = useMemo(() => canView('sorties_fonds'), [canView])
  const hasRequisitions = useMemo(() => canView('requisitions'), [canView])
  const hasRapports = useMemo(() => canView('rapports'), [canView])
  const hasBudget = useMemo(() => canView('budget'), [canView])

  const budgetRecettes = budgetSummary?.recettes
  const budgetDepenses = budgetSummary?.depenses
  const depensesPayee = budgetDepenses?.paye ?? budgetDepenses?.reel ?? 0
  const depensesEngagee = budgetDepenses?.engage ?? 0
  const recettesPct = budgetRecettes?.prevu ? Math.min(120, (budgetRecettes.reel / budgetRecettes.prevu) * 100) : 0
  const depensesPct = budgetDepenses?.prevu ? Math.min(120, (depensesPayee / budgetDepenses.prevu) * 100) : 0
  const netBudget = (budgetRecettes?.reel || 0) - depensesPayee

  const getPeriodDates = useCallback(() => {
    const now = new Date()
    let dateDebut: Date
    let dateFin: Date

    switch (periodType) {
      case 'today':
        dateDebut = startOfDay(now)
        dateFin = endOfDay(now)
        break
      case 'week':
        dateDebut = startOfWeek(now, { weekStartsOn: 1 })
        dateFin = endOfWeek(now, { weekStartsOn: 1 })
        break
      case 'month':
        dateDebut = startOfMonth(now)
        dateFin = endOfMonth(now)
        break
      case 'year':
        dateDebut = startOfYear(now)
        dateFin = endOfYear(now)
        break
      case 'custom':
        if (customDateDebut && customDateFin) {
          dateDebut = startOfDay(new Date(customDateDebut))
          dateFin = endOfDay(new Date(customDateFin))
        } else {
          dateDebut = startOfMonth(now)
          dateFin = endOfMonth(now)
        }
        break
      default:
        dateDebut = startOfMonth(now)
        dateFin = endOfMonth(now)
    }

    return {
      dateDebut: format(dateDebut, 'yyyy-MM-dd'),
      dateFin: format(dateFin, 'yyyy-MM-dd')
    }
  }, [periodType, customDateDebut, customDateFin])

  const normalizeDashboardResponse = (raw: any): DashboardStatsResponse | null => {
    if (raw?.stats && Array.isArray(raw?.daily_stats)) {
      return raw as DashboardStatsResponse
    }

    if (
      raw &&
      (raw.total_encaissements_period !== undefined ||
        raw.total_sorties_period !== undefined ||
        raw.solde_period !== undefined)
    ) {
      // TODO(remove-legacy-dashboard-shape): supprimer ce fallback après migration complète.
      return {
        stats: {
          total_encaissements_period: Number(raw.total_encaissements_period ?? 0),
          total_encaissements_jour: Number(raw.total_encaissements_jour ?? 0),
          total_sorties_period: Number(raw.total_sorties_period ?? 0),
          total_sorties_jour: Number(raw.total_sorties_jour ?? 0),
          solde_period: Number(raw.solde_period ?? 0),
          solde_actuel: Number(raw.solde_actuel ?? 0),
          solde_jour: Number(raw.solde_jour ?? 0),
          requisitions_en_attente: Number(raw.requisitions_en_attente ?? 0),
          max_caisse_amount: Number(raw.max_caisse_amount ?? 0),
          caisse_overlimit: Boolean(raw.caisse_overlimit ?? false),
        },
        daily_stats: Array.isArray(raw.daily_stats) ? raw.daily_stats : [],
        period: raw.period ?? null,
      }
    }

    return null
  }

  const loadStats = useCallback(async () => {
    try {
      if (!loading) setIsRefreshing(true)
      setErrorMessage(null)
      setForecastError(null)
      const { dateDebut, dateFin } = getPeriodDates()

      const [res, budgetRes] = await Promise.all([
        getDashboardStats({
          period_type: periodType,
          date_debut: dateDebut,
          date_fin: dateFin,
        }),
        getBudgetSummary(),
      ])

      const normalized = normalizeDashboardResponse(res)
      if (!normalized) {
        throw new Error('Réponse dashboard invalide')
      }

      if (normalized?.stats) {
        setStats({
          totalEncaissements: toNumber(normalized.stats.total_encaissements_period),
          totalSorties: toNumber(normalized.stats.total_sorties_period),
          requisitionsEnAttente:
            typeof normalized.stats.requisitions_en_attente === 'number' ? normalized.stats.requisitions_en_attente : 0,
          solde: toNumber(normalized.stats.solde_period),
          soldeActuel: toNumber(normalized.stats.solde_actuel),
          encaissementsJour: toNumber(normalized.stats.total_encaissements_jour),
          sortiesJour: toNumber(normalized.stats.total_sorties_jour),
          soldeJour: toNumber(normalized.stats.solde_jour),
          maxCaisseAmount: toNumber((normalized.stats as any).max_caisse_amount ?? 0),
          caisseOverlimit: Boolean((normalized.stats as any).caisse_overlimit ?? false),
        })
      }

      if (Array.isArray(normalized?.daily_stats) && normalized.daily_stats.length > 0) {
        setDailyStats(
          sortDailyStatsDesc(
            normalized.daily_stats.map((item: any) => ({
              ...item,
              encaissements: toNumber(item.encaissements),
              sorties: toNumber(item.sorties),
              solde: toNumber(item.solde),
            })) as any
          )
        )
      } else {
        // keep a stable UI even while backend migration is in progress
        const last7Days: DailyStats[] = []
        for (let i = 0; i <= 6; i++) {
          const d = format(subDays(new Date(), i), 'yyyy-MM-dd')
          last7Days.push({ date: d, encaissements: 0, sorties: 0, solde: 0 })
        }
        setDailyStats(sortDailyStatsDesc(last7Days))
      }

      if (budgetRes) {
        setBudgetSummary(budgetRes)
      }

      if (hasEncaissements || hasSorties) {
        try {
          const forecastRes = await getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 })
          setForecast(forecastRes)
        } catch (error: any) {
          console.error('Error loading forecast:', error)
          setForecastError('Impossible de charger la projection de trésorerie.')
        }
      }
    } catch (error: any) {
      console.error('Error loading stats:', error)
      const status = error instanceof ApiError ? `HTTP ${error.status}` : null
      const detail = error?.payload?.detail || error?.payload?.message || error?.message || null
      const parts = [status, detail].filter(Boolean).join(' - ')
      setErrorMessage(
        parts
          ? `Impossible de charger le tableau de bord. (${parts})`
          : "Impossible de charger le tableau de bord. Vérifie ton accès ou le serveur API."
      )
    } finally {
      setLoading(false)
      setIsRefreshing(false)
    }
  }, [getPeriodDates, periodType, loading, hasEncaissements, hasSorties])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (params.get('stress') === '1') {
      setForecastMode('stress')
    }
    if (params.get('focus') === 'forecast') {
      const el = document.getElementById('cash-forecast')
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }, [location.search])

  useEffect(() => {
    if (!permissionsLoading) {
      loadStats()
    }
  }, [loadStats, permissionsLoading])

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 720)
      if (window.innerWidth > 720) {
        setFabOpen(false)
      }
    }
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    if (permissionsLoading) return
    const intervalId = window.setInterval(() => {
      loadStats()
    }, 300000)
    return () => window.clearInterval(intervalId)
  }, [loadStats, permissionsLoading])

  useEffect(() => {
    if (permissionsLoading) return
    const handleRefresh = () => {
      loadStats()
    }
    const handleVisibilityChange = () => {
      if (!document.hidden) handleRefresh()
    }
    window.addEventListener('dashboard-refresh', handleRefresh)
    window.addEventListener('focus', handleRefresh)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('dashboard-refresh', handleRefresh)
      window.removeEventListener('focus', handleRefresh)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [loadStats, permissionsLoading])

  const formatCurrency = useCallback((amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }, [])

  const handleImprimerCloture = useCallback(async () => {
    try {
      setClotureLoading(true)
      setClotureError(null)
      const report = await getRapportCloture({ date_jour: clotureDate })
      generateCloturePDF(report)
    } catch (error: any) {
      console.error('Erreur lors de la génération du rapport de clôture', error)
      const status = error instanceof ApiError ? `HTTP ${error.status}` : null
      const detail = error?.payload?.detail || error?.payload?.message || error?.message || null
      const parts = [status, detail].filter(Boolean).join(' - ')
      setClotureError(parts || 'Impossible de générer le rapport de clôture.')
    } finally {
      setClotureLoading(false)
    }
  }, [clotureDate])

  const displayedDailyStats = isMobile ? dailyStats.slice(-7) : dailyStats

  const hasAnyPermission = hasEncaissements || hasSorties || hasRequisitions || hasRapports

  const periodLabel = useMemo(() => {
    switch (periodType) {
      case 'today': return 'du jour'
      case 'week': return 'de la semaine'
      case 'month': return 'du mois'
      case 'year': return 'de l\'année'
      case 'custom': return 'de la période'
      default: return 'du mois'
    }
  }, [periodType])

  const statCards = useMemo(() => {
    const cards: Array<{
      key: string
      label: string
      value: string
      tone: 'green' | 'red' | 'blue' | 'amber'
      icon: 'cash' | 'arrow' | 'balance' | 'pending'
    }> = []

    if (hasEncaissements) {
      cards.push({
        key: 'encaissements',
        label: `Encaissements ${periodLabel}`,
        value: formatCurrency(stats.totalEncaissements),
        tone: 'green',
        icon: 'cash'
      })
    }

    if (hasSorties) {
      cards.push({
        key: 'sorties',
        label: `Sorties ${periodLabel}`,
        value: formatCurrency(stats.totalSorties),
        tone: 'red',
        icon: 'arrow'
      })
    }

    if (hasEncaissements && hasSorties) {
      cards.push({
        key: 'solde',
        label: `Solde ${periodLabel}`,
        value: formatCurrency(stats.solde),
        tone: 'blue',
        icon: 'balance'
      })
      cards.push({
        key: 'solde_actuel',
        label: 'Solde actuel',
        value: formatCurrency(stats.soldeActuel),
        tone: 'blue',
        icon: 'balance'
      })
    }

    if (hasRequisitions) {
      cards.push({
        key: 'requisitions',
        label: 'Réquisitions en attente',
        value: String(stats.requisitionsEnAttente),
        tone: 'amber',
        icon: 'pending'
      })
    }

    return cards
  }, [
    hasEncaissements,
    hasSorties,
    hasRequisitions,
    periodLabel,
    stats.totalEncaissements,
    stats.totalSorties,
    stats.solde,
    stats.soldeActuel,
    stats.requisitionsEnAttente,
    formatCurrency,
  ])

  const forecastView = useMemo(() => {
    if (!forecast) return null
    const projection = forecastMode === 'stress' ? forecast.stress_projection : forecast.baseline_projection
    const threshold = forecast.reserve_threshold || 0
    let tone: 'ok' | 'warn' | 'critical' = 'ok'
    if (projection <= threshold) {
      tone = 'critical'
    } else if (projection <= threshold * 2) {
      tone = 'warn'
    }

    const dailyNet = forecast.net_total / Math.max(1, forecast.lookback_days)
    let tensionDate: string | null = null
    if (dailyNet < 0 && projection > threshold) {
      const daysToThreshold = Math.ceil((projection - threshold) / Math.abs(dailyNet))
      tensionDate = format(addDays(new Date(), daysToThreshold), 'dd/MM/yyyy')
    }

    const pressurePct = Math.round((forecast.pressure_ratio || 0) * 100)
    const advice =
      tone === 'critical'
        ? `⚠️ Attention : la projection passe sous la réserve critique (${formatCurrency(threshold)}).`
        : tone === 'warn'
        ? `Vigilance : la marge de sécurité devient serrée.`
        : `Trésorerie saine sur l'horizon projeté.`

    return {
      projection,
      tone,
      tensionDate,
      pressurePct,
      advice,
    }
  }, [forecast, forecastMode, formatCurrency])

  if (loading || permissionsLoading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonStats}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`dash-skel-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
              <div className={styles.skeletonLine} />
            </div>
          ))}
        </div>
        <div className={styles.skeletonBlock} />
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {fabOpen && (
        <button
          type="button"
          className={styles.fabOverlay}
          aria-label="Fermer le menu rapide"
          onClick={() => setFabOpen(false)}
        />
      )}
      <div className={styles.header}>
        <div>
          <h1>Tableau de bord des opérations financières</h1>
          <p>Bienvenue, {user?.prenom} {user?.nom}</p>
        </div>
        {hasAnyPermission && (
          <button onClick={() => loadStats()} className={styles.refreshBtn} disabled={isRefreshing}>
            {isRefreshing ? 'Actualisation...' : 'Actualiser'}
          </button>
        )}
      </div>

      {!hasAnyPermission && (
        <div style={{
          padding: '40px',
          background: '#fffbeb',
          border: '1px solid #fcd34d',
          borderRadius: '8px',
          textAlign: 'center',
          margin: '20px 0'
        }}>
          <h2 style={{ color: '#92400e', marginBottom: '12px', fontSize: '20px' }}>
            Aucun accès configuré
          </h2>
          <p style={{ color: '#78350f', fontSize: '15px', lineHeight: '1.6' }}>
            Votre compte n'a pas encore de permissions d'accès aux modules.<br />
            Veuillez contacter l'administrateur pour obtenir les droits nécessaires.
          </p>
        </div>
      )}

      {hasAnyPermission && (
        <div className={styles.periodCard}>
          <h3 className={styles.periodTitle}>Période d'affichage</h3>
          <div className={styles.periodButtons}>
            <button
              onClick={() => setPeriodType('today')}
              className={`${styles.periodBtn} ${periodType === 'today' ? styles.periodBtnActive : ''}`}
            >
              Aujourd'hui
            </button>
            <button
              onClick={() => setPeriodType('week')}
              className={`${styles.periodBtn} ${periodType === 'week' ? styles.periodBtnActive : ''}`}
            >
              Cette semaine
            </button>
            <button
              onClick={() => setPeriodType('month')}
              className={`${styles.periodBtn} ${periodType === 'month' ? styles.periodBtnActive : ''}`}
            >
              Ce mois
            </button>
            <button
              onClick={() => setPeriodType('year')}
              className={`${styles.periodBtn} ${periodType === 'year' ? styles.periodBtnActive : ''}`}
            >
              Cette année
            </button>
            <button
              onClick={() => setPeriodType('custom')}
              className={`${styles.periodBtn} ${periodType === 'custom' ? styles.periodBtnActive : ''}`}
            >
              Personnalisé
            </button>
          </div>

          {periodType === 'custom' && (
            <div className={styles.customDates}>
              <div className={styles.dateField}>
                <label>Date début</label>
                <input
                  type="date"
                  value={customDateDebut}
                  onChange={(e) => setCustomDateDebut(e.target.value)}
                />
              </div>
              <div className={styles.dateField}>
                <label>Date fin</label>
                <input
                  type="date"
                  value={customDateFin}
                  onChange={(e) => setCustomDateFin(e.target.value)}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {errorMessage && (
        <div className={styles.alert} role="alert" style={{ marginBottom: '16px' }}>
          <div>{errorMessage}</div>
          <button onClick={() => loadStats()} className={styles.retryBtn} disabled={loading}>
            Réessayer
          </button>
        </div>
      )}

      {stats.caisseOverlimit && stats.maxCaisseAmount > 0 && (
        <div className={styles.alert} role="alert" style={{ marginBottom: '16px', borderColor: '#dc2626', color: '#b91c1c' }}>
          <div>
            Alerte caisse : le solde actuel ({formatCurrency(stats.soldeActuel)}) dépasse le plafond configuré ({formatCurrency(stats.maxCaisseAmount)}).
          </div>
        </div>
      )}

      <div className={styles.statsGrid}>
        {statCards.map(card => (
          <div key={card.key} className={`${styles.statCard} ${styles[`statTone${card.tone}`]}`}>
            <div className={styles.statIcon}>
              {card.icon === 'cash' && (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                </svg>
              )}
              {card.icon === 'arrow' && (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12H3M16 5l-4 7 4 7"/>
                </svg>
              )}
              {card.icon === 'balance' && (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="16" rx="2" ry="2"/>
                  <line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
              )}
              {card.icon === 'pending' && (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
              )}
            </div>
            <div className={styles.statContent}>
              <div className={styles.statLabel}>{card.label}</div>
              <div className={`${styles.statValue} ${isRefreshing ? styles.statValueRefreshing : ''}`}>
                {card.value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {(hasEncaissements || hasSorties) && (
        <>
          {forecastError && (
            <div className={styles.alert} role="alert" style={{ marginBottom: '16px' }}>
              <div>{forecastError}</div>
            </div>
          )}
          {forecast && forecastView && (
            <div
              id="cash-forecast"
              className={`${styles.forecastWidget} ${
                forecastView.tone === 'critical'
                  ? styles.forecastCritical
                  : forecastView.tone === 'warn'
                  ? styles.forecastWarn
                  : ''
              }`}
            >
              <div className={styles.forecastHeader}>
                <div>
                  <h3>Projection à 30 jours</h3>
                  <p>Solde actuel + flux moyens (30j)</p>
                </div>
                <span className={`${styles.riskBadge} ${styles[`risk${forecastView.tone}`]}`}>
                  Risque : {forecastView.tone === 'critical' ? 'Élevé' : forecastView.tone === 'warn' ? 'Modéré' : 'Faible'}
                </span>
              </div>

              <div className={styles.toggleContainer}>
                <span className={forecastMode === 'baseline' ? styles.toggleActive : styles.toggleLabel}>Réaliste</span>
                <label className={styles.toggleSwitch}>
                  <input
                    type="checkbox"
                    checked={forecastMode === 'stress'}
                    onChange={() => setForecastMode((prev) => (prev === 'stress' ? 'baseline' : 'stress'))}
                  />
                  <span className={styles.toggleSlider} />
                </label>
                <span className={forecastMode === 'stress' ? styles.toggleActive : styles.toggleLabel}>Stress Test</span>
              </div>

              <div className={styles.forecastBody}>
                <div className={styles.projectedAmount}>{formatCurrency(forecastView.projection)}</div>
                {forecastMode === 'stress' && forecast.pending_total > 0 && (
                  <div className={styles.stressInfo}>
                    Inclut {formatCurrency(forecast.pending_total)} de réquisitions en attente.
                  </div>
                )}
                <div className={styles.progressBarContainer}>
                  <div
                    className={`${styles.progressBarFill} ${
                      forecastView.tone === 'critical'
                        ? styles.progressCritical
                        : forecastView.tone === 'warn'
                        ? styles.progressWarn
                        : styles.progressOk
                    }`}
                    style={{ width: `${forecastView.pressurePct}%` }}
                  />
                </div>
                <p className={styles.advice}>
                  {forecastView.advice}
                  {forecastView.tensionDate && ` Tension estimée vers le ${forecastView.tensionDate}.`}
                </p>
                {forecastMode === 'stress' && forecast.autonomy_days !== null && (
                  <div className={styles.autonomyHint}>
                    Autonomie estimée : {forecast.autonomy_days} jours en cas de validation totale.
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {hasBudget && budgetSummary && (
        <div className={styles.budgetOverview}>
          <div className={styles.budgetChartCard}>
            <div className={styles.budgetChartHeader}>
              <div>
                <h3>Performance budgétaire</h3>
                <p>Exercice {budgetSummary.annee ?? '—'} · USD</p>
              </div>
              <div className={styles.budgetSummaryMini}>
                <span>{recettesPct.toFixed(1)}% objectif</span>
                <span>{depensesPct.toFixed(1)}% payé</span>
              </div>
            </div>
            <div className={styles.barGroup}>
              <div className={styles.barRow}>
                <div className={styles.barLabel}>
                  <span className={styles.barTitle}>Recettes</span>
                  <span className={styles.barValue}>
                    {(budgetRecettes?.reel ?? 0).toLocaleString('fr-FR')} / {(budgetRecettes?.prevu ?? 0).toLocaleString('fr-FR')}
                  </span>
                </div>
                <div className={styles.barTrack}>
                  <div className={`${styles.barFill} ${styles.barRecettes}`} style={{ width: `${recettesPct}%` }} />
                </div>
              </div>
              <div className={styles.barRow}>
                <div className={styles.barLabel}>
                  <span className={styles.barTitle}>Dépenses</span>
                  <span className={styles.barValue}>
                    {depensesPayee.toLocaleString('fr-FR')} / {(budgetDepenses?.prevu ?? 0).toLocaleString('fr-FR')}
                  </span>
                  <span className={styles.barSubValue}>
                    Engagé: {depensesEngagee.toLocaleString('fr-FR')} $
                  </span>
                </div>
                <div className={styles.barTrack}>
                  <div className={`${styles.barFill} ${styles.barDepenses}`} style={{ width: `${depensesPct}%` }} />
                </div>
              </div>
            </div>
          </div>

          <div className={styles.budgetNetCard}>
            <span className={styles.budgetNetLabel}>Trésorerie nette</span>
            <strong className={netBudget >= 0 ? styles.netPositive : styles.netNegative}>
              {netBudget.toLocaleString('fr-FR')} $
            </strong>
            <p className={styles.budgetNetHint}>
              {netBudget >= 0 ? 'Disponible pour l’exercice en cours' : 'Dépassement à surveiller'}
            </p>
          </div>
        </div>
      )}

      {(hasEncaissements || hasSorties) && (
        <div className={styles.tableCard}>
          <h3 className={styles.tableTitle}>7 derniers jours</h3>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <colgroup>
                <col className={styles.dateCol} />
                <col className={styles.amountCol} />
                <col className={styles.amountCol} />
                <col className={styles.amountCol} />
              </colgroup>
              <thead>
                <tr>
                  <th className={styles.dateCol}>Date</th>
                  <th className={`${styles.numericCell} ${styles.amountCol}`}>Encaissements</th>
                  <th className={`${styles.numericCell} ${styles.amountCol}`}>Sorties</th>
                  <th className={`${styles.numericCell} ${styles.amountCol}`}>Solde</th>
                </tr>
              </thead>
              <tbody>
                {displayedDailyStats.length > 0 ? (
                  displayedDailyStats.map((day, index) => (
                    <tr key={day.date || String(index)}>
                      <td className={styles.dateCol}>{format(new Date(day.date), 'dd/MM/yyyy')}</td>
                      <td className={`${styles.numericCell} ${styles.amountCell} ${hasEncaissements ? styles.positiveCell : ''}`}>
                        {hasEncaissements ? formatCurrency(day.encaissements) : '—'}
                      </td>
                      <td className={`${styles.numericCell} ${styles.amountCell} ${hasSorties ? styles.negativeCell : ''}`}>
                        {hasSorties ? formatCurrency(day.sorties) : '—'}
                      </td>
                      <td
                        className={`${styles.numericCell} ${styles.amountCell} ${
                          hasEncaissements && hasSorties ? (day.solde >= 0 ? styles.neutralCell : styles.negativeCell) : ''
                        }`}
                      >
                        {hasEncaissements && hasSorties ? formatCurrency(day.solde) : '—'}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4}>Aucune donnée</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(hasEncaissements || hasRequisitions || hasSorties || hasRapports) && (
        <div className={styles.quickActions}>
          <h2>Actions rapides</h2>
          <div className={styles.actionsGrid}>
            {hasEncaissements && (
              <Link to="/encaissements" className={styles.actionCard}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                </svg>
                <h3>Nouvel encaissement</h3>
                <p>Enregistrer un paiement</p>
              </Link>
            )}

            {hasRequisitions && (
              <Link to="/requisitions" className={styles.actionCard}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="12" y1="18" x2="12" y2="12"/>
                  <line x1="9" y1="15" x2="15" y2="15"/>
                </svg>
                <h3>Réquisitions</h3>
                <p>Créer ou valider des réquisitions</p>
              </Link>
            )}

            {hasSorties && (
              <Link to="/sorties-fonds" className={styles.actionCard}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12H3M16 5l-4 7 4 7"/>
                </svg>
                <h3>Sorties de fonds</h3>
                <p>Effectuer les paiements</p>
              </Link>
            )}

            {hasRapports && (
              <Link to="/rapports" className={styles.actionCard}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <h3>Rapports</h3>
                <p>Consulter et exporter</p>
              </Link>
            )}

            {hasRapports && (
              <div className={styles.actionCard}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 3h18v6H3z"/>
                  <path d="M3 11h18v10H3z"/>
                  <line x1="7" y1="7" x2="17" y2="7"/>
                  <line x1="7" y1="15" x2="17" y2="15"/>
                </svg>
                <h3>PV de clôture</h3>
                <p>Générer le rapport journalier à signer.</p>
                <div className={styles.actionCardControls}>
                  <input
                    type="date"
                    value={clotureDate}
                    onChange={(e) => setClotureDate(e.target.value)}
                    className={styles.actionInput}
                  />
                  <button
                    type="button"
                    onClick={handleImprimerCloture}
                    className={styles.actionButton}
                    disabled={clotureLoading}
                  >
                    {clotureLoading ? 'Génération...' : 'Imprimer'}
                  </button>
                </div>
                {clotureError && <div className={styles.actionError}>{clotureError}</div>}
              </div>
            )}
          </div>
        </div>
      )}

      {(hasEncaissements || hasSorties) && (
        <div className={styles.fabContainer} data-open={fabOpen ? 'true' : 'false'}>
          <div className={styles.fabActions}>
            {hasEncaissements && (
              <Link to="/encaissements" className={`${styles.fabAction} ${styles.fabActionEnc}`}>
                💵 Nouvel encaissement
              </Link>
            )}
            {hasSorties && (
              <Link to="/sorties-fonds" className={`${styles.fabAction} ${styles.fabActionOut}`}>
                💸 Nouvelle sortie
              </Link>
            )}
            <Link to="/cloture-caisse" className={`${styles.fabAction} ${styles.fabActionClose}`}>
              🔒 Clôture de caisse
            </Link>
          </div>
          <button
            type="button"
            className={styles.fabMain}
            aria-label="Ouvrir les actions rapides"
            onClick={() => setFabOpen((prev) => !prev)}
          >
            +
          </button>
        </div>
      )}
    </div>
  )
}
