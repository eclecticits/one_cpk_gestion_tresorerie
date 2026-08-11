import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Check, Printer, Ban } from 'lucide-react'
import { format } from 'date-fns'
import { downloadExcel } from '../utils/download'

import { apiRequest, ApiError } from '../lib/apiClient'
import { getBudgetPostes } from '../api/budget'
import { getServices } from '../api/services'
import { listProjetsActivites, ProjetActivite } from '../api/projetsActivites'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { Encaissement, Service } from '../types'
import { getPrintSettings } from '../api/settings'
import { toNumber } from '../utils/amount'

import styles from './Encaissements.module.css'
import PrintReceipt from '../components/PrintReceipt'
import PaymentManager from '../components/PaymentManager'
import NotificationModal from '../components/NotificationModal'
import EncaissementForm from '../components/EncaissementForm'
import EncaissementTable from '../components/EncaissementTable'
import EncaissementFilters from '../components/EncaissementFilters'
import { generateEncaissementsReportPDF } from '../utils/pdfGeneratorReports'
import PageHeader from '../components/PageHeader'
import CaisseSessionBanner from '../components/CaisseSessionBanner'
import { useTreasuryLock } from '../hooks/useTreasuryLock'
import { useConfirmWithInput } from '../contexts/ConfirmContext'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

interface Notification {
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message: string
  details?: string
}

function buildQuery(params: Record<string, any>) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    sp.set(k, String(v))
  })
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

const normalizeDateInput = (value: string | null | undefined) => {
  if (!value) return null
  const raw = String(value).trim()
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(raw)) {
    const [day, month, year] = raw.split('/')
    return `${year}-${month}-${day}`
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return raw
  }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return null
  return format(parsed, 'yyyy-MM-dd')
}

