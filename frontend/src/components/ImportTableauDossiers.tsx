import { useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { uploadTableauExcel, type TableauImportResult } from '../api/tableau'
import styles from './ImportModules.module.css'

interface ImportTableauDossiersProps {
  exercice: string
  onImported: (importId: number | null) => void
}

// Contrat d'import — ce que l'application attend (procédé aligné sur budget).
const requiredHeaders = ['numero_ordre', 'nom', 'categorie']
const optionalHeaders = [
  'cotisation', 'assurance', 'chiffre_affaires', 'heures_formation',
  'date_naissance', 'anciennete', 'sexe', 'telephone', 'email', 'cabinet', 'nif',
]

const CATEGORIES = ['Société', 'EC Cabinet', 'EC Indépendant', 'EC Salarié', 'Stagiaire']

export default function ImportTableauDossiers({ exercice, onImported }: ImportTableauDossiersProps) {
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string; errors: TableauImportResult['errors'] } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!exercice.trim()) {
      setResult({ success: false, message: 'Veuillez saisir un exercice avant l\'import.', errors: [] })
      e.target.value = ''
      return
    }

    setImporting(true)
    setResult(null)
    try {
      const res = await uploadTableauExcel(exercice.trim(), file)
      setResult({
        success: res.success,
        message: res.message,
        errors: res.errors || [],
      })
      if (res.success) onImported(res.import_id)
    } catch (error: any) {
      const msg = error?.data?.detail || error?.message || 'Erreur lors de l\'import.'
      setResult({ success: false, message: String(msg), errors: [] })
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  return (
    <div className={styles.importContent}>
      <p style={{ fontSize: '13px', color: '#374151', marginBottom: '4px' }}>
        <strong>Format attendu :</strong> une feuille par section (Société, Cabinet, Indépendant, Salariés,
        Stagiaires) <em>ou</em> une feuille à plat avec une colonne <code>categorie</code>. Les en-têtes peuvent
        être sur n'importe quelle ligne — le parseur les détecte.
      </p>

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
          <p style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px' }}>
            categorie ∈ {CATEGORIES.join(' / ')}
          </p>
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
          <p style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px' }}>
            cotisation / assurance / chiffre_affaires = OUI ou NON · heures_formation = nombre (NHV)
          </p>
        </div>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.downloadBtn} onClick={downloadTemplate} disabled={importing}>
          📥 Télécharger le modèle Excel
        </button>
        <div className={styles.uploadSection}>
          <label htmlFor="tableau-membres-file" className={styles.uploadBtn}>
            📤 Sélectionner le fichier à importer
          </label>
          <input
            id="tableau-membres-file"
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleFileImport}
            disabled={importing}
            className={styles.fileInput}
          />
        </div>
        <div>
          <strong>Conclusion :</strong> calculée à l'analyse (INSCRIT / NON INSCRIT / À DÉLIBÉRER).
        </div>
      </div>

      {importing && <p>Import en cours…</p>}

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
              <h5>Avertissements</h5>
              <table>
                <thead>
                  <tr>
                    <th>Ligne</th>
                    <th>Colonne</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((err, idx) => (
                    <tr key={`${err.ligne ?? idx}-${idx}`}>
                      <td>{err.ligne ?? '—'}</td>
                      <td>{err.champ ?? '—'}</td>
                      <td>{err.message ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
