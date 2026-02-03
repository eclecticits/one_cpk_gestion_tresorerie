import { useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { SortieFonds, ModePatement, TypeSortieFonds } from '../types'
import { format } from 'date-fns'
import * as XLSX from 'xlsx'
import styles from './SortiesFonds.module.css'
import SortieFondsNotification from '../components/SortieFondsNotification'
import { CATEGORIES_SORTIE, getTypeSortieLabel, getBeneficiairePlaceholder, getMotifPlaceholder } from '../utils/sortieFondsHelpers'

export default function SortiesFonds() {
  const { user } = useAuth()
  const [showForm, setShowForm] = useState(false)
  const [sorties, setSorties] = useState<SortieFonds[]>([])
  const [requisitionsApprouvees, setRequisitionsApprouvees] = useState<any[]>([])
  const [rubriques, setRubriques] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [showSuccessNotification, setShowSuccessNotification] = useState(false)
  const [lastCreatedSortie, setLastCreatedSortie] = useState<any>(null)
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [filterType, setFilterType] = useState<string>('')
  const [filterModePaiement, setFilterModePaiement] = useState<string>('')
  const [filterNumeroRequisition, setFilterNumeroRequisition] = useState('')

  const [formData, setFormData] = useState({
    type_sortie: 'versement_banque' as TypeSortieFonds,
    requisition_id: '',
    montant_paye: '',
    date_paiement: format(new Date(), 'yyyy-MM-dd'),
    mode_paiement: 'cash' as ModePatement,
    reference: '',
    commentaire: '',
    motif: '',
    rubrique_code: '',
    beneficiaire: '',
    piece_justificative: ''
  })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [sortiesRes, reqRes, rubriquesRes] = await Promise.all([
        apiRequest('GET', '/sorties-fonds', { params: { include: 'requisition', limit: 100 } }),
        apiRequest('GET', '/requisitions', { params: { status_in: 'EN_ATTENTE,A_VALIDER,VALIDEE', include: 'created_by_user,approved_by_user', limit: 200 } }),
        apiRequest('GET', '/rubriques', { params: { active: true } }),
      ])

      if (sortiesRes) setSorties(sortiesRes as any)
      const items = Array.isArray(reqRes) ? reqRes : (reqRes as any)?.items ?? []
      const allowedStatuses = new Set(['EN_ATTENTE', 'A_VALIDER', 'VALIDEE'])
      const filteredReqs = (items as any[]).filter((r) => {
        const statusValue = (r as any).status ?? (r as any).statut
        return statusValue ? allowedStatuses.has(String(statusValue)) : false
      })
      setRequisitionsApprouvees(filteredReqs as any)
      if (rubriquesRes) setRubriques(rubriquesRes as any)
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (submitting) return

    if (!formData.montant_paye) {
      alert('⚠ CHAMPS OBLIGATOIRES MANQUANTS\n\nVeuillez saisir le montant.')
      return
    }

    if (formData.type_sortie === 'requisition' && !formData.requisition_id) {
      alert('⚠ RÉQUISITION OBLIGATOIRE\n\nVeuillez sélectionner une réquisition approuvée.')
      return
    }

    if (formData.type_sortie === 'sortie_directe' && parseFloat(formData.montant_paye) > 100) {
      alert('⚠ MONTANT MAXIMUM DÉPASSÉ\n\nLes sorties directes sont limitées à 100 $.\n\nPour les montants supérieurs, vous devez créer une réquisition.')
      return
    }

    if (!formData.motif.trim()) {
      alert('⚠ MOTIF OBLIGATOIRE\n\nLe motif est obligatoire pour toutes les sorties.')
      return
    }

    if (!formData.beneficiaire.trim()) {
      alert('⚠ BÉNÉFICIAIRE OBLIGATOIRE\n\nLe bénéficiaire est obligatoire pour toutes les sorties.')
      return
    }

    if (formData.type_sortie === 'sortie_directe' && !formData.rubrique_code) {
      alert('⚠ RUBRIQUE OBLIGATOIRE\n\nLa rubrique est obligatoire pour les sorties directes.')
      return
    }

    if ((formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && !formData.reference) {
      alert('⚠ RÉFÉRENCE OBLIGATOIRE\n\nLa référence est obligatoire pour les paiements par Mobile Money ou Virement bancaire.')
      return
    }

    setSubmitting(true)
    try {
      const selectedReq = formData.type_sortie === 'requisition'
        ? requisitionsApprouvees.find(r => r.id === formData.requisition_id)
        : null

      const isRemboursementTransport = selectedReq?.type_requisition === 'remboursement_transport'

      const sortieInsert: any = {
        type_sortie: formData.type_sortie === 'requisition' && isRemboursementTransport
          ? 'remboursement'
          : formData.type_sortie,
        montant_paye: parseFloat(formData.montant_paye),
        date_paiement: formData.date_paiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        motif: formData.motif,
        beneficiaire: formData.beneficiaire,
        piece_justificative: formData.piece_justificative || null,
        commentaire: formData.commentaire || null,
        created_by: user?.id,
      }

      if (formData.type_sortie === 'requisition') {
        sortieInsert.requisition_id = formData.requisition_id
      }

      if (formData.type_sortie === 'sortie_directe' && formData.rubrique_code) {
        sortieInsert.rubrique_code = formData.rubrique_code
      }

      await apiRequest('POST', '/sorties-fonds', sortieInsert)

      if (formData.type_sortie === 'requisition') {
        await apiRequest('PUT', `/requisitions/${formData.requisition_id}`, {
          statut: 'payee',
          payee_par: user?.id,
          payee_le: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })

        setLastCreatedSortie({
          requisition: selectedReq,
          sortie: {
            montant_paye: parseFloat(formData.montant_paye),
            mode_paiement: formData.mode_paiement,
            date_paiement: formData.date_paiement,
            reference: formData.reference
          }
        })
        setShowSuccessNotification(true)
      } else {
        alert(`✓ SORTIE ENREGISTRÉE\n\nLa sortie de fonds a été enregistrée avec succès.\n\nType: ${getTypeSortieLabel(formData.type_sortie)}\nMontant: ${parseFloat(formData.montant_paye).toFixed(2)} $\nBénéficiaire: ${formData.beneficiaire}\nMotif: ${formData.motif}`)
      }

      setShowForm(false)
      setFormData({
        type_sortie: 'versement_banque',
        requisition_id: '',
        montant_paye: '',
        date_paiement: format(new Date(), 'yyyy-MM-dd'),
        mode_paiement: 'cash',
        reference: '',
        commentaire: '',
        motif: '',
        rubrique_code: '',
        beneficiaire: '',
        piece_justificative: ''
      })
      loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))
    } catch (error: any) {
      console.error('Error creating sortie:', error)
      const errorMessage = error?.message || 'Erreur inconnue'
      alert(`✕ ERREUR D'ENREGISTREMENT\n\nUne erreur est survenue lors de l'enregistrement de la sortie de fonds:\n\n${errorMessage}\n\nVeuillez vérifier les informations et réessayer.`)
    } finally {
      setSubmitting(false)
    }
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const canCreate = user?.role === 'tresorerie' || user?.role === 'admin'

  const sortiesList = Array.isArray(sorties) ? sorties : []
  const requisitionsApprouveesList = Array.isArray(requisitionsApprouvees) ? requisitionsApprouvees : []
  const rubriquesList = Array.isArray(rubriques) ? rubriques : []

  const filteredSorties = sortiesList.filter(sortie => {
    const sortieWithType = sortie as any
    const typeSortie = sortieWithType.type_sortie || 'requisition'

    if (dateDebut || dateFin) {
      const sortieDate = new Date(sortie.date_paiement)
      const debut = dateDebut ? new Date(dateDebut) : null
      const fin = dateFin ? new Date(dateFin) : null

      if (debut && sortieDate < debut) return false
      if (fin && sortieDate > fin) return false
    }

    if (filterType && typeSortie !== filterType) return false

    if (filterModePaiement && sortie.mode_paiement !== filterModePaiement) return false

    if (filterNumeroRequisition) {
      const numeroReq = sortie.requisition?.numero_requisition || ''
      if (!numeroReq.toLowerCase().includes(filterNumeroRequisition.toLowerCase())) return false
    }

    return true
  })

  const totalSorties = filteredSorties.reduce((sum, s) => sum + Number(s.montant_paye), 0)

  const exportToExcel = async () => {
    const dataToExport = await Promise.all(
      filteredSorties.map(async (sortie) => {
        let rubriques = ''
        if (sortie.requisition_id) {
          const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: sortie.requisition_id } })

          const lignesList = Array.isArray(lignesRes) ? lignesRes : []
          rubriques = lignesList.length > 0
            ? [...new Set(lignesList.map((l: any) => l.rubrique))].join(', ')
            : ''
        }

        return {
          'Date': format(new Date(sortie.date_paiement), 'dd/MM/yyyy'),
          'N° Réquisition': sortie.requisition?.numero_requisition || '',
          'Objet': sortie.requisition?.objet || '',
          'Rubrique': rubriques,
          'Montant payé (USD)': Number(sortie.montant_paye),
          'Mode de paiement': sortie.mode_paiement === 'cash' ? 'Caisse' :
                              sortie.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement bancaire',
          'Référence': sortie.reference || '',
          'Commentaire': sortie.commentaire || ''
        }
      })
    )

    dataToExport.push({
      'Date': '',
      'N° Réquisition': '',
      'Objet': 'TOTAL',
      'Rubrique': '',
      'Montant payé (USD)': totalSorties,
      'Mode de paiement': '',
      'Référence': '',
      'Commentaire': ''
    })

    const ws = XLSX.utils.json_to_sheet(dataToExport)
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Sorties de fonds')

    const periodeSuffix = dateDebut || dateFin
      ? `_${dateDebut || 'debut'}_${dateFin || 'fin'}`
      : `_${format(new Date(), 'yyyy-MM-dd')}`

    XLSX.writeFile(wb, `sorties_fonds${periodeSuffix}.xlsx`)
  }

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Sorties de fonds</h1>
          <p>Enregistrement des paiements effectués</p>
        </div>
        {canCreate && (
          <button onClick={() => setShowForm(true)} className={styles.primaryBtn}>
            + Nouvelle sortie
          </button>
        )}
      </div>

      {canCreate && requisitionsApprouvees.length > 0 && (
        <div className={styles.infoBox} style={{marginBottom: '20px', padding: '15px', background: '#dcfce7', borderLeft: '4px solid #16a34a', borderRadius: '4px'}}>
          {requisitionsApprouvees.length > 0 && (
            <p style={{margin: 0, fontSize: '14px', color: '#166534'}}>
              <strong>{requisitionsApprouvees.length}</strong> réquisition{requisitionsApprouvees.length > 1 ? 's' : ''} en attente{requisitionsApprouvees.length > 1 ? 's' : ''} de traitement
            </p>
          )}
        </div>
      )}

      <div className={styles.filtersSection} style={{marginBottom: '20px', padding: '20px', background: 'white', borderRadius: '8px', border: '1px solid #e5e7eb'}}>
        <h3 style={{margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600}}>Filtres</h3>

        <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '16px'}}>
          <div>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500, color: '#374151'}}>
              Type de sortie
            </label>
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '14px'}}
            >
              <option value="">Tous les types</option>
              <option value="requisition">Réquisition classique</option>
              <option value="remboursement">Remboursement transport</option>
              <option value="versement_banque">Versement banque</option>
              <option value="sortie_directe">Autre</option>
            </select>
          </div>

          <div>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500, color: '#374151'}}>
              Mode de paiement
            </label>
            <select
              value={filterModePaiement}
              onChange={(e) => setFilterModePaiement(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '14px'}}
            >
              <option value="">Tous les modes</option>
              <option value="cash">Cash</option>
              <option value="mobile_money">Mobile Money</option>
              <option value="virement">Virement bancaire</option>
            </select>
          </div>

          <div>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500, color: '#374151'}}>
              N° Réquisition
            </label>
            <input
              type="text"
              value={filterNumeroRequisition}
              onChange={(e) => setFilterNumeroRequisition(e.target.value)}
              placeholder="Rechercher..."
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '14px'}}
            />
          </div>

          <div>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500, color: '#374151'}}>
              Date début
            </label>
            <input
              type="date"
              value={dateDebut}
              onChange={(e) => setDateDebut(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '14px'}}
            />
          </div>

          <div>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500, color: '#374151'}}>
              Date fin
            </label>
            <input
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px', fontSize: '14px'}}
            />
          </div>
        </div>

        <div style={{display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap'}}>
          {(dateDebut || dateFin || filterType || filterModePaiement || filterNumeroRequisition) && (
            <button
              onClick={() => {
                setDateDebut('')
                setDateFin('')
                setFilterType('')
                setFilterModePaiement('')
                setFilterNumeroRequisition('')
              }}
              style={{padding: '10px 20px', background: '#f3f4f6', border: '1px solid #d1d5db', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: 500}}
            >
              Réinitialiser tous les filtres
            </button>
          )}
          {filteredSorties.length > 0 && (
            <button
              onClick={exportToExcel}
              style={{padding: '10px 20px', background: '#16a34a', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: 500}}
            >
              📊 Exporter Excel
            </button>
          )}
        </div>
        {(dateDebut || dateFin) && (
          <div style={{marginTop: '16px', padding: '12px', background: '#f0fdf4', borderRadius: '6px', border: '1px solid #bbf7d0'}}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
              <span style={{fontSize: '14px', color: '#166534', fontWeight: 500}}>
                Total des sorties sur la période :
              </span>
              <span style={{fontSize: '18px', color: '#16a34a', fontWeight: 700}}>
                {formatCurrency(totalSorties)}
              </span>
            </div>
            <div style={{marginTop: '8px', fontSize: '13px', color: '#166534'}}>
              {filteredSorties.length} opération{filteredSorties.length > 1 ? 's' : ''}
            </div>
          </div>
        )}
      </div>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Nouvelle sortie de fonds</h2>
              <button onClick={() => setShowForm(false)} className={styles.closeBtn}>×</button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Type de sortie *</label>
                <select
                  value={formData.type_sortie}
                  onChange={(e) => setFormData({
                    ...formData,
                    type_sortie: e.target.value as TypeSortieFonds,
                    requisition_id: '',
                    montant_paye: '',
                    motif: '',
                    rubrique_code: '',
                    beneficiaire: ''
                  })}
                  required
                >
                  {CATEGORIES_SORTIE.map((categorie) => (
                    <optgroup key={categorie.label} label={categorie.label}>
                      {categorie.types.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>

              {formData.type_sortie === 'requisition' && (
                <div className={styles.field}>
                  <label>Réquisition approuvée *</label>
                  <select
                    value={formData.requisition_id}
                    onChange={(e) => {
                      const req = requisitionsApprouveesList.find(r => r.id === e.target.value)
                      setFormData({
                        ...formData,
                        requisition_id: e.target.value,
                        montant_paye: req ? req.montant_total.toString() : '',
                        mode_paiement: req?.mode_paiement || 'cash'
                      })
                    }}
                    required
                  >
                    <option value="">Sélectionner une réquisition...</option>
                    {requisitionsApprouveesList.map(req => (
                      <option key={req.id} value={req.id}>
                        {req.numero_requisition} - {req.objet} ({formatCurrency(Number(req.montant_total))})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.field}>
                <label>Motif de la sortie *</label>
                <textarea
                  value={formData.motif}
                  onChange={(e) => setFormData({ ...formData, motif: e.target.value })}
                  rows={3}
                  placeholder={getMotifPlaceholder(formData.type_sortie)}
                  required
                  style={{ resize: 'vertical' }}
                />
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Soyez descriptif et précis dans votre motif pour faciliter le suivi
                </small>
              </div>

              <div className={styles.field}>
                <label>Bénéficiaire *</label>
                <input
                  type="text"
                  value={formData.beneficiaire}
                  onChange={(e) => setFormData({ ...formData, beneficiaire: e.target.value })}
                  placeholder={getBeneficiairePlaceholder(formData.type_sortie)}
                  required
                />
              </div>

              {formData.type_sortie === 'sortie_directe' && (
                <div className={styles.field}>
                  <label>Rubrique *</label>
                  <select
                    value={formData.rubrique_code}
                    onChange={(e) => setFormData({ ...formData, rubrique_code: e.target.value })}
                    required
                  >
                    <option value="">Sélectionner une rubrique...</option>
                    {rubriquesList.map(r => (
                      <option key={r.id} value={r.code}>{r.libelle}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>
                    Montant (USD) *
                    {formData.type_sortie === 'sortie_directe' && (
                      <span style={{color: '#dc2626', fontSize: '12px', marginLeft: '8px'}}>
                        (Maximum 100 $)
                      </span>
                    )}
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    value={formData.montant_paye}
                    onChange={(e) => setFormData({ ...formData, montant_paye: e.target.value })}
                    max={formData.type_sortie === 'sortie_directe' ? 100 : undefined}
                    required
                    disabled={formData.type_sortie === 'requisition' && !!formData.requisition_id}
                  />
                </div>

                <div className={styles.field}>
                  <label>Date de paiement *</label>
                  <input
                    type="date"
                    value={formData.date_paiement}
                    onChange={(e) => setFormData({ ...formData, date_paiement: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Mode de paiement *</label>
                  <select
                    value={formData.mode_paiement}
                    onChange={(e) => setFormData({ ...formData, mode_paiement: e.target.value as ModePatement })}
                    required
                  >
                    <option value="cash">Cash</option>
                    <option value="mobile_money">Mobile Money</option>
                    <option value="virement">Virement bancaire</option>
                  </select>
                </div>

                {(formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && (
                  <div className={styles.field}>
                    <label>Référence *</label>
                    <input
                      type="text"
                      value={formData.reference}
                      onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                      placeholder="N° de transaction, virement, etc."
                      required
                    />
                  </div>
                )}

                {formData.mode_paiement === 'cash' && (
                  <div className={styles.field}>
                    <label>Référence (optionnel)</label>
                    <input
                      type="text"
                      value={formData.reference}
                      onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                      placeholder="Ex: Bordereau, reçu, etc."
                    />
                  </div>
                )}
              </div>

              <div className={styles.field}>
                <label>Pièce justificative (optionnel)</label>
                <input
                  type="text"
                  value={formData.piece_justificative}
                  onChange={(e) => setFormData({ ...formData, piece_justificative: e.target.value })}
                  placeholder="Référence de la facture, reçu, bordereau, etc."
                />
                <small style={{ color: '#6b7280', fontSize: '12px' }}>
                  Indiquez le numéro ou la référence du document justificatif
                </small>
              </div>

              <div className={styles.field}>
                <label>Observation (optionnel)</label>
                <textarea
                  value={formData.commentaire}
                  onChange={(e) => setFormData({ ...formData, commentaire: e.target.value })}
                  rows={2}
                  placeholder="Informations complémentaires..."
                  style={{ resize: 'vertical' }}
                />
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => setShowForm(false)} className={styles.secondaryBtn} disabled={submitting}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                  {submitting ? 'Enregistrement en cours...' : 'Enregistrer le paiement'}
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
              <th>Date</th>
              <th>Type</th>
              <th>N° Réquisition / Motif</th>
              <th>Objet / Bénéficiaire</th>
              <th>Montant payé</th>
              <th>Mode de paiement</th>
              <th>Référence</th>
            </tr>
          </thead>
          <tbody>
            {filteredSorties.length === 0 ? (
              <tr>
                <td colSpan={7} style={{textAlign: 'center', padding: '30px', color: '#9ca3af'}}>
                  {dateDebut || dateFin ? 'Aucune sortie de fonds trouvée pour cette période' : 'Aucune sortie de fonds enregistrée'}
                </td>
              </tr>
            ) : (
              filteredSorties.map((sortie) => {
                const sortieWithType = sortie as any
                const typeSortie = sortieWithType.type_sortie || 'requisition'

                return (
                  <tr key={sortie.id}>
                    <td>{format(new Date(sortie.date_paiement), 'dd/MM/yyyy')}</td>
                    <td>
                      <span style={{
                        padding: '4px 8px',
                        borderRadius: '6px',
                        fontSize: '11px',
                        fontWeight: 600,
                        background: typeSortie === 'requisition' ? '#dbeafe' :
                                   typeSortie === 'remboursement' ? '#e0e7ff' :
                                   typeSortie === 'versement_banque' ? '#fef3c7' : '#fee2e2',
                        color: typeSortie === 'requisition' ? '#1e40af' :
                               typeSortie === 'remboursement' ? '#3730a3' :
                               typeSortie === 'versement_banque' ? '#92400e' : '#dc2626'
                      }}>
                        {typeSortie === 'requisition' ? 'Réquisition' :
                         typeSortie === 'remboursement' ? 'Remboursement' :
                         typeSortie === 'versement_banque' ? 'Versement' : 'Sortie directe'}
                      </span>
                    </td>
                    <td>
                      {typeSortie === 'requisition' ? (
                        <strong>{sortie.requisition?.numero_requisition}</strong>
                      ) : (
                        <span style={{fontSize: '13px'}}>{sortieWithType.motif}</span>
                      )}
                    </td>
                    <td>
                      {typeSortie === 'requisition' ? (
                        sortie.requisition?.objet
                      ) : sortieWithType.beneficiaire ? (
                        <span style={{fontSize: '13px'}}>{sortieWithType.beneficiaire}</span>
                      ) : (
                        <span style={{fontSize: '13px', color: '#9ca3af'}}>-</span>
                      )}
                    </td>
                    <td><strong>{formatCurrency(Number(sortie.montant_paye))}</strong></td>
                    <td>
                      {sortie.mode_paiement === 'cash' ? 'Cash' :
                       sortie.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement'}
                    </td>
                    <td>{sortie.reference || '-'}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {showSuccessNotification && lastCreatedSortie && (
        <SortieFondsNotification
          requisition={lastCreatedSortie.requisition}
          sortie={lastCreatedSortie.sortie}
          userName={`${user?.prenom} ${user?.nom}`}
          onClose={() => setShowSuccessNotification(false)}
        />
      )}
    </div>
  )
}
