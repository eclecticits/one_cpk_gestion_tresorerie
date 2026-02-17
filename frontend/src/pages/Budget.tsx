import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { closeBudgetExercise, createBudgetLine, deleteBudgetLine, getBudgetExercises, getBudgetLinesTree, initializeBudgetExercise, reopenBudgetExercise, updateBudgetLine } from '../api/budget'
import { getPrintSettings } from '../api/settings'
import styles from './Budget.module.css'
import { formatAmount, toNumber } from '../utils/amount'
import type { BudgetExerciseSummary, BudgetLineSummary, BudgetLineTree } from '../types/budget'
import { ApiError } from '../lib/apiClient'
import { downloadExcel } from '../utils/download'
import { generateBudgetPDF } from '../utils/pdfGenerator'
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../hooks/useToast'
import PageHeader from '../components/PageHeader'

type BudgetTypeFilter = 'TOUT' | 'DEPENSE' | 'RECETTE'
type BudgetLineNode = BudgetLineTree

export default function Budget() {
  const [lines, setLines] = useState<BudgetLineNode[]>([])
  const [annee, setAnnee] = useState<number | null>(null)
  const [statut, setStatut] = useState<string | null>(null)
  const [exercices, setExercices] = useState<BudgetExerciseSummary[]>([])
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<BudgetTypeFilter>('DEPENSE')
  const [draftId, setDraftId] = useState(-1)
  const [rowStatus, setRowStatus] = useState<Record<number, 'idle' | 'saving' | 'saved' | 'error'>>({})
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<Set<number>>(() => new Set())
  const [closing, setClosing] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [initOpen, setInitOpen] = useState(false)
  const [initTargetYear, setInitTargetYear] = useState<number | null>(null)
  const [initCoefficient, setInitCoefficient] = useState(0)
  const [initOverwrite, setInitOverwrite] = useState(false)
  const [initLoading, setInitLoading] = useState(false)
  const [exporting, setExporting] = useState<'excel' | 'pdf' | null>(null)
  const [alertThreshold, setAlertThreshold] = useState(80)

  const confirm = useConfirm()
  const { notifyError, notifySuccess, notifyInfo } = useToast()

  const normalizeTree = (nodes: BudgetLineNode[]): BudgetLineNode[] =>
    nodes.map((node) => ({
      ...node,
      children: normalizeTree(node.children ?? []),
    }))

  const flattenTree = (nodes: BudgetLineNode[], acc: BudgetLineNode[] = []): BudgetLineNode[] => {
    nodes.forEach((node) => {
      acc.push(node)
      if (node.children && node.children.length > 0) {
        flattenTree(node.children, acc)
      }
    })
    return acc
  }

  const buildDescendantMap = (nodes: BudgetLineNode[]) => {
    const map = new Map<number, Set<number>>()
    const walk = (node: BudgetLineNode): Set<number> => {
      const collected = new Set<number>()
      node.children?.forEach((child) => {
        collected.add(child.id)
        walk(child).forEach((id) => collected.add(id))
      })
      map.set(node.id, collected)
      return collected
    }
    nodes.forEach((node) => walk(node))
    return map
  }

  const computeNodeTotals = (node: BudgetLineNode, map: Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>) => {
    let prevu = toNumber(node.montant_prevu)
    let engage = toNumber(node.montant_engage)
    let paye = toNumber(node.montant_paye)

    if (node.children && node.children.length > 0) {
      prevu = 0
      engage = 0
      paye = 0
      node.children.forEach((child) => {
        const childTotals = computeNodeTotals(child, map)
        prevu += childTotals.prevu
        engage += childTotals.engage
        paye += childTotals.paye
      })
    }

    const isDepense = (node.type || '').toUpperCase() === 'DEPENSE'
    const baseConsomme = isDepense ? paye : engage
    const disponible = prevu - baseConsomme
    const pourcentage = prevu > 0 ? (baseConsomme / prevu) * 100 : 0
    const totals = { prevu, engage, paye, disponible, pourcentage }
    map.set(node.id, totals)
    return totals
  }

  const loadBudget = useCallback(async () => {
    try {
      if (!selectedYear) {
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      const params = filter === 'TOUT' ? { annee: selectedYear } : { annee: selectedYear, type: filter }
      const response = await getBudgetLinesTree(params)
      setLines(normalizeTree(response.lignes || []))
      setAnnee(response.annee ?? null)
      setStatut(response.statut ?? null)
    } catch (err: any) {
      const status = err instanceof ApiError ? `HTTP ${err.status}` : null
      const detail = err?.payload?.detail || err?.payload?.message || err?.message || null
      const message = [status, detail].filter(Boolean).join(' - ')
      setError(message || 'Impossible de charger le budget')
    } finally {
      setLoading(false)
    }
  }, [filter, selectedYear])

  useEffect(() => {
    loadBudget()
  }, [loadBudget])

  useEffect(() => {
    const loadExercises = async () => {
      try {
        const response = await getBudgetExercises()
        const items = response.exercices || []
        setExercices(items)
        if (items.length > 0 && !selectedYear) {
          setSelectedYear(items[0].annee)
        }
      } catch (err: any) {
        const status = err instanceof ApiError ? `HTTP ${err.status}` : null
        const detail = err?.payload?.detail || err?.payload?.message || err?.message || null
        const message = [status, detail].filter(Boolean).join(' - ')
        setError(message || 'Impossible de charger les exercices')
      }
    }
    loadExercises()
  }, [])

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await getPrintSettings()
        if (typeof settings.budget_alert_threshold === 'number') {
          setAlertThreshold(settings.budget_alert_threshold)
        }
      } catch {
        setAlertThreshold(80)
      }
    }
    loadSettings()
  }, [])

  const { totalsById, rootTotals, flatLines, descendantMap } = useMemo(() => {
    const totalsMap = new Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>()
    const rootTotals = { prevu: 0, engage: 0, paye: 0, disponible: 0 }

    lines.forEach((line) => {
      const totals = computeNodeTotals(line, totalsMap)
      rootTotals.prevu += totals.prevu
      rootTotals.engage += totals.engage
      rootTotals.paye += totals.paye
      rootTotals.disponible += totals.disponible
    })

    const flatLines = flattenTree(lines, [])
    const descendantMap = buildDescendantMap(lines)

    return { totalsById: totalsMap, rootTotals, flatLines, descendantMap }
  }, [lines])

  const lineById = useMemo(() => {
    const map = new Map<number, BudgetLineNode>()
    flatLines.forEach((line) => map.set(line.id, line))
    return map
  }, [flatLines])

  const isRecetteView = filter === 'RECETTE'
  const isClosed = statut?.toLowerCase() === 'clôturé'
  const maxYear = exercices.length > 0 ? Math.max(...exercices.map((ex) => ex.annee)) : null
  const isOlderYearLocked = selectedYear !== null && maxYear !== null && selectedYear < maxYear
  const isReadOnly = isClosed || isOlderYearLocked

  const handleAddDraft = () => {
    if (!selectedYear || isReadOnly) return
    const newDraftId = draftId - 1
    setDraftId(newDraftId)
    setLines((prev) => [
      {
        id: newDraftId,
        code: '',
        libelle: '',
        parent_code: null,
        parent_id: null,
        type: filter === 'TOUT' ? 'DEPENSE' : filter,
        active: true,
        montant_prevu: 0,
        montant_engage: 0,
        montant_paye: 0,
        montant_disponible: 0,
        pourcentage_consomme: 0,
        children: [],
      },
      ...prev,
    ])
  }

  const handleAddChild = (parent: BudgetLineNode) => {
    if (!selectedYear || isReadOnly) return
    const newDraftId = draftId - 1
    setDraftId(newDraftId)
    const child: BudgetLineNode = {
      id: newDraftId,
      code: '',
      libelle: '',
      parent_code: parent.code,
      parent_id: parent.id,
      type: parent.type ?? (filter === 'TOUT' ? 'DEPENSE' : filter),
      active: true,
      montant_prevu: 0,
      montant_engage: 0,
      montant_paye: 0,
      montant_disponible: 0,
      pourcentage_consomme: 0,
      children: [],
    }
    setLines((prev) => insertChildNode(prev, parent.id, child))
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      next.delete(parent.id)
      return next
    })
  }

  const toggleCollapse = (id: number) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const updateTreeNode = (
    nodes: BudgetLineNode[],
    id: number,
    patch: Partial<BudgetLineSummary>
  ): BudgetLineNode[] =>
    nodes.map((node) => {
      if (node.id === id) {
        return { ...node, ...patch }
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: updateTreeNode(node.children, id, patch) }
      }
      return node
    })

  const replaceTreeNode = (nodes: BudgetLineNode[], id: number, replacement: BudgetLineNode): BudgetLineNode[] =>
    nodes.map((node) => {
      if (node.id === id) {
        return replacement
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: replaceTreeNode(node.children, id, replacement) }
      }
      return node
    })

  const insertChildNode = (nodes: BudgetLineNode[], parentId: number, child: BudgetLineNode): BudgetLineNode[] =>
    nodes.map((node) => {
      if (node.id === parentId) {
        return { ...node, children: [child, ...(node.children ?? [])] }
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: insertChildNode(node.children, parentId, child) }
      }
      return node
    })

  const removeTreeNode = (nodes: BudgetLineNode[], id: number): BudgetLineNode[] =>
    nodes
      .filter((node) => node.id !== id)
      .map((node) => {
        if (node.children && node.children.length > 0) {
          return { ...node, children: removeTreeNode(node.children, id) }
        }
        return node
      })

  const updateLocalLine = (id: number, patch: Partial<BudgetLineSummary>) => {
    setLines((prev) => updateTreeNode(prev, id, patch))
  }

  const handlePersist = async (line: BudgetLineNode) => {
    if (!selectedYear || isReadOnly) return
    if (!line.code || !line.libelle) return
    const hasChildren = line.children && line.children.length > 0
    try {
      setError(null)
      setRowStatus((prev) => ({ ...prev, [line.id]: 'saving' }))
      if (line.id < 0) {
        const created = await createBudgetLine({
          annee: selectedYear,
          code: line.code,
          libelle: line.libelle,
          parent_code: line.parent_code ?? null,
          parent_id: line.parent_id ?? null,
          type: line.type || 'DEPENSE',
          active: line.active ?? true,
          montant_prevu: hasChildren ? 0 : line.montant_prevu,
        })
        setLines((prev) =>
          replaceTreeNode(prev, line.id, { ...created, children: line.children ?? [] })
        )
        setRowStatus((prev) => ({ ...prev, [created.id]: 'saved' }))
      } else {
        const updatePayload: Partial<{
          code: string
          libelle: string
          parent_code?: string | null
          parent_id?: number | null
          type: string
          active?: boolean
          montant_prevu: string | number
        }> = {
          code: line.code,
          libelle: line.libelle,
          parent_code: line.parent_code ?? null,
          parent_id: line.parent_id ?? null,
          type: line.type || 'DEPENSE',
          active: line.active ?? true,
        }
        if (!hasChildren) {
          updatePayload.montant_prevu = line.montant_prevu
        }
        await updateBudgetLine(line.id, updatePayload)
        setRowStatus((prev) => ({ ...prev, [line.id]: 'saved' }))
      }
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de sauvegarder la ligne.'
      setError(detail)
      notifyError('Sauvegarde impossible', detail)
      setRowStatus((prev) => ({ ...prev, [line.id]: 'error' }))
      return
    }
    setTimeout(() => {
      setRowStatus((prev) => {
        if (prev[line.id] === 'saved') {
          const next = { ...prev }
          next[line.id] = 'idle'
          return next
        }
        return prev
      })
    }, 1500)
  }

  const handleDelete = async (line: BudgetLineNode) => {
    if (isReadOnly) return
    if (line.id < 0) {
      setLines((prev) => removeTreeNode(prev, line.id))
      return
    }
    const confirmed = await confirm({
      title: 'Supprimer la ligne budgétaire ?',
      description: `${line.code} - ${line.libelle}`,
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return
    try {
      await deleteBudgetLine(line.id)
      await loadBudget()
      notifySuccess('Ligne supprimée', 'La rubrique budgétaire a été supprimée.')
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de supprimer la ligne.'
      setError(detail)
      notifyError('Suppression impossible', detail)
    }
  }

  const handleCloseExercise = async () => {
    if (!selectedYear || isClosed) return
    const confirmed = await confirm({
      title: `Clôturer l’exercice ${selectedYear} ?`,
      description: 'Cette action bloque toutes les modifications pour cette année.',
      confirmText: 'Clôturer',
      variant: 'danger',
    })
    if (!confirmed) return
    try {
      setClosing(true)
      const res = await closeBudgetExercise(selectedYear)
      setStatut(res.statut || 'Clôturé')
      await loadBudget()
      notifySuccess('Exercice clôturé', `L’année ${selectedYear} est maintenant en lecture seule.`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de clôturer l’exercice.'
      setError(detail)
      notifyError('Clôture impossible', detail)
    } finally {
      setClosing(false)
    }
  }

  const handleReopenExercise = async () => {
    if (!selectedYear || !isClosed) return
    const confirmed = await confirm({
      title: `Déverrouiller l’exercice ${selectedYear} ?`,
      description: 'Cette action rouvre la modification des rubriques budgétaires.',
      confirmText: 'Déverrouiller',
    })
    if (!confirmed) return
    try {
      setReopening(true)
      const res = await reopenBudgetExercise(selectedYear)
      setStatut(res.statut || 'Brouillon')
      await loadBudget()
      notifySuccess('Exercice déverrouillé', `L’année ${selectedYear} est de nouveau modifiable.`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || "Impossible de déverrouiller l’exercice."
      setError(detail)
      notifyError('Déverrouillage impossible', detail)
    } finally {
      setReopening(false)
    }
  }

  const handleOpenInit = () => {
    if (!selectedYear) return
    setInitTargetYear(selectedYear + 1)
    setInitCoefficient(0)
    setInitOverwrite(false)
    setInitOpen(true)
  }

  const handleInitialize = async () => {
    if (!selectedYear || !initTargetYear) return
    try {
      setInitLoading(true)
      await initializeBudgetExercise({
        annee_source: selectedYear,
        annee_cible: initTargetYear,
        coefficient: initCoefficient,
        overwrite: initOverwrite,
      })
      const response = await getBudgetExercises()
      setExercices(response.exercices || [])
      setSelectedYear(initTargetYear)
      setInitOpen(false)
      notifySuccess('Exercice initialisé', `Le budget ${initTargetYear} est prêt.`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || "Impossible d'initialiser l'exercice."
      setError(detail)
      notifyError('Initialisation impossible', detail)
    } finally {
      setInitLoading(false)
    }
  }

  const handleExportExcel = async () => {
    if (!selectedYear) return
    try {
      setExporting('excel')
      await downloadExcel(
        '/exports/budget',
        { annee: selectedYear, type: filter },
        `budget_${selectedYear}_${filter}.xlsx`
      )
      notifyInfo('Export Excel', 'Le fichier a été téléchargé.')
    } catch (err: any) {
      const detail = err?.message || "Impossible d'exporter le fichier Excel."
      setError(detail)
      notifyError('Export Excel impossible', detail)
    } finally {
      setExporting(null)
    }
  }

  const handleExportPDF = async () => {
    if (!selectedYear) return
    try {
      setExporting('pdf')
      const leafLines = flatLines.filter((line) => !(line.children && line.children.length > 0))
      await generateBudgetPDF(leafLines, selectedYear, filter === 'RECETTE' ? 'RECETTE' : 'DEPENSE')
      notifyInfo('Export PDF', 'Le fichier a été généré.')
    } catch (err: any) {
      const detail = err?.message || "Impossible d'exporter le PDF."
      setError(detail)
      notifyError('Export PDF impossible', detail)
    } finally {
      setExporting(null)
    }
  }

  const renderRows = (nodes: BudgetLineNode[], depth = 0): JSX.Element[] =>
    nodes.map((line) => {
      const hasChildren = line.children && line.children.length > 0
      const isCollapsed = collapsedIds.has(line.id)
      const totals = totalsById.get(line.id) || {
        prevu: toNumber(line.montant_prevu),
        engage: toNumber(line.montant_engage),
        paye: toNumber(line.montant_paye),
        disponible: toNumber(line.montant_disponible),
        pourcentage: toNumber(line.pourcentage_consomme),
      }
      const pourcentage = totals.pourcentage
      const warningThreshold = Math.max(0, Math.min(100, alertThreshold))
      const tone = pourcentage >= 100 ? 'danger' : pourcentage >= warningThreshold ? 'warning' : 'ok'
      const objectif = totals.prevu
      const atteint = totals.paye
      const ecart = atteint - objectif
      const recetteStatus =
        objectif === 0
          ? 'Aucun objectif'
          : ecart >= 0
            ? `Objectif dépassé de ${formatAmount(ecart)}`
            : `Manque ${formatAmount(Math.abs(ecart))}`
      const isOverrun = !isRecetteView && totals.disponible < 0
      const isNearLimit = !isRecetteView && pourcentage >= warningThreshold && pourcentage < 100
      const isAtLimit = !isRecetteView && pourcentage >= 100

      const excludedParents = descendantMap.get(line.id) || new Set<number>()
      const parentOptions = flatLines.filter(
        (candidate) =>
          candidate.id !== line.id &&
          !excludedParents.has(candidate.id) &&
          (!line.type || candidate.type === line.type)
      )

      return (
        <Fragment key={line.id}>
          <tr className={`${styles.tableRow} ${line.active === false ? styles.rowInactive : ''} ${hasChildren ? styles.parentRow : ''}`}>
            <td className={styles.code}>
              <input
                className={styles.inlineInput}
                value={line.code}
                onChange={(e) => updateLocalLine(line.id, { code: e.target.value })}
                onBlur={() => handlePersist(line)}
                placeholder="Code"
                disabled={isReadOnly}
              />
            </td>
            <td>
              <div className={styles.treeCell} style={{ paddingLeft: `${depth * 18}px` }}>
                {hasChildren ? (
                  <button
                    className={styles.treeToggle}
                    type="button"
                    onClick={() => toggleCollapse(line.id)}
                    aria-label={isCollapsed ? 'Dérouler' : 'Enrouler'}
                  >
                    {isCollapsed ? '▸' : '▾'}
                  </button>
                ) : (
                  <span className={styles.treeSpacer} />
                )}
                <input
                  className={styles.inlineInput}
                  value={line.libelle}
                  onChange={(e) => updateLocalLine(line.id, { libelle: e.target.value })}
                  onBlur={() => handlePersist(line)}
                  placeholder="Rubrique"
                  disabled={isReadOnly}
                />
              </div>
            </td>
            <td>
              <select
                className={styles.inlineSelect}
                value={line.parent_id ?? ''}
                onChange={(e) => {
                  const parentId = e.target.value ? Number(e.target.value) : null
                  const parentLine = parentId ? lineById.get(parentId) : null
                  const nextLine = {
                    ...line,
                    parent_id: parentId,
                    parent_code: parentLine?.code ?? null,
                  }
                  updateLocalLine(line.id, { parent_id: parentId, parent_code: parentLine?.code ?? null })
                  handlePersist(nextLine)
                }}
                disabled={isReadOnly}
              >
                <option value="">Aucune</option>
                {parentOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.code} - {option.libelle}
                  </option>
                ))}
              </select>
            </td>
            <td>
              {hasChildren ? (
                <span className={styles.readonlyAmount}>
                  {formatAmount(totals.prevu)}
                  <span className={styles.autoSumLabel}>Σ Somme auto</span>
                </span>
              ) : (
                <input
                  className={styles.inlineInput}
                  type="number"
                  step="0.01"
                  value={toNumber(line.montant_prevu)}
                  onChange={(e) => updateLocalLine(line.id, { montant_prevu: Number(e.target.value) })}
                  onBlur={() => handlePersist(line)}
                  disabled={isReadOnly}
                />
              )}
            </td>
            <td>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={line.active !== false}
                  onChange={(e) => {
                    updateLocalLine(line.id, { active: e.target.checked })
                    handlePersist({ ...line, active: e.target.checked })
                  }}
                  disabled={isReadOnly}
                />
                <span className={styles.toggleTrack} />
              </label>
            </td>
            <td>{isRecetteView ? formatAmount(totals.paye) : formatAmount(totals.disponible)}</td>
            <td>
              {isRecetteView ? (
                <span className={ecart >= 0 ? styles.statusOk : styles.statusWarn}>{recetteStatus}</span>
              ) : (
                <div className={styles.progressRow}>
                  <div className={styles.progressTrack}>
                    <div
                      className={`${styles.progressFill} ${styles[`progress${tone}`]}`}
                      style={{ width: `${Math.min(pourcentage, 120)}%` }}
                    />
                  </div>
                  <span className={styles.progressLabel}>{pourcentage.toFixed(1)}%</span>
                </div>
              )}
            </td>
            <td>
              <div className={styles.rowActions}>
                {isAtLimit && <span className={styles.badgeError}>Dépassement</span>}
                {isNearLimit && <span className={styles.badgeWarn}>Alerte {alertThreshold}%</span>}
                {rowStatus[line.id] === 'saving' && <span className={styles.badgeSaving}>Sauvegarde…</span>}
                {rowStatus[line.id] === 'saved' && <span className={styles.badgeSaved}>Sauvegardé ✓</span>}
                {rowStatus[line.id] === 'error' && <span className={styles.badgeError}>Erreur</span>}
                <div className={styles.menuWrapper}>
                  <button
                    className={styles.menuButton}
                    onClick={() => setOpenMenuId(openMenuId === line.id ? null : line.id)}
                    aria-label="Actions"
                    disabled={isReadOnly}
                  >
                    ⋯
                  </button>
                  {openMenuId === line.id && (
                    <div className={styles.menu}>
                      <button className={styles.menuItem} onClick={() => handleAddChild(line)}>
                        Ajouter une sous-rubrique
                      </button>
                      <button className={styles.menuItemDanger} onClick={() => handleDelete(line)}>
                        Supprimer
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </td>
          </tr>
          {!isCollapsed && hasChildren && renderRows(line.children ?? [], depth + 1)}
        </Fragment>
      )
    })

  return (
    <div className={styles.page}>
      <PageHeader
        title="Suivi budgétaire"
        subtitle={`${annee ? `Exercice ${annee}` : 'Aucun exercice'}${statut ? ` · ${statut}` : ''}`}
        actions={
          <div className={styles.filters}>
          <select
            className={styles.yearSelect}
            value={selectedYear ?? ''}
            onChange={(e) => setSelectedYear(e.target.value ? Number(e.target.value) : null)}
          >
            {exercices.length === 0 && <option value="">Aucun exercice</option>}
            {exercices.map((item) => (
              <option key={item.annee} value={item.annee}>
                {item.annee} {item.statut ? `· ${item.statut}` : ''}
              </option>
            ))}
          </select>
          <button className={styles.primaryAction} onClick={handleAddDraft} disabled={isReadOnly}>
            + Nouvelle Rubrique
          </button>
          <button className={styles.secondaryAction} onClick={handleCloseExercise} disabled={!selectedYear || isClosed || closing || isOlderYearLocked}>
            {closing ? 'Clôture...' : 'Clôturer l’année'}
          </button>
          <button className={styles.dangerAction} onClick={handleReopenExercise} disabled={!selectedYear || !isClosed || reopening}>
            {reopening ? 'Déverrouillage...' : 'Déverrouiller'}
          </button>
          <button className={styles.secondaryAction} onClick={handleOpenInit} disabled={!selectedYear || initLoading}>
            Initialiser année suivante
          </button>
          <button className={styles.secondaryAction} onClick={handleExportExcel} disabled={!selectedYear || exporting === 'excel'}>
            {exporting === 'excel' ? 'Export Excel…' : 'Export Excel'}
          </button>
          <button className={styles.secondaryAction} onClick={handleExportPDF} disabled={!selectedYear || exporting === 'pdf'}>
            {exporting === 'pdf' ? 'Export PDF…' : 'Export PDF'}
          </button>
          <button
            className={`${styles.filterButton} ${filter === 'DEPENSE' ? styles.filterActive : ''}`}
            onClick={() => setFilter('DEPENSE')}
          >
            Dépenses (Contrôle)
          </button>
          <button
            className={`${styles.filterButton} ${filter === 'RECETTE' ? styles.filterActive : ''}`}
            onClick={() => setFilter('RECETTE')}
          >
            Recettes (Objectifs)
          </button>
          </div>
        }
      />

      <section className={styles.summary}>
        <div className={styles.summaryCard}>
          <span>{isRecetteView ? 'Objectif' : 'Plafond'}</span>
          <strong>{formatAmount(rootTotals.prevu)}</strong>
        </div>
        {isRecetteView ? (
          <div className={styles.summaryCard}>
            <span>Atteint</span>
            <strong>{formatAmount(rootTotals.paye)}</strong>
          </div>
        ) : (
          <>
            <div className={styles.summaryCard}>
              <span>Engagé</span>
              <strong>{formatAmount(rootTotals.engage)}</strong>
            </div>
            <div className={styles.summaryCard}>
              <span>Disponible</span>
              <strong>{formatAmount(rootTotals.disponible)}</strong>
            </div>
          </>
        )}
      </section>

      <div className={styles.infoBar}>
        {isRecetteView ? (
          <span>Les recettes sont des objectifs à atteindre ou dépasser.</span>
        ) : (
          <span>
            Les dépenses sont des plafonds à ne pas dépasser.
            {isClosed ? ' Exercice clôturé (lecture seule).' : ''}
            {isOlderYearLocked ? ' Exercice antérieur verrouillé.' : ''}
          </span>
        )}
      </div>

      {loading && <div className={styles.state}>Chargement du budget…</div>}
      {error && <div className={styles.error}>{error}</div>}

      {!loading && !error && (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Code</th>
                <th>Rubrique</th>
                <th>Parent</th>
                <th>{isRecetteView ? 'Objectif' : 'Plafond'}</th>
                <th>Actif</th>
                <th>{isRecetteView ? 'Atteint' : 'Disponible'}</th>
                <th>{isRecetteView ? 'Statut' : '% consommé'}</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {renderRows(lines)}
            </tbody>
          </table>
          {lines.length === 0 && <div className={styles.state}>Aucune rubrique budgétaire disponible.</div>}
        </div>
      )}

      {initOpen && (
        <div className={styles.modal} onClick={() => !initLoading && setInitOpen(false)}>
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <h3>Initialiser un nouvel exercice</h3>
            <div className={styles.formGrid}>
              <label>
                Année source
                <input type="number" value={selectedYear ?? ''} disabled />
              </label>
              <label>
                Année cible
                <input
                  type="number"
                  value={initTargetYear ?? ''}
                  onChange={(e) => setInitTargetYear(Number(e.target.value))}
                  disabled={initLoading}
                />
              </label>
              <label>
                Coefficient (ex: 0.05 pour +5%)
                <input
                  type="number"
                  step="0.01"
                  value={initCoefficient}
                  onChange={(e) => setInitCoefficient(Number(e.target.value))}
                  disabled={initLoading}
                />
              </label>
              <label>
                Écraser si existe
                <select
                  value={initOverwrite ? 'oui' : 'non'}
                  onChange={(e) => setInitOverwrite(e.target.value === 'oui')}
                  disabled={initLoading}
                >
                  <option value="non">Non</option>
                  <option value="oui">Oui</option>
                </select>
              </label>
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryAction} onClick={() => setInitOpen(false)} disabled={initLoading}>
                Annuler
              </button>
              <button className={styles.primaryAction} onClick={handleInitialize} disabled={initLoading}>
                {initLoading ? 'Initialisation...' : 'Créer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
