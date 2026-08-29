import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, Download, FileText, MessageSquare, MoreVertical, Plus, Table, X } from 'lucide-react'
import { closeBudgetExercise, createBudgetCommentaire, updateBudgetCommentaire, createBudgetExercise, createBudgetPoste, deleteBudgetPoste, getBudgetCommentaireGeneral, getBudgetCommentaires, getBudgetExercises, getBudgetPostesTree, getBudgetSummary, initializeBudgetExercise, reopenBudgetExercise, saveBudgetCommentaireGeneral, updateBudgetPoste } from '../api/budget'
import type { BudgetCommentaire, BudgetCommentaireGeneral } from '../api/budget'
import { getServices } from '../api/services'
import { getPrintSettings } from '../api/settings'
import styles from './Budget.module.css'
import { formatAmount, toNumber } from '../utils/amount'
import { compareBudgetCodes, normalizeBudgetCode as normalizeCode } from '../utils/budgetCode'
import type { BudgetExerciseSummary, BudgetPosteSummary, BudgetPosteTree } from '../types/budget'
import type { Service } from '../types'
import { ApiError } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { downloadExcel } from '../utils/download'

// `budget` est le premier type ouvert a la file (EXPORT_ASYNC_TYPES, phase 1
// de docs/architecture-exports-asynchrones-20260828.md) : c'est ici que
// l'attente d'un 202 devient visible en premier. Le bouton est deja desactive
// par `exporting` ; ce message dit POURQUOI il l'est.
const MESSAGE_EXPORT_EN_FILE =
  "Cet export est généré en arrière-plan. Laissez cette page ouverte : le téléchargement démarrera automatiquement dès que le fichier sera prêt."
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'export,
// pas au chargement de la page.
type PdfGeneratorModule = typeof import('../utils/pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('../utils/pdfGenerator')
  return _pdfGeneratorModulePromise
}
const generateBudgetPDF: PdfGeneratorModule['generateBudgetPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateBudgetPDF(...args)
}
const generateServiceBudgetReportPDF: PdfGeneratorModule['generateServiceBudgetReportPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorModule()
  return mod.generateServiceBudgetReportPDF(...args)
}
import { useConfirm } from '../contexts/ConfirmContext'
import { useToast } from '../hooks/useToast'
import { useTreeBranchReveal } from '../hooks/useTreeBranchReveal'
import PageHeader from '../components/PageHeader'
// xlsx est lourd : le composant d'import n'est chargé qu'à l'ouverture de la
// modale (importOpen), pas au chargement de la page Budget.
const ImportBudgetPostes = lazy(() => import('../components/ImportBudgetPostes'))

type BudgetTypeFilter = 'TOUT' | 'DEPENSE' | 'RECETTE'
type BudgetPosteNode = BudgetPosteTree

