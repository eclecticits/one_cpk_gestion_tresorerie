import { useState, useEffect, useLayoutEffect, useMemo, useRef, Suspense } from 'react'
import { lazyWithRetry } from '../utils/lazyWithRetry'
import { createPortal } from 'react-dom'
import {
  Archive,
  Ban,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  FileUp,
  History,
  Pencil,
  Repeat2,
  RotateCcw,
  UserRoundPlus,
} from 'lucide-react'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable } from '../types'
// xlsx est lourd : chargement dynamique seulement à l'ouverture de la modale d'import.
const ImportModules = lazyWithRetry(() => import('../components/ImportModules'))
import CategoryChange from '../components/CategoryChange'
import SuccessNotification from '../components/SuccessNotification'
import LoadingScreen from '../components/LoadingScreen'
import DeactivateExpertModal from '../components/DeactivateExpertModal'
import RegulariteExpert from '../components/RegulariteExpert'
import { downloadExcel } from '../utils/download'
import styles from './ExpertsComptables.module.css'
import { useToast } from '../hooks/useToast'

type ExpertCategoryFilter = '' | 'SEC' | 'En Cabinet' | 'Indépendant' | 'Salarié'
type ActionMenuState = {
  expert: ExpertComptable
  anchorRect: DOMRect
}

const getExpertCategory = (expert: ExpertComptable): ExpertCategoryFilter => {
  if (expert.type_ec === 'SEC') return 'SEC'
  if (expert.statut_professionnel === 'En Cabinet') return 'En Cabinet'
  if (expert.statut_professionnel === 'Indépendant') return 'Indépendant'
  if (expert.statut_professionnel === 'Salarié') return 'Salarié'
  return ''
}

const getCategoryLabel = (expert: ExpertComptable): string => {
  return getExpertCategory(expert) || expert.statut_professionnel || expert.type_ec || 'Non classé'
}

const getInitials = (name: string): string => {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return 'EC'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
}

const getAttachment = (expert: ExpertComptable): string => {
  return expert.cabinet_attache || expert.nom_employeur || expert.raison_sociale || '-'
}

const getCategoryClass = (category: string): string => {
  if (category === 'SEC') return styles.categorySec
  if (category === 'En Cabinet') return styles.categoryCabinet
  if (category === 'Indépendant') return styles.categoryIndependant
  if (category === 'Salarié') return styles.categorySalarie
  return styles.categoryDefault
}

// Les 26 provinces : une liste fermée évite qu'une faute de frappe crée une
// province de plus dans le filtre.
const PROVINCES = [
  'Bas-Uele', 'Équateur', 'Haut-Katanga', 'Haut-Lomami', 'Haut-Uele', 'Ituri', 'Kasaï', 'Kasaï-Central',
  'Kasaï-Oriental', 'Kinshasa', 'Kongo-Central', 'Kwango', 'Kwilu', 'Lomami', 'Lualaba', 'Mai-Ndombe',
  'Maniema', 'Mongala', 'Nord-Kivu', 'Nord-Ubangi', 'Sankuru', 'Sud-Kivu', 'Sud-Ubangi', 'Tanganyika',
  'Tshopo', 'Tshuapa',
]

type ExpertFormValues = {
  numero_ordre: string
  nom_denomination: string
  categorie: ExpertCategoryFilter
  sexe: string
  province_attache: string
  email: string
  telephone: string
  nif: string
  cabinet_attache: string
  nom_employeur: string
  raison_sociale: string
  associe_gerant: string
}

const emptyFormValues: ExpertFormValues = {
  numero_ordre: '',
  nom_denomination: '',
  categorie: '',
  sexe: '',
  province_attache: '',
  email: '',
  telephone: '',
  nif: '',
  cabinet_attache: '',
  nom_employeur: '',
  raison_sociale: '',
  associe_gerant: '',
}

const expertToFormValues = (expert: ExpertComptable): ExpertFormValues => ({
  numero_ordre: expert.numero_ordre,
  nom_denomination: expert.nom_denomination || '',
  categorie: getExpertCategory(expert),
  sexe: expert.sexe || '',
  province_attache: expert.province_attache || '',
  email: expert.email || '',
  telephone: expert.telephone || '',
  nif: expert.nif || '',
  cabinet_attache: expert.cabinet_attache || '',
  nom_employeur: expert.nom_employeur || '',
  raison_sociale: expert.raison_sociale || '',
  associe_gerant: expert.associe_gerant || '',
})

// Le classement que l'import Excel attribue à chaque catégorie.
const classementDeCategorie = (categorie: ExpertCategoryFilter) => {
  if (categorie === 'SEC') {
    return { type_ec: 'SEC', categorie_personne: 'Personne Morale', statut_professionnel: 'Cabinet' }
  }
  return { type_ec: 'EC', categorie_personne: 'Personne Physique', statut_professionnel: categorie }
}

// Seuls les champs de la catégorie partent : les autres ne s'affichent pas.
const champsDeCategorie = (values: ExpertFormValues): Record<string, string | null> => {
  const texte = (value: string) => value.trim() || null
  if (values.categorie === 'SEC') {
    return { raison_sociale: texte(values.raison_sociale), associe_gerant: texte(values.associe_gerant) }
  }
  if (values.categorie === 'En Cabinet') return { cabinet_attache: texte(values.cabinet_attache) }
  if (values.categorie === 'Indépendant') return { nif: texte(values.nif) }
  if (values.categorie === 'Salarié') return { nom_employeur: texte(values.nom_employeur) }
  return {}
}

// Mêmes champs obligatoires que l'import et que le changement de catégorie.
const champManquantAjout = (values: ExpertFormValues): string | null => {
  if (!values.categorie) return 'la catégorie'
  if (!values.numero_ordre.trim()) return "le numéro d'ordre"
  if (!values.nom_denomination.trim()) return 'le nom / dénomination'
  if (values.categorie === 'SEC' && !values.raison_sociale.trim()) return 'la raison sociale'
  if (values.categorie === 'SEC' && !values.associe_gerant.trim()) return "l'associé gérant"
  if (values.categorie === 'En Cabinet' && !values.cabinet_attache.trim()) return "le cabinet d'attache"
  if (values.categorie === 'Indépendant' && !values.nif.trim()) return 'le NIF'
  if (values.categorie === 'Salarié' && !values.nom_employeur.trim()) return "le nom de l'employeur"
  return null
}

const LIBELLES_CATEGORIE_HISTORIQUE: Record<string, string> = {
  sec: 'SEC',
  en_cabinet: 'En Cabinet',
  independant: 'Indépendant',
  salarie: 'Salarié',
}