export default function Encaissements() {
  const { user } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const confirmWithInput = useConfirmWithInput()
  const location = useLocation()
  const navigate = useNavigate()
  const isCreatePage = location.pathname === '/encaissements/nouveau'

  const [showForm, setShowForm] = useState(false)
  const [encaissements, setEncaissements] = useState<Encaissement[]>([])
  const [budgetLines, setBudgetPostes] = useState<any[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [projetsActivites, setProjetsActivites] = useState<ProjetActivite[]>([])
  const [loading, setLoading] = useState(true)
  const [pageSize, setPageSize] = useState(15)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [summaryTotals, setSummaryTotals] = useState({ totalNotesDebit: 0, totalPaye: 0 })
  const { isCaisseClosed: isCashClosed } = useTreasuryLock()
  const [comptesBancaires, setComptesBancaires] = useState<any[]>([])

  const [proformas, setProformas] = useState<Encaissement[]>([])

  const [printingEncaissement, setPrintingEncaissement] = useState<Encaissement | null>(null)
  const [managingPayment, setManagingPayment] = useState<Encaissement | null>(null)

  const [notification, setNotification] = useState<Notification | null>(null)

  const today = useMemo(() => format(new Date(), 'yyyy-MM-dd'), [])
  const [dateDebut, setDateDebut] = useState(today)
  const [dateFin, setDateFin] = useState(today)
  const [pendingDateDebut, setPendingDateDebut] = useState(today)
  const [pendingDateFin, setPendingDateFin] = useState(today)
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterOperationStatus, setFilterOperationStatus] = useState<string>('ACTIVE')
  const [filterNumeroRecu, setFilterNumeroRecu] = useState('')
  const [filterClient, setFilterClient] = useState('')
  // La liste est paginée côté serveur : filtrer sur le client fausserait les
  // totaux et la pagination. On retarde donc l'appel plutôt que de l'émettre à
  // chaque caractère — la saisie reste fluide, le réseau reste calme. Les
  // exports utilisent la même valeur, pour livrer exactement le tableau affiché.
  const debouncedNumeroRecu = useDebouncedValue(filterNumeroRecu)
  const debouncedClient = useDebouncedValue(filterClient)
  const [filterBudgetPosteId, setFilterBudgetPosteId] = useState<string>('')
  const [tauxChange, setTauxChange] = useState<number>(1)
  const [libellePresets, setLibellePresets] = useState<string[]>([])

  const userServiceIds = useMemo(() => {
    if (user?.service_ids && user.service_ids.length > 0) return user.service_ids
    if (user?.service_id) return [user.service_id]
    return []
  }, [user?.service_ids, user?.service_id])

  const isServiceUser = useMemo(() => {
    return userServiceIds.length > 0 && user?.role !== 'admin' && user?.role !== 'super_admin'
  }, [userServiceIds, user?.role])

  const formatCurrency = useCallback((amount: string | number | null | undefined) => {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(amount))
  }, [])

  const loadData = useCallback(async () => {
    try {
      setLoading(true)

      const encPath =
        '/encaissements' + buildQuery({
          include: 'expert_comptable',
          date_debut: dateDebut,
          date_fin: dateFin,
          statut_paiement: filterStatut,
          numero_recu: debouncedNumeroRecu,
          client: debouncedClient,
          budget_poste_id: filterBudgetPosteId,
          operation_status: filterOperationStatus,
          est_proforma: false,
          order: 'date_encaissement.desc',
          limit: pageSize,
          offset: (page - 1) * pageSize,
          include_summary: true,
        })
      const proformaPath =
        '/encaissements' +
        buildQuery({
          include: 'expert_comptable',
          est_proforma: true,
          order: 'date_encaissement.desc',
          limit: 200,
          offset: 0,
        })

      const [encRes, proRes, servicesRes] = await Promise.all([
        apiRequest<any>('GET', encPath),
        apiRequest<any>('GET', proformaPath),
        getServices({ active: true }),
      ])

      const encItems = Array.isArray(encRes) ? encRes : (encRes?.items ?? [])
      setEncaissements(encItems)
      const proItems = Array.isArray(proRes) ? proRes : (proRes?.items ?? [])
      setProformas(Array.isArray(proItems) ? proItems : [])
      setTotalCount(
        typeof encRes?.total === 'number' ? encRes.total : Array.isArray(encItems) ? encItems.length : 0
      )
      if (encRes?.total_montant_facture !== undefined || encRes?.total_montant_paye !== undefined) {
        setSummaryTotals({
          totalNotesDebit: toNumber(encRes.total_montant_facture ?? 0),
          totalPaye: toNumber(encRes.total_montant_paye ?? 0),
        })
      } else {
        const fallbackTotalNotesDebit = (encItems as Encaissement[]).reduce(
          (sum, e) => sum + toNumber(e.montant_total || e.montant || 0),
          0
        )
        const fallbackTotalPaye = (encItems as Encaissement[]).reduce(
          (sum, e) => sum + toNumber(e.montant_paye || 0),
          0
        )
        setSummaryTotals({ totalNotesDebit: fallbackTotalNotesDebit, totalPaye: fallbackTotalPaye })
      }
      setServices(Array.isArray(servicesRes) ? servicesRes : [])
    } catch (error) {
      console.error('Error loading data:', error)
      let details = 'Vérifie la connexion au backend / API_BASE_URL.'
      if (error instanceof ApiError) {
        const payloadDetail = (error.payload as any)?.detail
        if (typeof payloadDetail === 'string') {
          details = payloadDetail
        } else if (Array.isArray(payloadDetail)) {
          details = payloadDetail.map((d) => d?.msg || d?.message || String(d)).join(' | ')
        } else if (error.message) {
          details = error.message
        }
        if (error.payload) {
          const payloadStr = JSON.stringify(error.payload)
          if (payloadStr && payloadStr !== '{}' && !details.includes(payloadStr)) {
            details = `${details} | ${payloadStr}`
          }
        }
      } else if (error && typeof (error as any).message === 'string') {
        details = (error as any).message
      } else {
        details = String(error)
      }
      setNotification({
        type: 'error',
        title: 'Erreur de chargement',
        message: 'Impossible de charger les données.',
        details,
      })
    } finally {
      setLoading(false)
    }
  }, [
    dateDebut,
    dateFin,
    filterStatut,
    debouncedNumeroRecu,
    debouncedClient,
    filterBudgetPosteId,
    filterOperationStatus,
    pageSize,
    page,
  ])

  const loadBudgetLines = useCallback(
    async (serviceId: number | null) => {
      if (isServiceUser && !serviceId) {
        setBudgetPostes([])
        return
      }
      if (isServiceUser || serviceId) {
        const res = await apiRequest<any>('GET', '/budget/lines/autorisees', {
          params: {
            type: 'RECETTE',
            active: true,
            service_id: serviceId ?? undefined,
          },
        })
        setBudgetPostes(res?.lignes ?? [])
        return
      }
      const budgetRes = await getBudgetPostes({ type: 'RECETTE', active: true })
      setBudgetPostes(budgetRes?.postes ?? [])
    },
    [isServiceUser]
  )

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const loadComptes = async () => {
      try {
        const res = await apiRequest('GET', '/comptes-bancaires', { params: { active: true } })
        setComptesBancaires(Array.isArray(res) ? res : [])
      } catch {
        setComptesBancaires([])
      }
    }
    loadComptes()
  }, [])

  useEffect(() => {
    listProjetsActivites(true).then(setProjetsActivites).catch(() => setProjetsActivites([]))
  }, [])

  useEffect(() => {
    loadBudgetLines(null)
  }, [loadBudgetLines])

  const loadPrintSettings = useCallback(async () => {
    try {
      const settings = await getPrintSettings()
      const rate = Number(settings.exchange_rate_cdf || settings.exchange_rate || 1)
      setTauxChange(rate > 0 ? rate : 1)
      const presetsRaw = String(settings.encaissement_libelle_presets || '')
      const presets = presetsRaw
        .split(/\r?\n+/)
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
      setLibellePresets(presets)
    } catch {
      setTauxChange(1)
      setLibellePresets([])
    }
  }, [])

  useEffect(() => {
    loadPrintSettings()
  }, [loadPrintSettings])

  useEffect(() => {
    setPage(1)
  }, [dateDebut, dateFin, filterStatut, debouncedNumeroRecu, debouncedClient, filterBudgetPosteId, filterOperationStatus, pageSize])

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(page, totalPages)

  const budgetTree = useMemo(() => {
    const nodes = new Map<number, any>()
    const roots: any[] = []

    budgetLines.forEach((line: any) => {
      nodes.set(line.id, { ...line, children: [] })
    })

    budgetLines.forEach((line: any) => {
      const node = nodes.get(line.id)
      if (line.parent_id && nodes.has(line.parent_id)) {
        nodes.get(line.parent_id).children.push(node)
      } else {
        roots.push(node)
      }
    })

    const sortNodes = (list: any[]) => {
      list.sort((a, b) => String(a.code || '').localeCompare(String(b.code || '')))
      list.forEach((item) => sortNodes(item.children))
    }
    sortNodes(roots)
    return roots
  }, [budgetLines])

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const filteredEncaissements = useMemo(() => {
    const items = Array.isArray(encaissements) ? [...encaissements] : []
    items.sort((a, b) => {
      const da = new Date(a.date_encaissement).getTime()
      const db = new Date(b.date_encaissement).getTime()
      if (db !== da) return db - da
      const ca = new Date(a.created_at).getTime()
      const cb = new Date(b.created_at).getTime()
      return cb - ca
    })
    return items
  }, [encaissements])

  const totalEncaissements = useMemo(() => summaryTotals.totalPaye, [summaryTotals.totalPaye])
  const totalMontantNotesDebit = useMemo(() => summaryTotals.totalNotesDebit, [summaryTotals.totalNotesDebit])
  const totalResteAPayer = useMemo(() => totalMontantNotesDebit - totalEncaissements, [totalMontantNotesDebit, totalEncaissements])

  const resetFilters = useCallback(() => {
    setPendingDateDebut(today)
    setPendingDateFin(today)
    setDateDebut(today)
    setDateFin(today)
    setFilterStatut('')
    setFilterOperationStatus('ACTIVE')
    setFilterNumeroRecu('')
    setFilterClient('')
    setFilterBudgetPosteId('')
    setPage(1)
  }, [today])

  const applyDateFilters = useCallback(() => {
    setDateDebut(pendingDateDebut)
    setDateFin(pendingDateFin)
    setPage(1)
  }, [pendingDateDebut, pendingDateFin])

  const hasPendingDateFilters = pendingDateDebut !== dateDebut || pendingDateFin !== dateFin
  const hasActiveFilters = dateDebut || dateFin || filterStatut || filterNumeroRecu || filterClient || filterBudgetPosteId || filterOperationStatus !== 'ACTIVE'

  const exportToExcel = useCallback(async () => {
    try {
      const suffix = `${dateDebut || 'debut'}_${dateFin || 'fin'}`
      await downloadExcel('/exports/encaissements', {
        date_debut: dateDebut,
        date_fin: dateFin,
        statut_paiement: filterStatut,
        numero_recu: debouncedNumeroRecu,
        client: debouncedClient,
        budget_poste_id: filterBudgetPosteId,
        operation_status: filterOperationStatus,
        est_proforma: false,
      }, `encaissements_${suffix}.xlsx`)
    } catch (error) {
      console.error('Error exporting encaissements:', error)
      setNotification({
        type: 'error',
        title: "Erreur d'export",
        message: "Impossible d'exporter les encaissements.",
      })
    }
  }, [
    dateDebut,
    dateFin,
    filterStatut,
    debouncedNumeroRecu,
    debouncedClient,
    filterBudgetPosteId,
    filterOperationStatus,
  ])

  const exportToPDF = useCallback(async () => {
    const startFilter = normalizeDateInput(dateDebut)
    const endFilter = normalizeDateInput(dateFin)
    const exportPath =
      '/encaissements' +
      buildQuery({
        include: 'expert_comptable',
        date_debut: startFilter ?? dateDebut,
        date_fin: endFilter ?? dateFin,
        statut_paiement: filterStatut,
        numero_recu: debouncedNumeroRecu,
        client: debouncedClient,
        budget_poste_id: filterBudgetPosteId,
        operation_status: filterOperationStatus,
        est_proforma: false,
        order: 'date_encaissement.desc',
        limit: 5000,
        offset: 0,
      })
    const exportRes = await apiRequest<Encaissement[]>('GET', exportPath)
    const exportItems = Array.isArray(exportRes) ? exportRes : (exportRes as any)?.items ?? []

    const filteredItems = (startFilter || endFilter)
      ? exportItems.filter((enc: Encaissement) => {
          const encDate = normalizeDateInput(String(enc.date_encaissement || ''))
          if (!encDate) return false
          if (startFilter && encDate < startFilter) return false
          if (endFilter && encDate > endFilter) return false
          return true
        })
      : exportItems

    const dataForPDF = filteredItems.map((enc: Encaissement) => ({
      ...enc,
      client: enc.expert_comptable
        ? `${enc.expert_comptable.numero_ordre} - ${enc.expert_comptable.nom_denomination}`
        : enc.client_nom || '',
      matricule: enc.expert_comptable?.numero_ordre || (enc as any).matricule || '',
      rubrique: enc.budget_poste_code
        ? `${enc.budget_poste_code} - ${enc.budget_poste_libelle || ''}`.trim()
        : '—',
    }))

    const start = startFilter || dateDebut || format(new Date(), 'yyyy-MM-dd')
    const end = endFilter || dateFin || format(new Date(), 'yyyy-MM-dd')

    await generateEncaissementsReportPDF(dataForPDF as any, {
      dateDebut: start,
      dateFin: end,
      filters: [
        filterStatut
          ? {
              label: 'Statut',
              value:
                filterStatut === 'complet'
                  ? 'Payé'
                  : filterStatut === 'partiel'
                  ? 'Partiel'
                  : filterStatut === 'avance'
                  ? 'Avance'
                  : filterStatut,
            }
          : null,
        filterNumeroRecu ? { label: 'N° Note de débit', value: filterNumeroRecu } : null,
        filterClient ? { label: 'Client', value: filterClient } : null,
        filterOperationStatus !== 'ACTIVE'
          ? { label: 'Opérations', value: filterOperationStatus }
          : null,
      ],
    })
  }, [dateDebut, dateFin, filterStatut, debouncedNumeroRecu, debouncedClient, filterBudgetPosteId, filterOperationStatus])

  const handleConvertProforma = async (proforma: Encaissement) => {
    if (!proforma?.id) return
    const confirmed = window.confirm(
      `Confirmer le paiement de la pro forma de note de débit ${proforma.numero_proforma || ''} ?`
    )
    if (!confirmed) return
    try {
      const montantPaye =
        (proforma.devise_perception || 'USD') === 'CDF'
          ? Number(proforma.montant_percu || 0)
          : Number(proforma.montant_total || proforma.montant || 0)
      const res = await apiRequest<any>('POST', `/encaissements/${proforma.id}/convertir`, {
        montant_paye: montantPaye,
        mode_paiement: proforma.mode_paiement,
        reference: proforma.reference || null,
        canal: proforma.canal,
        compte_bancaire_id: proforma.compte_bancaire_id || null,
      })
      const converted = Array.isArray(res) ? res[0] : res
      await loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))
      setNotification({
        type: 'success',
        title: 'Paiement confirmé',
        message: `La pro forma de note de débit a été convertie en note de débit ${converted?.numero_recu || ''}.`,
      })
    } catch (error: any) {
      console.error('Error converting proforma:', error)
      setNotification({
        type: 'error',
        title: 'Conversion impossible',
        message: error?.message || 'Une erreur est survenue lors de la conversion.',
      })
    }
  }

  const handleCancelProforma = async (proforma: Encaissement) => {
    if (!proforma?.id) return
    const confirmed = window.confirm(
      `Annuler la pro forma de note de débit ${proforma.numero_proforma || ''} ?`
    )
    if (!confirmed) return
    try {
      await apiRequest('POST', `/encaissements/${proforma.id}/cancel-proforma`)
      await loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))
      setNotification({
        type: 'success',
        title: 'Pro forma annulée',
        message: `La pro forma de note de débit a été annulée.`,
      })
    } catch (error: any) {
      console.error('Error canceling proforma:', error)
      setNotification({
        type: 'error',
        title: 'Annulation impossible',
        message: error?.message || 'Une erreur est survenue lors de l\'annulation.',
      })
    }
  }

  const handleCancelEncaissement = async (encaissement: Encaissement) => {
    const result = await confirmWithInput({
      title: 'Annuler cette opération ?',
      description: 'Voulez-vous vraiment annuler cette opération ? Cette action modifiera les soldes et les rapports financiers.',
      confirmText: 'Annuler l’opération',
      variant: 'danger',
      inputLabel: 'Motif d’annulation (obligatoire)',
      inputPlaceholder: 'Ex: opération saisie deux fois',
      inputRequired: true,
      inputMultiline: true,
      inputRows: 3,
    })
    if (!result.confirmed) return
    if (!result.value?.trim()) {
      setNotification({
        type: 'warning',
        title: 'Motif requis',
        message: "Le motif d'annulation est obligatoire.",
      })
      return
    }
    try {
      await apiRequest('POST', `/encaissements/${encaissement.id}/cancel-operation`, {
        motif_annulation: result.value.trim(),
      })
      await loadData()
      if (managingPayment?.id === encaissement.id) setManagingPayment(null)
      if (printingEncaissement?.id === encaissement.id) setPrintingEncaissement(null)
      window.dispatchEvent(new Event('dashboard-refresh'))
      setNotification({
        type: 'success',
        title: 'Opération annulée',
        message: `La note de débit ${encaissement.numero_recu || '—'} a été annulée.`,
      })
    } catch (error: any) {
      setNotification({
        type: 'error',
        title: 'Annulation impossible',
        message: error?.message || 'Une erreur est survenue lors de l’annulation.',
      })
    }
  }

  if (loading || permissionsLoading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonGrid}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`enc-skel-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
              <div className={styles.skeletonLine} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  const form = (
    <EncaissementForm
      user={user}
      services={services}
      projetsActivites={projetsActivites}
      comptesBancaires={comptesBancaires}
      isCashClosed={isCashClosed}
      tauxChange={tauxChange}
      libellePresets={libellePresets}
      budgetTree={budgetTree}
      variant={isCreatePage ? 'page' : 'modal'}
      formId="encaissement-form"
      onClose={() => {
        if (isCreatePage) navigate('/encaissements')
        else setShowForm(false)
      }}
      onSuccess={(message, details) => {
        setNotification({
          type: 'success',
          title: 'Encaissement créé',
          message,
          details,
        })
      }}
      onError={(title, message, details) => {
        setNotification({
          type: 'error',
          title,
          message,
          details,
        })
      }}
      onProformaCreated={(numero, montant) => {
        setNotification({
          type: 'success',
          title: 'Pro forma créée',
          message: `La pro forma de note de débit ${numero} a été enregistrée.`,
          details: `Montant total : ${formatCurrency(montant)}`,
        })
      }}
      loadData={loadData}
      loadBudgetLines={loadBudgetLines}
    />
  )

  return (
    <div className={styles.container}>
      <PageHeader
        title={isCreatePage ? 'Nouvel encaissement' : 'Encaissements'}
        subtitle={isCreatePage ? 'Enregistrez un paiement ou une recette' : 'Enregistrement des paiements et recettes'}
        actions={
          isCreatePage ? (
            <div className={styles.headerActions}>
              <Link to="/" className={styles.breadcrumbLink}>Accueil</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <Link to="/encaissements" className={styles.breadcrumbLink}>Encaissements</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <span className={styles.breadcrumbCurrent}>Nouvel encaissement</span>
              <Link to="/encaissements" className={styles.secondaryBtn}>
                Retour à la liste
              </Link>
              <button
                type="submit"
                form="encaissement-form"
                className={styles.primaryBtn}
              >
                Enregistrer l’encaissement
              </button>
            </div>
          ) : hasPermission('encaissements') && (
            <div className={styles.headerActions}>
              <Link to="/clients" className={styles.secondaryBtn}>
                Gérer les clients
              </Link>
              <Link to="/encaissements/nouveau" className={styles.primaryBtn}>
                + Nouvel encaissement
              </Link>
            </div>
          )
        }
      />

      <CaisseSessionBanner />

      {isCreatePage && (
        <>
          {form}
          {notification && (
            <NotificationModal
              type={notification.type}
              title={notification.title}
              message={notification.message}
              details={notification.details}
              onClose={() => setNotification(null)}
              autoClose={notification.type === 'success'}
            />
          )}
        </>
      )}

      {!isCreatePage && (
        <>

      {totalCount > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {safePage} / {totalPages}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
          >
            Suivant →
          </button>
        </div>
      )}

      <EncaissementFilters
        dateDebut={pendingDateDebut}
        setDateDebut={setPendingDateDebut}
        dateFin={pendingDateFin}
        setDateFin={setPendingDateFin}
        applyDateFilters={applyDateFilters}
        hasPendingDateFilters={hasPendingDateFilters}
        filterStatut={filterStatut}
        setFilterStatut={setFilterStatut}
        filterNumeroRecu={filterNumeroRecu}
        setFilterNumeroRecu={setFilterNumeroRecu}
        filterClient={filterClient}
        setFilterClient={setFilterClient}
        filterBudgetPosteId={filterBudgetPosteId}
        setFilterBudgetPosteId={setFilterBudgetPosteId}
        filterOperationStatus={filterOperationStatus}
        setFilterOperationStatus={setFilterOperationStatus}
        canViewCancelled={hasPermission('view_cancelled_financial_operations')}
        budgetLines={budgetLines}
        pageSize={pageSize}
        setPageSize={setPageSize}
        hasActiveFilters={!!hasActiveFilters}
        resetFilters={resetFilters}
        totalCount={totalCount}
        exportToExcel={exportToExcel}
        exportToPDF={exportToPDF}
        totalMontantNotesDebit={totalMontantNotesDebit}
        totalEncaissements={totalEncaissements}
        totalResteAPayer={totalResteAPayer}
        formatCurrency={formatCurrency}
        filteredCount={filteredEncaissements.length}
      />

      {showForm && form}

      <div className={styles.proformaSection}>
        <div className={styles.sectionHeader}>
          <h3>Pro formas de notes de débit en attente</h3>
          <span className={styles.countBadge}>{proformas.length}</span>
        </div>
        {proformas.length === 0 ? (
          <div className={styles.emptyCards}>Aucune pro forma de note de débit en attente</div>
        ) : (
          <div className={styles.proformaTableContainer}>
            <table className={styles.proformaTable}>
              <thead>
                <tr>
                  <th>N° Pro forma</th>
                  <th>Date</th>
                  <th>Client</th>
                  <th>Libellé</th>
                  <th>Montant</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {proformas.map((pro) => (
                  <tr key={`pro-${pro.id}`}>
                    <td>
                      <strong>{pro.numero_proforma || '—'}</strong>
                    </td>
                    <td>{format(new Date(pro.date_encaissement), 'dd/MM/yyyy')}</td>
                    <td>
                      {pro.expert_comptable
                        ? `${pro.expert_comptable.nom_denomination} (${pro.expert_comptable.numero_ordre})`
                        : pro.client_nom || '—'}
                    </td>
                    <td>{pro.libelle || '—'}</td>
                    <td>
                      <strong>{formatCurrency(pro.montant_total || pro.montant || 0)}</strong>
                      {pro.devise_perception === 'CDF' && (
                        <div className={styles.inlineNote}>
                          Perçu: {formatCurrency(pro.montant_percu)} CDF
                        </div>
                      )}
                    </td>
                    <td>
                      <div className={styles.actionBtns}>
                        <button
                          onClick={() => handleConvertProforma(pro)}
                          className={`${styles.paymentBtn} ${styles.actionIconBtn}`}
                          title="Confirmer le paiement"
                          aria-label="Confirmer le paiement"
                        >
                          <Check size={16} />
                        </button>
                        <button
                          onClick={() => setPrintingEncaissement(pro)}
                          className={`${styles.printBtn} ${styles.actionIconBtn}`}
                          title="Imprimer la pro forma de note de débit"
                          aria-label="Imprimer la pro forma de note de débit"
                        >
                          <Printer size={16} />
                        </button>
                        <button
                          onClick={() => handleCancelProforma(pro)}
                          className={`${styles.deleteBtn} ${styles.actionIconBtn}`}
                          title="Annuler la pro forma de note de débit"
                          aria-label="Annuler la pro forma de note de débit"
                        >
                          <Ban size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <EncaissementTable
        encaissements={filteredEncaissements}
        hasActiveFilters={!!hasActiveFilters}
        formatCurrency={formatCurrency}
        onManagePayment={setManagingPayment}
        onPrintReceipt={setPrintingEncaissement}
        onCancelOperation={handleCancelEncaissement}
        canCancelOperation={hasPermission('cancel_encaissement')}
      />

      {printingEncaissement && (
        <PrintReceipt
          encaissement={printingEncaissement}
          autoPrint={true}
          onClose={() => setPrintingEncaissement(null)}
        />
      )}

      {managingPayment && (
        <PaymentManager encaissement={managingPayment} onClose={() => setManagingPayment(null)} onUpdate={loadData} />
      )}

      {notification && (
        <NotificationModal
          type={notification.type}
          title={notification.title}
          message={notification.message}
          details={notification.details}
          onClose={() => setNotification(null)}
          autoClose={notification.type === 'success'}
        />
      )}
      </>
      )}
    </div>
  )
}