export default function Budget() {
  const [lines, setLines] = useState<BudgetPosteNode[]>([])
  const [annee, setAnnee] = useState<number | null>(null)
  const [statut, setStatut] = useState<string | null>(null)
  const [exercices, setExercices] = useState<BudgetExerciseSummary[]>([])
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const [services, setServices] = useState<Service[]>([])
  const [selectedServiceId, setSelectedServiceId] = useState<number | null>(null)
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
  const [subOpen, setSubOpen] = useState(false)
  const [subParent, setSubParent] = useState<BudgetPosteNode | null>(null)
  const [subCode, setSubCode] = useState('')
  const [subLibelle, setSubLibelle] = useState('')
  const [subPrevu, setSubPrevu] = useState(0)
  const [subSaving, setSubSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedLeafIds, setSelectedLeafIds] = useState<Set<number>>(() => new Set())
  const [exporting, setExporting] = useState<'excel' | 'pdf' | null>(null)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [alertThreshold, setAlertThreshold] = useState(80)
  const [prevYearTotalsByCode, setPrevYearTotalsByCode] = useState<Map<string, number>>(() => new Map())
  const [prevYearLoading, setPrevYearLoading] = useState(false)
  // Fil de commentaires de l'exercice, indexé par code de poste. Chargé en un
  // seul appel : un budget dépasse la centaine de lignes, une requête par ligne
  // écroulerait la page. Le code est l'ancre — il survit aux réimports.
  const [commentairesByCode, setCommentairesByCode] = useState<Map<string, BudgetCommentaire[]>>(() => new Map())
  const [commentPanelCode, setCommentPanelCode] = useState<string | null>(null)
  const [commentPanelLibelle, setCommentPanelLibelle] = useState('')
  const [commentDraft, setCommentDraft] = useState('')
  const [commentSaving, setCommentSaving] = useState(false)
  const [commentEditingId, setCommentEditingId] = useState<number | null>(null)
  const [commentEditDraft, setCommentEditDraft] = useState('')
  // Commentaire général de l'exercice : un texte par vue, repris sous le
  // tableau dans tous les exports. Les deux vues sont chargées ensemble, la
  // bascule dépenses/recettes ne doit pas rappeler le serveur.
  const [commentGeneral, setCommentGeneral] = useState<BudgetCommentaireGeneral | null>(null)
  const [commentGeneralDraft, setCommentGeneralDraft] = useState('')
  const [commentGeneralSaving, setCommentGeneralSaving] = useState(false)
  const [budgetSummary, setBudgetSummary] = useState<{
    annee: number | null
    recettes: { prevu: number; reel: number }
    depenses: { prevu: number; reel: number; engage?: number; paye?: number }
    service_id?: number | null
    total_recettes?: number
    total_depenses?: number
    solde?: number
  } | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [createExerciseOpen, setCreateExerciseOpen] = useState(false)
  const [createExerciseYear, setCreateExerciseYear] = useState<number>(new Date().getFullYear())
  const [createExerciseLoading, setCreateExerciseLoading] = useState(false)
  const selectedService = useMemo(
    () => services.find((service) => service.id === selectedServiceId) || null,
    [services, selectedServiceId]
  )

  const confirm = useConfirm()
  const { notifyError, notifySuccess, notifyInfo } = useToast()
  const revealTreeBranch = useTreeBranchReveal()
  const { user } = useAuth()
  const isSuperAdmin = (user?.role || '').toLowerCase() === 'super_admin'
  const hasExercises = exercices.length > 0
  const hasSelectedExercise = selectedYear !== null
  const closeMenus = () => {
    setExportMenuOpen(false)
    setMoreMenuOpen(false)
  }

  const normalizeTree = (nodes: BudgetPosteNode[]): BudgetPosteNode[] =>
    [...nodes]
      .sort((a, b) => compareBudgetCodes(a.code, b.code))
      .map((node) => ({
        ...node,
        children: normalizeTree(node.children ?? []),
      }))

  const collectParentIds = (nodes: BudgetPosteNode[], acc: Set<number> = new Set()): Set<number> => {
    nodes.forEach((node) => {
      if (node.children && node.children.length > 0) {
        acc.add(node.id)
        collectParentIds(node.children, acc)
      }
    })
    return acc
  }

  const flattenTree = (nodes: BudgetPosteNode[], acc: BudgetPosteNode[] = []): BudgetPosteNode[] => {
    nodes.forEach((node) => {
      acc.push(node)
      if (node.children && node.children.length > 0) {
        flattenTree(node.children, acc)
      }
    })
    return acc
  }

  const computeNodeTotals = (node: BudgetPosteNode, map: Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>) => {
    let prevu = toNumber(node.montant_prevu)
    let engage = toNumber(node.montant_engage)
    let paye = toNumber(node.montant_paye)

    if (node.children && node.children.length > 0) {
      prevu = 0
      engage = 0
      paye = 0
      node.children.forEach((child) => {
        // Les totaux de l'enfant sont calculés dans tous les cas : une ligne
        // hors calcul reste affichée avec ses montants. Seule son addition au
        // parent est sautée.
        const childTotals = computeNodeTotals(child, map)
        if (child.inclure_dans_calculs === false) return
        prevu += childTotals.prevu
        engage += childTotals.engage
        paye += childTotals.paye
      })
    }

    const baseConsomme = paye
    const disponible = prevu - baseConsomme
    const pourcentage = prevu > 0 ? (baseConsomme / prevu) * 100 : 0
    const totals = { prevu, engage, paye, disponible, pourcentage }
    map.set(node.id, totals)
    return totals
  }

  const loadBudget = useCallback(async () => {
    try {
      if (!selectedYear) {
        setLines([])
        setAnnee(null)
        setStatut(null)
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      const params = filter === 'TOUT'
        ? { annee: selectedYear, service_id: selectedServiceId }
        : { annee: selectedYear, type: filter, service_id: selectedServiceId }
      const response = await getBudgetPostesTree(params)
      const normalized = normalizeTree(response.postes || [])
      setLines(normalized)
      setCollapsedIds(collectParentIds(normalized))
      setSelectedLeafIds(new Set())
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
  }, [filter, selectedYear, selectedServiceId])

  useEffect(() => {
    loadBudget()
  }, [loadBudget])

  const loadExercises = useCallback(async () => {
    try {
      const response = await getBudgetExercises()
      const items = response.exercices || []
      setExercices(items)
      setSelectedYear((current) => {
        if (items.length === 0) return null
        if (current && items.some((item) => item.annee === current)) return current
        return items[0].annee
      })
    } catch (err: any) {
      const status = err instanceof ApiError ? `HTTP ${err.status}` : null
      const detail = err?.payload?.detail || err?.payload?.message || err?.message || null
      const message = [status, detail].filter(Boolean).join(' - ')
      setError(message || 'Impossible de charger les exercices')
    }
  }, [])

  useEffect(() => {
    loadExercises()
  }, [loadExercises])

  useEffect(() => {
    const loadServices = async () => {
      try {
        const response = await getServices({ active: true })
        const items = Array.isArray(response) ? response : []
        setServices(items)
      } catch (err) {
        console.error('Erreur de chargement des services', err)
      }
    }
    loadServices()
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

  useEffect(() => {
    const loadSummary = async () => {
      if (!selectedYear) {
        setBudgetSummary(null)
        return
      }
      try {
        setSummaryLoading(true)
        const summary = await getBudgetSummary({ annee: selectedYear, service_id: selectedServiceId })
        setBudgetSummary(summary)
      } catch {
        setBudgetSummary(null)
      } finally {
        setSummaryLoading(false)
      }
    }
    loadSummary()
  }, [selectedYear, selectedServiceId])

  useEffect(() => {
    const loadPrevYear = async () => {
      if (!selectedYear) return
      const prevYear = selectedYear - 1
      const hasPrev = exercices.some((ex) => ex.annee === prevYear)
      if (!hasPrev) {
        setPrevYearTotalsByCode(new Map())
        return
      }
      try {
        setPrevYearLoading(true)
        const params = filter === 'TOUT' ? { annee: prevYear } : { annee: prevYear, type: filter }
        const response = await getBudgetPostesTree(params)
        const normalized = normalizeTree(response.postes || [])
        const totalsMap = new Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>()
        normalized.forEach((node) => computeNodeTotals(node, totalsMap))
        const flatPrev = flattenTree(normalized, [])
        const codeMap = new Map<string, number>()
        flatPrev.forEach((node) => {
          const code = normalizeCode(node.code)
          if (!code) return
          const totals = totalsMap.get(node.id)
          codeMap.set(code, totals ? totals.prevu : toNumber(node.montant_prevu))
        })
        setPrevYearTotalsByCode(codeMap)
      } catch {
        setPrevYearTotalsByCode(new Map())
      } finally {
        setPrevYearLoading(false)
      }
    }
    loadPrevYear()
  }, [selectedYear, filter, exercices])

  const loadCommentaires = useCallback(async () => {
    if (!selectedYear) {
      setCommentairesByCode(new Map())
      return
    }
    try {
      const res = await getBudgetCommentaires({ annee: selectedYear })
      const map = new Map<string, BudgetCommentaire[]>()
      for (const c of res.commentaires || []) {
        const key = normalizeCode(c.code)
        if (!key) continue
        const fil = map.get(key)
        if (fil) fil.push(c)
        else map.set(key, [c])
      }
      setCommentairesByCode(map)
    } catch {
      // Les commentaires sont un enrichissement : leur indisponibilité ne doit
      // pas empêcher de travailler le budget lui-même.
      setCommentairesByCode(new Map())
    }
  }, [selectedYear])

  useEffect(() => {
    loadCommentaires()
  }, [loadCommentaires])

  const loadCommentGeneral = useCallback(async () => {
    if (!selectedYear) {
      setCommentGeneral(null)
      return
    }
    try {
      setCommentGeneral(await getBudgetCommentaireGeneral({ annee: selectedYear }))
    } catch {
      // Même principe que le fil de ligne : un commentaire indisponible ne doit
      // pas empêcher de travailler le budget.
      setCommentGeneral(null)
    }
  }, [selectedYear])

  useEffect(() => {
    loadCommentGeneral()
  }, [loadCommentGeneral])

  // Texte de la vue courante. Les recettes et les dépenses sortent en deux
  // documents distincts, chacun avec son propre commentaire ; la vue « Tout »
  // édite celui des dépenses, qui est le budget principal.
  const vueExport: 'DEPENSE' | 'RECETTE' = filter === 'RECETTE' ? 'RECETTE' : 'DEPENSE'
  const commentGeneralTexte =
    (vueExport === 'RECETTE' ? commentGeneral?.recette : commentGeneral?.depense) || ''

  // Le brouillon de saisie suit la vue et l'exercice sélectionnés, tant que
  // l'utilisateur n'est pas en train de le modifier.
  useEffect(() => {
    setCommentGeneralDraft(commentGeneralTexte)
  }, [commentGeneralTexte, selectedYear, vueExport])

  const commentGeneralModifiable = commentGeneral?.modifiable !== false
  const commentGeneralDirty = commentGeneralDraft.trim() !== commentGeneralTexte.trim()

  const handleSaveCommentGeneral = async () => {
    if (!selectedYear) return
    try {
      setCommentGeneralSaving(true)
      const res = await saveBudgetCommentaireGeneral({
        annee: selectedYear,
        vue: vueExport,
        texte: commentGeneralDraft,
      })
      setCommentGeneral(res)
      notifySuccess(
        'Commentaire général enregistré',
        'Il apparaîtra sous le tableau dans les exports PDF et Excel.'
      )
    } catch (err: any) {
      notifyError(
        'Enregistrement impossible',
        err?.payload?.detail || err?.message || 'Réessaie dans un instant.'
      )
    } finally {
      setCommentGeneralSaving(false)
    }
  }

  const commentairesDuPoste = (code?: string | null) =>
    commentairesByCode.get(normalizeCode(code)) || []

  const handleUpdateCommentaire = async (id: number) => {
    const texte = commentEditDraft.trim()
    if (!texte) return
    try {
      setCommentSaving(true)
      await updateBudgetCommentaire(id, { texte })
      setCommentEditingId(null)
      setCommentEditDraft('')
      await loadCommentaires()
    } catch (err: any) {
      notifyError('Modification impossible', err?.message || 'Réessaie dans un instant.')
    } finally {
      setCommentSaving(false)
    }
  }

  const handleAddCommentaire = async () => {
    const texte = commentDraft.trim()
    if (!texte || !commentPanelCode || !selectedYear) return
    try {
      setCommentSaving(true)
      await createBudgetCommentaire({ annee: selectedYear, code: commentPanelCode, texte })
      setCommentDraft('')
      await loadCommentaires()
    } catch (err: any) {
      notifyError('Commentaire non enregistré', err?.message || 'Réessaie dans un instant.')
    } finally {
      setCommentSaving(false)
    }
  }

  const { totalsById, rootTotals, flatLines } = useMemo(() => {
    const totalsMap = new Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>()
    const rootTotals = { prevu: 0, engage: 0, paye: 0, disponible: 0 }

    lines.forEach((line) => {
      const totals = computeNodeTotals(line, totalsMap)
      if (line.inclure_dans_calculs === false) return
      rootTotals.prevu += totals.prevu
      rootTotals.engage += totals.engage
      rootTotals.paye += totals.paye
      rootTotals.disponible += totals.disponible
    })

    const flatLines = flattenTree(lines, [])
    return { totalsById: totalsMap, rootTotals, flatLines }
  }, [lines])


  const isRecetteView = filter === 'RECETTE'
  // Le brouillon est le seul état où un commentaire reste corrigeable. Le
  // serveur reste l'autorité (champ `modifiable`) ; ce booléen ne sert qu'au
  // libellé d'aide, pour annoncer la règle avant que l'on écrive.
  const isBrouillon = statut?.toLowerCase() === 'brouillon'
  const isClosed = statut?.toLowerCase() === 'clôturé'
  const maxYear = exercices.length > 0 ? Math.max(...exercices.map((ex) => ex.annee)) : null
  const isOlderYearLocked = selectedYear !== null && maxYear !== null && selectedYear < maxYear
  const isReadOnly = isClosed || isOlderYearLocked
  const hasActiveEditableExercise = hasSelectedExercise && !isReadOnly
  const canImport = hasActiveEditableExercise && filter !== 'TOUT'
  const emptyStateMessage = hasExercises
    ? "Aucun exercice budgétaire actif. Veuillez créer ou sélectionner un exercice avant d’ajouter des postes budgétaires."
    : "Aucun exercice budgétaire actif. Veuillez créer ou sélectionner un exercice avant d’ajouter des postes budgétaires."
  const selectionHint = hasExercises
    ? "Sélectionnez un exercice actif pour ajouter, importer ou modifier des postes budgétaires."
    : emptyStateMessage

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

  const handleAddChild = (parent: BudgetPosteNode) => {
    if (!selectedYear || isReadOnly) return
    setSubParent(parent)
    setSubCode('')
    setSubLibelle('')
    setSubPrevu(0)
    setSubOpen(true)
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
    nodes: BudgetPosteNode[],
    id: number,
    patch: Partial<BudgetPosteSummary>
  ): BudgetPosteNode[] =>
    nodes.map((node) => {
      if (node.id === id) {
        return { ...node, ...patch }
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: updateTreeNode(node.children, id, patch) }
      }
      return node
    })

  const replaceTreeNode = (nodes: BudgetPosteNode[], id: number, replacement: BudgetPosteNode): BudgetPosteNode[] =>
    nodes.map((node) => {
      if (node.id === id) {
        return replacement
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: replaceTreeNode(node.children, id, replacement) }
      }
      return node
    })

  const insertChildNode = (nodes: BudgetPosteNode[], parentId: number, child: BudgetPosteNode): BudgetPosteNode[] =>
    nodes.map((node) => {
      if (node.id === parentId) {
        return { ...node, children: [child, ...(node.children ?? [])] }
      }
      if (node.children && node.children.length > 0) {
        return { ...node, children: insertChildNode(node.children, parentId, child) }
      }
      return node
    })

  const removeTreeNode = (nodes: BudgetPosteNode[], id: number): BudgetPosteNode[] =>
    nodes
      .filter((node) => node.id !== id)
      .map((node) => {
        if (node.children && node.children.length > 0) {
          return { ...node, children: removeTreeNode(node.children, id) }
        }
        return node
      })

  const updateLocalLine = (id: number, patch: Partial<BudgetPosteSummary>) => {
    setLines((prev) => updateTreeNode(prev, id, patch))
  }

  const handlePersist = async (line: BudgetPosteNode) => {
    if (!selectedYear || isReadOnly) return
    if (!line.code || !line.libelle) return
    const hasChildren = line.children && line.children.length > 0
    try {
      setError(null)
      setRowStatus((prev) => ({ ...prev, [line.id]: 'saving' }))
      if (line.id < 0) {
        const created = await createBudgetPoste({
          annee: selectedYear,
          code: line.code,
          libelle: line.libelle,
          parent_code: line.parent_code ?? null,
          parent_id: line.parent_id ?? null,
          type: line.type || 'DEPENSE',
          active: line.active ?? true,
          inclure_dans_calculs: line.inclure_dans_calculs ?? true,
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
          inclure_dans_calculs?: boolean
          montant_prevu: string | number
        }> = {
          code: line.code,
          libelle: line.libelle,
          parent_code: line.parent_code ?? null,
          parent_id: line.parent_id ?? null,
          type: line.type || 'DEPENSE',
          active: line.active ?? true,
          inclure_dans_calculs: line.inclure_dans_calculs ?? true,
        }
        if (!hasChildren) {
          updatePayload.montant_prevu = line.montant_prevu
        }
        await updateBudgetPoste(line.id, updatePayload)
        setRowStatus((prev) => ({ ...prev, [line.id]: 'saved' }))
      }
    } catch (err: any) {
      const status = err instanceof ApiError ? `HTTP ${err.status}` : null
      const detail = err?.payload?.detail || err?.payload?.message || err?.message || 'Impossible de sauvegarder la ligne.'
      const message = [status, detail].filter(Boolean).join(' - ')
      setError(message)
      notifyError('Sauvegarde impossible', message)
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

  const handleDelete = async (line: BudgetPosteNode) => {
    if (isReadOnly) return
    if (line.id < 0) {
      setLines((prev) => removeTreeNode(prev, line.id))
      return
    }
    const confirmed = await confirm({
      title: 'Supprimer le poste budgétaire ?',
      description: `${line.code} - ${line.libelle}`,
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return
    try {
      await deleteBudgetPoste(line.id)
      await loadBudget()
      notifySuccess('Poste supprimé', 'Le poste budgétaire a été supprimé.')
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de supprimer la ligne.'
      setError(detail)
      notifyError('Suppression impossible', detail)
    }
  }

  const handleDeleteSelection = async () => {
    if (isReadOnly) return
    const ids = Array.from(selectedLeafIds)
    if (ids.length === 0) return
    const selectedLines = flattenTree(lines).filter((line) => ids.includes(line.id))
    const hasGlobal = selectedLines.some((line) => line.is_global)
    if (hasGlobal && !isSuperAdmin) {
      notifyInfo('Action limitée', 'Certaines lignes sont officielles et ne peuvent pas être supprimées.')
      return
    }
    const confirmed = await confirm({
      title: 'Supprimer la sélection ?',
      description: `${ids.length} sous-poste(s) vont être supprimés.`,
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return

    try {
      const draftIds = ids.filter((id) => id < 0)
      const realIds = ids.filter((id) => id >= 0)

      if (draftIds.length > 0) {
        setLines((prev) => draftIds.reduce((acc, id) => removeTreeNode(acc, id), prev))
      }

      for (const id of realIds) {
        await deleteBudgetPoste(id)
      }

      await loadBudget()
      setSelectedLeafIds(new Set())
      notifySuccess('Suppression terminée', `${ids.length} sous-poste(s) supprimé(s).`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de supprimer la sélection.'
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
      description: 'Cette action rouvre la modification des postes budgétaires.',
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

  const handleOpenCreateExercise = () => {
    const suggestedYear = exercices.length > 0
      ? Math.max(...exercices.map((item) => item.annee)) + 1
      : new Date().getFullYear()
    setCreateExerciseYear(suggestedYear)
    setCreateExerciseOpen(true)
  }

  const handleCreateExercise = async () => {
    if (!Number.isFinite(createExerciseYear) || createExerciseYear <= 0) {
      notifyError('Création impossible', "L'année de l'exercice est invalide.")
      return
    }
    try {
      setCreateExerciseLoading(true)
      setError(null)
      const created = await createBudgetExercise({ annee: createExerciseYear })
      await loadExercises()
      setSelectedYear(created.annee)
      setCreateExerciseOpen(false)
      notifySuccess('Exercice créé', `L’exercice ${created.annee} est prêt.`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || "Impossible de créer l'exercice."
      setError(detail)
      notifyError('Création impossible', detail)
    } finally {
      setCreateExerciseLoading(false)
    }
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
      await loadExercises()
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
        `budget_${selectedYear}_${filter}.xlsx`,
        { onMiseEnFile: () => notifyInfo('Export en préparation', MESSAGE_EXPORT_EN_FILE) }
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

  const handleExportServiceExcel = async () => {
    if (!selectedYear || !selectedServiceId) return
    try {
      setExporting('excel')
      await downloadExcel(
        '/exports/budget',
        { annee: selectedYear, type: filter, service_id: selectedServiceId },
        `budget_${selectedYear}_${filter}_service${selectedServiceId}.xlsx`,
        { onMiseEnFile: () => notifyInfo('Export en préparation', MESSAGE_EXPORT_EN_FILE) }
      )
      notifyInfo('Export Excel (service)', 'Le fichier du service a été téléchargé.')
    } catch (err: any) {
      const detail = err?.message || "Impossible d'exporter le fichier Excel du service."
      setError(detail)
      notifyError('Export Excel impossible', detail)
    } finally {
      setExporting(null)
    }
  }

  const handleExportPDF = async (avecCommentaires = false) => {
    if (!selectedYear) return
    try {
      setExporting('pdf')
      // Arbre complet : les postes parents (lignes annuelles) sont exportés avec
      // leurs sous-postes. Les montants d'un parent = somme de ses enfants.
      const totalsMap = new Map<number, { prevu: number; engage: number; paye: number; disponible: number; pourcentage: number }>()
      lines.forEach((root) => computeNodeTotals(root, totalsMap))
      const depthMap = new Map<number, number>()
      const walkDepth = (nodes: BudgetPosteNode[], d: number) => {
        nodes.forEach((n) => {
          depthMap.set(n.id, d)
          if (n.children && n.children.length > 0) walkDepth(n.children, d + 1)
        })
      }
      walkDepth(lines, 0)
      const hierarchicalLines = flatLines.map((node) => {
        const t = totalsMap.get(node.id)
        const hasChildren = !!(node.children && node.children.length > 0)
        return {
          code: node.code,
          libelle: node.libelle,
          type: node.type,
          montant_prevu: t ? t.prevu : toNumber(node.montant_prevu),
          montant_engage: t ? t.engage : toNumber(node.montant_engage),
          montant_paye: t ? t.paye : toNumber(node.montant_paye),
          montant_disponible: t ? t.disponible : toNumber(node.montant_disponible),
          pourcentage_consomme: t ? t.pourcentage : toNumber(node.pourcentage_consomme),
          is_parent: hasChildren,
          level: depthMap.get(node.id) ?? 0,
          inclure_dans_calculs: node.inclure_dans_calculs !== false,
        }
      })
      // La version annotée bascule en paysage et ajoute une colonne. On ne
      // transmet la carte des commentaires que dans ce cas : c'est sa présence
      // qui commande l'orientation, une carte vide garderait le portrait. Le
      // commentaire général, lui, accompagne les deux versions.
      await generateBudgetPDF(
        hierarchicalLines,
        selectedYear,
        vueExport,
        {
          commentaires: avecCommentaires ? commentairesByCode : undefined,
          commentaireGeneral: commentGeneralTexte,
          // La comparaison N-1 n'a pas d'export dédié : elle voyage avec la
          // version annotée, seule variante déjà en paysage — le portrait est
          // plein à 180 mm sur 182 utiles, deux colonnes de plus n'y entrent
          // pas sans écraser le libellé des postes.
          comparaisonN1: avecCommentaires ? prevYearTotalsByCode : undefined,
        }
      )
      notifyInfo(
        'Export PDF',
        avecCommentaires
          ? 'Version annotée générée (paysage, commentaires et comparaison N-1).'
          : 'Le fichier a été généré.'
      )
    } catch (err: any) {
      const detail = err?.message || "Impossible d'exporter le PDF."
      setError(detail)
      notifyError('Export PDF impossible', detail)
    } finally {
      setExporting(null)
    }
  }

  const handlePrintServiceReport = async () => {
    if (!selectedYear || !selectedService) return
    try {
      const leafLines = flatLines.filter((line) => !(line.children && line.children.length > 0))
      await generateServiceBudgetReportPDF({
        lignes: leafLines,
        annee: selectedYear,
        vue: vueExport,
        serviceLabel: `${selectedService.code} - ${selectedService.libelle}`,
        totals: {
          recettes: Number(budgetSummary?.total_recettes ?? budgetSummary?.recettes?.reel ?? 0),
          depenses: Number(budgetSummary?.total_depenses ?? budgetSummary?.depenses?.reel ?? 0),
          solde: Number(budgetSummary?.solde ?? 0),
        },
        commentaireGeneral: commentGeneralTexte,
      })
      notifyInfo('Rapport service', 'Le rapport a été généré.')
    } catch (err: any) {
      const detail = err?.message || "Impossible de générer le rapport."
      setError(detail)
      notifyError('Rapport service impossible', detail)
    }
  }


  const handleCreateSubRubrique = async () => {
    if (!selectedYear || !subParent) return
    if (!subCode.trim() || !subLibelle.trim()) return
    try {
      setSubSaving(true)
      await createBudgetPoste({
        annee: selectedYear,
        code: subCode,
        libelle: subLibelle,
        parent_id: subParent.id,
        parent_code: subParent.code,
        type: subParent.type ?? (filter === 'TOUT' ? 'DEPENSE' : filter),
        active: true,
        montant_prevu: subPrevu,
      })
      setSubOpen(false)
      setCollapsedIds((prev) => {
        const next = new Set(prev)
        next.delete(subParent.id)
        return next
      })
      await loadBudget()
      notifySuccess('Poste ajouté', `Ajouté sous ${subParent.code}.`)
    } catch (err: any) {
      const detail = err?.payload?.detail || err?.message || 'Impossible de créer le poste budgétaire.'
      setError(detail)
      notifyError('Création impossible', detail)
    } finally {
      setSubSaving(false)
    }
  }

  const renderRows = (nodes: BudgetPosteNode[], depth = 0, branchIds: number[] = []): JSX.Element[] =>
    nodes.map((line) => {
      const hasChildren = line.children && line.children.length > 0
      const isCollapsed = collapsedIds.has(line.id)
      const isLeaf = !hasChildren
      const totals = totalsById.get(line.id) || {
        prevu: toNumber(line.montant_prevu),
        engage: toNumber(line.montant_engage),
        paye: toNumber(line.montant_paye),
        disponible: toNumber(line.montant_disponible),
        pourcentage: toNumber(line.pourcentage_consomme),
      }
      const pourcentage = totals.pourcentage
      const warningThreshold = Math.max(0, Math.min(100, alertThreshold))
      const isOverrun = !isRecetteView && totals.disponible < -0.005
      const isAtLimit = !isRecetteView && !isOverrun && Math.abs(totals.disponible) <= 0.005
      const isNearLimit = !isRecetteView && !isAtLimit && pourcentage >= warningThreshold && pourcentage < 100
      const tone = isOverrun ? 'danger' : (isAtLimit || isNearLimit) ? 'warning' : 'ok'
      const objectif = totals.prevu
      const atteint = totals.paye
      const ecart = atteint - objectif
      const recetteStatus =
        objectif === 0
          ? 'Aucun objectif'
          : ecart >= 0
            ? `Objectif dépassé de ${formatAmount(ecart)}`
            : `Manque ${formatAmount(Math.abs(ecart))}`
      const prevPrevu = prevYearTotalsByCode.get(normalizeCode(line.code))
      const ecartValue = prevPrevu === undefined ? null : totals.prevu - prevPrevu

      return (
        <Fragment key={line.id}>
          <tr
            className={`${styles.tableRow} ${line.inclure_dans_calculs === false ? styles.rowHorsCalcul : ''} ${line.active === false ? styles.rowInactive : ''} ${hasChildren ? styles.parentRow : ''} ${hasChildren && !isCollapsed ? styles.parentRowOpen : ''} ${depth > 0 ? styles.childRow : ''}`}
            style={openMenuId === line.id ? { position: 'relative', zIndex: 50 } : {}}
            data-tree-node={String(line.id)}
            data-tree-branch={branchIds.length > 0 ? branchIds.join(' ') : undefined}
            onClick={(event) => {
              if (!hasChildren) return
              const target = event.target as HTMLElement
              if (target.closest('input,select,button,label,textarea')) return
              event.preventDefault()
              event.stopPropagation()
              const willOpen = isCollapsed
              toggleCollapse(line.id)
              if (willOpen) revealTreeBranch(event.currentTarget)
            }}
          >
            <td className={`${styles.colCode} ${styles.code}`}>
              <input
                className={styles.inlineInput}
                value={line.code}
                onChange={(e) => updateLocalLine(line.id, { code: e.target.value })}
                onBlur={() => handlePersist(line)}
                placeholder="Code"
                disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
              />
            </td>
            <td className={styles.colLabel}>
              <div className={styles.treeCell} style={{ paddingLeft: `${depth * 18}px` }}>
                {hasChildren ? (
                  <span className={`${styles.treeToggle} ${isCollapsed ? styles.treeToggleCollapsed : ''}`} aria-hidden />
                ) : (
                  <span className={styles.treeSpacer} />
                )}
                <input
                  className={styles.inlineInput}
                  value={line.libelle}
                  onChange={(e) => updateLocalLine(line.id, { libelle: e.target.value })}
                  onBlur={() => handlePersist(line)}
                  placeholder="Poste budgétaire"
                  disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
                />
                {line.is_global && <span className={styles.globalBadge}>🌍 Officiel</span>}
                {line.inclure_dans_calculs === false && (
                  <span
                    className={styles.horsCalculBadge}
                    title="Ligne affichée mais exclue des totaux, des pourcentages et de la synthèse"
                  >
                    Hors calcul
                  </span>
                )}
                {/* Pastille de commentaires : pas de douzième colonne, la table
                    en compte déjà onze. Le compteur reste visible même à zéro au
                    survol, sinon on ne découvre jamais la fonctionnalité. */}
                <button
                  type="button"
                  className={`${styles.commentBadge} ${commentairesDuPoste(line.code).length > 0 ? styles.commentBadgeActive : ''}`}
                  title={
                    commentairesDuPoste(line.code).length > 0
                      ? `${commentairesDuPoste(line.code).length} commentaire(s) — cliquer pour lire`
                      : 'Ajouter un commentaire'
                  }
                  onClick={(event) => {
                    event.stopPropagation()
                    setCommentPanelCode(line.code)
                    setCommentPanelLibelle(line.libelle || '')
                    setCommentDraft('')
                  }}
                >
                  <MessageSquare size={13} />
                  {commentairesDuPoste(line.code).length > 0 && (
                    <span>{commentairesDuPoste(line.code).length}</span>
                  )}
                </button>
              </div>
            </td>
            <td className={styles.colAmount}>
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
            <td className={styles.colPrevYear}>
              {prevPrevu === undefined ? (
                <span className={styles.mutedValue}>—</span>
              ) : (
                <span className={styles.prevValue}>{formatAmount(prevPrevu)}</span>
              )}
            </td>
            <td className={styles.colDelta}>
              {ecartValue === null ? (
                <span className={styles.mutedValue}>—</span>
              ) : (
                <span
                  className={
                    ecartValue > 0
                      ? styles.deltaPositive
                      : ecartValue < 0
                        ? styles.deltaNegative
                        : styles.deltaNeutral
                  }
                >
                  {formatAmount(ecartValue)}
                </span>
              )}
            </td>
            <td className={styles.colReal}>{formatAmount(totals.paye)}</td>
            <td className={styles.colActive}>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={line.active !== false}
                  onChange={(e) => {
                    updateLocalLine(line.id, { active: e.target.checked })
                    handlePersist({ ...line, active: e.target.checked })
                  }}
                  disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
                />
                <span className={styles.toggleTrack} />
              </label>
            </td>
            <td className={`${styles.colAvailable} ${isOverrun ? styles.overrunValue : ''}`}>
              {isRecetteView ? formatAmount(totals.paye) : formatAmount(totals.disponible)}
              {!isRecetteView && selectedServiceId && (
                <div
                  className={styles.remainingBar}
                  title={`Reste à dépenser: ${Math.max(0, 100 - pourcentage).toFixed(1)}%`}
                >
                  <div
                    className={`${styles.remainingFill} ${styles[`remaining${tone}`]}`}
                    style={{ width: `${Math.max(0, Math.min(100, 100 - pourcentage))}%` }}
                  />
                </div>
              )}
            </td>
            <td className={styles.colProgress}>
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
            <td className={styles.colActions}>
              <div className={styles.rowActions}>
                {isOverrun && <span className={styles.badgeError}>Dépassement</span>}
                {isAtLimit && <span className={styles.badgeWarn}>Plafond atteint</span>}
                {isNearLimit && <span className={styles.badgeWarn}>Alerte {alertThreshold}%</span>}
                {rowStatus[line.id] === 'saving' && <span className={styles.badgeSaving}>Sauvegarde…</span>}
                {rowStatus[line.id] === 'saved' && <span className={styles.badgeSaved}>Sauvegardé ✓</span>}
                {rowStatus[line.id] === 'error' && <span className={styles.badgeError}>Erreur</span>}
                <button
                  type="button"
                  className={`${styles.quickAdd} ${styles.iconBtn}`}
                  onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    handleAddChild(line)
                  }}
                  disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
                  title="Ajouter un sous-poste"
                  aria-label="Ajouter un sous-poste"
                >
                  <Plus size={14} />
                </button>
                <div className={styles.menuWrapper}>
                  <button
                    className={`${styles.menuButton} ${styles.iconBtn}`}
                    onClick={() => setOpenMenuId(openMenuId === line.id ? null : line.id)}
                    aria-label="Actions"
                    disabled={isReadOnly}
                  >
                    <MoreVertical size={16} />
                  </button>
          {openMenuId === line.id && (
            <div className={styles.menu}>
              <button
                className={styles.menuItem}
                onClick={() => handleAddChild(line)}
                disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
              >
                Ajouter un sous-poste
              </button>
              {/* Exclure une ligne des calculs : elle reste affichée, ses
                  montants sortent des totaux et de la synthèse. Cas type, le
                  report d'un exercice antérieur, qui n'est pas une recette de
                  l'année. L'exclusion s'applique à toute la branche. */}
              <button
                className={styles.menuItem}
                onClick={() => {
                  const inclure = line.inclure_dans_calculs === false
                  setOpenMenuId(null)
                  updateLocalLine(line.id, { inclure_dans_calculs: inclure })
                  handlePersist({ ...line, inclure_dans_calculs: inclure })
                }}
                disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
                title={
                  hasChildren
                    ? 'Le changement s’applique aussi à tous les sous-postes'
                    : 'La ligne reste affichée, ses montants sortent des totaux'
                }
              >
                {line.inclure_dans_calculs === false
                  ? 'Réintégrer aux calculs'
                  : 'Exclure des calculs'}
              </button>
              <button
                className={styles.menuItemDanger}
                onClick={() => handleDelete(line)}
                disabled={isReadOnly || (line.is_global && !isSuperAdmin)}
              >
                        Supprimer
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </td>
            <td className={`${styles.colSelect} ${styles.selectCell}`}>
              {isLeaf && (
                <input
                  type="checkbox"
                  checked={selectedLeafIds.has(line.id)}
                  onChange={(event) => {
                    const checked = event.target.checked
                    setSelectedLeafIds((prev) => {
                      const next = new Set(prev)
                      if (checked) {
                        next.add(line.id)
                      } else {
                        next.delete(line.id)
                      }
                      return next
                    })
                  }}
                  disabled={isReadOnly}
                />
              )}
            </td>
          </tr>
          {!isCollapsed && hasChildren && renderRows(line.children ?? [], depth + 1, [...branchIds, line.id])}
        </Fragment>
      )
    })

  return (
    <div className={styles.page}>
      <PageHeader
        title="Suivi budgétaire"
        subtitle={`${annee ? `Exercice ${annee}` : 'Aucun exercice'}${statut ? ` · ${statut}` : ''}`}
        actions={
          <div className={styles.toolbar}>
            <div className={styles.toolbarRow}>
              <div className={styles.toolbarFilters}>
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
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={handleOpenCreateExercise}
                  disabled={createExerciseLoading}
                >
                  {createExerciseLoading ? 'Création...' : 'Créer un exercice budgétaire'}
                </button>
                <select
                  className={styles.yearSelect}
                  value={selectedServiceId ?? ''}
                  onChange={(e) => setSelectedServiceId(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">Tous les services</option>
                  {services.map((service) => (
                    <option key={service.id} value={service.id}>
                      {service.code} - {service.libelle}
                    </option>
                  ))}
                </select>
              </div>
              <button className={styles.primaryAction} onClick={handleAddDraft} disabled={!hasActiveEditableExercise}>
                <Plus size={16} />
                Nouveau poste budgétaire
              </button>
            </div>
            <div className={styles.toolbarRow}>
              <div className={styles.toolbarPills}>
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
              <div className={styles.toolbarActions}>
                <div className={styles.dropdown}>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    onClick={() => {
                      setExportMenuOpen((prev) => !prev)
                      setMoreMenuOpen(false)
                    }}
                    title="Exporter"
                  >
                    <Download size={16} />
                    Exporter
                    <ChevronDown size={14} />
                  </button>
                  {exportMenuOpen && (
                    <>
                      <button type="button" className={styles.menuBackdrop} onClick={closeMenus} />
                      <div className={styles.dropdownMenu}>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleExportExcel()
                          }}
                          disabled={!selectedYear || exporting === 'excel'}
                        >
                          <Table size={14} />
                          {exporting === 'excel' ? 'Export Excel…' : 'Export Excel'}
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleExportPDF()
                          }}
                          disabled={!selectedYear || exporting === 'pdf'}
                        >
                          <FileText size={14} />
                          {exporting === 'pdf' ? 'Export PDF…' : 'Export PDF'}
                        </button>
                        {/* Variante annotée : même budget, même chiffres, plus
                            les justifications. Désactivée tant qu'aucune ligne
                            n'est commentée — le PDF serait identique au premier
                            mais en paysage, ce qui n'a aucun intérêt. */}
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleExportPDF(true)
                          }}
                          disabled={!selectedYear || exporting === 'pdf' || commentairesByCode.size === 0}
                          title={
                            commentairesByCode.size === 0
                              ? 'Aucune ligne commentée sur cet exercice'
                              : 'Format paysage : commentaires par ligne et comparaison N-1'
                          }
                        >
                          <MessageSquare size={14} />
                          Export PDF annoté (paysage)
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleExportServiceExcel()
                          }}
                          disabled={!selectedYear || !selectedServiceId || exporting === 'excel'}
                          title={!selectedServiceId ? 'Sélectionnez un service' : undefined}
                        >
                          <Table size={14} />
                          Export Excel (par service)
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handlePrintServiceReport()
                          }}
                          disabled={!selectedYear || !selectedServiceId}
                          title={!selectedServiceId ? 'Sélectionnez un service' : undefined}
                        >
                          <FileText size={14} />
                          Export PDF (par service)
                        </button>
                      </div>
                    </>
                  )}
                </div>
                <div className={styles.dropdown}>
                  <button
                    type="button"
                    className={styles.iconAction}
                    onClick={() => {
                      setMoreMenuOpen((prev) => !prev)
                      setExportMenuOpen(false)
                    }}
                    title="Plus d'actions"
                  >
                    <MoreVertical size={18} />
                  </button>
                  {moreMenuOpen && (
                    <>
                      <button type="button" className={styles.menuBackdrop} onClick={closeMenus} />
                      <div className={styles.dropdownMenu}>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleCloseExercise()
                          }}
                          disabled={!hasSelectedExercise || isClosed || closing || isOlderYearLocked}
                        >
                          {closing ? 'Clôture…' : 'Clôturer l’année'}
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleReopenExercise()
                          }}
                          disabled={!selectedYear || !isClosed || reopening}
                        >
                          {reopening ? 'Déverrouillage…' : 'Déverrouiller'}
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            closeMenus()
                            handleOpenInit()
                          }}
                          disabled={!hasActiveEditableExercise || initLoading}
                        >
                          Initialiser année suivante
                        </button>
                        <button
                          type="button"
                          className={styles.menuItem}
                          onClick={() => {
                            if (filter === 'TOUT') {
                              notifyError('Import impossible', 'Choisis un type (Dépenses ou Recettes) avant l’import.')
                              return
                            }
                            closeMenus()
                            setImportOpen(true)
                          }}
                          disabled={!canImport}
                        >
                          Importer Excel
                        </button>
                        <button
                          type="button"
                          className={styles.menuItemDanger}
                          onClick={() => {
                            closeMenus()
                            handleDeleteSelection()
                          }}
                          disabled={isReadOnly || selectedLeafIds.size === 0}
                        >
                          Supprimer sélection ({selectedLeafIds.size})
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        }
      />

      {(summaryLoading || budgetSummary) && (
        <section className={styles.overview}>
          <div className={styles.overviewHeader}>
            <h3>Résumé budget</h3>
            <span>Exercice {budgetSummary?.annee ?? selectedYear ?? '—'}</span>
          </div>
          {summaryLoading ? (
            <div className={styles.state}>Chargement de la synthèse…</div>
          ) : (
            budgetSummary && (
              <div className={styles.summary}>
                <div className={styles.summaryCard}>
                  <span>{selectedService ? 'Total recettes' : 'Total recettes prévues'}</span>
                  <strong>
                    {formatAmount(
                      selectedService ? budgetSummary.total_recettes ?? budgetSummary.recettes?.reel ?? 0 : budgetSummary.recettes?.prevu ?? 0
                    )}
                  </strong>
                </div>
                <div className={styles.summaryCard}>
                  <span>{selectedService ? 'Total dépenses' : 'Total dépenses prévues'}</span>
                  <strong>
                    {formatAmount(
                      selectedService ? budgetSummary.total_depenses ?? budgetSummary.depenses?.reel ?? 0 : budgetSummary.depenses?.prevu ?? 0
                    )}
                  </strong>
                </div>
                <div className={styles.summaryCard}>
                  <span>{selectedService ? 'Solde du service' : 'Solde prévisionnel'}</span>
                  <strong>
                    {formatAmount(
                      selectedService
                        ? budgetSummary.solde ?? (budgetSummary.total_recettes ?? 0) - (budgetSummary.total_depenses ?? 0)
                        : (budgetSummary.recettes?.prevu ?? 0) - (budgetSummary.depenses?.prevu ?? 0)
                    )}
                  </strong>
                </div>
              </div>
            )
          )}
        </section>
      )}

      <section className={styles.summary}>
        <div className={styles.summaryCard}>
          <span>Prévu</span>
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
          <span>
            Les recettes sont des objectifs à atteindre ou dépasser.
            {selectedService ? ` Filtre service : ${selectedService.code}.` : ''}
            {!hasSelectedExercise ? ` ${selectionHint}` : ''}
            {prevYearLoading ? ' Comparaison N-1 en cours…' : ''}
          </span>
        ) : (
          <span>
            Les dépenses sont des plafonds à ne pas dépasser.
            {selectedService ? ` Filtre service : ${selectedService.code}.` : ''}
            {!hasSelectedExercise ? ` ${selectionHint}` : ''}
            {isClosed ? ' Exercice clôturé (lecture seule).' : ''}
            {isOlderYearLocked ? ' Exercice antérieur verrouillé.' : ''}
            {prevYearLoading ? ' Comparaison N-1 en cours…' : ''}
          </span>
        )}
      </div>

      {!loading && !error && !hasSelectedExercise && (
        <section className={styles.emptyState}>
          <h3>Aucun exercice budgétaire actif</h3>
          <p>{emptyStateMessage}</p>
          <div className={styles.emptyStateActions}>
            <button type="button" className={styles.primaryAction} onClick={handleOpenCreateExercise}>
              Créer un exercice budgétaire
            </button>
          </div>
        </section>
      )}

      {loading && <div className={styles.state}>Chargement du budget…</div>}
      {error && <div className={styles.error}>{error}</div>}

      {!loading && !error && hasSelectedExercise && (
        <div className={styles.tableWrapper} data-tree-scroll>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.colCode}>Code</th>
                <th className={styles.colLabel}>Poste budgétaire</th>
                <th className={styles.colAmount}>Prévu</th>
                {/* Libelle generique : l'exercice compare se deduit de l'annee
                    selectionnee, l'afficher en dur ferait doublon avec le
                    selecteur d'exercice juste au-dessus. */}
                <th className={styles.colPrevYear}>Budget N-1</th>
                <th className={styles.colDelta}>Écart</th>
                <th className={styles.colReal}>Réalisé</th>
                <th className={styles.colActive}>Actif</th>
                <th className={styles.colAvailable}>{isRecetteView ? 'Atteint' : 'Disponible'}</th>
                <th className={styles.colProgress}>{isRecetteView ? 'Statut' : "% Taux d'exécution"}</th>
                <th className={styles.colActions}>Actions</th>
                <th className={`${styles.colSelect} ${styles.selectHeader}`}>Sélection</th>
              </tr>
            </thead>
            <tbody>
              {renderRows(lines)}
            </tbody>
          </table>
          {hasSelectedExercise && lines.length === 0 && (
            <div className={styles.state}>
              Aucun poste budgétaire disponible pour cet exercice. Vous pouvez créer un poste ou importer un fichier Excel.
            </div>
          )}
        </div>
      )}

      {/* Commentaire général : sous le tableau à l'écran comme sur les
          documents, pour que la saisie se fasse à la place exacte où le lecteur
          le trouvera. Un texte par vue — la bascule dépenses/recettes change le
          contenu du champ. */}
      {!loading && !error && hasSelectedExercise && (
        <section className={styles.generalComment}>
          <header className={styles.generalCommentHeader}>
            <h3>
              <MessageSquare size={15} />
              Commentaire général — {isRecetteView ? 'Recettes' : 'Dépenses'} {selectedYear}
            </h3>
            <span className={styles.commentHint}>
              Repris sous le tableau dans tous les exports PDF et Excel de cette vue.
            </span>
          </header>
          <textarea
            className={styles.generalCommentInput}
            value={commentGeneralDraft}
            onChange={(e) => setCommentGeneralDraft(e.target.value)}
            disabled={!commentGeneralModifiable || commentGeneralSaving}
            rows={4}
            placeholder={
              commentGeneralModifiable
                ? "Cadrage de l'exercice, hypothèses retenues, arbitrages… Ce texte accompagne le budget exporté."
                : 'Exercice clôturé : le commentaire général est figé.'
            }
          />
          <div className={styles.generalCommentActions}>
            {!commentGeneralModifiable && (
              <span className={styles.commentHint}>
                Exercice clôturé : lecture seule.
              </span>
            )}
            {commentGeneralModifiable && (
              <>
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={() => setCommentGeneralDraft(commentGeneralTexte)}
                  disabled={!commentGeneralDirty || commentGeneralSaving}
                >
                  Annuler
                </button>
                <button
                  type="button"
                  className={styles.primaryAction}
                  onClick={handleSaveCommentGeneral}
                  disabled={!commentGeneralDirty || commentGeneralSaving}
                >
                  {commentGeneralSaving ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              </>
            )}
          </div>
        </section>
      )}

      {commentPanelCode && (
        <div className={styles.commentOverlay} onClick={() => setCommentPanelCode(null)}>
          <aside
            className={styles.commentPanel}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={`Commentaires du poste ${commentPanelCode}`}
          >
            <header className={styles.commentPanelHeader}>
              <div>
                <span className={styles.commentPanelCode}>{commentPanelCode}</span>
                <h3>{commentPanelLibelle || 'Poste budgétaire'}</h3>
              </div>
              <button
                type="button"
                className={styles.commentPanelClose}
                onClick={() => setCommentPanelCode(null)}
                aria-label="Fermer"
              >
                <X size={18} />
              </button>
            </header>

            <div className={styles.commentThread}>
              {commentairesDuPoste(commentPanelCode).length === 0 && (
                <p className={styles.commentEmpty}>
                  Aucun commentaire sur cette ligne. Explique ici une variation de montant, un
                  arbitrage ou une réserve — la justification reste attachée au poste.
                </p>
              )}
              {commentairesDuPoste(commentPanelCode).map((c) => (
                <article key={c.id} className={styles.commentItem}>
                  <div className={styles.commentMeta}>
                    <strong>{c.auteur_nom || 'Auteur inconnu'}</strong>
                    <span>
                      {new Date(c.created_at).toLocaleString('fr-FR', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                    {/* Le statut figé à l'écriture : une demande de rallonge notée
                        en brouillon ne se lit pas comme une note d'exécution. */}
                    {c.statut_budget && (
                      <span className={styles.commentStatut}>{c.statut_budget}</span>
                    )}
                    {/* Une retouche muette laisserait croire à la rédaction
                        d'origine : elle est signalée, avec sa date au survol. */}
                    {c.updated_at && (
                      <span
                        className={styles.commentEdited}
                        title={`Modifié le ${new Date(c.updated_at).toLocaleString('fr-FR')}`}
                      >
                        modifié
                      </span>
                    )}
                  </div>
                  {commentEditingId === c.id ? (
                    <div className={styles.commentEditBox}>
                      <textarea
                        value={commentEditDraft}
                        onChange={(e) => setCommentEditDraft(e.target.value)}
                        rows={3}
                        disabled={commentSaving}
                      />
                      <div className={styles.commentEditActions}>
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          onClick={() => setCommentEditingId(null)}
                          disabled={commentSaving}
                        >
                          Annuler
                        </button>
                        <button
                          type="button"
                          className={styles.primaryAction}
                          onClick={() => handleUpdateCommentaire(c.id)}
                          disabled={commentSaving || !commentEditDraft.trim()}
                        >
                          {commentSaving ? 'Enregistrement…' : 'Enregistrer'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p>{c.texte}</p>
                      {c.modifiable && (
                        <button
                          type="button"
                          className={styles.commentEditLink}
                          onClick={() => {
                            setCommentEditingId(c.id)
                            setCommentEditDraft(c.texte)
                          }}
                        >
                          Modifier
                        </button>
                      )}
                    </>
                  )}
                </article>
              ))}
            </div>

            <div className={styles.commentComposer}>
              <textarea
                value={commentDraft}
                onChange={(e) => setCommentDraft(e.target.value)}
                placeholder="Ajouter un commentaire…"
                rows={3}
                disabled={commentSaving}
              />
              <div className={styles.commentComposerActions}>
                {/* La règle change au vote : tant que le budget se travaille, un
                    commentaire est une note corrigeable ; une fois voté, il est
                    versé au dossier et seul l'ajout reste possible. */}
                <span className={styles.commentHint}>
                  {isBrouillon
                    ? 'Budget au brouillon : tu peux encore modifier tes propres commentaires.'
                    : 'Budget voté : les commentaires sont figés, ajoute-en un nouveau.'}
                </span>
                <button
                  type="button"
                  className={styles.primaryAction}
                  onClick={handleAddCommentaire}
                  disabled={commentSaving || !commentDraft.trim()}
                >
                  {commentSaving ? 'Envoi…' : 'Commenter'}
                </button>
              </div>
            </div>
          </aside>
        </div>
      )}

      {createExerciseOpen && (
        <div className={styles.modal} onClick={() => !createExerciseLoading && setCreateExerciseOpen(false)}>
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <h3>Créer un exercice budgétaire</h3>
            <div className={styles.formGrid}>
              <label>
                Année
                <input
                  type="number"
                  value={createExerciseYear}
                  onChange={(e) => setCreateExerciseYear(Number(e.target.value))}
                  disabled={createExerciseLoading}
                />
              </label>
            </div>
            <div className={styles.modalActions}>
              <button
                className={styles.secondaryAction}
                onClick={() => setCreateExerciseOpen(false)}
                disabled={createExerciseLoading}
              >
                Annuler
              </button>
              <button className={styles.primaryAction} onClick={handleCreateExercise} disabled={createExerciseLoading}>
                {createExerciseLoading ? 'Création...' : 'Créer'}
              </button>
            </div>
          </div>
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

      {importOpen && selectedYear && filter !== 'TOUT' && (
        <Suspense fallback={null}>
          <ImportBudgetPostes
            annee={selectedYear}
            type={filter}
            onClose={() => setImportOpen(false)}
            onSuccess={() => {
              loadBudget()
            }}
          />
        </Suspense>
      )}

      {subOpen && subParent && (
        <div className={styles.modal} onClick={() => !subSaving && setSubOpen(false)}>
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <h3>Ajouter un sous-poste</h3>
            <div className={styles.formGrid}>
              <label>
                Parent
                <input type="text" value={`${subParent.code} - ${subParent.libelle}`} disabled />
              </label>
              <label>
                Code
                <input
                  type="text"
                  value={subCode}
                  onChange={(e) => setSubCode(e.target.value)}
                  disabled={subSaving}
                />
              </label>
              <label>
                Libellé
                <input
                  type="text"
                  value={subLibelle}
                  onChange={(e) => setSubLibelle(e.target.value)}
                  disabled={subSaving}
                />
              </label>
              <label>
                Prévu
                <input
                  type="number"
                  step="0.01"
                  value={subPrevu}
                  onChange={(e) => setSubPrevu(Number(e.target.value))}
                  disabled={subSaving}
                />
              </label>
            </div>
            <div className={styles.modalActions}>
              <button className={styles.secondaryAction} onClick={() => setSubOpen(false)} disabled={subSaving}>
                Annuler
              </button>
              <button className={styles.primaryAction} onClick={handleCreateSubRubrique} disabled={subSaving}>
                {subSaving ? 'Création...' : 'Créer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
