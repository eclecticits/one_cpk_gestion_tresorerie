import { type CSSProperties, type MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Columns3, RotateCcw, Save, Search, X } from 'lucide-react'
import { getBudgetPostesTree } from '../../api/budget'
import { getServiceRubriques, updateServiceRubriques } from '../../api/services'
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
type ColumnKey = 'selection' | 'code' | 'libelle' | 'type' | 'budget' | 'etat' | 'autorise'

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

const COLUMN_STORAGE_KEY = 'onec_budget_structure_column_widths'
const DEFAULT_COLUMN_WIDTHS: Record<ColumnKey, number> = {
  selection: 82,
  code: 132,
  libelle: 480,
  type: 108,
  budget: 126,
  etat: 92,
  autorise: 92,
}

const MIN_COLUMN_WIDTHS: Record<ColumnKey, number> = {
  selection: 72,
  code: 96,
  libelle: 280,
  type: 90,
  budget: 104,
  etat: 82,
  autorise: 82,
}

const COLUMN_LABELS: Record<ColumnKey, string> = {
  selection: 'Sélection',
  code: 'Code',
  libelle: 'Libellé',
  type: 'Type',
  budget: 'Budget',
  etat: 'État',
  autorise: 'Autorisé',
}

const loadColumnWidths = () => {
  try {
    const raw = window.sessionStorage.getItem(COLUMN_STORAGE_KEY)
    if (!raw) return DEFAULT_COLUMN_WIDTHS
    const parsed = JSON.parse(raw) as Partial<Record<ColumnKey, number>>
    return {
      ...DEFAULT_COLUMN_WIDTHS,
      ...Object.fromEntries(
        Object.entries(parsed).filter(([, width]) => typeof width === 'number' && Number.isFinite(width))
      ),
    } as Record<ColumnKey, number>
  } catch {
    return DEFAULT_COLUMN_WIDTHS
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
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  const [columnWidths, setColumnWidths] = useState<Record<ColumnKey, number>>(loadColumnWidths)
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
      const [allRes, assignedRes] = await Promise.all([
        getBudgetPostesTree({ active: true }),
        getServiceRubriques(serviceId),
      ])
      const rubriques = Array.isArray(allRes?.postes) ? allRes.postes : []
      const selectedIds = assignedRes.map((rubrique) => rubrique.id)
      setAllRubriques(rubriques)
      setAssignedIds(selectedIds)
      setInitialAssignedIds(selectedIds)
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
  const tableWidth = useMemo(
    () => Object.values(columnWidths).reduce((sum, width) => sum + width, 0),
    [columnWidths]
  )

  const startColumnResize = useCallback((column: ColumnKey, event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const startWidth = columnWidths[column]
    const minWidth = MIN_COLUMN_WIDTHS[column]

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
  }, [columnWidths])

  const autoFitColumns = () => {
    const longestLabel = visibleRows.reduce((max, row) => Math.max(max, String(row.node.libelle || '').length), 0)
    const longestCode = visibleRows.reduce((max, row) => Math.max(max, String(row.node.code || '').length), 0)
    setColumnWidths({
      selection: DEFAULT_COLUMN_WIDTHS.selection,
      code: Math.min(190, Math.max(MIN_COLUMN_WIDTHS.code, longestCode * 9 + 34)),
      libelle: Math.min(760, Math.max(MIN_COLUMN_WIDTHS.libelle, longestLabel * 7 + 130)),
      type: DEFAULT_COLUMN_WIDTHS.type,
      budget: DEFAULT_COLUMN_WIDTHS.budget,
      etat: DEFAULT_COLUMN_WIDTHS.etat,
      autorise: DEFAULT_COLUMN_WIDTHS.autorise,
    })
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

  const handleSave = async () => {
    if (!serviceId) return false
    setSaving(true)
    setError(null)
    setSaveMessage(null)
    try {
      await updateServiceRubriques(serviceId, assignedIds)
      setInitialAssignedIds(assignedIds)
      setSaveMessage('Les droits budgétaires ont été enregistrés avec succès.')
      return true
    } catch (err: any) {
      setError(err?.message || "Erreur lors de l'enregistrement. Les modifications locales sont conservées.")
      return false
    } finally {
      setSaving(false)
    }
  }

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
          <td colSpan={7} className={styles.state}>Sélectionnez une unité pour gérer ses postes budgétaires.</td>
        </tr>
      )
    }

    if (visibleRows.length === 0) {
      return (
        <tr>
          <td colSpan={7} className={styles.state}>Aucun poste budgétaire ne correspond à votre recherche.</td>
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
          <td className={styles.authorizedCol}>{checked ? 'Oui' : 'Non'}</td>
        </tr>
      )
    })
  }

  return (
    <section className={styles.workspace}>
      <main className={styles.panel}>
        <div className={styles.panelHeader}>
          <div>
            <div className={styles.panelTitle}>Postes budgétaires autorisés</div>
            <div className={styles.panelSubtitle}>
              {serviceLabel ? `Unité sélectionnée : ${serviceLabel}` : 'Sélectionnez une unité pour commencer.'}
            </div>
          </div>
          {hasUnsavedChanges && (
            <span className={styles.dirtyBadge}>
              <AlertCircle size={14} aria-hidden="true" />
              Modifications non enregistrées
            </span>
          )}
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
          <div className={styles.resultsCount}>
            {visibleRows.length} résultat{visibleRows.length > 1 ? 's' : ''}
          </div>
        </div>

        <div className={styles.bulkRow}>
          <div className={styles.selectionCount}>
            {selectedVisibleCount} postes sélectionnés sur {visibleRows.length} visibles
          </div>
          <div className={styles.bulkActions}>
            <button type="button" onClick={autoFitColumns} disabled={!serviceId || visibleRows.length === 0 || saving}>
              <Columns3 size={14} aria-hidden="true" />
              Ajuster colonnes
            </button>
            <button type="button" onClick={selectVisible} disabled={!serviceId || visibleRows.length === 0 || saving}>Tout sélectionner</button>
            <button type="button" onClick={deselectVisible} disabled={!serviceId || visibleRows.length === 0 || saving}>Tout désélectionner</button>
            <button type="button" onClick={invertVisible} disabled={!serviceId || visibleRows.length === 0 || saving}>Inverser la sélection</button>
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
              <col style={{ width: columnWidths.selection }} />
              <col style={{ width: columnWidths.code }} />
              <col style={{ width: columnWidths.libelle }} />
              <col style={{ width: columnWidths.type }} />
              <col style={{ width: columnWidths.budget }} />
              <col style={{ width: columnWidths.etat }} />
              <col style={{ width: columnWidths.autorise }} />
            </colgroup>
            <thead>
              <tr>
                <HeaderCell column="selection" className={styles.checkCol} />
                <HeaderCell column="code" className={styles.codeCol} />
                <HeaderCell column="libelle" />
                <HeaderCell column="type" className={styles.typeCol} />
                <HeaderCell column="budget" className={styles.budgetCol} />
                <HeaderCell column="etat" className={styles.stateCol} />
                <HeaderCell column="autorise" className={styles.authorizedCol} />
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
    </section>
  )
}
