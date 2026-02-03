import { useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { Requisition, LigneRequisition, StatutRequisition, ModePatement } from '../types'
import { format } from 'date-fns'
import * as XLSX from 'xlsx'
import { generateRequisitionsPDF, generateSingleRequisitionPDF } from '../utils/pdfGenerator'
import styles from './Requisitions.module.css'

export default function Requisitions() {
  const { user } = useAuth()
  const [showForm, setShowForm] = useState(false)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRequisition, setSelectedRequisition] = useState<Requisition | null>(null)
  const [selectedLignes, setSelectedLignes] = useState<LigneRequisition[]>([])
  const [selectedRequisitionUsers, setSelectedRequisitionUsers] = useState<{
    demandeur?: { prenom: string; nom: string }
    validateur?: { prenom: string; nom: string }
    approbateur?: { prenom: string; nom: string }
  }>({})
  const [requisitions, setRequisitions] = useState<any[]>([])
  const [rubriques, setRubriques] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [notification, setNotification] = useState<{
    show: boolean
    type: 'success' | 'error'
    title: string
    message: string
  }>({ show: false, type: 'success', title: '', message: '' })

  const [activeTab, setActiveTab] = useState<'classique' | 'mini' | 'remboursement_transport'>('classique')
  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterModePaiement, setFilterModePaiement] = useState<string>('')
  const [filterRubrique, setFilterRubrique] = useState<string>('')
  const [filterObjet, setFilterObjet] = useState<string>('')
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [sortField, setSortField] = useState<'created_at' | 'montant_total' | ''>('')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  const [formData, setFormData] = useState({
    objet: '',
    mode_paiement: 'cash' as ModePatement,
    type_requisition: 'classique' as 'classique' | 'mini' | 'remboursement_transport',
    a_valoir: false,
    instance_beneficiaire: '',
    notes_a_valoir: ''
  })

  const [lignes, setLignes] = useState<Omit<LigneRequisition, 'id' | 'requisition_id'>[]>([
    { rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0 }
  ])

  useEffect(() => {
    loadData()
  }, [])

  const loadRequisitions = async () => {
    const resp = await apiRequest('GET', '/requisitions', {
      params: { include: 'demandeur,validateur,approbateur,caissier' }
    })
    const items = Array.isArray(resp) ? resp : (resp as any)?.items ?? (resp as any)?.data ?? []
    setRequisitions(items as any)
  }

  const loadRubriques = async () => {
    const resp = await apiRequest('GET', '/rubriques', { params: { active: true, order: 'libelle.asc' } })
    const items = Array.isArray(resp) ? resp : (resp as any)?.items ?? (resp as any)?.data ?? []
    setRubriques(items as any)
  }

  const loadData = async () => {
    setLoading(true)
    try {
      await Promise.all([
        loadRequisitions(),
        loadRubriques(),
      ])
    } catch (error) {
      console.error('Error loading data:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de chargement',
        message: 'Impossible de charger les données. Veuillez vérifier la connexion au serveur.'
      })
    } finally {
      setLoading(false)
    }
  }

  const addLigne = () => {
    setLignes([...lignes, { rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0 }])
  }

  const removeLigne = (index: number) => {
    setLignes(lignes.filter((_, i) => i !== index))
  }

  const updateLigne = (index: number, field: string, value: any) => {
    const newLignes = [...lignes]
    newLignes[index] = { ...newLignes[index], [field]: value }

    if (field === 'quantite' || field === 'montant_unitaire') {
      newLignes[index].montant_total = newLignes[index].quantite * newLignes[index].montant_unitaire
    }

    setLignes(newLignes)
  }

  const calculateTotal = () => {
    return lignes.reduce((sum, ligne) => sum + ligne.montant_total, 0)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (submitting) return

    if (!formData.objet || lignes.length === 0) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Informations manquantes',
        message: 'Veuillez remplir l\'objet de la réquisition et ajouter au moins une ligne de dépense.'
      })
      return
    }

    const invalidLigne = lignes.find(l => !l.rubrique || !l.description || l.montant_unitaire <= 0)
    if (invalidLigne) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Lignes incomplètes',
        message: 'Toutes les lignes doivent avoir une rubrique, une description et un montant positif.'
      })
      return
    }

    setSubmitting(true)
    try {
      const numeroRes: any = await apiRequest('POST', '/requisitions/generate-numero')
      const numeroData = numeroRes

      const reqRes: any = await apiRequest('POST', '/requisitions', {
        numero_requisition: numeroData,
        objet: formData.objet,
        mode_paiement: formData.mode_paiement,
        type_requisition: formData.type_requisition,
        montant_total: calculateTotal(),
        status: 'EN_ATTENTE',
        created_by: user?.id,
        a_valoir: formData.a_valoir,
        instance_beneficiaire: formData.a_valoir ? formData.instance_beneficiaire : null,
        notes_a_valoir: formData.a_valoir ? formData.notes_a_valoir : null
      })

      const reqData = reqRes as any

      const lignesData = lignes.map(l => ({
        requisition_id: reqData.id,
        ...l
      }))

      await apiRequest('POST', '/lignes-requisition', lignesData)

      setNotification({
        show: true,
        type: 'success',
        title: 'Réquisition créée avec succès',
        message: `Votre réquisition a été créée et enregistrée.\n\nNuméro de réquisition : ${numeroData}\n\nElle est maintenant en attente de validation.`
      })
      setShowForm(false)
      resetForm()
      loadData()
    } catch (error: any) {
      console.error('Error creating requisition:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de création',
        message: error?.message || 'Une erreur est survenue lors de la création de la réquisition. Veuillez vérifier les informations et réessayer.'
      })
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
    setFormData({ objet: '', mode_paiement: 'cash', type_requisition: activeTab, a_valoir: false, instance_beneficiaire: '', notes_a_valoir: '' })
    setLignes([{ rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0 }])
  }


  const viewDetails = async (req: Requisition) => {
    setSelectedRequisition(req)
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
      const data = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
      setSelectedLignes(data || [])

      const users: any = {}
      if ((req as any).demandeur) users.demandeur = (req as any).demandeur
      if ((req as any).validateur) users.validateur = (req as any).validateur
      if ((req as any).approbateur) users.approbateur = (req as any).approbateur

      setSelectedRequisitionUsers(users)
      setShowDetailModal(true)
    } catch (error: any) {
      console.error('Error loading requisition details:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de chargement',
        message: error?.message || 'Impossible de charger les détails de la réquisition. Veuillez réessayer.'
      })
    }
  }

  const printRequisition = async (requisition: Requisition) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisition.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

      if (!lignesData || lignesData.length === 0) {
        setNotification({
          show: true,
          type: 'error',
          title: 'Erreur',
          message: 'Aucune ligne de dépense trouvée pour cette réquisition'
        })
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'print',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error: any) {
      console.error('Error printing PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur d\'impression',
        message: error?.message || 'Impossible d\'imprimer. Veuillez réessayer.'
      })
    }
  }

  const downloadRequisition = async (requisition: Requisition) => {
    try {
      const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisition.id } })
      const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

      if (!lignesData || lignesData.length === 0) {
        setNotification({
          show: true,
          type: 'error',
          title: 'Erreur',
          message: 'Aucune ligne de dépense trouvée pour cette réquisition'
        })
        return
      }

      await generateSingleRequisitionPDF(
        requisition,
        lignesData,
        'download',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error: any) {
      console.error('Error downloading PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur de téléchargement',
        message: error?.message || 'Impossible de télécharger le PDF. Veuillez réessayer.'
      })
    }
  }

  const handleSort = (field: 'created_at' | 'montant_total') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc')
    }
  }

  const requisitionsList = Array.isArray(requisitions) ? requisitions : []
  const rubriquesList = Array.isArray(rubriques) ? rubriques : []
  const selectedLignesList = Array.isArray(selectedLignes) ? selectedLignes : []
  const filteredRequisitions = requisitionsList
    .filter(req => {
      const reqTypeReq = (req as any).type_requisition || 'classique'
      if (reqTypeReq !== activeTab) return false

      const matchesSearch = searchQuery === '' ||
        req.numero_requisition.toLowerCase().includes(searchQuery.toLowerCase()) ||
        req.objet.toLowerCase().includes(searchQuery.toLowerCase())

      const statusValue = (req as any).status ?? (req as any).statut
      const matchesStatut = !filterStatut || statusValue === filterStatut
      const matchesMode = !filterModePaiement || req.mode_paiement === filterModePaiement
      const matchesObjet = !filterObjet || req.objet.toLowerCase().includes(filterObjet.toLowerCase())

      if (!dateDebut && !dateFin) return matchesSearch && matchesStatut && matchesMode && matchesObjet

      const reqDate = new Date(req.created_at)
      const debut = dateDebut ? new Date(dateDebut) : null
      const fin = dateFin ? new Date(dateFin) : null

      const matchesDate = (!debut || reqDate >= debut) && (!fin || reqDate <= fin)

      return matchesSearch && matchesStatut && matchesMode && matchesObjet && matchesDate
    })
    .sort((a, b) => {
      if (!sortField) return 0

      let aVal: any = a[sortField]
      let bVal: any = b[sortField]

      if (sortField === 'created_at') {
        aVal = new Date(aVal).getTime()
        bVal = new Date(bVal).getTime()
      } else if (sortField === 'montant_total') {
        aVal = Number(aVal)
        bVal = Number(bVal)
      }

      if (sortDirection === 'asc') {
        return aVal > bVal ? 1 : -1
      } else {
        return aVal < bVal ? 1 : -1
      }
    })

  const hasActiveFilters = searchQuery !== '' || filterStatut !== '' || filterModePaiement !== '' || filterObjet !== '' || filterRubrique !== ''

  const clearFilters = () => {
    setSearchQuery('')
    setFilterStatut('')
    setFilterModePaiement('')
    setFilterObjet('')
    setFilterRubrique('')
    setSortField('')
    setSortDirection('desc')
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getStatutBadge = (statut: StatutRequisition | string) => {
    const styles: any = {
      EN_ATTENTE: { bg: '#f3f4f6', color: '#374151' },
      VALIDEE: { bg: '#dbeafe', color: '#1e40af' },
      REJETEE: { bg: '#fee2e2', color: '#dc2626' },
      brouillon: { bg: '#f3f4f6', color: '#374151' },
      validee_tresorerie: { bg: '#dbeafe', color: '#1e40af' },
      approuvee: { bg: '#dcfce7', color: '#16a34a' },
      payee: { bg: '#e0e7ff', color: '#4f46e5' },
      rejetee: { bg: '#fee2e2', color: '#dc2626' },
    }

    const labels: any = {
      EN_ATTENTE: 'En attente',
      VALIDEE: 'Validée',
      REJETEE: 'Rejetée',
      brouillon: 'Brouillon',
      validee_tresorerie: 'Validée trésorerie',
      approuvee: 'Approuvée',
      payee: 'Payée',
      rejetee: 'Rejetée',
    }

    const style = styles[statut] || styles.EN_ATTENTE || styles.brouillon

    return (
      <span style={{
        padding: '4px 12px',
        borderRadius: '12px',
        background: style.bg,
        color: style.color,
        fontWeight: 600,
        fontSize: '13px'
      }}>
        {labels[statut]}
      </span>
    )
  }

  const canCreate = user?.role === 'secretariat' || user?.role === 'admin'

  const totalRequisitions = filteredRequisitions.reduce((sum, r) => sum + Number(r.montant_total), 0)

  const exportToExcel = async () => {
    const formatDate = (value: any) => {
      if (!value) return ''
      try {
        return format(new Date(value), 'dd/MM/yyyy')
      } catch {
        return ''
      }
    }

    const formatStatut = (value: any) => {
      const normalized = String(value || '').toLowerCase()
      if (normalized === 'en_attente') return 'En attente'
      if (normalized === 'validee') return 'Validée'
      if (normalized === 'rejetee') return 'Rejetée'
      if (normalized === 'brouillon') return 'Brouillon'
      if (normalized === 'validee_tresorerie') return 'Validée Trésorerie'
      if (normalized === 'approuvee') return 'Approuvée'
      if (normalized === 'payee') return 'Payée'
      return normalized ? normalized : ''
    }

    try {
      const results = await Promise.allSettled(
        filteredRequisitions.map(async (req) => {
          const demandeurData = (req as any).demandeur || null
          const approbateurData = (req as any).approbateur || (req as any).validateur || null
          const caissierData = (req as any).caissier || null

          let rubriques = ''
          try {
            const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
            const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
            rubriques = lignesData
              ? [...new Set(lignesData.map((l: any) => l.rubrique))].join(', ')
              : ''
          } catch {
            rubriques = ''
          }

          const statutValue = (req as any).statut ?? (req as any).status

          return {
            'N° Réquisition': req.numero_requisition || '',
            'Date': formatDate(req.created_at),
            'Objet': req.objet || '',
            'Rubrique': rubriques,
            'Montant (USD)': Number(req.montant_total || 0),
            'Statut': formatStatut(statutValue),
            'Demandeur': demandeurData ? `${demandeurData.nom} ${demandeurData.prenom}` : '',
            'Approbateur': approbateurData ? `${approbateurData.nom} ${approbateurData.prenom}` : '',
            'Date approbation': formatDate(req.approuvee_le) || formatDate(req.validee_le),
            'Caissier(e)': caissierData ? `${caissierData.nom} ${caissierData.prenom}` : '',
            'Date décaissement': formatDate(req.payee_le),
            'Mode paiement': req.mode_paiement === 'cash' ? 'Caisse' :
                            req.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement bancaire'
          }
        })
      )

      const dataToExport = results
        .filter((r): r is PromiseFulfilledResult<any> => r.status === 'fulfilled')
        .map(r => r.value)

      dataToExport.push({
        'N° Réquisition': '',
        'Date': '',
        'Objet': 'TOTAL',
        'Rubrique': '',
        'Montant (USD)': totalRequisitions,
        'Statut': '',
        'Demandeur': '',
        'Approbateur': '',
        'Date approbation': '',
        'Caissier(e)': '',
        'Date décaissement': '',
        'Mode paiement': ''
      })

      const ws = XLSX.utils.json_to_sheet(dataToExport)
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Réquisitions')

      const periodeSuffix = dateDebut || dateFin
        ? `_${dateDebut || 'debut'}_${dateFin || 'fin'}`
        : `_${format(new Date(), 'yyyy-MM-dd')}`

      XLSX.writeFile(wb, `requisitions${periodeSuffix}.xlsx`)
    } catch (error: any) {
      console.error('Error exporting Excel:', error)
      setNotification({
        show: true,
        type: 'error',
        title: 'Erreur export Excel',
        message: 'Impossible d’exporter le fichier Excel. Veuillez réessayer.'
      })
    }
  }

  const exportToPDF = async () => {
    const dataForPDF = await Promise.all(
      filteredRequisitions.map(async (req) => {
        const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } })
        const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []

        const rubriques = lignesData
          ? [...new Set(lignesData.map((l: any) => l.rubrique))].join(', ')
          : ''

        return {
          ...req,
          rubriques
        }
      })
    )

    const start = dateDebut || format(new Date(), 'yyyy-MM-dd')
    const end = dateFin || format(new Date(), 'yyyy-MM-dd')

    await generateRequisitionsPDF(
      dataForPDF,
      start,
      end,
      `${user?.prenom} ${user?.nom}`
    )
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Réquisitions de fonds</h1>
          <p>Demandes et workflow d'approbation</p>
        </div>
        {canCreate && (
          <button onClick={() => { setFormData({ ...formData, type_requisition: activeTab }); setShowForm(true); }} className={styles.primaryBtn}>
            + Nouvelle réquisition
          </button>
        )}
      </div>

      <div style={{marginBottom: '24px', borderBottom: '2px solid #e5e7eb'}}>
        <div style={{display: 'flex', gap: '8px'}}>
          <button
            onClick={() => setActiveTab('classique')}
            style={{
              padding: '12px 24px',
              background: activeTab === 'classique' ? 'white' : 'transparent',
              border: 'none',
              borderBottom: activeTab === 'classique' ? '3px solid #0d9488' : '3px solid transparent',
              color: activeTab === 'classique' ? '#0d9488' : '#6b7280',
              fontWeight: activeTab === 'classique' ? 600 : 500,
              cursor: 'pointer',
              fontSize: '15px',
              transition: 'all 0.2s'
            }}
          >
            Réquisitions classiques
          </button>
          <button
            onClick={() => setActiveTab('mini')}
            style={{
              padding: '12px 24px',
              background: activeTab === 'mini' ? 'white' : 'transparent',
              border: 'none',
              borderBottom: activeTab === 'mini' ? '3px solid #0d9488' : '3px solid transparent',
              color: activeTab === 'mini' ? '#0d9488' : '#6b7280',
              fontWeight: activeTab === 'mini' ? 600 : 500,
              cursor: 'pointer',
              fontSize: '15px',
              transition: 'all 0.2s'
            }}
          >
            Mini-réquisitions
          </button>
          <button
            onClick={() => setActiveTab('remboursement_transport')}
            style={{
              padding: '12px 24px',
              background: activeTab === 'remboursement_transport' ? 'white' : 'transparent',
              border: 'none',
              borderBottom: activeTab === 'remboursement_transport' ? '3px solid #0d9488' : '3px solid transparent',
              color: activeTab === 'remboursement_transport' ? '#0d9488' : '#6b7280',
              fontWeight: activeTab === 'remboursement_transport' ? 600 : 500,
              cursor: 'pointer',
              fontSize: '15px',
              transition: 'all 0.2s'
            }}
          >
            Remboursement transport
          </button>
        </div>
      </div>

      <div className={styles.filtersSection}>
        <div className={styles.filtersGrid}>
          <div className={styles.searchBar}>
            <input
              type="text"
              placeholder="Rechercher par numéro ou objet..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className={styles.filterGroup}>
            <label>Statut</label>
            <select value={filterStatut} onChange={(e) => setFilterStatut(e.target.value)}>
              <option value="">Tous les statuts</option>
              <option value="EN_ATTENTE">En attente</option>
              <option value="VALIDEE">Validée</option>
              <option value="REJETEE">Rejetée</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Mode de paiement</label>
            <select value={filterModePaiement} onChange={(e) => setFilterModePaiement(e.target.value)}>
              <option value="">Tous les modes</option>
              <option value="cash">Caisse</option>
              <option value="mobile_money">Mobile Money</option>
              <option value="virement">Virement bancaire</option>
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Rubrique</label>
            <select value={filterRubrique} onChange={(e) => setFilterRubrique(e.target.value)}>
              <option value="">Toutes les rubriques</option>
              {rubriquesList.map(r => (
                <option key={r.id} value={r.code}>{r.libelle}</option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <label>Recherche objet</label>
            <input
              type="text"
              value={filterObjet}
              onChange={(e) => setFilterObjet(e.target.value)}
              placeholder="Filtrer par objet..."
            />
          </div>
        </div>

        {hasActiveFilters && (
          <div className={styles.filtersActions}>
            <div className={styles.resultsInfo}>
              <p>
                <strong>{filteredRequisitions.length}</strong> réquisition{filteredRequisitions.length > 1 ? 's' : ''} trouvée{filteredRequisitions.length > 1 ? 's' : ''}
                <span className={styles.totalCount}> sur {requisitionsList.length} au total</span>
              </p>
            </div>
            <button onClick={clearFilters} className={styles.clearFiltersBtn}>
              Réinitialiser les filtres
            </button>
          </div>
        )}
      </div>

      <div className={styles.periodSection}>
        <h3>Filtrer par période</h3>
        <div className={styles.periodGrid}>
          <div className={styles.periodField}>
            <label>Date début</label>
            <input
              type="date"
              value={dateDebut}
              onChange={(e) => setDateDebut(e.target.value)}
            />
          </div>
          <div className={styles.periodField}>
            <label>Date fin</label>
            <input
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
            />
          </div>
          {(dateDebut || dateFin) && (
            <button
              onClick={() => {
                setDateDebut('')
                setDateFin('')
              }}
              className={styles.clearFiltersBtn}
            >
              Réinitialiser période
            </button>
          )}
          {filteredRequisitions.length > 0 && (
            <div className={styles.exportButtons}>
              <button onClick={exportToExcel} className={`${styles.exportBtn} ${styles.exportExcel}`}>
                Exporter Excel
              </button>
              <button onClick={exportToPDF} className={`${styles.exportBtn} ${styles.exportPDF}`}>
                Exporter PDF
              </button>
            </div>
          )}
        </div>
        {(dateDebut || dateFin) && (
          <div className={styles.recapCard}>
            <div className={styles.recapHeader}>
              <span>Récapitulatif période</span>
            </div>
            <div className={styles.recapGrid}>
              <div className={styles.recapItem}>
                <span className={styles.recapLabel}>Total des réquisitions</span>
                <span className={styles.recapValue}>
                  {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(totalRequisitions)}
                </span>
              </div>
              <div className={styles.recapItem}>
                <span className={styles.recapLabel}>Nombre de réquisitions</span>
                <span className={styles.recapValue}>
                  {filteredRequisitions.length}
                </span>
              </div>
            </div>
            <div className={styles.recapFooter}>
              {filteredRequisitions.length} réquisition{filteredRequisitions.length > 1 ? 's' : ''} sur la période
            </div>
          </div>
        )}
      </div>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Nouvelle réquisition</h2>
              <button onClick={() => { setShowForm(false); resetForm(); }} className={styles.closeBtn}>×</button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Objet de la réquisition *</label>
                <textarea
                  value={formData.objet}
                  onChange={(e) => setFormData({ ...formData, objet: e.target.value })}
                  rows={2}
                  placeholder="Ex: Achat de livres pour la bibliothèque"
                  required
                />
              </div>

              <div className={styles.field}>
                <label>Type de réquisition *</label>
                <select
                  value={formData.type_requisition}
                  onChange={(e) => setFormData({ ...formData, type_requisition: e.target.value as any })}
                  required
                >
                  <option value="classique">Réquisition classique</option>
                  <option value="mini">Mini-réquisition</option>
                  <option value="remboursement_transport">Remboursement transport</option>
                </select>
              </div>

              <div className={styles.field}>
                <label>Mode de paiement *</label>
                <select
                  value={formData.mode_paiement}
                  onChange={(e) => setFormData({ ...formData, mode_paiement: e.target.value as ModePatement })}
                  required
                >
                  <option value="cash">Caisse</option>
                  <option value="mobile_money">Mobile Money</option>
                  <option value="virement">Virement bancaire</option>
                </select>
              </div>

              <div className={styles.field}>
                <div style={{display: 'flex', alignItems: 'center', gap: '12px', padding: '12px', background: '#f9fafb', borderRadius: '8px', border: '1px solid #e5e7eb'}}>
                  <input
                    type="checkbox"
                    id="a_valoir"
                    checked={formData.a_valoir}
                    onChange={(e) => setFormData({ ...formData, a_valoir: e.target.checked })}
                    style={{width: '18px', height: '18px', cursor: 'pointer'}}
                  />
                  <label htmlFor="a_valoir" style={{cursor: 'pointer', margin: 0, fontWeight: 600, color: '#374151'}}>
                    À valoir (à rembourser par une autre instance)
                  </label>
                </div>
              </div>

              {formData.a_valoir && (
                <>
                  <div className={styles.field}>
                    <label>Instance bénéficiaire (qui doit rembourser) *</label>
                    <select
                      value={formData.instance_beneficiaire}
                      onChange={(e) => setFormData({ ...formData, instance_beneficiaire: e.target.value })}
                      required
                    >
                      <option value="">Sélectionnez l'instance</option>
                      <option value="Conseil National">Conseil National</option>
                      <option value="Conseil Provincial de Kinshasa">Conseil Provincial de Kinshasa</option>
                      <option value="Autre instance">Autre instance</option>
                    </select>
                  </div>

                  <div className={styles.field}>
                    <label>Notes / Justification</label>
                    <textarea
                      value={formData.notes_a_valoir}
                      onChange={(e) => setFormData({ ...formData, notes_a_valoir: e.target.value })}
                      rows={2}
                      placeholder="Ex: Dépense effectuée pour le compte du Conseil National qui remboursera..."
                    />
                  </div>
                </>
              )}

              <div className={styles.lignesSection}>
                <div className={styles.lignesHeader}>
                  <h3>Lignes de dépense</h3>
                  <button type="button" onClick={addLigne} className={styles.addBtn}>
                    + Ajouter une ligne
                  </button>
                </div>

                {lignes.map((ligne, index) => (
                  <div key={index} className={styles.ligne}>
                    <div className={styles.ligneFields}>
                      <div className={styles.field}>
                        <label>Rubrique *</label>
                        <select
                          value={ligne.rubrique}
                          onChange={(e) => updateLigne(index, 'rubrique', e.target.value)}
                          required
                        >
                          <option value="">Sélectionner...</option>
                          {rubriquesList.map(r => (
                            <option key={r.id} value={r.code}>{r.libelle}</option>
                          ))}
                        </select>
                      </div>

                      <div className={styles.field}>
                        <label>Description *</label>
                        <input
                          type="text"
                          value={ligne.description}
                          onChange={(e) => updateLigne(index, 'description', e.target.value)}
                          required
                        />
                      </div>

                      <div className={styles.field} style={{flex: 0.5}}>
                        <label>Qté *</label>
                        <input
                          type="number"
                          value={ligne.quantite}
                          onChange={(e) => updateLigne(index, 'quantite', parseInt(e.target.value) || 0)}
                          min="1"
                          required
                        />
                      </div>

                      <div className={styles.field}>
                        <label>Prix unit. *</label>
                        <input
                          type="number"
                          step="0.01"
                          value={ligne.montant_unitaire}
                          onChange={(e) => updateLigne(index, 'montant_unitaire', parseFloat(e.target.value) || 0)}
                          required
                        />
                      </div>

                      <div className={styles.field}>
                        <label>Total</label>
                        <input
                          type="text"
                          value={formatCurrency(ligne.montant_total)}
                          readOnly
                          disabled
                        />
                      </div>
                    </div>

                    {lignes.length > 1 && (
                      <button type="button" onClick={() => removeLigne(index)} className={styles.removeBtn}>
                        ×
                      </button>
                    )}
                  </div>
                ))}

                <div className={styles.total}>
                  <strong>Total général:</strong>
                  <strong>{formatCurrency(calculateTotal())}</strong>
                </div>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => { setShowForm(false); resetForm(); }} className={styles.secondaryBtn} disabled={submitting}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                  {submitting ? 'Création en cours...' : 'Créer la réquisition'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>N° Réquisition</th>
              <th
                className={styles.sortableHeader}
                onClick={() => handleSort('created_at')}
              >
                Date
                {sortField === 'created_at' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th>Objet</th>
              <th
                className={styles.sortableHeader}
                onClick={() => handleSort('montant_total')}
              >
                Montant
                {sortField === 'montant_total' && (
                  <span className={styles.sortIcon}>{sortDirection === 'asc' ? ' ▲' : ' ▼'}</span>
                )}
              </th>
              <th>Type</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredRequisitions.length === 0 ? (
              <tr>
                <td colSpan={7} className={styles.empty}>
                  Aucune réquisition trouvée
                </td>
              </tr>
            ) : (
              filteredRequisitions.map((req) => (
                <tr key={req.id}>
                  <td>{req.numero_requisition}</td>
                  <td>{format(new Date(req.created_at), 'dd/MM/yyyy')}</td>
                  <td>{req.objet}</td>
                  <td>{formatCurrency(Number(req.montant_total))}</td>
                  <td>
                    {(req as any).a_valoir ? (
                      <div style={{display: 'flex', flexDirection: 'column', gap: '4px'}}>
                        <span style={{
                          padding: '4px 8px',
                          borderRadius: '6px',
                          background: '#fef3c7',
                          color: '#92400e',
                          fontSize: '11px',
                          fontWeight: 600,
                          display: 'inline-block',
                          border: '1px solid #fbbf24'
                        }}>
                          À VALOIR
                        </span>
                        {(req as any).instance_beneficiaire && (
                          <span style={{fontSize: '10px', color: '#6b7280'}}>
                            {(req as any).instance_beneficiaire}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span style={{
                        padding: '4px 8px',
                        borderRadius: '6px',
                        background: '#f3f4f6',
                        color: '#6b7280',
                        fontSize: '11px',
                        fontWeight: 500
                      }}>
                        Standard
                      </span>
                    )}
                  </td>
                  <td>{getStatutBadge((req as any).status ?? req.statut)}</td>
                  <td>
                    <div className={styles.actions}>
                      <button
                        onClick={() => viewDetails(req)}
                        className={styles.viewBtn}
                        title="Voir les détails"
                      >
                        Voir détails
                      </button>
                      <button
                        onClick={() => printRequisition(req)}
                        className={styles.actionBtn}
                        style={{background: '#dbeafe', color: '#1e40af', border: '1px solid #3b82f6'}}
                        title="Imprimer la réquisition"
                      >
                        Imprimer
                      </button>
                      <button
                        onClick={() => downloadRequisition(req)}
                        className={styles.actionBtn}
                        style={{background: '#f3e8ff', color: '#7c3aed', border: '1px solid #a855f7'}}
                        title="Télécharger la réquisition en PDF"
                      >
                        Télécharger
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showDetailModal && selectedRequisition && (
        <div className={styles.modal}>
          <div className={styles.modalContent} style={{maxWidth: '1000px'}}>
            <div className={styles.modalHeader}>
              <h2>Détails de la réquisition {selectedRequisition.numero_requisition}</h2>
              <button onClick={() => setShowDetailModal(false)} className={styles.closeBtn}>×</button>
            </div>

            <div className={styles.detailContent}>
              <div className={styles.detailSection} style={{background: '#f0fdf4', borderLeft: '4px solid #16a34a'}}>
                <h3 style={{color: '#16a34a', marginBottom: '16px'}}>Traçabilité et Responsabilité</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Demandeur</label>
                    <p><strong>{selectedRequisitionUsers.demandeur ? `${selectedRequisitionUsers.demandeur.prenom} ${selectedRequisitionUsers.demandeur.nom}` : 'Non disponible'}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Date de la demande</label>
                    <p>{format(new Date(selectedRequisition.created_at), 'dd/MM/yyyy à HH:mm')}</p>
                  </div>
                  {((selectedRequisition as any).validee_par || (selectedRequisition as any).approuvee_par) && (
                    <>
                      <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Validateur / Rejeteur</label>
                    <p><strong>
                      {selectedRequisitionUsers.approbateur
                        ? `${selectedRequisitionUsers.approbateur.prenom} ${selectedRequisitionUsers.approbateur.nom}`
                        : selectedRequisitionUsers.validateur
                        ? `${selectedRequisitionUsers.validateur.prenom} ${selectedRequisitionUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Date de validation / rejet</label>
                        <p>
                          {(selectedRequisition as any).approuvee_le
                            ? format(new Date((selectedRequisition as any).approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : (selectedRequisition as any).validee_le
                            ? format(new Date((selectedRequisition as any).validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Statut actuel</label>
                    <p>{getStatutBadge((selectedRequisition as any).status ?? selectedRequisition.statut)}</p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedRequisition.numero_requisition}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Objet</label>
                    <p>{selectedRequisition.objet}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Mode de paiement</label>
                    <p>
                      {selectedRequisition.mode_paiement === 'cash' && 'Caisse'}
                      {selectedRequisition.mode_paiement === 'mobile_money' && 'Mobile Money'}
                      {selectedRequisition.mode_paiement === 'virement' && 'Virement bancaire'}
                    </p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{formatCurrency(Number(selectedRequisition.montant_total))}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Lignes de dépense</h3>
                <table className={styles.detailTable}>
                  <thead>
                    <tr>
                      <th>Rubrique</th>
                      <th>Description</th>
                      <th>Qté</th>
                      <th>Prix unitaire</th>
                      <th>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedLignesList.map((ligne) => (
                      <tr key={ligne.id}>
                        <td><span className={styles.rubriqueTag}>{ligne.rubrique}</span></td>
                        <td>{ligne.description}</td>
                        <td>{ligne.quantite}</td>
                        <td>{formatCurrency(Number(ligne.montant_unitaire))}</td>
                        <td><strong>{formatCurrency(Number(ligne.montant_total))}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={4} style={{textAlign: 'right', fontWeight: 600}}>Total général:</td>
                      <td><strong style={{fontSize: '16px', color: '#0d9488'}}>{formatCurrency(Number(selectedRequisition.montant_total))}</strong></td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              {selectedRequisition.motif_rejet && (
                <div className={styles.detailSection} style={{background: '#fee2e2', borderLeft: '4px solid #dc2626'}}>
                  <h3 style={{color: '#dc2626'}}>Motif du rejet</h3>
                  <p>{selectedRequisition.motif_rejet}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {notification.show && (
        <div className={styles.notificationOverlay}>
          <div className={`${styles.notificationBox} ${notification.type === 'success' ? styles.notificationSuccess : styles.notificationError}`}>
            <div className={styles.notificationHeader}>
              <div className={styles.notificationIcon}>
                {notification.type === 'success' ? '✓' : '✕'}
              </div>
              <h3>{notification.title}</h3>
            </div>
            <p className={styles.notificationMessage}>{notification.message}</p>
            <button
              onClick={() => setNotification({ ...notification, show: false })}
              className={styles.notificationBtn}
            >
              OK
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
