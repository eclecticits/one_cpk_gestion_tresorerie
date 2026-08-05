import { useMemo, useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { importExperts, type CategoryType, type ExpertImportRow } from '../api/experts'
import ResponsiveModal from './ResponsiveModal'
import styles from './ImportModules.module.css'

type ImportModule = CategoryType
type ConflictMode = 'add_only' | 'update_existing'

interface ValidationError {
  ligne: number
  colonne: string
  erreur: string
  code?: string
}

interface ImportResult {
  success: boolean
  imported: number
  created?: number
  updated?: number
  skipped?: number
  total_lignes?: number
  errors: ValidationError[]
  message: string
}

interface PreviewRow extends ExpertImportRow {
  __rowIndex: number
}

interface ModuleState {
  fileName: string
  rawRows: Record<string, unknown>[]
  rows: PreviewRow[]
  errors: ValidationError[]
  result: ImportResult | null
  preview: ImportResult | null
}

interface ModuleConfig {
  title: string
  shortTitle: string
  description: string
  required: string[]
  optional: string[]
  templateName: string
  accent: string
  example: Record<string, string>
}

interface ImportModulesProps {
  onClose: () => void
  onSuccess: () => void
}

const modules: Record<ImportModule, ModuleConfig> = {
  sec: {
    title: "Sociétés d'Expertise Comptable",
    shortTitle: 'SEC',
    description: 'Cabinets et sociétés inscrits au tableau national.',
    required: ["N° d'ordre", 'Dénomination', "Province d'attache", 'Raison sociale', 'Associé gérant'],
    optional: ['N° de téléphone', 'E-mail'],
    templateName: 'modele_experts_sec.xlsx',
    accent: 'expertAccentSec',
    example: {
      "N° d'ordre": '001',
      Dénomination: 'Cabinet Expert Conseil',
      "Province d'attache": 'Kinshasa',
      'Raison sociale': 'Expert Conseil SARL',
      'Associé gérant': 'Jean DUPONT',
      'N° de téléphone': '+243 000 000 000',
      'E-mail': 'contact@expertconseil.cd',
    },
  },
  en_cabinet: {
    title: 'Experts-comptables en cabinet',
    shortTitle: 'En cabinet',
    description: 'Experts personnes physiques rattachés à un cabinet.',
    required: ["N° d'ordre", 'Noms', 'Sexe', "Province d'attache", "Cabinet d'attache"],
    optional: ['N° de téléphone', 'E-mail'],
    templateName: 'modele_experts_en_cabinet.xlsx',
    accent: 'expertAccentCabinet',
    example: {
      "N° d'ordre": '101',
      Noms: 'MUKENDI Pierre',
      Sexe: 'M',
      "Province d'attache": 'Kinshasa',
      "Cabinet d'attache": 'Cabinet Expert Conseil',
      'N° de téléphone': '+243 000 000 000',
      'E-mail': 'pmukendi@cabinet.cd',
    },
  },
  independant: {
    title: 'Experts-comptables indépendants',
    shortTitle: 'Indépendants',
    description: 'Experts personnes physiques exerçant à titre indépendant.',
    required: ["N° d'ordre", 'Noms', 'Sexe', "Province d'attache", 'NIF'],
    optional: ['N° de téléphone', 'E-mail'],
    templateName: 'modele_experts_independants.xlsx',
    accent: 'expertAccentIndependant',
    example: {
      "N° d'ordre": '201',
      Noms: 'KALALA Marie',
      Sexe: 'F',
      "Province d'attache": 'Haut-Katanga',
      NIF: 'A1234567X',
      'N° de téléphone': '+243 000 000 000',
      'E-mail': 'mkalala@example.cd',
    },
  },
  salarie: {
    title: 'Experts-comptables salariés',
    shortTitle: 'Salariés',
    description: 'Experts personnes physiques salariés d’une organisation.',
    required: ["N° d'ordre", 'Noms', 'Sexe', "Province d'attache", "Nom de l'employeur"],
    optional: ['N° de téléphone', 'E-mail'],
    templateName: 'modele_experts_salaries.xlsx',
    accent: 'expertAccentSalarie',
    example: {
      "N° d'ordre": '301',
      Noms: 'MBALA Joseph',
      Sexe: 'M',
      "Province d'attache": 'Kasaï',
      "Nom de l'employeur": 'Société ABC',
      'N° de téléphone': '+243 000 000 000',
      'E-mail': 'jmbala@example.cd',
    },
  },
}

const initialState: ModuleState = {
  fileName: '',
  rawRows: [],
  rows: [],
  errors: [],
  result: null,
  preview: null,
}

const normalizeHeader = (raw: unknown): string => {
  if (raw === null || raw === undefined) return ''
  return String(raw)
    .replace(/\u00a0/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
}

const normalizeValue = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  return String(value).replace(/\u00a0/g, ' ').trim()
}

const normalizePhone = (raw: unknown): string | undefined => {
  const rawValue = normalizeValue(raw)
  if (!rawValue) return undefined
  const hasPlus = rawValue.startsWith('+')
  const digits = rawValue.replace(/\D/g, '')
  if (!digits) return undefined
  if (hasPlus) return `+${digits}`
  if (digits.startsWith('0') && digits.length === 10) return `+243${digits.slice(1)}`
  if (digits.length === 9) return `+243${digits}`
  if (digits.startsWith('243')) return `+${digits}`
  return undefined
}

const isValidEmail = (value: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)

const getCellValue = (row: Record<string, unknown>, key: string): string => normalizeValue(row[key])

const pickHeaderRowIndex = (rows: unknown[][], expectedHeaders: string[]): number => {
  const expected = new Set(expectedHeaders.map(normalizeHeader))
  let bestIndex = 0
  let bestMatch = 0
  rows.slice(0, 5).forEach((row, index) => {
    const matchCount = row.reduce<number>((count, cell) => {
      const normalized = normalizeHeader(cell)
      return normalized && expected.has(normalized) ? count + 1 : count
    }, 0)
    if (matchCount > bestMatch) {
      bestMatch = matchCount
      bestIndex = index
    }
  })
  return bestIndex
}

const buildRowsFromSheet = (worksheet: XLSX.WorkSheet, module: ImportModule) => {
  const config = modules[module]
  const expectedHeaders = [...config.required, ...config.optional]
  const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' }) as unknown[][]
  if (!rawRows.length) return { rows: [] as Record<string, unknown>[], missingRequired: config.required }

  const headerRowIndex = pickHeaderRowIndex(rawRows, expectedHeaders)
  const rawHeaders = (rawRows[headerRowIndex] || []).map((header) => normalizeValue(header))
  const normalizedExpected = new Map(expectedHeaders.map((header) => [normalizeHeader(header), header]))
  const mappedHeaders = rawHeaders.map((header) => normalizedExpected.get(normalizeHeader(header)) || header)
  const presentHeaderSet = new Set(mappedHeaders.map(normalizeHeader).filter(Boolean))
  const missingRequired = config.required.filter((header) => !presentHeaderSet.has(normalizeHeader(header)))

  const rows = rawRows
    .slice(headerRowIndex + 1)
    .map((row, rowOffset) => {
      const rowObj: Record<string, unknown> = { __rowIndex: headerRowIndex + 2 + rowOffset }
      mappedHeaders.forEach((header, index) => {
        const key = normalizeValue(header)
        if (key) rowObj[key] = index < row.length ? row[index] : ''
      })
      return rowObj
    })
    .filter((rowObj) => {
      return mappedHeaders.some((header) => {
        const key = normalizeValue(header)
        return key && normalizeValue(rowObj[key]) !== ''
      })
    })

  return { rows, missingRequired }
}

const validateRow = (module: ImportModule, row: Record<string, unknown>, index: number): ValidationError[] => {
  const config = modules[module]
  const ligne = typeof row.__rowIndex === 'number' ? row.__rowIndex : index + 2
  const errors: ValidationError[] = []

  config.required.forEach((field) => {
    if (!getCellValue(row, field)) {
      errors.push({ ligne, colonne: field, erreur: 'Champ obligatoire manquant', code: getCellValue(row, "N° d'ordre") })
    }
  })

  if (module !== 'sec') {
    const sexe = getCellValue(row, 'Sexe').toUpperCase()
    if (sexe && !['M', 'F'].includes(sexe)) {
      errors.push({ ligne, colonne: 'Sexe', erreur: 'Valeur attendue: M ou F', code: getCellValue(row, "N° d'ordre") })
    }
  }

  const email = getCellValue(row, 'E-mail').toLowerCase()
  if (email && !isValidEmail(email)) {
    errors.push({ ligne, colonne: 'E-mail', erreur: 'Format e-mail invalide', code: getCellValue(row, "N° d'ordre") })
  }

  return errors
}

const transformToDatabase = (module: ImportModule, row: Record<string, unknown>): PreviewRow => {
  const line = typeof row.__rowIndex === 'number' ? row.__rowIndex : 0
  const baseData = {
    __rowIndex: line,
    numero_ordre: getCellValue(row, "N° d'ordre"),
    email: getCellValue(row, 'E-mail').toLowerCase() || undefined,
    telephone: normalizePhone(getCellValue(row, 'N° de téléphone')),
    province_attache: getCellValue(row, "Province d'attache"),
  }

  if (module === 'sec') {
    return {
      ...baseData,
      nom_denomination: getCellValue(row, 'Dénomination'),
      type_ec: 'SEC',
      categorie_personne: 'Personne Morale',
      statut_professionnel: 'Cabinet',
      raison_sociale: getCellValue(row, 'Raison sociale'),
      associe_gerant: getCellValue(row, 'Associé gérant'),
    }
  }

  if (module === 'en_cabinet') {
    return {
      ...baseData,
      nom_denomination: getCellValue(row, 'Noms'),
      type_ec: 'EC',
      categorie_personne: 'Personne Physique',
      statut_professionnel: 'En Cabinet',
      sexe: getCellValue(row, 'Sexe').toUpperCase(),
      cabinet_attache: getCellValue(row, "Cabinet d'attache"),
    }
  }

  if (module === 'independant') {
    return {
      ...baseData,
      nom_denomination: getCellValue(row, 'Noms'),
      type_ec: 'EC',
      categorie_personne: 'Personne Physique',
      statut_professionnel: 'Indépendant',
      sexe: getCellValue(row, 'Sexe').toUpperCase(),
      nif: getCellValue(row, 'NIF'),
    }
  }

  return {
    ...baseData,
    nom_denomination: getCellValue(row, 'Noms'),
    type_ec: 'EC',
    categorie_personne: 'Personne Physique',
    statut_professionnel: 'Salarié',
    sexe: getCellValue(row, 'Sexe').toUpperCase(),
    nom_employeur: getCellValue(row, "Nom de l'employeur"),
  }
}

const mapApiErrors = (errors: { ligne: number; champ: string; message: string }[] = []): ValidationError[] => {
  return errors.map((error) => ({
    ligne: error.ligne,
    colonne: error.champ,
    erreur: error.message,
  }))
}

export default function ImportModules({ onClose, onSuccess }: ImportModulesProps) {
  const [activeModule, setActiveModule] = useState<ImportModule>('sec')
  const [conflictMode, setConflictMode] = useState<ConflictMode>('update_existing')
  const [showGuide, setShowGuide] = useState(false)
  const [importing, setImporting] = useState(false)
  const [moduleStates, setModuleStates] = useState<Record<ImportModule, ModuleState>>({
    sec: { ...initialState },
    en_cabinet: { ...initialState },
    independant: { ...initialState },
    salarie: { ...initialState },
  })
  const fileInputRef = useRef<HTMLInputElement>(null)

  const activeConfig = modules[activeModule]
  const activeState = moduleStates[activeModule]
  const canImport = activeState.rows.length > 0 && activeState.errors.length === 0 && !importing
  const summary = useMemo(() => {
    const uniqueNumeros = new Set(activeState.rows.map((row) => row.numero_ordre).filter(Boolean)).size
    const cabinets = activeState.rows.filter((row) => row.type_ec === 'SEC').length
    const physical = activeState.rows.length - cabinets
    return { total: activeState.rows.length, uniqueNumeros, cabinets, physical }
  }, [activeState.rows])

  const updateActiveState = (patch: Partial<ModuleState>) => {
    setModuleStates((current) => ({
      ...current,
      [activeModule]: {
        ...current[activeModule],
        ...patch,
      },
    }))
  }

  const downloadTemplate = () => {
    const worksheet = XLSX.utils.json_to_sheet([activeConfig.example])
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, activeConfig.shortTitle)
    XLSX.writeFile(workbook, activeConfig.templateName)
  }

  const downloadErrorsCsv = () => {
    const errors = activeState.result?.errors.length ? activeState.result.errors : activeState.errors
    if (!errors.length) return
    const csv = [
      ['ligne', 'code', 'colonne', 'message'],
      ...errors.map((error) => [String(error.ligne), error.code || '', error.colonne, error.erreur]),
    ]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `rapport_erreurs_${activeConfig.templateName.replace('.xlsx', '.csv')}`
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleFileSelection = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    try {
      const data = await file.arrayBuffer()
      const workbook = XLSX.read(data)
      const worksheet = workbook.Sheets[workbook.SheetNames[0]]
      const { rows: rawRows, missingRequired } = buildRowsFromSheet(worksheet, activeModule)

      if (missingRequired.length) {
        updateActiveState({
          fileName: file.name,
          rawRows,
          rows: [],
          preview: null,
          result: null,
          errors: [{ ligne: 1, colonne: 'entête', erreur: `Colonnes manquantes: ${missingRequired.join(', ')}` }],
        })
        return
      }

      const errors: ValidationError[] = []
      const validRows: PreviewRow[] = []
      const seenNumeros = new Map<string, number>()

      rawRows.forEach((row, index) => {
        const rowErrors = validateRow(activeModule, row, index)
        if (rowErrors.length) {
          errors.push(...rowErrors)
          return
        }

        const transformed = transformToDatabase(activeModule, row)
        if (seenNumeros.has(transformed.numero_ordre)) {
          errors.push({
            ligne: transformed.__rowIndex,
            colonne: "N° d'ordre",
            erreur: `Doublon dans le fichier, déjà présent ligne ${seenNumeros.get(transformed.numero_ordre)}`,
            code: transformed.numero_ordre,
          })
          return
        }

        seenNumeros.set(transformed.numero_ordre, transformed.__rowIndex)
        validRows.push(transformed)
      })

      if (validRows.length === 0 && errors.length === 0) {
        errors.push({ ligne: 1, colonne: 'fichier', erreur: 'Aucune ligne exploitable détectée' })
      }

      let preview: ImportResult | null = null
      if (validRows.length > 0 && errors.length === 0) {
        const previewResponse = await importExperts({
          category: activeModule,
          filename: file.name,
          rows: validRows,
          file_data: rawRows,
          dry_run: true,
          conflict_mode: conflictMode,
        })
        preview = {
          success: previewResponse.success,
          imported: previewResponse.imported,
          created: previewResponse.created,
          updated: previewResponse.updated,
          skipped: previewResponse.skipped,
          total_lignes: previewResponse.total_lignes,
          errors: mapApiErrors(previewResponse.errors),
          message: previewResponse.message,
        }
      }

      updateActiveState({
        fileName: file.name,
        rawRows,
        rows: validRows,
        errors,
        preview,
        result: null,
      })
    } catch (error: any) {
      updateActiveState({
        fileName: file.name,
        rawRows: [],
        rows: [],
        preview: null,
        result: null,
        errors: [{ ligne: 1, colonne: 'fichier', erreur: error?.message || 'Lecture du fichier impossible' }],
      })
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleImport = async () => {
    if (!canImport) return
    setImporting(true)
    try {
      const response = await importExperts({
        category: activeModule,
        filename: activeState.fileName,
        rows: activeState.rows,
        file_data: activeState.rawRows,
        dry_run: false,
        conflict_mode: conflictMode,
      })
      updateActiveState({
        result: {
          success: response.success,
          imported: response.imported,
          created: response.created,
          updated: response.updated,
          skipped: response.skipped,
          total_lignes: response.total_lignes,
          errors: mapApiErrors(response.errors),
          message: response.message,
        },
      })
      if (response.success) {
        onSuccess()
      }
    } catch (error: any) {
      updateActiveState({
        result: {
          success: false,
          imported: 0,
          errors: [],
          message: error?.message || "Erreur lors de l'import",
        },
      })
    } finally {
      setImporting(false)
    }
  }

  const displayedErrors = activeState.result?.errors.length ? activeState.result.errors : activeState.errors

  return (
    <ResponsiveModal
      isOpen
      onClose={onClose}
      title="Importer la liste nationale des experts-comptables"
      size="xl"
      contentClassName={styles.expertImportModalContent}
    >
      <div className={styles.expertImportShell}>
        <div className={styles.expertImportIntro}>
          <p>
            Import national réservé au Conseil National. Chaque catégorie possède son modèle, sa validation, son aperçu et
            son rapport.
          </p>
        </div>

        <div className={styles.expertModuleTabs} role="tablist" aria-label="Catégorie d'import experts-comptables">
          {(Object.keys(modules) as ImportModule[]).map((module) => (
            <button
              key={module}
              type="button"
              role="tab"
              aria-selected={activeModule === module}
              className={`${styles.expertModuleTab} ${activeModule === module ? styles.expertModuleTabActive : ''}`}
              onClick={() => setActiveModule(module)}
              disabled={importing}
            >
              <strong>{modules[module].shortTitle}</strong>
              <span>{modules[module].description}</span>
            </button>
          ))}
        </div>

        <section className={styles.importCard}>
          <div className={styles.importCardHeader}>
            <div>
              <h3>{activeConfig.title}</h3>
              <p className={styles.expertCardHint}>{activeConfig.description}</p>
            </div>
            <span className={`${styles.expertCategoryPill} ${styles[activeConfig.accent]}`}>{activeConfig.shortTitle}</span>
          </div>
          <div className={styles.filePickerRow}>
            <label htmlFor="experts-file-upload" className={styles.filePickerButton}>
              Choisir un fichier
            </label>
            <input
              id="experts-file-upload"
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
          <div className={styles.expertConflictGrid}>
            <label className={`${styles.conflictChoice} ${styles.conflictAdd}`}>
              <input
                type="radio"
                name="expertConflictMode"
                checked={conflictMode === 'add_only'}
                onChange={() => setConflictMode('add_only')}
                disabled={importing}
              />
              <span>
                <strong>Ajouter uniquement les nouveaux experts</strong>
                <small>Les numéros d’ordre déjà présents sont ignorés sans modifier les fiches existantes.</small>
              </span>
            </label>
            <label className={`${styles.conflictChoice} ${styles.conflictUpdate}`}>
              <input
                type="radio"
                name="expertConflictMode"
                checked={conflictMode === 'update_existing'}
                onChange={() => setConflictMode('update_existing')}
                disabled={importing}
              />
              <span>
                <strong>Mettre à jour les experts existants (recommandé)</strong>
                <small>Le numéro d’ordre est conservé; les champs importés actualisent la fiche nationale.</small>
              </span>
            </label>
          </div>
        </section>

        <section className={styles.importGridSection}>
          <div className={styles.importCard}>
            <h3>Résumé avant import</h3>
            <div className={styles.summaryGrid}>
              <span>Catégorie<strong>{activeConfig.shortTitle}</strong></span>
              <span>Lignes détectées<strong>{summary.total}</strong></span>
              <span>N° d’ordre uniques<strong>{summary.uniqueNumeros}</strong></span>
              <span>Personnes physiques<strong>{summary.physical}</strong></span>
              <span>Cabinets<strong>{summary.cabinets}</strong></span>
              <span>Mode conflit<strong>{conflictMode === 'add_only' ? 'Ajout seul' : 'Mise à jour'}</strong></span>
            </div>
            {activeState.preview && (
              <div className={styles.expertPreviewStats}>
                <span>Créations prévues: {activeState.preview.created ?? 0}</span>
                <span>Mises à jour prévues: {activeState.preview.updated ?? 0}</span>
                <span>Ignorés: {activeState.preview.skipped ?? 0}</span>
              </div>
            )}
          </div>

          <div className={styles.importCard}>
            <h3>Aperçu avant import</h3>
            {activeState.rows.length > 0 ? (
              <div className={styles.expertPreviewList}>
                {activeState.rows.slice(0, 5).map((row) => (
                  <div className={styles.expertPreviewRow} key={`${row.numero_ordre}-${row.__rowIndex}`}>
                    <strong>{row.numero_ordre}</strong>
                    <span>{row.nom_denomination}</span>
                    <em>{row.statut_professionnel || row.type_ec}</em>
                  </div>
                ))}
                {activeState.rows.length > 5 && <p>{activeState.rows.length - 5} ligne(s) supplémentaires.</p>}
              </div>
            ) : (
              <p className={styles.emptyPreview}>Sélectionnez un fichier Excel compatible avec la catégorie active.</p>
            )}
          </div>
        </section>

        {showGuide && (
          <section className={styles.importGuide}>
            <strong>Guide d'import</strong>
            <span>Colonnes obligatoires: {activeConfig.required.join(', ')}.</span>
            <span>Colonnes optionnelles: {activeConfig.optional.join(', ')}.</span>
            <span>Le fichier sélectionné est validé uniquement pour la catégorie active.</span>
          </section>
        )}

        {(displayedErrors.length > 0 || activeState.result) && (
          <section
            className={`${styles.importReport} ${
              activeState.result?.success ? styles.reportSuccess : displayedErrors.length ? styles.reportError : ''
            }`}
          >
            <div className={styles.reportHeader}>
              <h3>{activeState.result ? "Rapport d'import" : 'Validation du fichier'}</h3>
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
                <span>Erreurs: {displayedErrors.length}</span>
              </div>
            )}
            {displayedErrors.length > 0 && (
              <div className={styles.errorList}>
                {displayedErrors.slice(0, 5).map((error, index) => (
                  <span key={`${error.ligne}-${index}`}>
                    Ligne {error.ligne} · {error.code ? `${error.code} · ` : ''}
                    {error.colonne}: {error.erreur}
                  </span>
                ))}
                {displayedErrors.length > 5 && <span>{displayedErrors.length - 5} erreur(s) supplémentaire(s).</span>}
              </div>
            )}
          </section>
        )}

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
            {importing ? 'Import en cours...' : `Importer ${activeConfig.shortTitle}`}
          </button>
        </footer>
      </div>
    </ResponsiveModal>
  )
}
