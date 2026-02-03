import { useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, CategoriePersonne, StatutProfessionnel } from '../types'
import ImportModules from '../components/ImportModules'
import CategoryChange from '../components/CategoryChange'
import SuccessNotification from '../components/SuccessNotification'
import LoadingScreen from '../components/LoadingScreen'
import DeactivateExpertModal from '../components/DeactivateExpertModal'
import * as XLSX from 'xlsx'
import styles from './ExpertsComptables.module.css'

export default function ExpertsComptables() {
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [loading, setLoading] = useState(true)
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

  useEffect(() => {
    loadExperts()
  }, [])

  const loadExperts = async () => {
    try {
      // Le backend filtre "active=true" par défaut, donc on récupère actifs + inactifs
      const [actifsRes, inactifsRes] = await Promise.all([
        apiRequest('GET', '/experts-comptables', { params: { active: true, limit: 200 } }),
        apiRequest('GET', '/experts-comptables', { params: { active: false, limit: 200 } }),
      ])

      const data = [...(actifsRes || []), ...(inactifsRes || [])]
      setExperts(data as any)
    } catch (error) {
      console.error('Error loading experts:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!formData.numero_ordre || !formData.nom_denomination) {
      alert('⚠ CHAMPS REQUIS MANQUANTS\n\nVeuillez remplir tous les champs obligatoires :\n\n• Numéro d\'ordre\n• Nom/Dénomination')
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

      alert('✓ EXPERT-COMPTABLE AJOUTÉ\n\nL\'expert-comptable a été ajouté avec succès au système.')
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
        alert('✕ NUMÉRO D\'ORDRE EXISTANT\n\nCe numéro d\'ordre existe déjà dans le système.\n\nVeuillez utiliser un numéro d\'ordre différent.')
      } else {
        alert(`✕ ERREUR D'AJOUT\n\n${error?.message || 'Une erreur est survenue lors de l\'ajout de l\'expert-comptable.'}\n\nVeuillez réessayer.`)
      }
    }
  }

  const toggleActiveStatus = (expert: ExpertComptable) => {
    setSelectedExpert(expert)
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
      alert('Erreur: Impossible de modifier le statut de l\'expert-comptable. Veuillez réessayer.')
    } finally {
      setShowDeactivateModal(false)
      setSelectedExpert(null)
    }
  }

  const handleExportToExcel = () => {
    const dataToExport = filteredExperts.map(expert => ({
      'N° Ordre': expert.numero_ordre,
      'Nom/Dénomination': expert.nom_denomination,
      'Type': expert.type_ec,
      'Catégorie Personne': expert.categorie_personne || '',
      'Statut Professionnel': expert.statut_professionnel || '',
      'Cabinet Attache': expert.cabinet_attache || '',
      'Email': expert.email || '',
      'Téléphone': expert.telephone || '',
      'État': expert.active === false ? 'Non-actif' : 'Actif'
    }))

    const worksheet = XLSX.utils.json_to_sheet(dataToExport)

    const columnWidths = [
      { wch: 12 },
      { wch: 35 },
      { wch: 8 },
      { wch: 20 },
      { wch: 20 },
      { wch: 30 },
      { wch: 30 },
      { wch: 15 },
      { wch: 12 }
    ]
    worksheet['!cols'] = columnWidths

    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Experts Comptables')

    const date = new Date().toISOString().split('T')[0]
    const filename = `experts_comptables_${date}.xlsx`

    XLSX.writeFile(workbook, filename)
  }


  const handleSort = (field: 'numero_ordre' | 'nom_denomination') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const filteredExperts = experts
    .filter(e => {
      const matchesSearch =
        e.numero_ordre.toLowerCase().includes(search.toLowerCase()) ||
        e.nom_denomination.toLowerCase().includes(search.toLowerCase()) ||
        (e.email && e.email.toLowerCase().includes(search.toLowerCase())) ||
        (e.cabinet_attache && e.cabinet_attache.toLowerCase().includes(search.toLowerCase()))

      const matchesStatutProf = !filterStatutProf || e.statut_professionnel === filterStatutProf

      const matchesActive = filterActive === ''
        ? true
        : filterActive === 'true'
          ? (e.active !== false)
          : (e.active === false)

      return matchesSearch && matchesStatutProf && matchesActive
    })
    .sort((a, b) => {
      if (!sortField) return 0

      const aValue = a[sortField].toLowerCase()
      const bValue = b[sortField].toLowerCase()

      if (sortDirection === 'asc') {
        return aValue.localeCompare(bValue)
      } else {
        return bValue.localeCompare(aValue)
      }
    })

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
          <strong>{filteredExperts.length}</strong> expert{filteredExperts.length > 1 ? 's' : ''} trouvé{filteredExperts.length > 1 ? 's' : ''}
          {filteredExperts.length !== experts.length && (
            <span className={styles.totalCount}> sur {experts.length} au total</span>
          )}
        </p>
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
              <th className={styles.sortableHeader} onClick={() => handleSort('nom_denomination')}>
                Nom / Dénomination
                {sortField === 'nom_denomination' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th>Type</th>
              <th>Catégorie</th>
              <th>Statut</th>
              <th>Cabinet Attache</th>
              <th>Email</th>
              <th>Téléphone</th>
              <th>État</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredExperts.map((expert) => (
              <tr key={expert.id} style={{opacity: expert.active === false ? 0.6 : 1}}>
                <td><strong>{expert.numero_ordre}</strong></td>
                <td>{expert.nom_denomination}</td>
                <td>
                  <span className={styles.badge}>{expert.type_ec}</span>
                </td>
                <td>
                  {expert.categorie_personne ? (
                    <span className={styles.badgeCategory} data-category={expert.categorie_personne}>
                      {expert.categorie_personne}
                    </span>
                  ) : '-'}
                </td>
                <td>
                  {expert.statut_professionnel ? (
                    <span className={styles.badgeStatus}>
                      {expert.statut_professionnel}
                    </span>
                  ) : '-'}
                </td>
                <td>{expert.cabinet_attache || '-'}</td>
                <td>{expert.email || '-'}</td>
                <td>{expert.telephone || '-'}</td>
                <td>
                  <span style={{
                    display: 'inline-block',
                    padding: '4px 12px',
                    borderRadius: '12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    background: expert.active === false ? '#fee2e2' : '#dcfce7',
                    color: expert.active === false ? '#dc2626' : '#16a34a'
                  }}>
                    {expert.active === false ? 'Non-actif' : 'Actif'}
                  </span>
                </td>
                <td>
                  <button
                    onClick={() => toggleActiveStatus(expert)}
                    style={{
                      padding: '6px 12px',
                      fontSize: '13px',
                      borderRadius: '6px',
                      border: '1px solid',
                      cursor: 'pointer',
                      background: expert.active === false ? '#dcfce7' : '#fee2e2',
                      borderColor: expert.active === false ? '#16a34a' : '#dc2626',
                      color: expert.active === false ? '#16a34a' : '#dc2626',
                      fontWeight: 500
                    }}
                  >
                    {expert.active === false ? '✓ Réactiver' : '✕ Désactiver'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredExperts.length === 0 && (
          <div className={styles.empty}>Aucun expert-comptable trouvé</div>
        )}
      </div>

    </div>
  )
}
