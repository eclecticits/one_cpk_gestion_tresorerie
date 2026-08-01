import { useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { importBudgetPostes } from '../api/budget'
import { useToast } from '../hooks/useToast'
import styles from './ImportModules.module.css'

type BudgetType = 'DEPENSE' | 'RECETTE'
type ConflictMode = 'add_only' | 'update_existing' | 'replace_exercise'

interface ValidationError {
  ligne: number
  colonne: string
  erreur: string
  code?: string
}

interface ImportResult {
  success: boolean
  message: string
  imported?: number
  created?: number
  updated?: number
  skipped?: number
  error_count?: number
  total_lignes?: number
  backup_path?: string | null
  errors: ValidationError[]
}

interface PreviewRow {
  code: string
  libelle: string
  plafond: number
  parent_code?: string | null
}

interface ModuleState {
  fileName: string
  rows: PreviewRow[]
  errors: ValidationError[]
  result: ImportResult | null
  totalRows: number
}

interface ImportBudgetPostesProps {
  annee: number
  type: BudgetType
  onClose: () => void
  onSuccess: () => void
}

const requiredHeaders = ['code', 'libelle', 'plafond']
const initialModuleState: ModuleState = {
  fileName: '',
  rows: [],
  errors: [],
  result: null,
  totalRows: 0,
}

const headerAliases: Record<string, string> = {
  code: 'code',
  libelle: 'libelle',
  plafond: 'plafond',
  parent_code: 'parent_code',
  'parent code': 'parent_code',
  'code parent': 'parent_code',
  code_parent: 'parent_code',
  parent: 'parent_code',
  parentcode: 'parent_code',
}

const moduleCopy: Record<BudgetType, { label: string; accent: string; templateRows: PreviewRow[]; fileName: string }> = {
  DEPENSE: {
    label: 'Budget Dépenses',
    accent: 'depense',
    fileName: 'modele_budget_depenses.xlsx',
    templateRows: [
      { code: 'II', libelle: 'DEPENSES DE FONCTIONNEMENT', plafond: 0, parent_code: '' },
      { code: 'II.1', libelle: 'Personnel', plafond: 150000, parent_code: 'II' },
      { code: 'II.2', libelle: 'Services extérieurs', plafond: 60000, parent_code: 'II' },
    ],
  },
  RECETTE: {
    label: 'Budget Recettes',
    accent: 'recette',
    fileName: 'modele_budget_recettes.xlsx',
    templateRows: [
      { code: 'I', libelle: 'RECETTES ORDINAIRES', plafond: 0, parent_code: '' },
      { code: 'I.1', libelle: 'Cotisations', plafond: 250000, parent_code: 'I' },
      { code: 'I.2', libelle: 'Produits administratifs', plafond: 90000, parent_code: 'I' },
    ],
  },
}

const normalizeHeader = (raw: unknown): string => {
  if (raw === null || raw === undefined) return ''
  const value = String(raw)
    .replace(/\u00a0/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

const normalizeCode = (value: unknown): string => {
  return String(value ?? '')
    .replace(/\u00a0/g, ' ')
    .trim()
    .replace(/\s+/g, '')
    .replace(/\.+/g, '.')
    .replace(/^\.+|\.+$/g, '')
}

const pickHeaderRowIndex = (rows: unknown[][], expectedHeaders: string[]): number => {
  const expected = new Set(expectedHeaders.map(normalizeHeader))
  let bestIndex = 0
  let bestMatch = 0
  rows.slice(0, 5).forEach((row, idx) => {
    const matchCount = row.reduce((count: number, cell: unknown) => {
      const normalized = normalizeHeader(cell)
      return normalized && expected.has(normalized) ? count + 1 : count
    }, 0)
    if (matchCount > bestMatch) {
      bestMatch = matchCount
      bestIndex = idx
    }
  })
  return bestIndex
}

const buildRowsFromSheet = (worksheet: XLSX.WorkSheet) => {
  const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' }) as unknown[][]
  if (!rawRows.length) return { rows: [] as Record<string, unknown>[], missingRequired: requiredHeaders }

  const headerRowIndex = pickHeaderRowIndex(rawRows, Object.keys(headerAliases))
  const rawHeaders = (rawRows[headerRowIndex] || []).map((h: unknown) => String(h ?? '').trim())
  const normalizedAliases = new Map(
    Object.entries(headerAliases).map(([alias, canonical]) => [normalizeHeader(alias), canonical])
  )
  const mappedHeaders = rawHeaders.map((h) => normalizedAliases.get(normalizeHeader(h)) || h)
  const presentHeaderSet = new Set(mappedHeaders.map((h) => normalizeHeader(h)).filter(Boolean))
  const missingRequired = requiredHeaders.filter((h) => !presentHeaderSet.has(normalizeHeader(h)))

  const rows = rawRows.slice(headerRowIndex + 1).map((row) => {
    const rowObj: Record<string, unknown> = {}
    mappedHeaders.forEach((header, idx) => {
      const key = String(header ?? '').trim()
      if (key) rowObj[key] = idx < row.length ? row[idx] : ''
    })
    return rowObj
  })

  return { rows, missingRequired }
}

const validateAndPrepareRows = (rows: Record<string, unknown>[]) => {
  const errors: ValidationError[] = []
  const validRows: PreviewRow[] = []

  rows.forEach((row, index) => {
    const ligne = index + 2
    const code = normalizeCode(row.code)
    const parentCode = normalizeCode(row.parent_code)
    const libelle = String(row.libelle || '').trim()
    const rawPlafond = row.plafond
    const plafondIsEmpty = rawPlafond === '' || rawPlafond === null || rawPlafond === undefined
    const numericPlafond = plafondIsEmpty ? 0 : Number(rawPlafond)
    const isEmptyRow = !code && !libelle && !parentCode && (plafondIsEmpty || numericPlafond === 0)

    if (isEmptyRow) return
    if (!code) errors.push({ ligne, colonne: 'code', erreur: 'Champ obligatoire manquant', code })
    if (!libelle) errors.push({ ligne, colonne: 'libelle', erreur: 'Champ obligatoire manquant', code })
    if (!Number.isFinite(numericPlafond)) {
      errors.push({ ligne, colonne: 'plafond', erreur: 'Montant invalide', code })
    } else if (numericPlafond < 0) {
      errors.push({ ligne, colonne: 'plafond', erreur: 'Montant négatif interdit', code })
    }

    if (code && libelle && Number.isFinite(numericPlafond) && numericPlafond >= 0) {
      validRows.push({
        code,
        libelle,
        plafond: numericPlafond,
        parent_code: parentCode || undefined,
      })
    }
  })

  return { errors, validRows }
}

const summarizeRows = (rows: PreviewRow[]) => {
  const roots = rows.filter((row) => !row.parent_code && !row.code.includes('.')).length
  return {
    total: rows.length,
    roots,
    children: Math.max(rows.length - roots, 0),
  }
}

export default function ImportBudgetPostes({ annee, type, onClose, onSuccess }: ImportBudgetPostesProps) {
  const [activeType, setActiveType] = useState<BudgetType>(type)
  const [conflictMode, setConflictMode] = useState<ConflictMode>('update_existing')
  const [showGuide, setShowGuide] = useState(false)
  const [importing, setImporting] = useState(false)
  const [modules, setModules] = useState<Record<BudgetType, ModuleState>>({
    DEPENSE: { ...initialModuleState },
    RECETTE: { ...initialModuleState },
  })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { notifySuccess, notifyWarning } = useToast()

  const activeState = modules[activeType]
  const summary = summarizeRows(activeState.rows)
  const canImport = !importing && activeState.rows.length > 0 && activeState.errors.length === 0

  const updateActiveState = (patch: Partial<ModuleState>) => {
    setModules((current) => ({
      ...current,
      [activeType]: {
        ...current[activeType],
        ...patch,
      },
    }))
  }

  const downloadTemplate = () => {
    const worksheet = XLSX.utils.json_to_sheet(moduleCopy[activeType].templateRows)
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, moduleCopy[activeType].label)
    XLSX.writeFile(workbook, moduleCopy[activeType].fileName)
  }

  const downloadErrorsCsv = () => {
    const resultErrors = activeState.result?.errors || activeState.errors
    if (!resultErrors.length) return
    const rows = [
      ['ligne', 'code', 'message'],
      ...resultErrors.map((err) => [String(err.ligne), err.code || '', err.erreur]),
    ]
    const csv = rows
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `rapport_erreurs_${moduleCopy[activeType].fileName.replace('.xlsx', '.csv')}`
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleFileSelection = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    try {
      const data = await file.arrayBuffer()
      const workbook = XLSX.read(data)
      const worksheet = workbook.Sheets[workbook.SheetNames[0]]
      const { rows: jsonData, missingRequired } = buildRowsFromSheet(worksheet)

      if (missingRequired.length) {
        updateActiveState({
          fileName: file.name,
          rows: [],
          totalRows: jsonData.length,
          result: null,
          errors: [{ ligne: 1, colonne: 'entête', erreur: `Colonnes manquantes: ${missingRequired.join(', ')}` }],
        })
        return
      }

      const { errors, validRows } = validateAndPrepareRows(jsonData)
      updateActiveState({
        fileName: file.name,
        rows: validRows,
        errors: validRows.length ? errors : [...errors, { ligne: 1, colonne: 'fichier', erreur: 'Aucune ligne valide détectée' }],
        result: null,
        totalRows: jsonData.length,
      })
    } catch (error: any) {
      updateActiveState({
        fileName: file.name,
        rows: [],
        totalRows: 0,
        result: null,
        errors: [{ ligne: 1, colonne: 'fichier', erreur: error?.message || 'Lecture du fichier impossible' }],
      })
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleImport = async () => {
    if (!canImport) return

    let replaceConfirmation: string | null = null
    if (conflictMode === 'replace_exercise') {
      replaceConfirmation = window.prompt(
        `Cette option remplace tous les postes de ${moduleCopy[activeType].label} pour l'exercice ${annee}. Saisissez REMPLACER BUDGET pour confirmer.`
      )
      if (replaceConfirmation !== 'REMPLACER BUDGET') {
        updateActiveState({
          result: { success: false, message: 'Confirmation de remplacement invalide. Import annulé.', errors: [] },
        })
        return
      }
    }

    setImporting(true)
    try {
      const res = await importBudgetPostes({
        annee,
        type: activeType,
        filename: activeState.fileName,
        conflict_mode: conflictMode,
        replace_confirmation: replaceConfirmation,
        rows: activeState.rows,
      })

      const mappedErrors = (res.errors || []).map((err) => ({
        ligne: err.ligne,
        colonne: err.champ,
        erreur: err.message,
        code: (err as any).code,
      }))
      const nextResult: ImportResult = {
        success: res.success && mappedErrors.length === 0,
        message: res.message,
        imported: res.imported,
        created: res.created,
        updated: res.updated,
        skipped: res.skipped,
        error_count: res.error_count,
        total_lignes: res.total_lignes,
        backup_path: res.backup_path,
        errors: mappedErrors,
      }
      updateActiveState({ result: nextResult })

      if (!nextResult.success) return
      if (Number(res.skipped ?? 0) > 0) {
        notifyWarning('Import partiel', res.message)
      } else {
        notifySuccess('Import terminé', res.message)
      }
      onSuccess()
    } catch (error: any) {
      updateActiveState({
        result: {
          success: false,
          message: error?.message || "Erreur lors de l'import",
          errors: [],
        },
      })
    } finally {
      setImporting(false)
    }
  }

  const resultErrors = activeState.result?.errors || []
  const displayedErrors = resultErrors.length ? resultErrors : activeState.errors

  return (
    <div className={styles.modal}>
      <div className={styles.budgetImportDialog}>
        <header className={styles.budgetImportHeader}>
          <div>
            <h2>Importer des postes budgétaires</h2>
            <p>Format attendu: code, libelle, plafond, parent_code optionnel.</p>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Fermer" disabled={importing}>
            ×
          </button>
        </header>

        <div className={styles.budgetTypeTabs} role="tablist" aria-label="Type de budget">
          {(['DEPENSE', 'RECETTE'] as BudgetType[]).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={activeType === item}
              className={`${styles.budgetTypeTab} ${activeType === item ? styles.budgetTypeTabActive : ''}`}
              onClick={() => setActiveType(item)}
              disabled={importing}
            >
              {moduleCopy[item].label}
            </button>
          ))}
        </div>

        <div className={styles.budgetImportBody}>
          <section className={styles.importCard}>
            <div className={styles.importCardHeader}>
              <h3>Fichier à importer</h3>
              <span className={`${styles.importTypePill} ${styles[moduleCopy[activeType].accent]}`}>
                {moduleCopy[activeType].label}
              </span>
            </div>
            <div className={styles.filePickerRow}>
              <label htmlFor="budget-postes-file" className={styles.filePickerButton}>
                Choisir un fichier
              </label>
              <input
                id="budget-postes-file"
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileSelection}
                disabled={importing}
                className={styles.budgetFileInput}
              />
              <span className={styles.selectedFileName}>{activeState.fileName || 'Aucun fichier sélectionné'}</span>
            </div>
          </section>

          <section className={styles.importCard}>
            <h3>Gestion des conflits</h3>
            <div className={styles.conflictGrid}>
              <label className={`${styles.conflictChoice} ${styles.conflictAdd}`}>
                <input
                  type="radio"
                  name="budgetConflictMode"
                  checked={conflictMode === 'add_only'}
                  onChange={() => setConflictMode('add_only')}
                  disabled={importing}
                />
                <span>
                  <strong>Ajouter uniquement les nouveaux postes</strong>
                  <small>Les codes existants sont ignorés et restent inchangés.</small>
                </span>
              </label>
              <label className={`${styles.conflictChoice} ${styles.conflictUpdate}`}>
                <input
                  type="radio"
                  name="budgetConflictMode"
                  checked={conflictMode === 'update_existing'}
                  onChange={() => setConflictMode('update_existing')}
                  disabled={importing}
                />
                <span>
                  <strong>Mettre à jour les postes existants (recommandé)</strong>
                  <small>Libellé, plafond et parent sont actualisés sans changer l'identifiant.</small>
                </span>
              </label>
              <label className={`${styles.conflictChoice} ${styles.conflictReplace}`}>
                <input
                  type="radio"
                  name="budgetConflictMode"
                  checked={conflictMode === 'replace_exercise'}
                  onChange={() => setConflictMode('replace_exercise')}
                  disabled={importing}
                />
                <span>
                  <strong>Remplacer complètement le budget de l'exercice</strong>
                  <small>Les postes du module actif sont supprimés avant l'import.</small>
                </span>
              </label>
            </div>
          </section>

          <section className={styles.importGridSection}>
            <div className={styles.importCard}>
              <h3>Résumé avant import</h3>
              <div className={styles.summaryGrid}>
                <span>Exercice<strong>{annee}</strong></span>
                <span>Type<strong>{activeType === 'RECETTE' ? 'Recettes' : 'Dépenses'}</strong></span>
                <span>Lignes détectées<strong>{summary.total}</strong></span>
                <span>Postes racines<strong>{summary.roots}</strong></span>
                <span>Sous-postes<strong>{summary.children}</strong></span>
              </div>
            </div>

            <div className={styles.importCard}>
              <h3>Aperçu avant import</h3>
              {activeState.rows.length > 0 ? (
                <div className={styles.previewList}>
                  {activeState.rows.slice(0, 5).map((row, index) => (
                    <div className={styles.previewRow} key={`${row.code}-${index}`}>
                      <strong>{row.code}</strong>
                      <span>{row.libelle}</span>
                      <em>{row.plafond.toLocaleString('fr-FR')}</em>
                    </div>
                  ))}
                  {activeState.rows.length > 5 && <p>{activeState.rows.length - 5} ligne(s) supplémentaires.</p>}
                </div>
              ) : (
                <p className={styles.emptyPreview}>Sélectionnez un fichier Excel valide.</p>
              )}
            </div>
          </section>

          {showGuide && (
            <section className={styles.importGuide}>
              <strong>Guide d'import</strong>
              <span>Colonnes obligatoires: code, libelle, plafond. Colonne optionnelle: parent_code.</span>
              <span>Le module actif détermine le type importé; un fichier de recettes doit être chargé dans Budget Recettes.</span>
            </section>
          )}

          {(displayedErrors.length > 0 || activeState.result) && (
            <section
              className={`${styles.importReport} ${
                activeState.result?.success ? styles.reportSuccess : displayedErrors.length ? styles.reportError : ''
              }`}
            >
              <div className={styles.reportHeader}>
                <h3>{activeState.result?.success ? "Rapport d'import" : 'Validation'}</h3>
                {displayedErrors.length > 0 && (
                  <button type="button" className={styles.errorDownloadBtn} onClick={downloadErrorsCsv}>
                    Télécharger CSV
                  </button>
                )}
              </div>
              {activeState.result && <p>{activeState.result.message}</p>}
              {activeState.result && (
                <div className={styles.importStats}>
                  <span>Lignes: {activeState.result.total_lignes ?? summary.total}</span>
                  <span>Importés: {activeState.result.imported ?? 0}</span>
                  <span>Créés: {activeState.result.created ?? 0}</span>
                  <span>Mis à jour: {activeState.result.updated ?? 0}</span>
                  <span>Ignorés: {activeState.result.skipped ?? 0}</span>
                  <span>Erreurs: {activeState.result.error_count ?? displayedErrors.length}</span>
                </div>
              )}
              {displayedErrors.length > 0 && (
                <div className={styles.errorList}>
                  {displayedErrors.slice(0, 4).map((err, index) => (
                    <span key={`${err.ligne}-${index}`}>
                      Ligne {err.ligne} · {err.code ? `${err.code} · ` : ''}
                      {err.erreur}
                    </span>
                  ))}
                  {displayedErrors.length > 4 && <span>{displayedErrors.length - 4} erreur(s) supplémentaire(s).</span>}
                </div>
              )}
            </section>
          )}
        </div>

        <footer className={styles.budgetImportActions}>
          <button type="button" className={styles.secondaryImportButton} onClick={downloadTemplate} disabled={importing}>
            Télécharger le modèle
          </button>
          <button type="button" className={styles.secondaryImportButton} onClick={() => setShowGuide((value) => !value)}>
            Guide d'import
          </button>
          <span className={styles.actionSpacer} />
          <button type="button" className={styles.cancelImportButton} onClick={onClose} disabled={importing}>
            Annuler
          </button>
          <button type="button" className={styles.primaryImportButton} onClick={handleImport} disabled={!canImport}>
            {importing ? 'Import en cours...' : `Importer ${activeType === 'RECETTE' ? 'les recettes' : 'les dépenses'}`}
          </button>
        </footer>
      </div>
    </div>
  )
}
