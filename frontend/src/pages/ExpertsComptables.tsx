import { useState, useEffect, useLayoutEffect, useMemo, useRef, lazy, Suspense } from 'react'
import { createPortal } from 'react-dom'
import { Archive, Ban, Eye, History, Pencil, Repeat2, RotateCcw } from 'lucide-react'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, CategoriePersonne, StatutProfessionnel } from '../types'
// xlsx est lourd : chargement dynamique seulement à l'ouverture de la modale d'import.
const ImportModules = lazy(() => import('../components/ImportModules'))
import CategoryChange from '../components/CategoryChange'
import SuccessNotification from '../components/SuccessNotification'
import LoadingScreen from '../components/LoadingScreen'
import DeactivateExpertModal from '../components/DeactivateExpertModal'
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

const emptySummary = {
  total: 0,
  active: 0,
  inactive: 0,
  suspended: 0,
  sec: 0,
  cabinet: 0,
  independant: 0,
  salarie: 0,
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
      <button type="button" role="menuitem" onClick={() => runAction(onView)}>
        <History aria-hidden="true" size={16} />
        Voir l'historique
      </button>
      <div className={styles.rowMenuDivider} />
      <button type="button" role="menuitem" onClick={() => runAction(onToggleActive)}>
        {expert.active === false ? <RotateCcw aria-hidden="true" size={16} /> : <Ban aria-hidden="true" size={16} />}
        {expert.active === false ? 'Réactiver' : 'Désactiver'}
      </button>
      <button type="button" role="menuitem" className={styles.dangerMenuItem} onClick={() => runAction(onArchive)}>
        <Archive aria-hidden="true" size={16} />
        Archiver
      </button>
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
  const [showEditForm, setShowEditForm] = useState(false)
  const [editingExpert, setEditingExpert] = useState<ExpertComptable | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [expertToDelete, setExpertToDelete] = useState<ExpertComptable | null>(null)
  const [isDeletingExpert, setIsDeletingExpert] = useState(false)
  const [detailExpert, setDetailExpert] = useState<ExpertComptable | null>(null)
  const [actionMenu, setActionMenu] = useState<ActionMenuState | null>(null)
  const [categoryChangeNumero, setCategoryChangeNumero] = useState('')
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

  const [formData, setFormData] = useState({
    numero_ordre: '',
    nom_denomination: '',
    type_ec: 'EC',
    email: '',
    telephone: '',
    province_attache: '',
    categorie_personne: '' as CategoriePersonne | '',
    statut_professionnel: '' as StatutProfessionnel | '',
    cabinet_attache: '',
  })

  const [editFormData, setEditFormData] = useState({
    nom_denomination: '',
    type_ec: 'EC',
    email: '',
    telephone: '',
    province_attache: '',
    categorie_personne: '' as CategoriePersonne | '',
    statut_professionnel: '' as StatutProfessionnel | '',
    cabinet_attache: '',
  })

  const loadExperts = async () => {
    try {
      setIsFetching(true)
      if (initialLoad) {
        setLoading(true)
      }
      const includeInactive = filterActive === ''
      const activeParam = filterActive === 'true' ? true : filterActive === 'false' ? false : undefined
      const res: any = await apiRequest('GET', '/experts-comptables', {
        params: {
          q: search || undefined,
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
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setExperts(items as any)
      setTotalCount(typeof res?.total === 'number' ? res.total : items.length)
      setSummary(res?.summary ? { ...emptySummary, ...res.summary } : emptySummary)
    } catch (error) {
      console.error('Error loading experts:', error)
    } finally {
      setIsFetching(false)
      setLoading(false)
      setInitialLoad(false)
    }
  }

  useEffect(() => {
    loadExperts()
  }, [search, filterStatutProf, filterActive, filterProvince, filterCategory, sortField, sortDirection, pageSize, page])

  useEffect(() => {
    setPage(1)
  }, [search, filterStatutProf, filterActive, filterProvince, filterCategory, sortField, sortDirection, pageSize])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!formData.numero_ordre || !formData.nom_denomination) {
      notifyWarning('Champs requis manquants', "Veuillez saisir le numéro d'ordre et le nom/dénomination.")
      return
    }

    try {
      const typeEc = formData.categorie_personne === 'Personne Morale' ? 'SEC' : formData.type_ec

      await apiRequest('POST', '/experts-comptables', {
        numero_ordre: formData.numero_ordre,
        nom_denomination: formData.nom_denomination,
        type_ec: typeEc,
        email: formData.email || null,
        telephone: formData.telephone || null,
        province_attache: formData.province_attache || null,
        categorie_personne: formData.categorie_personne || null,
        statut_professionnel: formData.statut_professionnel || null,
        cabinet_attache: formData.cabinet_attache || null,
        active: true,
      }) 

      notifySuccess('Expert ajouté', "L'expert-comptable a été ajouté avec succès.")
      setShowForm(false)
      setFormData({
        numero_ordre: '',
        nom_denomination: '',
        type_ec: 'EC',
        email: '',
        telephone: '',
        province_attache: '',
        categorie_personne: '',
        statut_professionnel: '',
        cabinet_attache: '',
      })
      loadExperts()
    } catch (error: any) {
      console.error('Error creating expert:', error)
      if (error.code === '23505') {
        notifyWarning("Numéro d'ordre existant", "Ce numéro d'ordre existe déjà dans le système.")
      } else {
        notifyError("Erreur d'ajout", error?.message || "Une erreur est survenue lors de l'ajout de l'expert-comptable.")
      }
    }
  }

  const toggleActiveStatus = (expert: ExpertComptable) => {
    setSelectedExpert(expert)
    setShowDeactivateModal(true)
  }

  const openEditForm = (expert: ExpertComptable) => {
    setEditingExpert(expert)
    setEditFormData({
      nom_denomination: expert.nom_denomination || '',
      type_ec: expert.type_ec || 'EC',
      email: expert.email || '',
      telephone: expert.telephone || '',
      province_attache: expert.province_attache || '',
      categorie_personne: (expert.categorie_personne || '') as CategoriePersonne | '',
      statut_professionnel: (expert.statut_professionnel || '') as StatutProfessionnel | '',
      cabinet_attache: expert.cabinet_attache || '',
    })
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

    if (!editFormData.nom_denomination) {
      notifyWarning('Champs requis manquants', 'Veuillez remplir le nom/dénomination.')
      return
    }

    setIsSavingEdit(true)
    try {
      const typeEc = editFormData.categorie_personne === 'Personne Morale' ? 'SEC' : editFormData.type_ec

      await apiRequest('PUT', `/experts-comptables/${editingExpert.id}`, {
        nom_denomination: editFormData.nom_denomination,
        type_ec: typeEc,
        email: editFormData.email || null,
        telephone: editFormData.telephone || null,
        province_attache: editFormData.province_attache || null,
        categorie_personne: editFormData.categorie_personne || null,
        statut_professionnel: editFormData.statut_professionnel || null,
        cabinet_attache: editFormData.cabinet_attache || null,
      })

      setSuccessNotificationData({
        title: 'Expert mis à jour',
        message: `${editingExpert.nom_denomination} a été mis à jour avec succès.`,
      })
      setShowSuccessNotification(true)
      closeEditForm()
      loadExperts()
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
      await apiRequest('PATCH', `/experts-comptables/${selectedExpert.id}`, { active: newActiveStatus })

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
    return Array.from(new Set(experts.map((expert) => expert.province_attache).filter(Boolean) as string[])).sort((a, b) =>
      a.localeCompare(b)
    )
  }, [experts])

  const filteredExperts = experts

  const summaryItems = useMemo(() => {
    return [
      { label: 'Total experts', value: summary.total || totalCount, active: !filterActive && !filterCategory, onClick: () => { setFilterActive(''); setFilterCategory('') } },
      { label: 'Actifs', value: summary.active, active: filterActive === 'true', onClick: () => setFilterActive('true') },
      { label: 'Inactifs', value: summary.inactive, active: filterActive === 'false', onClick: () => setFilterActive('false') },
      { label: 'Suspendus', value: summary.suspended, disabled: true },
      { label: 'SEC', value: summary.sec, active: filterCategory === 'SEC', onClick: () => setFilterCategory('SEC') },
      { label: 'En cabinet', value: summary.cabinet, active: filterCategory === 'En Cabinet', onClick: () => setFilterCategory('En Cabinet') },
      { label: 'Indépendants', value: summary.independant, active: filterCategory === 'Indépendant', onClick: () => setFilterCategory('Indépendant') },
      { label: 'Salariés', value: summary.salarie, active: filterCategory === 'Salarié', onClick: () => setFilterCategory('Salarié') },
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
          <button type="button" onClick={() => setShowForm(true)} className={styles.primaryBtn} aria-label="Ajouter un expert">
            + Ajouter un expert
          </button>
          <button type="button" onClick={() => setShowImport(true)} className={styles.secondaryBtn}>
            Importer Excel
          </button>
          <button
            type="button"
            onClick={handleExportToExcel}
            className={styles.secondaryBtn}
            disabled={exportExcelEnCours}
          >
            {exportExcelEnCours ? 'Export en cours…' : 'Exporter Excel'}
          </button>
          <button type="button" onClick={() => { setCategoryChangeNumero(''); setShowCategoryChange(true) }} className={styles.secondaryBtn}>
            Changer de catégorie
          </button>
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
            {showMoreCols ? 'Afficher moins' : 'Afficher plus'}
          </button>
        </div>
      </header>

      <section className={styles.filtersCard} aria-label="Recherche et filtres">
        <div className={styles.searchBar}>
          <label htmlFor="experts-search">Recherche</label>
          <input
            id="experts-search"
            type="text"
            placeholder="Rechercher par numéro, nom, e-mail, cabinet ou province..."
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
            onClick={item.onClick}
            disabled={item.disabled}
          >
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </button>
        ))}
      </section>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Ajouter un expert-comptable</h2>
              <button onClick={() => setShowForm(false)} className={styles.closeBtn}>×</button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Numéro d'ordre *</label>
                <input
                  type="text"
                  value={formData.numero_ordre}
                  onChange={(e) => setFormData({ ...formData, numero_ordre: e.target.value })}
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Nom / Dénomination *</label>
                <input
                  type="text"
                  value={formData.nom_denomination}
                  onChange={(e) => setFormData({ ...formData, nom_denomination: e.target.value })}
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Province d'attache</label>
                <input
                  type="text"
                  value={formData.province_attache}
                  onChange={(e) => setFormData({ ...formData, province_attache: e.target.value })}
                  placeholder="Ex: Kinshasa, Haut-Katanga, Kasaï..."
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  />
                </div>

                <div className={styles.field}>
                  <label>Téléphone</label>
                  <input
                    type="tel"
                    value={formData.telephone}
                    onChange={(e) => setFormData({ ...formData, telephone: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Catégorie Personne</label>
                  <select
                    value={formData.categorie_personne}
                    onChange={(e) => setFormData({ ...formData, categorie_personne: e.target.value as CategoriePersonne | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="Personne Physique">Personne Physique</option>
                    <option value="Personne Morale">Personne Morale</option>
                  </select>
                </div>

                <div className={styles.field}>
                  <label>Statut Professionnel</label>
                  <select
                    value={formData.statut_professionnel}
                    onChange={(e) => setFormData({ ...formData, statut_professionnel: e.target.value as StatutProfessionnel | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="En Cabinet">En Cabinet</option>
                    <option value="Indépendant">Indépendant</option>
                    <option value="Salarié">Salarié</option>
                    <option value="Cabinet">Cabinet</option>
                  </select>
                </div>
              </div>

              {formData.statut_professionnel === 'En Cabinet' && (
                <div className={styles.field}>
                  <label>Cabinet d'Attache</label>
                  <input
                    type="text"
                    value={formData.cabinet_attache}
                    onChange={(e) => setFormData({ ...formData, cabinet_attache: e.target.value })}
                    placeholder="Nom du cabinet d'attache"
                  />
                </div>
              )}

              <div className={styles.formActions}>
                <button type="button" onClick={() => setShowForm(false)} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Ajouter
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
              <h2>Modifier l’expert-comptable</h2>
              <button onClick={closeEditForm} className={styles.closeBtn} disabled={isSavingEdit}>×</button>
            </div>

            <form onSubmit={handleEditSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Numéro d'ordre</label>
                <input type="text" value={editingExpert.numero_ordre} disabled />
              </div>

              <div className={styles.field}>
                <label>Nom / Dénomination *</label>
                <input
                  type="text"
                  value={editFormData.nom_denomination}
                  onChange={(e) => setEditFormData({ ...editFormData, nom_denomination: e.target.value })}
                  required
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Email</label>
                  <input
                    type="email"
                    value={editFormData.email}
                    onChange={(e) => setEditFormData({ ...editFormData, email: e.target.value })}
                  />
                </div>

                <div className={styles.field}>
                  <label>Téléphone</label>
                  <input
                    type="tel"
                    value={editFormData.telephone}
                    onChange={(e) => setEditFormData({ ...editFormData, telephone: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.field}>
                <label>Province d'attache</label>
                <input
                  type="text"
                  value={editFormData.province_attache}
                  onChange={(e) => setEditFormData({ ...editFormData, province_attache: e.target.value })}
                  placeholder="Ex: Kinshasa, Haut-Katanga, Kasaï..."
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Catégorie Personne</label>
                  <select
                    value={editFormData.categorie_personne}
                    onChange={(e) => setEditFormData({ ...editFormData, categorie_personne: e.target.value as CategoriePersonne | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="Personne Physique">Personne Physique</option>
                    <option value="Personne Morale">Personne Morale</option>
                  </select>
                </div>

                <div className={styles.field}>
                  <label>Statut Professionnel</label>
                  <select
                    value={editFormData.statut_professionnel}
                    onChange={(e) => setEditFormData({ ...editFormData, statut_professionnel: e.target.value as StatutProfessionnel | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="En Cabinet">En Cabinet</option>
                    <option value="Indépendant">Indépendant</option>
                    <option value="Salarié">Salarié</option>
                    <option value="Cabinet">Cabinet</option>
                  </select>
                </div>
              </div>

              {editFormData.statut_professionnel === 'En Cabinet' && (
                <div className={styles.field}>
                  <label>Cabinet d'Attache</label>
                  <input
                    type="text"
                    value={editFormData.cabinet_attache}
                    onChange={(e) => setEditFormData({ ...editFormData, cabinet_attache: e.target.value })}
                    placeholder="Nom du cabinet d'attache"
                  />
                </div>
              )}

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
                  {editingExpert.active === false ? '✓ Réactiver' : '✕ Désactiver'}
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
              <h2>Confirmer l’archivage</h2>
              <button
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
                  '📦 Archiver'
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
          {isFetching && <span className={styles.fetchHint}>Mise à jour…</span>}
        </div>

        <div className={styles.tableContainer}>
          <table className={styles.table}>
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
                <td className={styles.emailCol}>{expert.email || '-'}</td>
                <td className={styles.phoneCol}>{expert.telephone || '-'}</td>
                <td className={styles.statusCol}>
                  <span className={expert.active === false ? styles.badgeArchived : styles.badgeActive}>
                    {expert.active === false ? 'Inactif' : 'Actif'}
                  </span>
                </td>
                <td className={styles.actionsCol}>
                  <div className={styles.actionsCell}>
                    <button type="button" onClick={() => setDetailExpert(expert)} className={styles.viewBtn}>
                      Voir
                    </button>
                    <button type="button" onClick={() => openEditForm(expert)} className={styles.editInlineBtn}>
                      Modifier
                    </button>
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
            <h3>{hasActiveFilters ? 'Aucun résultat pour ces filtres' : 'Aucun expert trouvé'}</h3>
            <p>Modifiez la recherche ou réinitialisez les filtres pour élargir la liste.</p>
            {hasActiveFilters && (
              <button type="button" onClick={resetFilters} className={styles.secondaryBtn}>
                Réinitialiser les filtres
              </button>
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
        <aside className={styles.detailPanel} aria-label="Détail expert-comptable">
          <div className={styles.detailHeader}>
            <div className={styles.detailIdentity}>
              <span className={styles.detailAvatar}>{getInitials(detailExpert.nom_denomination)}</span>
              <div>
                <h2>{detailExpert.nom_denomination}</h2>
                <p>{detailExpert.numero_ordre}</p>
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
                <div><dt>Province</dt><dd>{detailExpert.province_attache || '-'}</dd></div>
                <div><dt>Type</dt><dd>{detailExpert.type_ec || '-'}</dd></div>
                <div><dt>Statut</dt><dd>{detailExpert.active === false ? 'Inactif' : 'Actif'}</dd></div>
              </dl>
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

            <section className={styles.detailSection}>
              <h3>Historique</h3>
              <p className={styles.detailMuted}>
                Les changements de catégorie restent accessibles via l'action dédiée. Le panneau conserve les filtres et la position courante.
              </p>
            </section>
          </div>

          <div className={styles.detailActions}>
            <button type="button" className={styles.secondaryBtn} onClick={() => openEditForm(detailExpert)}>
              Modifier
            </button>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => {
                setCategoryChangeNumero(detailExpert.numero_ordre)
                setShowCategoryChange(true)
              }}
            >
              Changer de catégorie
            </button>
            <button
              type="button"
              className={detailExpert.active === false ? styles.reactivateActionBtn : styles.deactivateActionBtn}
              onClick={() => toggleActiveStatus(detailExpert)}
            >
              {detailExpert.active === false ? 'Réactiver' : 'Désactiver'}
            </button>
          </div>
        </aside>
      )}

    </div>
  )
}
