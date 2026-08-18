import { useEffect, useState, lazy, Suspense } from 'react'
import { AlertTriangle, BarChart2, Bot, CheckCircle2, Download, FileSpreadsheet, FileText, GitCompare, RefreshCw, Settings, Table2, Upload, XCircle } from 'lucide-react'
import SecretariatAgentChat from '../components/SecretariatAgentChat'
// xlsx est lourd : chargement dynamique seulement quand l'onglet "import" est actif.
const ImportTableauDossiers = lazy(() => import('../components/ImportTableauDossiers'))
import BackButton from '../components/BackButton'
import { ApiError } from '../lib/apiClient'
import {
  compareTableauExercices,
  generateTableauPV,
  generateTableauReport,
  getTableauStats,
  listTableauAnomalies,
  listTableauDossiers,
  listTableauImports,
  listTableauReports,
  runTableauAnalyse,
  updateTableauReglages,
  downloadTableauExport,
  type TableauReglages,
  type TableauAnalyse,
  type TableauAnomalie,
  type TableauComparison,
  type TableauDossier,
  type TableauImport,
  type TableauReport,
  type TableauStats,
} from '../api/tableau'
import styles from './SecretariatPage.module.css'

type TabKey = 'dashboard' | 'import' | 'analyse' | 'anomalies' | 'comparaison' | 'rapports'

function StatCard({ value, label, icon }: { value: number | string; label: string; icon: React.ReactNode }) {
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
    </div>
  )
}

