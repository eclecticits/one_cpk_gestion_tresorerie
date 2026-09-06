import { useState, useEffect, useMemo, useRef, useCallback, Fragment, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '../lib/apiClient'
import { getBudgetPostes } from '../api/budget'
import { listComptesBancaires } from '../api/banques'
import { getPrintSettings } from '../api/settings'
import { getServices } from '../api/services'
import { scoreRequisitions } from '../api/ai'
import { useAuth } from '../contexts/AuthContext'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { usePermissions } from '../hooks/usePermissions'
import { useTreeBranchReveal } from '../hooks/useTreeBranchReveal'
import { toNumber } from '../utils/amount'
import BudgetDecisionTable from '../components/BudgetDecisionTable'
import RequisitionEditModal from '../components/RequisitionEditModal'
import { peutModifierRequisition } from '../utils/requisitionLock'
import { compareBudgetCodes } from '../utils/budgetCode'
import { sousTotalGroupeUsd, trouverGroupeEnDepassement } from '../utils/budgetGroups'
import type { Money } from '../types'
import { Requisition, LigneRequisition, StatutRequisition, ModePaiement, Service } from '../types'
import type { BudgetPosteSummary } from '../types/budget'
import type { CompteBancaire } from '../types/banque'
import { format, subDays } from 'date-fns'
import { Inbox, Sparkles, CheckCircle2, ReceiptText, Clock, Search, Paperclip, Printer, Download, Send, Trash2, Eye, Pencil, FileText, X, MoreHorizontal } from 'lucide-react'
// jsPDF/jspdf-autotable sont lourds : on charge ../utils/pdfGenerator dynamiquement,
// au moment de l'action (impression/téléchargement), plutôt qu'au chargement de la page.
type PdfGeneratorModule = typeof import('../utils/pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('../utils/pdfGenerator')
  return _pdfGeneratorModulePromise
}
const generateSingleRequisitionPDF: PdfGeneratorModule['generateSingleRequisitionPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateSingleRequisitionPDF(...args)
}

type PdfGeneratorReportsModule = typeof import('../utils/pdfGeneratorReports')
let _pdfGeneratorReportsModulePromise: Promise<PdfGeneratorReportsModule> | null = null
function loadPdfGeneratorReportsModule(): Promise<PdfGeneratorReportsModule> {
  if (!_pdfGeneratorReportsModulePromise) _pdfGeneratorReportsModulePromise = import('../utils/pdfGeneratorReports')
  return _pdfGeneratorReportsModulePromise
}
const generateRequisitionsReportPDF: PdfGeneratorReportsModule['generateRequisitionsReportPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorReportsModule()
  return mod.generateRequisitionsReportPDF(...args)
}
import { downloadAuthenticatedFile, openAuthenticatedFile, downloadExcel } from '../utils/download'
import { getStatusMeta } from '../utils/statusMapper'
import styles from './Requisitions.module.css'
import PageHeader from '../components/PageHeader'
import PlanDecaissement from '../components/PlanDecaissement'
import OrganisationAutocomplete from '../components/OrganisationAutocomplete'

// Résumé calculé par le backend quand les lignes ne s'accordent pas sur leur
// règlement. Ce n'est jamais un mode saisissable : il n'apparaît qu'en lecture.
const MODE_PAIEMENT_MIXTE = 'mixte'

const libelleModePaiement = (mode?: string | null) => {
  switch (String(mode || '')) {
    case 'cash':
      return 'Caisse'
    case 'virement':
      return 'Banque'
    case 'mobile_money':
      return 'Mobile Money'
    case 'card':
      return 'Carte (Visa)'
    case 'cheque':
      return 'Chèque'
    case MODE_PAIEMENT_MIXTE:
      return 'Mixte'
    default:
      return '—'
  }
}

// Ligne en cours de saisie. `mode_paiement` à null signifie « suit le règlement
// global de la réquisition » : c'est le cas courant, et le backend applique
// exactement la même règle d'héritage à la création.
type LigneFormulaire = Omit<
  LigneRequisition,
  'id' | 'requisition_id' | 'mode_paiement' | 'compte_bancaire_id'
> & {
  devise?: 'USD' | 'CDF'
  mode_paiement?: ModePaiement | null
  compte_bancaire_id?: number | null
}

type LigneDepenseDraft = Omit<LigneFormulaire, 'budget_poste_id' | 'rubrique'> & {
  id: string
}

type GroupeDepenseDraft = {
  id: string
  budget_poste_id: number | null
  rubrique: string
  budgetSearch: string
  showBudgetDropdown: boolean
  lignes: LigneDepenseDraft[]
}

const nouvelleLigneDepense = (id: string): LigneDepenseDraft => ({
  id,
  description: '',
  quantite: 1,
  montant_unitaire: 0,
  montant_total: 0,
  devise: 'USD',
  mode_paiement: null,
  compte_bancaire_id: null,
})

const flattenLignes = (groupes: GroupeDepenseDraft[]): LigneFormulaire[] =>
  groupes.flatMap((groupe) =>
    groupe.lignes.map(({ id: _id, ...ligne }) => ({
      ...ligne,
      budget_poste_id: groupe.budget_poste_id,
      rubrique: groupe.rubrique,
    }))
  )

const groupLignesByBudgetPoste = (
  lignes: LigneFormulaire[],
  makeId: (prefix: string) => string,
): GroupeDepenseDraft[] => {
  const groupes = new Map<string, GroupeDepenseDraft>()
  lignes.forEach((ligne) => {
    const key = ligne.budget_poste_id != null ? String(ligne.budget_poste_id) : makeId('poste')
    let groupe = groupes.get(key)
    if (!groupe) {
      groupe = {
        id: key.startsWith('poste-') ? key : makeId('poste'),
        budget_poste_id: ligne.budget_poste_id ?? null,
        rubrique: ligne.rubrique || '',
        budgetSearch: ligne.rubrique || '',
        showBudgetDropdown: false,
        lignes: [],
      }
      groupes.set(key, groupe)
    }
    groupe.lignes.push({
      id: makeId('ligne'),
      description: ligne.description || '',
      quantite: ligne.quantite || 1,
      montant_unitaire: ligne.montant_unitaire || 0,
      montant_total: ligne.montant_total || 0,
      devise: (ligne.devise || 'USD') as 'USD' | 'CDF',
      mode_paiement: ligne.mode_paiement ?? null,
      compte_bancaire_id: ligne.compte_bancaire_id ?? null,
    })
  })
  return Array.from(groupes.values())
}

// Un volet = les lignes qui partagent le même couple (mode, compte bancaire).
// C'est l'unité qui sera autorisée puis payée indépendamment des autres.
type VoletSaisie = {
  mode: ModePaiement
  compteId: number | null
  montantUsd: number
  numerosLignes: number[]
}

type ActionLigne = {
  cle: string
  libelle: string
  icone: ReactNode
  onSelect: () => void
  /** Action destructrice : signalée en rouge et séparée des autres. */
  destructive?: boolean
}

/**
 * Menu « … » des actions d'une ligne de tableau.
 *
 * Le panneau est rendu dans un portail sur <body> et positionné en
 * `position: fixed` à partir du rectangle du déclencheur : posé en
 * `position: absolute` dans la ligne, il serait rogné par l'`overflow` et le
 * `max-height` de .tableContainer. Le portail neutralise aussi les `transform`
 * du châssis, qui piègeraient un `fixed` en créant un bloc conteneur.
 */
function MenuActionsLigne({ items, libelle }: { items: ActionLigne[]; libelle: string }) {
  const [ouvert, setOuvert] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const [indexActif, setIndexActif] = useState(0)
  const declencheurRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const itemsRef = useRef<(HTMLButtonElement | null)[]>([])

  const fermer = useCallback((rendreLeFocus: boolean) => {
    setOuvert(false)
    if (rendreLeFocus) declencheurRef.current?.focus()
  }, [])

  const ouvrir = () => {
    const rect = declencheurRef.current?.getBoundingClientRect()
    if (!rect) return
    const largeur = 224
    const separateurs = items.some((item) => item.destructive) ? 9 : 0
    const hauteur = items.length * 34 + 8 + separateurs
    // Bascule au-dessus du déclencheur quand le bas de la fenêtre est trop
    // proche : les dernières lignes du tableau sont le cas courant.
    const placeEnDessous = window.innerHeight - rect.bottom > hauteur + 8
    setPosition({
      top: placeEnDessous ? rect.bottom + 4 : Math.max(8, rect.top - hauteur - 4),
      left: Math.max(8, Math.min(rect.right - largeur, window.innerWidth - largeur - 8)),
    })
    setIndexActif(0)
    setOuvert(true)
  }

  // Le panneau est en `fixed` : il ne suit pas le défilement. On le referme
  // plutôt que de le laisser flotter loin de sa ligne. `capture` intercepte
  // aussi le défilement interne de .tableContainer.
  useEffect(() => {
    if (!ouvert) return
    const surClicExterieur = (event: MouseEvent) => {
      const cible = event.target as Node
      if (menuRef.current?.contains(cible) || declencheurRef.current?.contains(cible)) return
      fermer(false)
    }
    const surDefilement = () => fermer(false)
    document.addEventListener('mousedown', surClicExterieur)
    window.addEventListener('scroll', surDefilement, true)
    window.addEventListener('resize', surDefilement)
    return () => {
      document.removeEventListener('mousedown', surClicExterieur)
      window.removeEventListener('scroll', surDefilement, true)
      window.removeEventListener('resize', surDefilement)
    }
  }, [ouvert, fermer])

  // Focus réellement déplacé sur l'entrée active : c'est ce qu'attend un
  // lecteur d'écran d'un role="menu".
  useEffect(() => {
    if (ouvert) itemsRef.current[indexActif]?.focus()
  }, [ouvert, indexActif])

  const surToucheMenu = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      fermer(true)
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndexActif((i) => (i + 1) % items.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndexActif((i) => (i - 1 + items.length) % items.length)
    } else if (event.key === 'Home') {
      event.preventDefault()
      setIndexActif(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      setIndexActif(items.length - 1)
    } else if (event.key === 'Tab') {
      // On rend la main au déclencheur plutôt que de laisser le focus filer
      // vers un panneau sur le point d'être démonté.
      event.preventDefault()
      fermer(true)
    }
  }

  const surToucheDeclencheur = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!ouvert) ouvrir()
    }
  }

  if (items.length === 0) return null

  return (
    <>
      <button
        type="button"
        ref={declencheurRef}
        className={`${styles.actionBtn} ${styles.actionIconBtn} ${styles.actionMenuBtn}`}
        onClick={() => (ouvert ? fermer(true) : ouvrir())}
        onKeyDown={surToucheDeclencheur}
        aria-haspopup="menu"
        aria-expanded={ouvert}
        title="Autres actions"
        aria-label={libelle}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {ouvert && position && createPortal(
        <div
          ref={menuRef}
          className={styles.rowMenu}
          role="menu"
          aria-label={libelle}
          style={{ top: position.top, left: position.left }}
          onKeyDown={surToucheMenu}
        >
          {items.map((item, index) => (
            <Fragment key={item.cle}>
              {item.destructive && index > 0 && (
                <div className={styles.rowMenuSeparator} role="separator" />
              )}
              <button
                type="button"
                role="menuitem"
                tabIndex={index === indexActif ? 0 : -1}
                ref={(element) => { itemsRef.current[index] = element }}
                className={`${styles.rowMenuItem} ${item.destructive ? styles.rowMenuDanger : ''}`}
                onClick={() => {
                  fermer(true)
                  item.onSelect()
                }}
                onMouseEnter={() => setIndexActif(index)}
              >
                <span className={styles.rowMenuIcone} aria-hidden="true">{item.icone}</span>
                {item.libelle}
              </button>
            </Fragment>
          ))}
        </div>,
        document.body
      )}
    </>
  )
}

