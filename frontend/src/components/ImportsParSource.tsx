import { Suspense, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BarChart2, Bot, Building2, ChevronLeft, ChevronRight, Download, FileSpreadsheet, Search, ShieldCheck, Table2, Upload, User, X,
} from 'lucide-react'
import {
  downloadTableauImportAnnote,
  getTableauImportLignes,
  type TableauImport,
  type TableauImportLignes,
} from '../api/tableau'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { lazyWithRetry } from '../utils/lazyWithRetry'
import type { SourceType } from './ImportTableauDossiers'
import styles from './ImportsParSource.module.css'

const ImportTableauDossiers = lazyWithRetry(() => import('./ImportTableauDossiers'))

const SOURCES: Array<{ type: SourceType; label: string; aide: string; icon: React.ReactNode }> = [
  { type: 'tableau', label: 'Tableau', aide: 'Classeur complet par section', icon: <Table2 size={16} /> },
  { type: 'personnes_physiques', label: 'Personnes physiques', aide: 'Fiches des experts-comptables', icon: <User size={16} /> },
  { type: 'personnes_morales', label: 'Personnes morales', aide: 'Fiches des sociétés', icon: <Building2 size={16} /> },
  { type: 'chiffres_affaires', label: "Chiffres d'affaires", aide: 'Déclarations par année et devise', icon: <BarChart2 size={16} /> },
  { type: 'assurances', label: 'Assurances', aide: 'Déclarations et couvertures', icon: <ShieldCheck size={16} /> },
]

const TAILLES = [25, 50, 100, 200]

const dateFr = (valeur: string) => new Date(`${valeur}T00:00:00`).toLocaleDateString('fr-FR')

/** Le plus récent au sens métier : date de situation, puis date de téléversement. */
function plusRecentDabord(a: TableauImport, b: TableauImport) {
  return b.date_situation.localeCompare(a.date_situation) || b.created_at.localeCompare(a.created_at) || b.id - a.id
}

/**
 * Écran des imports, une carte par source. Choisir une source montre l'import
 * en cours de cette source avec toutes ses colonnes, telles que le fichier Excel
 * les portait ; les imports précédents restent accessibles par le sélecteur.
 */
