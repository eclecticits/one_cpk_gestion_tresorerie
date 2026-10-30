import { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { Requisition, Money, Service, CommissionMember } from '../types'
import type { BudgetPosteSummary } from '../types/budget'
import {
  annexerPiecesReunion,
  deleteRemboursementTransportBrouillon,
  deposerPieceRemboursement,
  deposerPieceReunion,
  listPiecesRemboursement,
  listRemboursementTransportBrouillons,
  loadDossierRemboursementsTransport,
  pieceReunionPath,
  pieceRemboursementPath,
  retirerPieceReunion,
  saveRemboursementTransportBrouillon,
  uploadRemboursementTransportPdf,
  type PieceReunion,
  type PieceReunionKind,
  type PiecesRemboursement,
  type RemboursementTransportBrouillon,
} from '../api/remboursementsTransport'
import ConvocationReunionModal from '../components/ConvocationReunionModal'
import ReunionPieces from '../components/ReunionPieces'
import { getServiceMembers, getServices } from '../api/services'
import { getPrintSettings, type PrintSettings } from '../api/settings'
import { toNumber } from '../utils/amount'
import { buildUploadUrl } from '../utils/uploads'
import type { BudgetDecisionLine } from '../utils/budgetDecision'
import BudgetDecisionTable from '../components/BudgetDecisionTable'
import { getStatusMeta } from '../utils/statusMapper'
import { endOfMonth, format, startOfMonth, subMonths } from 'date-fns'
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'action.
type PdfGeneratorRemboursementModule = typeof import('../utils/pdfGeneratorRemboursement')
let _pdfGeneratorRemboursementModulePromise: Promise<PdfGeneratorRemboursementModule> | null = null
function loadPdfGeneratorRemboursementModule(): Promise<PdfGeneratorRemboursementModule> {
  if (!_pdfGeneratorRemboursementModulePromise) _pdfGeneratorRemboursementModulePromise = import('../utils/pdfGeneratorRemboursement')
  return _pdfGeneratorRemboursementModulePromise
}
const generateRemboursementTransportPDF: PdfGeneratorRemboursementModule['generateRemboursementTransportPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorRemboursementModule()
  return mod.generateRemboursementTransportPDF(...args)
}
const generateListePresencePDF: PdfGeneratorRemboursementModule['generateListePresencePDF'] = async (...args) => {
  const mod = await loadPdfGeneratorRemboursementModule()
  return mod.generateListePresencePDF(...args)
}
import { numberToWords } from '../utils/numberToWords'
import { getTenantSlug } from '../utils/tenant'
import { useConfirm } from '../contexts/ConfirmContext'
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import { isAssistantMember, resolveMemberFunctionLabel, trierParHierarchie } from '../utils/serviceMemberFunctions'
import { ArrowDown, ArrowUp, CheckCircle2, Mail, Paperclip, Plus, Printer, RotateCcw, Search, SearchX, Send, Trash2, Users } from 'lucide-react'
import BackButton from '../components/BackButton'
import BudgetPosteSelect from '../components/BudgetPosteSelect'
import RowActionsMenu from '../components/RowActionsMenu'
import styles from './RemboursementTransport.module.css'

const TODAY = format(new Date(), 'yyyy-MM-dd')
// Ouverte depuis une unité organisationnelle, la liste couvre l'année en cours
// (1er janvier → aujourd'hui) plutôt que la seule journée du jour.
const START_OF_YEAR = `${TODAY.slice(0, 4)}-01-01`
// Vue globale : le mois en cours (1er → aujourd'hui).
const START_OF_MONTH = `${TODAY.slice(0, 7)}-01`
const MOIS_PRECEDENT = subMonths(new Date(), 1)

// Raccourcis de période, sur le modèle de la liste des réquisitions. Bornes
// vides = toute la période.
const PERIODES_RAPIDES: { cle: string; libelle: string; debut: string; fin: string }[] = [
  { cle: 'jour', libelle: "Aujourd'hui", debut: TODAY, fin: TODAY },
  { cle: 'mois', libelle: 'Ce mois', debut: START_OF_MONTH, fin: TODAY },
  {
    cle: 'mois-precedent',
    libelle: 'Mois précédent',
    debut: format(startOfMonth(MOIS_PRECEDENT), 'yyyy-MM-dd'),
    fin: format(endOfMonth(MOIS_PRECEDENT), 'yyyy-MM-dd'),
  },
  { cle: 'annee', libelle: 'Cette année', debut: START_OF_YEAR, fin: TODAY },
  { cle: 'tout', libelle: 'Tout', debut: '', fin: '' },
]

interface RemboursementTransport {
  id: string
  numero_remboursement: string
  pdf_path?: string | null
  instance: string
  type_reunion: 'bureau' | 'commission' | 'commission_ad_hoc' | 'conseil' | 'atelier'
  nature_reunion: string
  nature_travail: string[]
  lieu: string
  date_reunion: string
  heure_debut?: string
  heure_fin?: string
  montant_total: Money
  requisition_id?: string
  requisition?: Requisition
  service_id?: number | null
  service_code?: string | null
  service_libelle?: string | null
  created_at: string
  created_by: string
}

type DraftDossier = {
  id: string
  reference: string
  created_at: string
  description?: string | null
  status?: string
}

interface Participant {
  id?: string
  nom: string
  titre_fonction: string
  montant: Money
  type_participant: 'principal' | 'assistant'
  expert_comptable_id?: string
  // Coché d'après la liste de présence signée : un absent n'est pas remboursé.
  present?: boolean
  // Rang à l'impression : l'ordre des lignes du formulaire.
  ordre?: number | null
}

const isPresent = (p: Participant) => p.present !== false

// Déplace la ligne `index` d'un cran (delta = -1 vers le haut, +1 vers le bas).
function deplacer<T>(liste: T[], index: number, delta: number): T[] {
  const cible = index + delta
  if (cible < 0 || cible >= liste.length) return liste
  const copie = [...liste]
  ;[copie[index], copie[cible]] = [copie[cible], copie[index]]
  return copie
}

interface ExpertComptable {
  id: string
  numero_ordre: string
  nom_denomination: string
}

export default function RemboursementTransport() {
  const { user } = useAuth()
  const confirm = useConfirm()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const location = useLocation()
  const navigate = useNavigate()
  const [remboursements, setRemboursements] = useState<RemboursementTransport[]>([])
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [printSettings, setPrintSettings] = useState<PrintSettings | null>(null)
  const [rubriques, setRubriques] = useState<BudgetPosteSummary[]>([])
  const [isAutoFilling, setIsAutoFilling] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [submittingExamenId, setSubmittingExamenId] = useState<string | null>(null)
  const [selectedRemboursementIds, setSelectedRemboursementIds] = useState<string[]>([])
  const [draftDossiers, setDraftDossiers] = useState<DraftDossier[]>([])
  const [selectedDraftDossierId, setSelectedDraftDossierId] = useState('')

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])
  // Ordre des participants modifié dans la fiche, pas encore enregistré.
  const [ordreFicheModifie, setOrdreFicheModifie] = useState(false)
  const [ordreFicheEnCours, setOrdreFicheEnCours] = useState(false)
  const [selectedBudgetLines, setSelectedBudgetLines] = useState<BudgetDecisionLine[]>([])
  // Liste de présence et PV d'un remboursement déjà créé : null tant que non
  // chargés ou si la fiche n'a pas de réquisition à laquelle les joindre.
  const [selectedPieces, setSelectedPieces] = useState<PiecesRemboursement | null>(null)
  const detailsRequestRef = useRef(0)
  const [selectedRemboursementUsers, setSelectedRemboursementUsers] = useState<{
    demandeur?: { prenom: string; nom: string }
    validateur?: { prenom: string; nom: string }
    approbateur?: { prenom: string; nom: string }
  }>({})

  const tenantInstance = user?.organisation_slug || getTenantSlug() || ''
  const serviceParam = new URLSearchParams(location.search).get('service_id')
  const serviceStateIdRaw = (location.state as any)?.fromCommission
  const serviceStateId =
    serviceStateIdRaw !== undefined && serviceStateIdRaw !== null ? String(serviceStateIdRaw) : ''
  const serviceContextId = serviceParam || serviceStateId
  const [formData, setFormData] = useState({
    instance: tenantInstance,
    service_id: serviceContextId || '',
    budget_poste_id: '',
    type_reunion: 'bureau' as 'bureau' | 'commission' | 'commission_ad_hoc' | 'conseil' | 'atelier',
    nature_reunion: '',
    nature_travail: [''],
    lieu: '',
    date_reunion: format(new Date(), 'yyyy-MM-dd'),
    heure_debut: '',
    heure_fin: ''
  })

  const getTypeReunionLabel = (value?: string | null) => {
    switch (String(value || '')) {
      case 'bureau':
        return 'Réunion du Bureau'
      case 'commission':
        return 'Réunion de la Commission permanente'
      case 'commission_ad_hoc':
        return 'Réunion de la Commission ad hoc'
      case 'conseil':
        return 'Réunion du Conseil'
      case 'atelier':
        return 'Atelier / Séminaire / Formation'
      default:
        return value || 'N/A'
    }
  }

  const getMeetingPeriodLabel = (start?: string | null, end?: string | null) => {
    if (start && end) return `${start} – ${end}`
    if (start) return `à partir de ${start}`
    if (end) return `jusqu'à ${end}`
    return ''
  }

  const [participants, setParticipants] = useState<Participant[]>([
    { nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }
  ])

  const [assistants, setAssistants] = useState<Participant[]>([])
  const [showAssistants, setShowAssistants] = useState(false)
  // Brouillon repris ou enregistré : la création finale le supprime.
  const [draftId, setDraftId] = useState<string | null>(null)
  const [savingDraft, setSavingDraft] = useState(false)
  const [brouillons, setBrouillons] = useState<RemboursementTransportBrouillon[]>([])
  // Ce que le serveur ajoute au brouillon (convocation, pièces déposées) :
  // le formulaire ne le saisit pas, il l'affiche.
  const [draftServeur, setDraftServeur] = useState<Record<string, any>>({})
  const [convocationBrouillon, setConvocationBrouillon] = useState<RemboursementTransportBrouillon | null>(null)
  const [showExpertSearch, setShowExpertSearch] = useState<number | null>(null)
  const [showAssistantExpertSearch, setShowAssistantExpertSearch] = useState<number | null>(null)

  const [notification, setNotification] = useState<{
    show: boolean
    type: 'success' | 'error' | 'warning'
    message: string
  }>({ show: false, type: 'success', message: '' })

  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterServiceId, setFilterServiceId] = useState<string>(serviceContextId || '')
  const defaultDateDebut = serviceContextId ? START_OF_YEAR : START_OF_MONTH
  const [dateDebut, setDateDebut] = useState(defaultDateDebut)
  const [dateFin, setDateFin] = useState(TODAY)
  const remboursementsRequestRef = useRef(0)
  const filtresRemboursementsInitialisesRef = useRef(false)
  const [expertSearchCache, setExpertSearchCache] = useState<Record<string, ExpertComptable[]>>({})
  const [expertSearchLoading, setExpertSearchLoading] = useState(false)
  const [activeSearchTerm, setActiveSearchTerm] = useState('')
  const [expertSearchLoadingTerm, setExpertSearchLoadingTerm] = useState('')
  const searchDebounceRef = useRef<number | null>(null)

  const serviceIds = (user?.service_ids && user.service_ids.length > 0)
    ? user.service_ids
    : user?.service_id
      ? [user.service_id]
      : []
  const hasGlobalServiceAccess =
    hasPermission('can_view_all_services') ||
    hasPermission('can_view_reports') ||
    hasPermission('rapports')
  const isServiceUser =
    serviceIds.length > 0 &&
    user?.role !== 'admin' &&
    user?.role !== 'super_admin' &&
    !hasGlobalServiceAccess

  const selectableServices = isServiceUser
    ? services.filter((service) => serviceIds.includes(service.id))
    : services
  const defaultServiceId = (() => {
    if (serviceContextId) return serviceContextId
    if (isServiceUser && selectableServices.length === 1) return String(selectableServices[0].id)
    return ''
  })()
  const isServiceLockedByContext = Boolean(serviceContextId) || (isServiceUser && selectableServices.length === 1)

  const serviceLabel = (() => {
    if (!formData.service_id) return ''
    const serviceId = Number(formData.service_id)
    if (!Number.isFinite(serviceId)) return ''
    const service = services.find((s) => s.id === serviceId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${serviceId}`
  })()

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    let active = true
    getPrintSettings()
      .then((settings) => {
        if (active) setPrintSettings(settings)
      })
      .catch(() => {
        if (active) setPrintSettings(null)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (defaultServiceId && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: defaultServiceId }))
    }
  }, [defaultServiceId, formData.service_id])

  const clearNewParam = () => {
    const params = new URLSearchParams(location.search)
    if (!params.has('new')) return
    params.delete('new')
    const nextSearch = params.toString()
    navigate(
      { pathname: location.pathname, search: nextSearch ? `?${nextSearch}` : '' },
      { replace: true, state: location.state }
    )
  }

  const openNewForm = () => {
    const params = new URLSearchParams(location.search)
    params.set('new', '1')
    if (serviceContextId) params.set('service_id', serviceContextId)
    navigate(
      { pathname: location.pathname, search: `?${params.toString()}` },
      { state: location.state }
    )
  }

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    setShowForm(params.get('new') === '1')
  }, [location.search])

  useEffect(() => {
    if (tenantInstance && formData.instance !== tenantInstance) {
      setFormData((prev) => ({ ...prev, instance: tenantInstance }))
    }
  }, [tenantInstance, formData.instance])

  useEffect(() => {
    if (serviceContextId && formData.service_id !== serviceContextId) {
      setFormData((prev) => ({ ...prev, service_id: serviceContextId }))
    }
  }, [serviceContextId, formData.service_id])

  useEffect(() => {
    if (serviceContextId && filterServiceId !== serviceContextId) {
      setFilterServiceId(serviceContextId)
    }
  }, [serviceContextId, filterServiceId])

  // La page reste montée quand on passe d'une unité à la vue globale (ou
  // l'inverse) : la borne de début suit alors le nouveau défaut.
  const previousServiceContextRef = useRef(serviceContextId)
  useEffect(() => {
    if (previousServiceContextRef.current === serviceContextId) return
    previousServiceContextRef.current = serviceContextId
    setDateDebut(defaultDateDebut)
  }, [serviceContextId, defaultDateDebut])

  const canAutofillParticipants = () => {
    const participantsEmpty = participants.every(
      (p) =>
        !p.nom.trim() &&
        !p.titre_fonction.trim() &&
        (toNumber(p.montant) || 0) === 0 &&
        !p.expert_comptable_id
    )
    const assistantsEmpty = assistants.length === 0 ||
      assistants.every(
        (a) =>
          !a.nom.trim() &&
          !a.titre_fonction.trim() &&
          (toNumber(a.montant) || 0) === 0 &&
          !a.expert_comptable_id
      )
    return participantsEmpty && assistantsEmpty
  }

  const buildParticipantFromMember = (member: CommissionMember, type: 'principal' | 'assistant'): Participant => {
    const nameFromUser = `${member.user?.prenom || ''} ${member.user?.nom || ''}`.trim()
    const fallbackName = member.email || member.matricule || ''
    const fullName = (member.full_name || '').trim() || nameFromUser || fallbackName
    return {
      nom: fullName,
      titre_fonction: (member.custom_title || '').trim() || resolveMemberFunctionLabel(member),
      montant: 0,
      type_participant: type,
    }
  }

  useEffect(() => {
    const fetchMembers = async () => {
      if (!showForm) return
      if (!formData.service_id) return
      if (isAutoFilling) return
      if (!canAutofillParticipants()) return
      const serviceId = Number(formData.service_id)
      if (!Number.isFinite(serviceId)) return
      try {
        setIsAutoFilling(true)
        const members = await getServiceMembers(serviceId)
        const principals = trierParHierarchie(
          members
            .filter((m) => !isAssistantMember(m))
            .map((m) => buildParticipantFromMember(m, 'principal'))
            .filter((p) => p.nom.trim())
        )
        const assistantsList = members
          .filter((m) => isAssistantMember(m))
          .map((m) => buildParticipantFromMember(m, 'assistant'))
          .filter((p) => p.nom.trim())
        if (participants.length === 0 || participants.every((p) => !p.nom.trim() && !p.titre_fonction.trim())) {
          setParticipants(
            principals.length > 0
              ? principals
              : [{ nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }]
          )
        }
        if (assistants.length === 0 || assistants.every((a) => !a.nom.trim() && !a.titre_fonction.trim())) {
          setAssistants(assistantsList)
          setShowAssistants(assistantsList.length > 0)
        }
      } catch (error) {
        console.error('Erreur lors du pré-remplissage des membres', error)
      } finally {
        setIsAutoFilling(false)
      }
    }
    fetchMembers()
  }, [showForm, formData.service_id])

  const chargerRemboursements = async () => {
    const requestId = ++remboursementsRequestRef.current
    const pageSize = 200
    let offset = 0
    const tous: RemboursementTransport[] = []

    // L'API limite volontairement une page à 200 lignes. Parcourir toutes les
    // pages de la période évite qu'une vue annuelle de service soit tronquée
    // silencieusement aux 200 opérations les plus récentes.
    for (;;) {
      const page: any = await apiRequest('GET', '/remboursements-transport', {
        params: {
          include: 'requisition',
          service_id: filterServiceId || undefined,
          date_debut: dateDebut || undefined,
          date_fin: dateFin || undefined,
          limit: pageSize,
          offset,
        },
      })
      if (requestId !== remboursementsRequestRef.current) return
      const items = Array.isArray(page) ? page : page?.items ?? page?.data ?? []
      tous.push(...items)
      if (items.length < pageSize) break
      offset += pageSize
    }
    if (requestId === remboursementsRequestRef.current) setRemboursements(tous)
  }

  const loadData = async () => {
    try {
      const [, expertsRes, servicesRes] = await Promise.all([
        chargerRemboursements(),
        apiRequest('GET', '/experts-comptables', { params: { active: true, limit: 200, offset: 0 } }),
        getServices({ active: true }),
      ])

      const exp = Array.isArray(expertsRes) ? expertsRes : (expertsRes as any)?.items ?? (expertsRes as any)?.data ?? []

      setExperts(exp as any)
      setServices(Array.isArray(servicesRes) ? servicesRes : [])
      try {
        const draftDossiersRes: any = await apiRequest('GET', '/dossiers/drafts', { params: { limit: 200 } })
        const drafts = Array.isArray(draftDossiersRes) ? draftDossiersRes : (draftDossiersRes as any)?.items ?? []
        setDraftDossiers(drafts as DraftDossier[])
      } catch (draftError) {
        console.error('Error loading draft dossiers:', draftError)
        setDraftDossiers([])
      }
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!filtresRemboursementsInitialisesRef.current) {
      filtresRemboursementsInitialisesRef.current = true
      return
    }
    chargerRemboursements().catch((error) => {
      console.error('Error loading filtered reimbursements:', error)
      setNotification({
        show: true,
        type: 'error',
        message: 'Impossible de charger tous les remboursements de la période.',
      })
    })
    // `chargerRemboursements` lit précisément ces trois filtres. Le garder
    // local évite de recréer toute la fonction de chargement avec useCallback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterServiceId, dateDebut, dateFin])

  useEffect(() => {
    const loadRubriques = async () => {
      const effectiveServiceId = formData.service_id || defaultServiceId
      if (!effectiveServiceId) {
        setRubriques([])
        return
      }
      try {
        const serviceId = Number(effectiveServiceId)
        const rubriquesRes = await apiRequest('GET', '/budget/lines/autorisees', {
          params: {
            active: true,
            type: 'DEPENSE',
            service_id: Number.isFinite(serviceId) ? serviceId : undefined,
          },
        })
        const postes = (rubriquesRes as any)?.lignes ?? []
        setRubriques(Array.isArray(postes) ? postes : [])
      } catch (error) {
        console.error('Error loading budget postes:', error)
        setRubriques([])
      }
    }
    loadRubriques()
  }, [formData.service_id, defaultServiceId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)

    try {
      if (!formData.service_id) {
        setNotification({
          show: true,
          type: 'error',
          message: 'Veuillez sélectionner une commission / service.'
        })
        setSubmitting(false)
        return
      }
      if (!formData.budget_poste_id) {
        setNotification({
          show: true,
          type: 'error',
          message: 'Veuillez sélectionner un poste budgétaire.'
        })
        setSubmitting(false)
        return
      }
      if (!participants.some((p) => p.nom.trim() !== '' && isPresent(p))) {
        setNotification({
          show: true,
          type: 'error',
          message: 'Aucun participant marqué présent : cochez au moins un présent.'
        })
        setSubmitting(false)
        return
      }
      // Recommandée, pas exigée : on prévient, l'utilisateur décide.
      if (!draftServeur?.pieces?.liste_presence) {
        const continuer = await confirm({
          title: 'Liste de présence signée absente',
          description:
            'Aucune liste de présence signée n\u2019est jointe. Elle justifie les présents auprès des validateurs. Créer quand même le remboursement ?',
          confirmText: 'Créer sans la liste',
          cancelText: 'Revenir pour la déposer',
        })
        if (!continuer) {
          setSubmitting(false)
          return
        }
      }
      const periodeReunion = getMeetingPeriodLabel(formData.heure_debut, formData.heure_fin)
      const objetRequisition = [
        'Remboursement des frais de transport des participants',
        getTypeReunionLabel(formData.type_reunion),
        formData.nature_reunion,
        `${format(new Date(formData.date_reunion), 'dd/MM/yyyy')}${periodeReunion ? `, ${periodeReunion}` : ''}`,
        formData.lieu,
      ].filter(Boolean).join(' — ')

      const selectedRubrique = rubriques.find((r) => String(r.id) === String(formData.budget_poste_id))
      const rubriqueLabel = selectedRubrique ? `${selectedRubrique.code} - ${selectedRubrique.libelle}` : 'Remboursement transport'
      const total = calculateTotal()

      // Réquisition et ligne dans le même appel : si la ligne est refusée, rien
      // n'est enregistré (pas de réquisition vide à rejeter ensuite).
      const requisitionData: any = await apiRequest('POST', '/requisitions', {
        objet: objetRequisition,
        type_requisition: 'remboursement_transport',
        mode_paiement: 'cash',
        montant_total: total,
        service_id: Number(formData.service_id),
        created_by: user?.id,
        statut: 'BROUILLON',
        lignes: [
          {
            budget_poste_id: Number(formData.budget_poste_id),
            rubrique: rubriqueLabel,
            description: objetRequisition,
            quantite: 1,
            montant_unitaire: total,
            montant_total: total,
            devise: 'USD',
          }
        ],
      })

      const remboursementInsert: any = {
        instance: formData.instance,
        type_reunion: formData.type_reunion,
        nature_reunion: formData.nature_reunion,
        nature_travail: formData.nature_travail.filter(n => n.trim() !== ''),
        lieu: formData.lieu,
        date_reunion: formData.date_reunion,
        heure_debut: formData.heure_debut || null,
        heure_fin: formData.heure_fin || null,
        montant_total: calculateTotal(),
        requisition_id: requisitionData.id,
        created_by: user?.id
      }

      const remboursementData: any = await apiRequest('POST', '/remboursements-transport', remboursementInsert)

      // L'ordre des lignes du formulaire est celui du PDF.
      const allParticipants = [
        ...participants.filter(p => p.nom.trim() !== '' && isPresent(p)),
        ...assistants.filter(p => p.nom.trim() !== '' && isPresent(p))
      ].map((p, index) => ({ ...p, ordre: index + 1 }))

      if (allParticipants.length > 0) {
        await apiRequest('POST', '/participants-transport', allParticipants.map(p => ({
          remboursement_id: remboursementData.id,
          nom: p.nom,
          titre_fonction: p.titre_fonction,
          montant: p.montant,
          type_participant: p.type_participant,
          expert_comptable_id: p.expert_comptable_id || null,
          ordre: p.ordre,
        })))
      }

      // Les pièces déposées sur le brouillon deviennent annexes de la
      // réquisition. En cas d'échec, le brouillon est gardé : ses pièces
      // restent disponibles pour être jointes à la main.
      let piecesJointes = true
      if (draftId && Object.keys(draftServeur?.pieces || {}).length) {
        try {
          await annexerPiecesReunion(draftId, requisitionData.id)
        } catch (annexeError) {
          console.error('Pièces de réunion non annexées', annexeError)
          piecesJointes = false
        }
      }
      const finaliserBrouillon = async () => {
        if (piecesJointes) await discardDraftAfterCreation()
      }

      try {
        const selectedService = services.find((service) => String(service.id) === String(formData.service_id))
        const remboursementForPdf = {
          ...remboursementData,
          service_id: remboursementData.service_id ?? (formData.service_id ? Number(formData.service_id) : null),
          service_code: remboursementData.service_code || selectedService?.code || null,
          service_libelle: remboursementData.service_libelle || selectedService?.libelle || null,
        }
        const pdfBlob = await generateRemboursementTransportPDF(
          remboursementForPdf,
          allParticipants,
          'blob',
          `${user?.prenom} ${user?.nom}`,
          'a4',
        )
        if (pdfBlob) {
          const rawNumber = remboursementForPdf.reference_numero || remboursementForPdf.numero_remboursement || 'remboursement_transport'
          const safeNumber = String(rawNumber).trim().replace(/[\\/:*?"<>|]+/g, '-')
          await uploadRemboursementTransportPdf(remboursementData.id, pdfBlob, `${safeNumber}.pdf`)
        }
      } catch (pdfError) {
        console.error('Error generating remboursement PDF after creation:', pdfError)
        setNotification({
          show: true,
          type: 'warning',
          message: `Remboursement ${remboursementData.numero_remboursement} créé, mais le PDF officiel n'a pas pu être généré automatiquement.`,
        })
        await finaliserBrouillon()
        clearNewParam()
        setShowForm(false)
        resetForm()
        loadData()
        return
      }

      await finaliserBrouillon()
      setNotification(
        piecesJointes
          ? {
              show: true,
              type: 'success',
              message: `Remboursement ${remboursementData.numero_remboursement} créé avec succès. Il doit être signé puis soumis à l'examen.`,
            }
          : {
              show: true,
              type: 'warning',
              message: `Remboursement ${remboursementData.numero_remboursement} créé, mais la liste de présence n'a pas pu être jointe. Le brouillon est conservé : joignez-la depuis le remboursement.`,
            },
      )
      clearNewParam()
      setShowForm(false)
      resetForm()
      loadData()
    } catch (error: any) {
      console.error('Error creating remboursement:', error)
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Erreur lors de la création du remboursement'
      })
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
    setFormData({
      instance: tenantInstance,
      service_id: defaultServiceId,
      budget_poste_id: '',
      type_reunion: 'bureau',
      nature_reunion: '',
      nature_travail: [''],
      lieu: '',
      date_reunion: format(new Date(), 'yyyy-MM-dd'),
      heure_debut: '',
      heure_fin: ''
    })
    setParticipants([{ nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }])
    setAssistants([])
    setShowAssistants(false)
    setDraftId(null)
    setDraftServeur({})
  }

  // --- Brouillons -------------------------------------------------------
  const loadBrouillons = async () => {
    try {
      const res = await listRemboursementTransportBrouillons(serviceContextId || null)
      setBrouillons(Array.isArray(res) ? res : [])
    } catch {
      setBrouillons([])
    }
  }

  useEffect(() => {
    loadBrouillons()
  }, [serviceContextId])

  // Enregistre le formulaire dans le brouillon (le crée au besoin) et le
  // renvoie ; null si le service manque ou si l'enregistrement échoue.
  const persistDraft = async (): Promise<RemboursementTransportBrouillon | null> => {
    const serviceId = Number(formData.service_id)
    if (!formData.service_id || !Number.isFinite(serviceId)) {
      setNotification({ show: true, type: 'error', message: 'Choisissez la commission / le service avant d\u2019enregistrer le brouillon.' })
      return null
    }
    setSavingDraft(true)
    try {
      const saved = await saveRemboursementTransportBrouillon(draftId, serviceId, {
        formData,
        participants,
        assistants,
        showAssistants,
      })
      setDraftId(saved.id)
      setDraftServeur(saved.contenu || {})
      loadBrouillons()
      return saved
    } catch (error: any) {
      setNotification({ show: true, type: 'error', message: error?.message || 'Enregistrement du brouillon impossible.' })
      return null
    } finally {
      setSavingDraft(false)
    }
  }

  const saveDraft = async () => {
    if (await persistDraft()) {
      setNotification({
        show: true,
        type: 'success',
        message: 'Brouillon enregistré. Vous pourrez le reprendre après la réunion pour cocher les présents et saisir les montants.',
      })
    }
  }

  // La convocation part de ce qui est enregistré : on enregistre d'abord.
  const convoquerDepuisFormulaire = async () => {
    const saved = await persistDraft()
    if (saved) setConvocationBrouillon(saved)
  }

  const openDraft = (brouillon: RemboursementTransportBrouillon) => {
    const contenu = brouillon.contenu || {}
    const saved = contenu.formData || {}
    setFormData({
      instance: tenantInstance,
      service_id: String(brouillon.service_id),
      budget_poste_id: saved.budget_poste_id || '',
      type_reunion: saved.type_reunion || 'bureau',
      nature_reunion: saved.nature_reunion || '',
      nature_travail: Array.isArray(saved.nature_travail) && saved.nature_travail.length ? saved.nature_travail : [''],
      lieu: saved.lieu || '',
      date_reunion: saved.date_reunion || format(new Date(), 'yyyy-MM-dd'),
      heure_debut: saved.heure_debut || '',
      heure_fin: saved.heure_fin || '',
    })
    const savedParticipants: Participant[] = Array.isArray(contenu.participants) ? contenu.participants : []
    const savedAssistants: Participant[] = Array.isArray(contenu.assistants) ? contenu.assistants : []
    setParticipants(
      savedParticipants.length
        ? savedParticipants
        : [{ nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }]
    )
    setAssistants(savedAssistants)
    setShowAssistants(Boolean(contenu.showAssistants) || savedAssistants.length > 0)
    setDraftId(brouillon.id)
    setDraftServeur(contenu)
    setShowForm(true)
    const params = new URLSearchParams(location.search)
    params.set('new', '1')
    params.set('service_id', String(brouillon.service_id))
    navigate({ pathname: location.pathname, search: `?${params.toString()}` }, { replace: true, state: location.state })
  }

  const removeDraft = async (brouillon: RemboursementTransportBrouillon) => {
    const ok = await confirm({
      title: 'Supprimer le brouillon',
      description: 'Ce brouillon de remboursement sera supprimé. Aucun remboursement ni réquisition n\u2019a encore été créé.',
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await deleteRemboursementTransportBrouillon(brouillon.id)
      if (draftId === brouillon.id) {
        setDraftId(null)
        setDraftServeur({})
      }
      if (convocationBrouillon?.id === brouillon.id) setConvocationBrouillon(null)
      loadBrouillons()
    } catch (error: any) {
      setNotification({ show: true, type: 'error', message: error?.message || 'Suppression du brouillon impossible.' })
    }
  }

  // La création finale remplace le brouillon : on le retire pour qu'il ne
  // soit pas repris une seconde fois.
  const discardDraftAfterCreation = async () => {
    if (!draftId) return
    try {
      await deleteRemboursementTransportBrouillon(draftId)
    } catch (error) {
      console.error('Brouillon non supprimé après création', error)
    }
    setDraftId(null)
    loadBrouillons()
  }

  const serviceInfo = (serviceId: string | number) => {
    const service = services.find((s) => String(s.id) === String(serviceId))
    return { service_code: service?.code || null, service_libelle: service?.libelle || null }
  }

  const printListePresence = async (source?: RemboursementTransportBrouillon) => {
    const contenu = source?.contenu
    const data = contenu?.formData || formData
    const people: Participant[] = source
      ? [...(contenu?.participants || []), ...(contenu?.assistants || [])]
      : [...participants, ...assistants]
    try {
      await generateListePresencePDF(
        {
          ...(source
            ? { service_code: source.service_code, service_libelle: source.service_libelle }
            : serviceInfo(formData.service_id)),
          instance: tenantInstance,
          type_reunion: data.type_reunion,
          nature_reunion: data.nature_reunion,
          nature_travail: data.nature_travail,
          lieu: data.lieu,
          date_reunion: data.date_reunion,
          heure_debut: data.heure_debut,
          heure_fin: data.heure_fin,
        },
        people
          .filter((p) => String(p?.nom || '').trim())
          .map((p) => ({ nom: p.nom, titre_fonction: p.titre_fonction, type_participant: p.type_participant })),
      )
    } catch (error) {
      console.error('Liste de présence', error)
      setNotification({ show: true, type: 'error', message: 'Impression de la liste de présence impossible.' })
    }
  }

  const addNatureTravail = () => {
    setFormData({ ...formData, nature_travail: [...formData.nature_travail, ''] })
  }

  const removeNatureTravail = (index: number) => {
    const newNature = formData.nature_travail.filter((_, i) => i !== index)
    setFormData({ ...formData, nature_travail: newNature })
  }

  const updateNatureTravail = (index: number, value: string) => {
    const newNature = [...formData.nature_travail]
    newNature[index] = value
    setFormData({ ...formData, nature_travail: newNature })
  }

  const addParticipant = () => {
    setParticipants([...participants, { nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }])
  }

  const removeParticipant = (index: number) => {
    setParticipants(participants.filter((_, i) => i !== index))
  }

  const updateParticipant = (index: number, field: keyof Participant, value: any) => {
    const newParticipants = [...participants]
    newParticipants[index] = { ...newParticipants[index], [field]: value }
    setParticipants(newParticipants)
  }

  const moveParticipant = (index: number, delta: number) => {
    setParticipants((prev) => deplacer(prev, index, delta))
  }

  const moveAssistant = (index: number, delta: number) => {
    setAssistants((prev) => deplacer(prev, index, delta))
  }

  const renderMoveButtons = (index: number, total: number, onMove: (index: number, delta: number) => void, nom: string) => (
    <>
      <button
        type="button"
        onClick={() => onMove(index, -1)}
        className={styles.moveBtn}
        disabled={index === 0}
        title="Monter"
        aria-label={`Monter ${nom || 'la ligne'}`}
      >
        <ArrowUp size={15} aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={() => onMove(index, 1)}
        className={styles.moveBtn}
        disabled={index === total - 1}
        title="Descendre"
        aria-label={`Descendre ${nom || 'la ligne'}`}
      >
        <ArrowDown size={15} aria-hidden="true" />
      </button>
    </>
  )

  const addAssistant = () => {
    setAssistants([...assistants, { nom: '', titre_fonction: '', montant: 0, type_participant: 'assistant' }])
  }

  const removeAssistant = (index: number) => {
    setAssistants(assistants.filter((_, i) => i !== index))
  }

  const updateAssistant = (index: number, field: keyof Participant, value: any) => {
    const newAssistants = [...assistants]
    newAssistants[index] = { ...newAssistants[index], [field]: value }
    setAssistants(newAssistants)
  }

  const selectExpert = (participantIndex: number, expert: ExpertComptable) => {
    const newParticipants = [...participants]
    newParticipants[participantIndex] = {
      ...newParticipants[participantIndex],
      nom: expert.nom_denomination,
      expert_comptable_id: expert.id
    }
    setParticipants(newParticipants)
    setShowExpertSearch(null)
  }

  const selectAssistantExpert = (assistantIndex: number, expert: ExpertComptable) => {
    const newAssistants = [...assistants]
    newAssistants[assistantIndex] = {
      ...newAssistants[assistantIndex],
      nom: expert.nom_denomination,
      expert_comptable_id: expert.id
    }
    setAssistants(newAssistants)
    setShowAssistantExpertSearch(null)
  }

  useEffect(() => {
    return () => {
      if (searchDebounceRef.current) {
        window.clearTimeout(searchDebounceRef.current)
      }
    }
  }, [])

  const renderExpertDropdown = (
    searchValue: string,
    onSelect: (expert: ExpertComptable) => void
  ) => {
    const filteredExperts = getFilteredExperts(searchValue)
    const loadingExperts = isLoadingExperts(searchValue)
    return (
      <div className={styles.expertDropdown}>
        <div className={styles.expertDropdownHeader}>
          {loadingExperts ? 'Recherche en cours...' : `${filteredExperts.length} expert(s) disponible(s)`}
          {!loadingExperts &&
            expertSearchLoading &&
            normalizeSearchTerm(activeSearchTerm) === normalizeSearchTerm(searchValue) &&
            !expertSearchCache[normalizeSearchTerm(searchValue)]
            ? ' (recherche...)'
            : ''}
        </div>
        <div className={styles.expertDropdownList}>
          {filteredExperts.slice(0, 25).map(expert => (
            <div
              key={expert.id}
              onMouseDown={(e) => {
                e.preventDefault()
                onSelect(expert)
              }}
              className={styles.expertDropdownItem}
            >
              <div className={styles.expertDropdownNumero}>{expert.numero_ordre}</div>
              <div className={styles.expertDropdownName}>{expert.nom_denomination}</div>
            </div>
          ))}
        </div>
        {filteredExperts.length === 0 && (
          <div className={styles.expertDropdownEmpty}>
            {searchValue.trim() ? (
              <>
                <div className={styles.expertDropdownEmptyIcon}><SearchX size={22} aria-hidden="true" /></div>
                <div className={styles.expertDropdownEmptyTitle}>Aucun expert trouvé</div>
                <div className={styles.expertDropdownEmptySubtitle}>pour "{searchValue}"</div>
              </>
            ) : (
              <>
                <div className={styles.expertDropdownEmptyIcon}><Users size={22} aria-hidden="true" /></div>
                <div className={styles.expertDropdownEmptyTitle}>{experts.length} experts disponibles</div>
                <div className={styles.expertDropdownEmptySubtitle}>Tapez pour rechercher</div>
              </>
            )}
          </div>
        )}
        {filteredExperts.length > 25 && (
          <div className={styles.expertDropdownFooter}>
            +{filteredExperts.length - 25} autres résultats
            <div className={styles.expertDropdownFooterHint}>Affinez votre recherche pour voir plus</div>
          </div>
        )}
      </div>
    )
  }

  const normalizeSearchTerm = (value: string) => value.trim().toLowerCase()

  const fetchExpertsBySearch = async (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized || expertSearchCache[normalized]) return
    setExpertSearchLoading(true)
    setExpertSearchLoadingTerm(normalized)
    try {
      const res: any = await apiRequest('GET', '/experts-comptables', {
        params: {
          q: searchTerm.trim(),
          active: true,
          limit: 200,
          offset: 0,
          order: 'nom_denomination.asc',
        },
      })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setExpertSearchCache((prev) => ({ ...prev, [normalized]: items as any }))
    } catch (error) {
      console.error('Error searching experts:', error)
    } finally {
      setExpertSearchLoading(false)
      setExpertSearchLoadingTerm((prev) => (prev === normalized ? '' : prev))
    }
  }

  const queueExpertSearch = (searchTerm: string) => {
    setActiveSearchTerm(searchTerm)
    if (searchDebounceRef.current) {
      window.clearTimeout(searchDebounceRef.current)
    }
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized) return
    searchDebounceRef.current = window.setTimeout(() => {
      fetchExpertsBySearch(searchTerm)
    }, 150)
  }

  const getFilteredExperts = (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized) return experts
    const local = experts.filter(e =>
      e.nom_denomination.toLowerCase().includes(normalized) ||
      e.numero_ordre.toLowerCase().includes(normalized)
    )
    if (local.length > 0) return local
    if (expertSearchCache[normalized]) return expertSearchCache[normalized]
    return []
  }

  const isLoadingExperts = (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    return !!normalized && expertSearchLoadingTerm === normalized && !expertSearchCache[normalized]
  }

  const calculateTotal = () => {
    const participantsTotal = participants.filter(isPresent).reduce((sum, p) => sum + (toNumber(p.montant) || 0), 0)
    const assistantsTotal = assistants.filter(isPresent).reduce((sum, p) => sum + (toNumber(p.montant) || 0), 0)
    return participantsTotal + assistantsTotal
  }

  // L'aperçu suit l'ordre des lignes du formulaire, comme le PDF.
  const previewParticipants = [...participants, ...assistants].filter(
    (p) => isPresent(p) && (p.nom.trim() !== '' || p.titre_fonction.trim() !== '')
  )
  const previewTotal = calculateTotal()
  const previewMontantLettres = numberToWords(previewTotal)
  const previewTravaux = formData.nature_travail.map((item) => item.trim()).filter(Boolean)
  const previewHoraires = getMeetingPeriodLabel(formData.heure_debut, formData.heure_fin) || 'Non renseigné'
  const previewLogoUrl = printSettings?.show_header_logo === false
    ? ''
    : printSettings?.logo_url
      ? buildUploadUrl(printSettings.logo_url)
      : '/imge_onec.png'

  const printRemboursement = async (remboursement: RemboursementTransport) => {
    try {
      const participantsRes: any = await apiRequest('GET', '/participants-transport', { params: { remboursement_id: remboursement.id, limit: 500 } })
      const participantsData = Array.isArray(participantsRes) ? participantsRes : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []
      const handleUpload = async (blob: Blob, filename: string) => {
        try {
          await uploadRemboursementTransportPdf(remboursement.id, blob, filename)
        } catch (error) {
          console.error('Error uploading remboursement PDF:', error)
        }
      }

      const serviceId = getRemboursementServiceId(remboursement)
      const service = services.find((item) => String(item.id) === String(serviceId))
      const remboursementForPdf = {
        ...remboursement,
        service_id: remboursement.service_id ?? (serviceId ? Number(serviceId) : null),
        service_code: remboursement.service_code || service?.code || null,
        service_libelle: remboursement.service_libelle || service?.libelle || null,
      }

      await generateRemboursementTransportPDF(
        remboursementForPdf,
        participantsData || [],
        'print',
        `${user?.prenom} ${user?.nom}`,
        'a4',
        handleUpload
      )
    } catch (error) {
      console.error('Error printing PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        message: 'Erreur lors de l\'impression du PDF'
      })
    }
  }

  // Dans la fiche, un participant ne change de place qu'avec un voisin du même
  // type : les assistants restent imprimés après les participants principaux.
  const peutDeplacerFiche = (index: number, delta: number) => {
    const voisin = selectedParticipants[index + delta]
    return Boolean(voisin) && voisin.type_participant === selectedParticipants[index].type_participant
  }

  const deplacerFiche = (index: number, delta: number) => {
    if (!peutDeplacerFiche(index, delta)) return
    setSelectedParticipants((prev) => deplacer(prev, index, delta))
    setOrdreFicheModifie(true)
  }

  const enregistrerOrdreFiche = async () => {
    if (!selectedRemboursementDetails) return
    setOrdreFicheEnCours(true)
    try {
      const res: any = await apiRequest(
        'PUT',
        `/remboursements-transport/${selectedRemboursementDetails.id}/participants/ordre`,
        { participant_ids: selectedParticipants.map((p) => p.id) },
      )
      const ordonnes = Array.isArray(res) ? res : selectedParticipants
      setSelectedParticipants(ordonnes)
      setOrdreFicheModifie(false)
      // Le serveur vient de régénérer sa version sommaire du PDF : on la
      // remplace aussitôt par l'état de frais mis en page, comme à la création.
      const blob = await generateRemboursementTransportPDF(selectedRemboursementDetails, ordonnes, 'blob', undefined, 'a4')
      if (blob) {
        const ref = (selectedRemboursementDetails as any).reference_numero || selectedRemboursementDetails.numero_remboursement || 'remboursement_transport'
        await uploadRemboursementTransportPdf(selectedRemboursementDetails.id, blob, `${String(ref).trim().replace(/[\\/:*?"<>|]+/g, '-')}.pdf`)
      }
      setNotification({ show: true, type: 'success', message: 'Ordre enregistré : le PDF a été régénéré.' })
    } catch (error: any) {
      console.error('Error saving participants order:', error)
      setNotification({ show: true, type: 'error', message: error?.message || "Impossible d'enregistrer l'ordre." })
    } finally {
      setOrdreFicheEnCours(false)
    }
  }

  const viewDetails = async (remboursement: RemboursementTransport) => {
    const requestId = ++detailsRequestRef.current
    setSelectedRemboursementDetails(remboursement)
    setSelectedPieces(null)
    const peutJoindrePieces =
      (hasPermission('remboursement_transport') || hasPermission('menu_services')) &&
      Boolean(remboursement.requisition?.id || remboursement.requisition_id)
    if (peutJoindrePieces) {
      listPiecesRemboursement(remboursement.id)
        .then((pieces) => {
          if (requestId === detailsRequestRef.current) setSelectedPieces(pieces)
        })
        .catch((error) => {
          if (requestId !== detailsRequestRef.current) return
          console.error('Error loading meeting documents:', error)
          setNotification({ show: true, type: 'error', message: 'Impossible de charger les pièces de la réunion.' })
        })
    }
    try {
      const participantsRes: any = await apiRequest('GET', '/participants-transport', { params: { remboursement_id: remboursement.id, limit: 500 } })
      if (requestId !== detailsRequestRef.current) return
      const participantsData = Array.isArray(participantsRes) ? participantsRes : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []
      setSelectedParticipants(participantsData || [])
      setOrdreFicheModifie(false)

      const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
      if (requisitionId) {
        const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisitionId } })
        if (requestId !== detailsRequestRef.current) return
        const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
        setSelectedBudgetLines(lignesData || [])
      } else {
        setSelectedBudgetLines([])
      }

      const users: any = {}
      if ((remboursement as any).requisition?.demandeur) users.demandeur = (remboursement as any).requisition.demandeur
      if ((remboursement as any).requisition?.validateur) users.validateur = (remboursement as any).requisition.validateur
      if ((remboursement as any).requisition?.approbateur) users.approbateur = (remboursement as any).requisition.approbateur

      setSelectedRemboursementUsers(users)
      setShowDetailModal(true)
    } catch (error: any) {
      if (requestId !== detailsRequestRef.current) return
      console.error('Error loading remboursement details:', error)
      setNotification({
        show: true,
        type: 'error',
        message: 'Erreur lors du chargement des détails. Veuillez réessayer.'
      })
    }
  }

  const normalizeStatus = (raw?: string | null) => {
    const upper = String(raw || '').toUpperCase()
    if (upper === 'BROUILLON') return 'BROUILLON'
    if (upper === 'SIGNEE_SERVICE') return 'SIGNEE_SERVICE'
    if (upper === 'EN_ATTENTE' || upper === 'A_VALIDER') return 'EN_ATTENTE'
    if (upper === 'AUTORISEE' || upper === 'VALIDEE') return 'AUTORISEE'
    if (upper === 'APPROUVEE') return 'APPROUVEE'
    if (upper === 'PAYEE') return 'PAYEE'
    if (upper === 'REJETEE') return 'REJETEE'
    return upper
  }

  const canSignRequisition = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const hasLines = requisition?.lignes_count == null ? true : Number(requisition.lignes_count) > 0
    return Boolean(requisition?.id) && Boolean(requisition?.service_id) && status === 'BROUILLON' && hasLines
  }

  const canSubmitToExamen = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    const hasEligibleExamenStatus = examenStatus === 'NON_EXAMINE' || examenStatus === 'REJETE'
    const hasLines = requisition?.lignes_count == null ? true : Number(requisition.lignes_count) > 0
    return (
      Boolean(requisition?.id) &&
      !requisition?.dossier_id &&
      Boolean(requisition?.service_id) &&
      status === 'SIGNEE_SERVICE' &&
      hasEligibleExamenStatus &&
      Boolean(requisition?.signed_by_id) &&
      Boolean(requisition?.signed_at) &&
      hasLines
    )
  }

  const getSubmitExamenLabel = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    if (!requisition?.id && !remboursement.requisition_id) return 'Réquisition manquante'
    if (requisition?.dossier_id) return 'Dans dossier'
    if (examenStatus === 'EN_EXAMEN') return 'Déjà soumis'
    if (examenStatus === 'EXAMINE') return 'Examiné'
    if (status === 'BROUILLON') return "Signer d'abord"
    if (status !== 'SIGNEE_SERVICE') return 'Non disponible'
    if (!requisition?.signed_by_id) return 'Signature requise'
    if (!requisition?.signed_at) return 'Date de signature requise'
    if (requisition?.lignes_count != null && Number(requisition.lignes_count) <= 0) return 'Aucune ligne'
    if (examenStatus === 'REJETE') return 'Resoumettre'
    return 'Soumettre'
  }

  const canSelectForDossier = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const requisitionId = requisition?.id || remboursement.requisition_id
    if (!requisitionId) return false
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    const isFinal = ['APPROUVEE', 'PAYEE', 'REJETEE'].includes(status)
    if (isFinal || examenStatus === 'EXAMINE') return false
    if (requisition?.dossier_id) return examenStatus === 'NON_EXAMINE'
    return true
  }

  const canDeleteRemboursement = (remboursement: RemboursementTransport) => {
    const examenStatus = String(remboursement.requisition?.examen_status || '').toUpperCase()
    return Boolean(remboursement.requisition?.id || remboursement.requisition_id) && examenStatus === 'NON_EXAMINE'
  }

  const toggleSelectRemboursement = (id: string) => {
    setSelectedRemboursementIds((prev) => (
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    ))
  }

  const clearSelection = () => {
    setSelectedRemboursementIds([])
    setSelectedDraftDossierId('')
  }

  const getRemboursementStatus = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    return normalizeStatus(requisition?.status ?? requisition?.statut)
  }

  const getRemboursementServiceId = (remboursement: RemboursementTransport) => {
    const serviceId = remboursement.requisition?.service_id
    return serviceId === undefined || serviceId === null ? '' : String(serviceId)
  }

  const getServiceLabel = (serviceId?: string | number | null) => {
    if (serviceId === undefined || serviceId === null || serviceId === '') return '—'
    const normalizedId = Number(serviceId)
    const service = services.find((item) => item.id === normalizedId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${serviceId}`
  }

  const getDateOnly = (value?: string | null) => {
    return String(value || '').slice(0, 10)
  }

  const handleSignRequisition = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return
    setSigningId(String(requisitionId))
    try {
      await apiRequest('PATCH', `/requisitions/${requisitionId}/sign`)
      setNotification({
        show: true,
        type: 'success',
        message: 'Remboursement signé par le service.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Signature impossible.'
      })
    } finally {
      setSigningId(null)
    }
  }

  const handleSubmitExamen = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return
    setSubmittingExamenId(String(requisitionId))
    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/submit-examen`)
      setNotification({
        show: true,
        type: 'success',
        message: "Le remboursement a été soumis à l'examen."
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible de soumettre le remboursement à l'examen."
      })
    } finally {
      setSubmittingExamenId(null)
    }
  }

  const getRequisitionId = (remboursement: RemboursementTransport) => {
    return remboursement.requisition?.id || remboursement.requisition_id || ''
  }

  const remboursementsList = Array.isArray(remboursements) ? remboursements : []
  const selectedRemboursements = remboursementsList.filter((remboursement) =>
    selectedRemboursementIds.includes(remboursement.id)
  )
  const selectedRequisitionIds = selectedRemboursements
    .map((remboursement) => getRequisitionId(remboursement))
    .filter(Boolean)
  const selectedDossierIds = new Set(
    selectedRemboursements
      .map((remboursement) => remboursement.requisition?.dossier_id)
      .filter(Boolean) as string[]
  )
  const selectedDossierId =
    selectedDossierIds.size === 1 && selectedRemboursements.every((remboursement) => remboursement.requisition?.dossier_id)
      ? Array.from(selectedDossierIds)[0]
      : null
  const canCreateDossier =
    selectedRemboursements.length > 0 &&
    selectedRequisitionIds.length === selectedRemboursements.length &&
    selectedRemboursements.every((remboursement) => !remboursement.requisition?.dossier_id)
  const canAddToDraftDossier = canCreateDossier && draftDossiers.length > 0
  const canSubmitDossier = Boolean(selectedDossierId)
  const hasMixedDossierSelection =
    selectedRemboursements.length > 0 && !canCreateDossier && !canSubmitDossier

  const handleCreateDossier = async () => {
    if (!canCreateDossier) return
    try {
      const res: any = await apiRequest('POST', '/dossiers', { requisition_ids: selectedRequisitionIds })
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: res?.reference
          ? `Dossier ${res.reference} créé en brouillon avec les remboursements sélectionnés.`
          : 'Dossier créé en brouillon avec les remboursements sélectionnés.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Impossible de créer le dossier.'
      })
    }
  }

  const handleAddToDraftDossier = async () => {
    if (!canAddToDraftDossier || !selectedDraftDossierId) return
    try {
      await apiRequest('POST', `/dossiers/${selectedDraftDossierId}/add-requisitions`, {
        requisition_ids: selectedRequisitionIds,
      })
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: 'Les remboursements sélectionnés ont été ajoutés au dossier brouillon.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Impossible d’ajouter les remboursements au dossier.'
      })
    }
  }

  const handleSubmitDossier = async (dossierId: string) => {
    try {
      await apiRequest('POST', `/dossiers/${dossierId}/submit-examen`)
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: "Le dossier de remboursements a été soumis à l'examen."
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible de soumettre le dossier à l'examen."
      })
    }
  }

  const handlePrintRecapitulatif = async (dossierId: string) => {
    try {
      const [{ dossier, remboursements: reunions }, mod] = await Promise.all([
        loadDossierRemboursementsTransport(dossierId),
        loadPdfGeneratorRemboursementModule(),
      ])
      await mod.generateRecapitulatifTransportPDF(dossier, reunions, 'print')
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible de générer l'état récapitulatif."
      })
    }
  }

  const handleDeleteRemboursement = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return

    const confirmed = await confirm({
      title: 'Supprimer le remboursement',
      description: remboursement.requisition?.dossier_id
        ? 'Ce remboursement sera supprimé car son dossier est encore en brouillon.'
        : 'Supprimer ce remboursement de transport ?',
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return

    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/soft-delete`)
      setSelectedRemboursementIds((prev) => prev.filter((id) => id !== remboursement.id))
      if (selectedRemboursementDetails?.id === remboursement.id) {
        setShowDetailModal(false)
        setSelectedRemboursementDetails(null)
      }
      await loadData()
      setNotification({
        show: true,
        type: 'success',
        message: 'Le remboursement a été supprimé.',
      })
    } catch (error: any) {
      console.error('Error deleting remboursement:', error)
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'La suppression du remboursement a échoué.',
      })
    }
  }

  const filteredRemboursements = remboursementsList.filter(r => {
    const searchLower = searchQuery.trim().toLowerCase()
    const serviceLabelForRow = getServiceLabel(getRemboursementServiceId(r))
    const matchSearch = !searchLower ||
                        r.numero_remboursement.toLowerCase().includes(searchLower) ||
                        r.nature_reunion.toLowerCase().includes(searchLower) ||
                        r.lieu.toLowerCase().includes(searchLower) ||
                        serviceLabelForRow.toLowerCase().includes(searchLower)

    const requisitionStatut = getRemboursementStatus(r)
    const matchStatut = !filterStatut || requisitionStatut === filterStatut

    const serviceId = getRemboursementServiceId(r)
    const matchService = !filterServiceId || serviceId === filterServiceId

    const dateReunion = getDateOnly(r.date_reunion)
    const matchDateDebut = !dateDebut || dateReunion >= dateDebut
    const matchDateFin = !dateFin || dateReunion <= dateFin

    return matchSearch && matchStatut && matchService && matchDateDebut && matchDateFin
  })
  const hasActiveFilters = Boolean(
    searchQuery || filterStatut || filterServiceId || dateDebut !== defaultDateDebut || dateFin !== TODAY
  )
  // Total de ce que la liste montre réellement : c'est le montant que l'agent
  // recoupe avec sa caisse, il doit suivre les filtres et non le stock complet.
  const filteredTotal = filteredRemboursements.reduce(
    (sum, r) => sum + (toNumber(r.montant_total) || 0),
    0
  )
  const selectableFilteredIds = filteredRemboursements.filter(canSelectForDossier).map((r) => r.id)
  const allSelectableFilteredSelected =
    selectableFilteredIds.length > 0 && selectableFilteredIds.every((id) => selectedRemboursementIds.includes(id))

  const toggleSelectVisible = () => {
    setSelectedRemboursementIds((prev) => {
      if (allSelectableFilteredSelected) {
        return prev.filter((id) => !selectableFilteredIds.includes(id))
      }
      return Array.from(new Set([...prev, ...selectableFilteredIds]))
    })
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const getStatutBadge = (statut: string) => {
    const meta = getStatusMeta(statut)
    return (
      <span
        className={styles.detailBadge}
        style={{ background: meta.bg, color: meta.color }}
      >
        {meta.label}
      </span>
    )
  }

  const openRequisitionAnnexe = async (annexe?: { id: string; filename?: string | null } | null) => {
    if (!annexe?.id) return
    try {
      if (annexe.filename) {
        await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
      } else {
        await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
      }
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible d'ouvrir la pièce jointe.",
      })
    }
  }

  const openRemboursementPdf = async (remboursement?: { id?: string; numero_remboursement?: string; pdf_path?: string | null } | null) => {
    if (!remboursement?.id || !remboursement?.pdf_path) return
    try {
      await openAuthenticatedFile(`/remboursements-transport/${remboursement.id}/pdf`)
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible d'ouvrir le PDF du remboursement.",
      })
    }
  }

  const canCreate = hasPermission('requisitions')

  if (loading || permissionsLoading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <BackButton fallback="/services" />
          <h1>Remboursement frais de transport</h1>
          <p>Gestion des remboursements pour réunions et commissions</p>
        </div>
        {canCreate && !showForm && (
          <button
            type="button"
            onClick={openNewForm}
            className={`${styles.primaryBtn} ${styles.newRequestBtn}`}
          >
            <Plus size={18} strokeWidth={2.4} aria-hidden="true" />
            <span>Nouveau remboursement</span>
          </button>
        )}
      </div>

      {showForm && (
        <section className={styles.workspace}>
          <div className={styles.workspaceHeader}>
            <div>
              <h2>{draftId ? 'Brouillon de remboursement' : 'Nouvelle demande de remboursement'}</h2>
              <p>
                {draftId
                  ? 'Cochez les présents d\u2019après la liste signée, saisissez les montants, puis créez le remboursement.'
                  : 'Préparez la réunion : enregistrez en brouillon et imprimez la liste de présence, puis complétez après la séance.'}
              </p>
            </div>
            <button
              onClick={() => {
                clearNewParam()
                setShowForm(false)
                resetForm()
              }}
              className={styles.closeBtn}
            >
              ×
            </button>
          </div>

          <div className={styles.workspaceGrid}>
            <div className={styles.workspaceFormCard}>
              <form onSubmit={handleSubmit}>
                <div className={styles.formSection}>
                  <h3>Informations générales</h3>
                  <div className={styles.formGrid}>
                    <div className={styles.formGroup}>
                      <label>Service / Commission *</label>
                      {isServiceLockedByContext ? (
                        <>
                          <input type="hidden" value={formData.service_id} />
                          <div className={styles.readonlyField}>{serviceLabel || 'Service assigné'}</div>
                        </>
                      ) : (
                        <select
                          value={formData.service_id}
                          onChange={(e) => setFormData({ ...formData, service_id: e.target.value, budget_poste_id: '' })}
                          required
                        >
                          <option value="">Sélectionner un service...</option>
                          {selectableServices.map((service) => (
                            <option key={service.id} value={service.id}>
                              {service.code} - {service.libelle}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>

                    <div className={`${styles.formGroup} ${styles.formGroupPoste}`}>
                      <label htmlFor="rt-poste-budgetaire">Poste budgétaire *</label>
                      <BudgetPosteSelect
                        id="rt-poste-budgetaire"
                        postes={rubriques}
                        value={formData.budget_poste_id}
                        onChange={(posteId) =>
                          setFormData({ ...formData, budget_poste_id: posteId == null ? '' : String(posteId) })
                        }
                        required
                        disabled={rubriques.length === 0}
                        placeholder={
                          rubriques.length === 0
                            ? 'Sélectionnez d\u2019abord une commission'
                            : 'Rechercher par code ou libellé'
                        }
                        emptyHint="Aucun poste budgétaire autorisé pour cette commission."
                        ariaLabel="Poste budgétaire d\u2019imputation"
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Instance *</label>
                      <input
                        type="text"
                        value={formData.instance}
                        readOnly
                        required
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Type de réunion *</label>
                      <select
                        value={formData.type_reunion}
                        onChange={(e) => setFormData({ ...formData, type_reunion: e.target.value as any })}
                        required
                      >
                        <option value="bureau">Réunion du Bureau</option>
                        <option value="commission">Réunion de la Commission permanente</option>
                        <option value="commission_ad_hoc">Réunion de la Commission ad hoc</option>
                        <option value="conseil">Réunion du Conseil</option>
                        <option value="atelier">Atelier / Séminaire / Formation</option>
                      </select>
                    </div>

                    <div className={styles.formGroup}>
                      <label>Nature de la réunion *</label>
                      <input
                        type="text"
                        value={formData.nature_reunion}
                        onChange={(e) => setFormData({ ...formData, nature_reunion: e.target.value })}
                        placeholder="Ex: Réunion du Bureau du 10 Octobre 2025"
                        required
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Lieu *</label>
                      <input
                        type="text"
                        value={formData.lieu}
                        onChange={(e) => setFormData({ ...formData, lieu: e.target.value })}
                        placeholder="Ex: Siège ONEC Kinshasa"
                        required
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Date de la réunion *</label>
                      <input
                        type="date"
                        value={formData.date_reunion}
                        onChange={(e) => setFormData({ ...formData, date_reunion: e.target.value })}
                        required
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Heure début</label>
                      <input
                        type="time"
                        value={formData.heure_debut}
                        onChange={(e) => setFormData({ ...formData, heure_debut: e.target.value })}
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Heure fin</label>
                      <input
                        type="time"
                        value={formData.heure_fin}
                        onChange={(e) => setFormData({ ...formData, heure_fin: e.target.value })}
                      />
                    </div>
                  </div>

                  <div className={styles.formGroup} style={{marginTop: '16px'}}>
                    <label>Nature du travail</label>
                    {formData.nature_travail.map((nature, index) => (
                      <div key={index} style={{display: 'flex', gap: '8px', marginBottom: '8px'}}>
                        <input
                          type="text"
                          value={nature}
                          onChange={(e) => updateNatureTravail(index, e.target.value)}
                          placeholder={`Ligne ${index + 1}`}
                          style={{flex: 1}}
                        />
                        {formData.nature_travail.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeNatureTravail(index)}
                            className={styles.removeBtn}
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                    <button type="button" onClick={addNatureTravail} className={styles.secondaryBtn}>
                      + Ajouter ligne
                    </button>
                  </div>
                </div>

                <div className={styles.formSection}>
                  <h3>Participants (Experts comptables)</h3>
                  <p className={styles.orderHint}>L'ordre des lignes est celui du PDF : utilisez les flèches pour le régler.</p>
                  <div className={styles.tableContainer}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th style={{ width: '40px' }}>N°</th>
                          <th>Nom du participant *</th>
                          <th>Qualité / Titre / Fonction *</th>
                          <th style={{ width: '70px', textAlign: 'center' }} title="D'après la liste de présence signée">Présent</th>
                          <th>Montant (USD) *</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {participants.map((p, index) => (
                          <tr key={index} style={isPresent(p) ? undefined : { opacity: 0.55 }}>
                            <td style={{ textAlign: 'center', verticalAlign: 'middle', fontWeight: 600 }}>{index + 1}</td>
                            <td className={styles.dropdownCell} style={{position: 'relative'}}>
                              <input
                                type="text"
                                value={p.nom}
                                onChange={(e) => {
                                  updateParticipant(index, 'nom', e.target.value)
                                  setShowExpertSearch(index)
                                  queueExpertSearch(e.target.value)
                                }}
                                onFocus={() => {
                                  setShowExpertSearch(index)
                                  queueExpertSearch(p.nom)
                                }}
                                placeholder="Rechercher un expert-comptable (nom ou N° ordre)..."
                                required
                                autoComplete="off"
                              />
                              {showExpertSearch === index && p.nom.trim() &&
                                renderExpertDropdown(p.nom, (expert) => selectExpert(index, expert))}
                          </td>
                          <td>
                            <input
                              type="text"
                              value={p.titre_fonction}
                              onChange={(e) => updateParticipant(index, 'titre_fonction', e.target.value)}
                              placeholder="Ex: Président, Vice-président, Rapporteur..."
                              required
                            />
                          </td>
                          <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>
                            <input
                              type="checkbox"
                              checked={isPresent(p)}
                              onChange={(e) => updateParticipant(index, 'present', e.target.checked)}
                              aria-label={`${p.nom || 'Participant'} présent`}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              value={isPresent(p) ? p.montant : 0}
                              onChange={(e) => updateParticipant(index, 'montant', parseFloat(e.target.value) || 0)}
                              required
                              disabled={!isPresent(p)}
                              title={isPresent(p) ? undefined : 'Absent : non remboursé'}
                              min="0"
                              step="0.01"
                            />
                          </td>
                          <td>
                            <div className={styles.rowActions}>
                              {renderMoveButtons(index, participants.length, moveParticipant, p.nom)}
                              {participants.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => removeParticipant(index)}
                                  className={styles.removeBtn}
                                >
                                  ×
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" onClick={addParticipant} className={styles.secondaryBtn}>
                  + Ajouter participant
                </button>
              </div>

                <div className={styles.formSection}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <h3>Assistants administratifs (optionnel)</h3>
                  <button
                    type="button"
                    onClick={() => setShowAssistants(!showAssistants)}
                    className={styles.secondaryBtn}
                  >
                    {showAssistants ? 'Masquer' : 'Afficher'}
                  </button>
                </div>

                {showAssistants && (
                  <>
                    <div className={styles.tableContainer}>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th style={{ width: '40px' }}>N°</th>
                            <th>Nom</th>
                            <th>Fonction</th>
                            <th style={{ width: '70px', textAlign: 'center' }}>Présent</th>
                            <th>Montant (USD)</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {assistants.length === 0 ? (
                            <tr>
                              <td colSpan={6} style={{textAlign: 'center', color: '#9ca3af'}}>
                                Aucun assistant administratif
                              </td>
                            </tr>
                          ) : (
                            assistants.map((a, index) => (
                              <tr key={index} style={isPresent(a) ? undefined : { opacity: 0.55 }}>
                                <td style={{ textAlign: 'center', verticalAlign: 'middle', fontWeight: 600 }}>{index + 1}</td>
                                <td className={styles.dropdownCell} style={{position: 'relative'}}>
                                  <input
                                    type="text"
                                    value={a.nom}
                                    onChange={(e) => {
                                      updateAssistant(index, 'nom', e.target.value)
                                      setShowAssistantExpertSearch(index)
                                      queueExpertSearch(e.target.value)
                                    }}
                                    onFocus={() => {
                                      setShowAssistantExpertSearch(index)
                                      queueExpertSearch(a.nom)
                                    }}
                                    placeholder="Rechercher un expert-comptable (nom ou N° ordre)..."
                                    autoComplete="off"
                                  />
                                  {showAssistantExpertSearch === index && a.nom.trim() &&
                                    renderExpertDropdown(a.nom, (expert) => selectAssistantExpert(index, expert))}
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    value={a.titre_fonction}
                                    onChange={(e) => updateAssistant(index, 'titre_fonction', e.target.value)}
                                    placeholder="Ex: Secrétaire administratif, Assistant à la commission"
                                  />
                                </td>
                                <td style={{ textAlign: 'center', verticalAlign: 'middle' }}>
                                  <input
                                    type="checkbox"
                                    checked={isPresent(a)}
                                    onChange={(e) => updateAssistant(index, 'present', e.target.checked)}
                                    aria-label={`${a.nom || 'Assistant'} présent`}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    value={isPresent(a) ? a.montant : 0}
                                    onChange={(e) => updateAssistant(index, 'montant', parseFloat(e.target.value) || 0)}
                                    disabled={!isPresent(a)}
                                    min="0"
                                    step="0.01"
                                  />
                                </td>
                                <td>
                                  <div className={styles.rowActions}>
                                    {renderMoveButtons(index, assistants.length, moveAssistant, a.nom)}
                                    <button
                                      type="button"
                                      onClick={() => removeAssistant(index)}
                                      className={styles.removeBtn}
                                    >
                                      ×
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    <button type="button" onClick={addAssistant} className={styles.secondaryBtn}>
                      + Ajouter assistant
                    </button>
                  </>
                )}
              </div>

              <div className={styles.formSection}>
                <h3>Après la réunion — pièces à joindre</h3>
                <ReunionPieces
                  pieces={(draftServeur?.pieces || {}) as Partial<Record<PieceReunionKind, PieceReunion>>}
                  onDeposer={async (kind, file, filename) => {
                    // Crée le brouillon s'il n'existe pas encore : une pièce s'y rattache.
                    const id = draftId || (await persistDraft())?.id
                    if (!id) return false
                    const b = await deposerPieceReunion(id, kind, file, filename)
                    setDraftServeur(b.contenu || {})
                    loadBrouillons()
                    return true
                  }}
                  voirPath={draftId ? (kind) => pieceReunionPath(draftId, kind) : undefined}
                  onRetirer={
                    draftId
                      ? async (kind) => {
                          const b = await retirerPieceReunion(draftId, kind)
                          setDraftServeur(b.contenu || {})
                          loadBrouillons()
                        }
                      : undefined
                  }
                  onMessage={(type, message) => setNotification({ show: true, type, message })}
                  disabled={submitting || savingDraft}
                />
              </div>

              <div className={styles.total}>
                <strong>Total général</strong>
                <strong className={styles.totalAmount}>{formatCurrency(calculateTotal())}</strong>
              </div>

              <div className={styles.formActions}>
                <button
                  type="button"
                  onClick={() => {
                    clearNewParam()
                    setShowForm(false)
                    resetForm()
                  }}
                  className={styles.secondaryBtn}
                  disabled={submitting}
                >
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={() => printListePresence()}
                  className={styles.secondaryBtn}
                  disabled={submitting}
                  title="Liste à faire signer en séance, avec des lignes libres pour les présents non prévus"
                >
                  <Printer size={15} aria-hidden="true" /> Liste de présence
                </button>
                <button
                  type="button"
                  onClick={convoquerDepuisFormulaire}
                  className={styles.secondaryBtn}
                  disabled={submitting || savingDraft}
                  title={
                    draftServeur?.convocation?.envoyee_le
                      ? `Convocation envoyée le ${format(new Date(draftServeur.convocation.envoyee_le), 'dd/MM/yyyy HH:mm')}`
                      : 'Envoyer la convocation par e-mail, avec l\u2019invitation agenda'
                  }
                >
                  <Mail size={15} aria-hidden="true" /> {draftServeur?.convocation?.envoyee_le ? 'Reconvoquer' : 'Convoquer'}
                </button>
                <button
                  type="button"
                  onClick={saveDraft}
                  className={styles.secondaryBtn}
                  disabled={submitting || savingDraft}
                  title="Enregistrer sans poste ni montants ; à compléter après la réunion"
                >
                  {savingDraft ? 'Enregistrement…' : draftId ? 'Mettre à jour le brouillon' : 'Enregistrer en brouillon'}
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={submitting || savingDraft}>
                  {submitting ? 'Création en cours...' : 'Créer le remboursement'}
                </button>
              </div>
            </form>
          </div>

          <div className={styles.workspacePreviewCard}>
            <div className={styles.previewLabel}>Aperçu du document</div>
            <div className={styles.previewSheet}>
              <div className={styles.previewStatusBadge}>Brouillon</div>

              <div className={styles.previewHeader}>
                <div className={styles.previewIdentity}>
                  {previewLogoUrl && (
                    <div className={styles.previewLogoFrame}>
                      <img
                        className={styles.previewLogo}
                        src={previewLogoUrl}
                        alt={`Logo ${printSettings?.organization_name || 'organisation'}`}
                      />
                    </div>
                  )}
                  <div className={styles.previewHeaderLeft}>
                    <div className={styles.previewOrg}>{printSettings?.organization_name || 'ONEC'}</div>
                    <div className={styles.previewSubtitle}>
                      {printSettings?.organization_subtitle || 'Antenne provinciale'}
                    </div>
                    {printSettings?.header_text && (
                      <div className={styles.previewMeta}>{printSettings.header_text}</div>
                    )}
                  </div>
                </div>
                <div className={styles.previewHeaderRight}>
                  <div className={styles.previewTitle}>
                    {printSettings?.trans_titre_officiel || 'État de frais de déplacement'}
                  </div>
                  <div className={styles.previewDocRef}>N° À GÉNÉRER</div>
                </div>
              </div>

              <div className={styles.previewSeparator} />

              <div className={styles.previewInfoGrid}>
                <div className={styles.previewInfoCol}>
                  <div className={styles.previewInfoItem}>
                    <span>Bénéficiaire</span>
                    <strong>{serviceLabel || 'Commission / service'}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Type de réunion</span>
                    <strong>{getTypeReunionLabel(formData.type_reunion)}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Lieu</span>
                    <strong>{formData.lieu || '—'}</strong>
                  </div>
                </div>
                <div className={styles.previewInfoCol}>
                  <div className={styles.previewInfoItem}>
                    <span>Instance</span>
                    <strong>{formData.instance || '—'}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Date</span>
                    <strong>{format(new Date(formData.date_reunion), 'dd/MM/yyyy')}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Horaires</span>
                    <strong>{previewHoraires}</strong>
                  </div>
                </div>
              </div>

              <div className={styles.previewMeetingSummary}>
                <div className={styles.previewMeetingLabel}>
                  {previewTravaux.length > 0 ? 'Objet et travaux de la réunion' : 'Objet de la réunion'}
                </div>
                <div className={styles.previewMeetingTitle}>{formData.nature_reunion || 'À renseigner'}</div>
                {previewTravaux.length > 0 && (
                  <ol className={styles.previewWorkList}>
                    {previewTravaux.map((travail, index) => <li key={`${travail}-${index}`}>{travail}</li>)}
                  </ol>
                )}
              </div>

              <div className={styles.previewBlock}>
                <div className={styles.previewBlockTitle}>Participants & Montants</div>
                {previewParticipants.length === 0 ? (
                  <div className={styles.previewEmpty}>Ajoutez des participants pour alimenter l'aperçu.</div>
                ) : (
                  <table className={styles.previewTable}>
                    <thead>
                      <tr>
                        <th style={{ width: '30px' }}>N°</th>
                        <th>Nom & Postnom</th>
                        <th>Fonction</th>
                        <th>Montant</th>
                        <th>Émargement</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewParticipants.map((p, idx) => (
                        <tr key={`${p.nom}-${idx}`}>
                          <td style={{ textAlign: 'center' }}>{idx + 1}</td>
                          <td>{p.nom || '—'}</td>
                          <td>
                            {p.titre_fonction || '—'}
                            {p.type_participant === 'assistant' && (
                              <small className={styles.previewParticipantType}>Assistant(e)</small>
                            )}
                          </td>
                          <td>{formatCurrency(p.montant)}</td>
                          <td>________________</td>
                        </tr>
                      ))}
                    </tbody>                  </table>
                )}
              </div>

              <div className={styles.previewFooter}>
                <div className={styles.previewAmountBox}>
                  <div>
                    <span>Montant total</span>
                    <strong>{formatCurrency(previewTotal)}</strong>
                  </div>
                  <div className={styles.previewAmountLetters}>Somme en lettres : {previewMontantLettres}</div>
                </div>
                <div className={styles.previewSignatures}>
                  <div className={styles.previewSignatureBox}>Le demandeur</div>
                  <div className={styles.previewSignatureBox}>
                    {printSettings?.secretaire_executif_label || 'Le Secrétaire exécutif'}
                  </div>
                  <div className={styles.previewSignatureBox}>
                    {printSettings?.trans_label_gauche || 'Vu par la Trésorerie'}
                  </div>
                  <div className={styles.previewSignatureBox}>
                    {printSettings?.trans_label_droite || 'Approuvé par'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
      )}

      {canCreate && brouillons.length > 0 && (
        <section className={styles.filtersSection} aria-labelledby="rt-brouillons-titre">
          <h3 id="rt-brouillons-titre" style={{ margin: '0 0 8px', fontSize: '15px' }}>
            Brouillons en préparation ({brouillons.length})
          </h3>
          <div className={styles.tableContainer}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Réunion</th>
                  <th>Commission / Service</th>
                  <th>Date</th>
                  <th style={{ textAlign: 'center' }}>Prévus</th>
                  <th style={{ textAlign: 'center' }}>Présents</th>
                  <th>Convocation</th>
                  <th>Liste signée</th>
                  <th>Modifié</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {brouillons.map((b) => {
                  const fd = b.contenu?.formData || {}
                  const people: Participant[] = [...(b.contenu?.participants || []), ...(b.contenu?.assistants || [])]
                    .filter((x: Participant) => String(x?.nom || '').trim())
                  const presents = people.filter(isPresent).length
                  const dateLabel = fd.date_reunion ? format(new Date(fd.date_reunion), 'dd/MM/yyyy') : '—'
                  return (
                    <tr key={b.id}>
                      <td>
                        <strong>{getTypeReunionLabel(fd.type_reunion)}</strong>
                        {fd.nature_reunion ? <div style={{ fontSize: '12px', color: '#6b7280' }}>{fd.nature_reunion}</div> : null}
                      </td>
                      <td>{[b.service_code, b.service_libelle].filter(Boolean).join(' - ') || '—'}</td>
                      <td>{dateLabel}</td>
                      <td style={{ textAlign: 'center' }}>{people.length}</td>
                      <td style={{ textAlign: 'center' }}>{presents}</td>
                      <td style={{ fontSize: '12px' }}>
                        {b.contenu?.convocation?.envoyee_le ? (
                          <>
                            {format(new Date(b.contenu.convocation.envoyee_le), 'dd/MM/yyyy')}
                            <div style={{ color: '#6b7280' }}>
                              {(b.contenu.convocation.destinataires || []).length} convoqué(s)
                            </div>
                          </>
                        ) : (
                          <span style={{ color: '#6b7280' }}>Non envoyée</span>
                        )}
                      </td>
                      <td style={{ fontSize: '12px' }}>
                        {b.contenu?.pieces?.liste_presence ? (
                          <span style={{ color: '#166534', fontWeight: 600 }}>Déposée</span>
                        ) : (
                          <span style={{ color: '#92400e' }}>À déposer</span>
                        )}
                      </td>
                      <td style={{ fontSize: '12px' }}>
                        {format(new Date(b.updated_at), 'dd/MM/yyyy HH:mm')}
                        {b.updated_by_nom ? <div style={{ color: '#6b7280' }}>{b.updated_by_nom}</div> : null}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          <button type="button" className={styles.primaryBtn} onClick={() => openDraft(b)}>
                            Reprendre
                          </button>
                          <button
                            type="button"
                            className={styles.secondaryBtn}
                            onClick={() => printListePresence(b)}
                            title="Imprimer la liste de présence"
                          >
                            <Printer size={15} aria-hidden="true" /> Liste
                          </button>
                          <button
                            type="button"
                            className={styles.secondaryBtn}
                            onClick={() => setConvocationBrouillon(b)}
                            title="Envoyer la convocation par e-mail"
                          >
                            <Mail size={15} aria-hidden="true" /> Convoquer
                          </button>
                          <button type="button" className={styles.secondaryBtn} onClick={() => removeDraft(b)}>
                            Supprimer
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className={styles.filtersSection}>
        <div className={styles.filters}>
          <div className={`${styles.filterGroup} ${styles.filterGroupSearch}`}>
            <label htmlFor="rt-filtre-recherche">Recherche</label>
            <input
              id="rt-filtre-recherche"
              type="text"
              placeholder="Numéro, nature ou lieu..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="rt-filtre-statut">Statut</label>
            <select
              id="rt-filtre-statut"
              value={filterStatut}
              onChange={(e) => setFilterStatut(e.target.value)}
            >
              <option value="">Tous les statuts</option>
              <option value="BROUILLON">Brouillon</option>
              <option value="SIGNEE_SERVICE">Signé service</option>
              <option value="EN_ATTENTE">En attente validation 1/2</option>
              <option value="AUTORISEE">Validation 1/2</option>
              <option value="APPROUVEE">Validation 2/2</option>
              <option value="PAYEE">Payée</option>
              <option value="REJETEE">Rejetée</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="rt-filtre-service">Commission / service</label>
            <select
              id="rt-filtre-service"
              value={filterServiceId}
              onChange={(e) => setFilterServiceId(e.target.value)}
              disabled={Boolean(serviceContextId)}
            >
              <option value="">Toutes les commissions</option>
              {selectableServices.map((service) => (
                <option key={service.id} value={String(service.id)}>
                  {service.code} - {service.libelle}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="rt-filtre-date-debut">Date début</label>
            <input
              id="rt-filtre-date-debut"
              type="date"
              value={dateDebut}
              max={dateFin || undefined}
              onChange={(e) => setDateDebut(e.target.value)}
            />
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="rt-filtre-date-fin">Date fin</label>
            <input
              id="rt-filtre-date-fin"
              type="date"
              value={dateFin}
              min={dateDebut || undefined}
              onChange={(e) => setDateFin(e.target.value)}
            />
          </div>
        </div>
        <div className={styles.filtersFooter}>
          <div className={styles.periodQuick} role="group" aria-label="Raccourcis de période">
            {PERIODES_RAPIDES.map((periode) => (
              <button
                key={periode.cle}
                type="button"
                className={styles.periodQuickBtn}
                aria-pressed={dateDebut === periode.debut && dateFin === periode.fin}
                onClick={() => {
                  setDateDebut(periode.debut)
                  setDateFin(periode.fin)
                }}
              >
                {periode.libelle}
              </button>
            ))}
          </div>
          {/* Toujours rendu, désactivé au repos : apparaître/disparaître décalait
              la barre sous le curseur au moment même de la saisie d'un filtre. */}
          <button
            type="button"
            className={styles.resetBtn}
            disabled={!hasActiveFilters}
            onClick={() => {
              setSearchQuery('')
              setFilterStatut('')
              setFilterServiceId(serviceContextId || '')
              setDateDebut(defaultDateDebut)
              setDateFin(TODAY)
            }}
          >
            <RotateCcw size={14} aria-hidden="true" />
            Réinitialiser
          </button>
        </div>
      </div>

      <div className={styles.resultsBar}>
        <div className={styles.resultsCount}>
          <strong>{filteredRemboursements.length}</strong>{' '}
          remboursement{filteredRemboursements.length > 1 ? 's' : ''}
          {hasActiveFilters && remboursementsList.length !== filteredRemboursements.length && (
            <span className={styles.resultsFiltered}> sur {remboursementsList.length}</span>
          )}
        </div>
        <div className={styles.resultsTotal}>
          <span className={styles.resultsTotalLabel}>Total affiché</span>
          <strong>{formatCurrency(filteredTotal)}</strong>
        </div>
      </div>

      {selectedRemboursementIds.length > 0 && (
        <div className={styles.groupingBar}>
          <div className={styles.groupingCount}>
            {selectedRemboursementIds.length} remboursement{selectedRemboursementIds.length > 1 ? 's' : ''} sélectionné
            {selectedRemboursementIds.length > 1 ? 's' : ''}
          </div>
          <div className={styles.groupingActions}>
            {canCreateDossier && (
              <button type="button" className={styles.groupingPrimary} onClick={handleCreateDossier}>
                Créer un dossier
              </button>
            )}
            {canAddToDraftDossier && (
              <div className={styles.groupingSelectWrap}>
                <select
                  className={styles.groupingSelect}
                  value={selectedDraftDossierId}
                  onChange={(e) => setSelectedDraftDossierId(e.target.value)}
                >
                  <option value="">Ajouter à un dossier...</option>
                  {draftDossiers.map((dossier) => (
                    <option key={dossier.id} value={dossier.id}>
                      {dossier.reference}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={styles.groupingPrimary}
                  onClick={handleAddToDraftDossier}
                  disabled={!selectedDraftDossierId}
                >
                  Ajouter au dossier
                </button>
              </div>
            )}
            {canSubmitDossier && selectedDossierId && (
              <button
                type="button"
                className={styles.groupingPrimary}
                onClick={() => handleSubmitDossier(selectedDossierId)}
              >
                Soumettre le dossier à l'examen
              </button>
            )}
            {selectedDossierId && (
              <button
                type="button"
                className={styles.groupingSecondary}
                onClick={() => handlePrintRecapitulatif(selectedDossierId)}
                title="Une ligne par personne, une colonne par réunion, en paysage. Les états de frais de chaque réunion restent inchangés."
              >
                État récapitulatif
              </button>
            )}
            {hasMixedDossierSelection && (
              <div className={styles.groupingHint}>
                Sélection incompatible : choisissez des remboursements sans dossier ou du même dossier brouillon.
              </div>
            )}
            <button type="button" className={styles.groupingSecondary} onClick={clearSelection}>
              Annuler
            </button>
          </div>
        </div>
      )}

      <div className={`${styles.tableContainer} ${styles.listTableContainer}`}>
        <table className={`${styles.table} ${styles.listTable}`}>
          <thead>
            <tr>
              <th className={styles.selectColumn}>
                <input
                  type="checkbox"
                  checked={allSelectableFilteredSelected}
                  onChange={toggleSelectVisible}
                  disabled={selectableFilteredIds.length === 0}
                  aria-label="Sélectionner les remboursements visibles"
                />
              </th>
              <th>N° Remboursement</th>
              <th>Date réunion</th>
              <th>Commission</th>
              <th>Nature</th>
              <th>Lieu</th>
              <th>Montant total</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredRemboursements.length === 0 ? (
              <tr>
                <td colSpan={9} className={styles.empty}>
                  {hasActiveFilters ? (
                    <div className={styles.emptyBlock}>
                      <div className={styles.emptyTitle}>Aucun remboursement pour ces filtres</div>
                      <div className={styles.emptySubtitle}>
                        {remboursementsList.length} remboursement{remboursementsList.length > 1 ? 's' : ''} au total.
                      </div>
                      {/* Vide les bornes de date au lieu de les remettre par défaut :
                          la vue s'ouvre sur le mois (ou l'année) en cours, remettre les
                          valeurs par défaut aurait reconduit le filtre qui
                          masque tout. */}
                      <button
                        type="button"
                        className={styles.resetBtn}
                        onClick={() => {
                          setSearchQuery('')
                          setFilterStatut('')
                          setFilterServiceId(serviceContextId || '')
                          setDateDebut('')
                          setDateFin('')
                        }}
                      >
                        Afficher tout l'historique
                      </button>
                    </div>
                  ) : (
                    <div className={styles.emptyBlock}>
                      <div className={styles.emptyTitle}>Aucun remboursement enregistré</div>
                      <div className={styles.emptySubtitle}>
                        {canCreate
                          ? 'Créez une première demande avec le bouton « Nouveau remboursement ».'
                          : 'Les demandes créées par votre commission apparaîtront ici.'}
                      </div>
                    </div>
                  )}
                </td>
              </tr>
            ) : (
              filteredRemboursements.map((r) => {
                const requisition = (r as any).requisition
                return (
                  <tr key={r.id}>
                    <td className={styles.selectColumn}>
                      <input
                        type="checkbox"
                        checked={selectedRemboursementIds.includes(r.id)}
                        onChange={() => toggleSelectRemboursement(r.id)}
                        disabled={!canSelectForDossier(r)}
                        aria-label={`Sélectionner ${r.numero_remboursement}`}
                      />
                    </td>
                    <td>
                      <div>
                        <strong>{r.numero_remboursement}</strong>
                      </div>
                    </td>
                    <td>{format(new Date(r.date_reunion), 'dd/MM/yyyy')}</td>
                    <td>{getServiceLabel(getRemboursementServiceId(r))}</td>
                    <td>{r.nature_reunion}</td>
                    <td>{r.lieu}</td>
                    <td><strong>{formatCurrency(r.montant_total)}</strong></td>
                    <td>{requisition ? getStatutBadge(getRemboursementStatus(r)) : getStatutBadge('EN_ATTENTE_COMMISSION')}</td>
                    <td>
                      <div className={styles.rowActions}>
                        <button
                          type="button"
                          onClick={() => viewDetails(r)}
                          className={`${styles.actionBtn} ${styles.actionIconBtn} ${styles.viewBtn}`}
                          title="Voir les détails du remboursement"
                          aria-label="Voir les détails du remboursement"
                        >
                          <Search size={16} />
                        </button>
                        <RowActionsMenu
                          libelle={`Autres actions sur le remboursement ${r.numero_remboursement}`}
                          items={[
                            ...(requisition?.annexe?.id
                              ? [{
                                  cle: 'annexe',
                                  libelle: 'Voir la pièce jointe',
                                  icone: <Paperclip size={15} />,
                                  onSelect: () => { void openRequisitionAnnexe(requisition.annexe) },
                                }]
                              : []),
                            {
                              cle: 'imprimer',
                              libelle: 'Imprimer le remboursement',
                              icone: <Printer size={15} />,
                              onSelect: () => { void printRemboursement(r) },
                            },
                            ...(canSignRequisition(r)
                              ? [{
                                  cle: 'signer',
                                  libelle: signingId === String(requisition?.id || r.requisition_id)
                                    ? 'Signature en cours…'
                                    : 'Valider et signer',
                                  icone: <CheckCircle2 size={15} />,
                                  disabled: signingId === String(requisition?.id || r.requisition_id),
                                  onSelect: () => { void handleSignRequisition(r) },
                                }]
                              : []),
                            {
                              cle: 'examen',
                              libelle: submittingExamenId === String(requisition?.id || r.requisition_id)
                                ? 'Envoi en cours…'
                                : "Soumettre à l'examen",
                              icone: <Send size={15} />,
                              disabled:
                                !canSubmitToExamen(r) ||
                                submittingExamenId === String(requisition?.id || r.requisition_id),
                              description: !canSubmitToExamen(r) ? getSubmitExamenLabel(r) : undefined,
                              onSelect: () => { void handleSubmitExamen(r) },
                            },
                            ...(canDeleteRemboursement(r)
                              ? [{
                                  cle: 'supprimer',
                                  libelle: 'Supprimer le remboursement',
                                  icone: <Trash2 size={15} />,
                                  onSelect: () => { void handleDeleteRemboursement(r) },
                                  destructive: true,
                                }]
                              : []),
                          ]}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {notification.show && (
        <div
          className={`${styles.toast} ${
            notification.type === 'success' ? styles.toastSuccess : styles.toastError
          }`}
          role="status"
        >
          <span>{notification.message}</span>
          <button
            type="button"
            className={styles.toastClose}
            onClick={() => setNotification({ ...notification, show: false })}
            aria-label="Fermer la notification"
          >
            ×
          </button>
        </div>
      )}

      {convocationBrouillon && (
        <ConvocationReunionModal
          brouillon={convocationBrouillon}
          onClose={() => setConvocationBrouillon(null)}
          onEnvoyee={(contenu, message, type) => {
            if (convocationBrouillon.id === draftId) setDraftServeur(contenu)
            setNotification({ show: true, type, message })
            loadBrouillons()
          }}
        />
      )}

      {showDetailModal && selectedRemboursementDetails && (
        <div className={`${styles.modal} ${styles.detailModalOverlay}`}>
          <div className={`${styles.modalContent} ${styles.detailModalContent}`}>
            <div className={styles.modalHeader}>
              <h2>Détails du remboursement {selectedRemboursementDetails.numero_remboursement}</h2>
              <button
                onClick={() => {
                  detailsRequestRef.current += 1
                  setShowDetailModal(false)
                }}
                className={styles.closeBtn}
              >×</button>
            </div>

            <div className={styles.detailContent}>
              <div className={`${styles.detailSection} ${styles.detailSectionAccent}`}>
                <h3 className={styles.detailSectionAccentTitle}>Traçabilité et Responsabilité</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Demandeur</label>
                    <p><strong>{selectedRemboursementUsers.demandeur ? `${selectedRemboursementUsers.demandeur.prenom} ${selectedRemboursementUsers.demandeur.nom}` : 'Non disponible'}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Date de la demande</label>
                    <p>{format(new Date((selectedRemboursementDetails as any).requisition?.created_at ?? selectedRemboursementDetails.created_at), 'dd/MM/yyyy à HH:mm')}</p>
                  </div>
                  {((selectedRemboursementDetails as any).requisition?.validee_par || (selectedRemboursementDetails as any).requisition?.approuvee_par) && (
                    <>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Validation technique</label>
                        <p><strong>
                          {selectedRemboursementUsers.validateur
                            ? `${selectedRemboursementUsers.validateur.prenom} ${selectedRemboursementUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Date d'autorisation</label>
                        <p>
                          {(selectedRemboursementDetails as any).requisition?.validee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Visa Trésorerie</label>
                        <p><strong>
                          {selectedRemboursementUsers.approbateur
                            ? `${selectedRemboursementUsers.approbateur.prenom} ${selectedRemboursementUsers.approbateur.nom}`
                            : 'En attente'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Date de visa</label>
                        <p>
                          {(selectedRemboursementDetails as any).requisition?.approuvee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Statut actuel</label>
                    <p>{(selectedRemboursementDetails as any).requisition ? getStatutBadge((selectedRemboursementDetails as any).requisition.statut) : getStatutBadge('EN_ATTENTE_COMMISSION')}</p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedRemboursementDetails.numero_remboursement}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Bénéficiaire</label>
                    <p>
                      {[selectedRemboursementDetails.service_code, selectedRemboursementDetails.service_libelle]
                        .filter(Boolean)
                        .join(' - ') || 'Commission / service non renseigné'}
                    </p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Instance</label>
                    <p>{selectedRemboursementDetails.instance || 'Non renseignée'}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Type de réunion</label>
                    <p>{getTypeReunionLabel(selectedRemboursementDetails.type_reunion)}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Date de réunion</label>
                    <p>{format(new Date(selectedRemboursementDetails.date_reunion), 'dd/MM/yyyy')}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Nature de réunion</label>
                    <p>{selectedRemboursementDetails.nature_reunion}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Lieu</label>
                    <p>{selectedRemboursementDetails.lieu}</p>
                  </div>
                  {selectedRemboursementDetails.heure_debut && (
                    <div className={styles.detailItem}>
                      <label>Heure de début</label>
                      <p>{selectedRemboursementDetails.heure_debut}</p>
                    </div>
                  )}
                  {selectedRemboursementDetails.heure_fin && (
                    <div className={styles.detailItem}>
                      <label>Heure de fin</label>
                      <p>{selectedRemboursementDetails.heure_fin}</p>
                    </div>
                  )}
                  {selectedRemboursementDetails.nature_travail?.filter((item) => item.trim()).length > 0 && (
                    <div className={`${styles.detailItem} ${styles.detailItemWide}`}>
                      <label>Travaux / ordre du jour</label>
                      <ol className={styles.detailWorkList}>
                        {selectedRemboursementDetails.nature_travail
                          .filter((item) => item.trim())
                          .map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
                      </ol>
                    </div>
                  )}
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong className={styles.detailAmount}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></p>
                  </div>
                  {selectedRemboursementDetails.pdf_path && (
                    <div className={styles.detailItem}>
                      <label>Document officiel</label>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => openRemboursementPdf(selectedRemboursementDetails)}
                      >
                        Voir le PDF du remboursement
                      </button>
                    </div>
                  )}
                  {(selectedRemboursementDetails as any).requisition?.annexe?.id && (
                    <div className={styles.detailItem}>
                      <label>Pièce jointe</label>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => openRequisitionAnnexe((selectedRemboursementDetails as any).requisition?.annexe)}
                      >
                        <Paperclip size="1em" style={{ verticalAlign: '-0.125em' }} aria-hidden="true" /> Voir la pièce jointe
                      </button>
                    </div>
                  )}                </div>
              </div>

              {selectedPieces && (
                <div className={styles.detailSection}>
                  <h3>Pièces de la réunion</h3>
                  <ReunionPieces
                    pieces={selectedPieces}
                    onDeposer={async (kind, file, filename) => {
                      setSelectedPieces(await deposerPieceRemboursement(selectedRemboursementDetails.id, kind, file, filename))
                      return true
                    }}
                    voirPath={(kind) => pieceRemboursementPath(selectedRemboursementDetails.id, kind)}
                    confirmationDepot="Elle est jointe à la réquisition."
                    canUpload={hasPermission('remboursement_transport')}
                    onMessage={(type, message) => setNotification({ show: true, type, message })}
                  />
                </div>
              )}

              <div className={styles.detailSection}>
                <h3>Repères budgétaires</h3>
                <BudgetDecisionTable
                  lines={selectedBudgetLines}
                  requestedAmount={selectedRemboursementDetails.montant_total}
                  emptyLabel="Aucun poste budgétaire rattaché à ce remboursement."
                />
              </div>

              <div className={styles.detailSection}>
                <div className={styles.detailSectionHeader}>
                  <h3>Participants</h3>
                  {ordreFicheModifie && (
                    <button
                      type="button"
                      className={styles.actionBtn}
                      onClick={() => { void enregistrerOrdreFiche() }}
                      disabled={ordreFicheEnCours}
                    >
                      {ordreFicheEnCours ? 'Enregistrement…' : "Enregistrer l'ordre"}
                    </button>
                  )}
                </div>
                <div className={styles.detailTableWrap}>
                  <table className={styles.detailTable}>
                    <thead>
                      <tr>
                        <th style={{ width: '40px' }}>N°</th>
                        <th>Nom</th>
                        <th>Titre/Fonction</th>
                        <th>Type</th>
                        <th className={styles.numCell}>Montant</th>
                        <th style={{ width: '80px' }} title="Ordre d'impression">Position</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedParticipants.map((participant, index) => (
                        <tr key={participant.id}>
                          <td style={{ textAlign: 'center', fontWeight: 600 }}>{index + 1}</td>
                          <td>{participant.nom}</td>
                          <td>{participant.titre_fonction}</td>
                          <td>
                            <span
                              className={`${styles.participantBadge} ${
                                participant.type_participant === 'principal'
                                  ? styles.participantBadgePrimary
                                  : styles.participantBadgeAssistant
                              }`}
                            >
                              {participant.type_participant === 'principal' ? 'Principal' : 'Assistant'}
                            </span>
                          </td>
                          <td className={styles.numCell}><strong>{formatCurrency(participant.montant)}</strong></td>
                          <td>
                            <div className={styles.rowActions}>
                              <button
                                type="button"
                                onClick={() => deplacerFiche(index, -1)}
                                className={styles.moveBtn}
                                disabled={!peutDeplacerFiche(index, -1) || ordreFicheEnCours}
                                title="Monter"
                                aria-label={`Monter ${participant.nom}`}
                              >
                                <ArrowUp size={15} aria-hidden="true" />
                              </button>
                              <button
                                type="button"
                                onClick={() => deplacerFiche(index, 1)}
                                className={styles.moveBtn}
                                disabled={!peutDeplacerFiche(index, 1) || ordreFicheEnCours}
                                title="Descendre"
                                aria-label={`Descendre ${participant.nom}`}
                              >
                                <ArrowDown size={15} aria-hidden="true" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={4} className={styles.numCell} style={{fontWeight: 600}}>Total général</td>
                        <td className={styles.numCell}>
                          <strong className={styles.detailAmount}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong>
                        </td>
                        <td />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