export default function Requisitions() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const confirm = useConfirm()
  const { settings: orgSettings } = useOrganisationSettings()
  const aiEnabled = Boolean(orgSettings?.is_ai_enabled)
  const { hasPermission, isAdmin, loading: permissionsLoading } = usePermissions()
  const [searchParams, setSearchParams] = useSearchParams()
  const serviceParam = searchParams.get('service_id')
  const serviceIds = useMemo(
    () =>
      user?.service_ids && user.service_ids.length > 0
        ? user.service_ids
        : user?.service_id
          ? [user.service_id]
          : [],
    [user?.service_id, user?.service_ids]
  )
  const hasGlobalServiceAccess = hasPermission('requisitions')
  const isServiceUser =
    serviceIds.length > 0 &&
    user?.role !== 'admin' &&
    user?.role !== 'super_admin' &&
    !hasGlobalServiceAccess
  // Un ?service_id= venant d'un autre écran verrouille le champ Service : on ne
  // l'honore que s'il fait partie des services de l'utilisateur, sinon le
  // formulaire proposerait un choix que l'API rejette en 403.
  const effectiveServiceParam = useMemo(() => {
    if (!serviceParam) return ''
    if (isServiceUser && !serviceIds.includes(Number(serviceParam))) return ''
    return serviceParam
  }, [serviceParam, isServiceUser, serviceIds])
  const navigate = useNavigate()
  const location = useLocation()
  // Création en page dédiée (même patron que /encaissements/nouveau et
  // /sorties-fonds/nouvelle) : le formulaire occupe toute la largeur de .main.
  const isCreatePage = location.pathname === '/requisitions/nouvelle'
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [requisitionAModifier, setRequisitionAModifier] = useState<any | null>(null)
  const [selectedRequisition, setSelectedRequisition] = useState<Requisition | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectedLignes, setSelectedLignes] = useState<LigneRequisition[]>([])
  const [budgetLines, setBudgetPostes] = useState<BudgetPosteSummary[]>([])
  const [serviceBudgetLines, setServiceBudgetLines] = useState<BudgetPosteSummary[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [comptesBancaires, setComptesBancaires] = useState<CompteBancaire[]>([])
  const [printSettings, setPrintSettings] = useState<any | null>(null)
  const [selectedRequisitionUsers, setSelectedRequisitionUsers] = useState<{
    demandeur?: { prenom: string; nom: string }
    validateur?: { prenom: string; nom: string }
    approbateur?: { prenom: string; nom: string }
  }>({})
  const [aiScores, setAiScores] = useState<Record<string, any>>({})
  const [filterBudgetOptions, setFilterBudgetOptions] = useState<BudgetPosteSummary[]>([])
  const [draftDossiers, setDraftDossiers] = useState<Array<{ id: string; reference: string; created_at: string; description?: string | null; status?: string }>>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [notification, setNotification] = useState<{
    show: boolean
    // 'info' : l'attente d'un export asynchrone n'est ni un succès ni une
    // alerte. NotificationModal gère déjà les quatre types.
    type: 'success' | 'error' | 'warning' | 'info'
    title: string
    message: string
  }>({ show: false, type: 'success', title: '', message: '' })
  // L'export des réquisitions est le plus coûteux des cinq (premier de l'ordre
  // de bascule, §6 de docs/architecture-exports-asynchrones-20260828.md) : c'est
  // celui dont l'attente sera la plus longue, donc celui où un bouton inerte se
  // paie en clics répétés — et en jobs créés pour rien.
  const [exportExcelEnCours, setExportExcelEnCours] = useState(false)
  const [showValidationColumns, setShowValidationColumns] = useState(true)

  const [activeTab, setActiveTab] = useState<'classique' | 'remboursement_transport'>('classique')
  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterModePaiement, setFilterModePaiement] = useState<string>('')
  const [filterBudgetPosteId, setFilterBudgetPosteId] = useState<string>('')
  const [filterObjet, setFilterObjet] = useState<string>('')
  const filterServiceId = serviceParam ?? ''
  const setFilterServiceId = (value: string) => {
    const nextParams = new URLSearchParams(searchParams)
    if (value) {
      nextParams.set('service_id', value)
    } else {
      nextParams.delete('service_id')
    }
    setSearchParams(nextParams, { replace: true })
  }
  const today = useMemo(() => format(new Date(), 'yyyy-MM-dd'), [])
  const defaultDateDebut = useMemo(() => format(subDays(new Date(), 30), 'yyyy-MM-dd'), [])
  const [dateDebut, setDateDebut] = useState(defaultDateDebut)
  const [dateFin, setDateFin] = useState(today)
  const [sortField, setSortField] = useState<'created_at' | 'montant_total' | ''>('')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(1)
  const [selectedDraftDossierId, setSelectedDraftDossierId] = useState('')
  const [editDossierId, setEditDossierId] = useState<string | null>(null)
  const [editDossierDescription, setEditDossierDescription] = useState('')
  const [draftDossierPage, setDraftDossierPage] = useState(0)
  const draftDossierPageSize = 10

  const [formData, setFormData] = useState({
    objet: '',
    // Date métier, pré-remplie au jour courant mais modifiable : une réquisition
    // papier saisie en retard doit pouvoir porter sa date réelle.
    date_requisition: new Date().toISOString().slice(0, 10),
    mode_paiement: 'cash' as ModePaiement,
    compte_bancaire_id: '',
    type_requisition: 'classique' as 'classique' | 'remboursement_transport',
    nature_requisition: 'BUDGETAIRE' as 'BUDGETAIRE' | 'HORS_BUDGET' | 'FONDS_DE_TIERS',
    montant_autorise: '',
    service_id: '',
    beneficiaire: '',
    tiers_organisation_id: null as number | null,
    tiers_nom_libre: '',
    a_valoir: false,
    decaissement_progressif: false,
    instance_beneficiaire: '',
    notes_a_valoir: ''
  })
  const [instanceBeneficiaireSelection, setInstanceBeneficiaireSelection] = useState<number | null>(null)
  const [annexeFile, setAnnexeFile] = useState<File | null>(null)
  const [annexeError, setAnnexeError] = useState('')
  const [expandedBudgetIds, setExpandedBudgetIds] = useState<Set<number>>(() => new Set())
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const budgetLoadSeqRef = useRef(0)
  const draftIdSeqRef = useRef(0)
  const makeDraftId = (prefix: string) => {
    draftIdSeqRef.current += 1
    return `${prefix}-${draftIdSeqRef.current}`
  }

  const [groupesDepense, setGroupesDepense] = useState<GroupeDepenseDraft[]>(() =>
    groupLignesByBudgetPoste(
      [{ budget_poste_id: null, rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0, devise: 'USD' }],
      makeDraftId,
    )
  )
  const lignes = useMemo(() => flattenLignes(groupesDepense), [groupesDepense])
  // Règlement ligne par ligne : masqué par défaut. La quasi-totalité des
  // réquisitions est mono-mode ; leur imposer une colonne de plus alourdirait la
  // saisie courante pour un besoin marginal.
  const [reglementParLigne, setReglementParLigne] = useState(false)
  // Le décaissement progressif devient obligatoire dès qu'il y a plusieurs
  // volets. On mémorise le choix propre du demandeur pour le lui rendre s'il
  // revient à un règlement unique, plutôt que de laisser une case cochée par
  // une contrainte qui n'existe plus.
  const choixProgressifRef = useRef(false)

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    const openForm = searchParams.get('new')
    if (effectiveServiceParam) {
      setFormData((prev) => ({ ...prev, service_id: effectiveServiceParam }))
    }
    if (openForm === '1' || openForm === 'true') {
      setActiveTab('classique')
      // ?new=1 (venant du portail service) redirige vers la page de création
      // dédiée en conservant le ?service_id= qui verrouille la commission.
      const nextParams = new URLSearchParams(searchParams)
      nextParams.delete('new')
      const search = nextParams.toString()
      navigate({ pathname: '/requisitions/nouvelle', search: search ? `?${search}` : '' }, { replace: true })
    }
  }, [searchParams, effectiveServiceParam, navigate])

  useEffect(() => {
    if (!isCreatePage) return
    setFormData((prev) => ({ ...prev, type_requisition: activeTab }))
  }, [activeTab, isCreatePage])

  useEffect(() => {
    if (formData.mode_paiement !== 'virement') {
      if (formData.compte_bancaire_id) {
        setFormData((prev) => ({ ...prev, compte_bancaire_id: '' }))
      }
      return
    }
    const bankAccounts = comptesBancaires.filter(
      (compte) => String(compte.account_type || 'BANK').toUpperCase() === 'BANK'
    )
    const current = bankAccounts.find((compte) => String(compte.id) === String(formData.compte_bancaire_id))
    if (current) return
    const nextId = bankAccounts.length === 1 ? String(bankAccounts[0].id) : ''
    if (String(nextId) !== String(formData.compte_bancaire_id || '')) {
      setFormData((prev) => ({ ...prev, compte_bancaire_id: nextId }))
    }
  }, [formData.mode_paiement, formData.compte_bancaire_id, comptesBancaires])


  const requisitionsQueryKey = ['requisitions', filterServiceId, filterBudgetPosteId] as const

  const requisitionsQuery = useQuery({
    queryKey: requisitionsQueryKey,
    queryFn: async () => {
      const resp = await apiRequest('GET', '/requisitions', {
        params: {
          include: 'demandeur,validateur,approbateur,examinateur,caissier',
          date_debut: dateDebut,
          date_fin: dateFin,
          status: filterStatut || undefined,
          mode_paiement: filterModePaiement || undefined,
          type_requisition: activeTab,
          search: searchQuery || undefined,
          objet: filterObjet || undefined,
          ...(filterServiceId ? { service_id: Number(filterServiceId) } : {}),
          ...(filterBudgetPosteId ? { budget_poste_id: Number(filterBudgetPosteId) } : {}),
          limit: 5000,
          offset: 0,
        }
      })
      return (Array.isArray(resp) ? resp : (resp as any)?.items ?? (resp as any)?.data ?? []) as any[]
    },
  })

  const requisitions = requisitionsQuery.data ?? []

  const refetchRequisitions = () => queryClient.invalidateQueries({ queryKey: ['requisitions'] })

  useEffect(() => {
    if (!requisitionsQuery.error) return
    console.error('Erreur chargement réquisitions:', requisitionsQuery.error)
    setNotification({
      show: true,
      type: 'error',
      title: 'Erreur de chargement',
      message: (requisitionsQuery.error as any)?.message || 'Impossible de charger les réquisitions pour ce filtre.'
    })
  }, [requisitionsQuery.error])

  const loadFilterBudgetOptions = async () => {
    const resp = await getBudgetPostes({ type: 'DEPENSE', active: true })
    const items = resp?.postes ?? []
    items.sort((a: any, b: any) => compareBudgetCodes(a.code, b.code))
    setFilterBudgetOptions(items)
  }

  // Les postes proposés sont exactement ceux rattachés au service choisi
  // (ServiceRubrique côté API). Sans service, aucun poste : proposer le budget
  // complet mènerait à une réquisition créée puis des lignes refusées en 403.
  const loadBudgetPostes = async (serviceId?: string) => {
    const loadSeq = ++budgetLoadSeqRef.current
    if (!serviceId) {
      setBudgetPostes([])
      return
    }
    try {
      const resp: any = await apiRequest('GET', '/budget/lines/autorisees', {
        params: {
          type: 'DEPENSE',
          active: true,
          service_id: Number(serviceId),
        },
      })
      const items = resp?.lignes ?? []
      if (loadSeq !== budgetLoadSeqRef.current) return
      setBudgetPostes(items)
    } catch (error) {
      console.error('Error loading allowed budget postes:', error)
      if (loadSeq !== budgetLoadSeqRef.current) return
      // Un échec ne doit pas laisser en place la liste du service précédent.
      setBudgetPostes([])
    }
  }

  const loadServiceBudgetPostes = async (serviceId: string) => {
    if (!serviceId) {
      setServiceBudgetLines([])
      return
    }
    try {
      const resp: any = await apiRequest('GET', '/budget/lines/autorisees', {
        params: {
          type: 'DEPENSE',
          active: true,
          service_id: Number(serviceId),
        },
      })
      const items = resp?.lignes ?? []
      setServiceBudgetLines(items)
    } catch (error) {
      console.error('Error loading service budget lines:', error)
      setServiceBudgetLines([])
    }
  }

  const loadServices = async () => {
    const resp = await getServices({ active: true })
    const items = Array.isArray(resp) ? resp : []
    setServices(items)
  }

  const loadComptesBancaires = async () => {
    const resp = await listComptesBancaires({ active: true, account_type: 'BANK' })
    setComptesBancaires(Array.isArray(resp) ? resp : [])
  }

  const loadDraftDossiers = async () => {
    const resp: any = await apiRequest('GET', '/dossiers/drafts', {
      params: { limit: 200 },
    })
    const items = Array.isArray(resp) ? resp : (resp?.items ?? [])
    setDraftDossiers(items)
  }
  
  const loadSettings = async () => {
    try {
      const settings = await getPrintSettings()
      setPrintSettings(settings)
    } catch (error) {
      console.error('Error loading settings:', error)
      setPrintSettings(null)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      await Promise.all([
        refetchRequisitions(),
        loadFilterBudgetOptions(),
        loadServices(),
        loadComptesBancaires(),
        loadDraftDossiers(),
        loadSettings(),
      ])
    } catch (error) {
      console.error('Error loading data:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de chargement',
        message: 'Impossible de charger les données. Veuillez vérifier la connexion au serveur.'
      })
    } finally {
      setLoading(false)
    }
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
      console.error('Erreur ouverture annexe:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur pièce jointe',
        message: "Impossible d'ouvrir la pièce jointe de la réquisition."
      })
    }
  }

  useEffect(() => {
    loadServiceBudgetPostes(formData.service_id)
  }, [formData.service_id])

  const selectableServices = useMemo(() => {
    if (!isServiceUser) return services
    if (!serviceIds.length) return services
    return services.filter((service) => serviceIds.includes(service.id))
  }, [services, isServiceUser, serviceIds])
  const servicesById = useMemo(() => {
    return new Map(services.map((service) => [String(service.id), service]))
  }, [services])
  const filterServiceLabel = useMemo(() => {
    if (!filterServiceId) return ''
    const service = servicesById.get(filterServiceId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${filterServiceId}`
  }, [filterServiceId, servicesById])
  const defaultServiceId = useMemo(() => {
    if (effectiveServiceParam) return effectiveServiceParam
    if (isServiceUser && selectableServices.length === 1) return String(selectableServices[0].id)
    return ''
  }, [effectiveServiceParam, isServiceUser, selectableServices])
  const isServiceLockedByContext =
    Boolean(effectiveServiceParam) || (isServiceUser && selectableServices.length === 1)

  useEffect(() => {
    if (defaultServiceId && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: defaultServiceId }))
    }
  }, [defaultServiceId, formData.service_id])

  useEffect(() => {
    if (!formData.service_id) return
    setGroupesDepense((prev) =>
      prev.map((groupe) => ({
        ...groupe,
        budget_poste_id: null,
        rubrique: '',
        budgetSearch: '',
        showBudgetDropdown: false,
      }))
    )
  }, [formData.service_id])

  useEffect(() => {
    const targetServiceId = formData.service_id || defaultServiceId
    if (targetServiceId) {
      loadBudgetPostes(targetServiceId)
      return
    }
    loadBudgetPostes()
  }, [formData.service_id, defaultServiceId])

  const addGroupeDepense = () => {
    const groupId = makeDraftId('poste')
    setGroupesDepense((prev) => [
      ...prev,
      {
        id: groupId,
        budget_poste_id: null,
        rubrique: '',
        budgetSearch: '',
        showBudgetDropdown: false,
        lignes: [nouvelleLigneDepense(makeDraftId('ligne'))],
      },
    ])
    setActiveGroupId(groupId)
  }

  const addLigne = (groupId: string) => {
    setGroupesDepense((prev) =>
      prev.map((groupe) =>
        groupe.id === groupId
          ? { ...groupe, lignes: [...groupe.lignes, nouvelleLigneDepense(makeDraftId('ligne'))] }
          : groupe
      )
    )
    setActiveGroupId(groupId)
  }

  const removeGroupeDepense = (groupId: string) => {
    setGroupesDepense((prev) => {
      const next = prev.filter((groupe) => groupe.id !== groupId)
      if (next.length > 0) return next
      const fallbackId = makeDraftId('poste')
      return [{
        id: fallbackId,
        budget_poste_id: null,
        rubrique: '',
        budgetSearch: '',
        showBudgetDropdown: false,
        lignes: [nouvelleLigneDepense(makeDraftId('ligne'))],
      }]
    })
    setActiveGroupId((prev) => (prev === groupId ? null : prev))
  }

  const removeLigne = (groupId: string, lineId: string) => {
    setGroupesDepense((prev) =>
      prev.map((groupe) => {
        if (groupe.id !== groupId) return groupe
        const nextLignes = groupe.lignes.filter((ligne) => ligne.id !== lineId)
        return { ...groupe, lignes: nextLignes.length > 0 ? nextLignes : [nouvelleLigneDepense(makeDraftId('ligne'))] }
      })
    )
  }

  const updateGroupePoste = (groupId: string, budgetPosteId: number | null, rubrique?: string) => {
    const selected = budgetPosteId ? budgetLinesById.get(Number(budgetPosteId)) : null
    const label = rubrique ?? (selected ? `${selected.code} - ${selected.libelle}` : '')
    setGroupesDepense((prev) =>
      prev.map((groupe) =>
        groupe.id === groupId
          ? { ...groupe, budget_poste_id: budgetPosteId, rubrique: label, budgetSearch: label }
          : groupe
      )
    )
  }

  const updateGroupeSearch = (groupId: string, value: string) => {
    setGroupesDepense((prev) =>
      prev.map((groupe) =>
        groupe.id === groupId
          ? { ...groupe, budget_poste_id: null, rubrique: '', budgetSearch: value, showBudgetDropdown: true }
          : groupe
      )
    )
  }

  const setGroupeDropdown = (groupId: string, show: boolean) => {
    setGroupesDepense((prev) =>
      prev.map((groupe) =>
        groupe.id === groupId ? { ...groupe, showBudgetDropdown: show } : groupe
      )
    )
  }

  const updateLigne = (groupId: string, lineId: string, field: string, value: any) => {
    setGroupesDepense((prev) =>
      prev.map((groupe) => {
        if (groupe.id !== groupId) return groupe
        return {
          ...groupe,
          lignes: groupe.lignes.map((ligne) => {
            if (ligne.id !== lineId) return ligne
            const next = { ...ligne, [field]: value }
            if (field === 'quantite' || field === 'montant_unitaire') {
              const quantite = Number(next.quantite || 0)
              const montantUnitaire = toNumber(next.montant_unitaire || 0)
              next.montant_total = quantite * montantUnitaire
            }
            return next
          }),
        }
      })
    )
  }

  // Dérogation de règlement sur une ligne. Le compte est pré-rempli avec celui
  // du règlement global (ou l'unique compte du tenant) : le cas « une autre
  // banque » reste une modification, pas une saisie repartie de zéro.
  const changerModeLigne = (groupId: string, lineId: string, mode: '' | 'cash' | 'virement') => {
    setGroupesDepense((prev) =>
      prev.map((groupe) => {
        if (groupe.id !== groupId) return groupe
        return {
          ...groupe,
          lignes: groupe.lignes.map((ligne) => {
            if (ligne.id !== lineId) return ligne
            if (!mode) return { ...ligne, mode_paiement: null, compte_bancaire_id: null }
            if (mode === 'cash') return { ...ligne, mode_paiement: 'cash', compte_bancaire_id: null }
            const compteDefaut =
              reglementGlobal.compteId ?? (comptesBancaires.length === 1 ? Number(comptesBancaires[0].id) : null)
            return {
              ...ligne,
              mode_paiement: 'virement',
              compte_bancaire_id: ligne.compte_bancaire_id ?? compteDefaut,
            }
          }),
        }
      })
    )
  }

  // Refermer le règlement par ligne efface les dérogations : laisser des lignes
  // divergentes derrière un bloc masqué ferait basculer la réquisition en mixte
  // sans que l'écran ne le montre nulle part.
  const activerReglementParLigne = (actif: boolean) => {
    setReglementParLigne(actif)
    if (!actif) {
      setGroupesDepense((prev) =>
        prev.map((groupe) => ({
          ...groupe,
          lignes: groupe.lignes.map((ligne) => ({ ...ligne, mode_paiement: null, compte_bancaire_id: null })),
        }))
      )
    }
  }

  const exchangeRate = printSettings?.exchange_rate_cdf
    ? Number(printSettings.exchange_rate_cdf)
    : printSettings?.exchange_rate
      ? Number(printSettings.exchange_rate)
      : 0
  const toUsd = (amount: Money | null | undefined, devise: 'USD' | 'CDF') => {
    const numericAmount = toNumber(amount ?? 0)
    if (devise === 'USD') return numericAmount
    if (!exchangeRate) return numericAmount
    return numericAmount / exchangeRate
  }

  const getAiBadge = (reqId: string) => {
    if (!aiEnabled) return null
    const score = aiScores[String(reqId)]
    if (!score) {
      return (
        <span className={`${styles.aiBadge} ${styles.aiBadgeLoading}`} title="Analyse IA en cours">
          <Sparkles size={12} />IA…
        </span>
      )
    }

    const levelClass =
      score.level === 'ELEVE'
        ? styles.aiBadgeHigh
        : score.level === 'MOYEN'
        ? styles.aiBadgeMedium
        : styles.aiBadgeLow

    const reasons = Array.isArray(score.reasons) ? score.reasons.join(' ') : ''
    const tooltip = `Score ${score.risk_score}/100 • ${score.explanation}${reasons ? ` ${reasons}` : ''}`
    return (
      <span className={`${styles.aiBadge} ${levelClass}`} title={tooltip}>
        <Sparkles size={12} />IA {score.risk_score}
      </span>
    )
  }

  const calculateTotalUsd = () => {
    return lignes.reduce((sum, ligne) => {
      const devise = (ligne as any).devise || 'USD'
      return sum + toUsd(ligne.montant_total, devise)
    }, 0)
  }

  // Délègue au module extrait : le sous-total affiché et celui qu'oppose le
  // contrôle de dépassement doivent être le même calcul, pas deux jumeaux.
  const getGroupeSousTotalUsd = (groupe: GroupeDepenseDraft) => sousTotalGroupeUsd(groupe, toUsd)

  // Règlement de référence de la pièce : celui du bloc « Règlement ». Toute
  // ligne qui n'a pas explicitement dérogé s'y rattache.
  const reglementGlobal = useMemo(
    () => ({
      mode: formData.mode_paiement,
      compteId:
        formData.mode_paiement === 'virement' && formData.compte_bancaire_id
          ? Number(formData.compte_bancaire_id)
          : null,
    }),
    [formData.mode_paiement, formData.compte_bancaire_id]
  )

  // Découpage en volets, calculé comme côté serveur (services/reglement.py) pour
  // que l'écran annonce exactement ce que le backend enregistrera. Un volet
  // caisse n'a jamais de compte : le neutraliser évite de scinder en deux un
  // règlement espèces à cause d'un compte resté sélectionné.
  const volets = useMemo<VoletSaisie[]>(() => {
    const parCle = new Map<string, VoletSaisie>()
    lignes.forEach((ligne, index) => {
      const mode = (ligne.mode_paiement || reglementGlobal.mode) as ModePaiement
      const compteId =
        mode === 'virement'
          ? ligne.mode_paiement
            ? ligne.compte_bancaire_id ?? null
            : reglementGlobal.compteId
          : null
      const cle = `${mode}:${compteId ?? ''}`
      const montantUsd = toUsd(ligne.montant_total, ((ligne as any).devise || 'USD') as 'USD' | 'CDF')
      const existant = parCle.get(cle)
      if (existant) {
        existant.montantUsd += montantUsd
        existant.numerosLignes.push(index + 1)
      } else {
        parCle.set(cle, { mode, compteId, montantUsd, numerosLignes: [index + 1] })
      }
    })
    return Array.from(parCle.values())
  }, [lignes, reglementGlobal, exchangeRate])

  const reglementMixte = volets.length > 1

  // Deux volets qui partagent le mode mais visent deux comptes différents ne
  // rendent pas la pièce « mixte » : elle reste `virement`. Le règlement est
  // bien scindé, mais le mode affiché doit rester juste (resume_mode_paiement).
  const modeResumeReglement = useMemo(() => {
    if (!volets.length) return formData.mode_paiement as string
    const modes = new Set(volets.map((volet) => volet.mode))
    return modes.size > 1 ? MODE_PAIEMENT_MIXTE : volets[0].mode
  }, [volets, formData.mode_paiement])

  // Un règlement scindé ne peut pas être soldé en un seul paiement : la case est
  // cochée d'office et verrouillée tant que les volets sont multiples.
  useEffect(() => {
    setFormData((prev) => {
      const cible = reglementMixte ? true : choixProgressifRef.current
      return prev.decaissement_progressif === cible
        ? prev
        : { ...prev, decaissement_progressif: cible }
    })
  }, [reglementMixte])

  const libelleCompteBancaire = (compteId: number | null) => {
    if (!compteId) return 'compte à désigner'
    const compte = comptesBancaires.find((item) => Number(item.id) === compteId)
    return compte ? `${compte.banque?.nom || 'Banque'} - ${compte.intitule}` : `Compte #${compteId}`
  }

  const MAX_ANNEXE_SIZE = 3 * 1024 * 1024
  const ALLOWED_ANNEXE_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']

  const validateAnnexe = (file: File) => {
    if (!ALLOWED_ANNEXE_TYPES.includes(file.type)) {
      return 'Format non autorisé (PDF, JPG, PNG).'
    }
    if (file.size > MAX_ANNEXE_SIZE) {
      return 'Fichier trop volumineux (max 3 Mo).'
    }
    return ''
  }

  const setAnnexeSelection = (file: File | null) => {
    if (!file) {
      setAnnexeFile(null)
      setAnnexeError('')
      return
    }
    const error = validateAnnexe(file)
    setAnnexeError(error)
    if (!error) {
      setAnnexeFile(file)
    } else {
      setAnnexeFile(null)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (submitting) return

    const isNatureBudgetaire = formData.nature_requisition === 'BUDGETAIRE'

    if (!formData.objet || (isNatureBudgetaire && lignes.length === 0)) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Informations manquantes',
        message: isNatureBudgetaire
          ? 'Veuillez remplir l\'objet de la réquisition et ajouter au moins une ligne de dépense.'
          : 'Veuillez remplir l\'objet de la réquisition.'
      })
      return
    }
    if (!isNatureBudgetaire && toNumber(formData.montant_autorise) <= 0) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Montant requis',
        message: 'Le montant autorisé doit être strictement positif.'
      })
      return
    }

    const invalidLigne = isNatureBudgetaire ? lignes.find(
      (l) => !l.budget_poste_id || !l.description || toNumber(l.montant_unitaire) <= 0
    ) : undefined
    if (invalidLigne) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Lignes incomplètes',
        message: 'Toutes les lignes doivent avoir un poste budgétaire, une description et un montant positif.'
      })
      return
    }

    const depassement = isNatureBudgetaire
      ? trouverGroupeEnDepassement(groupesDepense, {
          toUsd,
          disponiblePourPoste: (posteId) => {
            const budgetLine = posteId ? budgetLinesById.get(Number(posteId)) : null
            return budgetLine ? toNumber(budgetLine.montant_disponible) : null
          },
          // Un groupe sans poste connu ne peut pas être garanti tenir dans un
          // budget : à la validation de la pièce, il compte comme dépassement.
          groupeSansPosteDepasse: true,
        })
      : undefined
    if (depassement && printSettings?.budget_block_overrun) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Dépassement budgétaire',
        message: 'Au moins un poste budgétaire dépasse le disponible.'
      })
      return
    }

    if (!formData.service_id) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Service requis',
        message: 'Le choix d’une commission/service est obligatoire pour cette réquisition.'
      })
      return
    }

    if (formData.service_id && isNatureBudgetaire) {
      const overrunGroup = trouverGroupeEnDepassement(groupesDepense, {
        toUsd,
        disponiblePourPoste: (posteId) => {
          const serviceLine = posteId ? serviceBudgetLinesById.get(Number(posteId)) : null
          return serviceLine ? toNumber(serviceLine.montant_disponible) : null
        },
        // Ici on contrôle l'allocation du SERVICE : un groupe dont le poste n'y
        // figure pas est hors sujet, pas en dépassement.
        groupeSansPosteDepasse: false,
      })
      if (overrunGroup) {
        const budgetLine = overrunGroup.budget_poste_id
          ? budgetLinesById.get(Number(overrunGroup.budget_poste_id))
          : null
        const confirmed = await confirm({
          title: 'Dépassement budgétaire',
          description: `Attention, cette dépense dépasse l’allocation budgétaire prévue pour ce service${budgetLine?.code ? ` (${budgetLine.code})` : ''}.\n\nSouhaitez-vous continuer ?`,
          confirmText: 'Continuer',
          cancelText: 'Annuler',
          variant: 'danger',
        })
        if (!confirmed) {
          setNotification({
            show: true,
            type: 'warning',
            title: 'Dépassement (service)',
            message: 'Création annulée. Ajustez le montant ou le service.'
          })
          return
        }
      }
    }

    if (annexeError) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Annexe invalide',
        message: annexeError
      })
      return
    }

    // Garde-fou : des lignes en CDF sans taux de change seraient additionnées
    // comme si elles étaient en USD → montant total faux. On bloque.
    const hasCdfLine = isNatureBudgetaire && lignes.some((l) => ((l as any).devise || 'USD') === 'CDF')
    if (hasCdfLine && (!exchangeRate || exchangeRate <= 0)) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Taux de change manquant',
        message: 'Des lignes sont en CDF mais aucun taux de change n’est défini. Renseignez le taux (réglages) avant de créer la réquisition, sinon le montant total serait erroné.'
      })
      return
    }

    // Un volet bancaire sans compte serait refusé par l'API : on le dit ici,
    // avec le numéro de ligne, plutôt que de laisser remonter un 400 opaque.
    const voletSansCompte = isNatureBudgetaire
      ? volets.find((volet) => volet.mode === 'virement' && !volet.compteId)
      : undefined
    if (voletSansCompte) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Compte bancaire manquant',
        message: `Un règlement par banque doit désigner un compte (ligne${voletSansCompte.numerosLignes.length > 1 ? 's' : ''} ${voletSansCompte.numerosLignes.join(', ')}).`
      })
      return
    }

    // Une avance à valoir sans instance bénéficiaire est une créance que
    // personne ne doit : le champ est un identifiant tenu à part, l'attribut
    // `required` du HTML ne le couvre pas.
    if (formData.a_valoir && !formData.instance_beneficiaire.trim()) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Instance bénéficiaire manquante',
        message: "Une réquisition à valoir doit désigner l'instance qui remboursera."
      })
      return
    }

    // Hors budget : aucune ligne, aucun poste. Le bénéficiaire est la seule
    // pièce qui dise à qui l'argent va, et la sortie de fonds en dérive le sien.
    if (formData.nature_requisition === 'HORS_BUDGET' && !formData.beneficiaire.trim()) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Bénéficiaire manquant',
        message: 'Une réquisition hors budget doit désigner son bénéficiaire.'
      })
      return
    }

    if (formData.nature_requisition === 'FONDS_DE_TIERS' && !formData.tiers_organisation_id && !formData.tiers_nom_libre.trim()) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Tiers requis',
        message: 'Une réquisition Fonds de tiers doit identifier le tiers concerné.'
      })
      return
    }

    setSubmitting(true)
    try {
      // Lignes envoyées avec la réquisition : le backend écrit les deux dans la
      // même transaction. Un refus sur une ligne (rubrique non autorisée,
      // dépassement…) n'enregistre plus une réquisition vide en arrière-plan.
      // Une ligne sans dérogation part sans règlement : c'est le backend qui la
      // fait hériter de la pièce, une seule règle d'héritage pour tout le monde.
      const lignesPayload = isNatureBudgetaire ? lignes.map(l => {
        const devise = (l as any).devise || 'USD'
        return {
          ...l,
          montant_unitaire: toUsd(l.montant_unitaire, devise),
          montant_total: toUsd(l.montant_total, devise),
          mode_paiement: l.mode_paiement ?? null,
          compte_bancaire_id: l.mode_paiement === 'virement' ? l.compte_bancaire_id ?? null : null,
        }
      }) : null

      const reqRes: any = await apiRequest('POST', '/requisitions', {
        objet: formData.objet,
        date_requisition: formData.date_requisition || null,
        mode_paiement: formData.mode_paiement,
        compte_bancaire_id: formData.mode_paiement === 'virement' && formData.compte_bancaire_id
          ? Number(formData.compte_bancaire_id)
          : null,
        type_requisition: 'classique',
        nature_requisition: formData.nature_requisition,
        montant_total: isNatureBudgetaire ? calculateTotalUsd() : toNumber(formData.montant_autorise),
        devise: 'USD',
        status: 'BROUILLON',
        service_id: Number(formData.service_id),
        created_by: user?.id,
        beneficiaire: formData.beneficiaire || null,
        tiers_organisation_id: formData.nature_requisition === 'FONDS_DE_TIERS' ? formData.tiers_organisation_id : null,
        tiers_nom_libre: formData.nature_requisition === 'FONDS_DE_TIERS' && !formData.tiers_organisation_id
          ? formData.tiers_nom_libre
          : null,
        a_valoir: formData.a_valoir,
        decaissement_progressif: formData.decaissement_progressif,
        instance_beneficiaire: formData.a_valoir ? formData.instance_beneficiaire : null,
        notes_a_valoir: formData.a_valoir ? formData.notes_a_valoir : null,
        lignes: lignesPayload
      })

      const reqData = reqRes as any
      const numeroData = reqData.numero_requisition
      const lignesData = (lignesPayload || []).map(l => ({ ...l, requisition_id: reqData.id }))

      let pdfUploaded = false
      let annexeUploaded = false
      try {
        const pdfBlob = await generateSingleRequisitionPDF(
          reqData,
          lignesData,
          'blob',
          `${user?.prenom} ${user?.nom}`
        )
        if (pdfBlob) {
          const pdfForm = new FormData()
          pdfForm.append(
            'file',
            pdfBlob,
            `requisition_${reqData.numero_requisition || reqData.id}.pdf`
          )
          await apiRequest('POST', `/requisitions/${reqData.id}/pdf`, {
            params: { notify: !annexeFile },
            body: pdfForm
          })
          pdfUploaded = true
        }
      } catch (pdfError) {
        console.error('Error uploading requisition PDF:', pdfError)
        setNotification({
          show: true,
          type: 'warning',
          title: 'PDF requisition manquant',
          message: 'Le PDF n’a pas pu être uploadé. Le mail ne sera pas envoyé.'
        })
      }

      if (annexeFile && pdfUploaded) {
        const form = new FormData()
        form.append('file', annexeFile)
        await apiRequest('POST', `/requisitions/${reqData.id}/annexe`, { params: { notify: true }, body: form })
        annexeUploaded = true
      } else if (annexeFile && !pdfUploaded) {
        setNotification({
          show: true,
          type: 'warning',
          title: 'Annexe non envoyée',
          message: 'Veuillez réessayer après l’upload du PDF.'
        })
      }

      if (pdfUploaded && (!annexeFile || annexeUploaded)) {
        setNotification({
          show: true,
          type: 'success',
          title: 'Réquisition créée avec succès',
          message: `Votre réquisition a été créée et enregistrée comme brouillon.\n\nNuméro de réquisition : ${numeroData}\n\nLe PDF officiel a bien été sauvegardé.\n\nCliquez sur “Soumettre à l’examen” pour l’envoyer à l’étape d’examen.`
        })
      } else {
        setNotification({
          show: true,
          type: 'warning',
          title: 'Réquisition créée partiellement',
          message: `La réquisition ${numeroData} a été créée, mais le PDF officiel ou l’annexe n’a pas été sauvegardé correctement. Ne lancez pas la validation examen avant correction.`
        })
      }
      resetForm()
      loadData()
      // En page dédiée, on revient à la liste : la notification de succès reste
      // montée (même instance de composant) et s'affiche au-dessus du tableau.
      if (isCreatePage) navigate('/requisitions')
    } catch (error: any) {
      console.error('Error creating requisition:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de création',
        message: error?.message || 'Une erreur est survenue lors de la création de la réquisition. Veuillez vérifier les informations et réessayer.'
      })
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
      setFormData({
        objet: '',
        date_requisition: new Date().toISOString().slice(0, 10),
        mode_paiement: 'cash',
        compte_bancaire_id: '',
        type_requisition: 'classique',
        nature_requisition: 'BUDGETAIRE',
        montant_autorise: '',
        service_id: defaultServiceId,
        beneficiaire: '',
        tiers_organisation_id: null,
        tiers_nom_libre: '',
        a_valoir: false,
      decaissement_progressif: false,
      instance_beneficiaire: '',
      notes_a_valoir: ''
    })
    setInstanceBeneficiaireSelection(null)
    const groupId = makeDraftId('poste')
    setGroupesDepense([{
      id: groupId,
      budget_poste_id: null,
      rubrique: '',
      budgetSearch: '',
      showBudgetDropdown: false,
      lignes: [nouvelleLigneDepense(makeDraftId('ligne'))],
    }])
    setActiveGroupId(groupId)
    setReglementParLigne(false)
    choixProgressifRef.current = false
    setAnnexeFile(null)
    setAnnexeError('')
  }

  // Abandon de la saisie : on remet le formulaire à zéro et on revient à la liste.
  const closeCreationForm = () => {
    resetForm()
    navigate('/requisitions')
  }


  const viewDetails = async (req: Requisition) => {
    setSelectedRequisition(req)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const data = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      setSelectedLignes(data || [])
      // Les lignes (avec budget_poste_id) doivent vivre sur la réquisition pour que
      // le Plan de décaissement détecte le multi-postes et propose la répartition.
      setSelectedRequisition((prev) => (prev ? { ...prev, lignes: data || [] } : { ...req, lignes: data || [] }))

      const users: any = {}
      if ((req as any).demandeur) users.demandeur = (req as any).demandeur
      if ((req as any).validateur) users.validateur = (req as any).validateur
      if ((req as any).approbateur) users.approbateur = (req as any).approbateur

      setSelectedRequisitionUsers(users)
      setShowDetailModal(true)
    } catch (error: any) {
      console.error('Error loading requisition details:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de chargement',
        message: error?.message || 'Impossible de charger les détails de la réquisition. Veuillez réessayer.'
      })
    }
  }

  const printRequisition = async (requisition: Requisition) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisition.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

      if (!lignesData || lignesData.length === 0) {
        setNotification({
          show: true,
          type: 'error',
          title: 'Erreur',
          message: 'Aucune ligne de dépense trouvée pour cette réquisition'
        })
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'print',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error: any) {
      console.error('Error printing PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur d\'impression',
        message: error?.message || 'Impossible d\'imprimer. Veuillez réessayer.'
      })
    }
  }

  const downloadRequisition = async (requisition: Requisition) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisition.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

      if (!lignesData || lignesData.length === 0) {
        setNotification({
          show: true,
          type: 'error',
          title: 'Erreur',
          message: 'Aucune ligne de dépense trouvée pour cette réquisition'
        })
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'download',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error: any) {
      console.error('Error downloading PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de téléchargement',
        message: error?.message || 'Impossible de télécharger le PDF. Veuillez réessayer.'
      })
    }
  }

  const handleSort = (field: 'created_at' | 'montant_total') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc')
    }
  }

  const canSelectRequisition = (req: Requisition) => {
    const status = String((req as any).status ?? req.statut ?? '').toUpperCase()
    const examen = String((req as any).examen_status ?? '').toUpperCase()
    const isFinal = ['APPROUVEE', 'PAYEE', 'REJETEE'].includes(status)
    if (isFinal || examen === 'EXAMINE') return false
    if (req.dossier_id) return examen === 'NON_EXAMINE'
    return true
  }

  const toggleSelectRequisition = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((rid) => rid !== id) : [...prev, id]))
  }

  const clearSelection = () => {
    setSelectedIds([])
    setSelectedDraftDossierId('')
  }

  const toggleSelectPage = () => {
    const selectableIds = paginatedRequisitions.filter(canSelectRequisition).map((r) => String(r.id))
    const allSelected = selectableIds.length > 0 && selectableIds.every((rid) => selectedIds.includes(rid))
    setSelectedIds((prev) => {
      if (allSelected) {
        return prev.filter((rid) => !selectableIds.includes(rid))
      }
      const next = new Set([...prev, ...selectableIds])
      return Array.from(next)
    })
  }

  const handleCreateDossier = async () => {
    if (selectedIds.length === 0) return
    try {
      const res: any = await apiRequest('POST', '/dossiers', { requisition_ids: selectedIds })
      const dossierReference = res?.reference
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        title: 'Dossier créé',
        message: dossierReference
          ? `Dossier ${dossierReference} créé en brouillon. Vous pouvez le soumettre à l’examen quand vous le souhaitez.`
          : 'Dossier créé en brouillon. Vous pouvez le soumettre à l’examen quand vous le souhaitez.'
      })
      loadData()
    } catch (error) {
      console.error('Error creating dossier:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible de créer le dossier groupé. Veuillez réessayer.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const handleAddToDraftDossier = async () => {
    if (selectedIds.length === 0 || !selectedDraftDossierId) return
    try {
      await apiRequest('POST', `/dossiers/${selectedDraftDossierId}/add-requisitions`, {
        requisition_ids: selectedIds,
      })
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        title: 'Dossier mis à jour',
        message: 'Les réquisitions sélectionnées ont été ajoutées au dossier brouillon.'
      })
      loadData()
    } catch (error) {
      console.error('Error adding requisitions to dossier:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible d’ajouter les réquisitions au dossier.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const openEditDossier = (dossier: { id: string; description?: string | null }) => {
    setEditDossierId(dossier.id)
    setEditDossierDescription(dossier.description || '')
  }

  const closeEditDossier = () => {
    setEditDossierId(null)
    setEditDossierDescription('')
  }

  const handleUpdateDossierDescription = async () => {
    if (!editDossierId) return
    try {
      await apiRequest('PATCH', `/dossiers/${editDossierId}`, {
        description: editDossierDescription.trim() || null,
      })
      closeEditDossier()
      loadData()
    } catch (error) {
      console.error('Error updating dossier description:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible de modifier la description du dossier.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const handleDeleteDossier = async (dossierId: string) => {
    const confirmed = await confirm({
      title: 'Supprimer le dossier',
      description: 'Supprimer ce dossier brouillon ? Les réquisitions seront détachées.',
      confirmText: 'Supprimer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!confirmed) return
    try {
      await apiRequest('DELETE', `/dossiers/${dossierId}`)
      loadData()
    } catch (error) {
      console.error('Error deleting dossier:', error)
      await confirm({
        title: 'Erreur',
        description: 'Impossible de supprimer le dossier.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
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
        title: 'Dossier soumis',
        message: "Le dossier a été soumis à l’examen."
      })
      loadData()
    } catch (error) {
      console.error('Error submitting dossier:', error)
      await confirm({
        title: 'Erreur',
        description: "Impossible de soumettre le dossier à l'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const handleSubmitRequisitionExamen = async (req: Requisition) => {
    try {
      await apiRequest('POST', `/requisitions/${req.id}/submit-examen`)
      setNotification({
        show: true,
        type: 'success',
        title: 'Réquisition soumise',
        message: "La réquisition a été envoyée à l'examen."
      })
      loadData()
    } catch (error) {
      console.error('Error submitting requisition examen:', error)
      await confirm({
        title: 'Erreur',
        description: (error as any)?.message || "Impossible de soumettre la réquisition à l'examen.",
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const handleDeleteRequisition = async (req: Requisition) => {
    const confirmed = await confirm({
      title: 'Supprimer la réquisition',
      description: req.dossier_id
        ? 'Cette réquisition sera supprimée car son dossier est encore en brouillon.'
        : 'Supprimer cette réquisition ?',
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return

    try {
      await apiRequest('POST', `/requisitions/${req.id}/soft-delete`)
      setSelectedIds((prev) => prev.filter((id) => id !== String(req.id)))
      if (selectedRequisition?.id === req.id) {
        setShowDetailModal(false)
        setSelectedRequisition(null)
      }
      await loadData()
      setNotification({
        show: true,
        type: 'success',
        title: 'Réquisition supprimée',
        message: 'La réquisition a été supprimée.'
      })
    } catch (error: any) {
      console.error('Error deleting requisition:', error)
      await confirm({
        title: 'Suppression impossible',
        description: error?.message || 'La réquisition ne peut pas être supprimée.',
        confirmText: 'OK',
        hideCancel: true,
        variant: 'danger',
      })
    }
  }

  const requisitionsList = Array.isArray(requisitions) ? requisitions : []
  const selectedRequisitions = useMemo(
    () => requisitionsList.filter((req) => selectedIds.includes(String(req.id))),
    [requisitionsList, selectedIds]
  )
  const selectedDossierIds = useMemo(() => {
    const ids = new Set<string>()
    selectedRequisitions.forEach((req) => {
      if (req.dossier_id) ids.add(String(req.dossier_id))
    })
    return ids
  }, [selectedRequisitions])
  const selectedDossierId =
    selectedDossierIds.size === 1 && selectedRequisitions.every((req) => req.dossier_id)
      ? Array.from(selectedDossierIds)[0]
      : null
  const canCreateDossier = selectedRequisitions.length > 0 && selectedRequisitions.every((req) => !req.dossier_id)
  const canSubmitDossier = Boolean(selectedDossierId)
  const hasMixedDossierSelection =
    selectedRequisitions.length > 0 && !canCreateDossier && !canSubmitDossier
  const canAddToDraftDossier = canCreateDossier && draftDossiers.length > 0
  const draftDossierTotalPages = Math.max(1, Math.ceil(draftDossiers.length / draftDossierPageSize))
  const pagedDraftDossiers = draftDossiers.slice(
    draftDossierPage * draftDossierPageSize,
    (draftDossierPage + 1) * draftDossierPageSize
  )
  // Ton et libellé du sélecteur de nature, alignés sur les encaissements : la
  // couleur rappelle le régime en cours, la phrase dit ce qu'il implique.
  const natureToneClass = formData.nature_requisition === 'FONDS_DE_TIERS'
    ? styles.natureFunds
    : formData.nature_requisition === 'HORS_BUDGET'
      ? styles.natureOutOfBudget
      : styles.natureBudget
  const natureHelpText = formData.nature_requisition === 'FONDS_DE_TIERS'
    ? "Reversement de fonds appartenant à un tiers. Aucun poste budgétaire n'est consommé : identifiez le tiers et le montant autorisé."
    : formData.nature_requisition === 'HORS_BUDGET'
      ? 'Dépense autorisée sans imputation budgétaire immédiate. Elle pourra être régularisée et affectée au budget ultérieurement.'
      : 'Dépense rattachée au budget. Les lignes de dépense ci-dessous portent les postes imputés et fondent le montant total.'

  const budgetLinesById = useMemo(() => {
    return new Map(budgetLines.map(line => [line.id, line]))
  }, [budgetLines])
  const budgetLinesList = Array.isArray(budgetLines) ? budgetLines : []
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
      list.sort((a, b) => compareBudgetCodes(a.code, b.code))
      list.forEach((item) => sortNodes(item.children))
    }
    sortNodes(roots)
    return roots
  }, [budgetLinesList])
  const serviceBudgetLinesById = useMemo(() => {
    return new Map(serviceBudgetLines.map(line => [line.id, line]))
  }, [serviceBudgetLines])
  const activeServiceId = useMemo(() => {
    if (formData.service_id) return Number(formData.service_id)
    if (hasGlobalServiceAccess) return null
    if (serviceIds.length === 1) return serviceIds[0]
    return null
  }, [formData.service_id, hasGlobalServiceAccess, serviceIds])

  const serviceLabel = useMemo(() => {
    if (!activeServiceId) return ''
    const service = services.find((s) => s.id === activeServiceId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${activeServiceId}`
  }, [services, activeServiceId])


  const activeGroupe = groupesDepense.find((groupe) => groupe.id === activeGroupId) ?? groupesDepense[0] ?? null
  const activeBudgetLine = activeGroupe?.budget_poste_id
    ? budgetLinesById.get(Number(activeGroupe.budget_poste_id))
    : null
  const activeTotalUsd = activeGroupe
    ? activeGroupe.lignes.reduce((sum, ligne) => sum + toUsd(ligne.montant_total, (ligne.devise || 'USD') as 'USD' | 'CDF'), 0)
    : 0
  const activeDisponible = activeBudgetLine ? toNumber(activeBudgetLine.montant_disponible) : 0
  const activeSoldeApres = activeBudgetLine ? activeDisponible - activeTotalUsd : 0
  const activeMontantPrevu = activeBudgetLine ? toNumber(activeBudgetLine.montant_prevu) : 0
  const activeMontantEngage = activeBudgetLine ? toNumber(activeBudgetLine.montant_engage) : 0
  const activeConsumption = activeMontantPrevu > 0
    ? ((activeMontantEngage + activeTotalUsd) / activeMontantPrevu) * 100
    : 0
  const activeConsumptionClamped = Math.min(100, Math.max(0, activeConsumption))


  // Réétiquetage des groupes une fois les postes chargés : un groupe qui porte
  // déjà un id de poste mais pas encore son libellé le reçoit ici.
  useEffect(() => {
    setGroupesDepense((prev) => {
      let modifie = false
      const suivant = prev.map((groupe) => {
        if (groupe.budgetSearch || !groupe.budget_poste_id) return groupe
        const line = budgetLinesById.get(Number(groupe.budget_poste_id))
        if (!line) return groupe
        modifie = true
        const label = `${line.code} - ${line.libelle}`
        return { ...groupe, rubrique: label, budgetSearch: label }
      })
      // `prev.map` rend toujours un tableau NEUF, même quand aucun groupe ne
      // change : sans ce test, chaque chargement des postes provoquait un
      // re-rendu et le recalcul de `lignes` pour rien.
      return modifie ? suivant : prev
    })
  }, [budgetLinesById])

  useEffect(() => {
    if (!groupesDepense.length) return
    if (!activeGroupId || !groupesDepense.some((groupe) => groupe.id === activeGroupId)) {
      setActiveGroupId(groupesDepense[0].id)
    }
  }, [groupesDepense, activeGroupId])

  const filterBudgetTree = (query: string) => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return budgetTree

    const matches = (node: any) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      return code.includes(normalized) || libelle.includes(normalized)
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

  const selectBudgetPoste = (line: any, groupId: string) => {
    if ((line.children?.length || 0) > 0) return
    updateGroupePoste(groupId, line.id, `${line.code} - ${line.libelle}`)
    setActiveGroupId(groupId)
    setGroupeDropdown(groupId, false)
  }

  const BudgetDropdownNode = ({
    node,
    depth,
    expandedIds,
    onToggle,
    onSelect,
    forceExpand,
  }: {
    node: any
    depth: number
    expandedIds: Set<number>
    onToggle: (id: number, row?: HTMLElement | null) => void
    onSelect: (line: any) => void
    forceExpand: boolean
  }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = forceExpand || expandedIds.has(node.id)
    const disponibleLabel = hasChildren ? '' : formatCurrency(toNumber(node.montant_disponible ?? 0))
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
          <span className={styles.dropdownText}>
            <strong>{node.code}</strong> - {node.libelle}
          </span>
          {!hasChildren && (
            <span className={styles.dropdownMeta}>{disponibleLabel}</span>
          )}
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
                forceExpand={forceExpand}
              />
            ))}
          </div>
        )}
      </>
    )
  }
  const selectedLignesList = Array.isArray(selectedLignes) ? selectedLignes : []
  const getLignePosteLabel = (ligne: LigneRequisition) => {
    const code = String(ligne.budget_poste_code_snapshot || '').trim()
    const libelle = String(ligne.budget_poste_libelle_snapshot || '').trim()
    if (code && libelle) return `${code} - ${libelle}`
    if (code) return code
    if (libelle) return libelle
    return ligne.rubrique
  }
  const getRequisitionStatus = (req: Requisition) => {
    return normalizeStatusValue((req as any).status ?? (req as any).statut)
  }

  const canSubmitRequisitionExamen = (req: Requisition) => {
    const examenValue = String((req as any).examen_status ?? '').toUpperCase()
    const statusValue = getRequisitionStatus(req)
    const hasEligibleExamenStatus = examenValue === 'NON_EXAMINE' || examenValue === 'REJETE'
    const hasLines = (req as any).lignes_count == null ? true : Number((req as any).lignes_count) > 0
    if (req.dossier_id || !hasEligibleExamenStatus) return false
    return (
      Boolean((req as any).service_id) &&
      statusValue === 'SIGNEE_SERVICE' &&
      Boolean((req as any).signed_by_id) &&
      Boolean((req as any).signed_at) &&
      hasLines
    )
  }

  const canDeleteRequisition = (req: Requisition) => {
    return String((req as any).examen_status ?? '').toUpperCase() === 'NON_EXAMINE'
  }

  const normalizeStatusValue = (value: any) => {
    const raw = String(value ?? '').trim()
    if (!raw) return ''
    const upper = raw.toUpperCase()
    if (upper === 'BROUILLON') return 'BROUILLON'
    if (upper === 'SIGNEE_SERVICE') return 'SIGNEE_SERVICE'
    if (upper === 'EN_ATTENTE') return 'EN_ATTENTE'
    if (upper === 'AUTORISEE' || upper === 'VALIDEE' || upper === 'VALIDEE_TRESORERIE' || upper === 'VALIDE_TECHNIQUE') return 'AUTORISEE'
    if (upper === 'APPROUVEE') return 'APPROUVEE'
    if (upper === 'PAYEE' || upper === 'DECAISSE') return 'PAYEE'
    if (upper === 'REJETEE' || upper === 'REJETTE') return 'REJETEE'
    return upper
  }

  const statusKpis = [
    { status: '', label: 'Toutes', hint: 'Tous statuts' },
    ...['BROUILLON', 'SIGNEE_SERVICE', 'EN_ATTENTE', 'AUTORISEE', 'APPROUVEE', 'PAYEE', 'REJETEE'].map((status) => {
      const meta = getStatusMeta(status)
      return { status, label: meta.label, hint: meta.description || '' }
    }),
  ]

  const baseFilteredRequisitions = requisitionsList.filter(req => {
    if ((req as any).dossier_id) return false
    const reqTypeReq = (req as any).type_requisition || 'classique'
    if (reqTypeReq !== activeTab) return false

    const searchLower = searchQuery.toLowerCase()
    const demandeurFull = `${req.demandeur?.prenom || ''} ${req.demandeur?.nom || ''}`.trim().toLowerCase()
    const matchesSearch = searchLower === '' ||
      req.numero_requisition.toLowerCase().includes(searchLower) ||
      req.objet.toLowerCase().includes(searchLower) ||
      demandeurFull.includes(searchLower)

    const matchesMode = !filterModePaiement || req.mode_paiement === filterModePaiement
    const matchesObjet = !filterObjet || req.objet.toLowerCase().includes(filterObjet.toLowerCase())
    const matchesService = !filterServiceId || String(req.service_id ?? '') === filterServiceId

    if (!dateDebut && !dateFin) return matchesSearch && matchesMode && matchesObjet && matchesService

    const reqDate = new Date(req.created_at)
    const debut = dateDebut ? new Date(dateDebut) : null
    const fin = dateFin ? new Date(dateFin) : null
    if (debut) debut.setHours(0, 0, 0, 0)
    if (fin) fin.setHours(23, 59, 59, 999)

    const matchesDate = (!debut || reqDate >= debut) && (!fin || reqDate <= fin)

    return matchesSearch && matchesMode && matchesObjet && matchesService && matchesDate
  })

  const statusCounts = (() => {
    const counts: Record<string, number> = {}
    baseFilteredRequisitions.forEach((req) => {
      const normalized = normalizeStatusValue((req as any).status ?? (req as any).statut)
      if (!normalized) return
      counts[normalized] = (counts[normalized] || 0) + 1
    })
    return counts
  })()

  const filteredRequisitions = baseFilteredRequisitions
    .filter(req => {
      if (!filterStatut) return true
      return normalizeStatusValue((req as any).status ?? (req as any).statut) === filterStatut
    })
    .sort((a, b) => {
      if (!sortField) return 0

      let aVal: any = a[sortField]
      let bVal: any = b[sortField]

      if (sortField === 'created_at') {
        aVal = new Date(aVal).getTime()
        bVal = new Date(bVal).getTime()
      } else if (sortField === 'montant_total') {
        aVal = toNumber(aVal)
        bVal = toNumber(bVal)
      }

      if (sortDirection === 'asc') {
        return aVal > bVal ? 1 : -1
      } else {
        return aVal < bVal ? 1 : -1
      }
    })

  const hasActiveFilters = searchQuery !== '' || filterStatut !== '' || filterModePaiement !== '' || filterObjet !== '' || filterBudgetPosteId !== '' || filterServiceId !== ''

  useEffect(() => {
    setPage(1)
  }, [activeTab, searchQuery, filterStatut, filterModePaiement, filterObjet, filterBudgetPosteId, filterServiceId, dateDebut, dateFin, sortField, sortDirection, pageSize])

  useEffect(() => {
    setDraftDossierPage(0)
  }, [draftDossiers.length])

  const totalPages = Math.max(1, Math.ceil(filteredRequisitions.length / pageSize))
  const safePage = Math.min(page, totalPages)

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const startIndex = filteredRequisitions.length === 0 ? 0 : (safePage - 1) * pageSize + 1
  const endIndex = Math.min(safePage * pageSize, filteredRequisitions.length)
  const paginatedRequisitions = filteredRequisitions.slice((safePage - 1) * pageSize, safePage * pageSize)
  const selectablePageIds = useMemo(
    () => paginatedRequisitions.filter(canSelectRequisition).map((req) => String(req.id)),
    [paginatedRequisitions]
  )
  const allPageSelected =
    selectablePageIds.length > 0 && selectablePageIds.every((rid) => selectedIds.includes(rid))

  useEffect(() => {
    if (!aiEnabled) return
    const ids = paginatedRequisitions.map((req) => String(req.id))
    const missing = ids.filter((id) => id && !aiScores[id])
    if (missing.length === 0) return

    let cancelled = false
    const loadScores = async () => {
      try {
        const res = await scoreRequisitions({ requisition_ids: missing })
        if (cancelled) return
        setAiScores((prev) => {
          const next = { ...prev }
          res.forEach((score) => {
            next[String(score.requisition_id)] = score
          })
          return next
        })
      } catch (error) {
        console.error('Error loading AI scores:', error)
      }
    }
    loadScores()
    return () => {
      cancelled = true
    }
  }, [paginatedRequisitions, aiScores, aiEnabled])

  const clearFilters = () => {
    setSearchQuery('')
    setFilterStatut('')
    setFilterModePaiement('')
    setFilterObjet('')
    setFilterBudgetPosteId('')
    setFilterServiceId('')
    setSortField('')
    setSortDirection('desc')
  }

  const resetPeriod = () => {
    setDateDebut(defaultDateDebut)
    setDateFin(today)
  }

  const applyQuickPeriod = (days: number | 'all') => {
    if (days === 'all') {
      setDateDebut('')
      setDateFin('')
      return
    }
    setDateDebut(days === 0 ? today : format(subDays(new Date(), days), 'yyyy-MM-dd'))
    setDateFin(today)
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const formatCdf = (amount: number) => {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(amount)
  }

  const getStatutBadge = (statut: StatutRequisition | string) => {
    const meta = getStatusMeta(String(statut || '').toUpperCase())
    return (
      <span className={styles.badge} style={{ background: meta.bg, color: meta.color }}>
        {meta.label}
      </span>
    )
  }

  const getVisaBadge = (req: any) => {
    const statusValue = String(req?.status ?? req?.statut ?? '').toLowerCase()
    if (!statusValue) return null
    if (statusValue !== 'autorisee') return null
    return (
      <span className={styles.visaBadge} title="Validation 2/2 requise avant décaissement.">
        Validation 2/2 requise
      </span>
    )
  }

  const getPaymentStatusBadge = (req: Requisition) => {
    const statutValue = String((req as any).status ?? req.statut ?? '').toLowerCase()
    if (statutValue !== 'approuvee' && statutValue !== 'payee') {
      return null
    }

    const total = toNumber(req.montant_total)
    const paid = toNumber((req as any).montant_deja_paye ?? 0)
    const remaining = total - paid

    if (remaining <= 0) {
      return (
        <span className={`${styles.badge} ${styles.badgePaye}`}>
          <CheckCircle2 size={12} aria-hidden="true" />Payé
        </span>
      )
    }

    if (paid > 0) {
      return (
        <span className={`${styles.badge} ${styles.badgeAttente}`}>
          <ReceiptText size={12} aria-hidden="true" />Partiellement payée ({formatCurrency(remaining)})
        </span>
      )
    }

    return (
      <span className={`${styles.badge} ${styles.badgeAttente} ${styles.paymentPulse}`}>
        <Clock size={12} aria-hidden="true" />À payer ({formatCurrency(remaining)})
      </span>
    )
  }

  const canCreate = hasPermission('requisitions')

  const totalRequisitions = filteredRequisitions.reduce((sum, r) => sum + toNumber(r.montant_total), 0)

  const exportToExcel = async () => {
    if (exportExcelEnCours) return
    setExportExcelEnCours(true)
    try {
      const periodeSuffix = dateDebut || dateFin
        ? `_${dateDebut || 'debut'}_${dateFin || 'fin'}`
        : `_${format(new Date(), 'yyyy-MM-dd')}`
      // Export aligné sur le modèle budget : généré côté backend (openpyxl),
      // avec en-tête stylé, ligne TOTAL et feuille Synthèse.
      await downloadExcel(
        '/exports/requisitions',
        {
          date_debut: dateDebut || undefined,
          date_fin: dateFin || undefined,
          statut: filterStatut || undefined,
          service_id: filterServiceId ? Number(filterServiceId) : undefined,
          budget_poste_id: filterBudgetPosteId ? Number(filterBudgetPosteId) : undefined,
          search: searchQuery || undefined,
          objet: filterObjet || undefined,
          type_requisition: activeTab,
          mode_paiement: filterModePaiement || undefined,
        },
        `requisitions${periodeSuffix}.xlsx`,
        {
          // Le serveur a répondu 202 : le classeur se construit dans le worker.
          // Sans ce message, l'attente est indiscernable d'une interface figée.
          onMiseEnFile: () =>
            setNotification({
              show: true,
              type: 'info',
              title: 'Export en préparation',
              message:
                "Cet export est généré en arrière-plan. Laissez cette page ouverte : le téléchargement démarrera automatiquement dès que le fichier sera prêt.",
            }),
        }
      )
    } catch (error: any) {
      console.error('Error exporting Excel:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur export Excel',
        // Message du serveur d'abord : c'est lui qui sait si l'export a été
        // refusé pour cause de volume, et ce qu'il faut restreindre.
        message: error?.message || 'Impossible d’exporter le fichier Excel. Veuillez réessayer.'
      })
    } finally {
      setExportExcelEnCours(false)
    }
  }

  const exportToPDF = async () => {
    const dataForPDF = await Promise.all(
      filteredRequisitions.map(async (req) => {
        const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
        const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

        const posteBudgetaire = lignesData
          ? [...new Set(lignesData.map((l: any) => l.rubrique))].join(', ')
          : ''

        return {
          ...req,
          poste_budgetaire: posteBudgetaire,
          service_libelle: req.service_id
            ? (servicesById.get(String(req.service_id))?.libelle ?? '')
            : '',
        }
      })
    )

    const start = dateDebut || format(new Date(), 'yyyy-MM-dd')
    const end = dateFin || format(new Date(), 'yyyy-MM-dd')

    await generateRequisitionsReportPDF(dataForPDF, {
      dateDebut: start,
      dateFin: end,
      filters: [
        filterStatut ? { label: 'Statut', value: getStatusMeta(filterStatut).label } : null,
        filterModePaiement
          ? {
              label: 'Mode',
              value:
                filterModePaiement === 'cash'
                  ? 'Caisse'
                  : filterModePaiement === 'mobile_money'
                  ? 'Mobile Money'
                  : filterModePaiement === 'card'
                  ? 'Carte (Visa)'
                  : 'Opération bancaire',
            }
          : null,
        filterObjet ? { label: 'Objet', value: filterObjet } : null,
        filterServiceLabel ? { label: 'Service', value: filterServiceLabel } : null,
        searchQuery ? { label: 'Recherche', value: searchQuery } : null,
      ],
    })
  }

  if (loading || permissionsLoading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonGrid}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`req-skel-${idx}`} className={styles.skeletonCard}>
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
        title={isCreatePage ? 'Nouvelle réquisition' : 'Réquisitions de fonds'}
        subtitle={isCreatePage ? 'Demande de fonds et engagement budgétaire' : "Demandes et workflow d'approbation"}
        actions={
          isCreatePage ? (
            <div className={styles.headerActions}>
              <Link to="/" className={styles.breadcrumbLink}>Accueil</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <Link to="/requisitions" className={styles.breadcrumbLink}>Réquisitions</Link>
              <span className={styles.breadcrumbSeparator}>›</span>
              <span className={styles.breadcrumbCurrent}>Nouvelle réquisition</span>
              <Link to="/requisitions" className={styles.secondaryBtn}>
                Retour à la liste
              </Link>
              <button
                type="submit"
                form="requisition-form"
                className={styles.primaryBtn}
                disabled={submitting}
              >
                {submitting ? 'Création en cours...' : 'Enregistrer la réquisition'}
              </button>
            </div>
          ) : canCreate && (
            <div className={styles.headerActions}>
              <Link
                to="/requisitions/nouvelle"
                className={styles.primaryBtn}
                onClick={() => setFormData({ ...formData, type_requisition: 'classique' })}
              >
                + Nouvelle réquisition
              </Link>
            </div>
          )
        }
      />

      {!isCreatePage && (<>

      {filterServiceId && (
        <div className={styles.serviceContextBanner}>
          <span className={styles.serviceContextLabel}>
            Réquisitions filtrées sur le service : <strong>{filterServiceLabel}</strong>
          </span>
          <button
            type="button"
            className={styles.serviceContextClear}
            onClick={() => setFilterServiceId('')}
          >
            <X size={14} aria-hidden="true" /> Retirer le filtre
          </button>
        </div>
      )}

      <div className={styles.kpiGrid}>
        {statusKpis.map((item) => {
          const count = item.status ? (statusCounts[item.status] || 0) : baseFilteredRequisitions.length
          const isActive = filterStatut === item.status
          return (
            <button
              key={item.status || 'all'}
              type="button"
              className={`${styles.kpiCard} ${isActive ? styles.kpiCardActive : ''}`}
              onClick={() => {
                setFilterStatut((prev) => (prev === item.status ? '' : item.status))
                setPage(1)
              }}
            >
              <div className={styles.kpiLabel}>{item.label}</div>
              <div className={styles.kpiValue}>{count}</div>
              <div className={styles.kpiHint}>{item.hint}</div>
            </button>
          )
        })}
      </div>

      <div className={styles.filtersSection}>
        {draftDossiers.length > 0 && (
          <div className={styles.dossierSection}>
            <div className={styles.dossierHeader}>
              <h3>Dossiers brouillons</h3>
              <span>{draftDossiers.length} dossier{draftDossiers.length > 1 ? 's' : ''}</span>
            </div>
            <div className={styles.dossierTableWrap}>
              <table className={styles.dossierTable}>
                <thead>
                  <tr>
                    <th>Référence</th>
                    <th>Statut</th>
                    <th>Créé le</th>
                    <th className={styles.alignRight}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedDraftDossiers.map((dossier) => (
                    <tr key={dossier.id}>
                      <td className={styles.dossierRef}>{dossier.reference}</td>
                      <td>
                        <span className={styles.dossierBadge}>Brouillon</span>
                      </td>
                      <td>{format(new Date(dossier.created_at), 'dd/MM/yyyy')}</td>
                      <td className={styles.alignRight}>
                        <div className={styles.dossierActions}>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={() => navigate(`/requisitions/examen/${dossier.id}`)}
                          >
                            Ouvrir
                          </button>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={() => openEditDossier(dossier)}
                          >
                            Modifier description
                          </button>
                          <button
                            type="button"
                            className={styles.groupingPrimary}
                            onClick={() => handleSubmitDossier(dossier.id)}
                          >
                            Soumettre à l'examen
                          </button>
                          <button
                            type="button"
                            className={styles.groupingSecondary}
                            onClick={() => handleDeleteDossier(dossier.id)}
                          >
                            Supprimer
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {draftDossiers.length > draftDossierPageSize && (
              <div className={styles.dossierPagination}>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setDraftDossierPage((prev) => Math.max(0, prev - 1))}
                  disabled={draftDossierPage === 0}
                >
                  Précédent
                </button>
                <span className={styles.pageInfo}>
                  Page {draftDossierPage + 1} / {draftDossierTotalPages}
                </span>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setDraftDossierPage((prev) => Math.min(draftDossierTotalPages - 1, prev + 1))}
                  disabled={draftDossierPage >= draftDossierTotalPages - 1}
                >
                  Suivant
                </button>
              </div>
            )}
          </div>
        )}
        <div className={styles.filtersGrid}>
          <div className={styles.searchBar}>
            <label htmlFor="req-recherche">Recherche</label>
            <input
              id="req-recherche"
              type="text"
              placeholder="Rechercher par numéro ou objet..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Rechercher une réquisition par numéro ou objet"
            />
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-statut">Statut</label>
            <select id="req-filtre-statut" value={filterStatut} onChange={(e) => setFilterStatut(e.target.value)}>
              <option value="">Tous les statuts</option>
              {statusKpis.filter((item) => item.status).map((item) => (
                <option key={item.status} value={item.status}>{item.label}</option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-mode">Mode de paiement</label>
            <select id="req-filtre-mode" value={filterModePaiement} onChange={(e) => setFilterModePaiement(e.target.value)}>
              <option value="">Tous les modes</option>
              <option value="cash">Caisse</option>
              <option value="mobile_money">Mobile Money</option>
              <option value="virement">Opération bancaire</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-poste">Poste budgétaire</label>
            <select id="req-filtre-poste" value={filterBudgetPosteId} onChange={(e) => setFilterBudgetPosteId(e.target.value)}>
              <option value="">Tous les postes</option>
              {filterBudgetOptions.map((poste) => (
                <option key={poste.id} value={String(poste.id)}>
                  {poste.code} - {poste.libelle}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-service">Service / Commission</label>
            <select id="req-filtre-service" value={filterServiceId} onChange={(e) => setFilterServiceId(e.target.value)}>
              <option value="">Tous les services</option>
              {selectableServices.map((service) => (
                <option key={service.id} value={String(service.id)}>
                  {service.code} - {service.libelle}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-objet">Recherche objet</label>
            <input
              id="req-filtre-objet"
              type="text"
              value={filterObjet}
              onChange={(e) => setFilterObjet(e.target.value)}
              placeholder="Filtrer par objet..."
            />
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-date-debut">Date début</label>
            <input
              id="req-filtre-date-debut"
              type="date"
              value={dateDebut}
              onChange={(e) => setDateDebut(e.target.value)}
            />
          </div>

          <div className={styles.filterGroup}>
            <label htmlFor="req-filtre-date-fin">Date fin</label>
            <input
              id="req-filtre-date-fin"
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
            />
          </div>
        </div>
        <div className={styles.filtersActions}>
          <div className={styles.periodQuick} role="group" aria-label="Raccourcis de période">
            <button type="button" className={styles.periodQuickBtn} onClick={() => applyQuickPeriod(0)}>
              Aujourd'hui
            </button>
            <button type="button" className={styles.periodQuickBtn} onClick={() => applyQuickPeriod(7)}>
              7 jours
            </button>
            <button type="button" className={styles.periodQuickBtn} onClick={() => applyQuickPeriod(30)}>
              30 jours
            </button>
            <button type="button" className={styles.periodQuickBtn} onClick={() => applyQuickPeriod('all')}>
              Tout
            </button>
          </div>
          <div className={styles.pageSize}>
            <label htmlFor="req-page-size">Affichage</label>
            <select
              id="req-page-size"
              value={String(pageSize)}
              onChange={(e) => setPageSize(Number(e.target.value))}
            >
              <option value="20">20 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          <label className={styles.validationToggle}>
            <input
              type="checkbox"
              checked={showValidationColumns}
              onChange={(e) => setShowValidationColumns(e.target.checked)}
            />
            Validations 1/2 et 2/2
          </label>
          <span className={styles.actionsSpacer} />
          <button onClick={resetPeriod} className={styles.secondaryActionBtn}>
            Réinitialiser période
          </button>
          {hasActiveFilters && (
            <button onClick={clearFilters} className={styles.clearFiltersBtn}>
              Réinitialiser les filtres
            </button>
          )}
          {filteredRequisitions.length > 0 && (
            <>
              <button
                onClick={exportToExcel}
                className={`${styles.exportBtn} ${styles.exportExcel}`}
                disabled={exportExcelEnCours}
              >
                {exportExcelEnCours ? 'Export en cours…' : 'Exporter Excel'}
              </button>
              <button onClick={exportToPDF} className={`${styles.exportBtn} ${styles.exportPDF}`}>
                Exporter PDF
              </button>
            </>
          )}
        </div>

        <div className={styles.resultsInfo}>
          <p>
            <strong>{filteredRequisitions.length}</strong> réquisition{filteredRequisitions.length > 1 ? 's' : ''} trouvée{filteredRequisitions.length > 1 ? 's' : ''}
            <span className={styles.totalCount}> sur {requisitionsList.length} au total</span>
          </p>
          <p className={styles.resultsTotal}>
            Total période
            <strong>
              {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(totalRequisitions)}
            </strong>
            {exchangeRate > 0 && (
              <span className={styles.totalCount}>{formatCdf(totalRequisitions * exchangeRate)}</span>
            )}
          </p>
        </div>
      </div>

      <div className={styles.searchSticky}>
        <div className={styles.searchBox}>
          <span className={styles.searchIcon}><Search size={16} /></span>
          <input
            type="text"
            placeholder="Rechercher par numéro, objet ou demandeur..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInputMobile}
          />
          {searchQuery && (
            <button
              type="button"
              className={styles.searchClear}
              onClick={() => setSearchQuery('')}
              aria-label="Effacer la recherche"
            >
              <X size={16} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      </>)}

      {isCreatePage && (
        <div className={styles.createPageShell}>
          <div className={styles.createPageContent}>
            <form id="requisition-form" onSubmit={handleSubmit} className={`${styles.form} ${styles.createForm}`}>
              <div className={styles.createFormIntro}>
                <div>
                  <span className={styles.sectionEyebrow}>Dépense</span>
                  <h2>Informations principales</h2>
                </div>
                {activeTab === 'classique' && (
                  <div className={styles.natureControlStack}>
                    <div className={`${styles.natureControl} ${natureToneClass}`}>
                      <label htmlFor="req-nature">Nature</label>
                      <select
                        id="req-nature"
                        value={formData.nature_requisition}
                        onChange={(e) => setFormData({
                          ...formData,
                          nature_requisition: e.target.value as 'BUDGETAIRE' | 'HORS_BUDGET' | 'FONDS_DE_TIERS',
                          tiers_organisation_id: null,
                          tiers_nom_libre: '',
                        })}
                        required
                      >
                        <option value="BUDGETAIRE">Budgétaire</option>
                        <option value="HORS_BUDGET">Hors budget</option>
                        <option value="FONDS_DE_TIERS">Fonds de tiers</option>
                      </select>
                    </div>
                    <p className={styles.natureHelp}>{natureHelpText}</p>
                  </div>
                )}
              </div>
              <div className={styles.createLayout}>
                <div className={styles.createMain}>

                  <section className={styles.formSection} aria-labelledby="req-section-general">
                    <h3 className={styles.formSectionTitle} id="req-section-general">Informations générales</h3>
                    <div className={styles.compactGrid}>
                      <div className={`${styles.field} ${styles.span2}`}>
                        <label htmlFor="req-objet">Objet de la réquisition *</label>
                        <textarea
                          id="req-objet"
                          value={formData.objet}
                          onChange={(e) => setFormData({ ...formData, objet: e.target.value })}
                          rows={2}
                          placeholder="Ex: Achat de livres pour la bibliothèque"
                          required
                        />
                      </div>

                      <div className={styles.field}>
                        <label htmlFor="req-date">Date de la réquisition *</label>
                        <input
                          id="req-date"
                          type="date"
                          value={formData.date_requisition}
                          onChange={(e) => setFormData({ ...formData, date_requisition: e.target.value })}
                          required
                        />
                        <small className={styles.fieldHint}>
                          Date métier : modifiable pour une réquisition papier saisie en retard.
                        </small>
                      </div>

                      <div className={styles.field}>
                        {isServiceLockedByContext ? (
                          <>
                            <span className={styles.fieldLabel}>Service / Commission *</span>
                            <input type="hidden" value={formData.service_id} />
                            <div className={styles.readonlyField}>{serviceLabel || 'Service assigné'}</div>
                          </>
                        ) : (
                          <>
                            <label htmlFor="req-service">Service / Commission *</label>
                            <select
                              id="req-service"
                              value={formData.service_id}
                              onChange={(e) => setFormData({ ...formData, service_id: e.target.value })}
                              required
                            >
                              <option value="">Sélectionner un service...</option>
                              {selectableServices.map((service) => (
                                <option key={service.id} value={service.id}>
                                  {service.code} - {service.libelle}
                                </option>
                              ))}
                            </select>
                          </>
                        )}
                      </div>

                      {activeTab === 'classique' && (
                        <div className={styles.field}>
                          <label htmlFor="req-type">Type de réquisition</label>
                          <input id="req-type" type="text" value="Réquisition classique" disabled />
                        </div>
                      )}

                      <div className={styles.field}>
                        <label htmlFor="req-beneficiaire">
                          Bénéficiaire{formData.nature_requisition === 'HORS_BUDGET' ? ' *' : ''}
                        </label>
                        <input
                          id="req-beneficiaire"
                          type="text"
                          value={formData.beneficiaire}
                          onChange={(e) => setFormData({ ...formData, beneficiaire: e.target.value })}
                          placeholder="Bénéficiaire autorisé"
                          required={formData.nature_requisition === 'HORS_BUDGET'}
                        />
                      </div>

                      {formData.nature_requisition !== 'BUDGETAIRE' && (
                        <div className={styles.field}>
                          <label htmlFor="req-montant-autorise">Montant autorisé *</label>
                          <input
                            id="req-montant-autorise"
                            type="number"
                            min="0"
                            step="0.01"
                            value={formData.montant_autorise}
                            onChange={(e) => setFormData({ ...formData, montant_autorise: e.target.value })}
                            required
                          />
                        </div>
                      )}

                      {formData.nature_requisition === 'FONDS_DE_TIERS' && (
                        <>
                          <div className={styles.field}>
                            <label htmlFor="req-tiers-org">Tiers concerné</label>
                            <OrganisationAutocomplete
                              inputId="req-tiers-org"
                              value={formData.tiers_organisation_id}
                              onChange={(value, organisation) => {
                                setFormData({
                                  ...formData,
                                  tiers_organisation_id: typeof value === 'number' ? value : null,
                                  tiers_nom_libre: organisation?.nom ? '' : formData.tiers_nom_libre,
                                  beneficiaire: organisation?.nom || formData.beneficiaire,
                                })
                              }}
                              placeholder="Sélectionnez l'organisation tiers"
                            />
                          </div>
                          <div className={styles.field}>
                            <label htmlFor="req-tiers-libre">Tiers externe</label>
                            <input
                              id="req-tiers-libre"
                              type="text"
                              value={formData.tiers_nom_libre}
                              onChange={(e) => setFormData({
                                ...formData,
                                tiers_nom_libre: e.target.value,
                                tiers_organisation_id: null,
                                beneficiaire: e.target.value || formData.beneficiaire,
                              })}
                              placeholder="Nom du tiers si absent du référentiel"
                            />
                          </div>
                        </>
                      )}
                    </div>
                  </section>

                  <section className={styles.formSection} aria-labelledby="req-section-reglement">
                    <h3 className={styles.formSectionTitle} id="req-section-reglement">Règlement</h3>
                    <div className={styles.compactGrid}>
                      <div className={styles.field}>
                        <label htmlFor="req-mode-paiement">Mode de paiement *</label>
                        <select
                          id="req-mode-paiement"
                          value={formData.mode_paiement}
                          onChange={(e) => setFormData({ ...formData, mode_paiement: e.target.value as ModePaiement })}
                          required
                        >
                          <option value="cash">Caisse</option>
                          <option value="virement">Banque</option>
                        </select>
                      </div>

                      {formData.mode_paiement === 'virement' && (
                        <div className={`${styles.field} ${styles.span2}`}>
                          <label htmlFor="req-compte-bancaire">Compte bancaire *</label>
                          <select
                            id="req-compte-bancaire"
                            value={formData.compte_bancaire_id}
                            onChange={(e) => setFormData({ ...formData, compte_bancaire_id: e.target.value })}
                            required
                          >
                            <option value="">Sélectionner un compte bancaire</option>
                            {comptesBancaires.map((compte) => (
                              <option key={compte.id} value={compte.id}>
                                {(compte.banque?.nom || 'Banque')} - {compte.intitule} ({compte.devise})
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>

                    {/* Dérogation par ligne : proposée, jamais imposée. Repliée,
                        elle ne coûte qu'une ligne de texte au cas mono-mode. */}
                    <label className={styles.reglementSplitToggle} htmlFor="reglement-par-ligne">
                      <input
                        type="checkbox"
                        id="reglement-par-ligne"
                        checked={reglementParLigne}
                        onChange={(e) => activerReglementParLigne(e.target.checked)}
                      />
                      <span className={styles.optionText}>
                        <strong>Régler certaines lignes autrement</strong>
                        <small>
                          Ajoute un choix Caisse / Banque sur chaque ligne. Les lignes non modifiées
                          suivent le règlement ci-dessus.
                        </small>
                      </span>
                    </label>

                    <div className={styles.optionGrid}>
                      <label
                        className={styles.optionCard}
                        htmlFor="a_valoir"
                        data-checked={formData.a_valoir ? 'true' : 'false'}
                      >
                        <input
                          type="checkbox"
                          id="a_valoir"
                          checked={formData.a_valoir}
                          onChange={(e) => setFormData({ ...formData, a_valoir: e.target.checked })}
                        />
                        <span className={styles.optionText}>
                          <strong>À valoir</strong>
                          <small>Dépense à rembourser par une autre instance.</small>
                        </span>
                      </label>

                      <label
                        className={`${styles.optionCard} ${styles.optionCardAccent}`}
                        htmlFor="decaissement_progressif"
                        data-checked={formData.decaissement_progressif ? 'true' : 'false'}
                        data-locked={reglementMixte ? 'true' : 'false'}
                      >
                        <input
                          type="checkbox"
                          id="decaissement_progressif"
                          checked={formData.decaissement_progressif}
                          disabled={reglementMixte}
                          onChange={(e) => {
                            choixProgressifRef.current = e.target.checked
                            setFormData({ ...formData, decaissement_progressif: e.target.checked })
                          }}
                        />
                        <span className={styles.optionText}>
                          <strong>Décaissement progressif</strong>
                          <small>
                            {reglementMixte
                              ? `Imposé : le règlement se scinde en ${volets.length} volets.`
                              : 'Sorties par tranches autorisées par le demandeur.'}
                          </small>
                        </span>
                      </label>
                    </div>

                    {formData.decaissement_progressif && (
                      <p className={styles.optionNote}>
                        Après approbation, l'argent ne sortira pas en une fois : vous autoriserez des tranches
                        (bénéficiaire + montant) et la caisse ne pourra payer que les tranches autorisées,
                        dans la limite du montant total approuvé.
                      </p>
                    )}

                    {formData.a_valoir && (
                      <div className={styles.compactGrid}>
                        <div className={styles.field}>
                          <label htmlFor="req-instance-beneficiaire">Instance bénéficiaire (qui doit rembourser) *</label>
                          <OrganisationAutocomplete
                            inputId="req-instance-beneficiaire"
                            value={instanceBeneficiaireSelection}
                            onChange={(value, organisation) => {
                              setInstanceBeneficiaireSelection(typeof value === 'number' ? value : null)
                              setFormData({ ...formData, instance_beneficiaire: organisation?.nom || '' })
                            }}
                            placeholder="Sélectionnez l'instance"
                          />
                        </div>

                        <div className={`${styles.field} ${styles.span2}`}>
                          <label htmlFor="req-notes-a-valoir">Notes / Justification</label>
                          <textarea
                            id="req-notes-a-valoir"
                            value={formData.notes_a_valoir}
                            onChange={(e) => setFormData({ ...formData, notes_a_valoir: e.target.value })}
                            rows={2}
                            placeholder="Ex: Dépense effectuée pour le compte du Conseil National qui remboursera..."
                          />
                        </div>
                      </div>
                    )}
                  </section>

                  <section className={styles.formSection} aria-labelledby="req-section-annexe">
                    <h3 className={styles.formSectionTitle} id="req-section-annexe">Pièce justificative</h3>
                    <div className={styles.field}>
                      <label htmlFor="req-annexe" className={styles.srOnly}>
                        Justificatif (PDF ou image, 3 Mo maximum)
                      </label>
                      <div
                        className={`${styles.annexeDrop} ${annexeError ? styles.annexeDropError : ''}`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault()
                          const file = e.dataTransfer.files?.[0]
                          if (file) setAnnexeSelection(file)
                        }}
                      >
                        <input
                          id="req-annexe"
                          type="file"
                          accept=".pdf,image/png,image/jpeg"
                          onChange={(e) => setAnnexeSelection(e.target.files?.[0] || null)}
                        />
                        <div className={styles.annexeDropContent}>
                          <span className={styles.annexeIcon}><Paperclip size={16} /></span>
                          <div>
                            <strong>Glissez-déposez un fichier</strong>
                            <div className={styles.annexeHint}>
                              ou cliquez pour sélectionner — PDF / PNG / JPEG, 3 Mo maximum
                            </div>
                          </div>
                        </div>
                      </div>
                      {annexeFile && !annexeError && (
                        <div className={styles.annexePreview}>
                          <span className={styles.annexeFileIcon}><FileText size={14} aria-hidden="true" /></span>
                          <span>{annexeFile.name}</span>
                        </div>
                      )}
                      {annexeError && (
                        <div className={styles.annexeError}>{annexeError}</div>
                      )}
                      {!annexeError && (
                        <div className={styles.annexeHint}>
                          1 seul fichier. Si plusieurs notes de débit, scannez-les en un seul PDF.
                        </div>
                      )}
                    </div>
                  </section>

                  {formData.nature_requisition === 'BUDGETAIRE' && (
                  <section className={styles.lignesSection} aria-labelledby="req-section-lignes">
                    <div className={styles.lignesHeader}>
                      <div className={styles.lignesHeading}>
                        <h3 className={styles.formSectionTitle} id="req-section-lignes">Lignes de dépense</h3>
                        <p className={styles.lignesSubtitle}>
                          {groupesDepense.length} poste{groupesDepense.length > 1 ? 's' : ''} · {lignes.length} ligne{lignes.length > 1 ? 's' : ''} · Total {formatCurrency(calculateTotalUsd())}
                        </p>
                      </div>
                      <button type="button" onClick={addGroupeDepense} className={styles.addBtn}>
                        + Ajouter un autre poste budgétaire
                      </button>
                    </div>

                    <div className={styles.budgetGroups}>
                      {groupesDepense.map((groupe, groupIndex) => {
                        const budgetLine = groupe.budget_poste_id ? budgetLinesById.get(Number(groupe.budget_poste_id)) : null
                        const query = groupe.budgetSearch ?? ''
                        const filteredBudgetTree = filterBudgetTree(query)
                        const forceExpand = query.trim().length > 0
                        const sousTotalUsd = getGroupeSousTotalUsd(groupe)
                        const disponible = toNumber(budgetLine?.montant_disponible)
                        const soldeApres = budgetLine ? disponible - sousTotalUsd : 0
                        const resteCdf = budgetLine && exchangeRate ? disponible * exchangeRate : null
                        const seuil = printSettings?.budget_alert_threshold ?? 80
                        const pourcentage = budgetLine?.montant_prevu
                          ? ((toNumber(budgetLine.montant_engage) + sousTotalUsd) / toNumber(budgetLine.montant_prevu)) * 100
                          : 0
                        const depasse = Boolean(budgetLine && sousTotalUsd > disponible)
                        return (
                          <div
                            key={groupe.id}
                            className={styles.budgetGroup}
                            data-active={groupe.id === activeGroupId ? 'true' : 'false'}
                            data-overrun={depasse ? 'true' : 'false'}
                            onFocusCapture={() => setActiveGroupId(groupe.id)}
                          >
                            <div className={styles.budgetGroupTop}>
                              <div className={styles.budgetGroupPoste}>
                                <label>Poste budgétaire *</label>
                                <div className={styles.posteCell}>
                                  <input
                                    type="text"
                                    value={query}
                                    aria-label={`Poste budgétaire du groupe ${groupIndex + 1}`}
                                    onChange={(e) => updateGroupeSearch(groupe.id, e.target.value)}
                                    onFocus={() => {
                                      setActiveGroupId(groupe.id)
                                      setGroupeDropdown(groupe.id, true)
                                    }}
                                    onBlur={() => {
                                      setTimeout(() => setGroupeDropdown(groupe.id, false), 120)
                                    }}
                                    placeholder="Rechercher par code ou libellé"
                                  />
                                  {groupe.showBudgetDropdown && filteredBudgetTree.length > 0 && (
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
                                          onSelect={(line) => selectBudgetPoste(line, groupe.id)}
                                          forceExpand={forceExpand}
                                        />
                                      ))}
                                    </div>
                                  )}
                                  {groupe.showBudgetDropdown && filteredBudgetTree.length === 0 && (
                                    <div className={styles.dropdown} onMouseDown={(event) => event.preventDefault()}>
                                      <div className={styles.dropdownItem}>Aucun poste trouvé.</div>
                                    </div>
                                  )}
                                </div>
                                <input type="hidden" value={groupe.budget_poste_id ?? ''} />
                                {budgetLines.length === 0 && (
                                  <small className={styles.budgetHint}>
                                    Aucun poste budgétaire trouvé. Vérifie la page Budget (Dépenses).
                                  </small>
                                )}
                              </div>
                              <button
                                type="button"
                                className={styles.removeGroupBtn}
                                onClick={() => removeGroupeDepense(groupe.id)}
                                disabled={groupesDepense.length === 1}
                              >
                                Supprimer le groupe
                              </button>
                            </div>

                            {budgetLine && (
                              <div className={styles.groupBudgetInfo}>
                                <span>Budget prévu <strong>{formatCurrency(budgetLine.montant_prevu)}</strong></span>
                                <span>Déjà engagé <strong>{formatCurrency(budgetLine.montant_engage)}</strong></span>
                                <span className={depasse ? styles.budgetAlert : undefined}>Disponible <strong>{formatCurrency(disponible)}</strong></span>
                                <span>Sous-total <strong>{formatCurrency(sousTotalUsd)}</strong></span>
                                <span className={soldeApres < 0 ? styles.balanceAfterNegative : styles.balanceAfterPositive}>
                                  Solde après <strong>{formatCurrency(soldeApres)}</strong>
                                </span>
                                {resteCdf !== null && (
                                  <span className={styles.budgetMuted}>
                                    Disponible CDF {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(resteCdf)}
                                  </span>
                                )}
                                {pourcentage >= seuil && pourcentage < 100 && (
                                  <span className={styles.budgetWarn}>Seuil {seuil}% atteint</span>
                                )}
                              </div>
                            )}

                            {depasse && (
                              <div className={styles.budgetWarning}>
                                {printSettings?.budget_block_overrun ? 'Blocage' : 'Dépassement'} : le sous-total du poste
                                {' '}({formatCurrency(sousTotalUsd)}) dépasse le disponible budgétaire
                                {' '}({formatCurrency(disponible)}).
                              </div>
                            )}

                            <div className={styles.lignesTableWrap}>
                              <table className={`${styles.lignesTable} ${reglementParLigne ? styles.lignesTableSplit : ''}`}>
                                <thead>
                                  <tr>
                                    <th scope="col" className={styles.colDescription}>Description *</th>
                                    <th scope="col" className={styles.colQte}>Qté *</th>
                                    <th scope="col" className={styles.colDevise}>Devise</th>
                                    <th scope="col" className={styles.colPU}>Prix unitaire *</th>
                                    {reglementParLigne && (
                                      <th scope="col" className={styles.colReglement}>Règlement</th>
                                    )}
                                    <th scope="col" className={styles.colTotal}>Total (USD)</th>
                                    <th scope="col" className={styles.colAction}>
                                      <span className={styles.srOnly}>Actions</span>
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {groupe.lignes.map((ligne, lineIndex) => (
                                    <tr key={ligne.id} className={styles.ligneRow}>
                                      <td className={styles.colDescription} data-label="Description">
                                        <input
                                          type="text"
                                          value={ligne.description}
                                          aria-label={`Description de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                          placeholder="Nature de la dépense"
                                          onChange={(e) => updateLigne(groupe.id, ligne.id, 'description', e.target.value)}
                                          required
                                        />
                                      </td>
                                      <td className={styles.colQte} data-label="Qté">
                                        <input
                                          type="number"
                                          value={ligne.quantite}
                                          aria-label={`Quantité de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                          onChange={(e) => updateLigne(groupe.id, ligne.id, 'quantite', parseInt(e.target.value) || 0)}
                                          min="1"
                                          required
                                        />
                                      </td>
                                      <td className={styles.colDevise} data-label="Devise">
                                        <select
                                          value={ligne.devise || 'USD'}
                                          aria-label={`Devise de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                          onChange={(e) => updateLigne(groupe.id, ligne.id, 'devise', e.target.value)}
                                        >
                                          <option value="USD">USD</option>
                                          <option value="CDF">CDF</option>
                                        </select>
                                      </td>
                                      <td className={styles.colPU} data-label="Prix unitaire">
                                        <div className={styles.inlineInputRow}>
                                          <input
                                            type="number"
                                            step="0.01"
                                            value={ligne.montant_unitaire}
                                            aria-label={`Prix unitaire de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                            onChange={(e) => updateLigne(groupe.id, ligne.id, 'montant_unitaire', parseFloat(e.target.value) || 0)}
                                            required
                                          />
                                          {ligne.devise === 'CDF' && exchangeRate > 0 && (
                                            <button
                                              type="button"
                                              className={styles.convertBtn}
                                              title="Convertir ce prix unitaire en USD"
                                              onClick={() => {
                                                const usd = toUsd(ligne.montant_unitaire, 'CDF')
                                                updateLigne(groupe.id, ligne.id, 'devise', 'USD')
                                                updateLigne(groupe.id, ligne.id, 'montant_unitaire', parseFloat(usd.toFixed(2)))
                                              }}
                                            >
                                              Convertir en USD
                                            </button>
                                          )}
                                        </div>
                                        {ligne.devise === 'CDF' && exchangeRate === 0 && (
                                          <small className={styles.budgetHint}>Taux de change non défini.</small>
                                        )}
                                      </td>

                                      {reglementParLigne && (
                                        <td className={styles.colReglement} data-label="Règlement">
                                          <div className={styles.reglementCell}>
                                            <select
                                              value={ligne.mode_paiement ?? ''}
                                              aria-label={`Règlement de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                              onChange={(e) => changerModeLigne(groupe.id, ligne.id, e.target.value as '' | 'cash' | 'virement')}
                                            >
                                              <option value="">Global · {libelleModePaiement(formData.mode_paiement)}</option>
                                              <option value="cash">Caisse</option>
                                              <option value="virement">Banque</option>
                                            </select>
                                            {ligne.mode_paiement === 'virement' && (
                                              <select
                                                value={ligne.compte_bancaire_id ?? ''}
                                                aria-label={`Compte bancaire de la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                                onChange={(e) =>
                                                  updateLigne(
                                                    groupe.id,
                                                    ligne.id,
                                                    'compte_bancaire_id',
                                                    e.target.value ? Number(e.target.value) : null
                                                  )
                                                }
                                                required
                                              >
                                                <option value="">Compte bancaire…</option>
                                                {comptesBancaires.map((compte) => (
                                                  <option key={compte.id} value={compte.id}>
                                                    {(compte.banque?.nom || 'Banque')} - {compte.intitule} ({compte.devise})
                                                  </option>
                                                ))}
                                              </select>
                                            )}
                                          </div>
                                        </td>
                                      )}

                                      <td className={`${styles.colTotal} ${styles.cellAmount}`} data-label="Total (USD)">
                                        <strong>
                                          {formatCurrency(ligne.devise === 'CDF' ? toUsd(ligne.montant_total, 'CDF') : ligne.montant_total)}
                                        </strong>
                                      </td>
                                      <td className={styles.colAction} data-label="">
                                        <button
                                          type="button"
                                          onClick={() => removeLigne(groupe.id, ligne.id)}
                                          className={styles.removeBtn}
                                          disabled={groupesDepense.length === 1 && groupe.lignes.length === 1}
                                          aria-label={`Supprimer la ligne ${lineIndex + 1} du groupe ${groupIndex + 1}`}
                                          title="Supprimer la ligne"
                                        >
                                          ×
                                        </button>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                                <tfoot>
                                  <tr>
                                    <td colSpan={reglementParLigne ? 4 : 3}>Sous-total du poste</td>
                                    <td className={styles.cellAmount}>{formatCurrency(sousTotalUsd)}</td>
                                    <td />
                                  </tr>
                                  {budgetLine && (
                                    <tr className={styles.lignesFootHint}>
                                      <td colSpan={reglementParLigne ? 4 : 3}>Solde après demande</td>
                                      <td className={`${styles.cellAmount} ${soldeApres < 0 ? styles.balanceAfterNegative : styles.balanceAfterPositive}`}>
                                        {formatCurrency(soldeApres)}
                                      </td>
                                      <td />
                                    </tr>
                                  )}
                                </tfoot>
                              </table>
                            </div>

                            <div className={styles.groupActions}>
                              <button type="button" onClick={() => addLigne(groupe.id)} className={styles.addLineBtn}>
                                + Ajouter une ligne
                              </button>
                            </div>
                          </div>
                        )
                      })}
                      <div className={styles.totalBudgetGroups}>
                        <span>Total général</span>
                        <strong>{formatCurrency(calculateTotalUsd())}</strong>
                        {exchangeRate > 0 && (
                          <small>
                            Équivalent CDF {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(calculateTotalUsd() * exchangeRate)}
                          </small>
                        )}
                      </div>
                    </div>

                    {/* Le règlement mixte a des conséquences (mode de la pièce,
                        décaissement progressif, paiements séparés) : on les
                        annonce avant l'enregistrement, pas après. */}
                    {reglementMixte && (
                      <div className={styles.voletsPanel} aria-live="polite">
                        <div className={styles.voletsPanelHeader}>
                          <strong>Règlement en {volets.length} volets</strong>
                          <span>
                            {modeResumeReglement === MODE_PAIEMENT_MIXTE
                              ? 'La réquisition sera enregistrée avec le mode « Mixte ».'
                              : `Même mode (${libelleModePaiement(modeResumeReglement)}), mais plusieurs comptes : un volet par compte.`}
                          </span>
                        </div>
                        <ul className={styles.voletsList}>
                          {volets.map((volet) => (
                            <li key={`${volet.mode}-${volet.compteId ?? 'caisse'}`}>
                              <span className={styles.voletLabel}>
                                <strong>
                                  {libelleModePaiement(volet.mode)}
                                  {volet.mode === 'virement' && ` · ${libelleCompteBancaire(volet.compteId)}`}
                                </strong>
                                <small>
                                  Ligne{volet.numerosLignes.length > 1 ? 's' : ''} {volet.numerosLignes.join(', ')}
                                </small>
                              </span>
                              <strong className={styles.voletMontant}>{formatCurrency(volet.montantUsd)}</strong>
                            </li>
                          ))}
                        </ul>
                        <p className={styles.voletsNote}>
                          Décaissement progressif activé automatiquement : l'argent ne sortant pas du même
                          endroit, chaque volet sera autorisé puis payé séparément.
                        </p>
                      </div>
                    )}
                  </section>
                  )}

                </div>

                <aside className={styles.analysisColumn} aria-label="Récapitulatif et analyse budgétaire">
                  <div className={styles.summaryPanelHeader}>
                    <span>Total de la réquisition</span>
                    <strong>{formatCurrency(formData.nature_requisition === 'BUDGETAIRE' ? calculateTotalUsd() : toNumber(formData.montant_autorise))}</strong>
                  </div>

                  <div className={styles.summaryRows}>
                    <div>
                      <span>Service / Commission</span>
                      <strong>{serviceLabel || 'Non sélectionné'}</strong>
                    </div>
                    <div>
                      <span>Date de la réquisition</span>
                      {/* Affichage jj/mm/aaaa sans passer par Date() : évite tout décalage de fuseau. */}
                      <strong>
                        {formData.date_requisition
                          ? formData.date_requisition.split('-').reverse().join('/')
                          : '—'}
                      </strong>
                    </div>
                    <div>
                      <span>Mode de paiement</span>
                      <strong>
                        {reglementMixte
                          ? `${libelleModePaiement(modeResumeReglement)} · ${volets.length} volets`
                          : libelleModePaiement(modeResumeReglement)}
                      </strong>
                    </div>
                    <div>
                      <span>Lignes de dépense</span>
                      <strong>{formData.nature_requisition === 'BUDGETAIRE' ? lignes.length : 'Sans impact budget initial'}</strong>
                    </div>
                  </div>

                  {formData.nature_requisition !== 'BUDGETAIRE' ? (
                    <div className={styles.analysisEmpty}>
                      Cette réquisition autorise une sortie sans consommation budgétaire initiale.
                    </div>
                  ) : (
                  <>
                  <div className={styles.analysisHeader}>
                    <div className={styles.analysisTitle}>Analyse budgétaire</div>
                    <div className={styles.analysisSubtitle}>
                      {activeGroupe ? 'Poste actif' : 'Sélectionnez un poste'}
                    </div>
                  </div>

                  {activeBudgetLine ? (
                    <>
                      <div className={styles.analysisCard}>
                        <div className={styles.analysisCardTitle}>
                          {activeBudgetLine.code} - {activeBudgetLine.libelle}
                        </div>
                        <div className={styles.analysisRow}>
                          <span>Solde actuel</span>
                          <strong>{formatCurrency(activeDisponible)}</strong>
                        </div>
                        <div className={styles.progressBar}>
                          <div
                            className={styles.progressFill}
                            style={{ width: `${activeConsumptionClamped}%` }}
                          />
                        </div>
                        <div className={styles.analysisHint}>
                          Consommation après opération : {activeConsumption.toFixed(1)}%
                        </div>
                      </div>

                      <div className={styles.analysisCardPrimary}>
                        <div className={styles.analysisRow}>
                          <span>Reste à vivre</span>
                          <strong className={activeSoldeApres < 0 ? styles.negative : styles.positive}>
                            {formatCurrency(activeSoldeApres)}
                          </strong>
                        </div>
                        <div className={styles.analysisSub}>
                          Dépense saisie : {formatCurrency(activeTotalUsd)}
                        </div>
                        {activeSoldeApres < 0 && (
                          <div className={styles.analysisAlert}>
                            Dépassement estimé de {formatCurrency(Math.abs(activeSoldeApres))}
                          </div>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className={styles.analysisEmpty}>
                      Choisissez un poste budgétaire pour afficher le solde et l’impact.
                    </div>
                  )}
                  </>
                  )}
                </aside>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={closeCreationForm} className={styles.secondaryBtn} disabled={submitting}>
                  Annuler
                </button>
                <button type="button" onClick={resetForm} className={styles.secondaryBtn} disabled={submitting}>
                  Réinitialiser
                </button>
                <button
                  type="submit"
                  className={`${styles.primaryBtn} ${formData.nature_requisition === 'BUDGETAIRE' && printSettings?.budget_block_overrun && groupesDepense.some(groupe => {
                    const line = budgetLinesById.get(Number(groupe.budget_poste_id))
                    if (!line) return false
                    return getGroupeSousTotalUsd(groupe) > toNumber(line.montant_disponible)
                  }) ? styles.primaryBtnDisabled : ''}`}
                  disabled={submitting || (formData.nature_requisition === 'BUDGETAIRE' && printSettings?.budget_block_overrun && groupesDepense.some(groupe => {
                    const line = budgetLinesById.get(Number(groupe.budget_poste_id))
                    if (!line) return false
                    return getGroupeSousTotalUsd(groupe) > toNumber(line.montant_disponible)
                  }))}
                >
                  {submitting ? 'Création en cours...' : 'Enregistrer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {!isCreatePage && (<>

      {selectedIds.length > 0 && (
        <div className={styles.groupingBar}>
          <div className={styles.groupingCount}>
            {selectedIds.length} réquisition{selectedIds.length > 1 ? 's' : ''} sélectionnée
            {selectedIds.length > 1 ? 's' : ''}
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
                  onChange={(event) => setSelectedDraftDossierId(event.target.value)}
                >
                  <option value="">Ajouter à un dossier…</option>
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
            {hasMixedDossierSelection && (
              <div className={styles.groupingHint}>
                Sélection incompatible : choisissez des réquisitions du même dossier ou sans dossier.
              </div>
            )}
            <button type="button" className={styles.groupingSecondary} onClick={clearSelection}>
              Annuler
            </button>
          </div>
        </div>
      )}

      <div className={styles.listControls}>
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage <= 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {safePage} / {totalPages} · {startIndex}-{endIndex} sur {filteredRequisitions.length}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage >= totalPages}
          >
            Suivant →
          </button>
        </div>
      </div>

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colSelect}>
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={toggleSelectPage}
                  aria-label="Sélectionner toutes les réquisitions de la page"
                />
              </th>
              <th className={styles.colNumero}>N° Réquisition</th>
              <th
                className={`${styles.sortableHeader} ${styles.colDate}`}
                onClick={() => handleSort('created_at')}
              >
                Date
                {sortField === 'created_at' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th className={styles.colObjet}>Objet</th>
              <th className={styles.colService}>Service / Commission</th>
              <th
                className={`${styles.sortableHeader} ${styles.colMontant}`}
                onClick={() => handleSort('montant_total')}
              >
                Montant
                {sortField === 'montant_total' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th className={styles.colType}>Type</th>
              <th className={styles.colStatut}>Statut</th>
              {showValidationColumns && <th className={styles.colAutorisateur}>Validation 1/2</th>}
              {showValidationColumns && <th className={styles.colViseur}>Validation 2/2</th>}
              <th className={styles.colActions}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedRequisitions.length === 0 ? (
              <tr>
                <td colSpan={showValidationColumns ? 11 : 9} className={styles.empty}>
                  <Inbox size={32} className={styles.emptyIcon} />
                  <span>Aucune réquisition trouvée</span>
                </td>
              </tr>
            ) : (
              paginatedRequisitions.map((req) => {
                const canSubmitExamen = canSubmitRequisitionExamen(req)
                return (
                <tr key={req.id}>
                <td className={styles.colSelect}>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(String(req.id))}
                    onChange={() => toggleSelectRequisition(String(req.id))}
                    disabled={!canSelectRequisition(req)}
                    aria-label={`Sélectionner la réquisition ${req.numero_requisition}`}
                  />
                </td>
                <td className={styles.colNumero}>{req.numero_requisition}</td>
                  <td className={styles.colDate}>{format(new Date(req.created_at), 'dd/MM/yyyy')}</td>
                  <td className={styles.colObjet} title={req.objet}>{req.objet}</td>
                  <td className={styles.colService}>
                    {req.service_id
                      ? (servicesById.get(String(req.service_id))?.libelle ?? '—')
                      : '—'}
                  </td>
                  <td className={styles.colMontant}>
                    <div>
                      <div className={styles.amountRow}>
                        {getAiBadge(req.id)}
                        <span className={styles.amountValue}>{formatCurrency(req.montant_total)}</span>
                      </div>
                      {exchangeRate > 0 && (
                        <div className={styles.amountSubValue}>
                          {formatCdf(toNumber(req.montant_total) * exchangeRate)}
                        </div>
                      )}
                    </div>
                  </td>
                  <td className={styles.colType}>
                    <div className={styles.badgeStack}>
                      {(req as any).a_valoir ? (
                        <>
                          <span className={`${styles.badge} ${styles.badgeAValoir}`}>À valoir</span>
                          {(req as any).instance_beneficiaire && (
                            <span className={styles.badgeNote}>
                              {(req as any).instance_beneficiaire}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className={`${styles.badge} ${styles.badgeNeutre}`}>Standard</span>
                      )}
                      {(req as any).decaissement_progressif && (
                        <span className={`${styles.badge} ${styles.badgeProgressif}`}>Progressif</span>
                      )}
                    </div>
                  </td>
                  <td className={styles.colStatut}>
                    <div className={styles.badgeStack}>
                      {getStatutBadge((req as any).status ?? req.statut)}
                      {getPaymentStatusBadge(req)}
                      {getVisaBadge(req)}
                    </div>
                  </td>
                  {showValidationColumns && (
                    <td className={styles.colAutorisateur}>
                      {(req as any).validateur
                        ? `${(req as any).validateur.prenom || ''} ${(req as any).validateur.nom || ''}`.trim() || '—'
                        : '—'}
                    </td>
                  )}
                  {showValidationColumns && (
                    <td className={`${styles.colViseur} ${(req as any).approbateur ? '' : styles.missingViseur}`}>
                      {(req as any).approbateur
                        ? `${(req as any).approbateur.prenom || ''} ${(req as any).approbateur.nom || ''}`.trim() || '—'
                        : 'En attente'}
                    </td>
                  )}
                  <td className={styles.colActions}>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          viewDetails(req)
                        }}
                        className={`${styles.viewBtn} ${styles.actionIconBtn}`}
                        title="Voir les détails"
                        aria-label="Voir les détails"
                      >
                        <Search size={16} />
                      </button>
                      <MenuActionsLigne
                        libelle={`Autres actions sur la réquisition ${req.numero_requisition}`}
                        items={[
                          ...((req as any).annexe?.id
                            ? [{
                                cle: 'annexe',
                                libelle: 'Voir la pièce jointe',
                                icone: <Paperclip size={15} />,
                                onSelect: () => { void openRequisitionAnnexe((req as any).annexe) },
                              }]
                            : []),
                          {
                            cle: 'imprimer',
                            libelle: 'Imprimer la réquisition',
                            icone: <Printer size={15} />,
                            onSelect: () => printRequisition(req),
                          },
                          {
                            cle: 'telecharger',
                            libelle: 'Télécharger en PDF',
                            icone: <Download size={15} />,
                            onSelect: () => downloadRequisition(req),
                          },
                          ...(canSubmitExamen
                            ? [{
                                cle: 'examen',
                                libelle: "Soumettre à l'examen",
                                icone: <Send size={15} />,
                                onSelect: () => handleSubmitRequisitionExamen(req),
                              }]
                            : []),
                          ...(canDeleteRequisition(req)
                            ? [{
                                cle: 'supprimer',
                                libelle: 'Supprimer la réquisition',
                                icone: <Trash2 size={15} />,
                                onSelect: () => handleDeleteRequisition(req),
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

      <div className={styles.mobileCards}>
        {paginatedRequisitions.length === 0 ? (
          <div className={styles.emptyCards}>
            <Inbox size={32} className={styles.emptyIcon} />
            <span>Aucune réquisition trouvée</span>
          </div>
        ) : (
          paginatedRequisitions.map((req) => {
            const canSubmitExamen = canSubmitRequisitionExamen(req)
            return (
            <div
              key={`card-${req.id}`}
              className={styles.card}
              data-statut={String((req as any).status ?? req.statut ?? '').toLowerCase()}
              role="button"
              tabIndex={0}
              onClick={() => viewDetails(req)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  viewDetails(req)
                }
              }}
            >
              <div className={styles.cardHeader}>
                <div>
                  <div className={styles.cardTitle}>{req.objet}</div>
                  <div className={styles.cardSub}>
                    {req.demandeur ? `${req.demandeur.prenom} ${req.demandeur.nom}` : 'N/A'}
                  </div>
                </div>
                <div className={styles.cardHeaderRight}>
                  <div className={styles.cardAmount}>{formatCurrency(req.montant_total)}</div>
                  <div className={styles.cardSelect}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(String(req.id))}
                      onChange={() => toggleSelectRequisition(String(req.id))}
                      onClick={(e) => e.stopPropagation()}
                      disabled={!canSelectRequisition(req)}
                      aria-label={`Sélectionner la réquisition ${req.numero_requisition}`}
                    />
                  </div>
                </div>
              </div>

              <div className={styles.cardBody}>
                <div className={styles.cardGrid}>
                  <div>
                    <div className={styles.cardLabel}>Numéro</div>
                    <div className={styles.cardValue}>{req.numero_requisition}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Date</div>
                    <div className={styles.cardValue}>{format(new Date(req.created_at), 'dd/MM/yyyy')}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Type</div>
                    <div className={styles.cardValue}>
                      {(req as any).a_valoir ? 'À valoir' : 'Standard'}
                    </div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Statut</div>
                    <div className={styles.cardValue}>{getStatutBadge((req as any).status ?? req.statut)}</div>
                  </div>
                </div>
                <div className={styles.cardBadges}>
                  {getPaymentStatusBadge(req)}
                  {getVisaBadge(req)}
                  {getAiBadge(req.id)}
                </div>
              </div>

              <div className={styles.cardFooter}>
                <span className={styles.cardHint}>Touchez pour voir le détail</span>
                {canSubmitExamen && (
                  <button
                    type="button"
                    className={styles.cardActionBtn}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      handleSubmitRequisitionExamen(req)
                    }}
                  >
                    Soumettre à l'examen
                  </button>
                )}
                {canDeleteRequisition(req) && (
                  <button
                    type="button"
                    className={`${styles.cardActionBtn} ${styles.cardActionDanger}`}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      handleDeleteRequisition(req)
                    }}
                  >
                    Supprimer
                  </button>
                )}
                <span className={styles.cardChevron}>›</span>
              </div>
            </div>
          )})
        )}
      </div>

      </>)}

      {requisitionAModifier && (
        <RequisitionEditModal
          requisition={requisitionAModifier}
          utilisateurId={user?.id}
          onClose={() => setRequisitionAModifier(null)}
          onSaved={async () => {
            await loadData()
            // La fiche ouverte doit montrer la version corrigée, pas celle
            // qu'on vient de remplacer.
            if (selectedRequisition) await viewDetails(selectedRequisition)
          }}
        />
      )}

      {showDetailModal && selectedRequisition && (
        <div className={`${styles.modal} ${styles.detailModalOverlay}`}>
          <div className={`${styles.modalContent} ${styles.detailModalContent}`}>
            <div className={styles.modalHeader}>
              <h2>Détails de la réquisition {selectedRequisition.numero_requisition}</h2>
              <div className={styles.modalHeaderActions}>
                {peutModifierRequisition(selectedRequisition as any, user?.id) && (
                  <button
                    type="button"
                    className={styles.editReqBtn}
                    onClick={() => setRequisitionAModifier(selectedRequisition)}
                  >
                    <Pencil size={14} aria-hidden="true" />
                    Modifier
                  </button>
                )}
                <button onClick={() => setShowDetailModal(false)} className={styles.closeBtn} aria-label="Fermer la fiche"><X size={18} aria-hidden="true" /></button>
              </div>
            </div>

            <div className={styles.detailContent}>
              <div className={`${styles.detailSection} ${styles.detailSectionSuccess}`}>
                <h3>Traçabilité et Responsabilité</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Demandeur</label>
                    <p><strong>{selectedRequisitionUsers.demandeur ? `${selectedRequisitionUsers.demandeur.prenom} ${selectedRequisitionUsers.demandeur.nom}` : 'Non disponible'}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Date de la demande</label>
                    <p>{format(new Date(selectedRequisition.created_at), 'dd/MM/yyyy à HH:mm')}</p>
                  </div>
                  {((selectedRequisition as any).validee_par || (selectedRequisition as any).approuvee_par) && (
                    <>
                      <div className={styles.detailItem}>
                        <label>Validation 1/2</label>
                        <p><strong>
                          {selectedRequisitionUsers.validateur
                            ? `${selectedRequisitionUsers.validateur.prenom} ${selectedRequisitionUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label>Date d'autorisation</label>
                        <p>
                          {(selectedRequisition as any).validee_le
                            ? format(new Date((selectedRequisition as any).validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                      <div className={styles.detailItem}>
                        <label>Validation 2/2</label>
                        <p><strong>
                      {selectedRequisitionUsers.approbateur
                            ? `${selectedRequisitionUsers.approbateur.prenom} ${selectedRequisitionUsers.approbateur.nom}`
                            : 'En attente'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label>Date de visa</label>
                        <p>
                          {(selectedRequisition as any).approuvee_le
                            ? format(new Date((selectedRequisition as any).approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label>Statut actuel</label>
                    <div className={styles.badgeStack}>
                      {getStatutBadge((selectedRequisition as any).status ?? selectedRequisition.statut)}
                      {getPaymentStatusBadge(selectedRequisition)}
                    </div>
                  </div>
                  {selectedRequisition.annexe?.id && (
                    <div className={styles.detailItem}>
                      <label>Pièce jointe</label>
                      <button
                        className={styles.viewBtn}
                        type="button"
                        onClick={async (event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          await openRequisitionAnnexe(selectedRequisition.annexe)
                        }}
                      >
                        <Eye size={15} aria-hidden="true" />Voir la pièce jointe
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {(selectedRequisition as any).decaissement_progressif && (
                <PlanDecaissement
                  requisition={selectedRequisition}
                  currentUserId={user?.id}
                  canAuthorize={hasPermission('can_authorize_disbursement')}
                  isAdmin={isAdmin}
                  onChanged={() => refetchRequisitions()}
                />
              )}

              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedRequisition.numero_requisition}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Objet</label>
                    <p>{selectedRequisition.objet}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Mode de paiement</label>
                    <p>
                      {/* `mixte` ne vient jamais d'une saisie : le serveur le pose
                          quand les lignes ne s'accordent pas. Le détail des volets
                          dit alors d'où sort réellement l'argent. */}
                      {String(selectedRequisition.mode_paiement) === MODE_PAIEMENT_MIXTE && 'Mixte'}
                      {selectedRequisition.mode_paiement === 'cash' && 'Caisse'}
                      {selectedRequisition.mode_paiement === 'mobile_money' && 'Mobile Money'}
                      {selectedRequisition.mode_paiement === 'card' && 'Carte (Visa)'}
                      {selectedRequisition.mode_paiement === 'virement' && 'Opération bancaire'}
                    </p>
                    {Array.isArray((selectedRequisition as any).volets_reglement) &&
                      (selectedRequisition as any).volets_reglement.length > 1 && (
                        <ul className={styles.voletsDetailList}>
                          {(selectedRequisition as any).volets_reglement.map((volet: any, index: number) => (
                            <li key={`${volet.mode_paiement}-${volet.compte_bancaire_id ?? 'caisse'}-${index}`}>
                              <span>
                                {libelleModePaiement(volet.mode_paiement)}
                                {volet.mode_paiement === 'virement' &&
                                  ` · ${libelleCompteBancaire(volet.compte_bancaire_id ?? null)}`}
                              </span>
                              <strong>{formatCurrency(volet.montant_total)}</strong>
                            </li>
                          ))}
                        </ul>
                      )}
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong className={styles.detailAmount}>{formatCurrency(selectedRequisition.montant_total)}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Snapshot budgétaire à la demande</h3>
                <BudgetDecisionTable
                  lines={selectedLignesList}
                  requestedAmount={selectedRequisition.montant_total}
                  emptyLabel="Aucun poste budgétaire rattaché à cette réquisition."
                />
              </div>

              <div className={styles.detailSection}>
                <h3>Lignes de dépense</h3>
                <div className={styles.detailTableWrap}>
                  <table className={styles.detailTable}>
                    <thead>
                      <tr>
                        <th>Poste budgétaire</th>
                        <th>Description</th>
                        <th className={styles.numCell}>Qté</th>
                        <th className={styles.numCell}>Prix unitaire</th>
                        <th className={styles.numCell}>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedLignesList.map((ligne) => (
                        <tr key={ligne.id}>
                          <td><span className={styles.rubriqueTag}>{getLignePosteLabel(ligne)}</span></td>
                          <td>{ligne.description}</td>
                          <td className={styles.numCell}>{ligne.quantite}</td>
                          <td className={styles.numCell}>{formatCurrency(ligne.montant_unitaire)}</td>
                          <td className={styles.numCell}><strong>{formatCurrency(ligne.montant_total)}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={4} className={`${styles.numCell} ${styles.totalLabel}`}>Total général</td>
                        <td className={styles.numCell}><strong className={styles.detailAmount}>{formatCurrency(selectedRequisition.montant_total)}</strong></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>

              {selectedRequisition.motif_rejet && (
                <div className={`${styles.detailSection} ${styles.detailSectionDanger}`}>
                  <h3>Motif du rejet</h3>
                  <p>{selectedRequisition.motif_rejet}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {editDossierId && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h3>Modifier la description du dossier</h3>
              <button type="button" className={styles.closeBtn} onClick={closeEditDossier} aria-label="Fermer">
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <textarea
              className={styles.textarea}
              rows={4}
              value={editDossierDescription}
              onChange={(event) => setEditDossierDescription(event.target.value)}
              placeholder="Ajouter une description..."
            />
            <div className={styles.modalActions}>
              <button type="button" className={styles.secondaryBtn} onClick={closeEditDossier}>
                Annuler
              </button>
              <button type="button" className={styles.primaryBtn} onClick={handleUpdateDossierDescription}>
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}

      {notification.show && (
        <div className={styles.notificationOverlay}>
          <div className={`${styles.notificationBox} ${notification.type === 'success' ? styles.notificationSuccess : styles.notificationError}`}>
            <div className={styles.notificationHeader}>
              <div className={styles.notificationIcon} aria-hidden="true">
                {notification.type === 'success' ? <CheckCircle2 size={20} /> : <X size={20} />}
              </div>
              <h3>{notification.title}</h3>
            </div>
            <p className={styles.notificationMessage}>{notification.message}</p>
            <button
              onClick={() => setNotification({ ...notification, show: false })}
              className={styles.notificationBtn}
            >
              OK
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
