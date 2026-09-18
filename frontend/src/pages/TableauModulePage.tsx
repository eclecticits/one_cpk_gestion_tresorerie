import { useEffect, useState, Suspense } from 'react'
import { lazyWithRetry } from '../utils/lazyWithRetry'
import { useLocation, useNavigate } from 'react-router-dom'
import { AlertTriangle, BarChart2, Bot, CheckCircle2, ChevronLeft, ChevronRight, Download, FileSpreadsheet, FileText, GitCompare, Layers, Pencil, RefreshCw, Save, Search, Settings, Table2, Upload, X, XCircle } from 'lucide-react'
import TableauAssistantChat from '../components/TableauAssistantChat'
// xlsx est lourd : chargement dynamique seulement quand l'onglet "import" est actif.
const ImportTableauDossiers = lazyWithRetry(() => import('../components/ImportTableauDossiers'))
import BackButton from '../components/BackButton'
import { ApiError } from '../lib/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { useAuth } from '../contexts/AuthContext'
import {
  compareTableauExercices,
  correctTableauDossier,
  getTableauAnalyse,
  generateTableauPV,
  generateTableauReport,
  getTableauBase,
  getTableauReglages,
  listTableauAudit,
  TABLEAU_CATEGORIES,
  runTableauAnalyseBase,
  getTableauStats,
  listTableauAnomalies,
  listTableauDossiers,
  listTableauImports,
  listTableauActualisations,
  type TableauActualisation,
  listTableauReports,
  runTableauAnalyse,
  updateTableauReglages,
  downloadTableauExport,
  type TableauAuditEntry,
  type TableauReglages,
  type TableauAnalyse,
  type TableauBase,
  type TableauAnomalie,
  type TableauComparison,
  type TableauDossier,
  type TableauImport,
  type TableauReport,
  type TableauStats,
} from '../api/tableau'
import styles from './SecretariatPage.module.css'

type TabKey = 'dashboard' | 'actualisations' | 'base' | 'import' | 'analyse' | 'anomalies' | 'comparaison' | 'rapports' | 'reglages' | 'journal'

/** Chaque écran du module a son adresse : le menu de gauche y mène, et un lien
 *  vers une anomalie ou un rapport reste partageable. */
const CHEMINS: Record<TabKey, string> = {
  dashboard: '/tableau',
  actualisations: '/tableau/actualisations',
  base: '/tableau/base',
  import: '/tableau/imports',
  analyse: '/tableau/analyse',
  anomalies: '/tableau/anomalies',
  comparaison: '/tableau/comparaison',
  rapports: '/tableau/rapports',
  reglages: '/tableau/reglages',
  journal: '/tableau/journal',
}
const ONGLETS: Record<string, TabKey> = Object.fromEntries(
  Object.entries(CHEMINS).map(([onglet, chemin]) => [chemin, onglet as TabKey]),
)

const baseTableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '13px',
  background: '#fff',
}

const baseThStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  borderBottom: '1px solid #e5e7eb',
  color: '#6b7280',
  fontWeight: 600,
  whiteSpace: 'nowrap',
}

const baseTdStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderBottom: '1px solid #f1f2f4',
  color: '#374151',
}

const TITRES: Record<TabKey, string> = {
  dashboard: "Tableau de l'Ordre",
  actualisations: 'Actualisations',
  base: 'Base Tableau',
  import: 'Imports Excel',
  analyse: 'Analyse réglementaire',
  anomalies: 'Anomalies',
  comparaison: 'Comparaison d\'exercices',
  rapports: 'Rapports & procès-verbaux',
  reglages: 'Règles de délibération',
  journal: 'Journal des actions',
}

const LIBELLES_AUDIT: Record<string, string> = {
  'tableau.dossier.correct': 'Correction d\'un dossier',
  'tableau.decision.create': 'Décision de commission',
  'tableau.assistant.chat': 'Question à l\'assistant',
}

/** Ce que l'entrée dit en une ligne, sans étaler le contenu du journal. */
function resumerAudit(entree: TableauAuditEntry): string {
  const meta = entree.metadata_json || {}
  const morceaux: string[] = []
  if (typeof meta.numero_ordre === 'string') morceaux.push(meta.numero_ordre)
  if (Array.isArray(meta.champs) && meta.champs.length) morceaux.push(`champs : ${meta.champs.join(', ')}`)
  if (typeof meta.decision === 'string') morceaux.push(meta.decision)
  if (typeof meta.motif === 'string') morceaux.push(`« ${meta.motif} »`)
  if (Array.isArray(meta.outils) && meta.outils.length) morceaux.push(`outils : ${meta.outils.join(', ')}`)
  return morceaux.join(' · ') || '—'
}

function booleanStatus(value: boolean | null) {
  if (value === true) return <span style={{ color: '#166534', fontWeight: 600 }}>Oui</span>
  if (value === false) return <span style={{ color: '#991b1b', fontWeight: 600 }}>Non</span>
  return <span style={{ color: '#6b7280' }}>Non renseigné</span>
}

function AnalyseObsolete({ scope, onRelancer }: { scope: 'import' | 'base'; onRelancer?: () => void }) {
  return (
    <div role="status" style={{
      display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap',
      background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: '8px',
      padding: '12px 14px', marginBottom: '16px', fontSize: '13px', color: '#92400e',
    }}>
      <AlertTriangle size={18} style={{ flexShrink: 0 }} />
      <span style={{ flex: 1, minWidth: '240px' }}>
        <strong>Analyse obsolète.</strong> Un import, une correction, une décision ou un changement de
        réglages a modifié {scope === 'base' ? 'la base consolidée' : 'cet import'} depuis ce calcul.
        Les chiffres ci-dessous datent d'avant ; l'export, le rapport et le PV resteront refusés tant que
        l'analyse n'aura pas été relancée.
      </span>
      {onRelancer && (
        <button type="button" className={styles.secondaryButton} onClick={onRelancer}>
          <RefreshCw size={14} />
          Relancer l'analyse
        </button>
      )}
    </div>
  )
}

function StatCard({ value, label, icon, hint }: { value: number | string; label: string; icon: React.ReactNode; hint?: string }) {
  return (
    <div style={{
      background: '#fff',
      borderRadius: '8px',
      border: '1px solid #e5e7eb',
      padding: '16px 20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      minWidth: '140px',
    }}>
      <div style={{ color: 'var(--tenant-primary, #714b67)', opacity: 0.8 }}>{icon}</div>
      <div style={{ fontSize: '28px', fontWeight: '700', color: '#1f2933', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: '12px', color: '#6b7280', fontWeight: '500' }}>{label}</div>
      {hint && <div style={{ fontSize: '11px', color: '#9ca3af' }}>{hint}</div>}
    </div>
  )
}

