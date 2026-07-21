import { useEffect, useState, useMemo, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { getDashboardStats } from '../api/dashboard'
import { getCashForecast } from '../api/ai'
import { getRapportCloture } from '../api/reports'
import { getBudgetSummary } from '../api/budget'
import { getPrintSettings, type PrintSettings } from '../api/settings'
import { getTreasuryBalances } from '../api/treasury'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import { format, startOfDay, endOfDay, startOfWeek, endOfWeek, startOfMonth, endOfMonth, startOfYear, endOfYear, subDays, addDays } from 'date-fns'
import { RefreshCw } from 'lucide-react'
import styles from './Dashboard.module.css'
import { ApiError, apiRequest } from '../lib/apiClient'
import { toNumber } from '../utils/amount'
import { generateCloturePDF } from '../utils/pdfClotureGenerator'
import type { Money } from '../types'
import type { DashboardStatsResponse } from '../types/dashboard'
import type { CashForecast } from '../api/ai'
import type { TreasuryOverviewData } from '../types/treasury'
import TreasuryOverview from '../components/TreasuryOverview'
import AnimatedNumber from '../components/AnimatedNumber'
import NetworkGlobe from '../components/NetworkGlobe'

type PeriodType = 'today' | 'week' | 'month' | 'year' | 'custom'
type CurrencyCode = 'USD' | 'CDF'

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

const normalizeCurrencyCode = (value: string | null | undefined, fallback: CurrencyCode): CurrencyCode => {
  const normalized = String(value || '').toUpperCase()
  return normalized === 'CDF' ? 'CDF' : normalized === 'USD' ? 'USD' : fallback
}

const resolveDashboardCurrencyConfig = (
  printSettings: PrintSettings | null,
  orgCurrencyFallback: CurrencyCode
): { pivotCurrency: CurrencyCode; secondaryCurrency: CurrencyCode; exchangeRate: number } => {
  const pivotCurrency = normalizeCurrencyCode(printSettings?.default_currency, orgCurrencyFallback)
  const secondaryFallback: CurrencyCode = pivotCurrency === 'USD' ? 'CDF' : 'USD'
  const secondaryCurrency = normalizeCurrencyCode(printSettings?.secondary_currency, secondaryFallback)
  const exchangeRate = Number(printSettings?.exchange_rate_cdf ?? printSettings?.exchange_rate ?? 0)
  return {
    pivotCurrency,
    secondaryCurrency,
    exchangeRate: Number.isFinite(exchangeRate) && exchangeRate > 0 ? exchangeRate : 0,
  }
}

const convertFromCdfToUsd = (amount: number, exchangeRate: number) => (exchangeRate > 0 ? amount / exchangeRate : 0)
const convertFromUsdToCdf = (amount: number, exchangeRate: number) => (exchangeRate > 0 ? amount * exchangeRate : 0)

const convertToPivotCurrency = (
  usdAmount: number,
  cdfAmount: number,
  pivotCurrency: CurrencyCode,
  exchangeRate: number
) => {
  if (pivotCurrency === 'CDF') {
    return cdfAmount + convertFromUsdToCdf(usdAmount, exchangeRate)
  }
  return usdAmount + convertFromCdfToUsd(cdfAmount, exchangeRate)
}

export default function Dashboard() {
  const { user } = useAuth()
  const location = useLocation()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const { settings: orgSettings } = useOrganisationSettings()
  const aiEnabled = Boolean(orgSettings?.is_ai_enabled)
  const organisationCurrencyFallback: CurrencyCode = orgSettings?.currency_code?.toUpperCase() === 'CDF' ? 'CDF' : 'USD'
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
  const [showForecast, setShowForecast] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [fabOpen, setFabOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [budgetSummary, setBudgetSummary] = useState<BudgetSummary | null>(null)
  const [treasuryData, setTreasuryData] = useState<TreasuryOverviewData | null>(null)
  const [treasuryLoading, setTreasuryLoading] = useState(false)
  const [treasuryError, setTreasuryError] = useState<string | null>(null)
  const [periodType, setPeriodType] = useState<PeriodType>('month')
  const [customDateDebut, setCustomDateDebut] = useState('')
  const [customDateFin, setCustomDateFin] = useState('')
  const [dashboardCanal, setDashboardCanal] = useState<'ALL' | 'BANQUE' | 'CAISSE'>('ALL')
  const [dashboardCompteId, setDashboardCompteId] = useState<number | ''>('')
  const [comptesBancaires, setComptesBancaires] = useState<any[]>([])
  const [clotureDate, setClotureDate] = useState(() => format(new Date(), 'yyyy-MM-dd'))
  const [clotureLoading, setClotureLoading] = useState(false)
  const [clotureError, setClotureError] = useState<string | null>(null)
  const [printSettings, setPrintSettings] = useState<PrintSettings | null>(null)

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

  const bankAccounts = useMemo(
    () => comptesBancaires.filter((c) => String(c.account_type || 'BANK').toUpperCase() === 'BANK'),
    [comptesBancaires]
  )
  const cashAccounts = useMemo(
    () => comptesBancaires.filter((c) => String(c.account_type || 'BANK').toUpperCase() === 'CASH'),
    [comptesBancaires]
  )
  const selectedAccount = useMemo(
    () => comptesBancaires.find((c) => Number(c.id) === Number(dashboardCompteId)) || null,
    [comptesBancaires, dashboardCompteId]
  )
  const {
    pivotCurrency,
    secondaryCurrency,
    exchangeRate,
  } = useMemo(
    () => resolveDashboardCurrencyConfig(printSettings, organisationCurrencyFallback),
    [printSettings, organisationCurrencyFallback]
  )

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
      setTreasuryError(null)
      setTreasuryLoading(true)
      const { dateDebut, dateFin } = getPeriodDates()

      const accountCurrency = normalizeCurrencyCode(selectedAccount?.devise, pivotCurrency)
      const shouldLoadUsd = !selectedAccount || accountCurrency === 'USD'
      const shouldLoadCdf = !selectedAccount || accountCurrency === 'CDF'
      const baseParams = {
        period_type: periodType,
        date_debut: dateDebut,
        date_fin: dateFin,
        canal: dashboardCanal === 'ALL' ? undefined : dashboardCanal,
        compte_bancaire_id: dashboardCompteId ? Number(dashboardCompteId) : undefined,
      }

      const [usdRes, cdfRes, budgetRes, treasuryRes, printSettingsRes] = await Promise.all([
        shouldLoadUsd ? getDashboardStats({ ...baseParams, devise: 'USD' }) : Promise.resolve(null),
        shouldLoadCdf ? getDashboardStats({ ...baseParams, devise: 'CDF' }) : Promise.resolve(null),
        getBudgetSummary(),
        getTreasuryBalances().catch((err) => {
          if (err instanceof ApiError) {
            setTreasuryError(err.message)
          } else {
            setTreasuryError('Impossible de charger les soldes de trésorerie.')
          }
          return null
        }),
        getPrintSettings().catch(() => null),
      ])

      if (printSettingsRes) {
        setPrintSettings(printSettingsRes)
      }

      const activeCurrencyConfig = resolveDashboardCurrencyConfig(printSettingsRes, organisationCurrencyFallback)
      const normalizedUsd = usdRes ? normalizeDashboardResponse(usdRes) : null
      const normalizedCdf = cdfRes ? normalizeDashboardResponse(cdfRes) : null

      if (!normalizedUsd && !normalizedCdf) {
        throw new Error('Réponse dashboard invalide')
      }

      const usdStats = normalizedUsd?.stats
      const cdfStats = normalizedCdf?.stats
      const requisitionsEnAttente = typeof usdStats?.requisitions_en_attente === 'number'
        ? usdStats.requisitions_en_attente
        : typeof cdfStats?.requisitions_en_attente === 'number'
        ? cdfStats.requisitions_en_attente
        : 0
      const maxCaisseAmountRaw = toNumber((usdStats as any)?.max_caisse_amount ?? (cdfStats as any)?.max_caisse_amount ?? 0)
      const pivotMaxCaisseAmount = activeCurrencyConfig.pivotCurrency === 'CDF'
        ? convertFromUsdToCdf(maxCaisseAmountRaw, activeCurrencyConfig.exchangeRate)
        : maxCaisseAmountRaw

      if (usdStats || cdfStats) {
        const nextStats: Stats = {
          totalEncaissements: convertToPivotCurrency(
            toNumber(usdStats?.total_encaissements_period ?? 0),
            toNumber(cdfStats?.total_encaissements_period ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          totalSorties: convertToPivotCurrency(
            toNumber(usdStats?.total_sorties_period ?? 0),
            toNumber(cdfStats?.total_sorties_period ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          requisitionsEnAttente,
          solde: convertToPivotCurrency(
            toNumber(usdStats?.solde_period ?? 0),
            toNumber(cdfStats?.solde_period ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          soldeActuel: convertToPivotCurrency(
            toNumber(usdStats?.solde_actuel ?? 0),
            toNumber(cdfStats?.solde_actuel ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          encaissementsJour: convertToPivotCurrency(
            toNumber(usdStats?.total_encaissements_jour ?? 0),
            toNumber(cdfStats?.total_encaissements_jour ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          sortiesJour: convertToPivotCurrency(
            toNumber(usdStats?.total_sorties_jour ?? 0),
            toNumber(cdfStats?.total_sorties_jour ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          soldeJour: convertToPivotCurrency(
            toNumber(usdStats?.solde_jour ?? 0),
            toNumber(cdfStats?.solde_jour ?? 0),
            activeCurrencyConfig.pivotCurrency,
            activeCurrencyConfig.exchangeRate
          ),
          maxCaisseAmount: pivotMaxCaisseAmount,
          caisseOverlimit: Boolean((usdStats as any)?.caisse_overlimit ?? (cdfStats as any)?.caisse_overlimit ?? false),
        }
        setStats(nextStats)
      }

      const usdDailyStats = Array.isArray(normalizedUsd?.daily_stats) ? normalizedUsd?.daily_stats : []
      const cdfDailyStats = Array.isArray(normalizedCdf?.daily_stats) ? normalizedCdf?.daily_stats : []
      const dailyKeys = Array.from(
        new Set([
          ...usdDailyStats.map((item) => item.date),
          ...cdfDailyStats.map((item) => item.date),
        ])
      )

      if (dailyKeys.length > 0) {
        const usdDailyMap = new Map(
          usdDailyStats.map((item) => [
            item.date,
            {
              encaissements: toNumber(item.encaissements),
              sorties: toNumber(item.sorties),
              solde: toNumber(item.solde),
            },
          ])
        )
        const cdfDailyMap = new Map(
          cdfDailyStats.map((item) => [
            item.date,
            {
              encaissements: toNumber(item.encaissements),
              sorties: toNumber(item.sorties),
              solde: toNumber(item.solde),
            },
          ])
        )
        setDailyStats(
          sortDailyStatsDesc(
            dailyKeys.map((day) => {
              const usd = usdDailyMap.get(day)
              const cdf = cdfDailyMap.get(day)
              return {
                date: day,
                encaissements: convertToPivotCurrency(
                  usd?.encaissements ?? 0,
                  cdf?.encaissements ?? 0,
                  activeCurrencyConfig.pivotCurrency,
                  activeCurrencyConfig.exchangeRate
                ),
                sorties: convertToPivotCurrency(
                  usd?.sorties ?? 0,
                  cdf?.sorties ?? 0,
                  activeCurrencyConfig.pivotCurrency,
                  activeCurrencyConfig.exchangeRate
                ),
                solde: convertToPivotCurrency(
                  usd?.solde ?? 0,
                  cdf?.solde ?? 0,
                  activeCurrencyConfig.pivotCurrency,
                  activeCurrencyConfig.exchangeRate
                ),
              }
            })
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

      if (treasuryRes) {
        setTreasuryData(treasuryRes)
      }

      if (aiEnabled && showForecast && (hasEncaissements || hasSorties)) {
        try {
          const forecastRes = await getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 })
          setForecast(forecastRes)
        } catch (error: any) {
          console.error('Error loading forecast:', error)
          if (error instanceof ApiError) {
            setForecastError(error.message)
          } else {
            setForecastError('Impossible de charger la projection de trésorerie.')
          }
        }
      }
    } catch (error: any) {
      console.error('Error loading stats:', error)
      if (error instanceof ApiError) {
        // 503 already carries a clean French message (network or backend)
        setErrorMessage(
          error.status === 503
            ? error.message
            : `Impossible de charger le tableau de bord. (${error.message})`
        )
      } else {
        setErrorMessage("Impossible de charger le tableau de bord. Vérifie ton accès ou le serveur API.")
      }
    } finally {
      setLoading(false)
      setIsRefreshing(false)
      setTreasuryLoading(false)
    }
  }, [
    getPeriodDates,
    periodType,
    loading,
    hasEncaissements,
    hasSorties,
    showForecast,
    aiEnabled,
    dashboardCanal,
    dashboardCompteId,
    organisationCurrencyFallback,
    pivotCurrency,
    selectedAccount,
  ])

  useEffect(() => {
    if (!aiEnabled) {
      setShowForecast(false)
      setForecast(null)
      setForecastError(null)
    }
  }, [aiEnabled])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (params.get('stress') === '1') {
      setForecastMode('stress')
    }
    if (params.get('focus') === 'forecast') {
      setShowForecast(true)
      window.setTimeout(() => {
        const el = document.getElementById('cash-forecast')
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      }, 200)
    }
  }, [location.search])

  useEffect(() => {
    if (!permissionsLoading) {
      loadStats()
    }
  }, [loadStats, permissionsLoading])

  useEffect(() => {
    const loadComptes = async () => {
      try {
        const res = await apiRequest('GET', '/comptes-bancaires', { params: { active: true } })
        const items = Array.isArray(res) ? res : []
        setComptesBancaires(items)
      } catch (error) {
        setComptesBancaires([])
      }
    }
    loadComptes()
  }, [])

  useEffect(() => {
    if (dashboardCanal === 'ALL') {
      setDashboardCompteId('')
      return
    }
    const list = dashboardCanal === 'BANQUE' ? bankAccounts : cashAccounts
    if (!list.find((c) => Number(c.id) === Number(dashboardCompteId))) {
      setDashboardCompteId('')
    }
  }, [dashboardCanal, bankAccounts, cashAccounts, dashboardCompteId])

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

  const formatCurrencyByCode = useCallback((amount: Money, currency: 'USD' | 'CDF') => {
    return `${toNumber(amount).toLocaleString('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })} ${currency}`
  }, [])

  const formatCurrency = useCallback((amount: Money) => {
    return formatCurrencyByCode(amount, pivotCurrency)
  }, [pivotCurrency, formatCurrencyByCode])

  const showTreasuryOverview = (hasEncaissements || hasSorties) && dashboardCanal === 'ALL'
  const treasuryFallback: TreasuryOverviewData = {
    caisse: { solde_usd: 0, solde_cdf: 0 },
    comptes: [],
  }
  const treasuryView = treasuryData ?? treasuryFallback
  const treasuryBankUsd = useMemo(
    () =>
      treasuryView.comptes.reduce((acc, compte) => {
        if ((compte.devise || 'USD').toUpperCase() !== 'USD') return acc
        return acc + toNumber(compte.solde_actuel)
      }, 0),
    [treasuryView]
  )
  const treasuryBankCdf = useMemo(
    () =>
      treasuryView.comptes.reduce((acc, compte) => {
        if ((compte.devise || 'USD').toUpperCase() !== 'CDF') return acc
        return acc + toNumber(compte.solde_actuel)
      }, 0),
    [treasuryView]
  )
  const treasuryCurrentUsd = useMemo(
    () => toNumber(treasuryView.caisse.solde_usd) + treasuryBankUsd,
    [treasuryView, treasuryBankUsd]
  )
  const treasuryCurrentCdf = useMemo(
    () => toNumber(treasuryView.caisse.solde_cdf) + treasuryBankCdf,
    [treasuryView, treasuryBankCdf]
  )
  const treasuryCashPivot = useMemo(
    () =>
      convertToPivotCurrency(
        toNumber(treasuryView.caisse.solde_usd),
        toNumber(treasuryView.caisse.solde_cdf),
        pivotCurrency,
        exchangeRate
      ),
    [treasuryView, pivotCurrency, exchangeRate]
  )
  const treasuryBankPivot = useMemo(
    () => convertToPivotCurrency(treasuryBankUsd, treasuryBankCdf, pivotCurrency, exchangeRate),
    [treasuryBankUsd, treasuryBankCdf, pivotCurrency, exchangeRate]
  )
  const treasuryCurrentPivot = useMemo(
    () => convertToPivotCurrency(treasuryCurrentUsd, treasuryCurrentCdf, pivotCurrency, exchangeRate),
    [treasuryCurrentUsd, treasuryCurrentCdf, pivotCurrency, exchangeRate]
  )
  const displayedCurrentBalance = useMemo(() => {
    if (!dashboardCompteId && dashboardCanal === 'ALL' && treasuryData) {
      return treasuryCurrentPivot
    }
    if (!dashboardCompteId && dashboardCanal === 'BANQUE' && treasuryData) {
      return treasuryBankPivot
    }
    if (!dashboardCompteId && dashboardCanal === 'CAISSE' && treasuryData) {
      return treasuryCashPivot
    }
    return stats.soldeActuel
  }, [
    dashboardCanal,
    dashboardCompteId,
    treasuryData,
    treasuryCurrentPivot,
    treasuryBankPivot,
    treasuryCashPivot,
    stats.soldeActuel,
  ])

  const handleImprimerCloture = useCallback(async () => {
    try {
      setClotureLoading(true)
      setClotureError(null)
      const report = await getRapportCloture({ date_jour: clotureDate })
      generateCloturePDF(report)
    } catch (error: any) {
      console.error('Erreur lors de la génération du rapport de clôture', error)
      setClotureError(
        error instanceof ApiError
          ? (error.status === 503 ? error.message : `Impossible de générer le rapport de clôture. (${error.message})`)
          : 'Impossible de générer le rapport de clôture.'
      )
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
      rawValue: number
      format: (n: number) => string
      tone: 'green' | 'red' | 'blue' | 'amber'
      icon: 'cash' | 'arrow' | 'balance' | 'pending'
    }> = []

    if (hasEncaissements) {
      cards.push({
        key: 'encaissements',
        label: `Encaissements ${periodLabel}`,
        rawValue: toNumber(stats.totalEncaissements),
        format: (n) => formatCurrencyByCode(n, pivotCurrency),
        tone: 'green',
        icon: 'cash'
      })
    }

    if (hasSorties) {
      cards.push({
        key: 'sorties',
        label: `Sorties ${periodLabel}`,
        rawValue: toNumber(stats.totalSorties),
        format: (n) => formatCurrencyByCode(n, pivotCurrency),
        tone: 'red',
        icon: 'arrow'
      })
    }

    if (hasEncaissements && hasSorties) {
      cards.push({
        key: 'solde',
        label: `Solde ${periodLabel}`,
        rawValue: toNumber(stats.solde),
        format: (n) => formatCurrencyByCode(n, pivotCurrency),
        tone: 'blue',
        icon: 'balance'
      })
      cards.push({
        key: 'solde_actuel',
        label: 'Solde actuel',
        rawValue: toNumber(displayedCurrentBalance),
        format: (n) => formatCurrencyByCode(n, pivotCurrency),
        tone: 'blue',
        icon: 'balance'
      })
    }

    if (hasRequisitions) {
      cards.push({
        key: 'requisitions',
        label: 'Réquisitions en attente',
        rawValue: stats.requisitionsEnAttente,
        format: (n) => String(Math.round(n)),
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
    displayedCurrentBalance,
    stats.requisitionsEnAttente,
    pivotCurrency,
    formatCurrencyByCode,
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

  const [gaugeFillPct, setGaugeFillPct] = useState(0)

  useEffect(() => {
    if (!showForecast || !forecastView) {
      setGaugeFillPct(0)
      return
    }
    setGaugeFillPct(0)
    let raf2 = 0
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setGaugeFillPct(forecastView.pressurePct))
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
    }
  }, [showForecast, forecastView?.pressurePct])

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
      <div className={styles.bgGlobeWrap} aria-hidden="true">
        <NetworkGlobe size={680} className={styles.bgGlobe} />
      </div>
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
            <RefreshCw size={16} className={isRefreshing ? styles.refreshIconSpinning : styles.refreshIcon} />
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

          <div className={styles.filtersRow}>
            <div className={styles.filterField}>
              <label>Canal</label>
              <select
                value={dashboardCanal}
                onChange={(e) => setDashboardCanal(e.target.value as 'ALL' | 'BANQUE' | 'CAISSE')}
              >
                <option value="ALL">Tous</option>
                <option value="BANQUE">Banque</option>
                <option value="CAISSE">Caisse</option>
              </select>
            </div>
            <div className={styles.filterField}>
              <label>Compte</label>
              <select
                value={dashboardCompteId}
                onChange={(e) => setDashboardCompteId(e.target.value ? Number(e.target.value) : '')}
                disabled={dashboardCanal === 'ALL'}
              >
                <option value="">Tous les comptes</option>
                {(dashboardCanal === 'BANQUE' ? bankAccounts : cashAccounts).map((compte) => (
                  <option key={compte.id} value={compte.id}>
                    {dashboardCanal === 'BANQUE'
                      ? `${compte.banque?.nom || 'Banque'} - ${compte.intitule} (${compte.devise})`
                      : `${compte.intitule || 'Caisse'} (${compte.devise})`}
                  </option>
                ))}
                {dashboardCanal === 'BANQUE' && bankAccounts.length === 0 && (
                  <option disabled>Aucun compte bancaire configuré</option>
                )}
                {dashboardCanal === 'CAISSE' && cashAccounts.length === 0 && (
                  <option disabled>Aucun compte caisse configuré</option>
                )}
              </select>
            </div>
          </div>
        </div>
      )}

      {hasAnyPermission && showTreasuryOverview && (
        <TreasuryOverview
          data={treasuryView}
          fluxEntrees={stats.totalEncaissements}
          fluxSorties={stats.totalSorties}
          pivotCurrency={pivotCurrency}
          secondaryCurrency={secondaryCurrency}
          exchangeRate={exchangeRate}
          formatCurrency={formatCurrency}
          formatCurrencyByCode={formatCurrencyByCode}
          isLoading={treasuryLoading}
          errorMessage={treasuryError}
        />
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
        {statCards.map((card, index) => (
          <div
            key={card.key}
            className={`${styles.statCard} ${styles[`statTone${card.tone}`]}`}
            style={{ animationDelay: `${index * 60}ms` }}
            onMouseMove={(e) => {
              if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
              const el = e.currentTarget
              const rect = el.getBoundingClientRect()
              const px = (e.clientX - rect.left) / rect.width - 0.5
              const py = (e.clientY - rect.top) / rect.height - 0.5
              el.style.setProperty('--tilt-x', `${(-py * 6).toFixed(2)}deg`)
              el.style.setProperty('--tilt-y', `${(px * 6).toFixed(2)}deg`)
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.setProperty('--tilt-x', '0deg')
              e.currentTarget.style.setProperty('--tilt-y', '0deg')
            }}
          >
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
              <AnimatedNumber
                value={card.rawValue}
                format={card.format}
                className={`${styles.statValue} ${isRefreshing ? styles.statValueRefreshing : ''}`}
              />
            </div>
          </div>
        ))}
      </div>

      {(hasEncaissements || hasSorties) && aiEnabled && (
        <>
          <div className={styles.forecastToggleRow}>
            <button
              type="button"
              className={styles.secondaryAction}
              onClick={() => setShowForecast((prev) => !prev)}
            >
              {showForecast ? 'Masquer la projection 30 jours' : 'Afficher la projection 30 jours'}
            </button>
          </div>
          {showForecast && (
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
                        style={{ width: `${gaugeFillPct}%` }}
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
        </>
      )}
      {(hasEncaissements || hasSorties) && !aiEnabled && (
        <div className={styles.alert} role="status" style={{ marginTop: '16px' }}>
          Module IA désactivé : la projection de trésorerie est indisponible.
        </div>
      )}

      {hasBudget && budgetSummary && (
        <div className={styles.budgetOverview}>
          <div className={styles.budgetChartCard}>
            <div className={styles.budgetChartHeader}>
              <div>
                <h3>Performance budgétaire</h3>
                <p>Exercice {budgetSummary.annee ?? '—'} · {pivotCurrency}</p>
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
                    {formatCurrency(budgetRecettes?.reel ?? 0)} / {formatCurrency(budgetRecettes?.prevu ?? 0)}
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
                    {formatCurrency(depensesPayee)} / {formatCurrency(budgetDepenses?.prevu ?? 0)}
                  </span>
                  <span className={styles.barSubValue}>
                    Engagé: {formatCurrency(depensesEngagee)}
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
              {formatCurrency(netBudget)}
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
