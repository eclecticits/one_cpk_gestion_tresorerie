import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Circle } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import * as XLSX from 'xlsx'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import { usePermissions } from '../hooks/usePermissions'
import styles from './Rapports.module.css'
import { useToast } from '../hooks/useToast'
import type { ReportSummaryResponse } from '../types/reports'
import type { ReportJournalResponse } from '../types/reports'
import { toNumber } from '../utils/amount'
import { getStatusMeta } from '../utils/statusMapper'
import type { Money } from '../types'
import { generateGlobalReportPDF } from '../utils/pdfGenerator'
import { generateJournalPDF } from '../utils/pdfJournalGenerator'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Line } from 'recharts'
import { useAnnualReport } from '../hooks/useAnnualReport'
import TopExpenses from '../components/TopExpenses'
import AccessDeniedState from '../components/AccessDeniedState'

function buildQuery(params: Record<string, any>) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    sp.set(k, String(v))
  })
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

const toLocalDate = (value: string | null | undefined) => {
  if (!value) return null
  const raw = String(value)
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw)
  const parsed = dateOnly ? new Date(`${raw}T00:00:00`) : new Date(raw)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

const formatReportDate = (value: string | null | undefined, pattern = 'dd/MM/yyyy') => {
  const parsed = toLocalDate(value)
  return parsed ? format(parsed, pattern) : '-'
}

const getSortieModeLabel = (mode?: string | null) => {
  if (mode === 'cash') return 'Cash'
  if (mode === 'mobile_money') return 'Mobile Money'
  if (mode === 'card') return 'Carte (Visa)'
  if (mode === 'virement') return 'Opération bancaire'
  return mode || '-'
}

function formatRapportError(error: any): string {
  const status = typeof error?.status === 'number' ? `HTTP ${error.status}` : null
  const detail = error?.payload?.detail || error?.payload?.message || error?.message || null
  const parts = [status, detail].filter(Boolean).join(' - ')
  return parts
    ? `Impossible de charger les rapports. (${parts})`
    : "Impossible de charger les rapports. Vérifie ton accès ou le serveur API."
}

