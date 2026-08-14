import { useMemo, useState, useEffect, useCallback } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Printer, Undo2, Ban, Lock, Paperclip } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '../lib/apiClient'
import { getBudgetPostes } from '../api/budget'
import { getServices } from '../api/services'
import { getPrintSettings } from '../api/settings'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { useTreeBranchReveal } from '../hooks/useTreeBranchReveal'
import { toNumber } from '../utils/amount'
import { buildUploadUrl, openUploadUrl } from '../utils/uploads'
import { SortieFonds, ModePaiement, TypeSortieFonds, Service, Requisition, OrdreDecaissement } from '../types'
import { listOrdresDecaissement } from '../api/ordresDecaissement'
import { format } from 'date-fns'
import { downloadExcel } from '../utils/download'
import styles from './SortiesFonds.module.css'
import SortieFondsNotification from '../components/SortieFondsNotification'
import { CATEGORIES_SORTIE, getTypeSortieLabel, getBeneficiairePlaceholder, getMotifPlaceholder } from '../utils/sortieFondsHelpers'
import { generateSortieFondsPDF } from '../utils/pdfGeneratorSortie'
import { generateOrdreDirectPDF } from '../utils/pdfGeneratorOrdreDirect'
import { generateSortiesReportPDF } from '../utils/pdfGeneratorReports'
import { useToast } from '../hooks/useToast'
import { useConfirm, useConfirmWithInput } from '../contexts/ConfirmContext'
import { useTreasuryLock } from '../hooks/useTreasuryLock'
import PageHeader from '../components/PageHeader'
import CaisseSessionBanner from '../components/CaisseSessionBanner'
import RetourCaisseModal, { RetourSortieSource } from '../components/RetourCaisseModal'