type CategoryChangeEntry = {
  id: string
  old_category?: string | null
  new_category: string
  reason?: string | null
  created_at: string
}

const emptySummary = {
  total: 0,
  active: 0,
  inactive: 0,
  sec: 0,
  cabinet: 0,
  independant: 0,
  salarie: 0,
}

function ExpertFormFields({
  values,
  onChange,
  idPrefix,
  isCreate,
  categoryLocked,
}: {
  values: ExpertFormValues
  onChange: (values: ExpertFormValues) => void
  idPrefix: string
  isCreate: boolean
  categoryLocked: boolean
}) {
  const set = (field: keyof ExpertFormValues) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => onChange({ ...values, [field]: e.target.value })
  const marque = isCreate ? ' *' : ''
  const provinces = values.province_attache && !PROVINCES.includes(values.province_attache)
    ? [values.province_attache, ...PROVINCES]
    : PROVINCES

  return (
    <>
      <div className={styles.field}>
        <label htmlFor={`${idPrefix}-categorie`}>Catégorie{marque}</label>
        <select
          id={`${idPrefix}-categorie`}
          value={values.categorie}
          onChange={set('categorie')}
          disabled={categoryLocked}
          required={isCreate}
          autoFocus={isCreate}
        >
          <option value="">-- Sélectionner --</option>
          <option value="SEC">SEC</option>
          <option value="En Cabinet">En Cabinet</option>
          <option value="Indépendant">Indépendant</option>
          <option value="Salarié">Salarié</option>
        </select>
        {categoryLocked && (
          <small className={styles.fieldHint}>
            Pour la modifier, utilisez « Changer de catégorie » : le changement est conservé dans l'historique.
          </small>
        )}
      </div>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-numero`}>Numéro d'ordre{marque}</label>
          <input
            id={`${idPrefix}-numero`}
            type="text"
            value={values.numero_ordre}
            onChange={set('numero_ordre')}
            disabled={!isCreate}
            required={isCreate}
          />
        </div>
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-nom`}>Nom / Dénomination *</label>
          <input
            id={`${idPrefix}-nom`}
            type="text"
            value={values.nom_denomination}
            onChange={set('nom_denomination')}
            required
          />
        </div>
      </div>

      {values.categorie === 'Indépendant' && (
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-nif`}>NIF{marque}</label>
          <input id={`${idPrefix}-nif`} type="text" value={values.nif} onChange={set('nif')} placeholder="Ex: A1234567X" required={isCreate} />
        </div>
      )}

      {values.categorie === 'En Cabinet' && (
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-cabinet`}>Cabinet d'Attache{marque}</label>
          <input id={`${idPrefix}-cabinet`} type="text" value={values.cabinet_attache} onChange={set('cabinet_attache')} placeholder="Nom du cabinet d'attache" required={isCreate} />
        </div>
      )}

      {values.categorie === 'Salarié' && (
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-employeur`}>Nom de l'employeur{marque}</label>
          <input id={`${idPrefix}-employeur`} type="text" value={values.nom_employeur} onChange={set('nom_employeur')} required={isCreate} />
        </div>
      )}

      {values.categorie === 'SEC' && (
        <div className={styles.fieldRow}>
          <div className={styles.field}>
            <label htmlFor={`${idPrefix}-raison`}>Raison sociale{marque}</label>
            <input id={`${idPrefix}-raison`} type="text" value={values.raison_sociale} onChange={set('raison_sociale')} required={isCreate} />
          </div>
          <div className={styles.field}>
            <label htmlFor={`${idPrefix}-associe`}>Associé gérant{marque}</label>
            <input id={`${idPrefix}-associe`} type="text" value={values.associe_gerant} onChange={set('associe_gerant')} required={isCreate} />
          </div>
        </div>
      )}

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-province`}>Province d'attache</label>
          <select id={`${idPrefix}-province`} value={values.province_attache} onChange={set('province_attache')}>
            <option value="">-- Sélectionner --</option>
            {provinces.map((province) => (
              <option key={province} value={province}>{province}</option>
            ))}
          </select>
        </div>
        {values.categorie !== 'SEC' && (
          <div className={styles.field}>
            <label htmlFor={`${idPrefix}-sexe`}>Sexe</label>
            <select id={`${idPrefix}-sexe`} value={values.sexe} onChange={set('sexe')}>
              <option value="">-- Sélectionner --</option>
              <option value="M">Masculin</option>
              <option value="F">Féminin</option>
            </select>
          </div>
        )}
      </div>

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-email`}>Email</label>
          <input id={`${idPrefix}-email`} type="email" value={values.email} onChange={set('email')} />
        </div>
        <div className={styles.field}>
          <label htmlFor={`${idPrefix}-telephone`}>Téléphone</label>
          <input id={`${idPrefix}-telephone`} type="tel" value={values.telephone} onChange={set('telephone')} placeholder="Ex: +243 812 345 678" />
        </div>
      </div>
    </>
  )
}

function ExpertHistory({ expertId, version }: { expertId: string; version: number }) {
  const [entries, setEntries] = useState<CategoryChangeEntry[] | null>(null)
  const [indisponible, setIndisponible] = useState(false)

  useEffect(() => {
    let actif = true
    setEntries(null)
    setIndisponible(false)
    apiRequest<CategoryChangeEntry[]>('GET', `/experts-comptables/category-changes/${expertId}`)
      .then((data) => actif && setEntries(data))
      .catch(() => actif && setIndisponible(true))
    return () => {
      actif = false
    }
  }, [expertId, version])

  if (indisponible) return <p className={styles.detailMuted}>Historique indisponible.</p>
  if (!entries) return <p className={styles.detailMuted}>Chargement…</p>
  if (entries.length === 0) return <p className={styles.detailMuted}>Aucun changement de catégorie enregistré.</p>

  return (
    <ul className={styles.historyList}>
      {entries.map((entry) => (
        <li key={entry.id}>
          <strong>
            {(entry.old_category && LIBELLES_CATEGORIE_HISTORIQUE[entry.old_category]) || 'Non classé'}
            {' → '}
            {LIBELLES_CATEGORIE_HISTORIQUE[entry.new_category] || entry.new_category}
          </strong>
          <span>{new Date(entry.created_at).toLocaleDateString('fr-FR')}</span>
          {entry.reason && <small>{entry.reason}</small>}
        </li>
      ))}
    </ul>
  )
}

function getMenuPosition(anchorRect: DOMRect, menuWidth: number, menuHeight: number) {
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const margin = 8
  const preferredTop = anchorRect.bottom + margin
  const topPlacement = anchorRect.top - menuHeight - margin
  const hasBottomSpace = preferredTop + menuHeight <= viewportHeight - margin
  const top = hasBottomSpace ? preferredTop : Math.max(margin, topPlacement)
  const preferredLeft = anchorRect.right - menuWidth
  const maxLeft = Math.max(margin, viewportWidth - menuWidth - margin)
  const left = Math.min(Math.max(margin, preferredLeft), maxLeft)
  return { top, left }
}

function ExpertActionMenu({
  expert,
  anchorRect,
  trigger,
  onClose,
  onView,
  onViewHistory,
  onEdit,
  onCategoryChange,
  onToggleActive,
  onArchive,
}: {
  expert: ExpertComptable
  anchorRect: DOMRect
  trigger: HTMLElement | null
  onClose: (restoreFocus?: boolean) => void
  onView: () => void
  onViewHistory: () => void
  onEdit: () => void
  onCategoryChange: () => void
  onToggleActive: () => void
  onArchive: () => void
}) {
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState(() => getMenuPosition(anchorRect, 232, 244))

  useLayoutEffect(() => {
    const menu = menuRef.current
    if (!menu) return
    const rect = menu.getBoundingClientRect()
    setPosition(getMenuPosition(anchorRect, rect.width, rect.height))
  }, [anchorRect])

  useEffect(() => {
    const menu = menuRef.current
    const firstItem = menu?.querySelector<HTMLButtonElement>('[role="menuitem"]')
    firstItem?.focus()
  }, [])

  useEffect(() => {
    const updatePosition = () => {
      const currentTriggerRect = trigger?.getBoundingClientRect() ?? anchorRect
      const menu = menuRef.current
      const rect = menu?.getBoundingClientRect()
      setPosition(getMenuPosition(currentTriggerRect, rect?.width ?? 232, rect?.height ?? 244))
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || trigger?.contains(target)) return
      onClose(false)
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose(true)
      }
    }

    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [anchorRect, onClose, trigger])

  const runAction = (callback: () => void) => {
    callback()
    onClose(false)
  }

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
    if (items.length === 0) return
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)
    const nextIndex =
      event.key === 'ArrowDown'
        ? (currentIndex + 1) % items.length
        : (currentIndex - 1 + items.length) % items.length
    items[nextIndex].focus()
  }

  return createPortal(
    <div
      ref={menuRef}
      className={styles.rowMenu}
      role="menu"
      aria-label={`Actions pour ${expert.nom_denomination}`}
      onKeyDown={handleMenuKeyDown}
      style={{ top: position.top, left: position.left }}
    >
      <button type="button" role="menuitem" onClick={() => runAction(onView)}>
        <Eye aria-hidden="true" size={16} />
        Voir la fiche
      </button>
      <button type="button" role="menuitem" onClick={() => runAction(onEdit)}>
        <Pencil aria-hidden="true" size={16} />
        Modifier
      </button>
      <button type="button" role="menuitem" onClick={() => runAction(onCategoryChange)}>
        <Repeat2 aria-hidden="true" size={16} />
        Changer de catégorie
      </button>
      <button type="button" role="menuitem" onClick={() => runAction(onViewHistory)}>
        <History aria-hidden="true" size={16} />
        Voir l'historique
      </button>
      <div className={styles.rowMenuDivider} />
      <button type="button" role="menuitem" onClick={() => runAction(onToggleActive)}>
        {expert.active === false ? <RotateCcw aria-hidden="true" size={16} /> : <Ban aria-hidden="true" size={16} />}
        {expert.active === false ? 'Réactiver' : 'Désactiver'}
      </button>
      {expert.active !== false && (
        <button type="button" role="menuitem" className={styles.dangerMenuItem} onClick={() => runAction(onArchive)}>
          <Archive aria-hidden="true" size={16} />
          Archiver
        </button>
      )}
    </div>,
    document.body
  )
}

export default function ExpertsComptables() {
  const { notifyError, notifySuccess, notifyWarning, notifyInfo } = useToast()
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [loading, setLoading] = useState(true)
  // Distinct de `loading`, qui décrit le chargement de la liste : un export
  // parti en file (202) peut durer sans que la table cesse d'être affichable.
  const [exportExcelEnCours, setExportExcelEnCours] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [initialLoad, setInitialLoad] = useState(true)
  const [search, setSearch] = useState('')
  // La requête part quand la frappe s'arrête, pas à chaque touche.
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [loadError, setLoadError] = useState(false)
  const [provinces, setProvinces] = useState<string[]>([])
  const loadSeq = useRef(0)
  const [filterStatutProf, setFilterStatutProf] = useState<string>('')
  const [filterActive, setFilterActive] = useState<string>('true')
  const [filterProvince, setFilterProvince] = useState('')
  const [filterCategory, setFilterCategory] = useState<ExpertCategoryFilter>('')
  const [sortField, setSortField] = useState<'numero_ordre' | 'nom_denomination' | ''>('nom_denomination')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [showForm, setShowForm] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [showCategoryChange, setShowCategoryChange] = useState(false)
  const [showSuccessNotification, setShowSuccessNotification] = useState(false)
  const [successNotificationData, setSuccessNotificationData] = useState({ title: '', message: '' })
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [selectedExpert, setSelectedExpert] = useState<ExpertComptable | null>(null)
  const [showMoreCols, setShowMoreCols] = useState(() => {
    try {
      const stored = window.localStorage.getItem('experts_show_more_cols')
      return stored === 'true'
    } catch {
      return false
    }
  })
  const [isSavingCreate, setIsSavingCreate] = useState(false)
  const [showEditForm, setShowEditForm] = useState(false)
  const [editingExpert, setEditingExpert] = useState<ExpertComptable | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [expertToDelete, setExpertToDelete] = useState<ExpertComptable | null>(null)
  const [isDeletingExpert, setIsDeletingExpert] = useState(false)
  const [detailExpert, setDetailExpert] = useState<ExpertComptable | null>(null)
  const [actionMenu, setActionMenu] = useState<ActionMenuState | null>(null)
  const [categoryChangeNumero, setCategoryChangeNumero] = useState('')
  const [historyVersion, setHistoryVersion] = useState(0)
  const [historyScrollRequest, setHistoryScrollRequest] = useState(0)
  const historySectionRef = useRef<HTMLElement | null>(null)
  const activeMenuButtonRef = useRef<HTMLButtonElement | null>(null)
  const [pageSize, setPageSize] = useState(25)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [summary, setSummary] = useState(emptySummary)
  const loadingToast = isSavingEdit
    ? 'Enregistrement en cours...'
    : isDeletingExpert
      ? 'Archivage en cours...'
      : null

  const closeActionMenu = (restoreFocus = false) => {
    setActionMenu(null)
    if (restoreFocus) {
      window.setTimeout(() => activeMenuButtonRef.current?.focus(), 0)
    }
  }

  const openActionMenu = (expert: ExpertComptable, button: HTMLButtonElement) => {
    if (actionMenu?.expert.id === expert.id) {
      closeActionMenu(true)
      return
    }
    activeMenuButtonRef.current = button
    setActionMenu({
      expert,
      anchorRect: button.getBoundingClientRect(),
    })
  }

  const [formData, setFormData] = useState<ExpertFormValues>(emptyFormValues)
  const [editFormData, setEditFormData] = useState<ExpertFormValues>(emptyFormValues)

  const loadExperts = async () => {
    // Seule la dernière requête partie a le droit d'afficher son résultat.
    const seq = ++loadSeq.current
    try {
      setIsFetching(true)
      if (initialLoad) {
        setLoading(true)
      }
      const includeInactive = filterActive === ''
      const activeParam = filterActive === 'true' ? true : filterActive === 'false' ? false : undefined
      const res: any = await apiRequest('GET', '/experts-comptables', {
        params: {
          q: debouncedSearch || undefined,
          statut_professionnel: filterStatutProf || undefined,
          province_attache: filterProvince || undefined,
          category: filterCategory || undefined,
          include_inactive: includeInactive ? true : undefined,
          active: includeInactive ? undefined : activeParam,
          order: sortField ? `${sortField}.${sortDirection}` : 'nom_denomination.asc',
          limit: pageSize,
          offset: (page - 1) * pageSize,
          include_summary: true,
        }
      })
      if (seq !== loadSeq.current) return
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setLoadError(false)
      setExperts(items as any)
      setTotalCount(typeof res?.total === 'number' ? res.total : items.length)
      setSummary(res?.summary ? { ...emptySummary, ...res.summary } : emptySummary)
    } catch (error: any) {
      console.error('Error loading experts:', error)
      if (seq !== loadSeq.current) return
      setLoadError(true)
      setExperts([])
      setTotalCount(0)
      notifyError('Chargement impossible', error?.message || 'Impossible de charger la liste des experts-comptables.')
    } finally {
      if (seq === loadSeq.current) {
        setIsFetching(false)
        setLoading(false)
        setInitialLoad(false)
      }
    }
  }

  const loadProvinces = async () => {
    try {
      setProvinces(await apiRequest<string[]>('GET', '/experts-comptables/provinces'))
    } catch (error) {
      console.error('Error loading provinces:', error)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    loadExperts()
  }, [debouncedSearch, filterStatutProf, filterActive, filterProvince, filterCategory, sortField, sortDirection, pageSize, page])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, filterStatutProf, filterActive, filterProvince, filterCategory, sortField, sortDirection, pageSize])

  useEffect(() => {
    loadProvinces()
  }, [])

  useEffect(() => {
    if (historyScrollRequest > 0) {
      historySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [historyScrollRequest])

  // Le panneau et le formulaire gardent leur copie de l'expert : sans cette mise
  // à jour, ils affichaient l'ancien état après une action (bouton Désactiver
  // resté en place sur un expert déjà désactivé).
  const syncExpert = (updated: ExpertComptable) => {
    setDetailExpert((current) => (current?.id === updated.id ? updated : current))
    setEditingExpert((current) => (current?.id === updated.id ? updated : current))
  }

  const openCreateForm = () => {
    setFormData(emptyFormValues)
    setShowForm(true)
  }

  const closeCreateForm = () => {
    if (isSavingCreate) return
    setShowForm(false)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isSavingCreate) return

    const manquant = champManquantAjout(formData)
    if (manquant) {
      notifyWarning('Champs requis manquants', `Veuillez renseigner ${manquant}.`)
      return
    }

    setIsSavingCreate(true)
    try {
      await apiRequest('POST', '/experts-comptables', {
        numero_ordre: formData.numero_ordre.trim(),
        nom_denomination: formData.nom_denomination.trim(),
        ...classementDeCategorie(formData.categorie),
        ...champsDeCategorie(formData),
        email: formData.email.trim() || null,
        telephone: formData.telephone.trim() || null,
        province_attache: formData.province_attache || null,
        sexe: formData.categorie === 'SEC' ? null : (formData.sexe || null),
        active: true,
      })

      notifySuccess('Expert ajouté', "L'expert-comptable a été ajouté avec succès.")
      setShowForm(false)
      setFormData(emptyFormValues)
      loadExperts()
      loadProvinces()
    } catch (error: any) {
      console.error('Error creating expert:', error)
      if (error?.status === 409) {
        notifyWarning("Numéro d'ordre existant", "Ce numéro d'ordre existe déjà dans le système.")
      } else {
        notifyError("Erreur d'ajout", error?.message || "Une erreur est survenue lors de l'ajout de l'expert-comptable.")
      }
    } finally {
      setIsSavingCreate(false)
    }
  }

  const toggleActiveStatus = (expert: ExpertComptable) => {
    setSelectedExpert(expert)
    setShowDeactivateModal(true)
  }

  const openEditForm = (expert: ExpertComptable) => {
    setEditingExpert(expert)
    setEditFormData(expertToFormValues(expert))
    setShowEditForm(true)
  }

  const closeEditForm = () => {
    if (isSavingEdit) return
    setShowEditForm(false)
    setEditingExpert(null)
  }

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingExpert || isSavingEdit) return

    if (!editFormData.nom_denomination.trim()) {
      notifyWarning('Champs requis manquants', 'Veuillez remplir le nom/dénomination.')
      return
    }

    setIsSavingEdit(true)
    try {
      // Une catégorie déjà attribuée ne change que par le parcours historisé ;
      // seule une fiche non classée reçoit ici son classement.
      const classement = !getExpertCategory(editingExpert) && editFormData.categorie
        ? classementDeCategorie(editFormData.categorie)
        : {}
      const updated = await apiRequest<ExpertComptable>('PUT', `/experts-comptables/${editingExpert.id}`, {
        nom_denomination: editFormData.nom_denomination.trim(),
        ...classement,
        ...champsDeCategorie(editFormData),
        email: editFormData.email.trim() || null,
        telephone: editFormData.telephone.trim() || null,
        province_attache: editFormData.province_attache || null,
        sexe: editFormData.categorie === 'SEC' ? null : (editFormData.sexe || null),
      })
      syncExpert(updated)

      setSuccessNotificationData({
        title: 'Expert mis à jour',
        message: `${editingExpert.nom_denomination} a été mis à jour avec succès.`,
      })
      setShowSuccessNotification(true)
      setShowEditForm(false)
      setEditingExpert(null)
      loadExperts()
      loadProvinces()
    } catch (error: any) {
      console.error('Error updating expert:', error)
      notifyError('Mise à jour impossible', error?.message || "Impossible de mettre à jour l'expert-comptable.")
    } finally {
      setIsSavingEdit(false)
    }
  }

  const handleDeleteExpert = async (expert: ExpertComptable) => {
    setExpertToDelete(expert)
    setShowDeleteModal(true)
  }

  const confirmDeleteExpert = async () => {
    if (!expertToDelete) return
    if (isDeletingExpert) return
    setIsDeletingExpert(true)
    try {
      await apiRequest('DELETE', `/experts-comptables/${expertToDelete.id}`)
      syncExpert({ ...expertToDelete, active: false })
      setSuccessNotificationData({
        title: 'Expert archivé',
        message: `${expertToDelete.nom_denomination} a été archivé avec succès.`,
      })
      setShowSuccessNotification(true)
      loadExperts()
    } catch (error: any) {
      console.error('Error deleting expert:', error)
      notifyError('Archivage impossible', error?.message || "Impossible d’archiver cet expert.")
    } finally {
      setIsDeletingExpert(false)
      setShowDeleteModal(false)
      setExpertToDelete(null)
    }
  }

  const openDeactivateFromEdit = () => {
    if (!editingExpert) return
    setSelectedExpert(editingExpert)
    setShowDeactivateModal(true)
  }

  const confirmToggleStatus = async () => {
    if (!selectedExpert) return

    const newActiveStatus = !selectedExpert.active

    try {
      syncExpert(await apiRequest<ExpertComptable>('PATCH', `/experts-comptables/${selectedExpert.id}`, { active: newActiveStatus }))

      setSuccessNotificationData({
        title: 'Statut modifié avec succès',
        message: `${selectedExpert.nom_denomination} a été ${newActiveStatus ? 'réactivé' : 'désactivé'} avec succès.`
      })
      setShowSuccessNotification(true)
      loadExperts()
    } catch (error) {
      console.error('Error toggling expert status:', error)
      notifyError('Modification impossible', "Impossible de modifier le statut de l'expert-comptable.")
    } finally {
      setShowDeactivateModal(false)
      setSelectedExpert(null)
    }
  }

  const handleExportToExcel = async () => {
    if (exportExcelEnCours) return
    const includeInactive = filterActive === ''
    const activeParam = filterActive === 'true' ? true : filterActive === 'false' ? false : undefined
    const date = new Date().toISOString().split('T')[0]
    // Sans ce catch, un échec d'export partait en rejet de promesse non traité :
    // l'utilisateur cliquait, rien ne se passait, aucun message.
    setExportExcelEnCours(true)
    try {
      await downloadExcel('/exports/experts-comptables', {
        q: search || undefined,
        statut_professionnel: filterStatutProf || undefined,
        province_attache: filterProvince || undefined,
        category: filterCategory || undefined,
        include_inactive: includeInactive ? true : undefined,
        active: includeInactive ? undefined : activeParam,
        order: sortField ? `${sortField}.${sortDirection}` : 'nom_denomination.asc',
      }, `experts_comptables_${date}.xlsx`, {
        // Le serveur a répondu 202 : la génération se poursuit dans le worker.
        // Sans ce message, l'attente est indiscernable d'une interface figée.
        onMiseEnFile: () =>
          notifyInfo(
            'Export en préparation',
            "Cet export est généré en arrière-plan. Laissez cette page ouverte : le téléchargement démarrera automatiquement dès que le fichier sera prêt.",
          ),
      })
    } catch (error: any) {
      notifyError('Export Excel impossible', error?.message || "Impossible d'exporter les experts-comptables.")
    } finally {
      setExportExcelEnCours(false)
    }
  }


  const handleSort = (field: 'numero_ordre' | 'nom_denomination') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
    setPage(1)
  }

  const provinceOptions = useMemo(() => {
    return Array.from(new Set([...provinces, ...(filterProvince ? [filterProvince] : [])])).sort((a, b) =>
      a.localeCompare(b)
    )
  }, [provinces, filterProvince])

  const toggleCategoryFilter = (category: ExpertCategoryFilter) => {
    setFilterCategory((current) => (current === category ? '' : category))
  }

  const filteredExperts = experts

  const summaryItems = useMemo(() => {
    return [
      { label: 'Total experts', value: summary.total || totalCount, tone: 'total', active: !filterActive && !filterCategory, onClick: () => { setFilterActive(''); setFilterCategory('') } },
      { label: 'Actifs', value: summary.active, tone: 'active', active: filterActive === 'true', onClick: () => setFilterActive('true') },
      { label: 'Inactifs', value: summary.inactive, tone: 'inactive', active: filterActive === 'false', onClick: () => setFilterActive('false') },
      { label: 'SEC', value: summary.sec, tone: 'sec', active: filterCategory === 'SEC', onClick: () => toggleCategoryFilter('SEC') },
      { label: 'En cabinet', value: summary.cabinet, tone: 'cabinet', active: filterCategory === 'En Cabinet', onClick: () => toggleCategoryFilter('En Cabinet') },
      { label: 'Indépendants', value: summary.independant, tone: 'independant', active: filterCategory === 'Indépendant', onClick: () => toggleCategoryFilter('Indépendant') },
      { label: 'Salariés', value: summary.salarie, tone: 'salarie', active: filterCategory === 'Salarié', onClick: () => toggleCategoryFilter('Salarié') },
    ]
  }, [filterActive, filterCategory, summary, totalCount])

  const displayedTotal = totalCount
  const totalPages = Math.max(1, Math.ceil(displayedTotal / pageSize))
  const safePage = Math.min(page, totalPages)
  const paginatedExperts = filteredExperts
  const rangeStart = displayedTotal === 0 ? 0 : (safePage - 1) * pageSize + 1
  const rangeEnd = Math.min(safePage * pageSize, displayedTotal)
  const hasActiveFilters = Boolean(search || filterStatutProf || filterActive !== 'true' || filterProvince || filterCategory)

  const resetFilters = () => {
    setSearch('')
    setFilterStatutProf('')
    setFilterActive('true')
    setFilterProvince('')
    setFilterCategory('')
    setPage(1)
  }

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  useEffect(() => {
    closeActionMenu(false)
  }, [page, pageSize, search, filterStatutProf, filterActive, filterProvince, filterCategory])

  useEffect(() => {
    if (!actionMenu) return
    if (!experts.some((expert) => expert.id === actionMenu.expert.id)) {
      closeActionMenu(false)
    }
  }, [actionMenu, experts])

  // Échap ferme ce qui est au premier plan : le formulaire, puis la fiche.
  // Le menu de ligne gère sa touche ; les autres fenêtres gardent leurs boutons.
  useEffect(() => {
    if (!showEditForm && !detailExpert) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || actionMenu) return
      if (showForm || showImport || showCategoryChange || showDeactivateModal || showDeleteModal) return
      if (showEditForm) closeEditForm()
      else setDetailExpert(null)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [showEditForm, detailExpert, actionMenu, showForm, showImport, showCategoryChange, showDeactivateModal, showDeleteModal, isSavingEdit])

  if (loading) {
    return (
      <LoadingScreen
        message="Chargement des experts-comptables"
        subtitle="Récupération de la liste des experts-comptables..."
        showProgress={true}
        showTip={true}
      />
    )
  }

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <div className={styles.titleBlock}>
          <h1>Experts-comptables</h1>
          <p>Référentiel national des experts-comptables</p>
        </div>
        <div className={styles.headerActions}>
          <button type="button" onClick={openCreateForm} className={styles.primaryBtn} aria-label="Ajouter un expert">
            <UserRoundPlus size={17} aria-hidden="true" /> Ajouter un expert
          </button>
          <button type="button" onClick={() => setShowImport(true)} className={styles.secondaryBtn}>
            <FileUp size={16} aria-hidden="true" /> Importer Excel
          </button>
          <button
            type="button"
            onClick={handleExportToExcel}
            className={styles.secondaryBtn}
            disabled={exportExcelEnCours}
          >
            <Download size={16} aria-hidden="true" />
            {exportExcelEnCours ? 'Export en cours…' : 'Exporter Excel'}
          </button>
          <button type="button" onClick={() => { setCategoryChangeNumero(''); setShowCategoryChange(true) }} className={styles.secondaryBtn}>
            <Repeat2 size={16} aria-hidden="true" /> Changer de catégorie
          </button>
        </div>
      </header>

      <section className={styles.filtersCard} aria-label="Recherche et filtres">
        <div className={styles.searchBar}>
          <label htmlFor="experts-search">Recherche</label>
          <input
            id="experts-search"
            type="text"
            placeholder="Rechercher par numéro, nom, NIF, e-mail, cabinet, employeur ou province..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className={styles.filtersGrid}>
          <div className={styles.filterGroup}>
            <label htmlFor="experts-page-size">Éléments</label>
            <select
              id="experts-page-size"
              value={String(pageSize)}
              onChange={(e) => {
                setPageSize(Number(e.target.value))
                setPage(1)
              }}
            >
              <option value="10">10 / page</option>
              <option value="25">25 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="experts-active">État</label>
            <select id="experts-active" value={filterActive} onChange={(e) => setFilterActive(e.target.value)}>
              <option value="true">Actifs</option>
              <option value="false">Inactifs</option>
              <option value="">Tous</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="experts-category">Catégorie</label>
            <select
              id="experts-category"
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value as ExpertCategoryFilter)}
            >
              <option value="">Toutes</option>
              <option value="SEC">SEC</option>
              <option value="En Cabinet">En cabinet</option>
              <option value="Indépendant">Indépendants</option>
              <option value="Salarié">Salariés</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="experts-statut">Statut professionnel</label>
            <select id="experts-statut" value={filterStatutProf} onChange={(e) => setFilterStatutProf(e.target.value)}>
              <option value="">Tous</option>
              <option value="En Cabinet">En Cabinet</option>
              <option value="Indépendant">Indépendant</option>
              <option value="Salarié">Salarié</option>
              <option value="Cabinet">Cabinet</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label htmlFor="experts-province">Province d'attache</label>
            <select id="experts-province" value={filterProvince} onChange={(e) => setFilterProvince(e.target.value)}>
              <option value="">Toutes</option>
              {provinceOptions.map((province) => (
                <option key={province} value={province}>{province}</option>
              ))}
            </select>
          </div>
          <div className={styles.filterActions}>
            <button type="button" onClick={resetFilters} className={styles.clearFiltersBtn} disabled={!hasActiveFilters}>
              Réinitialiser
            </button>
          </div>
        </div>
      </section>

      <section className={styles.summaryStrip} aria-label="Indicateurs experts-comptables">
        {summaryItems.map((item) => (
          <button
            key={item.label}
            type="button"
            className={`${styles.summaryChip} ${item.active ? styles.summaryChipActive : ''}`}
            data-tone={item.tone}
            onClick={item.onClick}
          >
            <i aria-hidden="true" />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </button>
        ))}
      </section>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <div className={styles.modalHeading}>
                <span className={styles.modalIcon}><UserRoundPlus size={20} aria-hidden="true" /></span>
                <div><h2>Ajouter un expert-comptable</h2><p>Créez une fiche complète dans le référentiel.</p></div>
              </div>
              <button type="button" onClick={closeCreateForm} className={styles.closeBtn} disabled={isSavingCreate} aria-label="Fermer">×</button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <ExpertFormFields
                values={formData}
                onChange={setFormData}
                idPrefix="expert-ajout"
                isCreate
                categoryLocked={false}
              />

              <div className={styles.formActions}>
                <button type="button" onClick={closeCreateForm} className={styles.secondaryBtn} disabled={isSavingCreate}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={isSavingCreate}>
                  {isSavingCreate ? (
                    <>
                      <span className={`${styles.spinner} ${styles.spinnerDark}`} />
                      Enregistrement...
                    </>
                  ) : (
                    'Ajouter'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showEditForm && editingExpert && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <div className={styles.modalHeading}>
                <span className={styles.modalIcon}><Pencil size={19} aria-hidden="true" /></span>
                <div><h2>Modifier l’expert-comptable</h2><p>Mettez à jour les informations de la fiche.</p></div>
              </div>
              <button type="button" onClick={closeEditForm} className={styles.closeBtn} disabled={isSavingEdit} aria-label="Fermer">×</button>
            </div>

            <form onSubmit={handleEditSubmit} className={styles.form}>
              <ExpertFormFields
                values={editFormData}
                onChange={setEditFormData}
                idPrefix="expert-modif"
                isCreate={false}
                categoryLocked={Boolean(getExpertCategory(editingExpert))}
              />

              <div className={styles.formActions}>
                <button type="button" onClick={closeEditForm} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={openDeactivateFromEdit}
                  className={styles.deactivateBtn}
                  disabled={isSavingEdit}
                >
                  {editingExpert.active === false ? <RotateCcw size={16} aria-hidden="true" /> : <Ban size={16} aria-hidden="true" />}
                  {editingExpert.active === false ? 'Réactiver' : 'Désactiver'}
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={isSavingEdit}>
                  {isSavingEdit ? (
                    <>
                      <span className={`${styles.spinner} ${styles.spinnerDark}`} />
                      Enregistrement...
                    </>
                  ) : (
                    'Enregistrer'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showDeleteModal && expertToDelete && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <div className={styles.modalHeading}>
                <span className={`${styles.modalIcon} ${styles.modalIconDanger}`}><Archive size={19} aria-hidden="true" /></span>
                <h2>Confirmer l’archivage</h2>
              </div>
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                className={styles.closeBtn}
                disabled={isDeletingExpert}
              >
                ×
              </button>
            </div>
            <div className={styles.modalBody}>
              <p>
                Voulez-vous archiver
                <strong> {expertToDelete.nom_denomination}</strong> ?
              </p>
              <p className={styles.modalHint}>
                L’expert restera dans l’historique, mais n’apparaîtra plus pour les nouvelles opérations.
              </p>
            </div>
            <div className={styles.formActions}>
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                className={styles.secondaryBtn}
                disabled={isDeletingExpert}
              >
                Annuler
              </button>
              <button type="button" onClick={confirmDeleteExpert} className={styles.deleteBtn} disabled={isDeletingExpert}>
                {isDeletingExpert ? (
                  <>
                    <span className={styles.spinner} />
                    Archivage...
                  </>
                ) : (
                  <>
                    <Archive size={16} aria-hidden="true" /> Archiver
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <Suspense fallback={null}>
          <ImportModules
            onClose={() => setShowImport(false)}
            onSuccess={() => {
              setSortField('nom_denomination')
              setSortDirection('asc')
              setPage(1)
              // Tri et page déjà à ces valeurs : aucun effet ne relancerait le chargement.
              loadExperts()
              loadProvinces()
            }}
          />
        </Suspense>
      )}

      {showCategoryChange && (
        <CategoryChange
          initialNumeroOrdre={categoryChangeNumero}
          onClose={() => {
            setShowCategoryChange(false)
            setCategoryChangeNumero('')
          }}
          onSuccess={() => {
            loadExperts()
            setHistoryVersion((version) => version + 1)
            if (detailExpert) {
              apiRequest<ExpertComptable>('GET', `/experts-comptables/${detailExpert.id}`)
                .then(syncExpert)
                .catch((error) => console.error('Error refreshing expert:', error))
            }
            setSuccessNotificationData({
              title: 'Changement de catégorie effectué',
              message: 'Les informations de l\'expert-comptable ont été mises à jour avec succès'
            })
            setShowSuccessNotification(true)
          }}
        />
      )}

      {showSuccessNotification && (
        <SuccessNotification
          title={successNotificationData.title}
          message={successNotificationData.message}
          onClose={() => setShowSuccessNotification(false)}
        />
      )}

      {loadingToast && (
        <div className={styles.toast}>
          <span className={`${styles.spinner} ${styles.spinnerDark}`} />
          {loadingToast}
        </div>
      )}

      <DeactivateExpertModal
        isOpen={showDeactivateModal}
        expert={selectedExpert}
        onConfirm={confirmToggleStatus}
        onCancel={() => {
          setShowDeactivateModal(false)
          setSelectedExpert(null)
        }}
        isReactivate={selectedExpert?.active === false}
      />

      <section className={styles.tableSection}>
        <div className={styles.tableToolbar}>
          <div>
            <h2>Liste des experts</h2>
            <p>
              {rangeStart}-{rangeEnd} sur {displayedTotal} expert{displayedTotal > 1 ? 's' : ''}
            </p>
          </div>
          <div className={styles.toolbarActions}>
            {isFetching && <span className={styles.fetchHint}>Mise à jour…</span>}
            <button
              type="button"
              onClick={() => {
                setShowMoreCols((value) => {
                  const next = !value
                  try {
                    window.localStorage.setItem('experts_show_more_cols', String(next))
                  } catch {}
                  return next
                })
              }}
              className={styles.tertiaryBtn}
            >
              {showMoreCols ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
              {showMoreCols ? 'Afficher moins' : 'Afficher plus'}
            </button>
          </div>
        </div>

        <div className={styles.tableContainer}>
          <table className={`${styles.table} ${showMoreCols ? styles.tableWide : ''}`}>
          <thead>
            <tr>
              <th className={`${styles.sortableHeader} ${styles.expertCol}`} onClick={() => handleSort('nom_denomination')}>
                Expert
                {sortField === 'nom_denomination' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th className={`${styles.sortableHeader} ${styles.orderCol}`} onClick={() => handleSort('numero_ordre')}>
                N° d'ordre
                {sortField === 'numero_ordre' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th className={styles.provinceCol}>Province</th>
              <th className={styles.categoryCol}>Catégorie</th>
              <th className={styles.attachmentCol}>Cabinet / employeur</th>
              {showMoreCols && (
                <>
                  <th className={styles.nifCol}>NIF</th>
                  <th className={styles.sexeCol}>Sexe</th>
                  <th className={styles.attachmentCol}>Associé gérant</th>
                </>
              )}
              <th className={styles.emailCol}>Email</th>
              <th className={styles.phoneCol}>Téléphone</th>
              <th className={styles.statusCol}>État</th>
              <th className={styles.actionsCol}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedExperts.map((expert) => (
              <tr key={expert.id} className={expert.active === false ? styles.inactiveRow : ''}>
                <td className={styles.expertCol}>
                  <button type="button" className={styles.expertIdentity} onClick={() => setDetailExpert(expert)}>
                    <span className={styles.avatar}>{getInitials(expert.nom_denomination)}</span>
                    <span className={styles.identityText}>
                      <strong>{expert.nom_denomination}</strong>
                      <small>{expert.categorie_personne || expert.type_ec}</small>
                    </span>
                  </button>
                </td>
                <td className={styles.orderCol}><strong>{expert.numero_ordre}</strong></td>
                <td className={styles.provinceCol}>{expert.province_attache || '-'}</td>
                <td className={styles.categoryCol}>
                  <span className={`${styles.categoryBadge} ${getCategoryClass(getCategoryLabel(expert))}`}>
                    {getCategoryLabel(expert)}
                  </span>
                </td>
                <td className={styles.attachmentCol}>{getAttachment(expert)}</td>
                {showMoreCols && (
                  <>
                    <td className={styles.nifCol}>{expert.nif || '-'}</td>
                    <td className={styles.sexeCol}>{expert.sexe || '-'}</td>
                    <td className={styles.attachmentCol}>{expert.associe_gerant || '-'}</td>
                  </>
                )}
                <td className={styles.emailCol}>{expert.email || '-'}</td>
                <td className={styles.phoneCol}>{expert.telephone || '-'}</td>
                <td className={styles.statusCol}>
                  <span className={expert.active === false ? styles.badgeArchived : styles.badgeActive}>
                    {expert.active === false ? 'Inactif' : 'Actif'}
                  </span>
                </td>
                <td className={styles.actionsCol}>
                  <div className={styles.actionsCell}>
                    {/* Voir et Modifier vivent dans le menu ⋮, et le nom de
                        l'expert ouvre déjà sa fiche : les répéter ici volait à
                        la table une colonne entière pour rien. */}
                    <button
                      type="button"
                      className={styles.menuBtn}
                      aria-label={`Plus d'actions pour ${expert.nom_denomination}`}
                      aria-haspopup="menu"
                      aria-expanded={actionMenu?.expert.id === expert.id}
                      title="Plus d'actions"
                      onClick={(event) => openActionMenu(expert, event.currentTarget)}
                    >
                      ⋮
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {paginatedExperts.length === 0 && (
          <div className={styles.emptyState}>
            {loadError ? (
              <>
                <h3>La liste n'a pas pu être chargée</h3>
                <button type="button" onClick={loadExperts} className={styles.secondaryBtn}>
                  Réessayer
                </button>
              </>
            ) : (
              <>
                <h3>{hasActiveFilters ? 'Aucun résultat pour ces filtres' : 'Aucun expert trouvé'}</h3>
                <p>Modifiez la recherche ou réinitialisez les filtres pour élargir la liste.</p>
                {hasActiveFilters && (
                  <button type="button" onClick={resetFilters} className={styles.secondaryBtn}>
                    Réinitialiser les filtres
                  </button>
                )}
              </>
            )}
          </div>
        )}
        </div>
      </section>

      {displayedTotal > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            {rangeStart}-{rangeEnd} sur {displayedTotal} · Page {safePage} / {totalPages}
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

      {actionMenu && (
        <ExpertActionMenu
          expert={actionMenu.expert}
          anchorRect={actionMenu.anchorRect}
          trigger={activeMenuButtonRef.current}
          onClose={closeActionMenu}
          onView={() => setDetailExpert(actionMenu.expert)}
          onViewHistory={() => {
            setDetailExpert(actionMenu.expert)
            setHistoryScrollRequest((request) => request + 1)
          }}
          onEdit={() => openEditForm(actionMenu.expert)}
          onCategoryChange={() => {
            setCategoryChangeNumero(actionMenu.expert.numero_ordre)
            setShowCategoryChange(true)
          }}
          onToggleActive={() => toggleActiveStatus(actionMenu.expert)}
          onArchive={() => handleDeleteExpert(actionMenu.expert)}
        />
      )}

      {detailExpert && (
        <>
        <button type="button" className={styles.detailBackdrop} onClick={() => setDetailExpert(null)} aria-label="Fermer la fiche" />
        <aside className={styles.detailPanel} aria-label="Détail expert-comptable">
          <div className={styles.detailHeader}>
            <div className={styles.detailIdentity}>
              <span className={styles.detailAvatar}>{getInitials(detailExpert.nom_denomination)}</span>
              <div>
                <h2>{detailExpert.nom_denomination}</h2>
                <p>{detailExpert.numero_ordre} <span className={detailExpert.active === false ? styles.badgeArchived : styles.badgeActive}>{detailExpert.active === false ? 'Inactif' : 'Actif'}</span></p>
              </div>
            </div>
            <button type="button" onClick={() => setDetailExpert(null)} className={styles.panelCloseBtn} aria-label="Fermer le détail">
              ×
            </button>
          </div>

          <div className={styles.detailBody}>
            <section className={styles.detailSection}>
              <h3>Identité</h3>
              <dl className={styles.detailList}>
                <div><dt>Catégorie</dt><dd>{getCategoryLabel(detailExpert)}</dd></div>
                {detailExpert.categorie_personne === 'Personne Physique' && (
                  <div><dt>Sexe</dt><dd>{detailExpert.sexe === 'M' ? 'Masculin' : detailExpert.sexe === 'F' ? 'Féminin' : '-'}</dd></div>
                )}
                <div><dt>Province</dt><dd>{detailExpert.province_attache || '-'}</dd></div>
                <div><dt>Type</dt><dd>{detailExpert.type_ec || '-'}</dd></div>
                <div><dt>Statut</dt><dd>{detailExpert.active === false ? 'Inactif' : 'Actif'}</dd></div>
              </dl>
            </section>

            <section className={styles.detailSection}>
              <h3>Notes de débit</h3>
              <RegulariteExpert expertId={detailExpert.id} numeroOrdre={detailExpert.numero_ordre} />
            </section>

            <section className={styles.detailSection}>
              <h3>Rattachement</h3>
              <dl className={styles.detailList}>
                <div><dt>Cabinet</dt><dd>{detailExpert.cabinet_attache || '-'}</dd></div>
                <div><dt>Employeur</dt><dd>{detailExpert.nom_employeur || '-'}</dd></div>
                <div><dt>Raison sociale</dt><dd>{detailExpert.raison_sociale || '-'}</dd></div>
                <div><dt>Associé gérant</dt><dd>{detailExpert.associe_gerant || '-'}</dd></div>
              </dl>
            </section>

            <section className={styles.detailSection}>
              <h3>Contact et références</h3>
              <dl className={styles.detailList}>
                <div><dt>E-mail</dt><dd>{detailExpert.email || '-'}</dd></div>
                <div><dt>Téléphone</dt><dd>{detailExpert.telephone || '-'}</dd></div>
                <div><dt>NIF</dt><dd>{detailExpert.nif || '-'}</dd></div>
                <div><dt>Import d'origine</dt><dd>{detailExpert.import_id || '-'}</dd></div>
              </dl>
            </section>

            <section className={styles.detailSection} ref={historySectionRef}>
              <h3>Historique</h3>
              <ExpertHistory expertId={detailExpert.id} version={historyVersion} />
            </section>
          </div>

          <div className={styles.detailActions}>
            <button type="button" className={styles.secondaryBtn} onClick={() => openEditForm(detailExpert)}>
              <Pencil size={16} aria-hidden="true" /> Modifier
            </button>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => {
                setCategoryChangeNumero(detailExpert.numero_ordre)
                setShowCategoryChange(true)
              }}
            >
              <Repeat2 size={16} aria-hidden="true" /> Changer de catégorie
            </button>
            <button
              type="button"
              className={detailExpert.active === false ? styles.reactivateActionBtn : styles.deactivateActionBtn}
              onClick={() => toggleActiveStatus(detailExpert)}
            >
              {detailExpert.active === false ? <RotateCcw size={16} aria-hidden="true" /> : <Ban size={16} aria-hidden="true" />}
              {detailExpert.active === false ? 'Réactiver' : 'Désactiver'}
            </button>
          </div>
        </aside>
        </>
      )}

    </div>
  )
}