export default function AgentTableauPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard')
  const [stats, setStats] = useState<TableauStats | null>(null)
  const [imports, setImports] = useState<TableauImport[]>([])
  const [dossiers, setDossiers] = useState<TableauDossier[]>([])
  const [anomalies, setAnomalies] = useState<TableauAnomalie[]>([])
  const [reports, setReports] = useState<TableauReport[]>([])
  const [comparison, setComparison] = useState<TableauComparison | null>(null)
  const [analyse, setAnalyse] = useState<TableauAnalyse | null>(null)
  const [selectedImport, setSelectedImport] = useState<TableauImport | null>(null)
  const [selectedReport, setSelectedReport] = useState<TableauReport | null>(null)

  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

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
  const [showReglages, setShowReglages] = useState(false)

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

  const loadImportDetails = async (importId: number) => {
    const [dossiersData, anomaliesData] = await Promise.all([
      listTableauDossiers({ import_id: importId }).catch(() => []),
      listTableauAnomalies({ import_id: importId }).catch(() => []),
    ])
    setDossiers(dossiersData)
    setAnomalies(anomaliesData)
  }

  const handleSelectImport = async (imp: TableauImport) => {
    setSelectedImport(imp)
    setLoading(true)
    try {
      await loadImportDetails(imp.id)
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
      // recalculer les conclusions avec les nouveaux réglages
      const result = await runTableauAnalyse(selectedImport.id)
      setAnalyse(result)
      await loadImportDetails(selectedImport.id)
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
      await downloadTableauExport(selectedImport.id)
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

  const anomaliesHigh = anomalies.filter(a => a.gravite === 'high')
  const anomaliesMedium = anomalies.filter(a => a.gravite === 'medium')
  const anomaliesLow = anomalies.filter(a => a.gravite === 'low')

  const tabs: Array<{ key: TabKey; label: string; icon: React.ReactNode }> = [
    { key: 'dashboard', label: 'Tableau de bord', icon: <BarChart2 size={15} /> },
    { key: 'import', label: 'Import Excel', icon: <Upload size={15} /> },
    { key: 'analyse', label: 'Analyse IA', icon: <Bot size={15} /> },
    { key: 'anomalies', label: 'Anomalies', icon: <AlertTriangle size={15} /> },
    { key: 'comparaison', label: 'Comparaison', icon: <GitCompare size={15} /> },
    { key: 'rapports', label: 'Rapports', icon: <FileText size={15} /> },
  ]

  return (
    <div className={styles.page}>
      <SecretariatAgentChat />

      <div className={styles.controlPanel}>
        <div className={styles.topRow}>
          <div>
            <div className={styles.breadcrumb}>Secrétariat / Agent Tableau</div>
            <h1 className={styles.title}>
              <span className={styles.iconBox}><Table2 size={19} /></span>
              Agent Tableau
            </h1>
          </div>
          <div className={styles.actions}>
            <BackButton fallback="/secretariat" />
            <button type="button" className={styles.secondaryButton} onClick={() => void loadAll()} disabled={loading}>
              <RefreshCw size={15} />
              Actualiser
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '4px', marginTop: '10px', flexWrap: 'wrap' }}>
          {tabs.map(tab => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '5px',
                border: '1px solid',
                borderColor: activeTab === tab.key ? 'var(--tenant-primary, #714b67)' : '#e5e7eb',
                background: activeTab === tab.key ? 'var(--tenant-primary, #714b67)' : '#fff',
                color: activeTab === tab.key ? '#fff' : '#374151',
                fontSize: '13px',
                fontWeight: activeTab === tab.key ? '600' : '400',
                cursor: 'pointer',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
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
              <StatCard value={stats?.dossiers_importes ?? 0} label="Dossiers importés" icon={<FileSpreadsheet size={18} />} />
              <StatCard value={stats?.dossiers_analyses ?? 0} label="Dossiers analysés" icon={<Bot size={18} />} />
              <StatCard value={stats?.dossiers_incomplets ?? 0} label="Dossiers incomplets" icon={<AlertTriangle size={18} />} />
              <StatCard value={stats?.anomalies_detectees ?? 0} label="Anomalies détectées" icon={<XCircle size={18} />} />
              <StatCard value={stats?.decisions_a_valider ?? 0} label="Décisions enregistrées" icon={<CheckCircle2 size={18} />} />
            </div>

            <div className={styles.intro}>
              <section className={styles.panel}>
                <p className={styles.description}>
                  L'Agent Tableau assiste la Commission Tableau dans l'analyse des dossiers d'inscription,
                  de changement de catégorie, de conformité et de suivi des experts-comptables.
                  Importez un fichier Excel, lancez l'analyse IA, détectez les anomalies et générez rapports et PV.
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
                { label: 'Importer Excel', icon: <Upload size={18} />, desc: 'Charger le tableau des experts-comptables', tab: 'import' as TabKey },
                { label: 'Lancer l\'analyse', icon: <Bot size={18} />, desc: 'Détecter anomalies et dossiers incomplets', tab: 'analyse' as TabKey },
                { label: 'Voir les anomalies', icon: <AlertTriangle size={18} />, desc: 'Consulter les anomalies détectées', tab: 'anomalies' as TabKey },
                { label: 'Comparer exercices', icon: <GitCompare size={18} />, desc: 'Analyser les évolutions entre deux exercices', tab: 'comparaison' as TabKey },
                { label: 'Générer un rapport', icon: <FileText size={18} />, desc: 'Créer un rapport d\'analyse ou un PV', tab: 'rapports' as TabKey },
              ].map(action => (
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
                          Exercice {imp.exercice} · {imp.imported_rows} dossiers · {new Date(imp.created_at).toLocaleDateString('fr-FR')}
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
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAnalyse()}
                    disabled={actionLoading === 'analyse'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                  >
                    <Bot size={15} />
                    {actionLoading === 'analyse' ? 'Analyse...' : 'Lancer l\'analyse IA'}
                  </button>
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
                      {dossiers.slice(0, 50).map((d, i) => {
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
                          <td style={{ padding: '7px 10px', color: '#6b7280', fontWeight: '600' }}>{i + 1}</td>
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
                  {dossiers.length > 50 && (
                    <p style={{ fontSize: '12px', color: '#9ca3af', padding: '8px 10px' }}>
                      Affichage des 50 premiers dossiers sur {dossiers.length}.
                    </p>
                  )}
                </div>
              </div>
            )}
          </section>
        )}

        {activeTab === 'analyse' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Analyse IA</h2>
                <p className={styles.sectionSubtitle}>Détection automatique des anomalies et statistiques de conformité.</p>
              </div>
              {selectedImport && (
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={() => void handleAnalyse()}
                  disabled={actionLoading === 'analyse'}
                  style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                >
                  <Bot size={15} />
                  {actionLoading === 'analyse' ? 'Analyse en cours...' : 'Relancer l\'analyse'}
                </button>
              )}
            </div>

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

                <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
                       onClick={() => setShowReglages(v => !v)}>
                    <h3 style={{ fontSize: '13px', fontWeight: '600', color: '#374151', margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Settings size={15} /> Réglages de délibération
                    </h3>
                    <span style={{ fontSize: '12px', color: '#6b7280' }}>{showReglages ? 'Masquer ▲' : 'Modifier ▼'}</span>
                  </div>
                  {showReglages && (
                    <div style={{ marginTop: '12px' }}>
                      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                        <div>
                          <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Heures de formation min.</label>
                          <input type="number" value={reglages.heures_formation_min ?? 120}
                            onChange={e => setReglages(r => ({ ...r, heures_formation_min: Number(e.target.value) }))}
                            style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                        </div>
                        <div>
                          <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Seuil d'âge (exemption)</label>
                          <input type="number" value={reglages.age_seuil ?? 60}
                            onChange={e => setReglages(r => ({ ...r, age_seuil: Number(e.target.value) }))}
                            style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                        </div>
                        <div>
                          <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Au-delà du seuil d'âge</label>
                          <select value={reglages.age_action ?? 'a_deliberer'}
                            onChange={e => setReglages(r => ({ ...r, age_action: e.target.value as TableauReglages['age_action'] }))}
                            style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '200px' }}>
                            <option value="a_deliberer">Marquer « À DÉLIBÉRER »</option>
                            <option value="inscrit">Valider directement (INSCRIT)</option>
                            <option value="aucune">Ne rien changer (soumis aux 120h)</option>
                          </select>
                        </div>
                      </div>
                      <button type="button" className={styles.secondaryButton}
                        onClick={() => void handleSaveReglages()}
                        disabled={actionLoading === 'reglages'}
                        style={{ marginTop: '12px', background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}>
                        <Settings size={15} />
                        {actionLoading === 'reglages' ? 'Application...' : 'Appliquer et recalculer'}
                      </button>
                    </div>
                  )}
                </div>

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
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGenerateReport()}
                    disabled={actionLoading === 'report'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleExportTableau()}
                    disabled={actionLoading === 'export-xlsx'}
                    style={{ background: '#16a34a', color: '#fff', borderColor: '#16a34a' }}
                  >
                    <Download size={15} />
                    {actionLoading === 'export-xlsx' ? 'Export...' : 'Exporter le tableau (.xlsx)'}
                  </button>
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
                {selectedImport && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAnalyse()}
                    disabled={actionLoading === 'analyse'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', marginTop: '8px' }}
                  >
                    <Bot size={15} />
                    Lancer l'analyse IA
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
                  {anomalies.length} anomalie(s) pour l'import sélectionné.
                  {anomaliesHigh.length > 0 && ` ${anomaliesHigh.length} critique(s).`}
                </p>
              </div>
            </div>

            {anomalies.length === 0 ? (
              <div className={styles.emptyBox}>
                {selectedImport ? 'Aucune anomalie détectée. Lancez d\'abord l\'analyse IA.' : 'Sélectionnez un import.'}
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
                        {comparison.details.map((d, i) => (
                          <tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
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

            {selectedImport && (
              <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '20px' }}>
                <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
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
                    disabled={actionLoading === 'report'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                </div>

                <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
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
                    disabled={actionLoading === 'pv'}
                    style={{ background: 'var(--tenant-primary, #714b67)', color: '#fff', borderColor: 'var(--tenant-primary, #714b67)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'pv' ? 'Génération...' : 'Générer le PV'}
                  </button>
                </div>
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
      </div>
    </div>
  )
}
