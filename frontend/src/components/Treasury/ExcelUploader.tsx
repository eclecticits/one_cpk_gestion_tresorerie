import { useState } from 'react'
import styles from './ExcelUploader.module.css'
import { importTreasuryExcel, type TreasuryImportResult } from '../../api/treasury'

interface ExcelUploaderProps {
  onUploadComplete: (results: TreasuryImportResult[]) => void
}

export default function ExcelUploader({ onUploadComplete }: ExcelUploaderProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleFile = async (file: File | null) => {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const res = await importTreasuryExcel(file)
      onUploadComplete(res.data || [])
    } catch (err: any) {
      setError(err?.message || "Erreur d'import")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className={styles.wrapper}>
      <label htmlFor="excel-upload" className={styles.dropzone}>
        <div className={styles.icon}>⇪</div>
        <h3>Importer un releve (Excel/CSV)</h3>
        <p>Glissez votre fichier ici pour une classification IA automatique</p>
        <span className={styles.cta}>{uploading ? 'Import en cours...' : 'Choisir un fichier'}</span>
        <input
          id="excel-upload"
          type="file"
          accept=".xlsx,.xls,.csv"
          onChange={(e) => handleFile(e.target.files?.[0] || null)}
          disabled={uploading}
        />
      </label>
      {error && <div className={styles.error}>{error}</div>}
    </div>
  )
}
