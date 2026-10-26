import { useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { uploadTableauExcel, type TableauImportResult } from '../api/tableau'
import styles from './ImportModules.module.css'

interface ImportTableauDossiersProps {
  exercice: string
  onExerciceChange: (value: string) => void
  onImported: (importId: number | null) => void
}

type SourceType = 'tableau' | 'personnes_physiques' | 'personnes_morales' | 'chiffres_affaires' | 'assurances'

// Contrat d'import — miroir des adaptateurs serveur (`source_adapters.py`).
const SOURCES: Record<SourceType, {
  shortTitle: string
  title: string
  description: string
  accent: string
  required: string[]
  optional: string[]
}> = {
  tableau: {
    shortTitle: 'Tableau',
    title: 'Tableau des experts-comptables',
    description: 'Classeur complet : il alimente la base et l’analyse.',
    accent: 'expertAccentSec',
    required: ['numero_ordre', 'nom', 'categorie'],
    optional: [
      'cotisation', 'assurance', 'chiffre_affaires', 'heures_formation',
      'date_naissance', 'anciennete', 'sexe', 'telephone', 'email', 'cabinet', 'nif',
    ],
  },
  personnes_physiques: {
    shortTitle: 'Personnes physiques',
    title: 'Source détaillée — personnes physiques',
    description: 'Fiches EC, rapprochées du référentiel national.',
    accent: 'expertAccentIndependant',
    required: ['numero_ordre', 'membre'],
    optional: [],
  },
  personnes_morales: {
    shortTitle: 'Personnes morales',
    title: 'Source détaillée — personnes morales',
    description: 'Fiches SEC, rapprochées du référentiel national.',
    accent: 'expertAccentCabinet',
    required: ['numero_ordre', 'membre'],
    optional: [],
  },
  chiffres_affaires: {
    shortTitle: 'Chiffres d’affaires',
    title: 'Source détaillée — chiffres d’affaires',
    description: 'Déclarations de chiffre d’affaires, par année.',
    accent: 'expertAccentSalarie',
    required: ['numero_ordre ou membre', 'annee'],
    optional: [],
  },
  assurances: {
    shortTitle: 'Assurances',
    title: 'Source détaillée — assurances',
    description: 'Attestations d’assurance des membres.',
    accent: 'expertAccentNational',
    required: ['numero_ordre ou membre'],
    optional: [],
  },
}

const CATEGORIES = ['Société', 'EC Cabinet', 'EC Indépendant', 'EC Salarié', 'Stagiaire']

interface FeuilleApercu {
  nom: string
  lignes: number
}

const aujourdhui = () => {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

const tailleLisible = (octets: number) =>
  octets < 1024 * 1024 ? `${Math.max(1, Math.round(octets / 1024))} Ko` : `${(octets / (1024 * 1024)).toFixed(1)} Mo`

export default function ImportTableauDossiers({ exercice, onExerciceChange, onImported }: ImportTableauDossiersProps) {
  const [importing, setImporting] = useState(false)
  const [sourceType, setSourceType] = useState<SourceType>('tableau')
  const [dateSituation, setDateSituation] = useState(aujourdhui)
  const [fichier, setFichier] = useState<File | null>(null)
  const [feuilles, setFeuilles] = useState<FeuilleApercu[]>([])
  const [lectureErreur, setLectureErreur] = useState<string | null>(null)
  const [showGuide, setShowGuide] = useState(false)
  const [result, setResult] = useState<(Partial<TableauImportResult> & {
    success: boolean
    message: string
    errors: TableauImportResult['errors']
  }) | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const source = SOURCES[sourceType]
  const totalLignes = feuilles.reduce((sum, f) => sum + f.lignes, 0)
  const canImport = !importing && !!fichier && !!exercice.trim() && !!dateSituation

  const downloadTemplate = () => {
    const rows = [
      {
        numero_ordre: 'EC/16.00001', nom: 'ABEDI ASSAD', categorie: 'EC Cabinet',
        cotisation: 'OUI', assurance: '', chiffre_affaires: '', heures_formation: 120,
        date_naissance: '12/05/1980', anciennete: 'Ancien', sexe: 'M',
        telephone: '(+243)895873021', email: 'abedi@exemple.cd', cabinet: 'FICADEX', nif: '',
      },
      {
        numero_ordre: 'EC/17.00002', nom: 'ABISA LYDIE', categorie: 'EC Indépendant',
        cotisation: 'OUI', assurance: 'OUI', chiffre_affaires: 'OUI', heures_formation: 122,
        date_naissance: '03/09/1975', anciennete: 'Ancien', sexe: 'F',
        telephone: '(+243)859437431', email: 'abisa@exemple.cd', cabinet: '', nif: 'A1810696X',
      },
      {
        numero_ordre: 'SEC/18.00001', nom: 'ABN NZAILU & CO SAS', categorie: 'Société',
        cotisation: 'OUI', assurance: 'OUI', chiffre_affaires: 'OUI', heures_formation: '',
        date_naissance: '', anciennete: 'Ancien', sexe: '',
        telephone: '(+243)829000113', email: 'contact@abn.cd', cabinet: '', nif: '',
      },
    ]
    const ws = XLSX.utils.json_to_sheet(rows, {
      header: ['numero_ordre', 'nom', 'categorie', 'cotisation', 'assurance', 'chiffre_affaires',
        'heures_formation', 'date_naissance', 'anciennete', 'sexe', 'telephone', 'email', 'cabinet', 'nif'],
    })
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Membres')
    XLSX.writeFile(wb, 'modele_tableau_membres.xlsx')
  }

  const viderFichier = () => {
    setFichier(null)
    setFeuilles([])
    setLectureErreur(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  // Aperçu seulement : le serveur reste seul juge des en-têtes, qu'il détecte
  // sur n'importe quelle ligne. On compte ici les lignes non vides par feuille.
  const handleFileSelection = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setResult(null)
    setFichier(file)
    setFeuilles([])
    setLectureErreur(null)
    try {
      const wb = XLSX.read(await file.arrayBuffer(), { type: 'array' })
      setFeuilles(wb.SheetNames.map((nom) => ({
        nom,
        lignes: XLSX.utils.sheet_to_json<unknown[]>(wb.Sheets[nom], { header: 1, blankrows: false }).length,
      })))
    } catch {
      setLectureErreur('Le fichier n’a pas pu être lu dans le navigateur. Le serveur le contrôlera à l’import.')
    }
  }

  const handleImport = async () => {
    if (!fichier) return
    if (!exercice.trim()) {
      setResult({ success: false, message: 'Veuillez saisir un exercice avant l\'import.', errors: [] })
      return
    }
    if (!dateSituation) {
      setResult({ success: false, message: 'La date de situation est obligatoire.', errors: [] })
      return
    }

    setImporting(true)
    setResult(null)
    try {
      const res = await uploadTableauExcel(exercice.trim(), fichier, dateSituation, sourceType)
      setResult({ ...res, errors: res.errors || [] })
      if (res.success) {
        viderFichier()
        onImported(res.import_id)
      }
    } catch (error: any) {
      const msg = error?.data?.detail || error?.message || 'Erreur lors de l\'import.'
      setResult({ success: false, message: String(msg), errors: [] })
    } finally {
      setImporting(false)
    }
  }

  const downloadErrorsCsv = () => {
    if (!result?.errors.length) return
    const echapper = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
    const lignes = [
      ['Ligne', 'Colonne', 'Message'].join(';'),
      ...result.errors.map((err) => [err.ligne, err.champ, err.message].map(echapper).join(';')),
    ]
    const blob = new Blob([`﻿${lignes.join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'avertissements_import_tableau.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`${styles.expertImportShell} ${styles.tableauImportShell}`}>
      <div className={styles.expertImportIntro}>
        <p>
          Une feuille par section (Société, Cabinet, Indépendant, Salariés, Stagiaires) <em>ou</em> une feuille à plat
          avec une colonne <code>categorie</code>. Les en-têtes peuvent être sur n'importe quelle ligne : le parseur les
          détecte. La conclusion (INSCRIT / NON INSCRIT / À DÉLIBÉRER) est calculée à l'analyse.
        </p>
      </div>

      <div className={styles.expertModuleTabs} role="tablist" aria-label="Type de source">
        {(Object.keys(SOURCES) as SourceType[]).map((type) => (
          <button
            key={type}
            type="button"
            role="tab"
            aria-selected={sourceType === type}
            className={`${styles.expertModuleTab} ${sourceType === type ? styles.expertModuleTabActive : ''}`}
            onClick={() => setSourceType(type)}
            disabled={importing}
          >
            <strong>{SOURCES[type].shortTitle}</strong>
            <span>{SOURCES[type].description}</span>
          </button>
        ))}
      </div>

      <section className={styles.importCard}>
        <div className={styles.importCardHeader}>
          <div>
            <h3>{source.title}</h3>
            <p className={styles.expertCardHint}>{source.description}</p>
          </div>
          <span className={`${styles.expertCategoryPill} ${styles[source.accent]}`}>{source.shortTitle}</span>
        </div>
        <div className={styles.tableauFieldsRow}>
          <label className={styles.tableauField}>
            Exercice (année)
            <input
              value={exercice}
              onChange={(e) => onExerciceChange(e.target.value)}
              placeholder="ex : 2026"
              disabled={importing}
            />
          </label>
          <label className={styles.tableauField}>
            Date de situation
            <input
              type="date"
              value={dateSituation}
              onChange={(e) => setDateSituation(e.target.value)}
              disabled={importing}
              required
            />
          </label>
        </div>
        <div className={styles.filePickerRow}>
          <label htmlFor="tableau-membres-file" className={styles.filePickerButton}>
            Choisir un fichier
          </label>
          <input
            id="tableau-membres-file"
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleFileSelection}
            disabled={importing}
            className={styles.budgetFileInput}
          />
          <span className={styles.selectedFileName}>{fichier?.name || 'Aucun fichier sélectionné'}</span>
        </div>
      </section>

      <section className={styles.importGridSection}>
        <div className={styles.importCard}>
          <h3>Résumé avant import</h3>
          <div className={styles.summaryGrid}>
            <span>Source<strong>{source.shortTitle}</strong></span>
            <span>Exercice<strong>{exercice.trim() || '—'}</strong></span>
            <span>
              Situation au
              <strong>{dateSituation ? new Date(`${dateSituation}T00:00:00`).toLocaleDateString('fr-FR') : '—'}</strong>
            </span>
            <span>Taille du fichier<strong>{fichier ? tailleLisible(fichier.size) : '—'}</strong></span>
            <span>Feuilles<strong>{fichier ? feuilles.length : '—'}</strong></span>
            <span>Lignes non vides<strong>{fichier ? totalLignes : '—'}</strong></span>
          </div>
        </div>

        <div className={styles.importCard}>
          <h3>Aperçu avant import</h3>
          {lectureErreur ? (
            <p className={styles.emptyPreview}>{lectureErreur}</p>
          ) : feuilles.length > 0 ? (
            <div className={styles.expertPreviewList}>
              {feuilles.slice(0, 6).map((feuille, index) => (
                <div className={styles.expertPreviewRow} key={`${feuille.nom}-${index}`}>
                  <strong>Feuille {index + 1}</strong>
                  <span>{feuille.nom}</span>
                  <em>{feuille.lignes} ligne(s)</em>
                </div>
              ))}
              {feuilles.length > 6 && <p>{feuilles.length - 6} feuille(s) supplémentaire(s).</p>}
            </div>
          ) : (
            <p className={styles.emptyPreview}>Sélectionnez un fichier Excel (.xlsx ou .xls) pour la source active.</p>
          )}
        </div>
      </section>

      {showGuide && (
        <section className={styles.importGuide}>
          <strong>Guide d'import — {source.shortTitle}</strong>
          <span>Colonnes obligatoires : {source.required.join(', ')}.</span>
          {source.optional.length > 0 ? (
            <span>Colonnes optionnelles : {source.optional.join(', ')}.</span>
          ) : (
            <span>Les autres colonnes sont conservées telles quelles avec la ligne importée.</span>
          )}
          {sourceType === 'tableau' && (
            <>
              <span>categorie ∈ {CATEGORIES.join(' / ')}.</span>
              <span>cotisation / assurance / chiffre_affaires = OUI ou NON · heures_formation = nombre (NHV).</span>
            </>
          )}
          <span>Un fichier déjà importé pour la même date de situation est reconnu et n'est pas rechargé.</span>
        </section>
      )}

      {result && (
        <section className={`${styles.importReport} ${result.success ? styles.reportSuccess : styles.reportError}`}>
          <div className={styles.reportHeader}>
            <h3>{result.success ? (result.duplicate_detected ? 'Fichier déjà importé' : "Rapport d'import") : 'Import échoué'}</h3>
            {result.errors.length > 0 && (
              <button type="button" className={styles.errorDownloadBtn} onClick={downloadErrorsCsv}>
                Télécharger CSV
              </button>
            )}
          </div>
          <p>{result.message}</p>
          {result.success && (
            <div className={styles.importStats}>
              <span>Lignes: {result.total_lignes ?? 0}</span>
              <span>Importés: {result.imported ?? 0}</span>
              <span>Mis à jour: {result.updated ?? 0}</span>
              <span>Ignorés: {result.skipped ?? 0}</span>
              {result.rejected_rows != null && <span>Rejetées: {result.rejected_rows}</span>}
              <span>Avertissements: {result.errors.length}</span>
            </div>
          )}
          {!!result.nouveaux_membres && (
            <p>{result.nouveaux_membres} membre(s) entrent pour la première fois au Tableau de ce conseil.</p>
          )}
          {!!result.reprises && (
            <p>
              {result.reprises} valeur(s) reprise(s) de la situation précédente : une cellule vide n'efface pas ce qui
              était déjà connu.
            </p>
          )}
          {!!result.decisions_reportees && (
            <p>
              {result.decisions_reportees} membre(s) portent déjà une décision de la commission : elle continue de
              primer sur le verdict automatique.
            </p>
          )}
          {result.errors.length > 0 && (
            <div className={styles.errorList}>
              {result.errors.slice(0, 5).map((err, index) => (
                <span key={`${err.ligne ?? index}-${index}`}>
                  Ligne {err.ligne ?? '—'} · {err.champ ?? '—'}: {err.message ?? '—'}
                </span>
              ))}
              {result.errors.length > 5 && <span>{result.errors.length - 5} avertissement(s) supplémentaire(s).</span>}
            </div>
          )}
        </section>
      )}

      <footer className={`${styles.budgetImportActions} ${styles.tableauImportActions}`}>
        <button type="button" className={styles.secondaryImportButton} onClick={downloadTemplate} disabled={importing}>
          Télécharger le modèle
        </button>
        <button type="button" className={styles.secondaryImportButton} onClick={() => setShowGuide((value) => !value)}>
          Guide d'import
        </button>
        <span className={styles.actionSpacer} />
        <button type="button" className={styles.cancelImportButton} onClick={viderFichier} disabled={importing || !fichier}>
          Retirer le fichier
        </button>
        <button type="button" className={styles.primaryImportButton} onClick={handleImport} disabled={!canImport}>
          {importing ? 'Import en cours...' : `Importer ${source.shortTitle}`}
        </button>
      </footer>
    </div>
  )
}
