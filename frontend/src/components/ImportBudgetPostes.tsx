import { useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { importBudgetPostes } from '../api/budget'
import styles from './ImportModules.module.css'

interface ValidationError {
  ligne: number
  colonne: string
  erreur: string
}

interface ImportBudgetPostesProps {
  annee: number
  type: 'DEPENSE' | 'RECETTE'
  onClose: () => void
  onSuccess: () => void
}

const requiredHeaders = ['code', 'libelle', 'plafond']
const optionalHeaders = ['parent_code']

const normalizeHeader = (raw: any): string => {
  if (raw === null || raw === undefined) return ''
  const value = String(raw)
    .replace(/\u00a0/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
}

const pickHeaderRowIndex = (rows: any[][], expectedHeaders: string[]): number => {
  if (rows.length === 0) return 0
  const expected = new Set(expectedHeaders.map(normalizeHeader))
  let bestIndex = 0
  let bestMatch = 0
  rows.slice(0, 5).forEach((row, idx) => {
    const matchCount = row.reduce((count: number, cell: any) => {
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
  const expectedHeaders = [...requiredHeaders, ...optionalHeaders]
  const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' }) as any[][]
  if (!rawRows.length) return { headers: [], rows: [] as any[] }

  const headerRowIndex = pickHeaderRowIndex(rawRows, expectedHeaders)
  const rawHeaders = (rawRows[headerRowIndex] || []).map((h: any) => String(h ?? '').trim())
  const normalizedExpected = new Map(
    expectedHeaders.map((h) => [normalizeHeader(h), h])
  )
  const normalizedHeaders = rawHeaders.map((h) => normalizeHeader(h))
  const mappedHeaders = rawHeaders.map((h) => normalizedExpected.get(normalizeHeader(h)) || h)

  const presentHeaderSet = new Set(normalizedHeaders.filter(Boolean))
  const missingRequired = requiredHeaders.filter(
    (h) => !presentHeaderSet.has(normalizeHeader(h))
  )

  const dataRows = rawRows.slice(headerRowIndex + 1)
  const rows = dataRows.map((row) => {
    const rowObj: Record<string, any> = {}
    mappedHeaders.forEach((header, idx) => {
      const key = String(header ?? '').trim()
      if (!key) return
      rowObj[key] = idx < row.length ? row[idx] : ''
    })
    return rowObj
  })

  return { headers: mappedHeaders, rows, missingRequired }
}

export default function ImportBudgetPostes({ annee, type, onClose, onSuccess }: ImportBudgetPostesProps) {
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string; errors: ValidationError[] } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const downloadTemplate = () => {
    const rows = [
      {
        code: 'II',
        libelle: 'DEPENSES DE FONCTIONNEMENT',
        plafond: 0,
        parent_code: '',
      },
      {
        code: 'II.1',
        libelle: 'Personnel',
        plafond: 150000,
        parent_code: 'II',
      },
    ]
    const worksheet = XLSX.utils.json_to_sheet(rows)
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Modele')
    XLSX.writeFile(workbook, 'modele_postes_budgetaires.xlsx')
  }

  const validateRow = (row: any, index: number): ValidationError[] => {
    const errors: ValidationError[] = []
    const ligne = index + 2
    const codeValue = String(row.code || '').trim()
    const parentCodeValue = String(row.parent_code || '').trim()
    const libelleValue = String(row.libelle || '').trim()
    const plafondValue = row.plafond
    const plafondIsEmpty = plafondValue === '' || plafondValue === null || plafondValue === undefined
    const plafondIsZero = !plafondIsEmpty && Number(plafondValue) === 0
    const isEmptyRow = !codeValue && !libelleValue && !parentCodeValue && (plafondIsEmpty || plafondIsZero)
    if (isEmptyRow) {
      return []
    }

    if (!codeValue) {
      errors.push({ ligne, colonne: 'code', erreur: 'Champ obligatoire manquant' })
    }
    if (!libelleValue) {
      errors.push({ ligne, colonne: 'libelle', erreur: 'Champ obligatoire manquant' })
    }
    return errors
  }

  const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setImporting(true)
    setResult(null)

    try {
      const data = await file.arrayBuffer()
      const workbook = XLSX.read(data)
      const worksheet = workbook.Sheets[workbook.SheetNames[0]]
      const { rows: jsonData, missingRequired } = buildRowsFromSheet(worksheet)

      if (missingRequired?.length) {
        setResult({
          success: false,
          message: `Colonnes manquantes: ${missingRequired.join(', ')}`,
          errors: [],
        })
        setImporting(false)
        return
      }

      if (jsonData.length === 0) {
        setResult({ success: false, message: 'Le fichier Excel est vide', errors: [] })
        setImporting(false)
        return
      }

      const allErrors: ValidationError[] = []
      const validRows: any[] = []

      jsonData.forEach((row, index) => {
        const errors = validateRow(row, index)
        const codeValue = String(row.code || '').trim()
        const libelleValue = String(row.libelle || '').trim()
        const parentCodeValue = String(row.parent_code || '').trim()
        const plafondValue = row.plafond
        const plafondIsEmpty = plafondValue === '' || plafondValue === null || plafondValue === undefined
        const plafondIsZero = !plafondIsEmpty && Number(plafondValue) === 0
        const isEmptyRow = !codeValue && !libelleValue && !parentCodeValue && (plafondIsEmpty || plafondIsZero)

        if (isEmptyRow) {
          return
        }
        if (errors.length > 0) {
          allErrors.push(...errors)
        } else {
          validRows.push({
            code: codeValue,
            libelle: libelleValue,
            plafond: plafondIsEmpty ? 0 : Number(plafondValue) || 0,
            parent_code: parentCodeValue ? parentCodeValue : undefined,
          })
        }
      })

      if (allErrors.length > 0) {
        setResult({
          success: false,
          message: `${allErrors.length} erreur(s) de validation détectée(s)`,
          errors: allErrors,
        })
        setImporting(false)
        return
      }

      if (validRows.length === 0) {
        setResult({ success: false, message: 'Aucune ligne valide à importer', errors: [] })
        setImporting(false)
        return
      }

      const res = await importBudgetPostes({
        annee,
        type,
        filename: file.name,
        rows: validRows,
      })

      if (!res.success) {
        setResult({ success: false, message: res.message, errors: [] })
        setImporting(false)
        return
      }

      if (res.errors && res.errors.length > 0) {
        const mapped = res.errors.map((err) => ({
          ligne: err.ligne,
          colonne: err.champ,
          erreur: err.message,
        }))
        setResult({ success: false, message: res.message, errors: mapped })
        setImporting(false)
        return
      }

      setResult({ success: true, message: res.message, errors: [] })
      onSuccess()
    } catch (error: any) {
      setResult({
        success: false,
        message: error?.message || 'Erreur lors de l\'import',
        errors: [],
      })
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <div>
            <h2>Importer des postes budgétaires</h2>
            <div className={styles.typeBadgeRow}>
              <span className={styles.typeBadge}>
                {type === 'RECETTE' ? 'Import Recettes (Objectifs)' : 'Import Dépenses (Plafonds)'}
              </span>
            </div>
            <p>Format attendu: code, libelle, plafond, parent_code (optionnel, vide = poste racine)</p>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            ×
          </button>
        </div>

        <div className={styles.importContent}>
          <div className={styles.columnsInfo}>
            <div className={styles.columnsSection}>
              <h4>Colonnes obligatoires</h4>
              <ul className={styles.columnsList}>
                {requiredHeaders.map((col) => (
                  <li key={col} className={styles.requiredCol}>
                    <span className={styles.colIcon}>*</span> {col}
                  </li>
                ))}
              </ul>
            </div>
            <div className={styles.columnsSection}>
              <h4>Colonnes optionnelles</h4>
              <ul className={styles.columnsList}>
                {optionalHeaders.map((col) => (
                  <li key={col} className={styles.optionalCol}>
                    <span className={styles.colIcon}>+</span> {col}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.downloadBtn}
              onClick={downloadTemplate}
              disabled={importing}
            >
              📥 Télécharger le modèle Excel
            </button>
            <div className={styles.uploadSection}>
              <label htmlFor="budget-postes-file" className={styles.uploadBtn}>
                📤 Sélectionner le fichier à importer
              </label>
              <input
                id="budget-postes-file"
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileImport}
                disabled={importing}
                className={styles.fileInput}
              />
            </div>
            <div>
              <strong>Conflits:</strong> Ignorer si le code existe déjà.
            </div>
          </div>

          {importing && <p>Import en cours...</p>}

          {result && (
            <div className={`${styles.result} ${result.success ? styles.resultSuccess : styles.resultError}`}>
              <div className={styles.resultHeader}>
                <div className={styles.resultIcon}>{result.success ? '✓' : '!'}</div>
                <h4>{result.success ? 'Import terminé' : 'Import échoué'}</h4>
              </div>
              <div className={styles.resultSummary}>
                <p>{result.message}</p>
              </div>
              {result.errors.length > 0 && (
                <div className={styles.errorsTable}>
                  <h5>Erreurs détectées</h5>
                  <table>
                    <thead>
                      <tr>
                        <th>Ligne</th>
                        <th>Colonne</th>
                        <th>Erreur</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.errors.map((err, idx) => (
                        <tr key={`${err.ligne}-${idx}`}>
                          <td>{err.ligne}</td>
                          <td>{err.colonne}</td>
                          <td>{err.erreur}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