export default function TableauModulePage() {
  const { hasPermission } = usePermissions()
  const { user } = useAuth()
  const canImport = hasPermission('tableau.import')
  const canAnalyze = hasPermission('tableau.analyze')
  const canCompare = hasPermission('tableau.compare')
  const canReport = hasPermission('tableau.generate_report')
  const canGeneratePv = hasPermission('tableau.generate_pv')
  const canExport = hasPermission('tableau.export')
  const canCorrect = hasPermission('tableau.correct')
  const canSettings = hasPermission('tableau.settings')
  const canUseAssistant = hasPermission('tableau.use_assistant')
  const canViewAudit = hasPermission('tableau.view_audit_logs')
  const canNational = user?.role?.toLowerCase() === 'super_admin'
    || (user?.role?.toLowerCase() === 'admin' && user?.organisation_slug?.toLowerCase() === 'cn')
  const location = useLocation()
  const navigate = useNavigate()
  const activeTab: TabKey = ONGLETS[location.pathname.replace(/\/+$/, '') || '/tableau'] ?? 'dashboard'
  const setActiveTab = (tab: TabKey) => navigate(CHEMINS[tab])
  const [base, setBase] = useState<TableauBase | null>(null)
  const [baseLoading, setBaseLoading] = useState(false)
  const [baseNational, setBaseNational] = useState(false)
  const [baseError, setBaseError] = useState<string | null>(null)
  const [baseAnalyse, setBaseAnalyse] = useState<string | null>(null)
  const [baseExercice, setBaseExercice] = useState('')
  const [baseSearch, setBaseSearch] = useState('')
  const [baseCategorie, setBaseCategorie] = useState('')
  const [baseOrganisationId, setBaseOrganisationId] = useState('')
  const [basePage, setBasePage] = useState(1)
  const [basePageSize, setBasePageSize] = useState(50)
  const [baseRefresh, setBaseRefresh] = useState(0)
  // La base est consolidée à chaque requête : on n'interroge le serveur qu'une
  // fois la frappe stabilisée.
  const baseSearchDiffere = useDebouncedValue(baseSearch)
  const baseExerciceDiffere = useDebouncedValue(baseExercice)
  const [stats, setStats] = useState<TableauStats | null>(null)
  const [imports, setImports] = useState<TableauImport[]>([])
  const [actualisations, setActualisations] = useState<TableauActualisation[]>([])
  const [dossiers, setDossiers] = useState<TableauDossier[]>([])
  const [dossierPage, setDossierPage] = useState(1)
  const [dossierPageSize, setDossierPageSize] = useState(50)
  const [anomalies, setAnomalies] = useState<TableauAnomalie[]>([])
  const [reports, setReports] = useState<TableauReport[]>([])
  const [comparison, setComparison] = useState<TableauComparison | null>(null)
  const [comparisonPage, setComparisonPage] = useState(1)
  const [comparisonPageSize, setComparisonPageSize] = useState(50)
  const [analyse, setAnalyse] = useState<TableauAnalyse | null>(null)
  const [selectedImport, setSelectedImport] = useState<TableauImport | null>(null)
  const [selectedReport, setSelectedReport] = useState<TableauReport | null>(null)
  const [analysisScope, setAnalysisScope] = useState<'import' | 'base'>('import')
  const [correctionDossier, setCorrectionDossier] = useState<TableauDossier | null>(null)
  const [journal, setJournal] = useState<TableauAuditEntry[]>([])
  const [journalLoading, setJournalLoading] = useState(false)
  const [correctionForm, setCorrectionForm] = useState({
    numero_ordre: '', nom: '', categorie: '', email: '', telephone: '',
    cotisation: '', assurance: '', motif: '',
  })

  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (activeTab !== 'actualisations') return
    listTableauActualisations().then(result => setActualisations(result.items)).catch(() => setError('Impossible de charger les actualisations.'))
  }, [activeTab])

  const [exercice, setExercice] = useState(String(new Date().getFullYear()))
  const [compareExerciceA, setCompareExerciceA] = useState('')
  const [compareExerciceB, setCompareExerciceB] = useState('')
  const [reportTitle, setReportTitle] = useState('')
  const [reportInstructions, setReportInstructions] = useState('')
  const [pvInstructions, setPvInstructions] = useState('')

  const [reglages, setReglages] = useState<TableauReglages>({
    heures_formation_min: 120,
    age_seuil: 60,
    age_action: 'a_deliberer',
    nouveau_anciennete_ans: 3,
    exempter_nouveaux: true,
  })

  const apiErr = (err: unknown, fallback: string) =>
    err instanceof ApiError ? err.message : fallback

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [statsData, importsData, reportsData] = await Promise.all([
        getTableauStats().catch(() => null),
        listTableauImports().catch(() => []),
        listTableauReports().catch(() => []),
      ])
      if (statsData) setStats(statsData)
      setImports(importsData)
      setReports(reportsData)
      if (importsData.length > 0 && !selectedImport) {
        setSelectedImport(importsData[0])
        await loadImportDetails(importsData[0].id)
      } else if (selectedImport) {
        await loadImportDetails(selectedImport.id)
      }
    } catch (err) {
      setError(apiErr(err, 'Erreur de chargement.'))
    } finally {
      setLoading(false)
    }
  }

  const loadImportDetails = async (importId: number, scope: 'import' | 'base' = 'import') => {
    // L'analyse est relue avec le reste : c'est elle qui dit si le calcul
    // affiché vaut encore, ou s'il a été rendu obsolète depuis.
    const [dossiersData, anomaliesData, analyseData] = await Promise.all([
      listTableauDossiers({ import_id: importId }).catch(() => []),
      listTableauAnomalies({ import_id: importId, scope }).catch(() => []),
      getTableauAnalyse(importId, scope).catch(() => null),
    ])
    setDossiers(dossiersData)
    setAnomalies(anomaliesData)
    setAnalyse(analyseData)
  }

  const handleSelectImport = async (imp: TableauImport) => {
    setSelectedImport(imp)
    setAnalysisScope('import')
    setLoading(true)
    try {
      await loadImportDetails(imp.id, 'import')
    } finally {
      setLoading(false)
    }
  }

  const handleImported = async (importId: number | null) => {
    setError(null)
    await loadAll()
    if (importId != null) {
      const imps = await listTableauImports()
      const imp = imps.find(i => i.id === importId) || null
      if (imp) {
        setSelectedImport(imp)
        await loadImportDetails(imp.id)
      }
    }
  }

  const handleAnalyse = async () => {
    if (!selectedImport) return
    setActionLoading('analyse')
    setError(null)
    try {
      const result = await runTableauAnalyse(selectedImport.id)
      setAnalyse(result)
      setAnalysisScope('import')
      await loadImportDetails(selectedImport.id)
      await getTableauStats().then(s => s && setStats(s))
      setActiveTab('analyse')
    } catch (err) {
      setError(apiErr(err, "Erreur lors de l'analyse."))
    } finally {
      setActionLoading(null)
    }
  }

  const handleCompare = async () => {
    if (!compareExerciceA.trim() || !compareExerciceB.trim()) {
      setError('Veuillez renseigner les deux exercices à comparer.')
      return
    }
    setActionLoading('compare')
    setError(null)
    try {
      const result = await compareTableauExercices(compareExerciceA.trim(), compareExerciceB.trim())
      setComparison(result)
      setComparisonPage(1)
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la comparaison.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleGenerateReport = async () => {
    if (!selectedImport) return
    setActionLoading('report')
    setError(null)
    try {
      const r = await generateTableauReport({
        import_id: selectedImport.id,
        exercice: selectedImport.exercice,
        scope: analysisScope,
        titre: reportTitle.trim() || `Rapport d'analyse Tableau ${selectedImport.exercice}`,
        instructions: reportInstructions.trim() || undefined,
      })
      setSelectedReport(r)
      setReports(prev => [r, ...prev])
      setActiveTab('rapports')
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la génération du rapport.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleGeneratePV = async () => {
    if (!selectedImport) return
    setActionLoading('pv')
    setError(null)
    try {
      const r = await generateTableauPV({
        import_id: selectedImport.id,
        exercice: selectedImport.exercice,
        scope: analysisScope,
        instructions: pvInstructions.trim() || undefined,
      })
      setSelectedReport(r)
      setReports(prev => [r, ...prev])
      setActiveTab('rapports')
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la génération du PV.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleSaveReglages = async () => {
    if (!selectedImport) return
    setActionLoading('reglages')
    setError(null)
    try {
      await updateTableauReglages(selectedImport.id, reglages)
      // Les réglages sont communs à l'exercice : recalculer le même périmètre.
      if (analysisScope === 'base') {
        const result = await runTableauAnalyseBase(selectedImport.exercice)
        setAnalyse(result.analyses[0] || null)
        setAnomalies(await listTableauAnomalies({ import_id: selectedImport.id, scope: 'base' }))
      } else {
        const result = await runTableauAnalyse(selectedImport.id)
        setAnalyse(result)
        await loadImportDetails(selectedImport.id)
      }
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de l\'enregistrement des réglages.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleExportTableau = async () => {
    if (!selectedImport) return
    setActionLoading('export-xlsx')
    setError(null)
    try {
      await downloadTableauExport(selectedImport.id, analysisScope)
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de l\'export du tableau.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleExport = () => {
    if (!selectedReport?.contenu) return
    const blob = new Blob([selectedReport.contenu], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedReport.titre.replace(/\s+/g, '_')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => { void loadAll() }, [])

  // Les règles en vigueur se lisent sur le serveur : les valeurs par défaut du
  // code ne disent pas ce qui gouverne l'exercice.
  useEffect(() => {
    if (!selectedImport) return
    let annule = false
    getTableauReglages(selectedImport.id)
      .then(valeurs => { if (!annule && valeurs) setReglages(valeurs) })
      .catch(() => undefined)
    return () => { annule = true }
  }, [selectedImport?.id])
  useEffect(() => { setDossierPage(1) }, [selectedImport?.id, dossierPageSize])

  // Le journal ne se charge qu'à l'ouverture de son écran : il n'entre dans
  // aucun autre calcul de la page.
  useEffect(() => {
    if (activeTab !== 'journal' || !canViewAudit) return
    let annule = false
    setJournalLoading(true)
    listTableauAudit({ limit: 100 })
      .then(entrees => { if (!annule) setJournal(entrees) })
      .catch(() => { if (!annule) setJournal([]) })
      .finally(() => { if (!annule) setJournalLoading(false) })
    return () => { annule = true }
  }, [activeTab, canViewAudit])

  const anomaliesHigh = anomalies.filter(a => a.gravite === 'high')
  const anomaliesMedium = anomalies.filter(a => a.gravite === 'medium')
  const anomaliesLow = anomalies.filter(a => a.gravite === 'low')

  useEffect(() => {
    if (activeTab !== 'base') return
    let annule = false
    setBaseLoading(true)
    setBaseError(null)
    getTableauBase({
      exercice: baseExerciceDiffere || undefined,
      national: baseNational,
      q: baseSearchDiffere || undefined,
      categorie: baseCategorie || undefined,
      organisationId: baseOrganisationId ? Number(baseOrganisationId) : undefined,
      limit: basePageSize,
      offset: (basePage - 1) * basePageSize,
    })
      .then(data => {
        if (annule) return
        // L'exercice trouvé n'est pas recopié dans le champ : il s'y verrait
        // comme une saisie, et relancerait aussitôt la même requête.
        setBase(data)
      })
      .catch((error: any) => {
        if (annule) return
        setBase(null)
        setBaseError(error?.message || 'Impossible de charger la base du Tableau.')
      })
      .finally(() => { if (!annule) setBaseLoading(false) })
    return () => { annule = true }
  }, [activeTab, baseNational, baseExerciceDiffere, baseSearchDiffere, baseCategorie, baseOrganisationId, basePage, basePageSize, baseRefresh])

  useEffect(() => {
    setBasePage(1)
  }, [baseNational, baseExerciceDiffere, baseSearchDiffere, baseCategorie, baseOrganisationId, basePageSize])

  const handleBaseAnalyse = async () => {
    if (!base?.exercice) return
    setActionLoading('analyse-base')
    setBaseAnalyse(null)
    try {
      const result = await runTableauAnalyseBase(base.exercice, baseNational)
      // Une analyse nationale n'est pas tout ou rien : on nomme les conseils
      // en échec plutôt que d'annoncer un succès global qui n'en est pas un.
      const echecs = result.resultats.filter(item => item.status === 'erreur')
      setBaseAnalyse([
        `${result.total_dossiers} membre(s) analysé(s) dans ${result.analyses_count} conseil(s).`,
        echecs.length
          ? `${echecs.length} conseil(s) en échec, sans effet sur les autres : ${echecs
              .map(item => `${item.organisation_nom || `#${item.organisation_id}`} (${item.detail || 'erreur'})`)
              .join(' ; ')}`
          : '',
      ].filter(Boolean).join(' '))
      if (!baseNational && result.analyses[0]) {
        setAnalyse(result.analyses[0])
        setAnalysisScope('base')
        const imp = imports.find(item => item.id === result.analyses[0].import_id)
        if (imp) {
          setSelectedImport(imp)
          const anomaliesData = await listTableauAnomalies({ import_id: imp.id, scope: 'base' })
          setAnomalies(anomaliesData)
        }
      }
      setBaseRefresh(value => value + 1)
      await getTableauStats().then(setStats)
    } catch (err) {
      setBaseAnalyse(apiErr(err, "L'analyse de la base a échoué."))
    } finally {
      setActionLoading(null)
    }
  }

  const openCorrection = (dossier: TableauDossier) => {
    setCorrectionDossier(dossier)
    setCorrectionForm({
      numero_ordre: dossier.numero_ordre || '',
      nom: dossier.nom,
      categorie: dossier.categorie,
      email: dossier.email || '',
      telephone: dossier.telephone || '',
      cotisation: '',
      assurance: '',
      motif: '',
    })
  }

  const handleCorrection = async () => {
    if (!correctionDossier || correctionForm.motif.trim().length < 3) return
    setActionLoading('correction')
    setBaseError(null)
    try {
      const changes: Record<string, unknown> = {}
      const clearFields: string[] = []
      for (const field of ['numero_ordre', 'nom', 'categorie', 'email', 'telephone'] as const) {
        const next = correctionForm[field].trim()
        const previous = String(correctionDossier[field] || '')
        if (!next && previous && (field === 'email' || field === 'telephone' || field === 'numero_ordre')) {
          clearFields.push(field)
        } else if (next !== previous) {
          changes[field] = next
        }
      }
      for (const [field, value] of [['cotisation_payee', correctionForm.cotisation], ['assurance', correctionForm.assurance]] as const) {
        if (value === 'clear') clearFields.push(field)
        else if (value === 'true' || value === 'false') changes[field] = value === 'true'
      }
      await correctTableauDossier(correctionDossier.id, {
        changes,
        clear_fields: clearFields,
        motif: correctionForm.motif.trim(),
      })
      setCorrectionDossier(null)
      setBaseRefresh(value => value + 1)
      // La correction rend l'analyse obsolète : on la relit pour l'annoncer,
      // plutôt que de la masquer comme si elle n'avait jamais existé.
      if (selectedImport) await loadImportDetails(selectedImport.id, analysisScope)
      await getTableauStats().then(s => s && setStats(s)).catch(() => undefined)
    } catch (err) {
      setBaseError(apiErr(err, 'La correction a échoué.'))
    } finally {
      setActionLoading(null)
    }
  }

  // Une analyse ne vaut que si elle est à jour : le backend refuse export, rapport
  // et PV dès qu'elle est marquée obsolète.
  const exercicesConnus = [...new Set(imports.map(item => item.exercice))]
  const analyseObsolete = analyse?.status === 'stale'
  const analysePrete = analyse?.status === 'completed'
  const categoriesCorrection = correctionDossier && correctionDossier.categorie
    && !(TABLEAU_CATEGORIES as readonly string[]).includes(correctionDossier.categorie)
    ? [correctionDossier.categorie, ...TABLEAU_CATEGORIES]
    : [...TABLEAU_CATEGORIES]
  const relancerAnalyse = canAnalyze && selectedImport
    ? () => void (analysisScope === 'base' ? handleBaseAnalyse() : handleAnalyse())
    : undefined
  const baseTotalPages = Math.max(1, Math.ceil((base?.total_membres || 0) / basePageSize))
  const baseImport = imports.find(item => item.id === base?.analysis_import_id) || null
  const dossierTotalPages = Math.max(1, Math.ceil(dossiers.length / dossierPageSize))
  const dossiersAffiches = dossiers.slice(
    (dossierPage - 1) * dossierPageSize,
    dossierPage * dossierPageSize,
  )
  const comparisonTotalPages = Math.max(1, Math.ceil((comparison?.details.length || 0) / comparisonPageSize))
  const comparisonDetailsAffiches = (comparison?.details || []).slice(
    (comparisonPage - 1) * comparisonPageSize,
    comparisonPage * comparisonPageSize,
  )

  return (
    <div className={styles.page}>
      {canUseAssistant && <TableauAssistantChat />}

      <div className={styles.controlPanel}>
        <div className={styles.topRow}>
          <div>
            <div className={styles.breadcrumb}>Tableau de l'Ordre</div>
            <h1 className={styles.title}>
              <span className={styles.iconBox}><Table2 size={19} /></span>
              {TITRES[activeTab]}
            </h1>
          </div>
          <div className={styles.actions}>
            <BackButton fallback="/tableau" />
            <button type="button" className={styles.secondaryButton} onClick={() => void loadAll()} disabled={loading}>
              <RefreshCw size={15} />
              Actualiser
            </button>
          </div>
        </div>

      </div>

      <div className={styles.content}>
        {error && (
          <div className={styles.errorBox} style={{ marginBottom: '16px' }}>
            <XCircle size={15} style={{ display: 'inline', marginRight: '6px' }} />
            {error}
          </div>
        )}

        {activeTab === 'dashboard' && (
          <section>
            <h2 className={styles.sectionTitle} style={{ marginBottom: '14px' }}>Vue d'ensemble Commission Tableau</h2>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '24px' }}>
              <StatCard value={stats?.dossiers_importes ?? 0} label="Membres dans la base" icon={<FileSpreadsheet size={18} />} />
              <StatCard value={stats?.dossiers_analyses ?? 0} label="Membres analysés" icon={<Bot size={18} />} />
              <StatCard
                value={stats?.dossiers_incomplets ?? '—'}
                label="Dossiers incomplets"
                icon={<AlertTriangle size={18} />}
                hint={stats?.dossiers_incomplets == null ? 'Analyse de base requise' : undefined}
              />
              <StatCard value={stats?.anomalies_detectees ?? 0} label="Anomalies détectées" icon={<XCircle size={18} />} />
              <StatCard value={stats?.decisions_a_valider ?? 0} label="Décisions enregistrées" icon={<CheckCircle2 size={18} />} />
            </div>

            {stats?.last_exercice && stats.analyse_base_status !== 'completed' && (
              <p style={{ fontSize: '12px', color: '#92400e', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: '6px', padding: '10px 12px', marginBottom: '20px' }}>
                {stats.analyse_base_status === 'stale'
                  ? `L'analyse de la base ${stats.last_exercice} est obsolète : les chiffres qui en dépendent datent d'avant le dernier changement.`
                  : `Aucune analyse de la base ${stats.last_exercice} : les chiffres qui en dépendent ne peuvent pas être établis.`}
                {canAnalyze ? ' Lancez-la depuis l\'onglet « Base Tableau ».' : ''}
              </p>
            )}

            <div className={styles.intro}>
              <section className={styles.panel}>
                <p className={styles.description}>
                  L'Agent Tableau assiste la Commission Tableau dans l'analyse des dossiers d'inscription,
                  de changement de catégorie, de conformité et de suivi des experts-comptables.
                  Importez un fichier Excel, lancez l'analyse réglementaire, détectez les anomalies et générez rapports et PV.
                </p>
              </section>
              <aside className={styles.statusPanel}>
                <span className={styles.statusLabel}>Exercice actif</span>
                <span className={styles.statusValue}>{stats?.last_exercice ?? 'Aucun import'}</span>
                <span className={styles.pill}>{stats?.imports_count ?? 0} import(s) chargé(s)</span>
              </aside>
            </div>

            <h2 className={styles.sectionTitle} style={{ margin: '20px 0 12px' }}>Actions rapides</h2>
            <div className={styles.grid}>
              {[
                { label: 'Actualisations', icon: <RefreshCw size={18} />, desc: 'Consulter les révisions matérialisées', tab: 'actualisations' as TabKey, visible: true },
                { label: 'Consulter la base', icon: <Layers size={18} />, desc: 'Voir la situation actuelle par membre', tab: 'base' as TabKey, visible: true },
                { label: 'Importer Excel', icon: <Upload size={18} />, desc: 'Actualiser le tableau des experts-comptables', tab: 'import' as TabKey, visible: canImport },
                { label: 'Analyse réglementaire', icon: <Bot size={18} />, desc: 'Calculer les conclusions et anomalies', tab: 'analyse' as TabKey, visible: canAnalyze },
                { label: 'Voir les anomalies', icon: <AlertTriangle size={18} />, desc: 'Consulter les anomalies détectées', tab: 'anomalies' as TabKey, visible: true },
                { label: 'Comparer exercices', icon: <GitCompare size={18} />, desc: 'Comparer deux bases consolidées', tab: 'comparaison' as TabKey, visible: canCompare },
                { label: 'Générer un rapport', icon: <FileText size={18} />, desc: 'Créer un rapport d\'analyse ou un PV', tab: 'rapports' as TabKey, visible: canReport || canGeneratePv },
              ].filter(action => action.visible).map(action => (
                <button
                  key={action.tab}
                  type="button"
                  className={styles.featureCard}
                  style={{ textAlign: 'left', display: 'block', width: '100%', border: '1px solid #e5e7eb', background: '#fff', cursor: 'pointer', borderRadius: '8px', padding: '16px' }}
                  onClick={() => setActiveTab(action.tab)}
                >
                  <div className={styles.featureHeader}>
                    {action.icon}
                    <span>{action.label}</span>
                  </div>
                  <p className={styles.featureText}>{action.desc}</p>
                  <span className={styles.pill}>Ouvrir →</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {activeTab === 'actualisations' && (
          <section className={styles.managerWorkspace}>
            <h2 className={styles.sectionTitle}>Actualisations du Tableau</h2>
            <p className={styles.sectionSubtitle}>Les révisions sont matérialisées par le backend et restent immuables.</p>
            <div style={{ overflowX: 'auto' }}>
              <table style={baseTableStyle}><thead><tr><th style={baseThStyle}>Situation</th><th style={baseThStyle}>Révision</th><th style={baseThStyle}>Actualisée le</th><th style={baseThStyle}>Lignes</th><th style={baseThStyle}>Statut</th></tr></thead>
                <tbody>{actualisations.map(a => <tr key={a.id}><td style={baseTdStyle}>{a.date_situation}</td><td style={baseTdStyle}>#{a.revision_number}{a.is_current && <span className={styles.pill} style={{ marginLeft: 8 }}>Courante</span>}</td><td style={baseTdStyle}>{new Date(a.actualized_at).toLocaleString()}</td><td style={baseTdStyle}>{a.total_rows}</td><td style={baseTdStyle}>{a.status}</td></tr>)}</tbody>
              </table>
              {!actualisations.length && <div className={styles.emptyBox}>Aucune actualisation disponible.</div>}
            </div>
          </section>
        )}

        {activeTab === 'base' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Base Tableau</h2>
                <p className={styles.sectionSubtitle}>
                  La situation qui fait foi pour chaque membre, tous imports de l'exercice confondus.
                  Réimporter un fichier plus ancien ne fait pas reculer la base.
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                {canAnalyze && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={baseLoading || actionLoading === 'analyse-base' || !base || base.total_membres === 0}
                    onClick={() => void handleBaseAnalyse()}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                  >
                    <Bot size={15} />
                    {actionLoading === 'analyse-base' ? 'Analyse...' : 'Analyser la base'}
                  </button>
                )}
                {canExport && !baseNational && baseImport && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={actionLoading === 'export-base'}
                    onClick={() => {
                      setActionLoading('export-base')
                      downloadTableauExport(baseImport.id, 'base')
                        .catch(err => setBaseError(apiErr(err, "L'export de la base a échoué.")))
                        .finally(() => setActionLoading(null))
                    }}
                  >
                    <Download size={15} />
                    Exporter la base
                  </button>
                )}
                {canNational && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151' }}>
                    <input
                      type="checkbox"
                      checked={baseNational}
                      onChange={(event) => {
                        setBaseNational(event.target.checked)
                        setBaseOrganisationId('')
                      }}
                      disabled={baseLoading}
                    />
                    Tous les conseils
                  </label>
                )}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', padding: '0 14px' }}>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Recherche
                <span style={{ position: 'relative' }}>
                  <Search size={14} style={{ position: 'absolute', left: '9px', top: '9px', color: '#6b7280' }} />
                  <input
                    value={baseSearch}
                    onChange={event => setBaseSearch(event.target.value)}
                    placeholder="N° d'ordre, nom, e-mail, NIF ou cabinet"
                    style={{ width: '100%', padding: '7px 9px 7px 30px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  />
                </span>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Exercice
                <input
                  value={baseExercice}
                  onChange={event => setBaseExercice(event.target.value)}
                  placeholder={base?.exercice ? `${base.exercice} (le plus récent)` : '2026'}
                  title="Laissé vide, l'exercice le plus récent est utilisé."
                  style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px', width: '120px' }}
                />
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Catégorie
                <select value={baseCategorie} onChange={event => setBaseCategorie(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Toutes</option>
                  {TABLEAU_CATEGORIES.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              {baseNational && (
                <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                  Conseil
                  <select value={baseOrganisationId} onChange={event => setBaseOrganisationId(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                    <option value="">Tous</option>
                    {(base?.organisation_options || []).map(item => <option key={item.id} value={item.id}>{item.nom}</option>)}
                  </select>
                </label>
              )}
            </div>

            {baseAnalyse && (
              <div className={styles.resultSummary} style={{ marginBottom: '12px' }}>
                <p style={{ fontSize: '13px' }}>{baseAnalyse}</p>
              </div>
            )}

            {baseError ? (
              <div className={styles.emptyBox}>{baseError}</div>
            ) : baseLoading ? (
              <div className={styles.emptyBox}>Chargement de la base...</div>
            ) : !base || base.dossiers.length === 0 ? (
              <div className={styles.emptyBox}>
                Aucun import pour l'instant. Chargez un fichier depuis l'onglet « Import Excel ».
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={base.total_membres} label={`Membres - exercice ${base.exercice}`} icon={<Table2 size={18} />} />
                  <StatCard value={base.imports_couverts.length} label="Imports consolidés" icon={<Layers size={18} />} />
                  <StatCard value={base.membres_sans_numero} label="Sans n° d'ordre" icon={<AlertTriangle size={18} />} />
                  {base.national && (
                    <StatCard value={base.organisations.length} label="Conseils" icon={<BarChart2 size={18} />} />
                  )}
                </div>

                <div style={{ overflowX: 'auto' }}>
                  <table style={baseTableStyle}>
                    <thead>
                      <tr>
                        <th style={baseThStyle}>N° d'ordre</th>
                        <th style={baseThStyle}>Nom</th>
                        {base.national && <th style={baseThStyle}>Conseil</th>}
                        <th style={baseThStyle}>Catégorie</th>
                        <th style={baseThStyle}>Ancienneté</th>
                        <th style={baseThStyle}>Heures</th>
                        <th style={baseThStyle}>Cotisation</th>
                        <th style={baseThStyle}>Assurance</th>
                        <th style={baseThStyle}>Conclusion</th>
                        <th style={baseThStyle}>Situation</th>
                        {canCorrect && !baseNational && <th style={baseThStyle}>Action</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {base.dossiers.map(dossier => (
                        <tr key={dossier.id}>
                          <td style={baseTdStyle}>
                            {dossier.numero_ordre || <span style={{ color: '#b91c1c' }}>à compléter</span>}
                          </td>
                          <td style={baseTdStyle}>{dossier.nom}</td>
                          {base.national && <td style={baseTdStyle}>{dossier.organisation_nom || `#${dossier.organisation_id}`}</td>}
                          <td style={baseTdStyle}>{dossier.categorie || '—'}</td>
                          <td style={baseTdStyle}>
                            {dossier.anciennete_annees != null ? `${dossier.anciennete_annees} an(s)` : '—'}
                          </td>
                          <td style={baseTdStyle}>{dossier.heures_forco ?? '—'}</td>
                          <td style={baseTdStyle}>{booleanStatus(dossier.cotisation_payee)}</td>
                          <td style={baseTdStyle}>{booleanStatus(dossier.assurance)}</td>
                          <td style={baseTdStyle}>{dossier.conclusion || 'À analyser'}</td>
                          <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }} title={dossier.source_file_name || undefined}>
                            {dossier.date_situation ? new Date(`${dossier.date_situation}T00:00:00`).toLocaleDateString('fr-FR') : '—'}
                          </td>
                          {canCorrect && !baseNational && (
                            <td style={baseTdStyle}>
                              <button type="button" className={styles.secondaryButton} onClick={() => openCorrection(dossier)} title="Corriger le dossier" aria-label={`Corriger ${dossier.nom}`}>
                                <Pencil size={14} />
                              </button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '0 14px' }}>
                  <label style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    Lignes
                    <select value={basePageSize} onChange={event => setBasePageSize(Number(event.target.value))}>
                      {[25, 50, 100, 200].map(size => <option key={size} value={size}>{size}</option>)}
                    </select>
                  </label>
                  <span style={{ fontSize: '12px', color: '#6b7280' }}>
                    Page {Math.min(basePage, baseTotalPages)} sur {baseTotalPages}
                  </span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button type="button" className={styles.secondaryButton} disabled={basePage <= 1 || baseLoading} onClick={() => setBasePage(page => Math.max(1, page - 1))} title="Page précédente">
                      <ChevronLeft size={15} />
                    </button>
                    <button type="button" className={styles.secondaryButton} disabled={basePage >= baseTotalPages || baseLoading} onClick={() => setBasePage(page => page + 1)} title="Page suivante">
                      <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </>
            )}
          </section>
        )}

        {activeTab === 'import' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Import Excel</h2>
                <p className={styles.sectionSubtitle}>Importez le fichier Excel du tableau des experts-comptables (.xlsx ou .xls).</p>
              </div>
            </div>

            <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '20px', marginBottom: '20px' }}>
              <div style={{ marginBottom: '16px' }}>
                <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
                  Exercice (année)
                </label>
                <input
                  value={exercice}
                  onChange={e => setExercice(e.target.value)}
                  placeholder="ex : 2026"
                  style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '14px', width: '120px' }}
                />
              </div>
              <Suspense fallback={null}>
                <ImportTableauDossiers exercice={exercice} onImported={(id) => void handleImported(id)} />
              </Suspense>
            </div>

            {imports.length > 0 && (
              <>
                <h3 style={{ fontSize: '14px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>Imports précédents</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {imports.map(imp => (
                    <div
                      key={imp.id}
                      onClick={() => void handleSelectImport(imp)}
                      style={{
                        background: selectedImport?.id === imp.id ? '#f5f0f5' : '#fff',
                        border: `1px solid ${selectedImport?.id === imp.id ? 'var(--tenant-primary, #714b67)' : '#e5e7eb'}`,
                        borderRadius: '6px',
                        padding: '12px 16px',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '10px',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: '600', fontSize: '13px' }}>{imp.file_name}</div>
                        <div style={{ fontSize: '12px', color: '#6b7280' }}>
                          Exercice {imp.exercice} · situation du {new Date(`${imp.date_situation}T00:00:00`).toLocaleDateString('fr-FR')} · {imp.imported_rows} dossiers
                        </div>
                        {imp.error_message && (
                          <div style={{ fontSize: '12px', color: '#dc2626', marginTop: '2px' }}>{imp.error_message}</div>
                        )}
                      </div>
                      <span className={styles.pill} style={{
                        background: imp.status === 'completed' ? '#d1fae5' : imp.status === 'error' ? '#fee2e2' : '#fef3c7',
                        color: imp.status === 'completed' ? '#065f46' : imp.status === 'error' ? '#991b1b' : '#92400e',
                      }}>
                        {imp.status}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {selectedImport && dossiers.length > 0 && (
              <div style={{ marginTop: '20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <h3 style={{ fontSize: '14px', fontWeight: '600', color: '#374151' }}>
                    Dossiers — {selectedImport.exercice} ({dossiers.length})
                  </h3>
                  {canAnalyze && <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAnalyse()}
                    disabled={actionLoading === 'analyse'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                  >
                    <Bot size={15} />
                    {actionLoading === 'analyse' ? 'Analyse...' : 'Analyser cet import'}
                  </button>
                  }
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                        {['N°', 'N° ordre', 'Nom', 'Prénom', 'Catégorie', 'Cotisation', 'Formation (h)', 'Assurance', 'Conclusion'].map(h => (
                          <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontWeight: '600', color: '#374151', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dossiersAffiches.map((d, i) => {
                        const isSociete = d.categorie === 'Société' || d.categorie === 'SEC'
                        const concl = d.conclusion || d.statut_dossier
                        const conclColor =
                          concl === 'INSCRIT' ? { bg: '#d1fae5', fg: '#065f46' }
                          : concl === 'NON INSCRIT' ? { bg: '#fee2e2', fg: '#991b1b' }
                          : concl === 'À DÉLIBÉRER' ? { bg: '#fef3c7', fg: '#92400e' }
                          : { bg: '#f3f4f6', fg: '#374151' }
                        return (
                        <tr key={d.id} style={{
                          borderBottom: '1px solid #f3f4f6',
                          background: d.anomalie_detectee ? '#fff7ed' : '#fff',
                        }}>
                          <td style={{ padding: '7px 10px', color: '#6b7280', fontWeight: '600' }}>
                            {(dossierPage - 1) * dossierPageSize + i + 1}
                          </td>
                          <td style={{ padding: '7px 10px', color: '#6b7280' }}>{d.numero_ordre ?? '—'}</td>
                          <td style={{ padding: '7px 10px', fontWeight: '500' }}>{d.nom}</td>
                          <td style={{ padding: '7px 10px' }}>{d.prenom ?? '—'}</td>
                          <td style={{ padding: '7px 10px' }}>{d.categorie}</td>
                          <td style={{ padding: '7px 10px' }}>
                            {d.cotisation_payee === true ? <CheckCircle2 size={13} color="#16a34a" /> : d.cotisation_payee === false ? <XCircle size={13} color="#dc2626" /> : '—'}
                          </td>
                          <td style={{ padding: '7px 10px', color: isSociete ? '#9ca3af' : 'inherit' }}>
                            {isSociete ? 'N/A' : (d.heures_forco !== null ? d.heures_forco : '—')}
                          </td>
                          <td style={{ padding: '7px 10px' }}>
                            {d.assurance === true ? <CheckCircle2 size={13} color="#16a34a" /> : d.assurance === false ? <XCircle size={13} color="#dc2626" /> : '—'}
                          </td>
                          <td style={{ padding: '7px 10px' }}>
                            <span className={styles.pill} style={{
                              background: conclColor.bg,
                              color: conclColor.fg,
                              fontSize: '11px',
                            }}>
                              {concl}
                            </span>
                          </td>
                        </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginTop: '10px' }}>
                  <label style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    Lignes
                    <select value={dossierPageSize} onChange={event => setDossierPageSize(Number(event.target.value))}>
                      {[25, 50, 100, 200].map(size => <option key={size} value={size}>{size}</option>)}
                    </select>
                  </label>
                  <span style={{ fontSize: '12px', color: '#6b7280' }}>
                    Page {Math.min(dossierPage, dossierTotalPages)} sur {dossierTotalPages}
                  </span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button type="button" className={styles.secondaryButton} disabled={dossierPage <= 1} onClick={() => setDossierPage(page => Math.max(1, page - 1))} title="Page précédente">
                      <ChevronLeft size={15} />
                    </button>
                    <button type="button" className={styles.secondaryButton} disabled={dossierPage >= dossierTotalPages} onClick={() => setDossierPage(page => page + 1)} title="Page suivante">
                      <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {activeTab === 'analyse' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Analyse réglementaire</h2>
                <p className={styles.sectionSubtitle}>Calcul déterministe des conclusions, anomalies et statistiques de conformité.</p>
              </div>
              {selectedImport && canAnalyze && (
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={() => void (analysisScope === 'base' ? handleBaseAnalyse() : handleAnalyse())}
                  disabled={actionLoading === 'analyse'}
                  style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                >
                  <Bot size={15} />
                  {actionLoading === 'analyse' ? 'Analyse en cours...' : 'Relancer l\'analyse'}
                </button>
              )}
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {!selectedImport ? (
              <div className={styles.emptyBox}>
                Aucun import sélectionné. Allez dans l'onglet "Import Excel" pour charger un fichier.
              </div>
            ) : analyse ? (
              <div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={analyse.total_dossiers} label="Total dossiers" icon={<FileSpreadsheet size={18} />} />
                  <StatCard value={analyse.dossiers_complets} label="Dossiers complets" icon={<CheckCircle2 size={18} />} />
                  <StatCard value={analyse.dossiers_incomplets} label="Incomplets" icon={<AlertTriangle size={18} />} />
                  <StatCard value={analyse.anomalies_count} label="Anomalies" icon={<XCircle size={18} />} />
                  <StatCard value={analyse.doublons_count} label="Doublons" icon={<GitCompare size={18} />} />
                  <StatCard value={analyse.cotisations_non_payees} label="Cotis. non payées" icon={<XCircle size={18} />} />
                  <StatCard value={analyse.heures_forco_insuffisantes} label="FORCO insuff." icon={<AlertTriangle size={18} />} />
                  <StatCard value={analyse.assurances_manquantes} label="Assurances manq." icon={<XCircle size={18} />} />
                </div>

                {!!(analyse.stats_json?.categories) && (
                  <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '16px' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>Répartition par catégorie</h3>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {Object.entries(analyse.stats_json.categories as Record<string, number>).map(([cat, cnt]: [string, number]) => (
                        <div key={cat} style={{ background: '#f5f0f5', borderRadius: '6px', padding: '8px 14px', fontSize: '13px' }}>
                          <span style={{ fontWeight: '600' }}>{cat}</span>
                          <span style={{ color: 'var(--tenant-primary, #714b67)', fontWeight: '700', marginLeft: '8px' }}>{cnt}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!!(analyse.stats_json?.conclusions) && (() => {
                  const c = analyse.stats_json.conclusions as Record<string, number>
                  const pills: Array<[string, number, string]> = [
                    ['INSCRIT', c.inscrits || 0, '#16a34a'],
                    ['NON INSCRIT', c.non_inscrits || 0, '#dc2626'],
                    ['À DÉLIBÉRER', c.a_deliberer || 0, '#d97706'],
                    ['N/A', c.non_applicable || 0, '#6b7280'],
                  ]
                  return (
                    <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '16px' }}>
                      <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>Conclusions (verdict réglementaire)</h3>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        {pills.map(([label, cnt, color]) => (
                          <div key={label} style={{ borderLeft: `4px solid ${color}`, background: '#f9fafb', borderRadius: '6px', padding: '8px 14px', fontSize: '13px' }}>
                            <span style={{ fontWeight: '600' }}>{label}</span>
                            <span style={{ color, fontWeight: '700', marginLeft: '8px' }}>{cnt}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })()}

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '16px' }}>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
                      Titre du rapport (optionnel)
                    </label>
                    <input
                      value={reportTitle}
                      onChange={e => setReportTitle(e.target.value)}
                      placeholder={`Rapport Tableau ${selectedImport.exercice}`}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '280px' }}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
                      Instructions complémentaires
                    </label>
                    <input
                      value={reportInstructions}
                      onChange={e => setReportInstructions(e.target.value)}
                      placeholder="Observations ou points particuliers à inclure…"
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%' }}
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
                  {canReport && <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGenerateReport()}
                    disabled={actionLoading === 'report' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                  }
                  {canExport && <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleExportTableau()}
                    disabled={actionLoading === 'export-xlsx' || !analysePrete}
                    style={{ background: '#16a34a', color: '#fff', borderColor: '#16a34a' }}
                  >
                    <Download size={15} />
                    {actionLoading === 'export-xlsx' ? 'Export...' : 'Exporter le tableau (.xlsx)'}
                  </button>
                  }
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => setActiveTab('anomalies')}
                  >
                    <AlertTriangle size={15} />
                    Voir les anomalies ({analyse.anomalies_count})
                  </button>
                </div>
              </div>
            ) : (
              <div className={styles.emptyBox}>
                <Bot size={32} style={{ opacity: 0.3, marginBottom: '8px' }} />
                <p>Aucune analyse disponible pour cet import.</p>
                {selectedImport && canAnalyze && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAnalyse()}
                    disabled={actionLoading === 'analyse'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', marginTop: '8px' }}
                  >
                    <Bot size={15} />
                    Lancer l'analyse réglementaire
                  </button>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === 'anomalies' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Anomalies détectées</h2>
                <p className={styles.sectionSubtitle}>
                  {anomalies.length} anomalie(s) pour {analysisScope === 'base' ? 'la base consolidée' : "l'import sélectionné"}.
                  {anomaliesHigh.length > 0 && ` ${anomaliesHigh.length} critique(s).`}
                </p>
              </div>
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {anomalies.length === 0 ? (
              <div className={styles.emptyBox}>
                {selectedImport ? 'Aucune anomalie détectée. Lancez d\'abord l\'analyse réglementaire.' : 'Sélectionnez un import.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {[
                  { list: anomaliesHigh, label: 'Anomalies critiques', color: '#dc2626', bg: '#fee2e2' },
                  { list: anomaliesMedium, label: 'Anomalies importantes', color: '#d97706', bg: '#fef3c7' },
                  { list: anomaliesLow, label: 'Anomalies mineures', color: '#2563eb', bg: '#dbeafe' },
                ].filter(g => g.list.length > 0).map(group => (
                  <div key={group.label}>
                    <h3 style={{ fontSize: '13px', fontWeight: '600', color: group.color, marginBottom: '8px', marginTop: '12px' }}>
                      {group.label} ({group.list.length})
                    </h3>
                    {group.list.map(a => (
                      <div
                        key={a.id}
                        style={{
                          background: group.bg,
                          border: `1px solid ${group.color}30`,
                          borderLeft: `3px solid ${group.color}`,
                          borderRadius: '6px',
                          padding: '10px 14px',
                          marginBottom: '6px',
                          fontSize: '13px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                          <div>
                            <span style={{ fontWeight: '600', color: group.color }}>[{a.type_anomalie}]</span>
                            <span style={{ marginLeft: '8px' }}>{a.description}</span>
                          </div>
                          <span style={{ fontSize: '11px', color: '#9ca3af', whiteSpace: 'nowrap' }}>
                            Dossier #{a.dossier_id}
                          </span>
                        </div>
                        {(a.valeur_trouvee !== null || a.valeur_attendue !== null) && (
                          <div style={{ marginTop: '4px', fontSize: '12px', color: '#4b5563' }}>
                            {a.champ_concerne && <span style={{ marginRight: '8px' }}>Champ : <strong>{a.champ_concerne}</strong></span>}
                            {a.valeur_trouvee !== null && <span style={{ marginRight: '8px' }}>Valeur trouvée : <strong>{String(a.valeur_trouvee)}</strong></span>}
                            {a.valeur_attendue !== null && <span>Attendu : <strong>{String(a.valeur_attendue)}</strong></span>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {activeTab === 'comparaison' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Comparaison d'exercices</h2>
                <p className={styles.sectionSubtitle}>Analysez les évolutions entre deux tableaux annuels.</p>
              </div>
            </div>

            <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '20px', marginBottom: '20px' }}>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div>
                  <label style={{ fontSize: '12px', fontWeight: '600', display: 'block', marginBottom: '4px' }}>Exercice A</label>
                  <input
                    value={compareExerciceA}
                    onChange={e => setCompareExerciceA(e.target.value)}
                    placeholder="ex : 2025"
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '14px', width: '100px' }}
                  />
                </div>
                <span style={{ paddingBottom: '8px', color: '#9ca3af' }}>vs</span>
                <div>
                  <label style={{ fontSize: '12px', fontWeight: '600', display: 'block', marginBottom: '4px' }}>Exercice B</label>
                  <input
                    value={compareExerciceB}
                    onChange={e => setCompareExerciceB(e.target.value)}
                    placeholder="ex : 2026"
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '14px', width: '100px' }}
                  />
                </div>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={() => void handleCompare()}
                  disabled={actionLoading === 'compare'}
                  style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                >
                  <GitCompare size={15} />
                  {actionLoading === 'compare' ? 'Comparaison...' : 'Comparer'}
                </button>
              </div>
            </div>

            {comparison && (
              <div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={comparison.dossiers_en_commun} label="Dossiers communs" icon={<CheckCircle2 size={18} />} />
                  <StatCard value={comparison.nouveaux_dans_b} label={`Nouveaux en ${comparison.exercice_b}`} icon={<FileSpreadsheet size={18} />} />
                  <StatCard value={comparison.absents_de_b} label={`Absents de ${comparison.exercice_b}`} icon={<XCircle size={18} />} />
                  <StatCard value={comparison.changements_categorie} label="Changements de catégorie" icon={<GitCompare size={18} />} />
                </div>

                {comparison.details.length > 0 && (
                  <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', overflow: 'hidden' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                      <thead>
                        <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Type</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Nom</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Catégorie</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Détail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {comparisonDetailsAffiches.map((d, i) => (
                          <tr key={`${String(d.type)}-${String(d.numero_ordre ?? d.nom ?? '')}-${i}`} style={{ borderBottom: '1px solid #f3f4f6' }}>
                            <td style={{ padding: '8px 12px' }}>
                              <span className={styles.pill} style={{
                                background: d.type === 'nouveau' ? '#d1fae5' : d.type === 'absent' ? '#fee2e2' : '#fef3c7',
                                color: d.type === 'nouveau' ? '#065f46' : d.type === 'absent' ? '#991b1b' : '#92400e',
                                fontSize: '11px',
                              }}>
                                {d.type === 'nouveau' ? 'Nouveau' : d.type === 'absent' ? 'Absent' : 'Changement'}
                              </span>
                            </td>
                            <td style={{ padding: '8px 12px', fontWeight: '500' }}>{String(d.nom ?? '')} {String(d.prenom ?? '')}</td>
                            <td style={{ padding: '8px 12px' }}>{String(d.categorie ?? d.categorie_apres ?? '—')}</td>
                            <td style={{ padding: '8px 12px', fontSize: '12px', color: '#6b7280' }}>
                              {d.type === 'changement_categorie'
                                ? `${String(d.categorie_avant)} → ${String(d.categorie_apres)}`
                                : String(d.exercice ?? '')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid #e5e7eb', flexWrap: 'wrap' }}>
                      <select value={comparisonPageSize} onChange={event => { setComparisonPageSize(Number(event.target.value)); setComparisonPage(1) }}>
                        <option value={25}>25 par page</option>
                        <option value={50}>50 par page</option>
                        <option value={100}>100 par page</option>
                      </select>
                      <span style={{ fontSize: '12px', color: '#6b7280' }}>
                        Page {Math.min(comparisonPage, comparisonTotalPages)} sur {comparisonTotalPages}
                      </span>
                      <button type="button" className={styles.secondaryButton} disabled={comparisonPage <= 1} onClick={() => setComparisonPage(page => Math.max(1, page - 1))} title="Page précédente">
                        <ChevronLeft size={15} />
                      </button>
                      <button type="button" className={styles.secondaryButton} disabled={comparisonPage >= comparisonTotalPages} onClick={() => setComparisonPage(page => page + 1)} title="Page suivante">
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === 'rapports' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Rapports & Procès-verbaux</h2>
                <p className={styles.sectionSubtitle}>Générer et consulter les rapports d'analyse et les PV de la Commission Tableau.</p>
              </div>
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {selectedImport && !analyse && (canReport || canGeneratePv) && (
              <p style={{ fontSize: '13px', color: '#6b7280', marginBottom: '16px' }}>
                Aucune analyse enregistrée pour ce périmètre : lancez-la depuis l'onglet
                « Analyse réglementaire » avant de générer un rapport ou un procès-verbal.
              </p>
            )}

            {selectedImport && (canReport || canGeneratePv) && (
              <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '20px' }}>
                {canReport && <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
                  <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '12px' }}>Générer un rapport d'analyse</h3>
                  <input
                    value={reportTitle}
                    onChange={e => setReportTitle(e.target.value)}
                    placeholder={`Rapport Tableau ${selectedImport.exercice}`}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', marginBottom: '8px' }}
                  />
                  <textarea
                    value={reportInstructions}
                    onChange={e => setReportInstructions(e.target.value)}
                    placeholder="Instructions complémentaires…"
                    rows={2}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', resize: 'vertical', marginBottom: '8px' }}
                  />
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGenerateReport()}
                    disabled={actionLoading === 'report' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                </div>}

                {canGeneratePv && <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
                  <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '12px' }}>Générer un procès-verbal</h3>
                  <textarea
                    value={pvInstructions}
                    onChange={e => setPvInstructions(e.target.value)}
                    placeholder="Observations à intégrer dans le PV…"
                    rows={4}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', resize: 'vertical', marginBottom: '8px' }}
                  />
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGeneratePV()}
                    disabled={actionLoading === 'pv' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'pv' ? 'Génération...' : 'Générer le PV'}
                  </button>
                </div>}
              </div>
            )}

            <div style={{ display: 'flex', gap: '16px' }}>
              <div style={{ width: '260px', flexShrink: 0 }}>
                <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '8px' }}>Rapports générés ({reports.length})</h3>
                {reports.length === 0 ? (
                  <div className={styles.emptyBox} style={{ padding: '16px' }}>Aucun rapport.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {reports.map(r => (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => setSelectedReport(r)}
                        style={{
                          background: selectedReport?.id === r.id ? '#f5f0f5' : '#fff',
                          border: `1px solid ${selectedReport?.id === r.id ? 'var(--tenant-primary, #714b67)' : '#e5e7eb'}`,
                          borderRadius: '6px',
                          padding: '10px 12px',
                          cursor: 'pointer',
                          textAlign: 'left',
                          width: '100%',
                        }}
                      >
                        <div style={{ fontSize: '12px', fontWeight: '600', color: '#1f2933' }}>{r.titre}</div>
                        <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '2px' }}>
                          {r.type_rapport} · {r.exercice} · {new Date(r.created_at).toLocaleDateString('fr-FR')}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {selectedReport && (
                <div style={{ flex: 1, background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '14px', fontWeight: '600' }}>{selectedReport.titre}</h3>
                    {selectedReport.contenu && (
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={handleExport}
                      >
                        Exporter .txt
                      </button>
                    )}
                  </div>
                  <pre style={{
                    fontFamily: 'monospace',
                    fontSize: '12px',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: '#1f2933',
                    background: '#f9fafb',
                    borderRadius: '6px',
                    padding: '16px',
                    maxHeight: '500px',
                    overflowY: 'auto',
                    lineHeight: '1.6',
                  }}>
                    {selectedReport.contenu ?? 'Contenu non disponible.'}
                  </pre>
                </div>
              )}
            </div>
          </section>
        )}

        {activeTab === 'journal' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Journal des actions</h2>
                <p className={styles.sectionSubtitle}>
                  Ce que le module a enregistré : corrections, décisions et questions posées à
                  l'assistant. Les 100 entrées les plus récentes.
                </p>
              </div>
            </div>

            {journalLoading ? (
              <div className={styles.emptyBox}>Chargement du journal…</div>
            ) : journal.length === 0 ? (
              <div className={styles.emptyBox}>Aucune action enregistrée pour ce conseil.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr>
                      <th style={baseThStyle}>Date</th>
                      <th style={baseThStyle}>Action</th>
                      <th style={baseThStyle}>Cible</th>
                      <th style={baseThStyle}>Détail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journal.map(entree => (
                      <tr key={entree.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                        <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }}>
                          {new Date(entree.created_at).toLocaleString('fr-FR')}
                        </td>
                        <td style={baseTdStyle}>{LIBELLES_AUDIT[entree.action] || entree.action}</td>
                        <td style={baseTdStyle}>
                          {entree.target_type ? `${entree.target_type}${entree.target_id ? ` #${entree.target_id}` : ''}` : '—'}
                        </td>
                        <td style={{ ...baseTdStyle, color: '#6b7280' }}>{resumerAudit(entree)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {activeTab === 'reglages' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Règles de délibération</h2>
                <p className={styles.sectionSubtitle}>
                  Ces règles décident des conclusions : elles valent pour tout l'exercice choisi,
                  quel que soit le fichier par lequel la situation est arrivée.
                </p>
              </div>
            </div>

            {exercicesConnus.length === 0 ? (
              <div className={styles.emptyBox}>
                Aucun import : les règles s'appliquent à un exercice, il faut donc en charger un d'abord.
              </div>
            ) : (
              <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
                <label style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600, maxWidth: '260px', marginBottom: '16px' }}>
                  Exercice concerné
                  <select
                    value={selectedImport?.exercice || ''}
                    onChange={event => {
                      const imp = imports.find(item => item.exercice === event.target.value)
                      if (imp) void handleSelectImport(imp)
                    }}
                    style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  >
                    {exercicesConnus.map(ex => <option key={ex} value={ex}>{ex}</option>)}
                  </select>
                </label>

                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Heures de formation min.</label>
                    <input type="number" min={0} value={reglages.heures_formation_min ?? 120}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, heures_formation_min: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Seuil d'âge (exemption)</label>
                    <input type="number" min={0} value={reglages.age_seuil ?? 60}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, age_seuil: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Au-delà du seuil d'âge</label>
                    <select value={reglages.age_action ?? 'a_deliberer'}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, age_action: e.target.value as TableauReglages['age_action'] }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '220px' }}>
                      <option value="a_deliberer">Marquer « À DÉLIBÉRER »</option>
                      <option value="inscrit">Valider directement (INSCRIT)</option>
                      <option value="aucune">Ne rien changer (soumis au minimum d'heures)</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Ancienneté « nouveau membre » (ans)</label>
                    <input type="number" min={1} value={reglages.nouveau_anciennete_ans ?? 3}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, nouveau_anciennete_ans: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151', alignSelf: 'flex-end', paddingBottom: '8px' }}>
                    <input type="checkbox" checked={reglages.exempter_nouveaux ?? true}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, exempter_nouveaux: e.target.checked }))} />
                    Exempter les nouveaux membres de formation
                  </label>
                </div>

                <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '14px' }}>
                  Enregistrer relance l'analyse du périmètre en cours : les conclusions déjà
                  calculées seraient sinon celles des anciennes règles.
                </p>

                {canSettings && (
                  <button type="button" className={styles.secondaryButton}
                    onClick={() => void handleSaveReglages()}
                    disabled={actionLoading === 'reglages' || !selectedImport}
                    style={{ marginTop: '8px', background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}>
                    <Settings size={15} />
                    {actionLoading === 'reglages' ? 'Application...' : 'Enregistrer et recalculer'}
                  </button>
                )}
              </div>
            )}
          </section>
        )}
      </div>

      {correctionDossier && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="tableau-correction-title"
          style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
          onMouseDown={event => { if (event.target === event.currentTarget) setCorrectionDossier(null) }}
        >
          <div style={{ width: 'min(620px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 id="tableau-correction-title" className={styles.sectionTitle}>Corriger le dossier</h2>
                <p className={styles.sectionSubtitle}>{correctionDossier.nom} · exercice {correctionDossier.exercice}</p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => setCorrectionDossier(null)} title="Fermer" aria-label="Fermer">
                <X size={16} />
              </button>
            </div>
            <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '12px' }}>
              {([
                ['numero_ordre', "N° d'ordre"],
                ['nom', 'Nom'],
                ['email', 'E-mail'],
                ['telephone', 'Téléphone'],
              ] as const).map(([field, label]) => (
                <label key={field} style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                  {label}
                  <input
                    value={correctionForm[field]}
                    onChange={event => setCorrectionForm(current => ({ ...current, [field]: event.target.value }))}
                    style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  />
                </label>
              ))}
              <label style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                Catégorie
                <select value={correctionForm.categorie} onChange={event => setCorrectionForm(current => ({ ...current, categorie: event.target.value }))} style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  {categoriesCorrection.map(item => (
                    <option key={item} value={item}>
                      {(TABLEAU_CATEGORIES as readonly string[]).includes(item) ? item : `${item} (valeur actuelle)`}
                    </option>
                  ))}
                </select>
              </label>
              {([
                ['cotisation', 'Cotisation'],
                ['assurance', 'Assurance'],
              ] as const).map(([field, label]) => (
                <label key={field} style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                  {label}
                  <select value={correctionForm[field]} onChange={event => setCorrectionForm(current => ({ ...current, [field]: event.target.value }))} style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                    <option value="">Conserver la valeur actuelle</option>
                    <option value="true">Oui</option>
                    <option value="false">Non</option>
                    <option value="clear">Effacer la valeur</option>
                  </select>
                </label>
              ))}
              <label style={{ gridColumn: '1 / -1', display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                Motif de la correction
                <textarea
                  value={correctionForm.motif}
                  onChange={event => setCorrectionForm(current => ({ ...current, motif: event.target.value }))}
                  rows={3}
                  maxLength={500}
                  required
                  style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px', resize: 'vertical' }}
                />
              </label>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '0 16px 16px' }}>
              <button type="button" className={styles.secondaryButton} onClick={() => setCorrectionDossier(null)}>Annuler</button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={actionLoading === 'correction' || correctionForm.motif.trim().length < 3}
                onClick={() => void handleCorrection()}
                style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
              >
                <Save size={15} />
                {actionLoading === 'correction' ? 'Enregistrement...' : 'Enregistrer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
