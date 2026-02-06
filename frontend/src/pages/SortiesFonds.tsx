import { useMemo, useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { getBudgetLines } from '../api/budget'
import { useAuth } from '../contexts/AuthContext'
import { toNumber } from '../utils/amount'
import { SortieFonds, ModePatement, TypeSortieFonds } from '../types'
import { format } from 'date-fns'
import { downloadExcel } from '../utils/download'
import styles from './SortiesFonds.module.css'
import SortieFondsNotification from '../components/SortieFondsNotification'
import { CATEGORIES_SORTIE, getTypeSortieLabel, getBeneficiairePlaceholder, getMotifPlaceholder } from '../utils/sortieFondsHelpers'
import { useToast } from '../hooks/useToast'

export default function SortiesFonds() {
  const { user } = useAuth()
  const { notifyError, notifySuccess, notifyWarning } = useToast()
  const [showForm, setShowForm] = useState(false)
  const [sorties, setSorties] = useState<SortieFonds[]>([])
  const [requisitionsApprouvees, setRequisitionsApprouvees] = useState<any[]>([])
  const [budgetLines, setBudgetLines] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [showSuccessNotification, setShowSuccessNotification] = useState(false)
  const [lastCreatedSortie, setLastCreatedSortie] = useState<any>(null)
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [totalMontantSorties, setTotalMontantSorties] = useState(0)
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
    budget_ligne_id: '',
    beneficiaire: '',
    piece_justificative: ''
  })

  const loadData = async () => {
    try {
      setLoading(true)
      const [sortiesRes, reqRes, budgetRes] = await Promise.all([
        apiRequest<any>('GET', '/sorties-fonds', {
          params: {
            include: 'requisition',
            date_debut: dateDebut,
            date_fin: dateFin,
            type_sortie: filterType,
            mode_paiement: filterModePaiement,
            requisition_numero: filterNumeroRequisition,
            order: 'date_paiement.desc',
            limit: pageSize,
            offset: (page - 1) * pageSize,
            include_summary: true,
          }
        }),
        apiRequest('GET', '/requisitions', { params: { status_in: 'EN_ATTENTE,A_VALIDER,VALIDEE', include: 'created_by_user,approved_by_user', limit: 200 } }),
        getBudgetLines({ type: 'DEPENSE', active: true }),
      ])

      const sortiesItems = Array.isArray(sortiesRes) ? sortiesRes : (sortiesRes?.items ?? [])
      setSorties(sortiesItems as any)
      setTotalCount(typeof sortiesRes?.total === 'number' ? sortiesRes.total : sortiesItems.length)
      if (sortiesRes?.total_montant_paye !== undefined) {
        setTotalMontantSorties(toNumber(sortiesRes.total_montant_paye ?? 0))
      } else {
        const fallbackTotal = (sortiesItems as SortieFonds[]).reduce(
          (sum, s) => sum + toNumber(s.montant_paye || 0),
          0
        )
        setTotalMontantSorties(fallbackTotal)
      }
      const items = Array.isArray(reqRes) ? reqRes : (reqRes as any)?.items ?? []
      const allowedStatuses = new Set(['EN_ATTENTE', 'A_VALIDER', 'VALIDEE'])
      const filteredReqs = (items as any[]).filter((r) => {
        const statusValue = (r as any).status ?? (r as any).statut
        return statusValue ? allowedStatuses.has(String(statusValue)) : false
      })
      setRequisitionsApprouvees(filteredReqs as any)
      setBudgetLines(budgetRes?.lignes ?? [])
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [dateDebut, dateFin, filterType, filterModePaiement, filterNumeroRequisition, pageSize, page])

  useEffect(() => {
    setPage(1)
  }, [dateDebut, dateFin, filterType, filterModePaiement, filterNumeroRequisition, pageSize])

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(page, totalPages)

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const sortiesList = Array.isArray(sorties) ? sorties : []
  const requisitionsApprouveesList = Array.isArray(requisitionsApprouvees) ? requisitionsApprouvees : []
  const budgetLinesList = Array.isArray(budgetLines) ? budgetLines : []

  const budgetLineMap = useMemo(() => {
    return new Map(budgetLinesList.map((line: any) => [String(line.id), line]))
  }, [budgetLinesList])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (submitting) return

    if (!formData.montant_paye) {
      notifyWarning('Montant requis', 'Veuillez saisir le montant.')
      return
    }

    if (formData.type_sortie === 'requisition' && !formData.requisition_id) {
      notifyWarning('Réquisition requise', 'Veuillez sélectionner une réquisition approuvée.')
      return
    }

    if (formData.type_sortie === 'sortie_directe' && parseFloat(formData.montant_paye) > 100) {
      notifyWarning(
        'Montant maximum dépassé',
        'Les sorties directes sont limitées à 100 $. Pour les montants supérieurs, créez une réquisition.'
      )
      return
    }

    if (!formData.motif.trim()) {
      notifyWarning('Motif requis', 'Le motif est obligatoire pour toutes les sorties.')
      return
    }

    if (!formData.beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Le bénéficiaire est obligatoire pour toutes les sorties.')
      return
    }

    if (!formData.budget_ligne_id) {
      notifyWarning('Rubrique requise', 'La rubrique budgétaire est obligatoire.')
      return
    }

    const selectedBudget = budgetLinesList.find((b: any) => String(b.id) === String(formData.budget_ligne_id))
    if (selectedBudget) {
      const plafond = toNumber(selectedBudget.montant_prevu)
      const dejaPaye = toNumber(selectedBudget.montant_paye)
      const reste = plafond - dejaPaye
      if (parseFloat(formData.montant_paye) > reste) {
        notifyWarning(
          'Dépassement budgétaire',
          `Disponible: ${formatCurrency(reste)} · Demandé: ${formatCurrency(formData.montant_paye)}`
        )
        return
      }
    }

    if ((formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && !formData.reference) {
      notifyWarning('Référence requise', 'La référence est obligatoire pour Mobile Money ou Virement.')
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

      sortieInsert.budget_ligne_id = Number(formData.budget_ligne_id)

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
        notifySuccess(
          'Sortie enregistrée',
          `${getTypeSortieLabel(formData.type_sortie)} · ${parseFloat(formData.montant_paye).toFixed(2)} $ · ${formData.beneficiaire}`
        )
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
        budget_ligne_id: '',
        beneficiaire: '',
        piece_justificative: ''
      })
      loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))
    } catch (error: any) {
      console.error('Error creating sortie:', error)
      const errorMessage = error?.message || 'Erreur inconnue'
      notifyError("Erreur d'enregistrement", errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  const formatCurrency = (amount: string | number | null | undefined) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const canCreate = user?.role === 'tresorerie' || user?.role === 'admin'

  const filteredSorties = sortiesList
  const totalSorties = totalMontantSorties

  const exportToExcel = async () => {
    const suffix = `${dateDebut || 'debut'}_${dateFin || 'fin'}`
    await downloadExcel('/exports/sorties-fonds', {
      date_debut: dateDebut,
      date_fin: dateFin,
      type_sortie: filterType,
      mode_paiement: filterModePaiement,
      requisition_numero: filterNumeroRequisition,
    }, `sorties_fonds_${suffix}.xlsx`)
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
          <div className={styles.pageSize}>
            <label>Affichage</label>
            <select value={String(pageSize)} onChange={(e) => setPageSize(Number(e.target.value))}>
              <option value="20">20 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          {(dateDebut || dateFin || filterType || filterModePaiement || filterNumeroRequisition) && (
            <button
              onClick={() => {
                setDateDebut('')
                setDateFin('')
                setFilterType('')
                setFilterModePaiement('')
                setFilterNumeroRequisition('')
                setPage(1)
              }}
              style={{padding: '10px 20px', background: '#f3f4f6', border: '1px solid #d1d5db', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: 500}}
            >
              Réinitialiser tous les filtres
            </button>
          )}
          {totalCount > 0 && (
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
              {totalCount} opération{totalCount > 1 ? 's' : ''}
            </div>
          </div>
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
                        {req.numero_requisition} - {req.objet} ({formatCurrency(req.montant_total)})
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

              <div className={styles.field}>
                <label>Rubrique budgétaire *</label>
                <select
                  value={formData.budget_ligne_id}
                  onChange={(e) => setFormData({ ...formData, budget_ligne_id: e.target.value })}
                  required
                >
                  <option value="">Sélectionner une rubrique...</option>
                  {budgetLinesList.map((line: any) => (
                    <option key={line.id} value={line.id}>{line.code} - {line.libelle}</option>
                  ))}
                </select>
                {formData.budget_ligne_id && (() => {
                  const selected = budgetLinesList.find((b: any) => String(b.id) === String(formData.budget_ligne_id))
                  if (!selected) return null
                  const plafond = toNumber(selected.montant_prevu)
                  const dejaPaye = toNumber(selected.montant_paye)
                  const reste = plafond - dejaPaye
                  return (
                    <small style={{ color: reste < 0 ? '#b91c1c' : '#6b7280', fontSize: '12px' }}>
                      Disponible: {formatCurrency(reste)} · Payé: {formatCurrency(dejaPaye)}
                    </small>
                  )
                })()}
              </div>

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
              <th>Rubrique budget</th>
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
                    <td>
                      {sortieWithType.budget_ligne_id
                        ? (() => {
                            const line = budgetLineMap.get(String(sortieWithType.budget_ligne_id))
                            return line ? `${line.code} - ${line.libelle}` : `#${sortieWithType.budget_ligne_id}`
                          })()
                        : '-'}
                    </td>
                    <td><strong>{formatCurrency(sortie.montant_paye)}</strong></td>
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
