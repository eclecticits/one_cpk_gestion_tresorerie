import { useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, CategoriePersonne, StatutProfessionnel } from '../types'
import ImportModules from '../components/ImportModules'
import CategoryChange from '../components/CategoryChange'
import SuccessNotification from '../components/SuccessNotification'
import LoadingScreen from '../components/LoadingScreen'
import DeactivateExpertModal from '../components/DeactivateExpertModal'
import { downloadExcel } from '../utils/download'
import styles from './ExpertsComptables.module.css'
import { useToast } from '../hooks/useToast'

export default function ExpertsComptables() {
  const { notifyError, notifySuccess, notifyWarning } = useToast()
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [loading, setLoading] = useState(true)
  const [isFetching, setIsFetching] = useState(false)
  const [initialLoad, setInitialLoad] = useState(true)
  const [search, setSearch] = useState('')
  const [filterStatutProf, setFilterStatutProf] = useState<string>('')
  const [filterActive, setFilterActive] = useState<string>('true')
  const [sortField, setSortField] = useState<'numero_ordre' | 'nom_denomination' | ''>('')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [showForm, setShowForm] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [showCategoryChange, setShowCategoryChange] = useState(false)
  const [showSuccessNotification, setShowSuccessNotification] = useState(false)
  const [successNotificationData, setSuccessNotificationData] = useState({ title: '', message: '' })
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [selectedExpert, setSelectedExpert] = useState<ExpertComptable | null>(null)
  const [showMoreCols, setShowMoreCols] = useState(() => {
    try {
      const stored = window.localStorage.getItem('experts_show_more_cols')
      return stored === 'true'
    } catch {
      return false
    }
  })
  const [showEditForm, setShowEditForm] = useState(false)
  const [editingExpert, setEditingExpert] = useState<ExpertComptable | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [expertToDelete, setExpertToDelete] = useState<ExpertComptable | null>(null)
  const [isDeletingExpert, setIsDeletingExpert] = useState(false)
  const [pageSize, setPageSize] = useState(25)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const loadingToast = isSavingEdit
    ? 'Enregistrement en cours...'
    : isDeletingExpert
      ? 'Archivage en cours...'
      : null

  const [formData, setFormData] = useState({
    numero_ordre: '',
    nom_denomination: '',
    type_ec: 'EC',
    email: '',
    telephone: '',
    categorie_personne: '' as CategoriePersonne | '',
    statut_professionnel: '' as StatutProfessionnel | '',
    cabinet_attache: '',
  })

  const [editFormData, setEditFormData] = useState({
    nom_denomination: '',
    type_ec: 'EC',
    email: '',
    telephone: '',
    categorie_personne: '' as CategoriePersonne | '',
    statut_professionnel: '' as StatutProfessionnel | '',
    cabinet_attache: '',
  })

  const loadExperts = async () => {
    try {
      setIsFetching(true)
      if (initialLoad) {
        setLoading(true)
      }
      const includeInactive = filterActive === ''
      const activeParam = filterActive === 'true' ? true : filterActive === 'false' ? false : undefined
      const res: any = await apiRequest('GET', '/experts-comptables', {
        params: {
          q: search || undefined,
          statut_professionnel: filterStatutProf || undefined,
          include_inactive: includeInactive ? true : undefined,
          active: includeInactive ? undefined : activeParam,
          order: sortField ? `${sortField}.${sortDirection}` : 'numero_ordre.asc',
          limit: pageSize,
          offset: (page - 1) * pageSize,
          include_summary: true,
        }
      })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setExperts(items as any)
      setTotalCount(typeof res?.total === 'number' ? res.total : items.length)
    } catch (error) {
      console.error('Error loading experts:', error)
    } finally {
      setIsFetching(false)
      setLoading(false)
      setInitialLoad(false)
    }
  }

  useEffect(() => {
    loadExperts()
  }, [search, filterStatutProf, filterActive, sortField, sortDirection, pageSize, page])

  useEffect(() => {
    setPage(1)
  }, [search, filterStatutProf, filterActive, sortField, sortDirection, pageSize])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!formData.numero_ordre || !formData.nom_denomination) {
      notifyWarning('Champs requis manquants', "Veuillez saisir le numéro d'ordre et le nom/dénomination.")
      return
    }

    try {
      const typeEc = formData.categorie_personne === 'Personne Morale' ? 'SEC' : formData.type_ec

      await apiRequest('POST', '/experts-comptables', {
        numero_ordre: formData.numero_ordre,
        nom_denomination: formData.nom_denomination,
        type_ec: typeEc,
        email: formData.email || null,
        telephone: formData.telephone || null,
        categorie_personne: formData.categorie_personne || null,
        statut_professionnel: formData.statut_professionnel || null,
        cabinet_attache: formData.cabinet_attache || null,
        active: true,
      }) 

      notifySuccess('Expert ajouté', "L'expert-comptable a été ajouté avec succès.")
      setShowForm(false)
      setFormData({
        numero_ordre: '',
        nom_denomination: '',
        type_ec: 'EC',
        email: '',
        telephone: '',
        categorie_personne: '',
        statut_professionnel: '',
        cabinet_attache: '',
      })
      loadExperts()
    } catch (error: any) {
      console.error('Error creating expert:', error)
      if (error.code === '23505') {
        notifyWarning("Numéro d'ordre existant", "Ce numéro d'ordre existe déjà dans le système.")
      } else {
        notifyError("Erreur d'ajout", error?.message || "Une erreur est survenue lors de l'ajout de l'expert-comptable.")
      }
    }
  }

  const toggleActiveStatus = (expert: ExpertComptable) => {
    setSelectedExpert(expert)
    setShowDeactivateModal(true)
  }

  const openEditForm = (expert: ExpertComptable) => {
    setEditingExpert(expert)
    setEditFormData({
      nom_denomination: expert.nom_denomination || '',
      type_ec: expert.type_ec || 'EC',
      email: expert.email || '',
      telephone: expert.telephone || '',
      categorie_personne: (expert.categorie_personne || '') as CategoriePersonne | '',
      statut_professionnel: (expert.statut_professionnel || '') as StatutProfessionnel | '',
      cabinet_attache: expert.cabinet_attache || '',
    })
    setShowEditForm(true)
  }

  const closeEditForm = () => {
    if (isSavingEdit) return
    setShowEditForm(false)
    setEditingExpert(null)
  }

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingExpert || isSavingEdit) return

    if (!editFormData.nom_denomination) {
      notifyWarning('Champs requis manquants', 'Veuillez remplir le nom/dénomination.')
      return
    }

    setIsSavingEdit(true)
    try {
      const typeEc = editFormData.categorie_personne === 'Personne Morale' ? 'SEC' : editFormData.type_ec

      await apiRequest('PUT', `/experts-comptables/${editingExpert.id}`, {
        nom_denomination: editFormData.nom_denomination,
        type_ec: typeEc,
        email: editFormData.email || null,
        telephone: editFormData.telephone || null,
        categorie_personne: editFormData.categorie_personne || null,
        statut_professionnel: editFormData.statut_professionnel || null,
        cabinet_attache: editFormData.cabinet_attache || null,
      })

      setSuccessNotificationData({
        title: 'Expert mis à jour',
        message: `${editingExpert.nom_denomination} a été mis à jour avec succès.`,
      })
      setShowSuccessNotification(true)
      closeEditForm()
      loadExperts()
    } catch (error: any) {
      console.error('Error updating expert:', error)
      notifyError('Mise à jour impossible', error?.message || "Impossible de mettre à jour l'expert-comptable.")
    } finally {
      setIsSavingEdit(false)
    }
  }

  const handleDeleteExpert = async (expert: ExpertComptable) => {
    setExpertToDelete(expert)
    setShowDeleteModal(true)
  }

  const confirmDeleteExpert = async () => {
    if (!expertToDelete) return
    if (isDeletingExpert) return
    setIsDeletingExpert(true)
    try {
      await apiRequest('DELETE', `/experts-comptables/${expertToDelete.id}`)
      setSuccessNotificationData({
        title: 'Expert archivé',
        message: `${expertToDelete.nom_denomination} a été archivé avec succès.`,
      })
      setShowSuccessNotification(true)
      loadExperts()
    } catch (error: any) {
      console.error('Error deleting expert:', error)
      notifyError('Archivage impossible', error?.message || "Impossible d’archiver cet expert.")
    } finally {
      setIsDeletingExpert(false)
      setShowDeleteModal(false)
      setExpertToDelete(null)
    }
  }

  const openDeactivateFromEdit = () => {
    if (!editingExpert) return
    setSelectedExpert(editingExpert)
    setShowDeactivateModal(true)
  }

  const confirmToggleStatus = async () => {
    if (!selectedExpert) return

    const newActiveStatus = !selectedExpert.active

    try {
      await apiRequest('PATCH', `/experts-comptables/${selectedExpert.id}`, { active: newActiveStatus })

      setSuccessNotificationData({
        title: 'Statut modifié avec succès',
        message: `${selectedExpert.nom_denomination} a été ${newActiveStatus ? 'réactivé' : 'désactivé'} avec succès.`
      })
      setShowSuccessNotification(true)
      loadExperts()
    } catch (error) {
      console.error('Error toggling expert status:', error)
      notifyError('Modification impossible', "Impossible de modifier le statut de l'expert-comptable.")
    } finally {
      setShowDeactivateModal(false)
      setSelectedExpert(null)
    }
  }

  const handleExportToExcel = async () => {
    const includeInactive = filterActive === ''
    const activeParam = filterActive === 'true' ? true : filterActive === 'false' ? false : undefined
    const date = new Date().toISOString().split('T')[0]
    await downloadExcel('/exports/experts-comptables', {
      q: search || undefined,
      statut_professionnel: filterStatutProf || undefined,
      include_inactive: includeInactive ? true : undefined,
      active: includeInactive ? undefined : activeParam,
      order: sortField ? `${sortField}.${sortDirection}` : 'numero_ordre.asc',
    }, `experts_comptables_${date}.xlsx`)
  }


  const handleSort = (field: 'numero_ordre' | 'nom_denomination') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
    setPage(1)
  }

  const filteredExperts = experts

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(page, totalPages)
  const paginatedExperts = filteredExperts

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  if (loading) {
    return (
      <LoadingScreen
        message="Chargement des experts-comptables"
        subtitle="Récupération de la liste des experts-comptables..."
        showProgress={true}
        showTip={true}
      />
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Experts-Comptables</h1>
          <p>Référentiel des experts-comptables</p>
        </div>
        <div className={styles.headerActions}>
          <button
            onClick={() => {
              setShowMoreCols((v) => {
                const next = !v
                try {
                  window.localStorage.setItem('experts_show_more_cols', String(next))
                } catch {}
                return next
              })
            }}
            className={styles.secondaryBtn}
          >
            {showMoreCols ? 'Afficher moins' : 'Afficher plus'}
          </button>
          <button onClick={() => setShowCategoryChange(true)} className={styles.secondaryBtn}>
            Changer de catégorie
          </button>
          <button onClick={handleExportToExcel} className={styles.secondaryBtn}>
            📥 Télécharger Excel
          </button>
          <button onClick={() => setShowImport(true)} className={styles.secondaryBtn}>
            Importer Excel
          </button>
          <button onClick={() => setShowForm(true)} className={styles.primaryBtn}>
            + Ajouter EC
          </button>
        </div>
      </div>

      <div className={styles.filtersSection}>
        <div className={styles.searchBar}>
          <input
            type="text"
            placeholder="Rechercher par numéro, nom, email ou cabinet..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className={styles.filtersBar}>
          <div className={styles.filterGroup}>
            <label>Affichage</label>
            <select
              value={String(pageSize)}
              onChange={(e) => {
                setPageSize(Number(e.target.value))
                setPage(1)
              }}
            >
              <option value="10">10 / page</option>
              <option value="25">25 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label>Statut</label>
            <select value={filterActive} onChange={(e) => setFilterActive(e.target.value)}>
              <option value="true">Actifs</option>
              <option value="false">Non-actifs</option>
              <option value="">Tous</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Statut professionnel</label>
            <select value={filterStatutProf} onChange={(e) => setFilterStatutProf(e.target.value)}>
              <option value="">Tous</option>
              <option value="En Cabinet">En Cabinet</option>
              <option value="Indépendant">Indépendant</option>
              <option value="Salarié">Salarié</option>
              <option value="Cabinet">Cabinet</option>
            </select>
          </div>

          {(filterStatutProf || (filterActive !== 'true')) && (
            <button
              onClick={() => {
                setFilterStatutProf('')
                setFilterActive('true')
                setPage(1)
              }}
              className={styles.clearFiltersBtn}
            >
              Réinitialiser
            </button>
          )}
        </div>
      </div>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Ajouter un expert-comptable</h2>
              <button onClick={() => setShowForm(false)} className={styles.closeBtn}>×</button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Numéro d'ordre *</label>
                <input
                  type="text"
                  value={formData.numero_ordre}
                  onChange={(e) => setFormData({ ...formData, numero_ordre: e.target.value })}
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Nom / Dénomination *</label>
                <input
                  type="text"
                  value={formData.nom_denomination}
                  onChange={(e) => setFormData({ ...formData, nom_denomination: e.target.value })}
                  required
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Email</label>
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  />
                </div>

                <div className={styles.field}>
                  <label>Téléphone</label>
                  <input
                    type="tel"
                    value={formData.telephone}
                    onChange={(e) => setFormData({ ...formData, telephone: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Catégorie Personne</label>
                  <select
                    value={formData.categorie_personne}
                    onChange={(e) => setFormData({ ...formData, categorie_personne: e.target.value as CategoriePersonne | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="Personne Physique">Personne Physique</option>
                    <option value="Personne Morale">Personne Morale</option>
                  </select>
                </div>

                <div className={styles.field}>
                  <label>Statut Professionnel</label>
                  <select
                    value={formData.statut_professionnel}
                    onChange={(e) => setFormData({ ...formData, statut_professionnel: e.target.value as StatutProfessionnel | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="En Cabinet">En Cabinet</option>
                    <option value="Indépendant">Indépendant</option>
                    <option value="Salarié">Salarié</option>
                    <option value="Cabinet">Cabinet</option>
                  </select>
                </div>
              </div>

              {formData.statut_professionnel === 'En Cabinet' && (
                <div className={styles.field}>
                  <label>Cabinet d'Attache</label>
                  <input
                    type="text"
                    value={formData.cabinet_attache}
                    onChange={(e) => setFormData({ ...formData, cabinet_attache: e.target.value })}
                    placeholder="Nom du cabinet d'attache"
                  />
                </div>
              )}

              <div className={styles.formActions}>
                <button type="button" onClick={() => setShowForm(false)} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Ajouter
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showEditForm && editingExpert && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Modifier l’expert-comptable</h2>
              <button onClick={closeEditForm} className={styles.closeBtn} disabled={isSavingEdit}>×</button>
            </div>

            <form onSubmit={handleEditSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Numéro d'ordre</label>
                <input type="text" value={editingExpert.numero_ordre} disabled />
              </div>

              <div className={styles.field}>
                <label>Nom / Dénomination *</label>
                <input
                  type="text"
                  value={editFormData.nom_denomination}
                  onChange={(e) => setEditFormData({ ...editFormData, nom_denomination: e.target.value })}
                  required
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Email</label>
                  <input
                    type="email"
                    value={editFormData.email}
                    onChange={(e) => setEditFormData({ ...editFormData, email: e.target.value })}
                  />
                </div>

                <div className={styles.field}>
                  <label>Téléphone</label>
                  <input
                    type="tel"
                    value={editFormData.telephone}
                    onChange={(e) => setEditFormData({ ...editFormData, telephone: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Catégorie Personne</label>
                  <select
                    value={editFormData.categorie_personne}
                    onChange={(e) => setEditFormData({ ...editFormData, categorie_personne: e.target.value as CategoriePersonne | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="Personne Physique">Personne Physique</option>
                    <option value="Personne Morale">Personne Morale</option>
                  </select>
                </div>

                <div className={styles.field}>
                  <label>Statut Professionnel</label>
                  <select
                    value={editFormData.statut_professionnel}
                    onChange={(e) => setEditFormData({ ...editFormData, statut_professionnel: e.target.value as StatutProfessionnel | '' })}
                  >
                    <option value="">-- Sélectionner --</option>
                    <option value="En Cabinet">En Cabinet</option>
                    <option value="Indépendant">Indépendant</option>
                    <option value="Salarié">Salarié</option>
                    <option value="Cabinet">Cabinet</option>
                  </select>
                </div>
              </div>

              {editFormData.statut_professionnel === 'En Cabinet' && (
                <div className={styles.field}>
                  <label>Cabinet d'Attache</label>
                  <input
                    type="text"
                    value={editFormData.cabinet_attache}
                    onChange={(e) => setEditFormData({ ...editFormData, cabinet_attache: e.target.value })}
                    placeholder="Nom du cabinet d'attache"
                  />
                </div>
              )}

              <div className={styles.formActions}>
                <button type="button" onClick={closeEditForm} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={openDeactivateFromEdit}
                  className={styles.deactivateBtn}
                  disabled={isSavingEdit}
                >
                  {editingExpert.active === false ? '✓ Réactiver' : '✕ Désactiver'}
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={isSavingEdit}>
                  {isSavingEdit ? (
                    <>
                      <span className={`${styles.spinner} ${styles.spinnerDark}`} />
                      Enregistrement...
                    </>
                  ) : (
                    'Enregistrer'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showDeleteModal && expertToDelete && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Confirmer l’archivage</h2>
              <button
                onClick={() => setShowDeleteModal(false)}
                className={styles.closeBtn}
                disabled={isDeletingExpert}
              >
                ×
              </button>
            </div>
            <div className={styles.modalBody}>
              <p>
                Voulez-vous archiver
                <strong> {expertToDelete.nom_denomination}</strong> ?
              </p>
              <p className={styles.modalHint}>
                L’expert restera dans l’historique, mais n’apparaîtra plus pour les nouvelles opérations.
              </p>
            </div>
            <div className={styles.formActions}>
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                className={styles.secondaryBtn}
                disabled={isDeletingExpert}
              >
                Annuler
              </button>
              <button type="button" onClick={confirmDeleteExpert} className={styles.deleteBtn} disabled={isDeletingExpert}>
                {isDeletingExpert ? (
                  <>
                    <span className={styles.spinner} />
                    Archivage...
                  </>
                ) : (
                  '📦 Archiver'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <ImportModules
          onClose={() => setShowImport(false)}
          onSuccess={loadExperts}
        />
      )}

      {showCategoryChange && (
        <CategoryChange
          onClose={() => setShowCategoryChange(false)}
          onSuccess={() => {
            loadExperts()
            setSuccessNotificationData({
              title: 'Changement de catégorie effectué',
              message: 'Les informations de l\'expert-comptable ont été mises à jour avec succès'
            })
            setShowSuccessNotification(true)
          }}
        />
      )}

      {showSuccessNotification && (
        <SuccessNotification
          title={successNotificationData.title}
          message={successNotificationData.message}
          onClose={() => setShowSuccessNotification(false)}
        />
      )}

      {loadingToast && (
        <div className={styles.toast}>
          <span className={`${styles.spinner} ${styles.spinnerDark}`} />
          {loadingToast}
        </div>
      )}

      <DeactivateExpertModal
        isOpen={showDeactivateModal}
        expert={selectedExpert}
        onConfirm={confirmToggleStatus}
        onCancel={() => {
          setShowDeactivateModal(false)
          setSelectedExpert(null)
        }}
        isReactivate={selectedExpert?.active === false}
      />

      <div className={styles.resultsInfo}>
        <p>
          <strong>{totalCount}</strong> expert{totalCount > 1 ? 's' : ''} trouvé{totalCount > 1 ? 's' : ''}
        </p>
        {isFetching && <span className={styles.fetchHint}>Mise à jour…</span>}
      </div>

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.sortableHeader} onClick={() => handleSort('numero_ordre')}>
                N° Ordre
                {sortField === 'numero_ordre' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th className={`${styles.sortableHeader} ${styles.nameCol}`} onClick={() => handleSort('nom_denomination')}>
                Nom / Dénomination
                {sortField === 'nom_denomination' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              {showMoreCols && <th>Type</th>}
              {showMoreCols && <th>Statut</th>}
              <th className={styles.cabinetCol}>Cabinet Attache</th>
              <th className={styles.emailCol}>Email</th>
              <th className={styles.phoneCol}>Téléphone</th>
              {showMoreCols && <th className={styles.statusCol}>État</th>}
              <th className={styles.actionsCol}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedExperts.map((expert) => (
              <tr key={expert.id} style={{opacity: expert.active === false ? 0.6 : 1}}>
                <td><strong>{expert.numero_ordre}</strong></td>
                <td className={styles.nameCol}>{expert.nom_denomination}</td>
                {showMoreCols && (
                  <td>
                    <span className={styles.badge}>{expert.type_ec}</span>
                  </td>
                )}
                {showMoreCols && (
                  <td>
                    {expert.statut_professionnel ? (
                      <span className={styles.badgeStatus}>
                        {expert.statut_professionnel}
                      </span>
                    ) : '-'}
                  </td>
                )}
                <td className={styles.cabinetCol}>{expert.cabinet_attache || '-'}</td>
                <td className={styles.emailCol}>{expert.email || '-'}</td>
                <td className={styles.phoneCol}>{expert.telephone || '-'}</td>
                {showMoreCols && (
                  <td className={styles.statusCol}>
                    <span className={expert.active === false ? styles.badgeArchived : styles.badgeActive}>
                      {expert.active === false ? 'Archivé' : 'Actif'}
                    </span>
                  </td>
                )}
                <td className={styles.actionsCol}>
                  <div className={styles.actionsCell}>
                    <button onClick={() => openEditForm(expert)} className={styles.iconBtn} aria-label="Modifier">
                      ✏️
                    </button>
                    <button
                      onClick={() => toggleActiveStatus(expert)}
                      className={`${styles.iconBtn} ${expert.active === false ? styles.reactivateBtn : styles.deactivateBtn}`}
                      aria-label={expert.active === false ? 'Réactiver' : 'Désactiver'}
                    >
                      {expert.active === false ? '✓' : '✕'}
                    </button>
                    <button onClick={() => handleDeleteExpert(expert)} className={`${styles.iconBtn} ${styles.deleteBtn}`} aria-label="Archiver">
                      📦
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {paginatedExperts.length === 0 && (
          <div className={styles.empty}>Aucun expert-comptable trouvé</div>
        )}
      </div>

      {totalCount > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {safePage} / {totalPages}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
          >
            Suivant →
          </button>
        </div>
      )}

    </div>
  )
}