export default function ImportsParSource({
  imports,
  canImport,
  canExport,
  canAnalyze,
  exercice,
  onExerciceChange,
  onImported,
  onAnalyse,
  analyseEnCours,
}: {
  imports: TableauImport[]
  canImport: boolean
  canExport: boolean
  canAnalyze: boolean
  exercice: string
  onExerciceChange: (value: string) => void
  onImported: (importId: number | null) => Promise<void> | void
  onAnalyse: (imp: TableauImport) => void
  analyseEnCours: boolean
}) {
  const [params, setParams] = useSearchParams()
  const parType = useMemo(() => {
    const groupes = new Map<SourceType, TableauImport[]>()
    for (const imp of imports) {
      const liste = groupes.get(imp.source_type) || []
      liste.push(imp)
      groupes.set(imp.source_type, liste)
    }
    for (const liste of groupes.values()) liste.sort(plusRecentDabord)
    return groupes
  }, [imports])

  // Sans choix dans l'adresse : la première source qui a un import.
  const sourceAdresse = params.get('source') as SourceType | null
  const source: SourceType = SOURCES.some(s => s.type === sourceAdresse)
    ? sourceAdresse!
    : SOURCES.find(s => parType.has(s.type))?.type ?? 'tableau'
  const importsSource = parType.get(source) || []

  const [importChoisiId, setImportChoisiId] = useState<number | null>(null)
  const importVu = importsSource.find(imp => imp.id === importChoisiId) || importsSource[0] || null
  const [formulaireOuvert, setFormulaireOuvert] = useState(false)

  const [feuille, setFeuille] = useState<string | null>(null)
  const [recherche, setRecherche] = useState('')
  const rechercheDifferee = useDebouncedValue(recherche)
  const [signalees, setSignalees] = useState(false)
  const [page, setPage] = useState(1)
  const [taille, setTaille] = useState(50)
  const [donnees, setDonnees] = useState<TableauImportLignes | null>(null)
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  const choisirSource = (type: SourceType) => {
    const suivants = new URLSearchParams(params)
    suivants.set('source', type)
    setParams(suivants, { replace: true })
    setImportChoisiId(null)
    setFormulaireOuvert(false)
  }

  // Changer d'import ou de source repart de la première feuille, sans filtre.
  useEffect(() => {
    setFeuille(null)
    setRecherche('')
    setSignalees(false)
    setPage(1)
  }, [importVu?.id])

  useEffect(() => { setPage(1) }, [feuille, rechercheDifferee, signalees, taille])

  useEffect(() => {
    if (!importVu) {
      setDonnees(null)
      return
    }
    let annule = false
    setChargement(true)
    setErreur(null)
    getTableauImportLignes(importVu.id, {
      feuille, q: rechercheDifferee || undefined, signalees, limit: taille, offset: (page - 1) * taille,
    })
      .then(resultat => { if (!annule) setDonnees(resultat) })
      .catch((err: unknown) => {
        if (annule) return
        setDonnees(null)
        setErreur(err instanceof Error ? err.message : "Impossible de lire les lignes de l'import.")
      })
      .finally(() => { if (!annule) setChargement(false) })
    return () => { annule = true }
  }, [importVu?.id, feuille, rechercheDifferee, signalees, page, taille])

  const libelleSource = SOURCES.find(s => s.type === source)!.label
  const totalPages = Math.max(1, Math.ceil((donnees?.total || 0) / taille))
  const avecSignalements = (donnees?.total_signalees || 0) > 0

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.eyebrow}>Tableau</div>
          <h1>Imports Excel</h1>
          <p>Choisissez une source pour voir son import en cours, colonne par colonne, tel que le fichier l'a apporté.</p>
        </div>
        <div className={styles.meta}>
          <FileSpreadsheet size={16} />
          <span>{imports.length} import{imports.length > 1 ? 's' : ''}</span>
        </div>
      </div>

      <nav className={styles.nav} aria-label="Sources d'import">
        {SOURCES.map(item => {
          const dernier = parType.get(item.type)?.[0]
          const actif = item.type === source
          return (
            <button
              key={item.type}
              type="button"
              className={`${styles.tab} ${actif ? styles.tabActive : ''}`}
              onClick={() => choisirSource(item.type)}
              aria-pressed={actif}
            >
              <span className={styles.tabIcon}>{item.icon}</span>
              <span>
                <strong>{item.label}</strong>
                <small>
                  {dernier
                    ? `Situation du ${dateFr(dernier.date_situation)} · ${dernier.total_rows} ligne${dernier.total_rows > 1 ? 's' : ''}`
                    : 'Jamais importé'}
                </small>
              </span>
            </button>
          )
        })}
      </nav>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div className={styles.panelTitle}>
            <h2>{libelleSource}</h2>
            {importVu ? (
              <p>
                {importVu === importsSource[0] ? 'Import en cours' : 'Import précédent'} : <strong>{importVu.file_name}</strong>
                {' '}· exercice {importVu.exercice} · situation du {dateFr(importVu.date_situation)}
                {importVu.error_message && <span className={styles.errorText}> · {importVu.error_message}</span>}
              </p>
            ) : (
              <p>Aucun fichier importé pour cette source.</p>
            )}
          </div>
          <div className={styles.actions}>
            {importsSource.length > 1 && (
              <label className={styles.selectLabel}>
                <span>Import</span>
                <select value={importVu?.id ?? ''} onChange={event => setImportChoisiId(Number(event.target.value))}>
                  {importsSource.map((imp, index) => (
                    <option key={imp.id} value={imp.id}>
                      {index === 0 ? 'En cours — ' : ''}{dateFr(imp.date_situation)} · {imp.file_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {importVu && (canImport || canExport) && importVu.total_rows > 0 && (
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  downloadTableauImportAnnote(importVu.id, importVu.file_name).catch((err: unknown) => {
                    setErreur(err instanceof Error ? err.message : 'Téléchargement du fichier annoté impossible.')
                  })
                }}
                title="Le fichier importé, lignes signalées en rouge"
              >
                <Download size={15} /> Fichier annoté
              </button>
            )}
            {importVu && source === 'tableau' && canAnalyze && (
              <button type="button" className={styles.button} onClick={() => onAnalyse(importVu)} disabled={analyseEnCours}>
                <Bot size={15} /> {analyseEnCours ? 'Analyse...' : 'Analyser cet import'}
              </button>
            )}
            {canImport && (
              <button
                type="button"
                className={formulaireOuvert ? styles.button : styles.primaryButton}
                onClick={() => setFormulaireOuvert(ouvert => !ouvert)}
                aria-expanded={formulaireOuvert}
              >
                {formulaireOuvert ? <X size={15} /> : <Upload size={15} />}
                {formulaireOuvert ? "Fermer l'import" : 'Importer un fichier'}
              </button>
            )}
          </div>
        </div>

        {formulaireOuvert && canImport && (
          <div className={styles.importForm}>
            <Suspense fallback={null}>
              <ImportTableauDossiers
                key={source}
                source={source}
                exercice={exercice}
                onExerciceChange={onExerciceChange}
                onImported={id => {
                  setImportChoisiId(null)
                  void onImported(id)
                }}
              />
            </Suspense>
          </div>
        )}

        {importVu && (
          <>
            <div className={styles.toolbar}>
              {donnees && donnees.feuilles.length > 1 && (
                <div className={styles.sheets} role="tablist" aria-label="Feuilles du classeur">
                  {donnees.feuilles.map(item => (
                    <button
                      key={item.nom}
                      type="button"
                      role="tab"
                      aria-selected={donnees.feuille === item.nom}
                      className={`${styles.sheet} ${donnees.feuille === item.nom ? styles.sheetActive : ''}`}
                      onClick={() => setFeuille(item.nom)}
                    >
                      {item.nom} <em>{item.lignes}</em>
                    </button>
                  ))}
                </div>
              )}
              <label className={styles.search}>
                <Search size={15} />
                <input
                  value={recherche}
                  onChange={event => setRecherche(event.target.value)}
                  placeholder="Rechercher dans les valeurs"
                  aria-label="Rechercher dans les lignes de l'import"
                />
              </label>
              {avecSignalements && (
                <label className={styles.checkbox}>
                  <input type="checkbox" checked={signalees} onChange={event => setSignalees(event.target.checked)} />
                  Lignes signalées seulement ({donnees!.total_signalees})
                </label>
              )}
              <span className={styles.count}>
                {donnees ? `${donnees.total} ligne${donnees.total > 1 ? 's' : ''} · ${donnees.colonnes.length} colonnes` : ''}
              </span>
            </div>

            {erreur ? (
              <div className={styles.empty}>{erreur}</div>
            ) : chargement && !donnees ? (
              <div className={styles.empty}>Chargement des lignes...</div>
            ) : !donnees || donnees.total === 0 ? (
              <div className={styles.empty}>
                {recherche || signalees ? 'Aucune ligne ne correspond.' : "Cet import n'a conservé aucune ligne."}
              </div>
            ) : (
              <>
                <div className={styles.tableWrap} aria-busy={chargement}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th className={styles.lineCell}>Ligne</th>
                        {donnees.colonnes.map(colonne => <th key={colonne}>{colonne}</th>)}
                        {avecSignalements && <th>Signalement</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {donnees.lignes.map(ligne => {
                        const signalee = ligne.signalements.length > 0
                        return (
                          <tr key={ligne.id} className={signalee ? styles.flagged : undefined}>
                            <td className={styles.lineCell}>{ligne.ligne}</td>
                            {ligne.valeurs.map((valeur, index) => (
                              <td key={donnees.colonnes[index]} className={valeur === null || valeur === '' ? styles.emptyCell : undefined}>
                                {valeur === null || valeur === '' ? '—' : valeur}
                              </td>
                            ))}
                            {avecSignalements && <td className={styles.flagCell}>{ligne.signalements.join(' ; ')}</td>}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div className={styles.pager}>
                  <label>
                    Lignes
                    <select value={taille} onChange={event => setTaille(Number(event.target.value))}>
                      {TAILLES.map(valeur => <option key={valeur} value={valeur}>{valeur}</option>)}
                    </select>
                  </label>
                  <span>Page {Math.min(page, totalPages)} sur {totalPages}</span>
                  <div className={styles.pagerButtons}>
                    <button type="button" className={styles.button} disabled={page <= 1 || chargement} onClick={() => setPage(p => Math.max(1, p - 1))} title="Page précédente" aria-label="Page précédente">
                      <ChevronLeft size={15} />
                    </button>
                    <button type="button" className={styles.button} disabled={page >= totalPages || chargement} onClick={() => setPage(p => p + 1)} title="Page suivante" aria-label="Page suivante">
                      <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </>
            )}
          </>
        )}

        {!importVu && !formulaireOuvert && (
          <div className={styles.empty}>
            Aucun import « {libelleSource} » pour l'instant.
            {canImport ? ' Cliquez sur « Importer un fichier » pour en charger un.' : ''}
          </div>
        )}
      </section>
    </div>
  )
}
