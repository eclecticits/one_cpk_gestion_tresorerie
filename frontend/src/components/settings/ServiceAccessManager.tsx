import { type CSSProperties, type MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Columns3, PanelRight, RotateCcw, Save, Search, X } from 'lucide-react'
import { getBudgetPostesTree } from '../../api/budget'
import { getServiceRubriques, getServiceRubriquesUsage, updateServiceRubriques } from '../../api/services'
import type { BudgetPosteTree } from '../../types/budget'
import styles from './ServiceAccessManager.module.css'

type Props = {
  serviceId: number | null
  serviceLabel?: string
  serviceCode?: string
  serviceActive?: boolean
  onDirtyChange?: (dirty: boolean) => void
  onExit?: () => void
}

type BudgetTypeFilter = 'all' | 'DEPENSE' | 'RECETTE'
type ColumnKey = 'selection' | 'code' | 'libelle' | 'type' | 'budget' | 'etat'

type FlatRow = {
  node: BudgetPosteTree
  depth: number
  hasChildren: boolean
  isParent: boolean
}

const sortIds = (ids: number[]) => [...ids].sort((a, b) => a - b)

const sameIds = (a: number[], b: number[]) => {
  if (a.length !== b.length) return false
  const sortedA = sortIds(a)
  const sortedB = sortIds(b)
  return sortedA.every((id, index) => id === sortedB[index])
}

const formatAmount = (value: string | number | null | undefined) => {
  const amount = Number(value ?? 0)
  if (!Number.isFinite(amount)) return '—'
  return new Intl.NumberFormat('fr-FR', {
    maximumFractionDigits: 0,
  }).format(amount)
}

// v2 : les largeurs par défaut ont été resserrées. On change de clé pour que les
// sessions déjà ouvertes ne conservent pas les anciennes valeurs (1112px au total,
// soit un défilement horizontal systématique en dessous de 1150px utiles).
const COLUMN_STORAGE_KEY = 'onec_budget_structure_column_widths_v2'
const STRETCH_STORAGE_KEY = 'onec_budget_structure_stretch'

// Largeurs calées sur le contenu réel : un code hiérarchique (« 6.1.2.3 »), un badge
// de type, un montant formaté, un badge d'état. La colonne libellé n'a pas de largeur
// fixe utile : elle absorbe l'espace restant (voir stretchLibelle).
const DEFAULT_COLUMN_WIDTHS: Record<ColumnKey, number> = {
  selection: 76,
  code: 100,
  libelle: 380,
  type: 82,
  budget: 102,
  etat: 78,
}

const MIN_COLUMN_WIDTHS: Record<ColumnKey, number> = {
  selection: 68,
  code: 88,
  libelle: 240,
  type: 76,
  budget: 92,
  etat: 72,
}

const FIXED_COLUMNS: ColumnKey[] = ['selection', 'code', 'type', 'budget', 'etat']

const COLUMN_LABELS: Record<ColumnKey, string> = {
  // « Cocher » plutôt que « Sélection » : l'en-tête doit tenir dans une colonne de
  // 76px, largeur dictée par la case à cocher et non par son intitulé.
  selection: 'Cocher',
  code: 'Code',
  libelle: 'Libellé',
  type: 'Type',
  budget: 'Budget',
  etat: 'État',
}

const loadColumnWidths = () => {
  try {
    const raw = window.sessionStorage.getItem(COLUMN_STORAGE_KEY)
    if (!raw) return DEFAULT_COLUMN_WIDTHS
    const parsed = JSON.parse(raw) as Partial<Record<ColumnKey, number>>
    return {
      ...DEFAULT_COLUMN_WIDTHS,
      ...Object.fromEntries(
        Object.entries(parsed).filter(([key, width]) =>
          // Les colonnes retirées depuis (ex. « Autorisé ») doivent être ignorées :
          // sinon leur largeur resterait comptée dans la largeur totale du tableau.
          key in DEFAULT_COLUMN_WIDTHS && typeof width === 'number' && Number.isFinite(width)
        )
      ),
    } as Record<ColumnKey, number>
  } catch {
    return DEFAULT_COLUMN_WIDTHS
  }
}

