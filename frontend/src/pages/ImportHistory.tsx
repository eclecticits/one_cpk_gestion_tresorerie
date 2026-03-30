import { useEffect, useState } from 'react'
import * as XLSX from 'xlsx'
import { ApiError, apiRequest } from '../lib/apiClient'
import { useToast } from '../hooks/useToast'
import styles from './ImportHistory.module.css'

interface ImportRecord {
  id: string
  filename: string
  category: string
  imported_by: string | null
  created_at: string
  rows_imported: number
  status: string
  file_data: any[]
  imported_by_user?: {
    id: string
    email: string
    nom?: string
    prenom?: string
    role?: string
  } | null
}

const categoryLabels: Record<string, string> = {
  sec: 'SEC - Sociétés',
  en_cabinet: 'En Cabinet',
  independant: 'Indépendant',
  salarie: 'Salarié',
}

export default function ImportHistory() {
  const { notifyError, notifyWarning, notifySuccess } = useToast()
  const [imports, setImports] = useState<ImportRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [filterCategory, setFilterCategory] = useState('all')
  const [historyUnavailable, setHistoryUnavailable] = useState(false)
  const [deleteModal, setDeleteModal] = useState<{
    show: boolean
    importId: string
    filename: string
    rowCount: number
    deleteData: boolean
  } | null>(null)

  useEffect(() => {
    if (historyUnavailable) return
    loadImports()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterCategory, historyUnavailable])

  const loadImports = async () => {
    if (historyUnavailable) return
    setLoading(true)
    try {
      const params: any = { limit: 200 }
      if (filterCategory !== 'all') params.category = filterCategory
      const res: any = await apiRequest('GET', '/imports-history', { params })
      const data = Array.isArray(res) ? res : (res?.items ?? [])
      setImports(data)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setImports([])
        setHistoryUnavailable(true)
        return
      }
      notifyError("Erreur de chargement", "Impossible de charger l'historique.")
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadOriginal = (record: ImportRecord) => {
    if (!record.file_data || record.file_data.length === 0) {
      notifyWarning('Aucune donnée', "Aucune donnée d'origine pour cet import.")
      return
    }
    const worksheet = XLSX.utils.json_to_sheet(record.file_data)
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Données')
    XLSX.writeFile(workbook, record.filename || 'import.xlsx')
  }

  const handleDelete = async () => {
    if (!deleteModal) return
    try {
      await apiRequest('DELETE', `/imports-history/${deleteModal.importId}`)
      setDeleteModal(null)
      notifySuccess('Supprimé', "L'historique a été supprimé.")
      loadImports()
    } catch (err) {
      notifyError('Erreur', "Impossible de supprimer l'historique.")
    }
  }

  const formatDate = (value: string) => {
    try {
      return new Date(value).toLocaleString('fr-FR')
    } catch {
      return value
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Historique des imports</h1>
        <div className={styles.filters}>
          <label>Catégorie :</label>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className={styles.select}
          >
            <option value="all">Toutes les catégories</option>
            <option value="sec">SEC - Sociétés</option>
            <option value="en_cabinet">En Cabinet</option>
            <option value="independant">Indépendant</option>
            <option value="salarie">Salarié</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Chargement...</div>
      ) : historyUnavailable ? (
        <div className={styles.empty}>Historique indisponible.</div>
      ) : imports.length === 0 ? (
        <div className={styles.empty}>Aucun import trouvé</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Fichier</th>
                <th>Catégorie</th>
                <th>Date/Heure</th>
                <th>Utilisateur</th>
                <th>Lignes</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((record) => (
                <tr key={record.id}>
                  <td>{record.filename}</td>
                  <td>
                    <span className={styles.categoryBadge}>
                      {categoryLabels[record.category] || record.category}
                    </span>
                  </td>
                  <td>{formatDate(record.created_at)}</td>
                  <td>{record.imported_by_user?.email || '—'}</td>
                  <td>{record.rows_imported}</td>
                  <td>
                    <span className={`${styles.statusBadge} ${styles[record.status]}`}>
                      {record.status === 'success' ? 'Succès' : 'Erreur'}
                    </span>
                  </td>
                  <td>
                    <div className={styles.actions}>
                      <button
                        onClick={() => handleDownloadOriginal(record)}
                        className={styles.btnDownload}
                        title="Télécharger le fichier original"
                      >
                        📥 Original
                      </button>
                      <button
                        onClick={() =>
                          setDeleteModal({
                            show: true,
                            importId: record.id,
                            filename: record.filename,
                            rowCount: record.rows_imported,
                            deleteData: false,
                          })
                        }
                        className={styles.btnDelete}
                        title="Supprimer l'historique"
                      >
                        🗑️ Supprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteModal?.show && (
        <div className={styles.modalBackdrop}>
          <div className={styles.modal}>
            <h3>Supprimer l'historique</h3>
            <p>Confirmer la suppression de {deleteModal.filename} ?</p>
            <div className={styles.modalActions}>
              <button onClick={() => setDeleteModal(null)} className={styles.btnSecondary}>
                Annuler
              </button>
              <button onClick={handleDelete} className={styles.btnDanger}>
                Supprimer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