export default function Rapports() {
  const { notifyError, notifySuccess } = useToast()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { settings: orgSettings } = useOrganisationSettings()
  const aiEnabled = Boolean(orgSettings?.is_ai_enabled)
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const [dateDebut, setDateDebut] = useState(format(new Date(), 'yyyy-MM-dd'))
  const [dateFin, setDateFin] = useState(format(new Date(), 'yyyy-MM-dd'))
  const [reportCanal, setReportCanal] = useState<'ALL' | 'BANQUE' | 'CAISSE'>('ALL')
  // Défaut USD et non « Toutes » : une carte libellée $ qui cumulerait du CDF
  // est pire qu'une vue mono-devise, la table par devise restant là pour
  // signaler ce qui se passe dans l'autre.
  const [reportDevise, setReportDevise] = useState<'USD' | 'CDF' | 'ALL'>('USD')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null)
  const [sortiesWarning, setSortiesWarning] = useState<string | null>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [detailsLoaded, setDetailsLoaded] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [hasReportingAccess, setHasReportingAccess] = useState(false)
  const [checkingAccess, setCheckingAccess] = useState(true)
  const [journalCanal, setJournalCanal] = useState<'CAISSE' | 'BANQUE'>('CAISSE')
  const [journalDevise, setJournalDevise] = useState<'USD' | 'CDF'>('USD')
  const [journalCompteId, setJournalCompteId] = useState<number | ''>('')
  const [journalLoading, setJournalLoading] = useState(false)
  const [journalTableLoading, setJournalTableLoading] = useState(false)
  const [journalData, setJournalData] = useState<ReportJournalResponse | null>(null)
  const [showUnreconciledOnly, setShowUnreconciledOnly] = useState(false)
  const [reconcileDraft, setReconcileDraft] = useState<
    Record<string, { transaction_type: 'encaissement' | 'sortie'; transaction_id: string; is_reconciled: boolean }>
  >({})
  const [reconcileLoading, setReconcileLoading] = useState(false)
  const [annualYear, setAnnualYear] = useState(new Date().getFullYear())
  const [annualDevise, setAnnualDevise] = useState<'USD' | 'CDF'>('USD')
  const [annualCanal, setAnnualCanal] = useState<'ALL' | 'CAISSE' | 'BANQUE'>('ALL')
  const [annualPrefsReady, setAnnualPrefsReady] = useState(false)
  const { data: annualData, loading: annualLoading, refetch: loadAnnualSynthese } = useAnnualReport({
    year: annualYear,
    devise: annualDevise,
    canal: annualCanal,
    auto: annualPrefsReady,
  })
  const [topExpenses, setTopExpenses] = useState<{ motif: string; total: number | string }[]>([])
  const [topExpensesLoading, setTopExpensesLoading] = useState(false)
  const [topExpensesPeriod, setTopExpensesPeriod] = useState<'current' | 'previous'>('current')
  const [comptesBancaires, setComptesBancaires] = useState<any[]>([])

  const bankAccounts = useMemo(
    () => comptesBancaires.filter((c) => String(c.account_type || 'BANK').toUpperCase() === 'BANK'),
    [comptesBancaires]
  )
  const cashAccounts = useMemo(
    () => comptesBancaires.filter((c) => String(c.account_type || 'BANK').toUpperCase() === 'CASH'),
    [comptesBancaires]
  )
  const selectedCompte = useMemo(() => {
    if (!journalCompteId) return null
    return comptesBancaires.find((c) => Number(c.id) === Number(journalCompteId)) || null
  }, [journalCompteId, comptesBancaires])

  const journalDeviseEffective = ((selectedCompte?.devise || journalDevise || 'USD') as 'USD' | 'CDF')

  const visibleJournalLines = useMemo(() => {
    if (!journalData?.lignes) return []
    if (!showUnreconciledOnly) return journalData.lignes
    return journalData.lignes.filter((line) => line.is_reconciled === false)
  }, [journalData, showUnreconciledOnly])
  const showCompteColumn = useMemo(
    () => visibleJournalLines.some((line) => Boolean(line.compte_label)),
    [visibleJournalLines]
  )

  const pendingReconcileItems = useMemo(() => Object.values(reconcileDraft), [reconcileDraft])

  const monthLabels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

  const annualChartData = useMemo(() => {
    if (!annualData?.months) return []
    return annualData.months.map((m) => ({
      mois: monthLabels[m.mois - 1] || String(m.mois),
      entrees: toNumber(m.total_entrees),
      sorties: toNumber(m.total_sorties),
      solde: toNumber(m.solde),
    }))
  }, [annualData])

  const annualTotals = useMemo(() => {
    if (!annualData) return null
    const totalEntrees = toNumber(annualData.total_entrees)
    const totalSorties = toNumber(annualData.total_sorties)
    const soldeNet = toNumber(annualData.solde_net)
    const coverageRate = annualData.coverage_rate !== undefined && annualData.coverage_rate !== null
      ? Number(annualData.coverage_rate)
      : null
    const criticalMonthLabel =
      annualData.critical_month && annualData.critical_month >= 1
        ? monthLabels[annualData.critical_month - 1]
        : null
    const encCaisse = toNumber(annualData.encaissements_par_canal?.caisse ?? 0)
    const encBanque = toNumber(annualData.encaissements_par_canal?.banque ?? 0)
    const sortCaisse = toNumber(annualData.sorties_par_canal?.caisse ?? 0)
    const sortBanque = toNumber(annualData.sorties_par_canal?.banque ?? 0)
    const encTotalCanal = encCaisse + encBanque
    const sortTotalCanal = sortCaisse + sortBanque
    return {
      totalEntrees,
      totalSorties,
      soldeNet,
      coverageRate,
      criticalMonthLabel,
      encShareCaisse: encTotalCanal > 0 ? Math.round((encCaisse / encTotalCanal) * 100) : 0,
      encShareBanque: encTotalCanal > 0 ? Math.round((encBanque / encTotalCanal) * 100) : 0,
      sortShareCaisse: sortTotalCanal > 0 ? Math.round((sortCaisse / sortTotalCanal) * 100) : 0,
      sortShareBanque: sortTotalCanal > 0 ? Math.round((sortBanque / sortTotalCanal) * 100) : 0,
    }
  }, [annualData])

  const loadTopExpenses = async () => {
    setTopExpensesLoading(true)
    try {
      const baseDate = new Date(dateDebut || new Date())
      const monthStart = new Date(baseDate.getFullYear(), baseDate.getMonth(), 1)
      const periodStart =
        topExpensesPeriod === 'previous'
          ? new Date(monthStart.getFullYear(), monthStart.getMonth() - 1, 1)
          : monthStart
      const periodEnd = new Date(periodStart.getFullYear(), periodStart.getMonth() + 1, 0)
      const params: Record<string, any> = {
        date_debut: periodStart.toISOString().slice(0, 10),
        date_fin: periodEnd.toISOString().slice(0, 10),
        limit: 5,
        devise: annualDevise,
      }
      if (annualCanal !== 'ALL') {
        params.canal = annualCanal
      }
      const data = await apiRequest<any[]>('GET', '/reports/top-depenses', { params })
      setTopExpenses(Array.isArray(data) ? data : [])
    } catch (error) {
      setTopExpenses([])
    } finally {
      setTopExpensesLoading(false)
    }
  }

  const handleJournalPDF = async () => {
    // La caisse est unique par tenant (table caisse_centrale) : elle n'a pas de
    // ligne dans comptes_bancaires, donc aucun compte à choisir. Le backend
    // accepte d'ailleurs compte_bancaire_id absent pour le canal CAISSE.
    if (journalCanal === 'BANQUE' && !journalCompteId) {
      notifyError('Journal', 'Veuillez sélectionner un compte bancaire.')
      return
    }
    setJournalLoading(true)
    try {
      const params: Record<string, any> = {
        canal: journalCanal,
        devise: journalDeviseEffective,
        date_debut: dateDebut,
        date_fin: dateFin,
      }
      if (journalCompteId) {
        params.compte_bancaire_id = journalCompteId
      }
      const data = await apiRequest<ReportJournalResponse>('GET', '/reports/journal-tresorerie', { params })
      const nomCompte =
        journalCanal === 'CAISSE' && selectedCompte
          ? `${selectedCompte.intitule || 'Caisse'} (${journalDeviseEffective})`
          : journalCanal === 'CAISSE'
            ? `Caisse ${journalDeviseEffective}`
          : selectedCompte
            ? `${selectedCompte.banque?.nom || 'Banque'} - ${selectedCompte.intitule}`
            : 'Compte bancaire'
      const userName = user ? `${user.prenom} ${user.nom}`.trim() : ''
      await generateJournalPDF(data.lignes || [], {
        nom_compte: nomCompte,
        date_debut: dateDebut,
        date_fin: dateFin,
        devise: journalDeviseEffective,
        solde_initial: data.solde_initial,
        total_entrees: data.total_entrees,
        total_sorties: data.total_sorties,
        solde_final: data.solde_final,
        user_name: userName,
      })
      notifySuccess('Journal', 'PDF généré avec succès.')
    } catch (error: any) {
      notifyError('Journal', error?.payload?.detail || error?.message || 'Impossible de générer le journal.')
    } finally {
      setJournalLoading(false)
    }
  }

  const handleJournalTable = async () => {
    // La caisse est unique par tenant (table caisse_centrale) : elle n'a pas de
    // ligne dans comptes_bancaires, donc aucun compte à choisir. Le backend
    // accepte d'ailleurs compte_bancaire_id absent pour le canal CAISSE.
    if (journalCanal === 'BANQUE' && !journalCompteId) {
      notifyError('Journal', 'Veuillez sélectionner un compte bancaire.')
      return
    }
    setJournalTableLoading(true)
    try {
      const params: Record<string, any> = {
        canal: journalCanal,
        devise: journalDeviseEffective,
        date_debut: dateDebut,
        date_fin: dateFin,
      }
      if (journalCompteId) {
        params.compte_bancaire_id = journalCompteId
      }
      const data = await apiRequest<ReportJournalResponse>('GET', '/reports/journal-tresorerie', { params })
      setJournalData(data)
      notifySuccess('Journal', 'Journal chargé.')
    } catch (error: any) {
      notifyError('Journal', error?.payload?.detail || error?.message || 'Impossible de charger le journal.')
    } finally {
      setJournalTableLoading(false)
    }
  }

  const getReconcileType = (line: ReportJournalResponse['lignes'][number]) => {
    if (line.transaction_type === 'ENCAISSEMENT') return 'encaissement'
    if (line.transaction_type === 'SORTIE') return 'sortie'
    return null
  }

  const getReconcileKey = (line: ReportJournalResponse['lignes'][number]) => {
    if (!line.transaction_id || !line.transaction_type) return null
    return `${line.transaction_type}:${line.transaction_id}`
  }

  const getLineReconcileValue = (line: ReportJournalResponse['lignes'][number]) => {
    const key = getReconcileKey(line)
    if (key && reconcileDraft[key]) return reconcileDraft[key].is_reconciled
    return Boolean(line.is_reconciled)
  }

  const toggleReconcileDraft = (line: ReportJournalResponse['lignes'][number]) => {
    const reconcileType = getReconcileType(line)
    const key = getReconcileKey(line)
    if (!reconcileType || !key || !line.transaction_id) return
    const transactionId = line.transaction_id

    setReconcileDraft((prev) => {
      const baseValue = Boolean(line.is_reconciled)
      const currentValue = prev[key]?.is_reconciled ?? baseValue
      const nextValue = !currentValue
      if (nextValue === baseValue) {
        const { [key]: _, ...rest } = prev
        return rest
      }
      return {
        ...prev,
        [key]: {
          transaction_type: reconcileType,
          transaction_id: transactionId,
          is_reconciled: nextValue,
        },
      }
    })
  }

  const handleReconcileBatch = async () => {
    if (!pendingReconcileItems.length) return
    setReconcileLoading(true)
    try {
      const res = await apiRequest<{ items: any[] }>('POST', '/reconciliation/batch', {
        body: { items: pendingReconcileItems },
      })
      const updatedItems = Array.isArray(res?.items) ? res.items : []
      if (updatedItems.length && journalData) {
        const updates = new Map(
          updatedItems.map((item) => [`${String(item.transaction_type).toUpperCase()}:${item.transaction_id}`, item])
        )
        setJournalData({
          ...journalData,
          lignes: journalData.lignes.map((line) => {
            const key = getReconcileKey(line)
            if (!key || !updates.has(key)) return line
            const next = updates.get(key)
            return {
              ...line,
              is_reconciled: Boolean(next.is_reconciled),
              reconciled_at: next.reconciled_at || null,
              bank_statement_ref: next.bank_statement_ref || null,
            }
          }),
        })
      }
      setReconcileDraft({})
      notifySuccess('Pointage', `Rapprochement effectué (${updatedItems.length}).`)
    } catch (error: any) {
      notifyError('Pointage', error?.payload?.detail || error?.message || 'Impossible de rapprocher les transactions.')
    } finally {
      setReconcileLoading(false)
    }
  }

  const handleAnnualLoad = async () => {
    try {
      await loadAnnualSynthese()
      notifySuccess('Synthèse annuelle', 'Données chargées.')
    } catch (error: any) {
      notifyError('Synthèse annuelle', error?.payload?.detail || error?.message || 'Impossible de charger la synthèse.')
    }
  }

  const exportJournalToExcel = async () => {
    if (!journalData) return
    const nomCompte =
      journalCanal === 'CAISSE' && selectedCompte
        ? `${selectedCompte.intitule || 'Caisse'} (${journalDeviseEffective})`
        : journalCanal === 'CAISSE'
          ? `Caisse ${journalDeviseEffective}`
        : selectedCompte
          ? `${selectedCompte.banque?.nom || 'Banque'} - ${selectedCompte.intitule}`
          : 'Compte bancaire'
    const rows = journalData.lignes.map((line) => ({
      Date: formatReportDate(line.date),
      Libelle: `${(line.libelle || '').trim()}${line.reference ? ` (${line.reference})` : ''}`,
      Entree: toNumber(line.entree),
      Sortie: toNumber(line.sortie),
      Solde: toNumber(line.solde),
    }))
    const summaryRows = [
      { Date: 'Solde initial', Libelle: '', Entree: '', Sortie: '', Solde: toNumber(journalData.solde_initial) },
      { Date: 'Solde final', Libelle: '', Entree: '', Sortie: '', Solde: toNumber(journalData.solde_final) },
    ]
    const sheet = XLSX.utils.json_to_sheet([...summaryRows, ...rows])
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, sheet, 'Journal')
    XLSX.writeFile(wb, `Journal_${nomCompte}_${dateFin}.xlsx`)
  }

  const fetchWithLog = async (label: string, url: string) => {
    console.log(`[Rapports] ${label} -> ${url}`)
    const res = await apiRequest('GET', url)
    console.log(`[Rapports] ${label} <- OK`, Array.isArray(res) ? `items=${res.length}` : res)
    return res
  }

  const checkReportingAccess = () => {
    setHasReportingAccess(hasPermission('rapports'))
    setCheckingAccess(false)
  }

  useEffect(() => {
    checkReportingAccess()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, hasPermission])

  useEffect(() => {
    try {
      const raw = localStorage.getItem('annualSynthesePrefs')
      if (!raw) return
      const prefs = JSON.parse(raw)
      if (typeof prefs.year === 'number') setAnnualYear(prefs.year)
      if (prefs.devise === 'USD' || prefs.devise === 'CDF') setAnnualDevise(prefs.devise)
      if (prefs.canal === 'ALL' || prefs.canal === 'CAISSE' || prefs.canal === 'BANQUE') setAnnualCanal(prefs.canal)
    } catch {
      // ignore
    }
    setAnnualPrefsReady(true)
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(
        'annualSynthesePrefs',
        JSON.stringify({ year: annualYear, devise: annualDevise, canal: annualCanal })
      )
    } catch {
      // ignore
    }
  }, [annualYear, annualDevise, annualCanal])

  useEffect(() => {
    if (!annualPrefsReady) return
    loadTopExpenses().catch(() => undefined)
  }, [annualPrefsReady, dateDebut, dateFin, annualDevise, annualCanal, topExpensesPeriod])

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
    setJournalData(null)
    setShowUnreconciledOnly(false)
    setReconcileDraft({})
  }, [journalCanal, journalDevise, journalCompteId, dateDebut, dateFin])

  useEffect(() => {
    setReconcileDraft({})
  }, [journalData?.compte_bancaire_id, journalData?.period?.start, journalData?.period?.end])

  useEffect(() => {
    if (journalCanal !== 'CAISSE') return
    const matchingCash = cashAccounts.filter((c) => String(c.devise) === journalDevise)
    if (!matchingCash.length) {
      setJournalCompteId('')
      return
    }
    if (!journalCompteId || !matchingCash.find((c) => Number(c.id) === Number(journalCompteId))) {
      setJournalCompteId(Number(matchingCash[0].id))
    }
  }, [journalCanal, journalDevise, cashAccounts, journalCompteId])

  useEffect(() => {
    if (journalCanal !== 'BANQUE') return
    if (!bankAccounts.length) {
      setJournalCompteId('')
      return
    }
    if (!journalCompteId || !bankAccounts.find((c) => Number(c.id) === Number(journalCompteId))) {
      setJournalCompteId(Number(bankAccounts[0].id))
    }
  }, [journalCanal, bankAccounts, journalCompteId])

  const rapportQueryKey = ['rapports-summary', dateDebut, dateFin, reportCanal, reportDevise] as const

  const rapportQuery = useQuery({
    queryKey: rapportQueryKey,
    enabled: false,
    queryFn: async () => {
      const summaryUrl = '/reports/summary' + buildQuery({
        date_debut: dateDebut,
        date_fin: dateFin,
        canal: reportCanal === 'ALL' ? undefined : reportCanal,
        devise: reportDevise === 'ALL' ? undefined : reportDevise,
      })
      let lastEndpoints = [summaryUrl]

      let nextRapport: any | null = null

      const normalizeReportSummary = (raw: any): ReportSummaryResponse | null => {
        if (raw?.stats && raw?.stats?.totals && raw?.stats?.breakdowns) {
          return raw as ReportSummaryResponse
        }

        if (raw?.totals && raw?.breakdowns) {
          // TODO(remove-legacy-report-shape): supprimer ce fallback après migration complète.
          return {
            stats: {
              totals: raw.totals,
              breakdowns: raw.breakdowns,
              availability: raw.availability ?? { encaissements: true, sorties: true, requisitions: true },
            },
            daily_stats: raw.breakdowns?.par_jour || [],
            period: raw.period ?? null,
          }
        }

        return null
      }

      try {
      try {
        const summaryRaw = await fetchWithLog('reports-summary', summaryUrl)
        const summary = normalizeReportSummary(summaryRaw)
        if (!summary) {
          throw new Error('Réponse reports/summary invalide')
        }

        const totals = summary.stats?.totals || {}
        const breakdowns = summary.stats?.breakdowns || {}
        const availability = summary.stats?.availability || {}

        if (availability.sorties === false) {
          setSortiesWarning('Sorties indisponibles.')
        }

        const parStatutPaiement = Array.isArray(breakdowns.par_statut_paiement)
          ? breakdowns.par_statut_paiement
          : []
        const parModeEnc = breakdowns.par_mode_paiement?.encaissements || []
        const parModeSorties = breakdowns.par_mode_paiement?.sorties || []
        const parPosteBudgetaire = Array.isArray(breakdowns.par_poste_budgetaire)
          ? breakdowns.par_poste_budgetaire
          : []
        const parStatutRequisition = Array.isArray(breakdowns.par_statut_requisition)
          ? breakdowns.par_statut_requisition
          : []

        const totalEncaissements = toNumber(totals.encaissements_total ?? 0)
        const totalSorties = toNumber(totals.sorties_total ?? 0)
        const transfertsInternes = toNumber(totals.transferts_internes ?? 0)
        const depensesReelles = toNumber(totals.depenses_reelles ?? (totalSorties - transfertsInternes))
        const entreesInternes = toNumber(totals.entrees_internes ?? 0)
        // Ventilation sans conversion : seule vue exacte dès qu'USD et CDF
        // coexistent, les champs plats les additionnant tels quels.
        const parDevise = (Array.isArray(totals.par_devise) ? totals.par_devise : []).map(
          (ligne: any) => ({
            devise: String(ligne.devise || '').toUpperCase() || 'USD',
            encaissements: toNumber(ligne.encaissements_total ?? 0),
            sorties: toNumber(ligne.sorties_total ?? 0),
            depensesReelles: toNumber(ligne.depenses_reelles ?? 0),
            transfertsInternes: toNumber(ligne.transferts_internes ?? 0),
            entreesInternes: toNumber(ligne.entrees_internes ?? 0),
            soldeInitial: toNumber(ligne.solde_initial ?? 0),
            solde: toNumber(ligne.solde ?? 0),
          })
        )
        const soldeInitial = toNumber(totals.solde_initial ?? 0)
        const solde = toNumber(totals.solde ?? totalEncaissements + entreesInternes - totalSorties)
        const soldeFinal = toNumber(totals.solde_final ?? solde)

        const nombreEncaissements = parStatutPaiement.reduce(
          (sum: number, row: any) => sum + (Number(row.count) || 0),
          0
        )
        const nombreSorties = parModeSorties.reduce(
          (sum: number, row: any) => sum + (Number(row.count) || 0),
          0
        )
        const nombreRequisitions = Number(breakdowns.requisitions?.total ?? 0)

        const encaissementsParType = parPosteBudgetaire.reduce((acc: Record<string, number>, row: any) => {
          const key = row.key || 'Non renseigné'
          const val = toNumber(row.total ?? 0)
          acc[key] = (acc[key] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const encaissementsParStatut = parStatutPaiement.reduce((acc: Record<string, number>, row: any) => {
          const statut = row.key || row.statut || 'complet'
          acc[statut] = (acc[statut] || 0) + (Number(row.count) || 0)
          return acc
        }, {})

        const encaissementsParMode = parModeEnc.reduce((acc: Record<string, number>, row: any) => {
          const mode = row.key || row.mode || 'cash'
          const val = toNumber(row.total ?? 0)
          acc[mode] = (acc[mode] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const sortiesParMode = parModeSorties.reduce((acc: Record<string, number>, row: any) => {
          const mode = row.key || row.mode || 'cash'
          const val = toNumber(row.total ?? 0)
          acc[mode] = (acc[mode] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const requisitionsParStatut = parStatutRequisition.reduce((acc: Record<string, number>, row: any) => {
          const statut = normalizeStatut(row.key || row.statut || 'EN_ATTENTE_COMMISSION')
          acc[statut] = (acc[statut] || 0) + (Number(row.count) || 0)
          return acc
        }, {})

        nextRapport = {
          totalEncaissements,
          totalSorties,
          depensesReelles,
          transfertsInternes,
          entreesInternes,
          parDevise,
          soldeInitial,
          solde,
          soldeFinal,
          nombreEncaissements,
          nombreSorties,
          nombreRequisitions,
          encaissements: [],
          sorties: [],
          requisitions: [],
          encaissementsParType,
          encaissementsParStatut,
          encaissementsParMode,
          sortiesParMode,
          requisitionsParStatut,
        }
      } catch (summaryError) {
        console.warn('[Rapports] Summary failed, fallback to legacy endpoints', summaryError)
        const encUrl =
          '/encaissements' + buildQuery({
            date_debut: dateDebut,
            date_fin: dateFin,
            canal: reportCanal === 'ALL' ? undefined : reportCanal,
            limit: 1000,
          })
        const sortUrl =
          '/sorties-fonds' + buildQuery({
            date_debut: dateDebut,
            date_fin: dateFin,
            canal: reportCanal === 'ALL' ? undefined : reportCanal,
            limit: 1000,
          })
        const reqUrl =
          '/requisitions' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 1000 })

        lastEndpoints = [summaryUrl, encUrl, sortUrl, reqUrl]

        const [encaissements, sorties, requisitions] = await Promise.all([
          fetchWithLog('encaissements', encUrl),
          fetchWithLog('sorties-fonds', sortUrl).catch((err) => {
            console.error('[Rapports] Sorties indisponibles (fallback)', err)
            setSortiesWarning('Sorties indisponibles.')
            return []
          }),
          fetchWithLog('requisitions', reqUrl),
        ])

        // Repli sur les endpoints de liste : ils n'ont pas de filtre devise,
        // on l'applique ici pour ne pas retomber dans le cumul USD+CDF.
        const enc = filtrerParDevise(
          Array.isArray(encaissements) ? encaissements : [],
          'devise_perception'
        )
        const sor = filtrerParDevise(Array.isArray(sorties) ? sorties : [], 'devise')
        const req = Array.isArray(requisitions) ? requisitions : []

        const totalEncaissements =
          enc.reduce((sum: number, e: any) => {
            const val = montantEncaissement(e)
            return sum + (Number.isFinite(val) ? val : 0)
          }, 0) || 0

        const totalSorties =
          sor.reduce((sum: number, s: any) => {
            const val = toNumber(s.montant_paye ?? 0)
            return sum + (Number.isFinite(val) ? val : 0)
          }, 0) || 0

        const encaissementsParType = enc.reduce((acc: Record<string, number>, e: any) => {
          const key = e.budget_poste_code
            ? `${e.budget_poste_code}${e.budget_poste_libelle ? ` - ${e.budget_poste_libelle}` : ''}`
            : 'Non classé'
          const val = montantEncaissement(e)
          acc[key] = (acc[key] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const encaissementsParStatut = enc.reduce((acc: Record<string, number>, e: any) => {
          const statut = e.statut_paiement || 'complet'
          acc[statut] = (acc[statut] || 0) + 1
          return acc
        }, {})

        const encaissementsParMode = enc.reduce((acc: Record<string, number>, e: any) => {
          const mode = e.mode_paiement || 'cash'
          const val = montantEncaissement(e)
          acc[mode] = (acc[mode] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const sortiesParMode = sor.reduce((acc: Record<string, number>, s: any) => {
          const mode = s.mode_paiement || 'cash'
          const val = toNumber(s.montant_paye ?? 0)
          acc[mode] = (acc[mode] || 0) + (Number.isFinite(val) ? val : 0)
          return acc
        }, {})

        const requisitionsParStatut = req.reduce((acc: Record<string, number>, r: any) => {
          const statut = normalizeStatut(r.statut || r.status || 'EN_ATTENTE_COMMISSION')
          acc[statut] = (acc[statut] || 0) + 1
          return acc
        }, {})

        nextRapport = {
          totalEncaissements,
          totalSorties,
          soldeInitial: 0,
          solde: totalEncaissements - totalSorties,
          soldeFinal: totalEncaissements - totalSorties,
          nombreEncaissements: enc.length,
          nombreSorties: sor.length,
          nombreRequisitions: req.length,
          encaissements: enc,
          sorties: sor,
          requisitions: req,
          encaissementsParType,
          encaissementsParStatut,
          encaissementsParMode,
          sortiesParMode,
          requisitionsParStatut,
        }
      }

      const hasData =
        !!nextRapport &&
        (nextRapport.nombreEncaissements > 0 ||
          nextRapport.nombreSorties > 0 ||
          nextRapport.nombreRequisitions > 0)

      return { rapport: nextRapport, emptyMessage: hasData ? null : 'Aucune donnée trouvée pour la période sélectionnée.' }
    } catch (error: any) {
      console.error('Error loading rapport:', error)
      if (lastEndpoints.length) {
        console.log('[Rapports] Last endpoints', lastEndpoints)
      }
      throw error
    }
    },
  })

  const rapport = rapportQuery.data?.rapport ?? null
  const loading = rapportQuery.isFetching

  const loadRapport = () => {
    setErrorMessage(null)
    setEmptyMessage(null)
    setSortiesWarning(null)
    setDetailsLoaded(false)
    setDetailsError(null)
    rapportQuery.refetch()
  }

  useEffect(() => {
    if (rapportQuery.data) {
      setEmptyMessage(rapportQuery.data.emptyMessage)
    }
  }, [rapportQuery.data])

  useEffect(() => {
    if (rapportQuery.error) {
      setErrorMessage(formatRapportError(rapportQuery.error))
    }
  }, [rapportQuery.error])

  // Les endpoints de liste (/encaissements, /sorties-fonds) n'ont pas de filtre
  // devise : on le pose ici, sur les lignes reçues, pour que le détail affiché
  // corresponde aux totaux du résumé (eux filtrés côté SQL).
  const filtrerParDevise = <T,>(rows: T[], champ: 'devise' | 'devise_perception'): T[] => {
    if (reportDevise === 'ALL') return rows
    return rows.filter(
      (row: any) => String(row?.[champ] || 'USD').toUpperCase() === reportDevise
    )
  }

  // Montant d'un encaissement dans la devise regardée : `montant_paye` est le
  // pivot USD, `montant_percu` le montant réellement encaissé. En vue CDF, le
  // premier afficherait des dollars sous un total en francs.
  const montantEncaissement = (e: any) =>
    reportDevise === 'CDF'
      ? toNumber(e?.montant_percu ?? 0)
      : toNumber(e?.montant_paye ?? e?.montant_total ?? e?.montant ?? 0)

  // Transferts internes REÇUS par le canal affiché : leur ligne `sorties_fonds`
  // porte le canal opposé (un versement reçu en banque est une sortie de caisse),
  // donc un filtre `canal` les manquerait. On filtre sur le type, sans canal.
  // Vue consolidée : rien à récupérer, ces mêmes lignes figurent déjà dans le
  // détail des sorties (non filtré par canal) — les répéter les dupliquerait.
  const fetchTransfertsRecus = async (): Promise<any[]> => {
    if (reportCanal === 'ALL') return []
    const url =
      '/sorties-fonds' +
      buildQuery({
        date_debut: dateDebut,
        date_fin: dateFin,
        type_sortie: reportCanal === 'BANQUE' ? 'versement_banque' : 'approvisionnement_caisse',
        limit: 5000,
      })
    try {
      const res = await apiRequest('GET', url)
      return filtrerParDevise(Array.isArray(res) ? res : [], 'devise')
    } catch (err) {
      console.error('[Rapports] Transferts internes reçus indisponibles', err)
      return []
    }
  }

  const loadDetails = async () => {
    if (!rapport) return
    setDetailsLoading(true)
    setDetailsError(null)
    setSortiesWarning(null)
    try {
      const encUrl =
        '/encaissements' +
        buildQuery({
          date_debut: dateDebut,
          date_fin: dateFin,
          canal: reportCanal === 'ALL' ? undefined : reportCanal,
          include: 'expert_comptable',
          limit: 5000,
        })
      const sortUrl =
        '/sorties-fonds' +
        buildQuery({
          date_debut: dateDebut,
          date_fin: dateFin,
          canal: reportCanal === 'ALL' ? undefined : reportCanal,
          include: 'requisition',
          limit: 5000,
        })
      const reqUrl =
        '/requisitions' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 5000 })

      const encPromise = fetchWithLog('encaissements-details', encUrl)
      const reqPromise = fetchWithLog('requisitions-details', reqUrl)
      const sortPromise = fetchWithLog('sorties-fonds-details', sortUrl).catch((err) => {
        console.error('[Rapports] Sorties indisponibles (détails)', err)
        setSortiesWarning('Sorties indisponibles.')
        return []
      })

      const [encaissements, sorties, requisitions, transfertsRecus] = await Promise.all([
        encPromise,
        sortPromise,
        reqPromise,
        fetchTransfertsRecus(),
      ])

      const enc = filtrerParDevise(
        Array.isArray(encaissements) ? encaissements : [],
        'devise_perception'
      )
      const sor = filtrerParDevise(Array.isArray(sorties) ? sorties : [], 'devise')
      const req = Array.isArray(requisitions) ? requisitions : []

      queryClient.setQueryData(rapportQueryKey, (prev: any) => prev && {
        ...prev,
        rapport: {
          ...prev.rapport,
          encaissements: enc,
          sorties: sor,
          requisitions: req,
          transfertsRecus,
        },
      })
      setDetailsLoaded(true)
    } catch (error: any) {
      console.error('Error loading details:', error)
      const status = typeof error?.status === 'number' ? `HTTP ${error.status}` : null
      const detail = error?.payload?.detail || error?.payload?.message || error?.message || null
      const parts = [status, detail].filter(Boolean).join(' - ')
      setDetailsError(
        parts
          ? `Impossible de charger les détails. (${parts})`
          : "Impossible de charger les détails. Vérifie ton accès ou le serveur API."
      )
    } finally {
      setDetailsLoading(false)
    }
  }

  useEffect(() => {
    if (hasReportingAccess) loadRapport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasReportingAccess])

  useEffect(() => {
    setDetailsLoaded(false)
    setDetailsError(null)
    setSortiesWarning(null)
    setEmptyMessage(null)
    setErrorMessage(null)
  }, [dateDebut, dateFin, reportCanal, reportDevise])

  // Formatage dans la devise de la ligne : les totaux par devise ne sont pas
  // convertis, les afficher tous en $ les rendrait faux.
  const formatMoneyDevise = (amount: Money, devise: string) => {
    const code = (devise || 'USD').toUpperCase()
    try {
      return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: code }).format(
        toNumber(amount)
      )
    } catch {
      // Devise inconnue d'Intl : on garde le code brut plutôt que d'échouer.
      return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2 }).format(
        toNumber(amount)
      )} ${code}`
    }
  }

  // Tous les chiffres de l'écran sont désormais cadrés par le filtre Devise :
  // les libeller dans cette devise est donc exact. En vue « Toutes », ce sont
  // des cumuls inter-devises : on retire le symbole plutôt que d'afficher un $
  // qui serait faux, la table par devise donnant le détail juste en dessous.
  const formatCurrency = (amount: Money) => {
    if (reportDevise === 'ALL') {
      return new Intl.NumberFormat('fr-FR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(toNumber(amount))
    }
    return formatMoneyDevise(amount, reportDevise)
  }

  const normalizeRubrique = (value: any) => {
    const raw = String(value || '').replace(/\s+/g, ' ').trim()
    if (!raw) return ''
    return raw
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+MENT\b/g, '$1MENT')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TION\b/g, '$1TION')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TIONS\b/g, '$1TIONS')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TE\b/g, '$1TE')
  }

  const normalizeStatut = (value: any) => {
    const raw = String(value || '').trim().toLowerCase()
    if (!raw) return 'EN_ATTENTE_COMMISSION'
    if (raw.includes('rejet')) return 'REJETEE'
    if (raw.includes('pay')) return 'PAYEE'
    if (raw.includes('validation 2') || raw.includes('visa')) return 'APPROUVEE'
    if (raw.includes('attente')) return 'EN_ATTENTE'
    if (raw.includes('validation 1') || raw.includes('autorise') || raw.includes('valide')) return 'AUTORISEE'
    if (raw.includes('commission') || raw.includes('sign')) return 'EN_ATTENTE_COMMISSION'
    if (raw.includes('attente') || raw.includes('brouillon') || raw.includes('a_valider')) {
      return 'EN_ATTENTE_COMMISSION'
    }
    return String(value || '').toUpperCase()
  }

  const getStatutLabel = (value: any) => {
    const statut = normalizeStatut(value)
    return getStatusMeta(statut).label
  }

  const getStatutTone = (value: any) => {
    const statut = normalizeStatut(value)
    if (statut === 'PAYEE') return styles.statusOk
    if (statut === 'REJETEE') return styles.statusBad
    if (statut === 'AUTORISEE' || statut === 'APPROUVEE') return styles.statusWarn
    return styles.statusNeutral
  }

  const periodeLabel = useMemo(() => {
    return `du ${format(new Date(dateDebut), 'dd/MM/yyyy')} au ${format(new Date(dateFin), 'dd/MM/yyyy')}`
  }, [dateDebut, dateFin])

  // Libellé de la contrepartie entrante des transferts internes. En vue
  // consolidée les deux jambes figurent au rapport et s'annulent : c'est ce qui
  // rend l'égalité « entrées + transferts reçus - sorties = solde » vérifiable.
  const transfertsRecusLabel = useMemo(() => {
    if (reportCanal === 'BANQUE') return 'Transferts internes reçus (versements de la caisse)'
    if (reportCanal === 'CAISSE') {
      return 'Transferts internes reçus (approvisionnements depuis la banque)'
    }
    return 'Transferts internes reçus (contrepartie des sorties de transfert)'
  }, [reportCanal])

  const devisesPresentes: string[] = useMemo(
    () => (rapport?.parDevise || []).map((ligne: any) => ligne.devise),
    [rapport]
  )
  const multiDevises = devisesPresentes.length > 1

  const transfertsRecusHint = useMemo(() => {
    if (reportCanal === 'BANQUE') return 'Versements de la caisse — hors recettes, inclus dans le solde'
    if (reportCanal === 'CAISSE') {
      return 'Approvisionnements depuis la banque — hors recettes, inclus dans le solde'
    }
    return "Contrepartie des transferts internes : s'annule avec les sorties, solde inchangé"
  }, [reportCanal])

  // Détail des lignes de la période, pour les exports. Ils ne peuvent pas se
  // reposer sur `rapport.encaissements`/`.sorties` : ces listes ne sont remplies
  // que si l'utilisateur a déplié le détail à l'écran.
  const fetchExportDetails = async (): Promise<{ enc: any[]; sor: any[] }> => {
    const encUrl =
      '/encaissements' +
      buildQuery({
        date_debut: dateDebut,
        date_fin: dateFin,
        canal: reportCanal === 'ALL' ? undefined : reportCanal,
        include: 'expert_comptable',
        limit: 5000,
      })
    const sortUrl =
      '/sorties-fonds' +
      buildQuery({
        date_debut: dateDebut,
        date_fin: dateFin,
        canal: reportCanal === 'ALL' ? undefined : reportCanal,
        include: 'requisition',
        limit: 5000,
      })
    const [encaissements, sorties] = await Promise.all([
      apiRequest('GET', encUrl),
      apiRequest('GET', sortUrl),
    ])
    return {
      enc: filtrerParDevise(Array.isArray(encaissements) ? encaissements : [], 'devise_perception'),
      sor: filtrerParDevise(Array.isArray(sorties) ? sorties : [], 'devise'),
    }
  }

  const exportToExcel = async () => {
    try {
      if (!rapport) {
        notifyError("Filtre requis", "Cliquez d'abord sur Générer rapport pour la période sélectionnée.")
        return
      }

      const [{ enc, sor }, transfertsRecus] = await Promise.all([
        fetchExportDetails(),
        fetchTransfertsRecus(),
      ])

      const wb = XLSX.utils.book_new()

      const summaryData = [
        ['RAPPORT FINANCIER'],
        [`Période : ${periodeLabel}`],
        [],
        ['RÉSUMÉ'],
        ['Canal', reportCanal === 'ALL' ? 'Tous canaux' : reportCanal],
        ['Devise', reportDevise === 'ALL' ? 'Toutes (cumulées, non converties)' : reportDevise],
        ['Total Encaissements', formatCurrency(rapport.totalEncaissements)],
        [transfertsRecusLabel, formatCurrency(rapport.entreesInternes ?? 0)],
        ['Total Sorties', formatCurrency(rapport.totalSorties)],
        ['dont transferts internes', formatCurrency(rapport.transfertsInternes ?? 0)],
        [`Solde au ${dateDebut}`, formatCurrency(rapport.soldeInitial ?? 0)],
        ['Solde final', formatCurrency(rapport.soldeFinal ?? rapport.solde)],
        ["Nombre d'encaissements", rapport.nombreEncaissements],
        ['Nombre de sorties', rapport.nombreSorties],
        ['Nombre de réquisitions', rapport.nombreRequisitions],
        // Les lignes ci-dessus cumulent les devises (compatibilité). Le bloc qui
        // suit est la lecture exacte : montants bruts, une ligne par devise, en
        // nombres et non en texte formaté pour rester calculable dans Excel.
        ...((rapport.parDevise?.length ?? 0) > 0
          ? [
              [],
              ['DÉTAIL PAR DEVISE (montants non convertis)'],
              [
                'Devise',
                'Solde initial',
                'Encaissements',
                'Transferts reçus',
                'Sorties',
                'dont dépenses réelles',
                'Solde',
              ],
              ...rapport.parDevise.map((ligne: any) => [
                ligne.devise,
                ligne.soldeInitial,
                ligne.encaissements,
                ligne.entreesInternes,
                ligne.sorties,
                ligne.depensesReelles,
                ligne.solde,
              ]),
            ]
          : []),
      ]
      const summarySheet = XLSX.utils.aoa_to_sheet(summaryData)
      XLSX.utils.book_append_sheet(wb, summarySheet, 'Résumé')

      const encaissementsData = [
        // « Montant Total » reste la note de débit, toujours exprimée en pivot
        // USD ; « Montant Payé » suit la devise regardée, comme les totaux.
        ['Date', 'N° Note de débit', 'Client', 'Poste budgétaire', 'Description', 'Montant Total (USD)', `Montant Payé${reportDevise === 'ALL' ? '' : ` (${reportDevise})`}`, 'Devise perçue', 'Statut', 'Mode de paiement'],
        ...enc.map((e: any) => {
          const montantTotal = toNumber(e.montant_total ?? e.montant ?? 0)
          const montantPaye = montantEncaissement(e)
          const poste = e.budget_poste_code
            ? `${e.budget_poste_code}${e.budget_poste_libelle ? ` - ${e.budget_poste_libelle}` : ''}`
            : ''
          const statut =
            e.statut_paiement === 'non_paye'
              ? 'Non payé'
              : e.statut_paiement === 'partiel'
              ? 'Partiel'
              : e.statut_paiement === 'avance'
              ? 'Avance'
              : 'Payé'

          return [
            format(new Date(e.date_encaissement), 'dd/MM/yyyy'),
            e.numero_recu,
            e.expert_comptable?.nom_denomination || e.client_nom || '',
            poste,
            e.description || '',
            Number.isFinite(montantTotal) ? montantTotal : 0,
            Number.isFinite(montantPaye) ? montantPaye : 0,
            String(e.devise_perception || 'USD').toUpperCase(),
            statut,
            e.mode_paiement || '',
          ]
        })
      ]
      const encaissementsSheet = XLSX.utils.aoa_to_sheet(encaissementsData)
      XLSX.utils.book_append_sheet(wb, encaissementsSheet, 'Encaissements')

      const sortiesDataWithPostes = await Promise.all(
        sor.map(async (s: any) => {
          let posteBudgetaire = ''
          if (s.requisition_id) {
            const lignesUrl = '/lignes-requisition' + buildQuery({ requisition_id: s.requisition_id })
            const lignesRes: any = await apiRequest('GET', lignesUrl)
            const lignes = Array.isArray(lignesRes) ? lignesRes : []
            posteBudgetaire = lignes.length ? [...new Set(lignes.map((l: any) => l.rubrique))].join(', ') : ''
          }

          return [
            format(new Date(s.date_paiement), 'dd/MM/yyyy'),
            s.reference || '',
            s.requisition?.numero_requisition || '',
            s.requisition?.objet || '',
            posteBudgetaire,
            toNumber(s.montant_paye ?? 0),
            String(s.devise || 'USD').toUpperCase(),
            s.mode_paiement || '',
          ]
        })
      )

      const sortiesData = [
        ['Date', 'Référence', 'N° Réquisition', 'Objet', 'Poste budgétaire', 'Montant', 'Devise', 'Mode de paiement'],
        ...sortiesDataWithPostes
      ]
      const sortiesSheet = XLSX.utils.aoa_to_sheet(sortiesData)
      XLSX.utils.book_append_sheet(wb, sortiesSheet, 'Sorties de Fonds')

      // Détail des transferts reçus : absent des deux feuilles ci-dessus, car
      // leur ligne appartient au canal opposé (feuille Sorties du canal source).
      if (transfertsRecus.length) {
        const transfertsData = [
          ['Date', 'Référence', 'Motif', 'Bénéficiaire', 'Montant', 'Devise'],
          ...transfertsRecus.map((t: any) => [
            t.date_paiement ? format(new Date(t.date_paiement), 'dd/MM/yyyy') : '',
            t.reference_numero || t.reference || '',
            t.motif || '',
            t.beneficiaire || '',
            toNumber(t.montant_paye ?? 0),
            t.devise || '',
          ]),
        ]
        const transfertsSheet = XLSX.utils.aoa_to_sheet(transfertsData)
        XLSX.utils.book_append_sheet(wb, transfertsSheet, 'Transferts reçus')
      }

      XLSX.writeFile(wb, `rapport_${dateDebut}_${dateFin}.xlsx`)
      notifySuccess('Export Excel', 'Le fichier a été téléchargé.')
    } catch (error) {
      console.error('Error exporting to Excel:', error)
      notifyError("Erreur d'export", "Une erreur est survenue lors de l'export vers Excel.")
    }
  }

  const exportToPDF = async () => {
    if (!rapport) {
      notifyError("Filtre requis", "Cliquez d'abord sur Générer rapport pour la période sélectionnée.")
      return
    }
    // `loadDetails` n'a pas forcément été déclenché : sans ce chargement le PDF
    // perdrait les transferts reçus, et son résumé étiquetterait « USD » des
    // totaux dont il ne connaît pas les devises (cf. pdfGenerator).
    const [{ enc, sor }, transfertsRecus] = await Promise.all([
      detailsLoaded
        ? Promise.resolve({ enc: rapport.encaissements || [], sor: rapport.sorties || [] })
        : fetchExportDetails(),
      rapport.transfertsRecus?.length
        ? Promise.resolve(rapport.transfertsRecus)
        : fetchTransfertsRecus(),
    ])
    await generateGlobalReportPDF(
      {
        ...rapport,
        encaissements: enc,
        sorties: sor,
        transfertsRecus,
        canal: reportCanal,
        devise: reportDevise,
      },
      dateDebut,
      dateFin
    )
  }

  if (checkingAccess || permissionsLoading) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <h1>Vérification des accès...</h1>
        </div>
      </div>
    )
  }

  if (!hasReportingAccess) {
    return (
      <div className={styles.container}>
        <AccessDeniedState message="Vous n'avez pas les privilèges nécessaires pour accéder aux rapports. Contactez un administrateur." />
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Rapports d’activités financières</h1>
          <p>Statistiques et analyses détaillées</p>
        </div>
      </div>

      <div className={styles.filters}>
        <div className={styles.field}>
          <label>Date début</label>
          <input
            type="date"
            value={dateDebut}
            onChange={(e) => setDateDebut(e.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label>Date fin</label>
          <input
            type="date"
            value={dateFin}
            onChange={(e) => setDateFin(e.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label>Canal</label>
          <select
            value={reportCanal}
            onChange={(e) => setReportCanal(e.target.value as 'ALL' | 'BANQUE' | 'CAISSE')}
          >
            <option value="ALL">Tous</option>
            <option value="BANQUE">Banque</option>
            <option value="CAISSE">Caisse</option>
          </select>
        </div>

        <div className={styles.field}>
          <label>Devise</label>
          <select
            value={reportDevise}
            onChange={(e) => setReportDevise(e.target.value as 'USD' | 'CDF' | 'ALL')}
          >
            <option value="USD">USD</option>
            <option value="CDF">CDF</option>
            <option value="ALL">Toutes (cumulées)</option>
          </select>
        </div>

        <button onClick={loadRapport} className={styles.primaryBtn} disabled={loading}>
          {loading ? 'Chargement...' : 'Générer rapport'}
        </button>

        {rapport && (
          <>
            <button onClick={exportToExcel} className={styles.exportBtn}>
              📊 Excel
            </button>
            <button onClick={exportToPDF} className={styles.exportBtn}>
              📄 PDF
            </button>
            <button
              onClick={loadDetails}
              className={styles.exportBtn}
              disabled={detailsLoading || detailsLoaded}
            >
              {detailsLoading ? 'Chargement...' : detailsLoaded ? 'Détails chargés' : 'Charger détails'}
            </button>
          </>
        )}
      </div>

      <div className={styles.annualCard}>
        <div className={styles.annualHeader}>
          <div>
            <h2>Synthèse annuelle</h2>
            <p>Comparaison mensuelle des flux de trésorerie.</p>
          </div>
          <div className={styles.annualControls}>
            <div className={styles.field}>
              <label>Année</label>
              <input
                type="number"
                min={2020}
                max={2100}
                value={annualYear}
                onChange={(e) => setAnnualYear(Number(e.target.value || new Date().getFullYear()))}
              />
            </div>
            <div className={styles.field}>
              <label>Devise</label>
              <select value={annualDevise} onChange={(e) => setAnnualDevise(e.target.value as 'USD' | 'CDF')}>
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>Canal</label>
              <select value={annualCanal} onChange={(e) => setAnnualCanal(e.target.value as any)}>
                <option value="ALL">Tous</option>
                <option value="CAISSE">Caisse</option>
                <option value="BANQUE">Banque</option>
              </select>
            </div>
            <button onClick={handleAnnualLoad} className={styles.primaryBtn} disabled={annualLoading}>
              {annualLoading ? 'Chargement...' : 'Rafraîchir'}
            </button>
          </div>
        </div>

        {annualData && (
          <>
            <div className={styles.annualContent}>
              <div className={styles.annualChart}>
                <ResponsiveContainer width="100%" height={360} minWidth={0} minHeight={280}>
                  <BarChart data={annualChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
                    <XAxis dataKey="mois" axisLine={false} tickLine={false} />
                    <YAxis axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0' }}
                      cursor={{ fill: '#f8fafc' }}
                    />
                    <Legend verticalAlign="top" align="right" height={36} />
                    <Bar dataKey="entrees" name="Entrées" fill="#0b5d43" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="sorties" name="Sorties" fill="#00A09D" radius={[3, 3, 0, 0]} />
                    <Line type="monotone" dataKey="solde" name="Solde net" stroke="#f59e0b" strokeWidth={2} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className={styles.topExpensesWrap}>
                <div className={styles.topExpensesHeader}>
                  <div>
                    <h4>Top 5 Dépenses</h4>
                    <p>{topExpensesPeriod === 'current' ? 'Ce mois' : 'Mois précédent'}</p>
                  </div>
                  <div className={styles.toggleGroup}>
                    <button
                      type="button"
                      className={topExpensesPeriod === 'current' ? styles.toggleActive : styles.toggleBtn}
                      onClick={() => setTopExpensesPeriod('current')}
                    >
                      Ce mois
                    </button>
                    <button
                      type="button"
                      className={topExpensesPeriod === 'previous' ? styles.toggleActive : styles.toggleBtn}
                      onClick={() => setTopExpensesPeriod('previous')}
                    >
                      Mois précédent
                    </button>
                  </div>
                </div>
                <TopExpenses expenses={topExpenses} devise={annualDevise} />
                {topExpensesLoading && (
                  <div className={styles.annualLoading}>Chargement des top dépenses…</div>
                )}
              </div>
            </div>

            {annualTotals && (
              <div className={styles.annualKpis}>
                <div className={styles.kpiCard}>
                  <span>Total annuel entrées</span>
                  <strong>{annualTotals.totalEntrees.toLocaleString('fr-FR')} {annualDevise}</strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Total annuel sorties</span>
                  <strong>{annualTotals.totalSorties.toLocaleString('fr-FR')} {annualDevise}</strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Excédent / Déficit</span>
                  <strong className={annualTotals.soldeNet >= 0 ? styles.kpiPositive : styles.kpiNegative}>
                    {annualTotals.soldeNet >= 0 ? '+' : ''}{annualTotals.soldeNet.toLocaleString('fr-FR')} {annualDevise}
                  </strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Taux de couverture</span>
                  <strong>
                    {annualTotals.coverageRate !== null ? `${(annualTotals.coverageRate * 100).toFixed(1)}%` : '—'}
                  </strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Mois le plus critique</span>
                  <strong>{annualTotals.criticalMonthLabel || '—'}</strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Répartition encaissements</span>
                  <strong>{annualTotals.encShareCaisse}% Caisse · {annualTotals.encShareBanque}% Banque</strong>
                </div>
                <div className={styles.kpiCard}>
                  <span>Répartition sorties</span>
                  <strong>{annualTotals.sortShareCaisse}% Caisse · {annualTotals.sortShareBanque}% Banque</strong>
                </div>
              </div>
            )}
          </>
        )}
        {annualLoading && (
          <div className={styles.annualLoading}>
            Chargement de la synthèse annuelle…
          </div>
        )}
      </div>

      <div className={styles.journalCard}>
        <div>
          <h3>Journal de trésorerie</h3>
          <p>Grand livre avec solde progressif par canal et devise.</p>
        </div>
        <div className={styles.journalGrid}>
          <div className={styles.field}>
            <label>Canal</label>
            <select
              value={journalCanal}
              onChange={(e) => {
                const next = e.target.value as 'CAISSE' | 'BANQUE'
                setJournalCanal(next)
                if (next === 'CAISSE') {
                  const matchingCash = cashAccounts.filter((c) => String(c.devise) === journalDevise)
                  setJournalCompteId(matchingCash.length ? Number(matchingCash[0].id) : '')
                } else {
                  setJournalCompteId('')
                }
              }}
            >
              <option value="CAISSE">Caisse</option>
              <option value="BANQUE">Banque</option>
            </select>
          </div>

          <div className={styles.field}>
            <label>{journalCanal === 'BANQUE' ? 'Compte bancaire' : 'Compte caisse'}</label>
            <select
              value={journalCompteId}
              onChange={(e) => setJournalCompteId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Sélectionner...</option>
              {(journalCanal === 'BANQUE' ? bankAccounts : cashAccounts.filter((c) => String(c.devise) === journalDevise)).map(
                (compte) => (
                  <option key={compte.id} value={compte.id}>
                    {journalCanal === 'BANQUE'
                      ? `${compte.banque?.nom || 'Banque'} - ${compte.intitule} (${compte.devise})`
                      : `${compte.intitule || 'Caisse'} (${compte.devise})`}
                  </option>
                )
              )}
              {journalCanal === 'CAISSE' && cashAccounts.filter((c) => String(c.devise) === journalDevise).length === 0 && (
                <option disabled>Aucun compte caisse en {journalDevise}</option>
              )}
            </select>
          </div>

          <div className={styles.field}>
            <label>Devise</label>
            <select
              value={journalDeviseEffective}
              onChange={(e) => setJournalDevise(e.target.value as 'USD' | 'CDF')}
              disabled={journalCanal === 'BANQUE'}
            >
              <option value="USD">USD</option>
              <option value="CDF">CDF</option>
            </select>
          </div>

          <button
            onClick={handleJournalPDF}
            className={styles.primaryBtn}
            disabled={journalLoading || (journalCanal === 'BANQUE' && !journalCompteId)}
          >
            {journalLoading ? 'Génération...' : 'Générer le journal PDF'}
          </button>
          <button
            onClick={handleJournalTable}
            className={styles.exportBtn}
            disabled={journalTableLoading || (journalCanal === 'BANQUE' && !journalCompteId)}
          >
            {journalTableLoading ? 'Chargement...' : 'Afficher le journal'}
          </button>
        </div>
      </div>

      {errorMessage && (
        <div className={styles.alert} role="alert">
          <div>{errorMessage}</div>
          <button onClick={loadRapport} className={styles.retryBtn} disabled={loading}>
            Réessayer
          </button>
        </div>
      )}

      {journalData && (
        <div className={styles.journalTableWrap}>
          <div className={styles.journalHeader}>
            <div>
              <h3>Journal — {journalData.canal} {journalData.devise}</h3>
              <p>
                Solde initial: {toNumber(journalData.solde_initial).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} ·
                Solde final: {toNumber(journalData.solde_final).toLocaleString('fr-FR', { minimumFractionDigits: 2 })}
              </p>
              <div className={styles.journalFilters}>
                <label className={styles.reconcileToggle}>
                  <input
                    type="checkbox"
                    checked={showUnreconciledOnly}
                    onChange={(e) => setShowUnreconciledOnly(e.target.checked)}
                  />
                  <span>Afficher uniquement les non-pointés</span>
                </label>
              </div>
            </div>
            <div className={styles.journalActions}>
              <button
                className={styles.primaryBtn}
                onClick={handleReconcileBatch}
                disabled={reconcileLoading || pendingReconcileItems.length === 0}
              >
                {reconcileLoading
                  ? 'Pointage...'
                  : `Clôturer le rapprochement${pendingReconcileItems.length ? ` (${pendingReconcileItems.length})` : ''}`}
              </button>
              <button className={styles.exportBtn} onClick={exportJournalToExcel}>
                📊 Excel
              </button>
              <button className={styles.secondaryBtn} onClick={() => setJournalData(null)}>
                Fermer
              </button>
            </div>
          </div>
          <div className={`${styles.tableWrapperScrollable} ${styles.tableRows10}`}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Libellé / Référence</th>
                  {showCompteColumn && <th>Compte</th>}
                  <th className={styles.numericCell}>Entrée</th>
                  <th className={styles.numericCell}>Sortie</th>
                  <th className={styles.numericCell}>Solde</th>
                  <th className={styles.reconcileHeader}>Pointé</th>
                </tr>
              </thead>
              <tbody>
                <tr className={styles.journalInitialRow}>
                  <td>{journalData.period?.start ? formatReportDate(journalData.period.start) : '-'}</td>
                  <td>Solde initial</td>
                  {showCompteColumn && <td>-</td>}
                  <td className={`${styles.numericCell} ${styles.amountCell}`}>-</td>
                  <td className={`${styles.numericCell} ${styles.amountCell}`}>-</td>
                  <td className={`${styles.numericCell} ${styles.amountCell}`}>
                    {toNumber(journalData.solde_initial).toLocaleString('fr-FR', { minimumFractionDigits: 2 })}
                  </td>
                  <td className={styles.reconcileCell}>-</td>
                </tr>
                {visibleJournalLines.length === 0 && (
                  <tr>
                    <td colSpan={showCompteColumn ? 7 : 6} className={styles.emptyCell}>
                      Aucun mouvement sur la période.
                    </td>
                  </tr>
                )}
                {visibleJournalLines.map((line, index) => {
                  const canReconcile = line.transaction_id && (line.transaction_type === 'ENCAISSEMENT' || line.transaction_type === 'SORTIE')
                  const currentReconcile = getLineReconcileValue(line)
                  return (
                  <tr key={`${line.date}-${index}`}>
                    <td>{formatReportDate(line.date)}</td>
                    <td>
                      {(line.libelle || '').trim()}
                      {line.reference ? ` (${line.reference})` : ''}
                    </td>
                    {showCompteColumn && <td>{line.compte_label || '-'}</td>}
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>
                      {toNumber(line.entree) > 0 ? toNumber(line.entree).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) : '-'}
                    </td>
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>
                      {toNumber(line.sortie) > 0 ? toNumber(line.sortie).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) : '-'}
                    </td>
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>
                      {toNumber(line.solde).toLocaleString('fr-FR', { minimumFractionDigits: 2 })}
                    </td>
                    <td className={styles.reconcileCell}>
                      {canReconcile ? (
                        <label className={styles.reconcileToggle}>
                          <input
                            type="checkbox"
                            checked={currentReconcile}
                            onChange={() => toggleReconcileDraft(line)}
                          />
                          <span>{currentReconcile ? <CheckCircle2 size={14} /> : <Circle size={14} />}</span>
                        </label>
                      ) : (
                        <span className={styles.reconcileMuted}>—</span>
                      )}
                    </td>
                  </tr>
                  )
                })}
                {visibleJournalLines.length > 0 && (
                  <tr className={styles.journalFinalRow}>
                    <td>{journalData.period?.end ? formatReportDate(journalData.period.end) : '-'}</td>
                    <td>Solde final</td>
                    {showCompteColumn && <td>-</td>}
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>-</td>
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>-</td>
                    <td className={`${styles.numericCell} ${styles.amountCell}`}>
                      {toNumber(journalData.solde_final).toLocaleString('fr-FR', { minimumFractionDigits: 2 })}
                    </td>
                    <td className={styles.reconcileCell}>-</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {sortiesWarning && !errorMessage && (
        <div className={styles.alert} role="status">
          <div>{sortiesWarning}</div>
          <button onClick={loadRapport} className={styles.retryBtn} disabled={loading}>
            Réessayer
          </button>
        </div>
      )}

      {detailsError && !errorMessage && (
        <div className={styles.alert} role="alert">
          <div>{detailsError}</div>
          <button onClick={loadDetails} className={styles.retryBtn} disabled={detailsLoading}>
            Réessayer
          </button>
        </div>
      )}

      {emptyMessage && !errorMessage && (
        <div className={styles.emptyState}>
          <div className={styles.emptyTitle}>Aucun rapport</div>
          <div className={styles.emptyText}>{emptyMessage}</div>
        </div>
      )}

      {rapport && !errorMessage && !emptyMessage && (
        <>
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>Total encaissements</div>
              <div className={styles.statValue} style={{ color: '#16a34a' }}>
                {formatCurrency(rapport.totalEncaissements)}
              </div>
              <div className={styles.statSubtext}>{rapport.nombreEncaissements} opérations</div>
              {toNumber(rapport.entreesInternes) > 0 && (
                <div style={{ marginTop: '8px', fontSize: '12px', lineHeight: 1.5, color: '#1d4ed8' }}>
                  Transferts internes reçus : <strong>{formatCurrency(rapport.entreesInternes)}</strong>
                  <div style={{ color: '#6b7280' }}>{transfertsRecusHint}</div>
                </div>
              )}
            </div>

            <div className={styles.statCard}>
              <div className={styles.statLabel}>Total sorties</div>
              <div className={styles.statValue} style={{ color: '#dc2626' }}>
                {formatCurrency(rapport.totalSorties)}
              </div>
              <div className={styles.statSubtext}>{rapport.nombreSorties} paiements</div>
              {toNumber(rapport.transfertsInternes) > 0 && (
                <div style={{ marginTop: '8px', fontSize: '12px', lineHeight: 1.5 }}>
                  <div style={{ color: '#b91c1c' }}>
                    Dépenses réelles : <strong>{formatCurrency(rapport.depensesReelles)}</strong>
                  </div>
                  <div style={{ color: '#1d4ed8' }}>
                    Transferts internes : <strong>{formatCurrency(rapport.transfertsInternes)}</strong>
                  </div>
                </div>
              )}
            </div>

            <div className={styles.statCard}>
              <div className={styles.statLabel}>Solde final</div>
              <div className={styles.statValue} style={{ color: '#2563eb' }}>
                {formatCurrency(rapport.soldeFinal ?? rapport.solde)}
              </div>
              <div className={styles.statSubtext}>
                Solde au {dateDebut} : {formatCurrency(rapport.soldeInitial ?? 0)}
              </div>
              <div className={styles.statBadge}>Solde initial inclus</div>
              <div className={styles.statSubtext}>
                {(rapport.soldeFinal ?? rapport.solde) >= 0 ? 'Excédent' : 'Déficit'}
              </div>
            </div>

            <div className={styles.statCard}>
              <div className={styles.statLabel}>Réquisitions</div>
              <div className={styles.statValue} style={{ color: '#f59e0b' }}>
                {rapport.nombreRequisitions}
              </div>
              <div className={styles.statSubtext}>demandes créées</div>
            </div>
          </div>

          {/* Les cartes ci-dessus additionnent les devises (héritage) : cette
              ventilation est la seule lecture exacte en environnement bi-devise.
              Affichée dès qu'une devise est connue, mise en avant si plusieurs. */}
          {(rapport.parDevise?.length ?? 0) > 0 && (
            <div className={styles.tableSection}>
              <h3>
                Détail par devise{multiDevises ? ' (montants non convertis)' : ''}
                {reportDevise !== 'ALL' && multiDevises ? ' — toutes devises, hors filtre' : ''}
              </h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Devise</th>
                      <th>Solde initial</th>
                      <th>Encaissements</th>
                      <th>Transferts reçus</th>
                      <th>Sorties</th>
                      <th>dont dépenses réelles</th>
                      <th>Solde</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rapport.parDevise.map((ligne: any) => (
                      <tr key={ligne.devise}>
                        <td><strong>{ligne.devise}</strong></td>
                        <td>{formatMoneyDevise(ligne.soldeInitial, ligne.devise)}</td>
                        <td>{formatMoneyDevise(ligne.encaissements, ligne.devise)}</td>
                        <td>{formatMoneyDevise(ligne.entreesInternes, ligne.devise)}</td>
                        <td>{formatMoneyDevise(ligne.sorties, ligne.devise)}</td>
                        <td>{formatMoneyDevise(ligne.depensesReelles, ligne.devise)}</td>
                        <td>
                          <strong>{formatMoneyDevise(ligne.solde, ligne.devise)}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {multiDevises && (
                <p style={{ marginTop: '8px', fontSize: '12px', color: '#6b7280' }}>
                  {reportDevise === 'ALL'
                    ? `Les totaux affichés plus haut cumulent ${devisesPresentes.join(
                        ' et '
                      )} sans conversion : s'y référer devise par devise.`
                    : `Vue ${reportDevise} : les totaux et graphiques ci-dessus ne comptent que cette devise. Les mouvements ${devisesPresentes
                        .filter((d) => d !== reportDevise)
                        .join(' et ')} figurent dans ce tableau uniquement.`}
                </p>
              )}
            </div>
          )}

          <div className={styles.chartsGrid}>
            <div className={styles.chartCard}>
              <h3>Encaissements par poste budgétaire</h3>
              <div className={`${styles.chartContent} ${styles.chartContentScrollable} ${styles.chartRows5}`}>
                {Object.entries(rapport.encaissementsParType || {}).map(([type, montant]: any) => (
                  <div key={type} className={styles.chartItem}>
                    <div className={styles.chartLabel}>{type}</div>
                    <div className={styles.chartValue}>{formatCurrency(montant)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.chartCard}>
              <h3>Encaissements par statut</h3>
              <div className={styles.chartContent}>
                {Object.entries(rapport.encaissementsParStatut || {}).map(([statut, count]: any) => (
                  <div key={statut} className={styles.chartItem}>
                    <div className={styles.chartLabel}>
                      {statut === 'non_paye' ? 'Non payé' :
                       statut === 'partiel' ? 'Partiel' :
                       statut === 'complet' ? 'Complet' : 'Avance'}
                    </div>
                    <div className={styles.chartValue}>{count}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.chartCard}>
              <h3>Encaissements par mode</h3>
              <div className={styles.chartContent}>
                {Object.entries(rapport.encaissementsParMode || {}).map(([mode, montant]: any) => (
                  <div key={mode} className={styles.chartItem}>
                    <div className={styles.chartLabel}>
                      {mode === 'cash' ? 'Cash' : mode === 'mobile_money' ? 'Mobile Money' : 'Opération bancaire'}
                    </div>
                    <div className={styles.chartValue}>{formatCurrency(montant)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.chartCard}>
              <h3>Sorties par mode de paiement</h3>
              <div className={styles.chartContent}>
                {Object.entries(rapport.sortiesParMode || {}).map(([mode, montant]: any) => (
                  <div key={mode} className={styles.chartItem}>
                    <div className={styles.chartLabel}>
                      {getSortieModeLabel(mode)}
                    </div>
                    <div className={styles.chartValue}>{formatCurrency(montant)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.chartCard}>
              <h3>Réquisitions par statut</h3>
              <div className={styles.chartContent}>
                {Object.entries(rapport.requisitionsParStatut || {}).map(([statut, count]: any) => (
                  <div key={statut} className={styles.chartItem}>
                    <div className={styles.chartLabel}>{statut}</div>
                    <div className={styles.chartValue}>{count}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className={styles.tableSection}>
            <h3>Encaissements</h3>
            <div className={`${styles.tableWrapper} ${styles.tableWrapperScrollable} ${styles.tableRows10}`}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>N° Note de débit</th>
                    <th>Client</th>
                    <th>Poste budgétaire</th>
                    <th>Montant payé</th>
                  </tr>
                </thead>
                <tbody>
                  {(rapport.encaissements || []).map((e: any) => (
                    <tr key={e.id}>
                      <td>{formatReportDate(e.date_encaissement)}</td>
                      <td>{e.numero_recu}</td>
                      <td>{e.expert_comptable?.nom_denomination || e.client_nom || '-'}</td>
                      <td>{[e.budget_poste_code, e.budget_poste_libelle].filter(Boolean).join(' - ') || '-'}</td>
                      <td>{formatCurrency(montantEncaissement(e))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.tableSection}>
            <h3>Sorties de fonds</h3>
            <div className={`${styles.tableWrapper} ${styles.tableWrapperScrollable} ${styles.tableRows10}`}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Référence</th>
                    <th>Réquisition</th>
                    <th>Montant</th>
                    <th>Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {(rapport.sorties || []).map((s: any) => (
                    <tr key={s.id}>
                      <td>{formatReportDate(s.date_paiement)}</td>
                      <td>{s.reference || '-'}</td>
                      <td>{s.requisition?.numero_requisition || s.requisition_id || '-'}</td>
                      <td>{formatCurrency(s.montant_paye ?? 0)}</td>
                      <td>{getSortieModeLabel(s.mode_paiement)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.tableSection}>
            <h3>Réquisitions</h3>
            {aiEnabled ? (
              <div className={styles.docIntelCard}>
                <div className={styles.docHeader}>
                  <div>
                    <div className={styles.docTitle}>RAPPORT DES RÉQUISITIONS DE FONDS</div>
                    <div className={styles.docSub}>Vue intelligence documentaire</div>
                  </div>
                  <div className={styles.docMeta}>
                    {dateDebut} → {dateFin}
                  </div>
                </div>

                {(() => {
                  const items = Array.isArray(rapport.requisitions) ? rapport.requisitions : []
                  const totalMontant = items.reduce((sum: number, r: any) => sum + toNumber(r.montant_total || 0), 0)
                  const totalPayee = items
                    .filter((r: any) => normalizeStatut(r.statut || r.status) === 'PAYEE')
                    .reduce((sum: number, r: any) => sum + toNumber(r.montant_total || 0), 0)
                  const totalRejete = items
                    .filter((r: any) => normalizeStatut(r.statut || r.status) === 'REJETEE')
                    .reduce((sum: number, r: any) => sum + toNumber(r.montant_total || 0), 0)
                  const totalPending = Math.max(0, totalMontant - totalPayee - totalRejete)

                  const rubriqueTotals = new Map<string, number>()
                  items.forEach((r: any) => {
                    const rub = normalizeRubrique(r.poste_budgetaire || '')
                    const key = rub || 'Non classé'
                    rubriqueTotals.set(key, (rubriqueTotals.get(key) || 0) + toNumber(r.montant_total || 0))
                  })
                  const topRubriques = Array.from(rubriqueTotals.entries())
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 4)

                  const totalSafe = totalMontant || 1
                  const paidPct = (totalPayee / totalSafe) * 100
                  const pendingPct = (totalPending / totalSafe) * 100
                  const rejectedPct = (totalRejete / totalSafe) * 100

                  return (
                    <>
                      <div className={styles.kpiRow}>
                        <div className={styles.kpiCard}>
                          <div className={styles.kpiLabel}>Total</div>
                          <div className={styles.kpiValue}>{formatCurrency(totalMontant)}</div>
                        </div>
                        <div className={styles.kpiCard}>
                          <div className={styles.kpiLabel}>Payé</div>
                          <div className={styles.kpiValue}>{formatCurrency(totalPayee)}</div>
                        </div>
                        <div className={styles.kpiCard}>
                          <div className={styles.kpiLabel}>En attente</div>
                          <div className={styles.kpiValue}>{formatCurrency(totalPending)}</div>
                        </div>
                        <div className={styles.kpiCard}>
                          <div className={styles.kpiLabel}>Rejeté</div>
                          <div className={styles.kpiValue}>{formatCurrency(totalRejete)}</div>
                        </div>
                      </div>

                      <div className={styles.tensionBar}>
                        <div className={styles.tensionPaid} style={{ width: `${paidPct}%` }} />
                        <div className={styles.tensionPending} style={{ width: `${pendingPct}%` }} />
                        <div className={styles.tensionRejected} style={{ width: `${rejectedPct}%` }} />
                      </div>

                      <div className={styles.rubriqueRow}>
                        {topRubriques.map(([label, total]) => (
                          <div key={label} className={styles.rubriqueChip}>
                            <span>{label}</span>
                            <strong>{formatCurrency(total)}</strong>
                          </div>
                        ))}
                      </div>

                      <div className={`${styles.smartList} ${styles.smartListScrollable}`}>
                        {items.map((r: any) => (
                          <div key={r.id} className={styles.smartItem}>
                            <div>
                              <div className={styles.smartTitle}>{r.objet || r.numero_requisition}</div>
                              <div className={styles.smartMeta}>
                                {r.numero_requisition} · {normalizeRubrique(r.poste_budgetaire || 'Non classé')}
                              </div>
                            </div>
                            <div className={styles.smartRight}>
                              <span className={`${styles.statusBadge} ${getStatutTone(r.statut || r.status)}`}>
                                {getStatutLabel(r.statut || r.status)}
                              </span>
                              <div className={styles.smartAmount}>{formatCurrency(r.montant_total || 0)}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )
                })()}
              </div>
            ) : (
              <div className={styles.alert} role="status">
                Le module IA est désactivé pour cette organisation. Activez-le depuis le cockpit super admin pour
                accéder à la vue intelligente des réquisitions.
              </div>
            )}
            <div className={`${styles.tableWrapper} ${styles.tableWrapperScrollable} ${styles.tableRows10}`}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>N° Réquisition</th>
                    <th>Statut</th>
                    <th>Montant</th>
                  </tr>
                </thead>
                <tbody>
                  {(rapport.requisitions || []).map((r: any) => (
                    <tr key={r.id}>
                      <td>{format(new Date(r.created_at), 'dd/MM/yyyy')}</td>
                      <td>{r.numero_requisition}</td>
                      <td>{r.statut || r.status}</td>
                      <td>{formatCurrency(r.montant_total ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