const loadStretchPreference = () => {
  try {
    return window.sessionStorage.getItem(STRETCH_STORAGE_KEY) !== '0'
  } catch {
    return true
  }
}

export default function ServiceAccessManager({
  serviceId,
  serviceLabel,
  serviceCode,
  serviceActive,
  onDirtyChange,
  onExit,
}: Props) {
  const [allRubriques, setAllRubriques] = useState<BudgetPosteTree[]>([])
  const [assignedIds, setAssignedIds] = useState<number[]>([])
  const [initialAssignedIds, setInitialAssignedIds] = useState<number[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [typeFilter, setTypeFilter] = useState<BudgetTypeFilter>('all')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  // Postes déjà utilisés dans ce service (badge d'avertissement avant désactivation).
  const [usageUsed, setUsageUsed] = useState<Set<number>>(new Set())
  const [usageEnCours, setUsageEnCours] = useState<Set<number>>(new Set())
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  const [summaryVisible, setSummaryVisible] = useState(() => {
    if (typeof window === 'undefined') return true
    return window.localStorage.getItem('budget.summaryHidden') !== '1'
  })

  const toggleSummary = useCallback(() => {
    setSummaryVisible((visible) => {
      const next = !visible
      try {
        window.localStorage.setItem('budget.summaryHidden', next ? '0' : '1')
      } catch {
        /* stockage indisponible : le repli reste valable pour la session */
      }
      return next
    })
  }, [])
  const [columnWidths, setColumnWidths] = useState<Record<ColumnKey, number>>(loadColumnWidths)
  // Tant que l'utilisateur n'a pas redimensionné le libellé lui-même, cette colonne
  // occupe l'espace restant : le tableau remplit le panneau sans bande blanche à
  // droite, et se réduit au lieu de déborder quand le panneau rétrécit.
  const [stretchLibelle, setStretchLibelle] = useState(loadStretchPreference)
  const [availableWidth, setAvailableWidth] = useState(0)
  const listRef = useRef<HTMLDivElement | null>(null)

  const hasUnsavedChanges = useMemo(
    () => !sameIds(assignedIds, initialAssignedIds),
    [assignedIds, initialAssignedIds]
  )

  useEffect(() => {
    onDirtyChange?.(hasUnsavedChanges)
  }, [hasUnsavedChanges, onDirtyChange])

  useEffect(() => {
    try {
      window.sessionStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(columnWidths))
    } catch {
      // Session persistence is best-effort only.
    }
  }, [columnWidths])

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STRETCH_STORAGE_KEY, stretchLibelle ? '1' : '0')
    } catch {
      // Session persistence is best-effort only.
    }
  }, [stretchLibelle])

  // Largeur réellement offerte au tableau : elle change quand on replie le résumé,
  // quand on redimensionne la fenêtre ou quand la sidebar applicative se replie.
  useEffect(() => {
    const node = listRef.current
    if (!node) return
    const measure = () => setAvailableWidth(node.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasUnsavedChanges])

  const loadData = useCallback(async () => {
    if (!serviceId) {
      setAllRubriques([])
      setAssignedIds([])
      setInitialAssignedIds([])
      setError(null)
      setSaveMessage(null)
      return
    }
    setLoading(true)
    setError(null)
    setSaveMessage(null)
    try {
      const [allRes, assignedRes, usageRes] = await Promise.all([
        getBudgetPostesTree({ active: true }),
        getServiceRubriques(serviceId),
        getServiceRubriquesUsage(serviceId).catch(() => ({ used: [], en_cours: [] })),
      ])
      const rubriques = Array.isArray(allRes?.postes) ? allRes.postes : []
      const selectedIds = assignedRes.map((rubrique) => rubrique.id)
      setAllRubriques(rubriques)
      setAssignedIds(selectedIds)
      setInitialAssignedIds(selectedIds)
      setUsageUsed(new Set(usageRes?.used || []))
      setUsageEnCours(new Set(usageRes?.en_cours || []))
      setExpandedIds(new Set())
    } catch (err: any) {
      setError(err?.message || 'Impossible de charger les postes budgétaires.')
    } finally {
      setLoading(false)
    }
  }, [serviceId])

  useEffect(() => {
    loadData()
  }, [loadData])

  const descendantMap = useMemo(() => {
    const map = new Map<number, number[]>()
    const walk = (node: BudgetPosteTree): number[] => {
      const collected: number[] = []
      ;(node.children || []).forEach((child) => {
        collected.push(child.id)
        collected.push(...walk(child))
      })
      map.set(node.id, collected)
      return collected
    }
    allRubriques.forEach((node) => {
      walk(node)
    })
    return map
  }, [allRubriques])

  const allFlatRows = useMemo(() => {
    const rows: FlatRow[] = []
    const walk = (nodes: BudgetPosteTree[], depth: number) => {
      nodes.forEach((node) => {
        const children = node.children || []
        rows.push({
          node,
          depth,
          hasChildren: children.length > 0,
          isParent: children.length > 0,
        })
        walk(children, depth + 1)
      })
    }
    walk(allRubriques, 0)
    return rows
  }, [allRubriques])

  const filteredTree = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    const matches = (node: BudgetPosteTree) => {
      const type = String(node.type || '').toUpperCase()
      const matchesType = typeFilter === 'all' || type === typeFilter
      const matchesSearch = !term
        || String(node.code || '').toLowerCase().includes(term)
        || String(node.libelle || '').toLowerCase().includes(term)
        || String(node.type || '').toLowerCase().includes(term)
      return matchesType && matchesSearch
    }
    const filterNodes = (nodes: BudgetPosteTree[]): BudgetPosteTree[] =>
      nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean) as BudgetPosteTree[]
    return filterNodes(allRubriques)
  }, [allRubriques, searchTerm, typeFilter])

  const visibleRows = useMemo(() => {
    const rows: FlatRow[] = []
    const forceExpand = searchTerm.trim().length > 0 || typeFilter !== 'all'
    const walk = (nodes: BudgetPosteTree[], depth: number) => {
      nodes.forEach((node) => {
        const children = node.children || []
        const isExpanded = forceExpand || expandedIds.has(node.id)
        rows.push({
          node,
          depth,
          hasChildren: children.length > 0,
          isParent: children.length > 0,
        })
        if (children.length > 0 && isExpanded) {
          walk(children, depth + 1)
        }
      })
    }
    walk(filteredTree, 0)
    return rows
  }, [expandedIds, filteredTree, searchTerm, typeFilter])

  const visibleIds = useMemo(() => visibleRows.map((row) => row.node.id), [visibleRows])
  const selectedVisibleCount = useMemo(
    () => visibleIds.filter((id) => assignedIds.includes(id)).length,
    [assignedIds, visibleIds]
  )

  const expenseAssignedCount = useMemo(
    () => allFlatRows.filter((row) => row.node.type?.toUpperCase() === 'DEPENSE' && assignedIds.includes(row.node.id)).length,
    [allFlatRows, assignedIds]
  )
  const revenueAssignedCount = useMemo(
    () => allFlatRows.filter((row) => row.node.type?.toUpperCase() === 'RECETTE' && assignedIds.includes(row.node.id)).length,
    [allFlatRows, assignedIds]
  )
  const authorizedBudget = useMemo(
    () => allFlatRows.reduce((sum, row) => assignedIds.includes(row.node.id) ? sum + Number(row.node.montant_prevu || 0) : sum, 0),
    [allFlatRows, assignedIds]
  )
  const fixedColumnsWidth = useMemo(
    () => FIXED_COLUMNS.reduce((sum, column) => sum + columnWidths[column], 0),
    [columnWidths]
  )

  // Largeurs effectivement rendues : identiques à l'état sauf pour le libellé en
  // mode élastique, qui prend le reste (−1px pour ne pas déclencher de barre
  // horizontale, ce qui recalculerait la largeur en boucle).
  const effectiveWidths = useMemo(() => {
    if (!stretchLibelle || availableWidth <= 0) return columnWidths
    return {
      ...columnWidths,
      libelle: Math.max(MIN_COLUMN_WIDTHS.libelle, availableWidth - fixedColumnsWidth - 1),
    }
  }, [columnWidths, stretchLibelle, availableWidth, fixedColumnsWidth])

  const tableWidth = useMemo(
    () => Object.values(effectiveWidths).reduce((sum, width) => sum + width, 0),
    [effectiveWidths]
  )

  const startColumnResize = useCallback((column: ColumnKey, event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    // On repart de la largeur affichée, sinon la colonne libellé saute au premier
    // pixel de glissement quand elle était élastique.
    const startWidth = effectiveWidths[column]
    const minWidth = MIN_COLUMN_WIDTHS[column]
    // Redimensionner le libellé à la main, c'est reprendre la main sur l'élasticité.
    // On fige d'abord la largeur affichée, sinon la colonne retomberait un instant
    // sur sa valeur stockée entre le clic et le premier déplacement.
    if (column === 'libelle') {
      setColumnWidths((prev) => ({ ...prev, libelle: startWidth }))
      setStretchLibelle(false)
    }

    const handleMove = (moveEvent: MouseEvent) => {
      const nextWidth = Math.max(minWidth, startWidth + moveEvent.clientX - startX)
      setColumnWidths((prev) => ({ ...prev, [column]: nextWidth }))
    }

    const handleUp = () => {
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleUp)
  }, [effectiveWidths])

  const autoFitColumns = () => {
    const longestLabel = visibleRows.reduce((max, row) => Math.max(max, String(row.node.libelle || '').length), 0)
    const longestCode = visibleRows.reduce((max, row) => Math.max(max, String(row.node.code || '').length), 0)
    const next: Record<ColumnKey, number> = {
      selection: DEFAULT_COLUMN_WIDTHS.selection,
      code: Math.min(190, Math.max(MIN_COLUMN_WIDTHS.code, longestCode * 9 + 34)),
      libelle: Math.min(760, Math.max(MIN_COLUMN_WIDTHS.libelle, longestLabel * 7 + 130)),
      type: DEFAULT_COLUMN_WIDTHS.type,
      budget: DEFAULT_COLUMN_WIDTHS.budget,
      etat: DEFAULT_COLUMN_WIDTHS.etat,
    }
    // Si le contenu tient dans la place disponible, on garde le libellé élastique :
    // ajuster les colonnes ne doit pas laisser une bande blanche à droite.
    const remaining = availableWidth - FIXED_COLUMNS.reduce((sum, column) => sum + next[column], 0)
    setStretchLibelle(availableWidth > 0 && remaining >= next.libelle)
    setColumnWidths(next)
  }

  const HeaderCell = ({ column, className }: { column: ColumnKey; className?: string }) => (
    <th className={className}>
      <div className={styles.headerCell}>
        <span>{COLUMN_LABELS[column]}</span>
        <button
          type="button"
          className={styles.resizeHandle}
          onMouseDown={(event) => startColumnResize(column, event)}
          onDoubleClick={autoFitColumns}
          aria-label={`Redimensionner la colonne ${COLUMN_LABELS[column]}`}
        />
      </div>
    </th>
  )

  const toggleExpanded = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleRubrique = (id: number) => {
    const scrollTop = listRef.current?.scrollTop ?? 0
    setSaveMessage(null)
    setAssignedIds((prev) => {
      const next = new Set(prev)
      const descendants = descendantMap.get(id) || []
      if (next.has(id)) {
        next.delete(id)
        descendants.forEach((childId) => next.delete(childId))
      } else {
        next.add(id)
        descendants.forEach((childId) => next.add(childId))
      }
      return Array.from(next)
    })
    requestAnimationFrame(() => {
      if (listRef.current) {
        listRef.current.scrollTop = scrollTop
      }
    })
  }

  const selectVisible = () => {
    setSaveMessage(null)
    setAssignedIds((prev) => Array.from(new Set([...prev, ...visibleIds])))
  }

  const deselectVisible = () => {
    setSaveMessage(null)
    const visible = new Set(visibleIds)
    setAssignedIds((prev) => prev.filter((id) => !visible.has(id)))
  }

  const invertVisible = () => {
    setSaveMessage(null)
    const visible = new Set(visibleIds)
    setAssignedIds((prev) => {
      const next = new Set(prev)
      visible.forEach((id) => {
        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }
      })
      return Array.from(next)
    })
  }

  const clearFilters = () => {
    setSearchTerm('')
    setTypeFilter('all')
  }

  const cancelChanges = () => {
    setAssignedIds(initialAssignedIds)
    setSaveMessage(null)
    setError(null)
  }

  const [conflict, setConflict] = useState<{ bloques: any[]; aConfirmer: any[] } | null>(null)

  const applyRubriques = async (force: boolean): Promise<boolean> => {
    if (!serviceId) return false
    setSaving(true)
    setError(null)
    setSaveMessage(null)
    try {
      await updateServiceRubriques(serviceId, assignedIds, force)
      setInitialAssignedIds(assignedIds)
      setSaveMessage('Les droits budgétaires ont été enregistrés avec succès.')
      setConflict(null)
      return true
    } catch (err: any) {
      const detail = err?.payload?.detail
      if (err?.status === 409 && detail && detail.code === 'rubriques_utilisees') {
        setConflict({ bloques: detail.bloques || [], aConfirmer: detail.a_confirmer || [] })
        return false
      }
      setError(err?.message || "Erreur lors de l'enregistrement. Les modifications locales sont conservées.")
      setConflict(null)
      return false
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => applyRubriques(false)

  const saveAndExit = async () => {
    const saved = await handleSave()
    if (saved) onExit?.()
  }

  const renderRows = () => {
    if (loading) {
      return Array.from({ length: 8 }).map((_, index) => (
        <tr key={`skeleton-${index}`} className={styles.skeletonRow}>
          <td><span /></td>
          <td><span /></td>
          <td><span /></td>
          <td><span /></td>
          <td><span /></td>
          <td><span /></td>
          <td><span /></td>
        </tr>
      ))
    }

    if (!serviceId) {
      return (
        <tr>
          <td colSpan={6} className={styles.state}>Sélectionnez une unité pour gérer ses postes budgétaires.</td>
        </tr>
      )
    }

    if (visibleRows.length === 0) {
      return (
        <tr>
          <td colSpan={6} className={styles.state}>Aucun poste budgétaire ne correspond à votre recherche.</td>
        </tr>
      )
    }

    return visibleRows.map(({ node, depth, hasChildren, isParent }) => {
      const checked = assignedIds.includes(node.id)
      const isActive = node.active !== false
      const rowStyle = {
        '--row-depth': depth,
      } as CSSProperties
      return (
        <tr
          key={node.id}
          className={`${checked ? styles.rowSelected : ''} ${isParent ? styles.parentRow : ''}`}
          style={rowStyle}
        >
          <td className={styles.checkCol}>
            <label className={styles.switch} aria-label={`Autoriser le poste ${node.code} ${node.libelle}`}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleRubrique(node.id)}
                disabled={saving}
              />
              <span />
            </label>
          </td>
          <td className={styles.codeCol} title={node.code}>{node.code}</td>
          <td className={styles.libelleCell}>
            <div className={styles.treeCell} style={{ paddingLeft: `${8 + depth * 24}px` }}>
              <span className={styles.depthGuide} aria-hidden="true" />
              {hasChildren ? (
                <button
                  type="button"
                  className={styles.treeToggle}
                  onClick={() => toggleExpanded(node.id)}
                  aria-label={expandedIds.has(node.id) ? 'Réduire ce poste parent' : 'Développer ce poste parent'}
                >
                  {expandedIds.has(node.id) || searchTerm.trim() || typeFilter !== 'all'
                    ? <ChevronDown size={14} aria-hidden="true" />
                    : <ChevronRight size={14} aria-hidden="true" />}
                </button>
              ) : (
                <span className={styles.treeSpacer} />
              )}
              <span className={styles.treeLabel} title={node.libelle}>{node.libelle}</span>
              {usageEnCours.has(node.id) ? (
                <span
                  title="Utilisé par des réquisitions en cours — désactivation bloquée"
                  style={{ marginLeft: 8, fontSize: 10.5, fontWeight: 700, color: '#b91c1c', background: '#fee2e2', border: '1px solid #fecaca', borderRadius: 999, padding: '1px 7px', whiteSpace: 'nowrap' }}
                >
                  en cours
                </span>
              ) : usageUsed.has(node.id) ? (
                <span
                  title="Déjà utilisé dans ce service — la désactivation demandera confirmation"
                  style={{ marginLeft: 8, fontSize: 10.5, fontWeight: 700, color: '#b45309', background: '#fef3c7', border: '1px solid #fde68a', borderRadius: 999, padding: '1px 7px', whiteSpace: 'nowrap' }}
                >
                  déjà utilisé
                </span>
              ) : null}
            </div>
          </td>
          <td className={styles.typeCol}>
            <span className={`${styles.typeBadge} ${node.type?.toUpperCase() === 'RECETTE' ? styles.typeRecette : styles.typeDepense}`}>
              {node.type || '—'}
            </span>
          </td>
          <td className={styles.budgetCol}>{formatAmount(node.montant_prevu)}</td>
          <td className={styles.stateCol}>
            <span className={`${styles.statusBadge} ${isActive ? styles.statusActive : styles.statusInactive}`}>
              {isActive ? 'Actif' : 'Inactif'}
            </span>
          </td>
        </tr>
      )
    })
  }

  return (
    <section className={`${styles.workspace} ${summaryVisible ? '' : styles.workspaceWide}`}>
      <main className={styles.panel}>
        <div className={styles.panelHeader}>
          <div className={styles.panelIdentity}>
            <span className={styles.panelTitle}>Postes autorisés</span>
            <span
              className={styles.panelSubtitle}
              title={serviceLabel || undefined}
            >
              {serviceLabel ? `· ${serviceLabel}` : '· Sélectionnez une unité pour commencer.'}
            </span>
          </div>
          <div className={styles.panelHeaderActions}>
            {hasUnsavedChanges && (
              <span className={styles.dirtyBadge} title="Modifications non enregistrées">
                <AlertCircle size={14} aria-hidden="true" />
                Non enregistré
              </span>
            )}
            <button
              type="button"
              className={styles.summaryToggleButton}
              onClick={toggleSummary}
              aria-expanded={summaryVisible}
              title={summaryVisible ? 'Masquer le résumé pour élargir le tableau' : 'Afficher le résumé'}
            >
              <PanelRight size={15} aria-hidden="true" />
              {summaryVisible ? 'Masquer le résumé' : 'Résumé'}
            </button>
          </div>
        </div>

        <div className={styles.filtersRow}>
          <label className={styles.searchBox}>
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Rechercher par code, libellé ou type"
              disabled={!serviceId}
              aria-label="Rechercher un poste budgétaire par code, libellé ou type"
            />
            {searchTerm && (
              <button
                type="button"
                className={styles.inlineClear}
                onClick={() => setSearchTerm('')}
                aria-label="Effacer la recherche"
              >
                <X size={14} aria-hidden="true" />
              </button>
            )}
          </label>
          <div className={styles.typeFilters} aria-label="Filtrer les postes par type">
            <button type="button" className={typeFilter === 'all' ? styles.filterActive : ''} onClick={() => setTypeFilter('all')}>Tous</button>
            <button type="button" className={typeFilter === 'DEPENSE' ? styles.filterActive : ''} onClick={() => setTypeFilter('DEPENSE')}>Dépenses</button>
            <button type="button" className={typeFilter === 'RECETTE' ? styles.filterActive : ''} onClick={() => setTypeFilter('RECETTE')}>Recettes</button>
          </div>
          <button type="button" className={styles.clearButton} onClick={clearFilters} disabled={!searchTerm && typeFilter === 'all'}>
            <X size={14} aria-hidden="true" />
            Effacer
          </button>

          {/* Compteurs et actions groupées fusionnés dans la ligne de filtres :
              ils passent à la ligne d'un bloc quand la largeur manque, ce qui
              évite une troisième bande fixe au-dessus du tableau. */}
          <div className={styles.toolbarActions}>
            <div className={styles.resultsCount}>
              {visibleRows.length} résultat{visibleRows.length > 1 ? 's' : ''}
              <span aria-hidden="true"> · </span>
              {selectedVisibleCount} sélectionné{selectedVisibleCount > 1 ? 's' : ''}
            </div>
            <div className={styles.bulkActions}>
              <button
                type="button"
                className={styles.iconButton}
                onClick={autoFitColumns}
                disabled={!serviceId || visibleRows.length === 0 || saving}
                aria-label="Ajuster la largeur des colonnes"
                title="Ajuster la largeur des colonnes"
              >
                <Columns3 size={14} aria-hidden="true" />
              </button>
              <button type="button" onClick={selectVisible} disabled={!serviceId || visibleRows.length === 0 || saving} title="Sélectionner tous les postes visibles">Tout cocher</button>
              <button type="button" onClick={deselectVisible} disabled={!serviceId || visibleRows.length === 0 || saving} title="Désélectionner tous les postes visibles">Tout décocher</button>
              <button type="button" onClick={invertVisible} disabled={!serviceId || visibleRows.length === 0 || saving} title="Inverser la sélection des postes visibles">Inverser</button>
            </div>
          </div>
        </div>

        {error && (
          <div className={styles.error}>
            <AlertCircle size={16} aria-hidden="true" />
            <span>{error}</span>
            <button type="button" onClick={loadData} disabled={loading || saving}>Réessayer</button>
          </div>
        )}

        {saveMessage && (
          <div className={styles.success}>
            <CheckCircle2 size={16} aria-hidden="true" />
            <span>{saveMessage}</span>
            <button type="button" onClick={onExit}>Retour à la liste</button>
            <button type="button" onClick={() => setSaveMessage(null)}>Continuer les modifications</button>
          </div>
        )}

        <div className={styles.listWrap} ref={listRef}>
          <table className={styles.table} style={{ width: tableWidth, minWidth: tableWidth }}>
            <colgroup>
              <col style={{ width: effectiveWidths.selection }} />
              <col style={{ width: effectiveWidths.code }} />
              <col style={{ width: effectiveWidths.libelle }} />
              <col style={{ width: effectiveWidths.type }} />
              <col style={{ width: effectiveWidths.budget }} />
              <col style={{ width: effectiveWidths.etat }} />
            </colgroup>
            <thead>
              <tr>
                <HeaderCell column="selection" className={styles.checkCol} />
                <HeaderCell column="code" className={styles.codeCol} />
                <HeaderCell column="libelle" />
                <HeaderCell column="type" className={styles.typeCol} />
                <HeaderCell column="budget" className={styles.budgetCol} />
                <HeaderCell column="etat" className={styles.stateCol} />
              </tr>
            </thead>
            <tbody>{renderRows()}</tbody>
          </table>
        </div>

        <footer className={styles.actionBar}>
          <button type="button" className={styles.secondaryButton} onClick={cancelChanges} disabled={!hasUnsavedChanges || saving}>
            <RotateCcw size={15} aria-hidden="true" />
            Annuler les modifications
          </button>
          <div className={styles.saveActions}>
            <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={!serviceId || !hasUnsavedChanges || saving}>
              <Save size={15} aria-hidden="true" />
              {saving ? 'Enregistrement...' : 'Enregistrer'}
            </button>
            <button type="button" className={styles.secondaryStrongButton} onClick={saveAndExit} disabled={!serviceId || saving || (!hasUnsavedChanges && !saveMessage)}>
              Enregistrer et quitter
            </button>
          </div>
        </footer>
      </main>

      {summaryVisible && (
      <aside className={styles.summaryPanel} aria-label="Résumé de la structure budgétaire">
        <div className={styles.summaryHeader}>
          <span>Résumé</span>
          {typeof serviceActive === 'boolean' && (
            <span className={`${styles.statusBadge} ${serviceActive ? styles.statusActive : styles.statusInactive}`}>
              {serviceActive ? 'Actif' : 'Inactif'}
            </span>
          )}
        </div>
        <dl className={styles.summaryList}>
          <div>
            <dt>Unité sélectionnée</dt>
            <dd title={serviceLabel || undefined}>{serviceLabel || 'Aucune'}</dd>
          </div>
          {serviceCode && (
            <div>
              <dt>Code</dt>
              <dd>{serviceCode}</dd>
            </div>
          )}
          <div>
            <dt>Total postes</dt>
            <dd>{allFlatRows.length}</dd>
          </div>
          <div>
            <dt>Postes autorisés</dt>
            <dd>{assignedIds.length}</dd>
          </div>
          <div>
            <dt>État des modifications</dt>
            <dd>{hasUnsavedChanges ? 'Non enregistrées' : 'À jour'}</dd>
          </div>
          {summaryExpanded && (
            <>
              <div>
                <dt>Dépenses autorisées</dt>
                <dd>{expenseAssignedCount}</dd>
              </div>
              <div>
                <dt>Recettes autorisées</dt>
                <dd>{revenueAssignedCount}</dd>
              </div>
              <div>
                <dt>Budget autorisé</dt>
                <dd>{formatAmount(authorizedBudget)}</dd>
              </div>
            </>
          )}
        </dl>
        <button
          type="button"
          className={styles.summaryToggle}
          onClick={() => setSummaryExpanded((expanded) => !expanded)}
        >
          {summaryExpanded ? 'Masquer les détails' : 'Afficher les détails'}
        </button>
      </aside>
      )}

      {conflict && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setConflict(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#fff', borderRadius: 12, maxWidth: 520, width: '100%',
              boxShadow: '0 20px 50px rgba(0,0,0,0.25)', padding: 20, maxHeight: '85vh', overflow: 'auto',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <AlertCircle size={20} color="#d97706" aria-hidden="true" />
              <h3 style={{ margin: 0, fontSize: 16, color: '#1e293b' }}>Postes déjà utilisés dans ce service</h3>
            </div>

            {conflict.bloques.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#b91c1c', marginBottom: 6 }}>
                  Désactivation impossible — opérations en cours
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#334155' }}>
                  {conflict.bloques.map((p: any) => (
                    <li key={`b-${p.id}`}>{p.code ? `${p.code} — ` : ''}{p.libelle || `Poste ${p.id}`}</li>
                  ))}
                </ul>
                <p style={{ fontSize: 12.5, color: '#64748b', marginTop: 6 }}>
                  Ré-autorisez ces postes (ou terminez / annulez leurs réquisitions en cours) avant d'enregistrer.
                </p>
              </div>
            )}

            {conflict.aConfirmer.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#b45309', marginBottom: 6 }}>
                  Déjà utilisés (historique)
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#334155' }}>
                  {conflict.aConfirmer.map((p: any) => (
                    <li key={`c-${p.id}`}>{p.code ? `${p.code} — ` : ''}{p.libelle || `Poste ${p.id}`}</li>
                  ))}
                </ul>
                <p style={{ fontSize: 12.5, color: '#64748b', marginTop: 6 }}>
                  Les désactiver les retirera des choix futurs. L'historique et les états restent consultables.
                </p>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
              <button
                type="button"
                onClick={() => setConflict(null)}
                style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff', cursor: 'pointer', fontWeight: 600 }}
              >
                Fermer
              </button>
              {conflict.bloques.length === 0 && conflict.aConfirmer.length > 0 && (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => applyRubriques(true)}
                  style={{ padding: '8px 14px', borderRadius: 8, border: 'none', background: '#d97706', color: '#fff', cursor: 'pointer', fontWeight: 600, opacity: saving ? 0.6 : 1 }}
                >
                  {saving ? 'Confirmation...' : 'Confirmer la désactivation'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
