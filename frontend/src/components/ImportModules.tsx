import { useState, useRef } from 'react'
import * as XLSX from 'xlsx'
import { importExperts, CategoryType, ExpertImportRow } from '../api/experts'
import styles from './ImportModules.module.css'

type ImportModule = CategoryType

interface ValidationError {
  ligne: number
  colonne: string
  erreur: string
}

interface ImportResult {
  success: boolean
  imported: number
  updated?: number
  skipped?: number
  total_lignes?: number
  errors: ValidationError[]
  message: string
}

interface ImportModulesProps {
  onClose: () => void
  onSuccess: () => void
}

export default function ImportModules({ onClose, onSuccess }: ImportModulesProps) {
  const [selectedModule, setSelectedModule] = useState<ImportModule | null>(null)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const modules = {
    sec: {
      title: 'SEC - Sociétés d\'Expertise Comptable',
      description: 'Import des personnes morales (cabinets)',
      required: ['N° d\'ordre', 'Dénomination', 'Raison sociale', 'Associé gérant'],
      optional: ['N° de téléphone', 'E-mail'],
      example: {
        "N° d'ordre": "001",
        "Dénomination": "Cabinet Expert Conseil",
        "Raison sociale": "Expert Conseil SARL",
        "N° de téléphone": "+243 XXX XXX XXX",
        "E-mail": "contact@expertconseil.cd",
        "Associé gérant": "Jean DUPONT"
      }
    },
    en_cabinet: {
      title: 'Experts-comptables en cabinet',
      description: 'Import des experts travaillant en cabinet',
      required: ['N° d\'ordre', 'Noms', 'Sexe', 'Cabinet d\'attache'],
      optional: ['N° de téléphone', 'E-mail'],
      example: {
        "N° d'ordre": "101",
        "Noms": "MUKENDI Pierre",
        "Sexe": "M",
        "N° de téléphone": "+243 XXX XXX XXX",
        "E-mail": "pmukendi@cabinet.cd",
        "Cabinet d'attache": "Cabinet Expert Conseil"
      }
    },
    independant: {
      title: 'Experts-comptables indépendants',
      description: 'Import des experts indépendants',
      required: ['N° d\'ordre', 'Noms', 'Sexe', 'NIF'],
      optional: ['N° de téléphone', 'E-mail'],
      example: {
        "N° d'ordre": "201",
        "Noms": "KALALA Marie",
        "Sexe": "F",
        "N° de téléphone": "+243 XXX XXX XXX",
        "E-mail": "mkalala@gmail.com",
        "NIF": "A1234567X"
      }
    },
    salarie: {
      title: 'Experts-comptables salariés',
      description: 'Import des experts salariés',
      required: ['N° d\'ordre', 'Noms', 'Sexe', 'Nom de l\'employeur'],
      optional: ['N° de téléphone', 'E-mail'],
      example: {
        "N° d'ordre": "301",
        "Noms": "MBALA Joseph",
        "Sexe": "M",
        "N° de téléphone": "+243 XXX XXX XXX",
        "E-mail": "jmbala@entreprise.cd",
        "Nom de l'employeur": "Société ABC"
      }
    }
  }

  const normalizeEmail = (raw: any): string | undefined => {
    if (raw === null || raw === undefined) return undefined
    const value = String(raw).trim()
    return value ? value : undefined
  }

  const normalizePhone = (raw: any): string | undefined => {
    if (raw === null || raw === undefined) return undefined
    const rawStr = String(raw).trim()
    if (!rawStr) return undefined
    const hasPlus = rawStr.startsWith('+')
    const digits = rawStr.replace(/\D/g, '')
    if (!digits) return undefined
    if (hasPlus) return `+${digits}`
    if (digits.startsWith('0') && digits.length === 10) return `+243${digits.slice(1)}`
    if (digits.length === 9) return `+243${digits}`
    if (digits.startsWith('243')) return `+${digits}`
    return undefined
  }

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

  const buildRowsFromSheet = (worksheet: XLSX.WorkSheet, module: ImportModule) => {
    const expectedHeaders = [...modules[module].required, ...modules[module].optional]
    const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '' }) as any[][]
    if (!rawRows.length) return { headers: [], rows: [] as any[] }

    const headerRowIndex = pickHeaderRowIndex(rawRows, expectedHeaders)
    const rawHeaders = (rawRows[headerRowIndex] || []).map((h: any) => String(h ?? '').trim())
    const normalizedExpected = new Map(
      expectedHeaders.map((h) => [normalizeHeader(h), h])
    )
    const normalizedHeaders = rawHeaders.map((h) => normalizeHeader(h))
    const mappedHeaders = rawHeaders.map((h) => normalizedExpected.get(normalizeHeader(h)) || h)

    console.log('[Import Experts] Header row index:', headerRowIndex + 1)
    console.log('[Import Experts] Headers raw:', rawHeaders)
    console.log('[Import Experts] Headers normalized:', normalizedHeaders)
    console.log('[Import Experts] Header mapping:', mappedHeaders)

    const presentHeaderSet = new Set(normalizedHeaders.filter(Boolean))
    const missingRequired = modules[module].required.filter(
      (h) => !presentHeaderSet.has(normalizeHeader(h))
    )
    if (missingRequired.length > 0) {
      console.log('[Import Experts] Missing required headers after normalization:', missingRequired)
      console.log('[Import Experts] Expected headers:', expectedHeaders)
    }

    const dataRows = rawRows.slice(headerRowIndex + 1)
    const rows = dataRows.map((row, rowOffset) => {
      const rowObj: Record<string, any> = {}
      mappedHeaders.forEach((header, idx) => {
        const key = String(header ?? '').trim()
        if (!key) return
        rowObj[key] = idx < row.length ? row[idx] : ''
      })
      rowObj.__rowIndex = headerRowIndex + 2 + rowOffset
      return rowObj
    }).filter((rowObj) => {
      const hasValue = mappedHeaders.some((header) => {
        const key = String(header ?? '').trim()
        if (!key) return false
        const value = rowObj[key]
        return value !== null && value !== undefined && String(value).trim() !== ''
      })
      return hasValue
    })

    return { headers: mappedHeaders, rows }
  }

  const getCellValue = (row: any, key: string): string => {
    const value = row?.[key]
    if (value === null || value === undefined) return ''
    return String(value).trim()
  }

  const validateSexe = (sexe: string): boolean => {
    return ['M', 'F', 'm', 'f'].includes(sexe)
  }

  const validateSEC = (row: any, index: number): ValidationError[] => {
    const errors: ValidationError[] = []
    const ligne = typeof row?.__rowIndex === 'number' ? row.__rowIndex : index + 2

    if (!getCellValue(row, "N° d'ordre")) {
      errors.push({ ligne, colonne: "N° d'ordre", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Dénomination")) {
      errors.push({ ligne, colonne: "Dénomination", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Raison sociale")) {
      errors.push({ ligne, colonne: "Raison sociale", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Associé gérant")) {
      errors.push({ ligne, colonne: "Associé gérant", erreur: "Champ obligatoire manquant" })
    }

    return errors
  }

  const validateEnCabinet = (row: any, index: number): ValidationError[] => {
    const errors: ValidationError[] = []
    const ligne = typeof row?.__rowIndex === 'number' ? row.__rowIndex : index + 2

    if (!getCellValue(row, "N° d'ordre")) {
      errors.push({ ligne, colonne: "N° d'ordre", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Noms")) {
      errors.push({ ligne, colonne: "Noms", erreur: "Champ obligatoire manquant" })
    }
    const sexeValue = getCellValue(row, "Sexe")
    if (!sexeValue) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Champ obligatoire manquant" })
    } else if (!validateSexe(sexeValue)) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Doit être M ou F" })
    }
    if (!getCellValue(row, "Cabinet d'attache")) {
      errors.push({ ligne, colonne: "Cabinet d'attache", erreur: "Champ obligatoire manquant" })
    }

    return errors
  }

  const validateIndependant = (row: any, index: number): ValidationError[] => {
    const errors: ValidationError[] = []
    const ligne = typeof row?.__rowIndex === 'number' ? row.__rowIndex : index + 2

    if (!getCellValue(row, "N° d'ordre")) {
      errors.push({ ligne, colonne: "N° d'ordre", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Noms")) {
      errors.push({ ligne, colonne: "Noms", erreur: "Champ obligatoire manquant" })
    }
    const sexeValue = getCellValue(row, "Sexe")
    if (!sexeValue) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Champ obligatoire manquant" })
    } else if (!validateSexe(sexeValue)) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Doit être M ou F" })
    }
    if (!getCellValue(row, "NIF")) {
      errors.push({ ligne, colonne: "NIF", erreur: "Champ obligatoire manquant" })
    }

    return errors
  }

  const validateSalarie = (row: any, index: number): ValidationError[] => {
    const errors: ValidationError[] = []
    const ligne = typeof row?.__rowIndex === 'number' ? row.__rowIndex : index + 2

    if (!getCellValue(row, "N° d'ordre")) {
      errors.push({ ligne, colonne: "N° d'ordre", erreur: "Champ obligatoire manquant" })
    }
    if (!getCellValue(row, "Noms")) {
      errors.push({ ligne, colonne: "Noms", erreur: "Champ obligatoire manquant" })
    }
    const sexeValue = getCellValue(row, "Sexe")
    if (!sexeValue) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Champ obligatoire manquant" })
    } else if (!validateSexe(sexeValue)) {
      errors.push({ ligne, colonne: "Sexe", erreur: "Doit être M ou F" })
    }
    if (!getCellValue(row, "Nom de l'employeur")) {
      errors.push({ ligne, colonne: "Nom de l'employeur", erreur: "Champ obligatoire manquant" })
    }

    return errors
  }

  const transformToDatabase = (module: ImportModule, row: any): ExpertImportRow => {
    const emailRaw = normalizeEmail(getCellValue(row, "E-mail"))
    const baseData = {
      numero_ordre: getCellValue(row, "N° d'ordre"),
      email: emailRaw,
      telephone: normalizePhone(getCellValue(row, "N° de téléphone")),
    }

    switch (module) {
      case 'sec':
        return {
          ...baseData,
          nom_denomination: getCellValue(row, "Dénomination"),
          type_ec: 'SEC',
          categorie_personne: 'Personne Morale',
          statut_professionnel: 'Cabinet',
          raison_sociale: getCellValue(row, "Raison sociale"),
          associe_gerant: getCellValue(row, "Associé gérant"),
        }

      case 'en_cabinet':
        return {
          ...baseData,
          nom_denomination: getCellValue(row, "Noms"),
          type_ec: 'EC',
          categorie_personne: 'Personne Physique',
          statut_professionnel: 'En Cabinet',
          sexe: getCellValue(row, "Sexe").toUpperCase(),
          cabinet_attache: getCellValue(row, "Cabinet d'attache"),
        }

      case 'independant':
        return {
          ...baseData,
          nom_denomination: getCellValue(row, "Noms"),
          type_ec: 'EC',
          categorie_personne: 'Personne Physique',
          statut_professionnel: 'Indépendant',
          sexe: getCellValue(row, "Sexe").toUpperCase(),
          nif: getCellValue(row, "NIF"),
        }

      case 'salarie':
        return {
          ...baseData,
          nom_denomination: getCellValue(row, "Noms"),
          type_ec: 'EC',
          categorie_personne: 'Personne Physique',
          statut_professionnel: 'Salarié',
          sexe: getCellValue(row, "Sexe").toUpperCase(),
          nom_employeur: getCellValue(row, "Nom de l'employeur"),
        }

      default:
        return { ...baseData, nom_denomination: '' }
    }
  }

  const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedModule) return

    const file = e.target.files?.[0]
    if (!file) return

    setImporting(true)
    setResult(null)

    try {
      const data = await file.arrayBuffer()
      const workbook = XLSX.read(data)
      const worksheet = workbook.Sheets[workbook.SheetNames[0]]
      const { rows: jsonData } = buildRowsFromSheet(worksheet, selectedModule)

      if (jsonData.length === 0) {
        setResult({
          success: false,
          imported: 0,
          errors: [],
          message: 'Le fichier Excel est vide'
        })
        setImporting(false)
        return
      }

      const allErrors: ValidationError[] = []
      const validRows: any[] = []
      const validRowIndices: number[] = []

      jsonData.forEach((row, index) => {
        let errors: ValidationError[] = []

        switch (selectedModule) {
          case 'sec':
            errors = validateSEC(row, index)
            break
          case 'en_cabinet':
            errors = validateEnCabinet(row, index)
            break
          case 'independant':
            errors = validateIndependant(row, index)
            break
          case 'salarie':
            errors = validateSalarie(row, index)
            break
        }

        if (errors.length > 0) {
          allErrors.push(...errors)
        } else {
          validRows.push(transformToDatabase(selectedModule, row))
          validRowIndices.push(
            typeof (row as any)?.__rowIndex === 'number' ? (row as any).__rowIndex : index + 2
          )
        }
      })

      if (allErrors.length > 0) {
        setResult({
          success: false,
          imported: 0,
          errors: allErrors,
          message: `${allErrors.length} erreur(s) de validation détectée(s)`
        })
        setImporting(false)
        return
      }

      if (validRows.length === 0) {
        setResult({
          success: false,
          imported: 0,
          errors: [],
          message: 'Aucune ligne valide à importer'
        })
        setImporting(false)
        return
      }

      const numeroOrdreMap = new Map<string, number[]>()
      validRows.forEach((row, index) => {
        const numero = row.numero_ordre
        if (!numeroOrdreMap.has(numero)) {
          numeroOrdreMap.set(numero, [])
        }
        numeroOrdreMap.get(numero)!.push(index)
      })

      const duplicateErrors: ValidationError[] = []
      numeroOrdreMap.forEach((indices, numero) => {
        if (indices.length > 1) {
          indices.forEach(idx => {
            const ligneExcel = validRowIndices[idx] ?? idx + 2
            duplicateErrors.push({
              ligne: ligneExcel,
              colonne: "N° d'ordre",
              erreur: `Doublon détecté : le N° d'ordre "${numero}" apparaît ${indices.length} fois dans le fichier`
            })
          })
        }
      })

      if (duplicateErrors.length > 0) {
        setResult({
          success: false,
          imported: 0,
          errors: duplicateErrors,
          message: `${duplicateErrors.length} doublon(s) détecté(s) dans le fichier Excel`
        })
        setImporting(false)
        return
      }

      // Appel API FastAPI pour import
      const importResponse = await importExperts({
        category: selectedModule,
        filename: file.name,
        rows: validRows,
        file_data: jsonData,
      })

      const apiErrors = (importResponse.errors || []).map((err) => ({
        ligne: err.ligne,
        colonne: err.champ,
        erreur: err.message,
      }))

      setResult({
        success: importResponse.success,
        imported: importResponse.imported,
        updated: importResponse.updated,
        skipped: importResponse.skipped,
        total_lignes: importResponse.total_lignes,
        errors: apiErrors,
        message: importResponse.message
      })

      if (importResponse.success) {
        setTimeout(() => {
          onSuccess()
          onClose()
        }, 2000)
      }

    } catch (error: any) {
      console.error('Erreur lors de l\'import:', error)
      setResult({
        success: false,
        imported: 0,
        errors: [],
        message: error.message || 'Une erreur inattendue est survenue'
      })
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const downloadTemplate = (module: ImportModule) => {
    const moduleConfig = modules[module]
    const worksheet = XLSX.utils.json_to_sheet([moduleConfig.example])
    const telCell = worksheet['E2']
    if (telCell) telCell.z = '@'
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Modèle')
    XLSX.writeFile(workbook, `modele_${module}.xlsx`)
  }

  if (!selectedModule) {
    return (
      <div className={styles.modal}>
        <div className={styles.modalContent}>
          <div className={styles.modalHeader}>
            <h2>Choisir un module d'importation</h2>
            <button onClick={onClose} className={styles.closeBtn}>×</button>
          </div>

          <div className={styles.modulesGrid}>
            {Object.entries(modules).map(([key, config]) => (
              <div
                key={key}
                className={styles.moduleCard}
                onClick={() => setSelectedModule(key as ImportModule)}
              >
                <h3>{config.title}</h3>
                <p>{config.description}</p>
                <div className={styles.moduleInfo}>
                  <span className={styles.requiredBadge}>
                    {config.required.length} champs obligatoires
                  </span>
                  <span className={styles.optionalBadge}>
                    {config.optional.length} champs optionnels
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  const currentModule = modules[selectedModule]

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <div>
            <button
              onClick={() => setSelectedModule(null)}
              className={styles.backBtn}
            >
              ← Retour
            </button>
            <h2>{currentModule.title}</h2>
            <p>{currentModule.description}</p>
          </div>
          <button onClick={onClose} className={styles.closeBtn}>×</button>
        </div>

        <div className={styles.importContent}>
          <div className={styles.columnsInfo}>
            <div className={styles.columnsSection}>
              <h4>Colonnes obligatoires</h4>
              <ul className={styles.columnsList}>
                {currentModule.required.map(col => (
                  <li key={col} className={styles.requiredCol}>
                    <span className={styles.colIcon}>*</span>
                    {col}
                  </li>
                ))}
              </ul>
            </div>

            <div className={styles.columnsSection}>
              <h4>Colonnes optionnelles</h4>
              <ul className={styles.columnsList}>
                {currentModule.optional.map(col => (
                  <li key={col} className={styles.optionalCol}>
                    <span className={styles.colIcon}>○</span>
                    {col}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className={styles.actions}>
            <button
              onClick={() => downloadTemplate(selectedModule)}
              className={styles.downloadBtn}
            >
              📥 Télécharger le modèle Excel
            </button>

            <div className={styles.uploadSection}>
              <label htmlFor="file-upload" className={styles.uploadBtn}>
                📤 Sélectionner le fichier à importer
              </label>
              <input
                id="file-upload"
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileImport}
                disabled={importing}
                className={styles.fileInput}
              />
            </div>
          </div>

          {importing && (
            <div className={styles.loading}>
              <div className={styles.spinner}></div>
              <p>Importation en cours...</p>
            </div>
          )}

          {result && (
            <div className={`${styles.result} ${result.success ? styles.resultSuccess : styles.resultError}`}>
              <div className={styles.resultHeader}>
                <span className={styles.resultIcon}>
                  {result.success ? '✓' : '✕'}
                </span>
                <h4>{result.message}</h4>
              </div>

              {result.success && (
                <div className={styles.resultSummary}>
                  <p>
                    Total lignes: <strong>{result.total_lignes ?? result.imported}</strong> •
                    Importées: <strong>{result.imported}</strong> •
                    Mises à jour: <strong>{result.updated ?? 0}</strong> •
                    Ignorées: <strong>{result.skipped ?? 0}</strong>
                  </p>
                </div>
              )}

              {result.errors.length > 0 && (
                <div className={styles.errorsList}>
                  <h5>Erreurs détectées:</h5>
                  <div className={styles.errorsTable}>
                    <table>
                      <thead>
                        <tr>
                          <th>Ligne</th>
                          <th>Colonne</th>
                          <th>Erreur</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.errors.slice(0, 20).map((err, idx) => (
                          <tr key={idx}>
                            <td>{err.ligne}</td>
                            <td>{err.colonne}</td>
                            <td>{err.erreur}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {result.errors.length > 20 && (
                      <p className={styles.moreErrors}>
                        ... et {result.errors.length - 20} autres erreurs
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
