import { useState, useEffect } from 'react'
import { apiRequest, ApiError } from '../lib/apiClient'
import * as XLSX from 'xlsx'
import styles from './ImportHistory.module.css'
import { useToast } from '../hooks/useToast'

interface ImportRecord {
  id: string
  filename: string
  category: string
  imported_by: string
  created_at: string
  rows_imported: number
  status: string
  file_data: any[]
  error_details?: any
  user_email?: string
  imported_by_user?: {
    id: string
    email: string
    nom?: string
    prenom?: string
    role?: string
  } | null
}

export default function ImportHistory() {
  const { notifyError, notifyWarning, notifySuccess } = useToast()
  const [imports, setImports] = useState<ImportRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [filterCategory, setFilterCategory] = useState<string>('all')
  const [historyUnavailable, setHistoryUnavailable] = useState(false)
  const [deleteModal, setDeleteModal] = useState<{
    show: boolean
    importId: string
    filename: string
    rowCount: number
    deleteData: boolean
  } | null>(null)

  const categoryLabels: Record<string, string> = {
    sec: 'SEC - Sociétés',
    en_cabinet: 'En Cabinet',
    independant: 'Indépendant',
    salarie: 'Salarié'
  }

  useEffect(() => {
    if (historyUnavailable) return
    loadImports()
  }, [filterCategory, historyUnavailable])

  const loadImports = async () => {
    if (historyUnavailable) return
    setLoading(true)
    try {
      setHistoryUnavailable(false)
      const params: any = { limit: 200 }
      if (filterCategory !== 'all') params.category = filterCategory

      const res: any = await apiRequest('GET', '/imports-history', { params })
      const data = (res || []) as any[]

      const formattedData = data.map((record: any) => ({
        ...record,
        user_email: record?.imported_by_user?.email || 'Inconnu'
      }))

      setImports(formattedData)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setImports([])
        setHistoryUnavailable(true)
        return
      }
      console.error('Erreur lors du chargement:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadOriginal = (record: ImportRecord) => {
    const worksheet = XLSX.utils.json_to_sheet(record.file_data)
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Données')
    XLSX.writeFile(workbook, record.filename)
  }

  const handleDownloadCurrent = async (record: ImportRecord) => {
    try {
      const res: any = await apiRequest('GET', '/experts-comptables', { params: { import_id: record.id, limit: 500 } })

      const data = res as any[]

      if (!data || data.length === 0) {
        notifyWarning('Aucune donnée', "Aucune donnée n'a été trouvée pour cet import.")
        return
      }

      const exportData = data.map(expert => ({
        'N° d\'ordre': expert.numero_ordre,
        'Nom/Dénomination': expert.nom_denomination,
        'Type': expert.type_ec,
        'Catégorie': expert.categorie_personne,
        'Statut': expert.statut_professionnel,
        'Sexe': expert.sexe,
        'Téléphone': expert.telephone,
        'E-mail': expert.email,
        'NIF': expert.nif,
        'Cabinet': expert.cabinet_attache,
        'Employeur': expert.nom_employeur,
        'Raison sociale': expert.raison_sociale,
        'Associé gérant': expert.associe_gerant
      }))

      const worksheet = XLSX.utils.json_to_sheet(exportData)
      const workbook = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(workbook, worksheet, 'Export')
      XLSX.writeFile(workbook, `export_${record.filename}`)
      notifySuccess('Export terminé', 'Le fichier a été téléchargé.')
    } catch (error) {
      console.error('Erreur lors de l\'export:', error)
      notifyError("Erreur d'export", "Une erreur est survenue lors de l'export des données.")
    }
  }

  const confirmDelete = async (deleteData: boolean) => {
    if (!deleteModal) return

    try {
      if (deleteData) {
        await apiRequest('DELETE', '/experts-comptables', { params: { import_id: deleteModal.importId } })
      }

      await apiRequest('DELETE', `/imports-history/${deleteModal.importId}`)

      setDeleteModal(null)
      loadImports()
      notifySuccess('Suppression effectuée', "L'import a été supprimé.")
    } catch (error) {
      console.error('Erreur lors de la suppression:', error)
      notifyError("Erreur de suppression", "Une erreur est survenue lors de la suppression de l'import.")
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('fr-FR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>Historique des Imports</h1>
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
        <div className={styles.empty}>Historique indisponible (endpoint non exposé).</div>
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
                      {categoryLabels[record.category]}
                    </span>
                  </td>
      <td>{formatDate(record.created_at)}</td>
                  <td>{record.user_email}</td>
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
                        onClick={() => handleDownloadCurrent(record)}
                        className={styles.btnDownload}
                        title="Télécharger les données actuelles"
                      >
                        📊 Actuel
                      </button>
                      <button
                        onClick={() => setDeleteModal({
                          show: true,
                          importId: record.id,
                          filename: record.filename,
                          rowCount: record.rows_imported,
                          deleteData: false
                        })}
                        className={styles.btnDelete}
                        title="Supprimer"
                      >
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteModal && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <h2>Confirmer la suppression</h2>
            <p>Fichier : <strong>{deleteModal.filename}</strong></p>
            <p>Nombre de lignes : <strong>{deleteModal.rowCount}</strong></p>

            <div className={styles.deleteOptions}>
              <button
                onClick={() => confirmDelete(false)}
                className={styles.btnHistoryOnly}
              >
                Supprimer uniquement l'historique
              </button>
              <button
                onClick={() => confirmDelete(true)}
                className={styles.btnWithData}
              >
                Supprimer l'historique ET les données
              </button>
              <button
                onClick={() => setDeleteModal(null)}
                className={styles.btnCancel}
              >
                Annuler
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
