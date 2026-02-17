import { useEffect, useMemo, useState } from 'react'
import styles from './RequisitionPdfSmart.module.css'
import {
  parseRequisitionPdf,
  PdfRequisitionParseResponse,
  importRequisitionsFromPdf,
  validateImportedRequisition,
} from '../api/pdfRequisitions'

const emptyResult: PdfRequisitionParseResponse = {
  items: [],
  raw_text_excerpt: '',
  warnings: [],
  total_items: 0,
  matched: 0,
  conflicts: 0,
  missing: 0,
}

const statusLabel = (value: string) => {
  if (value === 'found') return 'Enregistré ✅'
  if (value === 'missing') return 'Manquant'
  if (value === 'conflict') return 'Conflit ⚠️'
  return 'Non détecté'
}

export default function RequisitionPdfSmart() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [validatingId, setValidatingId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'missing' | 'conflict' | 'found'>('all')
  const [result, setResult] = useState<PdfRequisitionParseResponse>(emptyResult)
  const [error, setError] = useState<string | null>(null)

  const previewUrl = useMemo(() => {
    if (!file) return ''
    return URL.createObjectURL(file)
  }, [file])

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const handleUpload = async (selected: File) => {
    setLoading(true)
    setError(null)
    try {
      const parsed = await parseRequisitionPdf(selected)
      setResult(parsed)
    } catch (err: any) {
      setError(err?.message || 'Impossible d’analyser ce PDF.')
    } finally {
      setLoading(false)
    }
  }

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0]
    if (!selected) return
    setFile(selected)
    handleUpload(selected)
  }

  const filteredItems = useMemo(() => {
    if (filter === 'all') return result.items
    return result.items.filter(item => item.match_status === filter)
  }, [filter, result.items])

  const handleBulkImport = async () => {
    if (!file) return
    const itemsToImport = result.items
      .filter(item => item.match_status === 'missing' && item.numero_requisition && item.montant)
      .map(item => ({
        numero_requisition: item.numero_requisition!,
        montant: item.montant!,
        objet: item.objet,
        rubrique: item.rubrique,
      }))
    if (itemsToImport.length === 0) return
    setImporting(true)
    try {
      await importRequisitionsFromPdf(itemsToImport)
      await handleUpload(file)
    } catch (err: any) {
      setError(err?.message || "Impossible d'importer les lignes manquantes.")
    } finally {
      setImporting(false)
    }
  }

  const handleValidateImport = async (id?: string | null) => {
    if (!id) return
    setValidatingId(id)
    try {
      await validateImportedRequisition(id)
      if (file) {
        await handleUpload(file)
      }
    } catch (err: any) {
      setError(err?.message || "Impossible de valider l'import.")
    } finally {
      setValidatingId(null)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <div className={styles.title}>Analyse OCR “Smart” des réquisitions</div>
          <div className={styles.subtitle}>Glisse un PDF et compare instantanément avec la base.</div>
        </div>
        <div className={styles.uploadRow}>
          <label className={styles.uploadButton}>
            {loading ? 'Analyse…' : 'Importer un PDF'}
            <input type="file" accept="application/pdf" onChange={onFileChange} hidden />
          </label>
          {file && <div className={styles.fileName}>{file.name}</div>}
        </div>
      </div>

      <div className={styles.split}>
        <div className={styles.panel}>
          <div className={styles.panelTitle}>Document original</div>
          {previewUrl ? (
            <iframe title="pdf-preview" className={styles.pdfFrame} src={previewUrl} />
          ) : (
            <div className={styles.warning}>Charge un PDF pour afficher le document original.</div>
          )}
        </div>

        <div className={styles.panel}>
          <div className={styles.panelTitle}>Vue intelligente & réconciliation</div>
          <div className={styles.uploadRow}>
            <button
              className={styles.uploadButton}
              onClick={handleBulkImport}
              disabled={importing || result.missing === 0}
            >
              {importing ? 'Import…' : 'Tout importer (manquantes)'}
            </button>
            <select value={filter} onChange={(e) => setFilter(e.target.value as any)}>
              <option value="all">Tout</option>
              <option value="missing">Manquantes</option>
              <option value="conflict">Conflits</option>
              <option value="found">Enregistrées</option>
            </select>
          </div>
          <div className={styles.kpis}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Lignes détectées</div>
              <div className={styles.kpiValue}>{result.total_items}</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Enregistrées</div>
              <div className={styles.kpiValue}>{result.matched}</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Conflits</div>
              <div className={styles.kpiValue}>{result.conflicts}</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Manquantes</div>
              <div className={styles.kpiValue}>{result.missing}</div>
            </div>
          </div>

          {error && <div className={styles.warning}>{error}</div>}
          {result.warnings.map((warning) => (
            <div key={warning} className={styles.warning}>{warning}</div>
          ))}

          <div className={styles.list}>
            {filteredItems.map((item, index) => (
              <div key={`${item.numero_requisition || item.raw_line}-${index}`} className={styles.row}>
                <div>
                  <div className={styles.rowTitle}>{item.numero_requisition || '—'}</div>
                  <div className={styles.rowText}>{item.objet || item.raw_line}</div>
                </div>
                <div className={styles.rowText}>{item.rubrique || '—'}</div>
                <div className={styles.rowText}>
                  {item.montant ? `${item.montant} $` : '—'}
                  {item.match_status === 'conflict' && item.db_montant ? (
                    <div className={styles.rowText}>DB: {item.db_montant} $</div>
                  ) : null}
                </div>
                <div className={styles.rowText}>{item.statut || item.db_status || '—'}</div>
                <div>
                  <span
                    className={`${styles.badge} ${
                      item.match_status === 'found'
                        ? styles.badgeOk
                        : item.match_status === 'missing'
                          ? styles.badgeMissing
                          : item.match_status === 'conflict'
                            ? styles.badgeConflict
                            : styles.badgeUnmatched
                    }`}
                  >
                    {statusLabel(item.match_status)}
                  </span>
                  {item.db_status === 'PENDING_VALIDATION_IMPORT' && item.db_id && (
                    <button
                      className={styles.validateBtn}
                      onClick={() => handleValidateImport(item.db_id)}
                      disabled={validatingId === item.db_id}
                    >
                      {validatingId === item.db_id ? 'Validation…' : 'Valider import'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {result.raw_text_excerpt && (
            <div>
              <div className={styles.panelTitle}>Extrait brut (debug)</div>
              <div className={styles.excerpt}>{result.raw_text_excerpt}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