export default function SortiesFonds() {
  const { user } = useAuth()
  // Antidater une opération de caisse revient à en réécrire la chronologie :
  // réservé au super administrateur, le serveur applique la même règle.
  const peutAntidater = (user?.role || '').toLowerCase() === 'super_admin'
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const { notifyError, notifySuccess, notifyWarning } = useToast()
  const confirm = useConfirm()
  const confirmWithInput = useConfirmWithInput()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const isCreatePage = location.pathname.endsWith('/nouvelle')
  const serviceParam = searchParams.get('service_id')
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [budgetLines, setBudgetPostes] = useState<any[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [showSuccessNotification, setShowSuccessNotification] = useState(false)
  const [lastCreatedSortie, setLastCreatedSortie] = useState<any>(null)
  const [retourModalSortie, setRetourModalSortie] = useState<RetourSortieSource | null>(null)
  const [printSettings, setPrintSettings] = useState<any | null>(null)
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(1)

  const today = useMemo(() => format(new Date(), 'yyyy-MM-dd'), [])
  // Par défaut, la liste couvre le mois en cours (du 1er au jour même) pour que
  // l'historique récent soit visible d'emblée.
  const startOfMonth = useMemo(() => {
    const d = new Date()
    return format(new Date(d.getFullYear(), d.getMonth(), 1), 'yyyy-MM-dd')
  }, [])
  const [dateDebut, setDateDebut] = useState(startOfMonth)
  const [dateFin, setDateFin] = useState(today)
  const [pendingDateDebut, setPendingDateDebut] = useState(startOfMonth)
  const [pendingDateFin, setPendingDateFin] = useState(today)

  const applyDateFilters = useCallback(() => {
    setDateDebut(pendingDateDebut)
    setDateFin(pendingDateFin)
    setPage(1)
  }, [pendingDateDebut, pendingDateFin])

  const hasPendingDateFilters = pendingDateDebut !== dateDebut || pendingDateFin !== dateFin
  
  const [filterType, setFilterType] = useState<string>('')
  const [filterModePaiement, setFilterModePaiement] = useState<string>('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterNumeroRequisition, setFilterNumeroRequisition] = useState('')
  const [budgetSearch, setBudgetSearch] = useState('')
  const [showBudgetDropdown, setShowBudgetDropdown] = useState(false)
  const [expandedBudgetIds, setExpandedBudgetIds] = useState<Set<number>>(() => new Set())
  const [rubriqueLocked, setRubriqueLocked] = useState(false)
  const [rubriqueLockMessage, setRubriqueLockMessage] = useState('')
  // Nombre de postes budgétaires distincts portés par la réquisition sélectionnée.
  // Au-delà de 1, l'imputation est répartie par le serveur au prorata des lignes :
  // la caisse n'a aucun poste à choisir.
  const [requisitionPostesCount, setRequisitionPostesCount] = useState(0)
  const [serviceLocked, setServiceLocked] = useState(false)
  const [serviceLockMessage, setServiceLockMessage] = useState('')
  const { isCaisseClosed: isCashClosed } = useTreasuryLock()
  const [comptesBancaires, setComptesBancaires] = useState<any[]>([])
  const [filteredComptes, setFilteredComptes] = useState<any[]>([])
  const [annexesModal, setAnnexesModal] = useState<
    null | { title: string; items: { label: string; url: string }[] }
  >(null)

  const [ordresAutorises, setOrdresAutorises] = useState<OrdreDecaissement[]>([])
  const [loadingOrdres, setLoadingOrdres] = useState(false)
  const [ordresDirects, setOrdresDirects] = useState<OrdreDecaissement[]>([])
  const [loadingOrdresDirects, setLoadingOrdresDirects] = useState(false)
  const [formData, setFormData] = useState({
    type_sortie: 'requisition' as TypeSortieFonds,
    requisition_id: '',
    ordre_decaissement_id: '',
    montant_paye: '',
    date_paiement: format(new Date(), 'yyyy-MM-dd'),
    mode_paiement: 'cash' as ModePaiement,
    reference: '',
    devise: 'USD',
    canal: 'CAISSE',
    compte_bancaire_id: '',
    commentaire: '',
    motif: '',
    rubrique_code: '',
    budget_poste_id: '',
    service_id: '',
    beneficiaire: '',
    piece_justificative: ''
  })
  const [justificatifFiles, setJustificatifFiles] = useState<File[]>([])

  const resolveSelectableCompteId = useCallback(
    (accounts: any[], canal: string, currentId: string) => {
      const current = accounts.find((compte) => String(compte.id) === String(currentId))
      if (current) return String(current.id)
      if (String(canal).toUpperCase() === 'CAISSE') {
        return accounts.length > 0 ? String(accounts[0].id) : ''
      }
      return accounts.length === 1 ? String(accounts[0].id) : ''
    },
    []
  )

  const userServiceIds = useMemo(() => {
    if (user?.service_ids && user.service_ids.length > 0) return user.service_ids
    if (user?.service_id) return [user.service_id]
    return []
  }, [user?.service_ids, user?.service_id])

  const isServiceUser = useMemo(() => {
    return userServiceIds.length > 0 && user?.role !== 'admin' && user?.role !== 'super_admin'
  }, [userServiceIds, user?.role])
  const defaultServiceId = useMemo(() => {
    if (serviceParam) return serviceParam
    if (isServiceUser && userServiceIds.length === 1) return String(userServiceIds[0])
    return ''
  }, [serviceParam, isServiceUser, userServiceIds])
  const isServiceLockedByContext = Boolean(serviceParam) || (isServiceUser && userServiceIds.length === 1)

  const openAnnexesModal = (items: { label: string; url: string }[], title: string) => {
    if (!items || items.length === 0) {
      notifyWarning('Justificatifs', 'Aucun justificatif trouvé pour cette sortie.')
      return
    }
    setAnnexesModal({ title, items })
  }

  const getAnnexesList = (sortie: any): string[] => {
    const annexes = sortie?.annexes
    if (Array.isArray(annexes)) {
      return annexes
    }
    if (typeof annexes === 'string' && annexes.trim()) {
      return [annexes]
    }
    return []
  }

  const openAnnexesForSortie = async (sortie: any) => {
    const annexes = getAnnexesList(sortie)
    if (annexes.length > 0) {
      const items = annexes.map((file) => {
        const name = file.split(/[\\/]/).pop() || file
        const normalized = file.startsWith('/uploads/')
          ? file
          : `/uploads/sorties-fonds/annexes/${name}`
        return {
          label: name,
          url: buildUploadUrl(normalized)
        }
      })
      openAnnexesModal(items, 'Justificatifs de la sortie')
      return
    }

    if (!sortie?.requisition_id) {
      notifyWarning('Justificatifs', 'Aucun justificatif trouvé pour cette sortie.')
      return
    }

    try {
      const annexesRes = await apiRequest<any[]>(
        'GET',
        `/requisitions/${sortie.requisition_id}/annexes`
      )
      const items = (annexesRes || []).map((annexe: any) => {
        const filePath = annexe?.file_path || annexe?.filename || 'annexe'
        const label = annexe?.filename || filePath
        const normalized = filePath.startsWith('/uploads/') ? filePath : `/uploads/${filePath}`
        return {
          label,
          url: buildUploadUrl(normalized)
        }
      })
      openAnnexesModal(items, 'Justificatifs de la réquisition')
    } catch (error) {
      console.error('Error loading requisition annexes:', error)
      notifyError('Erreur', 'Impossible de charger les justificatifs de la réquisition.')
    }
  }

  const sortiesFondsQueryKey = [
    'sorties-fonds',
    dateDebut,
    dateFin,
    filterType,
    filterModePaiement,
    filterStatut,
    filterNumeroRequisition,
    pageSize,
    page,
  ] as const

  const sortiesQuery = useQuery({
    queryKey: sortiesFondsQueryKey,
    queryFn: async () => {
      const [sortiesRes, reqRes, servicesRes] = await Promise.all([
        apiRequest<any>('GET', '/sorties-fonds', {
          params: {
            include: 'requisition',
            date_debut: dateDebut || undefined,
            date_fin: dateFin || undefined,
            type_sortie: filterType,
            mode_paiement: filterModePaiement,
            statut: filterStatut,
            requisition_numero: filterNumeroRequisition,
            order: 'created_at.desc',
            limit: pageSize,
            offset: (page - 1) * pageSize,
            include_summary: true,
          }
        }),
        apiRequest('GET', '/requisitions', {
          params: {
            status_in: 'APPROUVEE,EN_DECAISSEMENT',
            include: 'demandeur,validateur,approbateur,examinateur',
            limit: 300
          }
        }),
        getServices({ active: true }),
      ])

      const sortiesItems = (Array.isArray(sortiesRes) ? sortiesRes : (sortiesRes?.items ?? [])) as SortieFonds[]
      const totalCount = typeof sortiesRes?.total === 'number' ? sortiesRes.total : sortiesItems.length
      const totalMontantSorties = sortiesRes?.total_montant_paye !== undefined
        ? toNumber(sortiesRes.total_montant_paye ?? 0)
        : sortiesItems.reduce((sum, s) => sum + toNumber(s.montant_paye || 0), 0)

      const transfertTypes = ['versement_banque', 'approvisionnement_caisse']
      let totalDepensesReelles: number
      let totalTransfertsInternes: number
      if (sortiesRes?.total_depenses_reelles !== undefined) {
        totalDepensesReelles = toNumber(sortiesRes.total_depenses_reelles ?? 0)
        totalTransfertsInternes = toNumber(sortiesRes.total_transferts_internes ?? 0)
      } else {
        totalTransfertsInternes = sortiesItems
          .filter((s) => transfertTypes.includes(String((s as any).type_sortie)))
          .reduce((sum, s) => sum + toNumber(s.montant_paye || 0), 0)
        totalDepensesReelles = sortiesItems
          .filter((s) => !transfertTypes.includes(String((s as any).type_sortie)))
          .reduce((sum, s) => sum + toNumber(s.montant_paye || 0), 0)
      }

      const requisitionsItems = Array.isArray(reqRes) ? reqRes : (reqRes as any)?.items ?? []
      const allowedStatuses = new Set(['APPROUVEE', 'EN_DECAISSEMENT'])
      const cancelledRequisitionIds = new Set(
        (sortiesItems as any[])
          .filter((s) => String((s as any)?.statut || '').toUpperCase() === 'ANNULEE' && (s as any)?.requisition_id)
          .map((s) => String((s as any).requisition_id))
      )
      const requisitionsApprouvees = (requisitionsItems as any[]).filter((r) => {
        const statusValue = (r as any).status ?? (r as any).statut
        if (!statusValue || !allowedStatuses.has(String(statusValue))) return false
        // Les réquisitions à décaissement progressif restent payables tranche
        // par tranche, même si une sortie liée a été annulée.
        if ((r as any).decaissement_progressif) return true
        const reqId = (r as any)?.id ? String((r as any).id) : ''
        return reqId ? !cancelledRequisitionIds.has(reqId) : true
      }) as Requisition[]

      // Retours en caisse : ils viennent en diminution de la dépense. L'API les
      // expose à part pour que l'écran affiche brut / retours / net et se
      // rapproche de l'export Excel, dont le total est net.
      const totalRetoursCaisse = toNumber(sortiesRes?.total_retours_caisse ?? 0)
      const totalDepensesNettes = sortiesRes?.total_depenses_nettes !== undefined
        ? toNumber(sortiesRes.total_depenses_nettes ?? 0)
        : totalDepensesReelles - totalRetoursCaisse

      return {
        sorties: sortiesItems,
        requisitionsApprouvees,
        services: (Array.isArray(servicesRes) ? servicesRes : []) as Service[],
        totalCount,
        totalMontantSorties,
        totalDepensesReelles,
        totalTransfertsInternes,
        totalRetoursCaisse,
        totalDepensesNettes,
      }
    },
  })

  const sorties = sortiesQuery.data?.sorties ?? []
  const requisitionsApprouvees = sortiesQuery.data?.requisitionsApprouvees ?? []
  const services = sortiesQuery.data?.services ?? []
  const loading = sortiesQuery.isFetching
  const totalCount = sortiesQuery.data?.totalCount ?? 0
  const totalMontantSorties = sortiesQuery.data?.totalMontantSorties ?? 0
  const totalDepensesReelles = sortiesQuery.data?.totalDepensesReelles ?? 0
  const totalTransfertsInternes = sortiesQuery.data?.totalTransfertsInternes ?? 0
  const totalRetoursCaisse = sortiesQuery.data?.totalRetoursCaisse ?? 0
  const totalDepensesNettes = sortiesQuery.data?.totalDepensesNettes ?? 0

  const invalidateSortiesFonds = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['sorties-fonds'] })
  }, [queryClient])

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

  // Réglages « workflow budgétaire » : ils décident si un dépassement est
  // bloquant et pour qui (cf. _can_force_budget_overrun côté API).
  useEffect(() => {
    getPrintSettings()
      .then(setPrintSettings)
      .catch(() => setPrintSettings(null))
  }, [])

  const canForceBudgetOverrun = useMemo(() => {
    if (!printSettings) return false
    if (!printSettings.budget_block_overrun) return true
    const roles = String(printSettings.budget_force_roles || '')
      .split(',')
      .map((r) => r.trim().toLowerCase())
      .filter(Boolean)
    return Boolean(user?.role) && roles.includes(String(user?.role).toLowerCase())
  }, [printSettings, user?.role])

  useEffect(() => {
    const devise = String(formData.devise || 'USD').toUpperCase()
    // Approvisionnement caisse : c'est le compte bancaire source qui impose la
    // devise (une même banque peut avoir un compte USD et un compte CDF), on ne
    // filtre donc pas la liste sur la devise du formulaire.
    const filtreDevise = formData.type_sortie === 'approvisionnement_caisse'
      ? () => true
      : (compte: any) => String(compte.devise || '').toUpperCase() === devise
    const banqueComptes = comptesBancaires.filter(
      (compte) =>
        filtreDevise(compte) &&
        String(compte.account_type || 'BANK').toUpperCase() === 'BANK'
    )
    const caisseComptes = comptesBancaires.filter(
      (compte) =>
        filtreDevise(compte) &&
        String(compte.account_type || 'BANK').toUpperCase() === 'CASH'
    )
    // Versement à la banque : la caisse est la source, le compte sélectionné
    // est la banque de destination (type BANK).
    const wantBanque = formData.canal === 'BANQUE' || formData.type_sortie === 'versement_banque'
    const next = wantBanque ? banqueComptes : caisseComptes
    setFilteredComptes(next)
    const canalForPick = formData.type_sortie === 'versement_banque' ? 'BANQUE' : formData.canal
    const nextCompteId = resolveSelectableCompteId(next, canalForPick, formData.compte_bancaire_id)
    if (String(nextCompteId) !== String(formData.compte_bancaire_id || '')) {
      setFormData((prev) => ({
        ...prev,
        compte_bancaire_id: nextCompteId,
      }))
    }
  }, [formData.devise, formData.canal, formData.type_sortie, formData.compte_bancaire_id, comptesBancaires, resolveSelectableCompteId])

  // Approvisionnement caisse : la devise de la sortie suit celle du compte
  // bancaire source retenu (retrait d'espèces sur ce compte précis).
  useEffect(() => {
    if (formData.type_sortie !== 'approvisionnement_caisse') return
    if (!formData.compte_bancaire_id) return
    const compte = comptesBancaires.find(
      (c) => String(c.id) === String(formData.compte_bancaire_id)
    )
    const deviseCompte = String(compte?.devise || '').toUpperCase()
    if (deviseCompte && deviseCompte !== String(formData.devise || '').toUpperCase()) {
      setFormData((prev) => ({ ...prev, devise: deviseCompte }))
    }
  }, [formData.type_sortie, formData.compte_bancaire_id, formData.devise, comptesBancaires])

  useEffect(() => {
    // Les transferts caisse/banque restent en espèces : ne pas basculer.
    if (
      isCashClosed &&
      formData.mode_paiement === 'cash' &&
      formData.type_sortie !== 'versement_banque' &&
      formData.type_sortie !== 'approvisionnement_caisse'
    ) {
      setFormData((prev) => ({ ...prev, mode_paiement: 'virement' }))
    }
  }, [isCashClosed, formData.mode_paiement, formData.type_sortie])

  const loadBudgetLines = useCallback(async (serviceId: number | null) => {
    if (isServiceUser && !serviceId) {
      setBudgetPostes([])
      return
    }
    if (isServiceUser || serviceId) {
      const res = await apiRequest<any>('GET', '/budget/lines/autorisees', {
        params: {
          type: 'DEPENSE',
          active: true,
          service_id: serviceId ?? undefined,
        },
      })
      setBudgetPostes(res?.lignes ?? [])
      return
    }
    const budgetRes = await getBudgetPostes({ type: 'DEPENSE', active: true })
    setBudgetPostes(budgetRes?.postes ?? [])
  }, [isServiceUser])

  useEffect(() => {
    if (defaultServiceId && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: defaultServiceId }))
    }
  }, [defaultServiceId, formData.service_id])

  useEffect(() => {
    if (serviceParam && formData.service_id !== serviceParam) {
      setFormData((prev) => ({ ...prev, service_id: serviceParam }))
    }
  }, [serviceParam, formData.service_id])

  useEffect(() => {
    const resolvedServiceId = formData.service_id ? Number(formData.service_id) : null
    const serviceIdForBudget = isServiceUser
      ? resolvedServiceId ?? (userServiceIds.length === 1 ? userServiceIds[0] : null)
      : resolvedServiceId
    loadBudgetLines(serviceIdForBudget)
    setFormData((prev) => (prev.budget_poste_id ? { ...prev, budget_poste_id: '' } : prev))
    setBudgetSearch((prev) => (prev ? '' : prev))
  }, [formData.service_id, isServiceUser, userServiceIds, loadBudgetLines])

  useEffect(() => {
    setPage(1)
  }, [dateDebut, dateFin, filterType, filterModePaiement, filterStatut, filterNumeroRequisition, pageSize])

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(page, totalPages)

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const sortiesList = Array.isArray(sorties) ? sorties : []
  const requisitionsApprouveesList = Array.isArray(requisitionsApprouvees) ? requisitionsApprouvees : []
  const requisitionsClassiques = requisitionsApprouveesList.filter(
    (req) => req?.type_requisition !== 'remboursement_transport'
  )
  const requisitionsRemboursement = requisitionsApprouveesList.filter(
    (req) => req?.type_requisition === 'remboursement_transport'
  )
  const requiresApprovedRequisition =
    formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement'
  const approvedRequisitionsForType =
    formData.type_sortie === 'remboursement' ? requisitionsRemboursement : requisitionsClassiques
  const noApprovedRequisitionAvailable =
    requiresApprovedRequisition && approvedRequisitionsForType.length === 0
  const budgetLinesList = Array.isArray(budgetLines) ? budgetLines : []
  const servicesList = Array.isArray(services) ? services : []
  const serviceLabel = useMemo(() => {
    if (!formData.service_id) return ''
    const serviceId = Number(formData.service_id)
    if (!Number.isFinite(serviceId)) return ''
    const service = servicesList.find((s) => s.id === serviceId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${serviceId}`
  }, [formData.service_id, servicesList])
  const selectedRequisition = useMemo(() => {
    if (!formData.requisition_id) return null
    return requisitionsApprouveesList.find((req) => String(req.id) === String(formData.requisition_id)) || null
  }, [formData.requisition_id, requisitionsApprouveesList])
  const resetSortieForm = useCallback(() => {
    setOrdresAutorises([])
    setRequisitionPostesCount(0)
    setRubriqueLocked(false)
    setRubriqueLockMessage('')
    setServiceLocked(false)
    setServiceLockMessage('')
    setBudgetSearch('')
    setFormData({
      type_sortie: 'requisition',
      requisition_id: '',
      ordre_decaissement_id: '',
      montant_paye: '',
      date_paiement: format(new Date(), 'yyyy-MM-dd'),
      mode_paiement: 'cash',
      reference: '',
      devise: 'USD',
      canal: 'CAISSE',
      compte_bancaire_id: '',
      commentaire: '',
      motif: '',
      rubrique_code: '',
      budget_poste_id: '',
      service_id: defaultServiceId,
      beneficiaire: '',
      piece_justificative: ''
    })
    setJustificatifFiles([])
  }, [defaultServiceId])
  const closeCreationForm = useCallback(() => {
    setShowForm(false)
    setJustificatifFiles([])
    if (isCreatePage) {
      navigate('/sorties-fonds')
    }
  }, [isCreatePage, navigate])
  const isRequisitionBound =
    (formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement') &&
    !!formData.requisition_id
  const isProgressif = !!(selectedRequisition as any)?.decaissement_progressif
  const approvedAmount = selectedRequisition ? toNumber((selectedRequisition as any).montant_total) : 0
  const alreadyPaidAmount = useMemo(() => {
    if (!selectedRequisition) return 0
    const explicit =
      (selectedRequisition as any).montant_deja_paye ??
      (selectedRequisition as any).montant_paye ??
      (selectedRequisition as any).montant_paye_total
    if (explicit !== undefined && explicit !== null) return toNumber(explicit)
    return sortiesList
      .filter((sortie: any) =>
        String(sortie.requisition_id || sortie.requisition?.id || '') === String(selectedRequisition.id) &&
        String(sortie.statut || '').toUpperCase() !== 'ANNULEE'
      )
      .reduce((sum: number, sortie: any) => sum + toNumber(sortie.montant_paye), 0)
  }, [selectedRequisition, sortiesList])
  const currentPaymentAmount = toNumber(formData.montant_paye)
  const remainingBeforePayment = Math.max(0, approvedAmount - alreadyPaidAmount)
  const remainingAfterPayment = Math.max(0, remainingBeforePayment - currentPaymentAmount)
  const amountExceedsRemaining =
    Boolean(selectedRequisition && currentPaymentAmount > 0) &&
    currentPaymentAmount > remainingBeforePayment
  const loadOrdresAutorises = useCallback(async (reqId: string) => {
    if (!reqId) {
      setOrdresAutorises([])
      return
    }
    setLoadingOrdres(true)
    try {
      const res = await listOrdresDecaissement({ requisition_id: reqId, statut: 'AUTORISE', limit: 200 })
      setOrdresAutorises(res.items || [])
    } catch (err) {
      console.error('Error loading ordres de décaissement:', err)
      setOrdresAutorises([])
    } finally {
      setLoadingOrdres(false)
    }
  }, [])
  const loadOrdresDirects = useCallback(async () => {
    setLoadingOrdresDirects(true)
    try {
      // Uniquement les vraies sorties directes (sans réquisition) : les tranches
      // de réquisitions progressives se paient par le chemin « réquisition ».
      const res = await listOrdresDecaissement({ sans_requisition: true, statut: 'AUTORISE', limit: 200 })
      setOrdresDirects(res.items || [])
    } catch (err) {
      console.error('Error loading ordres de sortie directe:', err)
      setOrdresDirects([])
    } finally {
      setLoadingOrdresDirects(false)
    }
  }, [])
  const isSortieDirecte = formData.type_sortie === 'sortie_directe'
  // Versement à la banque : simple transfert caisse -> banque, sans service,
  // sans bénéficiaire externe et sans imputation budgétaire.
  const isVersementBanque = formData.type_sortie === 'versement_banque'
  // Approvisionnement caisse : transfert inverse banque -> caisse (retrait
  // d'espèces pour alimenter la caisse).
  const isApproCaisse = formData.type_sortie === 'approvisionnement_caisse'
  const isTransfertInterne = isVersementBanque || isApproCaisse
  const showCompteSourceSelector = formData.canal === 'BANQUE' || isVersementBanque
  const showCaisseDebitInfo = formData.canal === 'CAISSE' && !isVersementBanque
  // Poste(s) budgétaire(s) définis EN AMONT par la source (réquisition / ordre de
  // décaissement). La caissière exécute : elle n'a pas à (re)saisir le poste.
  const selectedOrdre = useMemo(() => {
    const oid = formData.ordre_decaissement_id
    if (!oid) return null
    return (
      ordresDirects.find((o) => String(o.id) === String(oid)) ||
      ordresAutorises.find((o) => String(o.id) === String(oid)) ||
      null
    )
  }, [formData.ordre_decaissement_id, ordresDirects, ordresAutorises])
  const ordrePostes = useMemo(() => {
    const lignes = Array.isArray((selectedOrdre as any)?.lignes) ? (selectedOrdre as any).lignes : []
    const map = new Map<number, number>()
    for (const l of lignes) {
      const pid = Number(l?.budget_poste_id)
      if (!Number.isFinite(pid)) continue
      map.set(pid, (map.get(pid) || 0) + toNumber(l?.montant ?? l?.montant_total))
    }
    return Array.from(map.entries()).map(([id, montant]) => ({ id, montant }))
  }, [selectedOrdre])
  const posteSourceMulti = ordrePostes.length > 1 || requisitionPostesCount > 1
  // La sortie est liée à une source (réquisition ou ordre) : le(s) poste(s) sont
  // définis en amont, la caissière ne les ressaisit jamais.
  const hasSourceBinding =
    isRequisitionBound || isProgressif || (isSortieDirecte && !!formData.ordre_decaissement_id)
  // Poste unique connu : verrouillé par la réquisition (budget_poste_id) OU porté
  // par l'unique ligne de l'ordre (tranche progressive ne visant qu'un poste).
  const posteSourceMono =
    !posteSourceMulti && hasSourceBinding && (!!formData.budget_poste_id || ordrePostes.length === 1)
  const posteDefiniParSource = posteSourceMono || posteSourceMulti
  // Poste unique retenu pour l'affichage / l'envoi (soit celui verrouillé, soit
  // celui de l'ordre mono-poste).
  const posteMonoId = formData.budget_poste_id
    ? Number(formData.budget_poste_id)
    : ordrePostes.length === 1
      ? ordrePostes[0].id
      : null
  useEffect(() => {
    if (isSortieDirecte) loadOrdresDirects()
  }, [isSortieDirecte, loadOrdresDirects])
  // Impression du bon de sortie directe depuis la caisse (avant paiement).
  const handlePrintOrdreDirect = useCallback(async () => {
    const ordre = ordresDirects.find((o) => String(o.id) === String(formData.ordre_decaissement_id))
    if (!ordre) return
    try {
      const ordreServiceId = Number((ordre as any).service_id)
      const service = Number.isFinite(ordreServiceId)
        ? services.find((s: any) => s.id === ordreServiceId)
        : undefined
      const posteLabels = new Map<number, string>()
      ;(Array.isArray(budgetLines) ? budgetLines : []).forEach((line: any) => {
        posteLabels.set(Number(line.id), `${line.code} - ${line.libelle}`)
      })
      await generateOrdreDirectPDF(ordre, {
        serviceLabel: service ? `${(service as any).code} — ${(service as any).libelle}` : undefined,
        posteLabels,
      })
    } catch (err: any) {
      notifyError('Erreur', err?.message || 'Impossible de générer le bon de sortie directe.')
    }
  }, [ordresDirects, formData.ordre_decaissement_id, services, budgetLines, notifyError])
  // Sortie directe programmée : le poste budgétaire défini à la programmation
  // est repris et verrouillé (comme une réquisition mono-poste). Cet effet se
  // ré-applique après le nettoyage automatique déclenché par le changement de
  // service.
  useEffect(() => {
    if (!isSortieDirecte || !formData.ordre_decaissement_id) return
    const ordre = ordresDirects.find((o) => String(o.id) === String(formData.ordre_decaissement_id))
    if (!ordre) return
    const lignesOrdre = Array.isArray((ordre as any).lignes) ? (ordre as any).lignes : []
    const ids = Array.from(
      new Set(
        lignesOrdre
          .map((l: any) => Number(l?.budget_poste_id))
          .filter((v: any) => Number.isFinite(v))
      )
    )
    if (ids.length === 1) {
      const budgetId = String(ids[0])
      if (String(formData.budget_poste_id) !== budgetId) {
        setFormData((prev) => ({ ...prev, budget_poste_id: budgetId }))
      }
      const selected = (Array.isArray(budgetLines) ? budgetLines : []).find(
        (b: any) => String(b.id) === budgetId
      )
      setBudgetSearch(selected ? `${selected.code} - ${selected.libelle}` : '')
      setRubriqueLocked(true)
      setRubriqueLockMessage('Poste budgétaire verrouillé par la sortie directe programmée')
    } else if (ids.length > 1) {
      setRubriqueLocked(false)
      setRubriqueLockMessage('Sortie programmée multi-postes : sélection manuelle requise')
    } else {
      setRubriqueLocked(false)
      setRubriqueLockMessage('Poste budgétaire non défini à la programmation : sélection manuelle requise')
    }
  }, [
    isSortieDirecte,
    formData.ordre_decaissement_id,
    formData.budget_poste_id,
    ordresDirects,
    budgetLines,
  ])
  const isServiceLockedByRequisition = isRequisitionBound && !!selectedRequisition?.service_id

  const isPaymentRejectable = useCallback((req: Requisition | null | undefined) => {
    if (!req) return false
    const statusValue = String(req.status ?? req.statut ?? '').toUpperCase()
    return statusValue === 'APPROUVEE' && !req.payee_par && !req.payee_le
  }, [])

  const getPaymentDocumentLabel = useCallback((req: Requisition | null | undefined) => {
    if (!req) return 'ce dossier'
    return String(req.type_requisition || '').toLowerCase() === 'remboursement_transport'
      ? 'ce remboursement transport'
      : 'cette réquisition'
  }, [])
  const budgetTree = useMemo(() => {
    const nodes = new Map<number, any>()
    const roots: any[] = []

    budgetLinesList.forEach((line: any) => {
      nodes.set(line.id, { ...line, children: [] })
    })

    budgetLinesList.forEach((line: any) => {
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
  }, [budgetLinesList])

  const filteredBudgetTree = useMemo(() => {
    const query = budgetSearch.trim().toLowerCase()
    if (!query) return budgetTree

    const matches = (node: any) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      return code.includes(query) || libelle.includes(query)
    }

    const filterNodes = (nodes: any[]): any[] => {
      return nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean)
    }

    return filterNodes(budgetTree)
  }, [budgetTree, budgetSearch])

  const selectBudgetPoste = (line: any) => {
    if ((line.children?.length || 0) > 0 || rubriqueLocked) return
    setFormData({ ...formData, budget_poste_id: String(line.id) })
    setBudgetSearch(`${line.code} - ${line.libelle}`)
    setShowBudgetDropdown(false)
  }

  const revealBudgetBranch = useTreeBranchReveal()

  const toggleBudgetNode = (id: number, row?: HTMLElement | null) => {
    setExpandedBudgetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
    // Recentrage seulement à l'ouverture : replier n'a rien à montrer.
    if (!expandedBudgetIds.has(id)) revealBudgetBranch(row ?? null)
  }

  const forceExpandBudgetTree = budgetSearch.trim().length > 0

  const BudgetDropdownNode = ({
    node,
    depth,
    expandedIds,
    onToggle,
    onSelect,
  }: {
    node: any
    depth: number
    expandedIds: Set<number>
    onToggle: (id: number, row?: HTMLElement | null) => void
    onSelect: (line: any) => void
  }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = forceExpandBudgetTree || expandedIds.has(node.id)
    return (
      <>
        <div
          className={`${styles.dropdownItem} ${hasChildren ? styles.parentItem : ''}`}
          style={{ paddingLeft: `${10 + depth * 16}px` }}
          data-tree-node={hasChildren ? node.id : undefined}
          onClick={(event) => {
            if (hasChildren) {
              onToggle(node.id, event.currentTarget)
            } else {
              onSelect(node)
            }
          }}
        >
          {hasChildren && (
            <span className={`${styles.treeToggle} ${isExpanded ? styles.treeToggleOpen : ''}`} />
          )}
          <strong>{node.code}</strong> - {node.libelle}
          {hasChildren && <span className={styles.parentBadge}>Parent</span>}
        </div>
        {hasChildren && isExpanded && (
          <div className={styles.treeBranch} data-tree-branch={node.id}>
            {node.children.map((child: any) => (
              <BudgetDropdownNode
                key={child.id}
                node={child}
                depth={depth + 1}
                expandedIds={expandedIds}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </>
    )
  }
  const canUpdateStatut = hasPermission('cancel_sortie_fonds')
  // Un retour en caisse n'a de sens que sur une vraie dépense valide (pas un
  // transfert interne). La permission de paiement est vérifiée côté backend.
  const canRetournerCaisse = (sortie: SortieFonds): boolean => {
    const statut = String((sortie as any)?.statut || 'VALIDE').toUpperCase()
    const type = String((sortie as any)?.type_sortie || '').toLowerCase()
    return (
      hasPermission('sorties_fonds') &&
      statut === 'VALIDE' &&
      type !== 'versement_banque' &&
      type !== 'approvisionnement_caisse'
    )
  }

  const budgetLineMap = useMemo(() => {
    return new Map(budgetLinesList.map((line: any) => [String(line.id), line]))
  }, [budgetLinesList])

  // Libellé du poste pour le bon de sortie. Une sortie multi-postes n'a ni
  // budget_poste_id ni budget_poste_code (l'imputation est répartie) : seul
  // budget_poste_libelle est renseigné, avec « Réparti sur N postes ». Il faut donc
  // accepter le libellé seul, sans exiger le code.
  const formatBudgetLabel = useCallback((sortie: any): string => {
    if (!sortie) return ''
    const code = sortie.budget_poste_code
    const libelle = sortie.budget_poste_libelle
    if (code && libelle) return `${code} - ${libelle}`
    if (libelle) return libelle
    if (sortie.budget_poste_id) {
      const line = budgetLineMap.get(String(sortie.budget_poste_id))
      if (line) return `${line.code} - ${line.libelle}`
    }
    return sortie.rubrique_code || ''
  }, [budgetLineMap])

  const handlePrintBonCaisse = async (sortie: SortieFonds, opts: { silent?: boolean } = {}) => {
    const budgetLabel = formatBudgetLabel(sortie)
    const reqDetails = sortie?.requisition_id
      ? requisitionsApprouveesList.find((r: any) => String(r.id) === String(sortie.requisition_id))
      : null
    if (sortie?.requisition_id) {
      const statusValue = String(reqDetails?.status ?? reqDetails?.statut ?? sortie?.requisition?.status ?? sortie?.requisition?.statut ?? '')
      const normalized = statusValue.toUpperCase()
      if (normalized && normalized !== 'APPROUVEE' && normalized !== 'PAYEE') {
        if (!opts.silent) notifyWarning('Validation requise', 'La réquisition doit être approuvée (2/2) avant impression du bon.')
        return
      }
    }
    const mergedSortie = reqDetails
      ? { ...sortie, requisition: { ...(sortie as any).requisition, ...reqDetails } }
      : sortie
    const ref = mergedSortie?.reference_numero || mergedSortie?.reference || mergedSortie?.id || 'N/A'
    try {
      // Cumul des retours de cette sortie, pour l'imprimer sur le bon d'origine.
      let retourInfo: { totalRetourne: number; resteAJustifier: number } | undefined
      try {
        const summary = await apiRequest<any>('GET', '/retours-caisse', {
          params: { sortie_fonds_id: mergedSortie.id, include_summary: true, limit: 1 },
        })
        const tr = toNumber(summary?.total_retourne || 0)
        if (tr > 0) {
          const rj =
            summary?.reste_a_justifier != null
              ? toNumber(summary.reste_a_justifier)
              : Math.max(0, toNumber(mergedSortie?.montant_paye || 0) - tr)
          retourInfo = { totalRetourne: tr, resteAJustifier: rj }
        }
      } catch {
        /* pas de bloc retour si le résumé est indisponible */
      }
      const pdfBlob = await generateSortieFondsPDF(mergedSortie, budgetLabel, 'blob', retourInfo)
      if (pdfBlob) {
        const formData = new FormData()
        formData.append(
          'file',
          new File([pdfBlob], `Bon_Caisse_${String(ref).slice(0, 16)}.pdf`, { type: 'application/pdf' })
        )
        apiRequest('POST', `/sorties-fonds/${mergedSortie.id}/pdf`, {
          params: { notify: false },
          body: formData,
        }).catch(() => {
          notifyWarning('Archivage incomplet', 'Le bon de caisse a été généré, mais son archivage a échoué.')
        })

        if (!opts.silent) {
          const url = URL.createObjectURL(pdfBlob)
          const link = document.createElement('a')
          link.href = url
          link.download = `Sortie_Fonds_${String(ref).slice(0, 16)}.pdf`
          document.body.appendChild(link)
          link.click()
          link.remove()
          URL.revokeObjectURL(url)
        }
        return
      }
      if (!opts.silent) await generateSortieFondsPDF(mergedSortie, budgetLabel)
    } catch (error: any) {
      console.error('Erreur génération bon de caisse:', error)
      notifyError('Erreur', error?.message || "Impossible de générer le bon de caisse.")
    }
  }

  const updateSortieStatut = async (sortie: SortieFonds, statut: 'VALIDE' | 'ANNULEE') => {
    try {
      let motif_annulation: string | undefined
      if (statut === 'ANNULEE') {
        const alreadyCancelled = String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE'
        if (alreadyCancelled && !canEditAnnulationMotif(sortie)) {
          notifyWarning('Motif verrouillé', 'Le motif d’annulation n’est plus modifiable après 5 minutes.')
          return
        }
        const existingMotif = (sortie as any).motif_annulation || ''
        const result = await confirmWithInput({
          title: 'Annuler cette sortie ?',
          description: existingMotif
            ? `Motif actuel : ${existingMotif}`
            : 'Cette action sera visible sur le QR de vérification.',
          confirmText: 'Annuler',
          variant: 'danger',
          inputLabel: 'Motif (obligatoire)',
          inputPlaceholder: 'Ex: Paiement saisi en double',
          inputRequired: true,
          inputMultiline: true,
          inputRows: 3,
          inputInitialValue: existingMotif,
        })
        if (!result.confirmed) return
        if (!result.value) {
          notifyWarning('Motif requis', 'Veuillez saisir un motif d’annulation/remboursement.')
          return
        }
        motif_annulation = result.value
      }

      await apiRequest('PATCH', `/sorties-fonds/${sortie.id}/statut`, { statut, motif_annulation })
      invalidateSortiesFonds()
      notifySuccess(
        statut === 'VALIDE' ? 'Sortie validée' : 'Sortie annulée',
        statut === 'VALIDE'
          ? 'La sortie de fonds est maintenant valide.'
          : 'La sortie de fonds est maintenant annulée.'
      )
    } catch (error: any) {
      console.error('Erreur mise à jour statut sortie:', error)
      notifyError('Erreur', error?.payload?.detail || "Impossible de mettre à jour le statut.")
    }
  }

  const rejectAtPayment = async (req: Requisition | null) => {
    if (!req) return
    if (!isPaymentRejectable(req)) {
      notifyWarning('Rejet impossible', "Seuls les dossiers approuvés et non payés peuvent être rejetés à la sortie de fonds.")
      return
    }

    const result = await confirmWithInput({
      title: `Rejeter ${getPaymentDocumentLabel(req)} ?`,
      description: 'Le motif de rejet sera conservé dans le dossier et visible dans le workflow.',
      confirmText: 'Rejeter',
      variant: 'danger',
      inputLabel: 'Motif de rejet (obligatoire)',
      inputPlaceholder: 'Ex: pièces insuffisantes pour exécuter le paiement',
      inputRequired: true,
      inputMultiline: true,
      inputRows: 3,
      inputInitialValue: req.motif_rejet || '',
    })
    if (!result.confirmed) return
    if (!result.value?.trim()) {
      notifyWarning('Motif requis', 'Veuillez saisir un motif de rejet.')
      return
    }

    try {
      await apiRequest('POST', `/sorties-fonds/requisitions/${req.id}/reject`, {
        motif_rejet: result.value.trim(),
      })

      if (String(formData.requisition_id) === String(req.id)) {
        setFormData((prev) => ({
          ...prev,
          requisition_id: '',
          ordre_decaissement_id: '',
          montant_paye: '',
          mode_paiement: 'cash',
          motif: '',
          beneficiaire: '',
          rubrique_code: '',
          budget_poste_id: '',
          commentaire: '',
          piece_justificative: '',
          service_id: isServiceLockedByContext ? defaultServiceId : '',
        }))
        setRubriqueLocked(false)
        setRubriqueLockMessage('')
        setServiceLocked(false)
        setServiceLockMessage('')
      }

      notifySuccess(
        'Dossier rejeté',
        `${String(req.type_requisition || '').toLowerCase() === 'remboursement_transport' ? 'Le remboursement transport' : 'La réquisition'} a été rejeté${String(req.type_requisition || '').toLowerCase() === 'remboursement_transport' ? '' : 'e'} à l’étape de sortie de fonds.`
      )
      invalidateSortiesFonds()
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || "Impossible de rejeter ce dossier.")
    }
  }

  const renderStatutBadge = (statutValue?: string, motif?: string | null) => {
    const statut = (statutValue || 'VALIDE').toUpperCase()
    if (statut === 'ANNULEE') {
      return (
        <span
          className={`${styles.statusBadge} ${styles.statusCancelled}`}
          title={motif ? `Motif : ${motif}` : undefined}
        >
          Annulée
        </span>
      )
    }
    if (statut === 'REMBOURSEE') {
      return (
        <span
          className={`${styles.statusBadge} ${styles.statusRefunded}`}
          title={motif ? `Motif : ${motif}` : undefined}
        >
          Remboursée
        </span>
      )
    }
    if (statut === 'BROUILLON') {
      return <span className={`${styles.statusBadge} ${styles.statusPending}`}>Brouillon</span>
    }
    return <span className={`${styles.statusBadge} ${styles.statusValid}`}>Validée</span>
  }

  const applyRequisitionRubrique = async (reqId: string) => {
    if (!reqId) {
      setRubriqueLocked(false)
      setRubriqueLockMessage('')
      setRequisitionPostesCount(0)
      return
    }
    setRubriqueLocked(true)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: reqId } })
      const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      const ids = Array.from(
        new Set(lignes.map((l: any) => Number(l.budget_poste_id)).filter((v: any) => Number.isFinite(v)))
      )
      setRequisitionPostesCount(ids.length)
      if (ids.length === 1) {
        const budgetId = String(ids[0])
        setFormData((prev) => ({ ...prev, budget_poste_id: budgetId }))
        const selected = budgetLinesList.find((b: any) => String(b.id) === budgetId)
        if (selected) {
          setBudgetSearch(`${selected.code} - ${selected.libelle}`)
        } else {
          setBudgetSearch('')
        }
        setRubriqueLocked(true)
        setRubriqueLockMessage('Poste budgétaire verrouillé par la source')
      } else if (ids.length > 1) {
        // Les postes viennent de la réquisition : le serveur répartit le montant payé
        // au prorata des lignes. Rien à saisir ici.
        setFormData((prev) => ({ ...prev, budget_poste_id: '' }))
        setBudgetSearch('')
        setRubriqueLocked(true)
        setRubriqueLockMessage(`Réparti sur ${ids.length} postes définis par la réquisition`)
      } else {
        setFormData((prev) => ({ ...prev, budget_poste_id: '' }))
        setBudgetSearch('')
        setRubriqueLocked(false)
        setRubriqueLockMessage('Poste budgétaire non défini: sélection manuelle requise')
      }
    } catch (error) {
      console.error('Error loading lignes requisition:', error)
      setRequisitionPostesCount(0)
      setRubriqueLocked(false)
      setRubriqueLockMessage('Impossible de charger le poste budgétaire lié')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (submitting) return

    if (!formData.montant_paye) {
      notifyWarning('Montant requis', 'Veuillez saisir le montant.')
      return
    }

    if (amountExceedsRemaining) {
      notifyWarning(
        'Montant supérieur au solde',
        `Reste à payer: ${formatCurrency(remainingBeforePayment)} · Saisi: ${formatCurrency(formData.montant_paye)}`
      )
      return
    }

    if ((formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement') && !formData.requisition_id) {
      notifyWarning('Réquisition requise', 'Veuillez sélectionner une réquisition approuvée.')
      return
    }

    if (isProgressif && !formData.ordre_decaissement_id) {
      notifyWarning(
        'Ordre de décaissement requis',
        'Cette réquisition est à décaissement progressif : sélectionnez un ordre autorisé par le demandeur.'
      )
      return
    }

    if (!isTransfertInterne && !formData.service_id) {
      notifyWarning('Service requis', 'Veuillez sélectionner un service / commission.')
      return
    }

    if (formData.type_sortie === 'sortie_directe' && !formData.ordre_decaissement_id) {
      notifyWarning(
        'Ordre requis',
        'La caisse exécute uniquement une sortie directe programmée par un utilisateur habilité.'
      )
      return
    }

    if (
      formData.type_sortie === 'sortie_directe' &&
      (formData.devise || 'USD').toUpperCase() === 'USD' &&
      parseFloat(formData.montant_paye) > 100
    ) {
      notifyWarning(
        'Montant maximum dépassé',
        'Les sorties directes sont limitées à 100 $. Pour les montants supérieurs, créez une réquisition.'
      )
      return
    }

    if (!formData.motif.trim()) {
      notifyWarning('Motif requis', 'Le motif est obligatoire pour toutes les sorties.')
      return
    }

    if (!isTransfertInterne && !formData.beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Le bénéficiaire est obligatoire pour toutes les sorties.')
      return
    }

    // Le poste n'est jamais ressaisi quand il est défini par la source (réquisition
    // / ordre) : la caissière exécute. On ne l'exige que pour une sortie libre.
    if (!isTransfertInterne && !posteDefiniParSource && !formData.budget_poste_id) {
      notifyWarning('Poste requis', 'Le poste budgétaire est obligatoire.')
      return
    }

    const selectedBudget = isTransfertInterne
      ? null
      : budgetLinesList.find((b: any) => String(b.id) === String(formData.budget_poste_id))
    if (selectedBudget) {
      const plafond = toNumber(selectedBudget.montant_prevu)
      const dejaPaye = toNumber(selectedBudget.montant_paye)
      const reste = plafond - dejaPaye
      if (parseFloat(formData.montant_paye) > reste) {
        // Le dépassement n'est bloquant que si les réglages l'exigent : sinon
        // on avertit et on laisse l'opérateur confirmer (l'API tranche aussi).
        if (!canForceBudgetOverrun) {
          notifyWarning(
            'Dépassement budgétaire',
            `Disponible: ${formatCurrency(reste)} · Demandé: ${formatCurrency(formData.montant_paye)}`
          )
          return
        }
        const confirmed = await confirm({
          title: 'Dépassement budgétaire',
          description: `Disponible: ${formatCurrency(reste)} · Demandé: ${formatCurrency(formData.montant_paye)}\n\nLe dépassement est autorisé par les réglages. Confirmer la sortie ?`,
          confirmText: 'Confirmer',
          cancelText: 'Annuler',
          variant: 'danger',
        })
        if (!confirmed) return
      }
    }

    if ((formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && !formData.reference) {
      notifyWarning('Référence requise', 'La référence est obligatoire pour Mobile Money ou Opération bancaire.')
      return
    }

    if (formData.canal === 'BANQUE' && !formData.compte_bancaire_id) {
      notifyWarning(
        isApproCaisse ? 'Banque source requise' : 'Compte bancaire requis',
        isApproCaisse
          ? 'Veuillez sélectionner la banque source du retrait.'
          : 'Veuillez sélectionner le compte bancaire à débiter.'
      )
      return
    }
    if (isVersementBanque && !formData.compte_bancaire_id) {
      notifyWarning('Banque requise', 'Veuillez sélectionner la banque de destination du versement.')
      return
    }

    setSubmitting(true)
    try {
      const selectedReq = (formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement')
        ? requisitionsApprouvees.find(r => String(r.id) === String(formData.requisition_id))
        : null
      const serviceId = isTransfertInterne ? null : Number(formData.service_id)
      if (!isTransfertInterne && !Number.isFinite(serviceId as number)) {
        notifyWarning('Service requis', 'Veuillez sélectionner un service / commission valide.')
        setSubmitting(false)
        return
      }

      // Versement banque : le « bénéficiaire » est la banque de destination.
      const compteDestination = isVersementBanque
        ? comptesBancaires.find((c) => String(c.id) === String(formData.compte_bancaire_id))
        : null
      // Appro caisse : on retire des espèces sur un compte précis, la devise de
      // la sortie est forcément celle de ce compte.
      const compteSourceAppro = isApproCaisse
        ? comptesBancaires.find((c) => String(c.id) === String(formData.compte_bancaire_id))
        : null
      const deviseFinale = (
        compteSourceAppro?.devise || formData.devise || 'USD'
      ).toUpperCase()
      const beneficiaireFinal = isVersementBanque
        ? `${compteDestination?.banque?.nom || 'Banque'} - ${compteDestination?.intitule || ''}`.trim()
        : isApproCaisse
          ? 'Caisse centrale'
          : formData.beneficiaire

      const sortieInsert: any = {
        type_sortie: formData.type_sortie,
        service_id: serviceId,
        montant_paye: parseFloat(formData.montant_paye),
        date_paiement: formData.date_paiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        devise: deviseFinale,
        canal: formData.canal,
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        motif: formData.motif,
        beneficiaire: beneficiaireFinal,
        piece_justificative: formData.piece_justificative || null,
        commentaire: formData.commentaire || null,
        created_by: user?.id,
      }

      if (formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement') {
        sortieInsert.requisition_id = formData.requisition_id
        if (isProgressif && formData.ordre_decaissement_id) {
          sortieInsert.ordre_decaissement_id = formData.ordre_decaissement_id
        }
      } else if (formData.type_sortie === 'sortie_directe' && formData.ordre_decaissement_id) {
        sortieInsert.ordre_decaissement_id = formData.ordre_decaissement_id
      }

      if (!isTransfertInterne) {
        if (posteDefiniParSource) {
          // Poste(s) défini(s) par la source : le backend impute via la réquisition
          // ou les lignes de l'ordre. On envoie le poste mono si connu, sinon null.
          sortieInsert.budget_poste_id = posteSourceMulti ? null : posteMonoId
        } else {
          const budgetPosteId = formData.budget_poste_id ? Number(formData.budget_poste_id) : null
          if (!budgetPosteId || !Number.isFinite(budgetPosteId)) {
            notifyWarning('Poste requis', 'Veuillez sélectionner un poste budgétaire valide.')
            setSubmitting(false)
            return
          }
          sortieInsert.budget_poste_id = budgetPosteId
        }
      }

      const sortieRes: any = await apiRequest('POST', '/sorties-fonds', sortieInsert)

      // On lit la réponse du serveur plutôt que le formulaire : en multi-postes le
      // champ local est vide, alors que la sortie créée porte « Réparti sur N postes ».
      const budgetLabel = formatBudgetLabel(sortieRes) || (formData.rubrique_code || '')
      const selectedOrdreDirect =
        formData.type_sortie === 'sortie_directe' && formData.ordre_decaissement_id
          ? ordresDirects.find((o) => String(o.id) === String(formData.ordre_decaissement_id))
          : null
      // « Autorisé par » : le vrai autorisateur de la tranche/ordre (auto).
      const autoUser = (selectedOrdre as any)?.autorise_par_user
      const autorisateurTranche = autoUser
        ? `${autoUser.prenom || ''} ${autoUser.nom || ''}`.trim()
        : ''
      const pdfSortieBase = selectedReq
        ? { ...sortieRes, requisition: { ...(sortieRes?.requisition || {}), ...selectedReq } }
        : selectedOrdreDirect
          ? { ...sortieRes, ordre_numero: selectedOrdreDirect.numero_ordre }
          : { ...sortieRes }
      const pdfSortie = autorisateurTranche
        ? { ...pdfSortieBase, autorisateur_tranche: autorisateurTranche }
        : pdfSortieBase

      try {
        const pdfBlob = await generateSortieFondsPDF(pdfSortie, budgetLabel, 'blob')
        if (pdfBlob && sortieRes?.id) {
          const pdfForm = new FormData()
          pdfForm.append(
            'file',
            pdfBlob,
            `sortie_${sortieRes.reference_numero || sortieRes.id}.pdf`
          )
          justificatifFiles.forEach((file) => {
            pdfForm.append('attachments', file, file.name)
          })
          await apiRequest('POST', `/sorties-fonds/${sortieRes.id}/pdf`, { params: { notify: true }, body: pdfForm })
        }
      } catch (pdfError) {
        console.error('Error uploading sortie PDF:', pdfError)
      }

      // Le panneau de succès (récapitulatif + impression du bon) est rendu par cette
      // page. Or Layout.tsx enveloppe l'Outlet dans un <div key={location.pathname}> :
      // changer d'URL démonte la page et détruit son état. Sur /sorties-fonds/nouvelle,
      // il faut donc différer le retour à la liste jusqu'à la fermeture du panneau,
      // sinon celui-ci est détruit avant d'avoir été peint.
      const showsSuccessPanel =
        formData.type_sortie === 'requisition'
        || formData.type_sortie === 'remboursement'
        || formData.type_sortie === 'sortie_directe'

      if (formData.type_sortie === 'requisition' || formData.type_sortie === 'remboursement') {
        // Aucun appel de statut ici : POST /sorties-fonds met déjà la réquisition à
        // jour dans la même transaction (statut PAYEE + payee_par/payee_le quand le
        // cumul des sorties VALIDES atteint le montant total, EN_DECAISSEMENT pour un
        // paiement partiel), et enregistre l'historique — cas progressif comme
        // classique. Le PUT /requisitions qui se trouvait ici faisait doublon et était
        // systématiquement rejeté en 409 par le verrou historique
        // (ensure_requisition_editable), la réquisition étant par construction déjà
        // dans un statut final à cet instant.

        const isRemboursementSortie = formData.type_sortie === 'remboursement'
        const transportRef =
          (selectedReq as any)?.remboursement_transport?.reference_numero ||
          (selectedReq as any)?.remboursement_transport?.numero_remboursement ||
          (sortieRes as any)?.requisition?.remboursement_transport?.reference_numero ||
          (sortieRes as any)?.requisition?.remboursement_transport?.numero_remboursement
        setLastCreatedSortie({
          requisition: selectedReq,
          sortie: {
            type_sortie: formData.type_sortie,
            document_label: isRemboursementSortie ? 'Remboursement transport' : 'Réquisition',
            document_reference: isRemboursementSortie
              ? transportRef || selectedReq?.numero_requisition || ''
              : selectedReq?.numero_requisition || '',
            montant_paye: parseFloat(formData.montant_paye),
            mode_paiement: formData.mode_paiement,
            date_paiement: formData.date_paiement,
            reference: formData.reference
          },
          // Permet le bouton « Imprimer le bon de sortie » dans le panneau de succès,
          // à remettre au bénéficiaire pour signature.
          pdfSortie,
          budgetLabel,
        })
        setShowSuccessNotification(true)
      } else if (formData.type_sortie === 'sortie_directe') {
        // Sortie directe : proposer immédiatement l'impression du bon de
        // sortie à la caisse, comme pour une réquisition.
        setLastCreatedSortie({
          requisition: {
            numero_requisition: selectedOrdreDirect?.numero_ordre || sortieRes?.reference_numero || '',
            objet: formData.motif,
            montant_total: parseFloat(formData.montant_paye),
          },
          sortie: {
            type_sortie: formData.type_sortie,
            document_label: 'Sortie directe',
            document_reference: selectedOrdreDirect?.numero_ordre || sortieRes?.reference_numero || '',
            montant_paye: parseFloat(formData.montant_paye),
            mode_paiement: formData.mode_paiement,
            date_paiement: formData.date_paiement,
            reference: formData.reference || sortieRes?.reference_numero || ''
          },
          pdfSortie,
          budgetLabel,
        })
        setShowSuccessNotification(true)
      } else {
        notifySuccess(
          'Sortie enregistrée',
          `${getTypeSortieLabel(formData.type_sortie)} · ${parseFloat(formData.montant_paye).toFixed(2)} $ · ${formData.beneficiaire}`
        )
      }

      setShowForm(false)
      if (isCreatePage && !showsSuccessPanel) {
        navigate('/sorties-fonds')
      }
      setOrdresAutorises([])
      setFormData({
        type_sortie: 'requisition',
        requisition_id: '',
        ordre_decaissement_id: '',
        montant_paye: '',
        date_paiement: format(new Date(), 'yyyy-MM-dd'),
        mode_paiement: 'cash',
        reference: '',
        devise: 'USD',
        canal: 'CAISSE',
        compte_bancaire_id: '',
        commentaire: '',
        motif: '',
        rubrique_code: '',
        budget_poste_id: '',
        service_id: defaultServiceId,
        beneficiaire: '',
        piece_justificative: ''
      })
      setJustificatifFiles([])
      invalidateSortiesFonds()
      window.dispatchEvent(new Event('dashboard-refresh'))
    } catch (error: any) {
      console.error('Error creating sortie:', error)
      let errorMessage = error?.message || 'Erreur inconnue'
      if (typeof errorMessage === 'string') {
        if (errorMessage.includes('Fonds insuffisants en caisse')) {
          errorMessage = 'Solde insuffisant en caisse. Approvisionnez la caisse ou choisissez un compte bancaire.'
        } else if (errorMessage.includes('Fonds insuffisants sur le compte')) {
          errorMessage = 'Solde insuffisant sur le compte sélectionné. Choisissez un autre compte ou approvisionnez-le.'
        }
      }
      notifyError("Erreur d'enregistrement", errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  const handleSaveDraft = async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      await apiRequest('POST', '/sorties-fonds/drafts', {
        type_sortie: formData.type_sortie,
        requisition_id: formData.requisition_id || null,
        ordre_decaissement_id: formData.ordre_decaissement_id || null,
        rubrique_code: formData.rubrique_code || null,
        budget_poste_id: formData.budget_poste_id ? Number(formData.budget_poste_id) : null,
        service_id: formData.service_id ? Number(formData.service_id) : null,
        montant_paye: formData.montant_paye ? parseFloat(formData.montant_paye) : 0,
        date_paiement: formData.date_paiement || null,
        mode_paiement: formData.mode_paiement || 'cash',
        reference: formData.reference || null,
        devise: formData.devise || 'USD',
        canal: formData.canal || 'CAISSE',
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        motif: formData.motif || null,
        beneficiaire: formData.beneficiaire || null,
        piece_justificative: formData.piece_justificative || null,
        commentaire: formData.commentaire || null,
      })
      notifySuccess('Brouillon enregistré', 'La sortie de fonds a été enregistrée en brouillon.')
      invalidateSortiesFonds()
      setFilterStatut('BROUILLON')
      setPage(1)
      if (isCreatePage) {
        navigate('/sorties-fonds')
      } else {
        setShowForm(false)
      }
      resetSortieForm()
    } catch (error: any) {
      notifyError("Erreur d'enregistrement", error?.message || "Impossible d'enregistrer le brouillon.")
    } finally {
      setSubmitting(false)
    }
  }

  const formatCurrency = (amount: string | number | null | undefined) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const canCreate = hasPermission('sorties_fonds')

  const filteredSorties = sortiesList
  const totalSorties = totalMontantSorties
  const hasActiveFilters = Boolean(
    dateDebut || dateFin || filterType || filterModePaiement || filterStatut || filterNumeroRequisition
  )

  const resetFilters = useCallback(() => {
    setDateDebut(today)
    setDateFin(today)
    setPendingDateDebut(today)
    setPendingDateFin(today)
    setFilterType('')
    setFilterModePaiement('')
    setFilterStatut('')
    setFilterNumeroRequisition('')
    setPage(1)
  }, [today])

  const isCancelable = (sortie: SortieFonds) => {
    const reference = sortie.created_at || sortie.date_paiement
    if (!reference) return true
    const refDate = new Date(reference)
    if (Number.isNaN(refDate.getTime())) return true
    const diffMs = Date.now() - refDate.getTime()
    return diffMs <= 30 * 60 * 1000
  }

  const canEditAnnulationMotif = (sortie: SortieFonds) => {
    const statut = String((sortie as any)?.statut || '').toUpperCase()
    if (statut !== 'ANNULEE') return true
    const annuleeLe = (sortie as any)?.annulee_le
    if (!annuleeLe) return true
    const annuleeDate = new Date(annuleeLe)
    if (Number.isNaN(annuleeDate.getTime())) return true
    const diffMs = Date.now() - annuleeDate.getTime()
    return diffMs <= 5 * 60 * 1000
  }

  const getTypeBadgeClass = (typeSortie: string) => {
    switch (typeSortie) {
      case 'requisition':
        return `${styles.typeBadge} ${styles.typeBadgeRequisition}`
      case 'remboursement':
        return `${styles.typeBadge} ${styles.typeBadgeRefund}`
      case 'versement_banque':
        return `${styles.typeBadge} ${styles.typeBadgeTransfer}`
      case 'approvisionnement_caisse':
        return `${styles.typeBadge} ${styles.typeBadgeAppro}`
      default:
        return `${styles.typeBadge} ${styles.typeBadgeDirect}`
    }
  }

  const getTypeLabel = (typeSortie: string) => {
    if (typeSortie === 'requisition') return 'Réquisition'
    if (typeSortie === 'remboursement') return 'Remboursement'
    if (typeSortie === 'versement_banque') return 'Versement'
    if (typeSortie === 'approvisionnement_caisse') return 'Approvisionnement'
    return 'Sortie directe'
  }

  const getModePaiementLabel = (modePaiement: string) => {
    if (modePaiement === 'cash') return 'Cash'
    if (modePaiement === 'mobile_money') return 'Mobile Money'
    if (modePaiement === 'card') return 'Carte (Visa)'
    return 'Opération bancaire'
  }

  const exportToExcel = async () => {
    const suffix = `${dateDebut || 'debut'}_${dateFin || 'fin'}`
    await downloadExcel('/exports/sorties-fonds', {
      date_debut: dateDebut,
      date_fin: dateFin,
      type_sortie: filterType,
      mode_paiement: filterModePaiement,
      statut: filterStatut,
      requisition_numero: filterNumeroRequisition,
    }, `sorties_fonds_${suffix}.xlsx`)
  }

  const exportToPDF = async () => {
    try {
      // Retours en caisse de la période (lignes négatives). On les omet si l'on
      // filtre sur un type/mode/statut spécifique de sortie, que les retours ne portent pas.
      const includeRetours =
        !filterType && !filterModePaiement && (!filterStatut || filterStatut === 'ALL' || filterStatut === 'VALIDE')
      let retours: any[] = []
      if (includeRetours) {
        try {
          const res = await apiRequest<any>('GET', '/retours-caisse', {
            params: { date_debut: dateDebut, date_fin: dateFin, statut: 'VALIDE', limit: 5000 },
          })
          retours = Array.isArray(res) ? res : res?.items || []
        } catch {
          retours = []
        }
      }
      await generateSortiesReportPDF(filteredSorties as any[], {
        dateDebut,
        dateFin,
        retours,
        filters: [
          filterType ? { label: 'Type', value: getTypeLabel(filterType) } : null,
          filterModePaiement ? { label: 'Mode', value: getModePaiementLabel(filterModePaiement) } : null,
          filterStatut ? { label: 'Statut', value: filterStatut === 'ALL' ? 'Tous' : filterStatut } : null,
          filterNumeroRequisition ? { label: 'N° Réquisition', value: filterNumeroRequisition } : null,
        ],
      })
    } catch (error: any) {
      console.error('Erreur export PDF sorties:', error)
      notifyError('Erreur', error?.message || "Impossible de générer le rapport PDF.")
    }
  }

  if (loading || permissionsLoading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonGrid}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`sortie-skel-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
              <div className={styles.skeletonLine} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <PageHeader
        title={isCreatePage ? 'Nouvelle sortie de fonds' : 'Sorties de fonds'}
        subtitle={isCreatePage ? "Enregistrez le paiement d'une réquisition approuvée" : 'Enregistrement des paiements effectués'}
        actions={
          isCreatePage ? (
            <div className={styles.headerActions}>
              <Link to="/" className={styles.breadcrumbLink}>Accueil</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <Link to="/sorties-fonds" className={styles.breadcrumbLink}>Sorties de fonds</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <span className={styles.breadcrumbCurrent}>Nouvelle sortie</span>
              <Link to="/sorties-fonds" className={styles.secondaryBtn}>
                Retour à la liste
              </Link>
              <button
                type="submit"
                form="sortie-fonds-form"
                className={styles.primaryBtn}
                disabled={submitting || noApprovedRequisitionAvailable || amountExceedsRemaining || (isCashClosed && formData.mode_paiement === 'cash')}
              >
                {submitting ? 'Enregistrement...' : 'Enregistrer la sortie'}
              </button>
            </div>
          ) : canCreate && (
            <div className={styles.headerActions}>
              <Link to="/clients" className={styles.secondaryBtn}>
                Gérer les clients
              </Link>
              <Link to="/cloture-caisse" className={styles.secondaryBtn}>
                {isCashClosed ? 'Ouvrir la caisse' : 'Clôture de la journée'}
              </Link>
              <Link to="/sorties-fonds/nouvelle" className={styles.primaryBtn}>
                + Nouvelle sortie
              </Link>
            </div>
          )
        }
      />

      <CaisseSessionBanner />

      {!isCreatePage && canCreate && requisitionsApprouvees.length > 0 && (
        <div className={styles.infoBox}>
          {requisitionsApprouvees.length > 0 && (
            <p className={styles.infoBoxText}>
              <strong>{requisitionsApprouvees.length}</strong> réquisition{requisitionsApprouvees.length > 1 ? 's' : ''} en attente{requisitionsApprouvees.length > 1 ? 's' : ''} de traitement
            </p>
          )}
        </div>
      )}

      {!isCreatePage && <div className={styles.filtersSection}>
        <div className={styles.filtersHeader}>
          <h3 className={styles.filtersTitle}>Filtres</h3>
          <span className={styles.filtersMeta}>
            {totalCount} opération{totalCount > 1 ? 's' : ''}
          </span>
        </div>

        <div className={styles.filtersGrid}>
          <div className={styles.filterGroup}>
            <label>Type de sortie</label>
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
            >
              <option value="">Tous les types</option>
              <option value="requisition">Réquisition</option>
              <option value="remboursement">Remboursement transport</option>
              <option value="versement_banque">Versement banque</option>
              <option value="approvisionnement_caisse">Approvisionnement caisse</option>
              <option value="sortie_directe">Sortie directe / tranche programmée</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Mode de paiement</label>
            <select
              value={filterModePaiement}
              onChange={(e) => setFilterModePaiement(e.target.value)}
            >
              <option value="">Tous les modes</option>
              <option value="cash">Cash</option>
              <option value="mobile_money">Mobile Money</option>
              <option value="virement">Opération bancaire</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Statut</label>
            <select
              value={filterStatut}
              onChange={(e) => setFilterStatut(e.target.value)}
            >
              <option value="">Actifs</option>
              <option value="BROUILLON">Brouillon</option>
              <option value="VALIDE">Validée</option>
              <option value="ANNULEE">Annulée</option>
              {hasPermission('view_cancelled_financial_operations') && <option value="ALL">Tous</option>}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>N° Réquisition</label>
            <input
              type="text"
              value={filterNumeroRequisition}
              onChange={(e) => setFilterNumeroRequisition(e.target.value)}
              placeholder="Rechercher..."
            />
          </div>

          <div className={styles.filterGroup}>
            <label>Date début</label>
            <input
              type="date"
              value={pendingDateDebut}
              onChange={(e) => setPendingDateDebut(e.target.value)}
            />
          </div>

          <div className={styles.filterGroup}>
            <label>Date fin</label>
            <input
              type="date"
              value={pendingDateFin}
              onChange={(e) => setPendingDateFin(e.target.value)}
            />
          </div>
        </div>

        <div className={styles.filtersActions}>
          <div className={styles.pageSize}>
            <label>Affichage</label>
            <select value={String(pageSize)} onChange={(e) => setPageSize(Number(e.target.value))}>
              <option value="20">20 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          <button
            type="button"
            onClick={applyDateFilters}
            className={styles.applyBtn}
            disabled={!hasPendingDateFilters}
          >
            Appliquer la période
          </button>
          {hasActiveFilters && (
            <button
              onClick={resetFilters}
              className={styles.resetBtn}
            >
              Réinitialiser
            </button>
          )}
          {totalCount > 0 && (
            <button
              onClick={exportToExcel}
              className={styles.exportBtn}
            >
              📊 Exporter Excel
            </button>
          )}
          {filteredSorties.length > 0 && (
            <button
              onClick={exportToPDF}
              className={styles.exportBtn}
            >
              📄 Exporter PDF
            </button>
          )}
        </div>

        <div className={styles.summaryBox}>
          <div className={styles.summaryContent}>
            <div>
              <div className={styles.summaryLabel}>Total des sorties sur la période</div>
              <div className={styles.summaryCount}>
                {totalCount} opération{totalCount > 1 ? 's' : ''} • Montant total
              </div>
            </div>
            <div className={styles.summaryValue}>{formatCurrency(totalSorties)}</div>
          </div>
          {(totalTransfertsInternes > 0 || totalRetoursCaisse > 0) && (
            <div
              style={{
                display: 'flex',
                gap: '24px',
                flexWrap: 'wrap',
                marginTop: '10px',
                paddingTop: '10px',
                borderTop: '1px solid rgba(0,0,0,0.08)',
              }}
            >
              <div>
                <div style={{ fontSize: '12px', color: '#6b7280' }}>
                  Dépenses réelles{totalRetoursCaisse > 0 ? ' (brut)' : ''}
                </div>
                <div style={{ fontWeight: 700, color: '#b91c1c' }}>
                  {formatCurrency(totalDepensesReelles)}
                </div>
              </div>
              {totalRetoursCaisse > 0 && (
                <>
                  <div>
                    <div style={{ fontSize: '12px', color: '#6b7280' }}>Retours en caisse</div>
                    <div style={{ fontWeight: 700, color: '#047857' }}>
                      −{formatCurrency(totalRetoursCaisse)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', color: '#6b7280' }}>Dépenses nettes</div>
                    <div style={{ fontWeight: 700, color: '#b91c1c' }}>
                      {formatCurrency(totalDepensesNettes)}
                    </div>
                  </div>
                </>
              )}
              {totalTransfertsInternes > 0 && (
                <div>
                  <div style={{ fontSize: '12px', color: '#6b7280' }}>
                    Transferts internes (caisse ↔ banque)
                  </div>
                  <div style={{ fontWeight: 700, color: '#1d4ed8' }}>
                    {formatCurrency(totalTransfertsInternes)}
                  </div>
                </div>
              )}
              {totalRetoursCaisse > 0 && (
                <div>
                  <div style={{ fontSize: '12px', color: '#6b7280' }}>
                    Total net = export Excel
                  </div>
                  <div style={{ fontWeight: 700, color: '#111827' }}>
                    {formatCurrency(totalMontantSorties - totalRetoursCaisse)}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>}

      {!isCreatePage && totalCount > 0 && (
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

      {(showForm || isCreatePage) && (
        <div className={isCreatePage ? styles.createPageShell : styles.modal}>
          <div className={isCreatePage ? styles.createPageContent : styles.modalContent}>
            {!isCreatePage && (
              <div className={styles.modalHeader}>
                <h2>Nouvelle sortie de fonds</h2>
                <button onClick={closeCreationForm} className={styles.closeBtn}>×</button>
              </div>
            )}

            <form id="sortie-fonds-form" onSubmit={handleSubmit} className={`${styles.form} ${isCreatePage ? styles.createForm : ''}`}>
              {isCreatePage && (
                <div className={styles.createFormIntro}>
                  <div>
                    <span className={styles.sectionEyebrow}>Paiement</span>
                    <h2>Informations principales</h2>
                  </div>
                  <p>Les champs liés à la réquisition, au bénéficiaire et au canal de paiement sont regroupés pour limiter le défilement.</p>
                </div>
              )}
              <div className={isCreatePage ? styles.createLayout : undefined}>
                <div className={isCreatePage ? styles.createMain : undefined}>
              <div className={styles.field}>
                <label>Type de sortie *</label>
                <select
                  value={formData.type_sortie}
                  onChange={(e) => {
                    const nextType = e.target.value as TypeSortieFonds
                    const versement = nextType === 'versement_banque'
                    const appro = nextType === 'approvisionnement_caisse'
                    setFormData({
                      ...formData,
                      type_sortie: nextType,
                      requisition_id: '',
                      ordre_decaissement_id: '',
                      montant_paye: '',
                      motif: versement
                        ? 'Dépôt des recettes journalières à la banque'
                        : appro
                          ? 'Approvisionnement de la caisse depuis la banque'
                          : '',
                      rubrique_code: '',
                      beneficiaire: '',
                      budget_poste_id: '',
                      // Versement : caisse -> banque. Approvisionnement :
                      // banque -> caisse. Le canal indique d'où sort l'argent.
                      canal: versement ? 'CAISSE' : appro ? 'BANQUE' : formData.canal,
                      mode_paiement: versement || appro ? 'cash' : formData.mode_paiement,
                      compte_bancaire_id: versement || appro ? '' : formData.compte_bancaire_id
                    })
                    setOrdresAutorises([])
                    setRubriqueLocked(false)
                    setRubriqueLockMessage('')
                    setServiceLocked(false)
                    setServiceLockMessage('')
                  }}
                  required
                >
                  {CATEGORIES_SORTIE.map((categorie) => (
                    <optgroup key={categorie.label} label={categorie.label}>
                      {categorie.types.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              {requiresApprovedRequisition && (() => {
                const isRemboursementSortie = formData.type_sortie === 'remboursement'
                const requisitionsSource = approvedRequisitionsForType
                return (
                <div className={styles.field}>
                  <label>
                    {isRemboursementSortie
                      ? 'Remboursement transport approuvé *'
                      : 'Réquisition approuvée *'}
                  </label>
                  <select
                    value={formData.requisition_id}
                    onChange={async (e) => {
                      const selectedId = e.target.value
                      const req = requisitionsSource.find(r => String(r.id) === String(selectedId))
                      const enforcedCanal = req?.mode_paiement
                        ? (req.mode_paiement === 'cash' ? 'CAISSE' : 'BANQUE')
                        : formData.canal
                      const requisitionAccount = comptesBancaires.find(
                        (compte) => String(compte.id) === String(req?.compte_bancaire_id || '')
                      )
                      const nextDevise = requisitionAccount?.devise || formData.devise
                      const matchingAccounts = comptesBancaires.filter(
                        (compte) =>
                          String(compte.account_type || 'BANK').toUpperCase() === (enforcedCanal === 'CAISSE' ? 'CASH' : 'BANK') &&
                          String(compte.devise || '').toUpperCase() === String(nextDevise || 'USD')
                      )
                      const nextCompteId = resolveSelectableCompteId(
                        matchingAccounts,
                        enforcedCanal,
                        requisitionAccount ? String(requisitionAccount.id) : formData.compte_bancaire_id
                      )
                      const reqProgressif = !!(req as any)?.decaissement_progressif
                      setFormData({
                        ...formData,
                        requisition_id: selectedId,
                        ordre_decaissement_id: '',
                        montant_paye: req ? (reqProgressif ? '' : req.montant_total.toString()) : '',
                        beneficiaire: reqProgressif ? '' : formData.beneficiaire,
                        mode_paiement: req?.mode_paiement || 'cash',
                        devise: nextDevise,
                        service_id: req?.service_id ? String(req.service_id) : formData.service_id,
                        canal: enforcedCanal,
                        compte_bancaire_id: nextCompteId
                      })
                      if (reqProgressif) {
                        loadOrdresAutorises(selectedId)
                      } else {
                        setOrdresAutorises([])
                      }
                      if (req?.service_id) {
                        setServiceLocked(true)
                        setServiceLockMessage('Service verrouillé par la réquisition')
                      } else {
                        setServiceLocked(false)
                        setServiceLockMessage('')
                      }
                      await applyRequisitionRubrique(selectedId)
                      // Réquisition classique déjà partiellement payée : pré-remplir
                      // le montant avec le reste dû (source serveur fiable) pour un
                      // complément en un clic. Réquisition neuve : le total est conservé.
                      if (req && !reqProgressif) {
                        try {
                          const solde = await apiRequest<any>('GET', `/sorties-fonds/requisitions/${selectedId}/solde`)
                          const reste = Number(solde?.reste)
                          if (Number.isFinite(reste) && reste > 0 && reste < toNumber(req.montant_total)) {
                            setFormData(prev => ({ ...prev, montant_paye: String(reste) }))
                          }
                        } catch {
                          /* silencieux : on conserve le total pré-rempli */
                        }
                      }
                    }}
                    disabled={requisitionsSource.length === 0}
                    required
                  >
                    <option value="">
                      {isRemboursementSortie
                        ? 'Sélectionner un remboursement...'
                        : 'Sélectionner une réquisition...'}
                    </option>
                    {requisitionsSource.length === 0 && (
                      <option value="" disabled>
                        {isRemboursementSortie
                          ? 'Aucun remboursement transport approuvé'
                          : 'Aucune réquisition approuvée'}
                      </option>
                    )}
                    {requisitionsSource.map(req => (
                      <option key={req.id} value={req.id}>
                        {req.numero_requisition} - {req.objet} ({formatCurrency(req.montant_total)})
                      </option>
                    ))}
                  </select>
                  {requisitionsSource.length === 0 && (
                    <small style={{ color: '#b91c1c', fontSize: '12px', display: 'block', marginTop: '6px' }}>
                      {isRemboursementSortie
                        ? 'Aucun remboursement transport approuvé disponible.'
                        : 'Aucune réquisition approuvée disponible.'}
                    </small>
                  )}
                  {selectedRequisition && (
                    <div className={styles.inlineActions}>
                      <div className={styles.selectionHint}>
                        {String(selectedRequisition.type_requisition || '').toLowerCase() === 'remboursement_transport'
                          ? 'Remboursement transport sélectionné'
                          : 'Réquisition sélectionnée'} :
                        {' '}
                        <strong>{selectedRequisition.numero_requisition}</strong>
                      </div>
                      {isPaymentRejectable(selectedRequisition) && !isProgressif && (
                        <button
                          type="button"
                          className={styles.dangerBtn}
                          onClick={() => rejectAtPayment(selectedRequisition)}
                        >
                          Rejeter à la sortie de fonds
                        </button>
                      )}
                      {isProgressif && (
                        <small style={{ color: '#6b7280', fontSize: '12px', display: 'block' }}>
                          Réquisition à décaissement progressif : le rejet global n'est pas possible ici.
                          L'annulation se fait <strong>tranche par tranche (ordre de décaissement)</strong> par
                          le demandeur, dans le Plan de décaissement de la réquisition.
                        </small>
                      )}
                    </div>
                  )}
                </div>
                )
              })()}

              {isSortieDirecte && (
                <div className={styles.field}>
                  <label>Ordre de sortie directe à payer *</label>
                  <select
                    value={formData.ordre_decaissement_id}
                    onChange={(e) => {
                      const oid = e.target.value
                      const ordre = ordresDirects.find((o) => String(o.id) === String(oid))
                      const ordreServiceId = (ordre as any)?.service_id
                      setFormData({
                        ...formData,
                        ordre_decaissement_id: oid,
                        montant_paye: ordre ? String(toNumber(ordre.montant)) : '',
                        beneficiaire: ordre ? ordre.beneficiaire : '',
                        devise: ordre?.devise ? String(ordre.devise) : formData.devise,
                        motif: ordre?.motif ? String(ordre.motif) : formData.motif,
                        service_id: ordreServiceId ? String(ordreServiceId) : formData.service_id,
                      })
                      if (ordreServiceId) {
                        setServiceLocked(true)
                        setServiceLockMessage('Service verrouillé par la sortie directe programmée')
                      } else {
                        setServiceLocked(false)
                        setServiceLockMessage('')
                      }
                      if (!ordre) {
                        setRubriqueLocked(false)
                        setRubriqueLockMessage('')
                      }
                    }}
                    required
                    disabled={loadingOrdresDirects || ordresDirects.length === 0}
                  >
                    <option value="">
                      {loadingOrdresDirects
                        ? 'Chargement…'
                        : ordresDirects.length === 0
                          ? 'Aucune sortie directe autorisée en attente de paiement'
                          : 'Sélectionner une sortie directe à payer…'}
                    </option>
                    {ordresDirects.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.numero_ordre} — {o.beneficiaire} ({toNumber(o.montant).toFixed(2)} {o.devise})
                      </option>
                    ))}
                  </select>
                  <small style={{ color: '#92400e', fontSize: '12px', display: 'block', marginTop: '6px' }}>
                    Sorties directes autorisées (sans réquisition) : montant et bénéficiaire sont
                    verrouillés. Les tranches de réquisitions progressives se paient via le mode
                    « Réquisition ».
                  </small>
                  {formData.ordre_decaissement_id && (
                    <button
                      type="button"
                      onClick={handlePrintOrdreDirect}
                      style={{
                        marginTop: '8px',
                        background: 'transparent',
                        color: '#1d4ed8',
                        border: '1px solid #93c5fd',
                        borderRadius: '6px',
                        padding: '6px 12px',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      <Printer size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Imprimer le bon de sortie directe
                    </button>
                  )}
                </div>
              )}

              {requiresApprovedRequisition && isProgressif && (
                <div className={styles.field}>
                  <label>Ordre de décaissement autorisé *</label>
                  <select
                    value={formData.ordre_decaissement_id}
                    onChange={(e) => {
                      const oid = e.target.value
                      const ordre = ordresAutorises.find((o) => String(o.id) === String(oid))
                      setFormData({
                        ...formData,
                        ordre_decaissement_id: oid,
                        montant_paye: ordre ? String(toNumber(ordre.montant)) : '',
                        beneficiaire: ordre ? ordre.beneficiaire : '',
                        devise: ordre?.devise ? String(ordre.devise) : formData.devise,
                      })
                    }}
                    required
                    disabled={loadingOrdres || ordresAutorises.length === 0}
                  >
                    <option value="">
                      {loadingOrdres
                        ? 'Chargement des ordres…'
                        : ordresAutorises.length === 0
                          ? 'Aucun ordre autorisé en attente'
                          : 'Sélectionner un ordre autorisé…'}
                    </option>
                    {ordresAutorises.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.numero_ordre} — {o.beneficiaire} ({formatCurrency(o.montant)})
                      </option>
                    ))}
                  </select>
                  <small style={{ color: '#4338ca', fontSize: '12px', display: 'block', marginTop: '6px' }}>
                    Réquisition à décaissement progressif : montant et bénéficiaire sont verrouillés
                    par l'ordre autorisé par le demandeur.
                  </small>
                  {ordresAutorises.length === 0 && !loadingOrdres && (
                    <small style={{ color: '#b91c1c', fontSize: '12px', display: 'block', marginTop: '4px' }}>
                      Aucune tranche autorisée : le demandeur doit d'abord autoriser un ordre de
                      décaissement depuis le détail de la réquisition.
                    </small>
                  )}
                </div>
              )}

              {!isTransfertInterne && (
              <div className={styles.field}>
                <label>Service / Commission *</label>
                {isServiceUser && userServiceIds.length === 1 ? (
                  <>
                    <input type="hidden" value={formData.service_id} />
                    <div className={styles.readonlyField}>{serviceLabel || 'Service assigné'}</div>
                  </>
                ) : (
                  <select
                    value={formData.service_id}
                    onChange={(e) => {
                      setFormData({ ...formData, service_id: e.target.value })
                      setServiceLocked(false)
                      setServiceLockMessage('')
                    }}
                    disabled={noApprovedRequisitionAvailable || serviceLocked || isServiceLockedByRequisition || isServiceLockedByContext}
                    className={(noApprovedRequisitionAvailable || serviceLocked || isServiceLockedByRequisition || isServiceLockedByContext) ? styles.lockedSelect : undefined}
                    required
                  >
                    <option value="">Sélectionner un service...</option>
                    {servicesList
                      .filter((service) => !isServiceUser || userServiceIds.includes(service.id))
                      .map((service) => (
                        <option key={service.id} value={service.id}>
                          {service.code} - {service.libelle}
                        </option>
                      ))}
                  </select>
                )}
                {(serviceLocked || isServiceLockedByRequisition || isServiceLockedByContext) && (
                  <small style={{ color: '#b91c1c', fontSize: '12px', display: 'block', marginTop: '6px' }}>
                    <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />{serviceLockMessage || 'Service verrouillé'}
                  </small>
                )}
              </div>
              )}

              <div className={styles.field}>
                <label>Motif de la sortie *</label>
                <textarea
                  value={formData.motif}
                  onChange={(e) => setFormData({ ...formData, motif: e.target.value })}
                  rows={3}
                  placeholder={getMotifPlaceholder(formData.type_sortie)}
                  disabled={noApprovedRequisitionAvailable}
                  required
                  style={{ resize: 'vertical' }}
                />
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Soyez descriptif et précis dans votre motif pour faciliter le suivi
                </small>
              </div>

              {!isTransfertInterne && (
              <div className={styles.field}>
                <label>Bénéficiaire *</label>
                <input
                  type="text"
                  value={formData.beneficiaire}
                  onChange={(e) => setFormData({ ...formData, beneficiaire: e.target.value })}
                  placeholder={getBeneficiairePlaceholder(formData.type_sortie)}
                  disabled={noApprovedRequisitionAvailable || isProgressif || isSortieDirecte}
                  className={(isProgressif || isSortieDirecte) ? styles.lockedSelect : undefined}
                  required
                />
              </div>
              )}

              {/* Poste(s) défini(s) en amont par la source : lecture seule, la caissière exécute. */}
              {!isTransfertInterne && posteSourceMulti && (
              <div className={styles.field}>
                <label>Postes budgétaires (définis par l'ordre)</label>
                <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '8px', padding: '10px' }}>
                  <div style={{ fontSize: '12px', color: '#0369a1', marginBottom: '6px' }}>
                    <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Réparti sur {ordrePostes.length} postes — imputation définie en amont, non modifiable.
                  </div>
                  <div style={{ display: 'grid', gap: '4px' }}>
                    {ordrePostes.map((p) => {
                      const line = budgetLineMap.get(String(p.id))
                      return (
                        <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', fontSize: '13px' }}>
                          <span>{line ? `${line.code} - ${line.libelle}` : `Poste #${p.id}`}</span>
                          <strong>{formatCurrency(p.montant)}</strong>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
              )}

              {!isTransfertInterne && posteSourceMono && (
              <div className={styles.field}>
                <label>Poste budgétaire (défini par la source)</label>
                <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '8px', padding: '10px', fontSize: '13px' }}>
                  <span><Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />{(() => {
                    const line = posteMonoId != null ? budgetLineMap.get(String(posteMonoId)) : null
                    return line ? `${line.code} - ${line.libelle}` : `Poste #${posteMonoId ?? ''}`
                  })()}</span>
                  <div style={{ fontSize: '12px', color: '#0369a1', marginTop: '4px' }}>Défini en amont — non modifiable.</div>
                </div>
              </div>
              )}

              {!isTransfertInterne && !posteDefiniParSource && (
              <div className={styles.field}>
                <label>Poste budgétaire *</label>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    value={budgetSearch}
                    onChange={(e) => {
                      setBudgetSearch(e.target.value)
                      setFormData({ ...formData, budget_poste_id: '' })
                      setShowBudgetDropdown(true)
                    }}
                    onFocus={() => setShowBudgetDropdown(true)}
                    onBlur={() => {
                      setTimeout(() => setShowBudgetDropdown(false), 120)
                    }}
                    placeholder="Rechercher par code ou libellé"
                    disabled={noApprovedRequisitionAvailable || rubriqueLocked}
                    className={(noApprovedRequisitionAvailable || rubriqueLocked) ? styles.lockedSelect : undefined}
                  />
                  {showBudgetDropdown && filteredBudgetTree.length > 0 && (
                    <div
                      className={styles.dropdown}
                      data-tree-scroll
                      onMouseDown={(event) => event.preventDefault()}
                    >
                      {filteredBudgetTree.map((node: any) => (
                        <BudgetDropdownNode
                          key={node.id}
                          node={node}
                          depth={0}
                          expandedIds={expandedBudgetIds}
                          onToggle={toggleBudgetNode}
                          onSelect={selectBudgetPoste}
                        />
                      ))}
                    </div>
                  )}
                  {showBudgetDropdown && filteredBudgetTree.length === 0 && (
                    <div
                      className={styles.dropdown}
                      onMouseDown={(event) => event.preventDefault()}
                    >
                      <div className={styles.dropdownItem}>
                        Aucun poste trouvé.
                      </div>
                    </div>
                  )}
                </div>
                <input type="hidden" value={formData.budget_poste_id} required />
                {!rubriqueLocked && rubriqueLockMessage && (
                  <small style={{ color: '#b91c1c', fontSize: '12px', display: 'block', marginTop: '6px' }}>
                    {rubriqueLockMessage}
                  </small>
                )}
                {formData.budget_poste_id && (() => {
                  const selected = budgetLinesList.find((b: any) => String(b.id) === String(formData.budget_poste_id))
                  if (!selected) return null
                  const plafond = toNumber(selected.montant_prevu)
                  const dejaPaye = toNumber(selected.montant_paye)
                  const reste = plafond - dejaPaye
                  return (
                    <small style={{ color: reste < 0 ? '#b91c1c' : '#6b7280', fontSize: '12px' }}>
                      Disponible: {formatCurrency(reste)} · Payé: {formatCurrency(dejaPaye)}
                    </small>
                  )
                })()}
              </div>
              )}

              {isTransfertInterne && (
                <small style={{ color: '#0369a1', fontSize: '12px', display: 'block', marginBottom: '8px' }}>
                  {isVersementBanque
                    ? "Versement des espèces de la caisse vers la banque : la caisse est débitée et le compte bancaire choisi est crédité. Aucun service, bénéficiaire ni poste budgétaire n'est requis — ce n'est pas une dépense."
                    : "Approvisionnement de la caisse : retrait d'espèces du compte bancaire choisi (débité) pour alimenter la caisse (créditée). Aucun service, bénéficiaire ni poste budgétaire n'est requis — ce n'est pas une dépense."}
                </small>
              )}

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Devise *</label>
                  <select
                    value={formData.devise}
                    onChange={(e) => {
                      const devise = e.target.value
                      const wantCash = formData.canal === 'CAISSE' && !isVersementBanque
                      const nextAccounts = comptesBancaires.filter(
                        (compte) =>
                          String(compte.account_type || 'BANK').toUpperCase() === (wantCash ? 'CASH' : 'BANK') &&
                          String(compte.devise || '').toUpperCase() === String(devise)
                      )
                      setFormData((prev) => ({
                        ...prev,
                        devise,
                        compte_bancaire_id: resolveSelectableCompteId(
                          nextAccounts,
                          isVersementBanque ? 'BANQUE' : prev.canal,
                          prev.compte_bancaire_id
                        ),
                        }))
                    }}
                    disabled={noApprovedRequisitionAvailable || isApproCaisse}
                    className={isApproCaisse ? styles.lockedSelect : undefined}
                    required
                  >
                    <option value="USD">USD</option>
                    <option value="CDF">CDF</option>
                  </select>
                  {isApproCaisse && (
                    <div className={styles.lockedHint}>
                      <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
                      Devise imposée par le compte bancaire source.
                    </div>
                  )}
                </div>
                {!isTransfertInterne && (
                <div className={styles.field}>
                  <label>Canal *</label>
                  <select
                    value={formData.canal}
                    className={(noApprovedRequisitionAvailable || isCashClosed || (isRequisitionBound && !!selectedRequisition?.mode_paiement)) ? styles.lockedSelect : undefined}
                    onChange={(e) => {
                      const canal = e.target.value
                      const nextAccounts = comptesBancaires.filter(
                        (compte) =>
                          String(compte.account_type || 'BANK').toUpperCase() === (canal === 'CAISSE' ? 'CASH' : 'BANK') &&
                          String(compte.devise || '').toUpperCase() === String(formData.devise || 'USD')
                      )
                      setFormData((prev) => ({
                        ...prev,
                        canal,
                        compte_bancaire_id: resolveSelectableCompteId(nextAccounts, canal, prev.compte_bancaire_id),
                        }))
                    }}
                    disabled={noApprovedRequisitionAvailable || isCashClosed || (isRequisitionBound && !!selectedRequisition?.mode_paiement)}
                    required
                  >
                    <option value="CAISSE" disabled={isCashClosed}>Caisse</option>
                    <option value="BANQUE">Banque</option>
                  </select>
                  {isCashClosed && (
                    <div className={styles.lockedHint}>
                      Caisse fermée : ouvrez la caisse pour effectuer des sorties en espèces.
                    </div>
                  )}
                  {isRequisitionBound && !!selectedRequisition?.mode_paiement && (
                    <div className={styles.lockedHint}>
                      <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Canal verrouillé par le mode de paiement de la réquisition.
                    </div>
                  )}
                </div>
                )}
                {showCompteSourceSelector && (
                  <div className={styles.field}>
                    <label>
                      {isVersementBanque
                        ? 'Banque de destination *'
                        : isApproCaisse
                          ? 'Banque source (retrait) *'
                          : 'Compte bancaire à débiter *'}
                    </label>
                    <select
                      value={formData.compte_bancaire_id}
                      onChange={(e) => {
                        const compteId = e.target.value
                        // Appro caisse : la devise du retrait est celle du compte choisi.
                        const compte = comptesBancaires.find((c) => String(c.id) === String(compteId))
                        const deviseCompte = String(compte?.devise || '').toUpperCase()
                        setFormData((prev) => ({
                          ...prev,
                          compte_bancaire_id: compteId,
                          devise: isApproCaisse && deviseCompte ? deviseCompte : prev.devise,
                        }))
                      }}
                      disabled={noApprovedRequisitionAvailable}
                      className={noApprovedRequisitionAvailable ? styles.lockedSelect : undefined}
                      required
                    >
                      <option value="">Sélectionner un compte</option>
                      {filteredComptes.map((compte) => (
                        <option key={compte.id} value={compte.id}>
                          {(String(compte.account_type || 'BANK').toUpperCase() === 'CASH' ? 'Caisse' : (compte.banque?.nom || 'Banque'))} - {compte.intitule} ({compte.devise})
                        </option>
                      ))}
                      {filteredComptes.length === 0 && (
                        <option value="" disabled>
                          {isApproCaisse
                            ? 'Aucun compte bancaire configuré'
                            : `Aucun compte bancaire ${formData.devise} configuré`}
                        </option>
                      )}
                    </select>
                    {isRequisitionBound && !!selectedRequisition?.mode_paiement && (
                      <div className={styles.lockedHint}>
                        Le compte source reste sélectionnable parmi les comptes compatibles.
                      </div>
                    )}
                  </div>
                )}
                {showCaisseDebitInfo && (
                  <div className={styles.field}>
                    <label>Caisse à débiter</label>
                    <div className={styles.readOnlySourceBox}>
                      La sortie sera exécutée sur la caisse active. Aucun compte bancaire source n'est requis.
                    </div>
                  </div>
                )}
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>
                    Montant ({formData.devise}) *
                    {formData.type_sortie === 'sortie_directe' && (
                      <span style={{color: '#dc2626', fontSize: '12px', marginLeft: '8px'}}>
                        (Maximum 100 $)
                      </span>
                    )}
                  </label>
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    value={formData.montant_paye}
                    onChange={(e) => setFormData({ ...formData, montant_paye: e.target.value })}
                    max={formData.type_sortie === 'sortie_directe' ? 100 : undefined}
                    required
                    disabled={noApprovedRequisitionAvailable || isRequisitionBound || isSortieDirecte}
                    className={(noApprovedRequisitionAvailable || isRequisitionBound || isSortieDirecte) ? styles.lockedSelect : undefined}
                  />
                  {selectedRequisition && (
                    <small className={amountExceedsRemaining ? styles.inlineError : styles.inlineHelp}>
                      Approuvé: {formatCurrency(approvedAmount)} · Déjà payé: {formatCurrency(alreadyPaidAmount)} · Reste après cette sortie: {formatCurrency(remainingAfterPayment)}
                    </small>
                  )}
                </div>

                <div className={styles.field}>
                  <label>Date de paiement *</label>
                  <input
                    type="date"
                    value={formData.date_paiement}
                    onChange={(e) => setFormData({ ...formData, date_paiement: e.target.value })}
                    disabled={noApprovedRequisitionAvailable || !peutAntidater}
                    required
                    title={
                      peutAntidater
                        ? 'Super administrateur : vous pouvez régulariser une saisie à une date antérieure'
                        : "L'opération est horodatée par le serveur"
                    }
                  />
                  {!peutAntidater && (
                    <small className={styles.fieldHint}>
                      Horodatage automatique par le serveur.
                    </small>
                  )}
                </div>
              </div>

              <div className={styles.fieldRow}>
                {!isTransfertInterne && (
                <div className={styles.field}>
                  <label>Mode de paiement *</label>
                  <select
                    value={formData.mode_paiement}
                    className={(noApprovedRequisitionAvailable || isCashClosed || (isRequisitionBound && !!selectedRequisition?.mode_paiement)) ? styles.lockedSelect : undefined}
                    onChange={(e) => setFormData({ ...formData, mode_paiement: e.target.value as ModePaiement })}
                    disabled={noApprovedRequisitionAvailable || (isRequisitionBound && !!selectedRequisition?.mode_paiement)}
                    required
                  >
                    <option value="cash" disabled={isCashClosed}>Cash</option>
                    <option value="mobile_money">Mobile Money</option>
                    <option value="virement">Opération bancaire</option>
                  </select>
                  {isCashClosed && (
                    <div className={styles.lockedHint}>
                      Caisse fermée : ouvrez la caisse pour payer en espèces.
                    </div>
                  )}
                  {isRequisitionBound && !!selectedRequisition?.mode_paiement && (
                    <div className={styles.lockedHint}>
                      <Lock size={13} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />Mode de paiement verrouillé par la réquisition approuvée.
                    </div>
                  )}
                </div>
                )}

                {(formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && (
                  <div className={styles.field}>
                    <label>Référence *</label>
                    <input
                      type="text"
                      value={formData.reference}
                      onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                      placeholder="N° de transaction, opération bancaire, etc."
                      disabled={noApprovedRequisitionAvailable}
                      required
                    />
                  </div>
                )}

                {formData.mode_paiement === 'cash' && (
                  <div className={styles.field}>
                    <label>Référence (optionnel)</label>
                    <input
                      type="text"
                      value={formData.reference}
                      onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                      placeholder="Ex: Bordereau, note de débit, etc."
                      disabled={noApprovedRequisitionAvailable}
                    />
                  </div>
                )}
              </div>

              <div className={styles.field}>
                <label>Pièce justificative (optionnel)</label>
                <input
                  type="text"
                  value={formData.piece_justificative}
                  onChange={(e) => setFormData({ ...formData, piece_justificative: e.target.value })}
                  placeholder="Référence de la note de débit, bordereau, etc."
                  disabled={noApprovedRequisitionAvailable}
                />
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Indiquez le numéro ou la référence du document justificatif
                </small>
              </div>

              <div className={styles.field}>
                <label>Justificatifs (fichiers, optionnel)</label>
                <label className={styles.fileDropZone}>
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={(e) => setJustificatifFiles(Array.from(e.target.files || []))}
                    disabled={noApprovedRequisitionAvailable}
                  />
                  <span>Glisser-déposer ou choisir un fichier</span>
                  <small>PDF, JPG, PNG · 3 Mo max par fichier</small>
                </label>
                {justificatifFiles.length > 0 && (
                  <div className={styles.selectedFiles}>
                    {justificatifFiles.map((file) => (
                      <span key={`${file.name}-${file.size}`}>
                        {file.name}
                      </span>
                    ))}
                    <button type="button" onClick={() => setJustificatifFiles([])}>
                      Supprimer
                    </button>
                  </div>
                )}
              </div>

              <div className={styles.field}>
                <label>Observation (optionnel)</label>
                <textarea
                  value={formData.commentaire}
                  onChange={(e) => setFormData({ ...formData, commentaire: e.target.value })}
                  rows={2}
                  placeholder="Informations complémentaires..."
                  disabled={noApprovedRequisitionAvailable}
                  style={{ resize: 'vertical' }}
                />
              </div>

                </div>
              {isCreatePage && (
                  <aside className={styles.requisitionSummaryPanel} aria-label="Résumé de la réquisition">
                    <div className={styles.summaryPanelHeader}>
                      <span>Résumé</span>
                      <strong>{selectedRequisition?.numero_requisition || 'Aucune réquisition'}</strong>
                    </div>
                    <div className={styles.summaryRows}>
                      <div>
                        <span>Type</span>
                        <strong>{getTypeSortieLabel(formData.type_sortie)}</strong>
                      </div>
                      <div>
                        <span>Service / Commission</span>
                        <strong>{serviceLabel || 'Non défini'}</strong>
                      </div>
                      <div>
                        <span>Bénéficiaire</span>
                        <strong>{formData.beneficiaire || (selectedRequisition as any)?.demandeur?.nom || 'Non renseigné'}</strong>
                      </div>
                      <div>
                        <span>Statut</span>
                        <strong>{String((selectedRequisition as any)?.status || (selectedRequisition as any)?.statut || 'En préparation')}</strong>
                      </div>
                    </div>
                    <div className={styles.amountReview}>
                      <div>
                        <span>Montant approuvé</span>
                        <strong>{formatCurrency(approvedAmount)}</strong>
                      </div>
                      <div>
                        <span>Déjà payé</span>
                        <strong>{formatCurrency(alreadyPaidAmount)}</strong>
                      </div>
                      <div className={amountExceedsRemaining ? styles.amountWarning : styles.amountCurrent}>
                        <span>Cette sortie</span>
                        <strong>{formatCurrency(currentPaymentAmount)}</strong>
                      </div>
                      <div>
                        <span>Reste après validation</span>
                        <strong>{formatCurrency(remainingAfterPayment)}</strong>
                      </div>
                    </div>
                    {amountExceedsRemaining && (
                      <div className={styles.validationNotice}>
                        Le montant saisi dépasse le reste à payer ({formatCurrency(remainingBeforePayment)}).
                      </div>
                    )}
                    <div className={styles.summaryRows}>
                      <div>
                        <span>Date d'approbation</span>
                        <strong>{(selectedRequisition as any)?.approved_at ? format(new Date((selectedRequisition as any).approved_at), 'dd/MM/yyyy') : 'Non disponible'}</strong>
                      </div>
                      <div>
                        <span>Approuvé par</span>
                        <strong>{(selectedRequisition as any)?.approved_by_user?.nom || (selectedRequisition as any)?.approbateur?.nom || 'Non disponible'}</strong>
                      </div>
                    </div>
                  </aside>
              )}
              </div>

              <div className={styles.formActions}>
                <button
                  type="button"
                  onClick={closeCreationForm}
                  className={styles.secondaryBtn}
                  disabled={submitting}
                >
                  Annuler
                </button>
                {isCreatePage && (
                  <>
                    <button
                      type="button"
                      className={styles.secondaryBtn}
                      disabled={submitting}
                      onClick={resetSortieForm}
                    >
                      Réinitialiser
                    </button>
                    <button
                      type="button"
                      className={styles.secondaryBtn}
                      disabled={submitting}
                      onClick={handleSaveDraft}
                    >
                      {submitting ? 'Enregistrement...' : 'Enregistrer le brouillon'}
                    </button>
                  </>
                )}
                <button
                  type="submit"
                  className={styles.primaryBtn}
                  disabled={submitting || noApprovedRequisitionAvailable || amountExceedsRemaining || (isCashClosed && formData.mode_paiement === 'cash')}
                >
                  {submitting ? 'Enregistrement en cours...' : isCreatePage ? 'Enregistrer et valider' : 'Enregistrer le paiement'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {!isCreatePage && (
        <>
        <div className={styles.tableContainer}>
          <table className={styles.table}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>N° Réquisition / Motif</th>
              <th>Objet / Bénéficiaire</th>
              <th>Poste budgétaire</th>
              <th>Montant payé</th>
              <th>Paiement</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredSorties.length === 0 ? (
              <tr>
                <td colSpan={9} style={{textAlign: 'center', padding: '30px', color: '#9ca3af'}}>
                  {dateDebut || dateFin ? 'Aucune sortie de fonds trouvée pour cette période' : 'Aucune sortie de fonds enregistrée'}
                </td>
              </tr>
            ) : (
              filteredSorties.map((sortie) => {
                const sortieWithType = sortie as any
                const typeSortie = sortieWithType.type_sortie || 'requisition'

                return (
                  <tr key={sortie.id}>
                    <td>
                      <div className={styles.cellStack}>
                        <strong className={styles.cellPrimary}>{format(new Date(sortie.date_paiement), 'dd/MM/yyyy')}</strong>
                        {(() => {
                          const u = (sortie as any).programme_par_user
                          if (!u) return null
                          const full = `${u.prenom || ''} ${u.nom || ''}`.trim()
                          const name = full || u.email
                          return name ? <span className={styles.cellSecondary}>par {name}</span> : null
                        })()}
                      </div>
                    </td>
                    <td>
                      <div className={styles.cellStack}>
                        <span className={getTypeBadgeClass(typeSortie)}>
                          {getTypeLabel(typeSortie)}
                        </span>
                        {/* Transferts internes : le sens réel n'est pas lisible
                            depuis le seul mot « sortie ». */}
                        {typeSortie === 'approvisionnement_caisse' && (
                          <span className={styles.senseHint}>Banque → Caisse (entrée caisse)</span>
                        )}
                        {typeSortie === 'versement_banque' && (
                          <span className={styles.senseHint} style={{ color: '#92400e' }}>
                            Caisse → Banque (entrée banque)
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      {typeSortie === 'requisition' ? (
                        <div className={styles.cellStack}>
                          <strong className={styles.cellPrimary}>{sortie.requisition?.numero_requisition || '—'}</strong>
                          <span className={styles.cellSecondary}>Dossier validé</span>
                        </div>
                      ) : (
                        <div className={styles.cellStack}>
                          <span className={styles.cellPrimary}>{sortieWithType.motif || '—'}</span>
                          <span className={styles.cellSecondary}>{getTypeLabel(typeSortie)}</span>
                        </div>
                      )}
                    </td>
                    <td>
                      <div className={styles.cellStack}>
                        <span className={styles.cellPrimary}>
                          {typeSortie === 'requisition'
                            ? sortie.requisition?.objet || '—'
                            : sortieWithType.beneficiaire || '—'}
                        </span>
                        {typeSortie === 'requisition' && sortieWithType.beneficiaire && (
                          <span className={styles.cellSecondary}>{sortieWithType.beneficiaire}</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div className={styles.cellStack}>
                        <span className={styles.cellPrimary}>
                          {sortieWithType.budget_poste_code && sortieWithType.budget_poste_libelle
                            ? `${sortieWithType.budget_poste_code} - ${sortieWithType.budget_poste_libelle}`
                            : sortieWithType.budget_poste_id
                              ? (() => {
                                  const line = budgetLineMap.get(String(sortieWithType.budget_poste_id))
                                  return line ? `${line.code} - ${line.libelle}` : `#${sortieWithType.budget_poste_id}`
                                })()
                              : sortieWithType.budget_poste_libelle
                                ? sortieWithType.budget_poste_libelle
                                : '-'}
                        </span>
                      </div>
                    </td>
                    <td><strong className={styles.amountValue}>{formatCurrency(sortie.montant_paye)}</strong></td>
                    <td>
                      <div className={styles.cellStack}>
                        <span className={styles.cellPrimary}>{getModePaiementLabel(sortie.mode_paiement)}</span>
                        <span className={`${styles.cellSecondary} ${styles.referenceValue}`}>{(sortie as any).reference_numero || sortie.reference || '—'}</span>
                      </div>
                    </td>
                    <td>{renderStatutBadge((sortie as any).statut, (sortie as any).motif_annulation)}</td>
                    <td>
                      <div className={styles.actions}>
                        {(() => {
                          const annexes = getAnnexesList(sortie)
                          const canFetchRequisition = Boolean((sortie as any)?.requisition_id)
                          if (annexes.length === 0 && !canFetchRequisition) {
                            return null
                          }
                          return (
                          <button
                            onClick={() => {
                              openAnnexesForSortie(sortie)
                            }}
                            className={`${styles.actionBtn} ${styles.actionIconBtn} ${styles.detailBtn}`}
                            title="Voir détails"
                            aria-label="Voir détails"
                          >
                            <Search size={16} />
                          </button>
                          )
                        })()}
                        <button
                          onClick={() => handlePrintBonCaisse(sortie as SortieFonds)}
                          className={`${styles.actionBtn} ${styles.actionIconBtn} ${styles.printActionBtn}`}
                          title={String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE' ? 'Imprimer l’opération annulée' : 'Imprimer le bon de caisse'}
                          aria-label={String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE' ? 'Imprimer l’opération annulée' : 'Imprimer le bon de caisse'}
                        >
                          <Printer size={16} /><span className={styles.printLabel}>Bon</span>
                        </button>
                        {canRetournerCaisse(sortie as SortieFonds) && (
                          <button
                            type="button"
                            className={`${styles.actionBtn} ${styles.actionIconBtn}`}
                            onClick={() => setRetourModalSortie(sortie as any)}
                            title="Retour en caisse (reliquat d’avance / correction)"
                            aria-label="Retour en caisse"
                          >
                            <Undo2 size={16} /><span className={styles.printLabel}>Retour</span>
                          </button>
                        )}
                        {canUpdateStatut && (
                          <div className={styles.statusActions}>
                            <button
                              type="button"
                              className={`${styles.actionBtn} ${styles.actionIconBtn} ${styles.statusBtnCancel}`}
                              onClick={() => updateSortieStatut(sortie as SortieFonds, 'ANNULEE')}
                              disabled={
                                String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE'
                                  ? !isCancelable(sortie as SortieFonds) || !canEditAnnulationMotif(sortie as SortieFonds)
                                  : !isCancelable(sortie as SortieFonds)
                              }
                              title={
                                String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE'
                                  ? (!isCancelable(sortie as SortieFonds)
                                    ? 'Annulation impossible après 30 minutes'
                                    : !canEditAnnulationMotif(sortie as SortieFonds)
                                      ? 'Motif non modifiable après 5 minutes'
                                      : 'Modifier le motif')
                                  : (!isCancelable(sortie as SortieFonds)
                                    ? 'Annulation impossible après 30 minutes'
                                    : 'Annuler')
                              }
                              aria-label="Annuler"
                            >
                              <Ban size={16} />
                            </button>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
          </table>
        </div>

      <div className={styles.mobileCards}>
        {filteredSorties.length === 0 ? (
          <div className={styles.emptyCards}>
            {dateDebut || dateFin ? 'Aucune sortie de fonds trouvée pour cette période' : 'Aucune sortie de fonds enregistrée'}
          </div>
        ) : (
          filteredSorties.map((sortie) => {
            const sortieWithType = sortie as any
            const typeSortie = sortieWithType.type_sortie || 'requisition'
            const typeLabel =
              typeSortie === 'requisition'
                ? 'Réquisition'
                : typeSortie === 'remboursement'
                ? 'Remboursement'
                : typeSortie === 'versement_banque'
                ? 'Versement'
                : 'Sortie directe'

            const motif = typeSortie === 'requisition'
              ? sortie.requisition?.numero_requisition
              : sortieWithType.motif || '-'

            const beneficiaire = typeSortie === 'requisition'
              ? sortie.requisition?.objet
              : sortieWithType.beneficiaire || '-'

            return (
              <div key={`card-${sortie.id}`} className={styles.card}>
                <div className={styles.cardHeader}>
                  <div>
                    <div className={styles.cardTitle}>{format(new Date(sortie.date_paiement), 'dd/MM/yyyy')}</div>
                    <div className={styles.cardSub}>{typeLabel}</div>
                  </div>
                  <div className={styles.cardAmountMain}>-{formatCurrency(sortie.montant_paye)}</div>
                </div>

                <div className={styles.cardBody}>
                  <div className={getTypeBadgeClass(typeSortie)}>{typeLabel}</div>
                  {typeSortie === 'approvisionnement_caisse' && (
                    <div className={styles.senseHint}>Banque → Caisse (entrée caisse)</div>
                  )}
                  {typeSortie === 'versement_banque' && (
                    <div className={styles.senseHint} style={{ color: '#92400e' }}>
                      Caisse → Banque (entrée banque)
                    </div>
                  )}
                  <div className={styles.cardGrid}>
                    <div>
                      <div className={styles.cardLabel}>Réf</div>
                      <div className={styles.cardValue}>{motif}</div>
                    </div>
                    <div>
                      <div className={styles.cardLabel}>Bénéficiaire</div>
                      <div className={styles.cardValue}>{beneficiaire}</div>
                    </div>
                    <div>
                      <div className={styles.cardLabel}>Mode</div>
                      <div className={styles.cardValue}>{getModePaiementLabel(sortie.mode_paiement)}</div>
                    </div>
                    <div>
                      <div className={styles.cardLabel}>Statut</div>
                      <div className={styles.cardValue}>
                        {renderStatutBadge((sortie as any).statut, (sortie as any).motif_annulation)}
                      </div>
                    </div>
                  </div>
                </div>

                <div className={styles.cardActions}>
                  {(() => {
                    const annexes = getAnnexesList(sortie)
                    const canFetchRequisition = Boolean((sortie as any)?.requisition_id)
                    if (annexes.length === 0 && !canFetchRequisition) {
                      return null
                    }
                    return (
                    <button
                      type="button"
                      className={styles.cardActionBtn}
                      onClick={() => {
                        openAnnexesForSortie(sortie)
                      }}
                      title="Voir détails"
                    >
                      <Paperclip size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Voir détails
                    </button>
                    )
                  })()}
                  <button
                    onClick={() => handlePrintBonCaisse(sortie as SortieFonds)}
                    className={styles.cardActionBtn}
                  >
                    <Printer size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Bon de caisse
                  </button>
                  {canRetournerCaisse(sortie as SortieFonds) && (
                    <button
                      type="button"
                      className={styles.cardActionBtn}
                      onClick={() => setRetourModalSortie(sortie as any)}
                    >
                      <Undo2 size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Retour en caisse
                    </button>
                  )}
                  {canUpdateStatut && (
                    <>
                      <button
                        type="button"
                        className={`${styles.cardActionBtn} ${styles.cardActionCancel}`}
                        onClick={() => updateSortieStatut(sortie as SortieFonds, 'ANNULEE')}
                        disabled={
                          String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE'
                            ? !isCancelable(sortie as SortieFonds) || !canEditAnnulationMotif(sortie as SortieFonds)
                            : !isCancelable(sortie as SortieFonds)
                        }
                        title={
                          String((sortie as any)?.statut || '').toUpperCase() === 'ANNULEE'
                            ? (!isCancelable(sortie as SortieFonds)
                              ? 'Annulation impossible après 30 minutes'
                              : !canEditAnnulationMotif(sortie as SortieFonds)
                                ? 'Motif non modifiable après 5 minutes'
                                : 'Modifier le motif')
                            : (!isCancelable(sortie as SortieFonds)
                              ? 'Annulation impossible après 30 minutes'
                              : 'Annuler')
                        }
                      >
                        <Ban size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Annuler
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
        </>
      )}

      <RetourCaisseModal
        isOpen={!!retourModalSortie}
        sortie={retourModalSortie}
        onClose={() => setRetourModalSortie(null)}
        onSuccess={() => {
          invalidateSortiesFonds()
          const target = retourModalSortie
          const full = target ? (sorties as any[]).find((s) => String(s.id) === String(target.id)) : null
          if (full) {
            // Régénère et ré-archive le bon d'origine avec le retour (sans téléchargement).
            handlePrintBonCaisse(full as SortieFonds, { silent: true }).catch(() => {})
          }
        }}
      />

      {annexesModal && (
        <div
          className={styles.modal}
          onClick={() => setAnnexesModal(null)}
        >
          <div
            className={styles.modalContent}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h2>{annexesModal.title}</h2>
              <button onClick={() => setAnnexesModal(null)} className={styles.closeBtn}>×</button>
            </div>
            <div className={styles.annexesBody}>
              <div className={styles.annexesActions}>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={() => {
                    annexesModal.items.forEach((item, idx) => {
                      if (idx === 0) {
                        openUploadUrl(item.url).catch((error) => {
                          console.error('Error opening annex:', error)
                          notifyError('Erreur', "Impossible d'ouvrir le justificatif.")
                        })
                      } else {
                        setTimeout(() => {
                          openUploadUrl(item.url).catch((error) => {
                            console.error('Error opening annex:', error)
                            notifyError('Erreur', "Impossible d'ouvrir le justificatif.")
                          })
                        }, idx * 300)
                      }
                    })
                  }}
                >
                  Ouvrir tout
                </button>
              </div>
              <ul className={styles.annexesList}>
                {annexesModal.items.map((item, idx) => {
                  return (
                    <li key={`${item.label}-${idx}`} className={styles.annexesItem}>
                      <span className={styles.annexIndex}>{idx + 1}</span>
                      <button
                        type="button"
                        className={styles.annexLink}
                        onClick={() => openUploadUrl(item.url).catch((error) => {
                          console.error('Error opening annex:', error)
                          notifyError('Erreur', "Impossible d'ouvrir le justificatif.")
                        })}
                      >
                        {item.label}
                      </button>
                      <button
                        type="button"
                        className={styles.annexOpen}
                        onClick={() => openUploadUrl(item.url).catch((error) => {
                          console.error('Error opening annex:', error)
                          notifyError('Erreur', "Impossible d'ouvrir le justificatif.")
                        })}
                      >
                        Ouvrir
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>
        </div>
      )}

      {showSuccessNotification && lastCreatedSortie && (
        <SortieFondsNotification
          requisition={lastCreatedSortie.requisition}
          sortie={lastCreatedSortie.sortie}
          userName={`${user?.prenom} ${user?.nom}`}
          onClose={() => {
            setShowSuccessNotification(false)
            // Retour à la liste seulement maintenant : cf. showsSuccessPanel dans
            // handleSubmit (naviguer plus tôt détruisait ce panneau).
            if (isCreatePage) navigate('/sorties-fonds')
          }}
          onPrintReceipt={
            lastCreatedSortie.pdfSortie
              ? () => {
                  generateSortieFondsPDF(lastCreatedSortie.pdfSortie, lastCreatedSortie.budgetLabel).catch(
                    (err: any) => {
                      console.error('Erreur impression bon de sortie:', err)
                      notifyError('Erreur', "Impossible de générer le bon de sortie.")
                    }
                  )
                }
              : undefined
          }
        />
      )}
    </div>
  )
}
