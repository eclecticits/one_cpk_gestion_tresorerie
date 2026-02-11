import { useEffect, useMemo, useState } from 'react'
import { format, startOfMonth, endOfMonth } from 'date-fns'
import * as XLSX from 'xlsx'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import styles from './Rapports.module.css'
import { useToast } from '../hooks/useToast'
import type { ReportSummaryResponse } from '../types/reports'
import { toNumber } from '../utils/amount'
import type { Money } from '../types'

function buildQuery(params: Record<string, any>) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    sp.set(k, String(v))
  })
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

export default function Rapports() {
  const { notifyError, notifySuccess } = useToast()
  const { user } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const [dateDebut, setDateDebut] = useState(format(startOfMonth(new Date()), 'yyyy-MM-dd'))
  const [dateFin, setDateFin] = useState(format(endOfMonth(new Date()), 'yyyy-MM-dd'))
  const [loading, setLoading] = useState(false)
  const [rapport, setRapport] = useState<any>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null)
  const [sortiesWarning, setSortiesWarning] = useState<string | null>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [detailsLoaded, setDetailsLoaded] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [hasReportingAccess, setHasReportingAccess] = useState(false)
  const [checkingAccess, setCheckingAccess] = useState(true)
  const [lastEndpoints, setLastEndpoints] = useState<string[]>([])

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

  const loadRapport = async () => {
    setLoading(true)
    setErrorMessage(null)
    setEmptyMessage(null)
    setSortiesWarning(null)
    setDetailsLoaded(false)
    setDetailsError(null)
    try {
      const summaryUrl = '/reports/summary' + buildQuery({ date_debut: dateDebut, date_fin: dateFin })
      setLastEndpoints([summaryUrl])

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
        const parTypeOperation = Array.isArray(breakdowns.par_type_operation)
          ? breakdowns.par_type_operation
          : []
        const parStatutRequisition = Array.isArray(breakdowns.par_statut_requisition)
          ? breakdowns.par_statut_requisition
          : []

        const totalEncaissements = toNumber(totals.encaissements_total ?? 0)
        const totalSorties = toNumber(totals.sorties_total ?? 0)
        const soldeInitial = toNumber(totals.solde_initial ?? 0)
        const solde = toNumber(totals.solde ?? totalEncaissements - totalSorties)
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

        const encaissementsParType = parTypeOperation.reduce((acc: Record<string, number>, row: any) => {
          const key = row.key || row.type || 'autre'
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
          const statut = row.key || row.statut || 'brouillon'
          acc[statut] = (acc[statut] || 0) + (Number(row.count) || 0)
          return acc
        }, {})

        nextRapport = {
          totalEncaissements,
          totalSorties,
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
          '/encaissements' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 1000 })
        const sortUrl =
          '/sorties-fonds' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 1000 })
        const reqUrl =
          '/requisitions' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 1000 })

        setLastEndpoints([summaryUrl, encUrl, sortUrl, reqUrl])

        const [encaissements, sorties, requisitions] = await Promise.all([
          fetchWithLog('encaissements', encUrl),
          fetchWithLog('sorties-fonds', sortUrl).catch((err) => {
            console.error('[Rapports] Sorties indisponibles (fallback)', err)
            setSortiesWarning('Sorties indisponibles.')
            return []
          }),
          fetchWithLog('requisitions', reqUrl),
        ])

        const enc = Array.isArray(encaissements) ? encaissements : []
        const sor = Array.isArray(sorties) ? sorties : []
        const req = Array.isArray(requisitions) ? requisitions : []

        const totalEncaissements =
          enc.reduce((sum: number, e: any) => {
            const val = toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)
            return sum + (Number.isFinite(val) ? val : 0)
          }, 0) || 0

        const totalSorties =
          sor.reduce((sum: number, s: any) => {
            const val = toNumber(s.montant_paye ?? 0)
            return sum + (Number.isFinite(val) ? val : 0)
          }, 0) || 0

        const encaissementsParType = enc.reduce((acc: Record<string, number>, e: any) => {
          const key = e.type_operation || 'autre'
          const val = toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)
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
          const val = toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)
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
          const statut = r.statut || r.status || 'brouillon'
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

      if (nextRapport) {
        setRapport(nextRapport)
      } else {
        setRapport(null)
      }
      const hasData =
        !!nextRapport &&
        (nextRapport.nombreEncaissements > 0 ||
          nextRapport.nombreSorties > 0 ||
          nextRapport.nombreRequisitions > 0)
      if (!hasData) {
        setEmptyMessage('Aucune donnée trouvée pour la période sélectionnée.')
      }
    } catch (error: any) {
      console.error('Error loading rapport:', error)
      setRapport(null)
      const status = typeof error?.status === 'number' ? `HTTP ${error.status}` : null
      const detail = error?.payload?.detail || error?.payload?.message || error?.message || null
      const parts = [status, detail].filter(Boolean).join(' - ')
      setErrorMessage(
        parts
          ? `Impossible de charger les rapports. (${parts})`
          : "Impossible de charger les rapports. Vérifie ton accès ou le serveur API."
      )
      if (lastEndpoints.length) {
        console.log('[Rapports] Last endpoints', lastEndpoints)
      }
    } finally {
      setLoading(false)
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
        buildQuery({ date_debut: dateDebut, date_fin: dateFin, include: 'expert_comptable', limit: 5000 })
      const sortUrl =
        '/sorties-fonds' +
        buildQuery({ date_debut: dateDebut, date_fin: dateFin, include: 'requisition', limit: 5000 })
      const reqUrl =
        '/requisitions' + buildQuery({ date_debut: dateDebut, date_fin: dateFin, limit: 5000 })

      const encPromise = fetchWithLog('encaissements-details', encUrl)
      const reqPromise = fetchWithLog('requisitions-details', reqUrl)
      const sortPromise = fetchWithLog('sorties-fonds-details', sortUrl).catch((err) => {
        console.error('[Rapports] Sorties indisponibles (détails)', err)
        setSortiesWarning('Sorties indisponibles.')
        return []
      })

      const [encaissements, sorties, requisitions] = await Promise.all([
        encPromise,
        sortPromise,
        reqPromise,
      ])

      const enc = Array.isArray(encaissements) ? encaissements : []
      const sor = Array.isArray(sorties) ? sorties : []
      const req = Array.isArray(requisitions) ? requisitions : []

      setRapport((prev: any) => ({
        ...prev,
        encaissements: enc,
        sorties: sor,
        requisitions: req,
      }))
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

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const periodeLabel = useMemo(() => {
    return `du ${format(new Date(dateDebut), 'dd/MM/yyyy')} au ${format(new Date(dateFin), 'dd/MM/yyyy')}`
  }, [dateDebut, dateFin])

  const exportToExcel = async () => {
    try {
      if (!rapport) return

      const encUrl =
        '/encaissements' +
        buildQuery({ date_debut: dateDebut, date_fin: dateFin, include: 'expert_comptable', limit: 5000 })
      const sortUrl =
        '/sorties-fonds' +
        buildQuery({ date_debut: dateDebut, date_fin: dateFin, include: 'requisition', limit: 5000 })

      const [encaissements, sorties] = await Promise.all([
        apiRequest('GET', encUrl),
        apiRequest('GET', sortUrl),
      ])

      const enc = Array.isArray(encaissements) ? encaissements : []
      const sor = Array.isArray(sorties) ? sorties : []

      const wb = XLSX.utils.book_new()

      const summaryData = [
        ['RAPPORT FINANCIER'],
        [`Période : ${periodeLabel}`],
        [],
        ['RÉSUMÉ'],
        ['Total Encaissements', formatCurrency(rapport.totalEncaissements)],
        ['Total Sorties', formatCurrency(rapport.totalSorties)],
        [`Solde au ${dateDebut}`, formatCurrency(rapport.soldeInitial ?? 0)],
        ['Solde final', formatCurrency(rapport.soldeFinal ?? rapport.solde)],
        ["Nombre d'encaissements", rapport.nombreEncaissements],
        ['Nombre de sorties', rapport.nombreSorties],
        ['Nombre de réquisitions', rapport.nombreRequisitions],
      ]
      const summarySheet = XLSX.utils.aoa_to_sheet(summaryData)
      XLSX.utils.book_append_sheet(wb, summarySheet, 'Résumé')

      const encaissementsData = [
        ['Date', 'N° Reçu', 'Client', 'Rubrique', 'Type', 'Description', 'Montant Total', 'Montant Payé', 'Statut', 'Mode de paiement'],
        ...enc.map((e: any) => {
          const montantTotal = toNumber(e.montant_total ?? e.montant ?? 0)
          const montantPaye = toNumber(e.montant_paye ?? 0)
          const typeOp = e.type_operation || 'autre'
          const rubrique = typeOp === 'formation' ? 'Formation' : typeOp === 'livre' ? 'Livre' : 'Autre'
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
            rubrique,
            typeOp,
            e.description || '',
            Number.isFinite(montantTotal) ? montantTotal : 0,
            Number.isFinite(montantPaye) ? montantPaye : 0,
            statut,
            e.mode_paiement || '',
          ]
        })
      ]
      const encaissementsSheet = XLSX.utils.aoa_to_sheet(encaissementsData)
      XLSX.utils.book_append_sheet(wb, encaissementsSheet, 'Encaissements')

      const sortiesDataWithRubriques = await Promise.all(
        sor.map(async (s: any) => {
          let rubriques = ''
          if (s.requisition_id) {
            const lignesUrl = '/lignes-requisition' + buildQuery({ requisition_id: s.requisition_id })
            const lignesRes: any = await apiRequest('GET', lignesUrl)
            const lignes = Array.isArray(lignesRes) ? lignesRes : []
            rubriques = lignes.length ? [...new Set(lignes.map((l: any) => l.rubrique))].join(', ') : ''
          }

          return [
            format(new Date(s.date_paiement), 'dd/MM/yyyy'),
            s.reference || '',
            s.requisition?.numero_requisition || '',
            s.requisition?.objet || '',
            rubriques,
            toNumber(s.montant_paye ?? 0),
            s.mode_paiement || '',
          ]
        })
      )

      const sortiesData = [
        ['Date', 'Référence', 'N° Réquisition', 'Objet', 'Rubrique', 'Montant', 'Mode de paiement'],
        ...sortiesDataWithRubriques
      ]
      const sortiesSheet = XLSX.utils.aoa_to_sheet(sortiesData)
      XLSX.utils.book_append_sheet(wb, sortiesSheet, 'Sorties de Fonds')

      XLSX.writeFile(wb, `rapport_${dateDebut}_${dateFin}.xlsx`)
      notifySuccess('Export Excel', 'Le fichier a été téléchargé.')
    } catch (error) {
      console.error('Error exporting to Excel:', error)
      notifyError("Erreur d'export", "Une erreur est survenue lors de l'export vers Excel.")
    }
  }

  const exportToPDF = () => {
    const originalTitle = document.title
    const dateStr = `${format(new Date(dateDebut), 'yyyy-MM-dd')}_${format(new Date(dateFin), 'yyyy-MM-dd')}`
    document.title = `Rapport_Tresorerie_${dateStr}_ONEC_CPK`
    window.print()
    setTimeout(() => {
      document.title = originalTitle
    }, 100)
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
        <div className={styles.header}>
          <h1>Accès refusé</h1>
          <p>Vous n'avez pas les privilèges nécessaires pour accéder aux rapports. Contactez un administrateur.</p>
        </div>
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

      {errorMessage && (
        <div className={styles.alert} role="alert">
          <div>{errorMessage}</div>
          <button onClick={loadRapport} className={styles.retryBtn} disabled={loading}>
            Réessayer
          </button>
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
            </div>

            <div className={styles.statCard}>
              <div className={styles.statLabel}>Total sorties</div>
              <div className={styles.statValue} style={{ color: '#dc2626' }}>
                {formatCurrency(rapport.totalSorties)}
              </div>
              <div className={styles.statSubtext}>{rapport.nombreSorties} paiements</div>
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

          <div className={styles.chartsGrid}>
            <div className={styles.chartCard}>
              <h3>Encaissements par type</h3>
              <div className={styles.chartContent}>
                {Object.entries(rapport.encaissementsParType || {}).map(([type, montant]: any) => (
                  <div key={type} className={styles.chartItem}>
                    <div className={styles.chartLabel}>
                      {type === 'formation' ? 'Formation' : type === 'livre' ? 'Livre' : 'Autre'}
                    </div>
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
                      {mode === 'cash' ? 'Cash' : mode === 'mobile_money' ? 'Mobile Money' : 'Virement'}
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
                      {mode === 'cash' ? 'Cash' : mode === 'mobile_money' ? 'Mobile Money' : 'Virement'}
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
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>N° Reçu</th>
                    <th>Client</th>
                    <th>Type</th>
                    <th>Montant payé</th>
                  </tr>
                </thead>
                <tbody>
                  {(rapport.encaissements || []).map((e: any) => (
                    <tr key={e.id}>
                      <td>{format(new Date(e.date_encaissement), 'dd/MM/yyyy')}</td>
                      <td>{e.numero_recu}</td>
                      <td>{e.expert_comptable?.nom_denomination || e.client_nom || '-'}</td>
                      <td>{e.type_operation}</td>
                      <td>{formatCurrency(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.tableSection}>
            <h3>Sorties de fonds</h3>
            <div className={styles.tableWrapper}>
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
                      <td>{s.date_paiement ? format(new Date(s.date_paiement), 'dd/MM/yyyy') : '-'}</td>
                      <td>{s.reference || '-'}</td>
                      <td>{s.requisition?.numero_requisition || s.requisition_id || '-'}</td>
                      <td>{formatCurrency(s.montant_paye ?? 0)}</td>
                      <td>{s.mode_paiement || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className={styles.tableSection}>
            <h3>Réquisitions</h3>
            <div className={styles.tableWrapper}>
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
