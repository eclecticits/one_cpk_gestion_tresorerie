import { useState, useEffect } from 'react'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { Requisition } from '../types'
import { format } from 'date-fns'
import { generateRemboursementTransportPDF } from '../utils/pdfGeneratorRemboursement'
import styles from './RemboursementTransport.module.css'

interface RemboursementTransport {
  id: string
  numero_remboursement: string
  instance: string
  type_reunion: 'bureau' | 'commission' | 'conseil' | 'atelier'
  nature_reunion: string
  nature_travail: string[]
  lieu: string
  date_reunion: string
  heure_debut?: string
  heure_fin?: string
  montant_total: number
  requisition_id?: string
  requisition?: Requisition
  created_at: string
  created_by: string
}

interface Participant {
  id?: string
  nom: string
  titre_fonction: string
  montant: number
  type_participant: 'principal' | 'assistant'
  expert_comptable_id?: string
}

interface ExpertComptable {
  id: string
  numero_ordre: string
  nom_denomination: string
}

export default function RemboursementTransport() {
  const { user } = useAuth()
  const [remboursements, setRemboursements] = useState<RemboursementTransport[]>([])
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])
  const [selectedRemboursementUsers, setSelectedRemboursementUsers] = useState<{
    demandeur?: { prenom: string; nom: string }
    validateur?: { prenom: string; nom: string }
    approbateur?: { prenom: string; nom: string }
  }>({})

  const [formData, setFormData] = useState({
    instance: 'Conseil Provincial' as 'Conseil Provincial' | 'Conseil National',
    type_reunion: 'bureau' as 'bureau' | 'commission' | 'conseil' | 'atelier',
    nature_reunion: '',
    nature_travail: [''],
    lieu: '',
    date_reunion: format(new Date(), 'yyyy-MM-dd'),
    heure_debut: '',
    heure_fin: ''
  })

  const [participants, setParticipants] = useState<Participant[]>([
    { nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }
  ])

  const [assistants, setAssistants] = useState<Participant[]>([])
  const [showAssistants, setShowAssistants] = useState(false)
  const [showExpertSearch, setShowExpertSearch] = useState<number | null>(null)
  const [showAssistantExpertSearch, setShowAssistantExpertSearch] = useState<number | null>(null)

  const [notification, setNotification] = useState<{
    show: boolean
    type: 'success' | 'error'
    message: string
  }>({ show: false, type: 'success', message: '' })

  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [remboursementsRes, expertsRes] = await Promise.all([
        apiRequest('GET', '/remboursements-transport', { params: { include: 'requisition', limit: 200, offset: 0 } }),
        apiRequest('GET', '/experts-comptables', { params: { active: true, limit: 200, offset: 0 } }),
      ])

      const remb = Array.isArray(remboursementsRes) ? remboursementsRes : (remboursementsRes as any)?.items ?? (remboursementsRes as any)?.data ?? []
      const exp = Array.isArray(expertsRes) ? expertsRes : (expertsRes as any)?.items ?? (expertsRes as any)?.data ?? []

      setRemboursements(remb as any)
      setExperts(exp as any)
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)

    try {
      const objetRequisition = `Remboursement transport - ${formData.nature_reunion} - ${formData.lieu} - ${format(new Date(formData.date_reunion), 'dd/MM/yyyy')}`

      const numeroData: any = await apiRequest('POST', '/requisitions/generate-numero')

      const requisitionData: any = await apiRequest('POST', '/requisitions', {
        numero_requisition: numeroData,
        objet: objetRequisition,
        type_requisition: 'remboursement_transport',
        mode_paiement: 'cash',
        montant_total: calculateTotal(),
        created_by: user?.id,
        statut: 'brouillon',
      })

      const remboursementInsert: any = {
        instance: formData.instance,
        type_reunion: formData.type_reunion,
        nature_reunion: formData.nature_reunion,
        nature_travail: formData.nature_travail.filter(n => n.trim() !== ''),
        lieu: formData.lieu,
        date_reunion: formData.date_reunion,
        heure_debut: formData.heure_debut || null,
        heure_fin: formData.heure_fin || null,
        montant_total: calculateTotal(),
        requisition_id: requisitionData.id,
        created_by: user?.id
      }

      const remboursementData: any = await apiRequest('POST', '/remboursements-transport', remboursementInsert)

      const allParticipants = [
        ...participants.filter(p => p.nom.trim() !== ''),
        ...assistants.filter(p => p.nom.trim() !== '')
      ]

      if (allParticipants.length > 0) {
        await apiRequest('POST', '/participants-transport', allParticipants.map(p => ({
          remboursement_id: remboursementData.id,
          nom: p.nom,
          titre_fonction: p.titre_fonction,
          montant: p.montant,
          type_participant: p.type_participant,
          expert_comptable_id: p.expert_comptable_id || null
        })))
      }

      setNotification({
        show: true,
        type: 'success',
        message: `Remboursement ${remboursementData.numero_remboursement} créé avec succès ! Une réquisition ${numeroData} a été créée et est en attente de validation.`
      })
      setShowForm(false)
      resetForm()
      loadData()
    } catch (error: any) {
      console.error('Error creating remboursement:', error)
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Erreur lors de la création du remboursement'
      })
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
    setFormData({
      instance: 'Conseil Provincial',
      type_reunion: 'bureau',
      nature_reunion: '',
      nature_travail: [''],
      lieu: '',
      date_reunion: format(new Date(), 'yyyy-MM-dd'),
      heure_debut: '',
      heure_fin: ''
    })
    setParticipants([{ nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }])
    setAssistants([])
    setShowAssistants(false)
  }

  const addNatureTravail = () => {
    setFormData({ ...formData, nature_travail: [...formData.nature_travail, ''] })
  }

  const removeNatureTravail = (index: number) => {
    const newNature = formData.nature_travail.filter((_, i) => i !== index)
    setFormData({ ...formData, nature_travail: newNature })
  }

  const updateNatureTravail = (index: number, value: string) => {
    const newNature = [...formData.nature_travail]
    newNature[index] = value
    setFormData({ ...formData, nature_travail: newNature })
  }

  const addParticipant = () => {
    setParticipants([...participants, { nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }])
  }

  const removeParticipant = (index: number) => {
    setParticipants(participants.filter((_, i) => i !== index))
  }

  const updateParticipant = (index: number, field: keyof Participant, value: any) => {
    const newParticipants = [...participants]
    newParticipants[index] = { ...newParticipants[index], [field]: value }
    setParticipants(newParticipants)
  }

  const addAssistant = () => {
    setAssistants([...assistants, { nom: '', titre_fonction: '', montant: 0, type_participant: 'assistant' }])
  }

  const removeAssistant = (index: number) => {
    setAssistants(assistants.filter((_, i) => i !== index))
  }

  const updateAssistant = (index: number, field: keyof Participant, value: any) => {
    const newAssistants = [...assistants]
    newAssistants[index] = { ...newAssistants[index], [field]: value }
    setAssistants(newAssistants)
  }

  const selectExpert = (participantIndex: number, expert: ExpertComptable) => {
    const newParticipants = [...participants]
    newParticipants[participantIndex] = {
      ...newParticipants[participantIndex],
      nom: expert.nom_denomination,
      expert_comptable_id: expert.id
    }
    setParticipants(newParticipants)
    setShowExpertSearch(null)
  }

  const selectAssistantExpert = (assistantIndex: number, expert: ExpertComptable) => {
    const newAssistants = [...assistants]
    newAssistants[assistantIndex] = {
      ...newAssistants[assistantIndex],
      nom: expert.nom_denomination,
      expert_comptable_id: expert.id
    }
    setAssistants(newAssistants)
    setShowAssistantExpertSearch(null)
  }

  const getFilteredExperts = (searchTerm: string) => {
    if (!searchTerm.trim()) return experts
    return experts.filter(e =>
      e.nom_denomination.toLowerCase().includes(searchTerm.toLowerCase()) ||
      e.numero_ordre.toLowerCase().includes(searchTerm.toLowerCase())
    )
  }

  const calculateTotal = () => {
    const participantsTotal = participants.reduce((sum, p) => sum + (Number(p.montant) || 0), 0)
    const assistantsTotal = assistants.reduce((sum, p) => sum + (Number(p.montant) || 0), 0)
    return participantsTotal + assistantsTotal
  }

  const printRemboursement = async (remboursement: RemboursementTransport) => {
    try {
      const participantsRes: any = await apiRequest('GET', '/participants-transport', { params: { remboursement_id: remboursement.id, limit: 500 } })
      const participantsData = Array.isArray(participantsRes) ? participantsRes : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []

      await generateRemboursementTransportPDF(
        remboursement,
        participantsData || [],
        'print',
        `${user?.prenom} ${user?.nom}`
      )
    } catch (error) {
      console.error('Error printing PDF:', error)
      setNotification({
        show: true,
        type: 'error',
        message: 'Erreur lors de l\'impression du PDF'
      })
    }
  }

  const viewDetails = async (remboursement: RemboursementTransport) => {
    setSelectedRemboursementDetails(remboursement)
    try {
      const participantsRes: any = await apiRequest('GET', '/participants-transport', { params: { remboursement_id: remboursement.id, limit: 500 } })
      const participantsData = Array.isArray(participantsRes) ? participantsRes : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []
      setSelectedParticipants(participantsData || [])

      const users: any = {}
      if ((remboursement as any).requisition?.demandeur) users.demandeur = (remboursement as any).requisition.demandeur
      if ((remboursement as any).requisition?.validateur) users.validateur = (remboursement as any).requisition.validateur
      if ((remboursement as any).requisition?.approbateur) users.approbateur = (remboursement as any).requisition.approbateur

      setSelectedRemboursementUsers(users)
      setShowDetailModal(true)
    } catch (error: any) {
      console.error('Error loading remboursement details:', error)
      setNotification({
        show: true,
        type: 'error',
        message: 'Erreur lors du chargement des détails. Veuillez réessayer.'
      })
    }
  }

  const remboursementsList = Array.isArray(remboursements) ? remboursements : []
  const filteredRemboursements = remboursementsList.filter(r => {
    const matchSearch = r.numero_remboursement.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        r.nature_reunion.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        r.lieu.toLowerCase().includes(searchQuery.toLowerCase())

    const requisitionStatut = (r as any).requisition?.statut
    const matchStatut = !filterStatut || requisitionStatut === filterStatut

    const matchDateDebut = !dateDebut || r.date_reunion >= dateDebut
    const matchDateFin = !dateFin || r.date_reunion <= dateFin

    return matchSearch && matchStatut && matchDateDebut && matchDateFin
  })

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getStatutBadge = (statut: string) => {
    const badges: any = {
      brouillon: { text: 'En attente', color: '#9ca3af' },
      validee_tresorerie: { text: 'Validée trésorerie', color: '#2563eb' },
      approuvee: { text: 'Approuvée', color: '#16a34a' },
      payee: { text: 'Payée', color: '#0d9488' },
      rejetee: { text: 'Rejetée', color: '#dc2626' }
    }
    const badge = badges[statut] || badges.brouillon
    return (
      <span style={{
        padding: '4px 12px',
        borderRadius: '12px',
        background: badge.color + '20',
        color: badge.color,
        fontSize: '12px',
        fontWeight: 600
      }}>
        {badge.text}
      </span>
    )
  }

  const canCreate = user?.role === 'secretariat' || user?.role === 'admin'

  if (loading) {
    return <div className={styles.loading}>Chargement...</div>
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>Remboursement frais de transport</h1>
          <p>Gestion des remboursements pour réunions et commissions</p>
        </div>
        {canCreate && (
          <button onClick={() => setShowForm(true)} className={styles.primaryBtn}>
            + Nouveau remboursement
          </button>
        )}
      </div>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent} style={{maxWidth: '1100px'}}>
            <div className={styles.modalHeader}>
              <h2>Nouveau remboursement frais de transport</h2>
              <button onClick={() => { setShowForm(false); resetForm(); }} className={styles.closeBtn}>×</button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className={styles.formSection}>
                <h3>Informations générales</h3>
                <div className={styles.formGrid}>
                  <div className={styles.formGroup}>
                    <label>Instance *</label>
                    <select
                      value={formData.instance}
                      onChange={(e) => setFormData({ ...formData, instance: e.target.value as any })}
                      required
                    >
                      <option value="Conseil Provincial">Conseil Provincial</option>
                      <option value="Conseil National">Conseil National</option>
                    </select>
                  </div>

                  <div className={styles.formGroup}>
                    <label>Type de réunion *</label>
                    <select
                      value={formData.type_reunion}
                      onChange={(e) => setFormData({ ...formData, type_reunion: e.target.value as any })}
                      required
                    >
                      <option value="bureau">Réunion du Bureau</option>
                      <option value="commission">Réunion de Commission</option>
                      <option value="conseil">Réunion du Conseil</option>
                      <option value="atelier">Atelier / Séminaire / Formation</option>
                    </select>
                  </div>

                  <div className={styles.formGroup}>
                    <label>Nature de la réunion *</label>
                    <input
                      type="text"
                      value={formData.nature_reunion}
                      onChange={(e) => setFormData({ ...formData, nature_reunion: e.target.value })}
                      placeholder="Ex: Réunion du Bureau du 10 Octobre 2025"
                      required
                    />
                  </div>

                  <div className={styles.formGroup}>
                    <label>Lieu *</label>
                    <input
                      type="text"
                      value={formData.lieu}
                      onChange={(e) => setFormData({ ...formData, lieu: e.target.value })}
                      placeholder="Ex: Siège ONEC Kinshasa"
                      required
                    />
                  </div>

                  <div className={styles.formGroup}>
                    <label>Date de la réunion *</label>
                    <input
                      type="date"
                      value={formData.date_reunion}
                      onChange={(e) => setFormData({ ...formData, date_reunion: e.target.value })}
                      required
                    />
                  </div>

                  <div className={styles.formGroup}>
                    <label>Heure début</label>
                    <input
                      type="time"
                      value={formData.heure_debut}
                      onChange={(e) => setFormData({ ...formData, heure_debut: e.target.value })}
                    />
                  </div>

                  <div className={styles.formGroup}>
                    <label>Heure fin</label>
                    <input
                      type="time"
                      value={formData.heure_fin}
                      onChange={(e) => setFormData({ ...formData, heure_fin: e.target.value })}
                    />
                  </div>
                </div>

                <div className={styles.formGroup} style={{marginTop: '16px'}}>
                  <label>Nature du travail</label>
                  {formData.nature_travail.map((nature, index) => (
                    <div key={index} style={{display: 'flex', gap: '8px', marginBottom: '8px'}}>
                      <input
                        type="text"
                        value={nature}
                        onChange={(e) => updateNatureTravail(index, e.target.value)}
                        placeholder={`Ligne ${index + 1}`}
                        style={{flex: 1}}
                      />
                      {formData.nature_travail.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removeNatureTravail(index)}
                          className={styles.removeBtn}
                        >
                          ×
                        </button>
                      )}
                    </div>
                  ))}
                  <button type="button" onClick={addNatureTravail} className={styles.secondaryBtn}>
                    + Ajouter ligne
                  </button>
                </div>
              </div>

              <div className={styles.formSection}>
                <h3>Participants (Experts comptables ou membres)</h3>
                <div className={styles.tableContainer}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Nom du participant *</th>
                        <th>Qualité / Titre / Fonction *</th>
                        <th>Montant (USD) *</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {participants.map((p, index) => (
                        <tr key={index}>
                          <td style={{position: 'relative'}}>
                            <input
                              type="text"
                              value={p.nom}
                              onChange={(e) => {
                                updateParticipant(index, 'nom', e.target.value)
                                setShowExpertSearch(index)
                              }}
                              onFocus={() => setShowExpertSearch(index)}
                              placeholder="Rechercher: nom ou N° ordre (ex: EC/16)..."
                              required
                              autoComplete="off"
                            />
                            {showExpertSearch === index && (
                              <div style={{
                                position: 'absolute',
                                top: 'calc(100% + 2px)',
                                left: 0,
                                width: '400px',
                                maxWidth: '95vw',
                                background: 'white',
                                border: '2px solid #16a34a',
                                borderRadius: '8px',
                                maxHeight: '350px',
                                zIndex: 10000,
                                boxShadow: '0 10px 40px rgba(0,0,0,0.25)'
                              }}>
                                <div style={{
                                  padding: '12px 16px',
                                  background: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
                                  borderBottom: '2px solid #86efac',
                                  fontSize: '13px',
                                  color: '#15803d',
                                  fontWeight: 700,
                                  position: 'sticky',
                                  top: 0,
                                  zIndex: 1
                                }}>
                                  {getFilteredExperts(p.nom).length} expert(s) disponible(s)
                                </div>
                                <div style={{
                                  maxHeight: '300px',
                                  overflowY: 'auto',
                                  overflowX: 'hidden'
                                }}>
                                  {getFilteredExperts(p.nom).slice(0, 25).map(expert => (
                                    <div
                                      key={expert.id}
                                      onMouseDown={(e) => {
                                        e.preventDefault()
                                        selectExpert(index, expert)
                                      }}
                                      style={{
                                        padding: '14px 16px',
                                        cursor: 'pointer',
                                        borderBottom: '1px solid #f3f4f6',
                                        transition: 'all 0.2s',
                                        borderLeft: '3px solid transparent'
                                      }}
                                      onMouseEnter={(e) => {
                                        e.currentTarget.style.background = '#f0fdf4'
                                        e.currentTarget.style.borderLeftColor = '#16a34a'
                                      }}
                                      onMouseLeave={(e) => {
                                        e.currentTarget.style.background = 'white'
                                        e.currentTarget.style.borderLeftColor = 'transparent'
                                      }}
                                    >
                                      <div style={{
                                        fontWeight: 700,
                                        color: '#16a34a',
                                        fontSize: '14px',
                                        marginBottom: '6px',
                                        fontFamily: 'Courier New, monospace',
                                        letterSpacing: '0.5px'
                                      }}>
                                        {expert.numero_ordre}
                                      </div>
                                      <div style={{
                                        fontSize: '13px',
                                        color: '#1f2937',
                                        fontWeight: 500,
                                        lineHeight: '1.4'
                                      }}>
                                        {expert.nom_denomination}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                                {getFilteredExperts(p.nom).length === 0 && (
                                  <div style={{
                                    padding: '32px 24px',
                                    textAlign: 'center',
                                    color: '#6b7280'
                                  }}>
                                    {p.nom.trim() ? (
                                      <div>
                                        <div style={{fontSize: '32px', marginBottom: '12px'}}>🔍</div>
                                        <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '6px'}}>
                                          Aucun expert trouvé
                                        </div>
                                        <div style={{fontSize: '12px'}}>
                                          pour "{p.nom}"
                                        </div>
                                      </div>
                                    ) : (
                                      <div>
                                        <div style={{fontSize: '32px', marginBottom: '12px'}}>👨‍💼</div>
                                        <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '6px'}}>
                                          {experts.length} experts disponibles
                                        </div>
                                        <div style={{fontSize: '12px'}}>
                                          Tapez pour rechercher
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}
                                {getFilteredExperts(p.nom).length > 25 && (
                                  <div style={{
                                    padding: '12px 16px',
                                    textAlign: 'center',
                                    fontSize: '12px',
                                    color: '#6b7280',
                                    background: '#fafafa',
                                    borderTop: '1px solid #e5e7eb',
                                    fontWeight: 600
                                  }}>
                                    +{getFilteredExperts(p.nom).length - 25} autres résultats
                                    <div style={{fontSize: '11px', marginTop: '4px', fontWeight: 400}}>
                                      Affinez votre recherche pour voir plus
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </td>
                          <td>
                            <input
                              type="text"
                              value={p.titre_fonction}
                              onChange={(e) => updateParticipant(index, 'titre_fonction', e.target.value)}
                              placeholder="Ex: Président, Vice-président, Rapporteur..."
                              required
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              value={p.montant}
                              onChange={(e) => updateParticipant(index, 'montant', parseFloat(e.target.value) || 0)}
                              required
                              min="0"
                              step="0.01"
                            />
                          </td>
                          <td>
                            {participants.length > 1 && (
                              <button
                                type="button"
                                onClick={() => removeParticipant(index)}
                                className={styles.removeBtn}
                              >
                                ×
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button type="button" onClick={addParticipant} className={styles.secondaryBtn}>
                  + Ajouter participant
                </button>
              </div>

              <div className={styles.formSection}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <h3>Assistants administratifs (optionnel)</h3>
                  <button
                    type="button"
                    onClick={() => setShowAssistants(!showAssistants)}
                    className={styles.secondaryBtn}
                  >
                    {showAssistants ? 'Masquer' : 'Afficher'}
                  </button>
                </div>

                {showAssistants && (
                  <>
                    <div className={styles.tableContainer}>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th>Nom</th>
                            <th>Fonction</th>
                            <th>Montant (USD)</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {assistants.length === 0 ? (
                            <tr>
                              <td colSpan={4} style={{textAlign: 'center', color: '#9ca3af'}}>
                                Aucun assistant administratif
                              </td>
                            </tr>
                          ) : (
                            assistants.map((a, index) => (
                              <tr key={index}>
                                <td style={{position: 'relative'}}>
                                  <input
                                    type="text"
                                    value={a.nom}
                                    onChange={(e) => {
                                      updateAssistant(index, 'nom', e.target.value)
                                      setShowAssistantExpertSearch(index)
                                    }}
                                    onFocus={() => setShowAssistantExpertSearch(index)}
                                    placeholder="Rechercher: nom ou N° ordre (ex: EC/16)..."
                                    autoComplete="off"
                                  />
                                  {showAssistantExpertSearch === index && (
                                    <div style={{
                                      position: 'absolute',
                                      top: 'calc(100% + 2px)',
                                      left: 0,
                                      width: '400px',
                                      maxWidth: '95vw',
                                      background: 'white',
                                      border: '2px solid #16a34a',
                                      borderRadius: '8px',
                                      maxHeight: '350px',
                                      zIndex: 10000,
                                      boxShadow: '0 10px 40px rgba(0,0,0,0.25)'
                                    }}>
                                      <div style={{
                                        padding: '12px 16px',
                                        background: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
                                        borderBottom: '2px solid #86efac',
                                        fontSize: '13px',
                                        color: '#15803d',
                                        fontWeight: 700,
                                        position: 'sticky',
                                        top: 0,
                                        zIndex: 1
                                      }}>
                                        {getFilteredExperts(a.nom).length} expert(s) disponible(s)
                                      </div>
                                      <div style={{
                                        maxHeight: '300px',
                                        overflowY: 'auto',
                                        overflowX: 'hidden'
                                      }}>
                                        {getFilteredExperts(a.nom).slice(0, 25).map(expert => (
                                          <div
                                            key={expert.id}
                                            onMouseDown={(e) => {
                                              e.preventDefault()
                                              selectAssistantExpert(index, expert)
                                            }}
                                            style={{
                                              padding: '14px 16px',
                                              cursor: 'pointer',
                                              borderBottom: '1px solid #f3f4f6',
                                              transition: 'all 0.2s',
                                              borderLeft: '3px solid transparent'
                                            }}
                                            onMouseEnter={(e) => {
                                              e.currentTarget.style.background = '#f0fdf4'
                                              e.currentTarget.style.borderLeftColor = '#16a34a'
                                            }}
                                            onMouseLeave={(e) => {
                                              e.currentTarget.style.background = 'white'
                                              e.currentTarget.style.borderLeftColor = 'transparent'
                                            }}
                                          >
                                            <div style={{
                                              fontWeight: 700,
                                              color: '#16a34a',
                                              fontSize: '14px',
                                              marginBottom: '6px',
                                              fontFamily: 'Courier New, monospace',
                                              letterSpacing: '0.5px'
                                            }}>
                                              {expert.numero_ordre}
                                            </div>
                                            <div style={{
                                              fontSize: '13px',
                                              color: '#1f2937',
                                              fontWeight: 500,
                                              lineHeight: '1.4'
                                            }}>
                                              {expert.nom_denomination}
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                      {getFilteredExperts(a.nom).length === 0 && (
                                        <div style={{
                                          padding: '32px 24px',
                                          textAlign: 'center',
                                          color: '#6b7280'
                                        }}>
                                          {a.nom.trim() ? (
                                            <div>
                                              <div style={{fontSize: '32px', marginBottom: '12px'}}>🔍</div>
                                              <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '6px'}}>
                                                Aucun expert trouvé
                                              </div>
                                              <div style={{fontSize: '12px'}}>
                                                pour "{a.nom}"
                                              </div>
                                            </div>
                                          ) : (
                                            <div>
                                              <div style={{fontSize: '32px', marginBottom: '12px'}}>👨‍💼</div>
                                              <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '6px'}}>
                                                {experts.length} experts disponibles
                                              </div>
                                              <div style={{fontSize: '12px'}}>
                                                Tapez pour rechercher
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                      {getFilteredExperts(a.nom).length > 25 && (
                                        <div style={{
                                          padding: '12px 16px',
                                          textAlign: 'center',
                                          fontSize: '12px',
                                          color: '#6b7280',
                                          background: '#fafafa',
                                          borderTop: '1px solid #e5e7eb',
                                          fontWeight: 600
                                        }}>
                                          +{getFilteredExperts(a.nom).length - 25} autres résultats
                                          <div style={{fontSize: '11px', marginTop: '4px', fontWeight: 400}}>
                                            Affinez votre recherche pour voir plus
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    value={a.titre_fonction}
                                    onChange={(e) => updateAssistant(index, 'titre_fonction', e.target.value)}
                                    placeholder="Ex: Secrétaire administratif, Assistant à la commission"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    value={a.montant}
                                    onChange={(e) => updateAssistant(index, 'montant', parseFloat(e.target.value) || 0)}
                                    min="0"
                                    step="0.01"
                                  />
                                </td>
                                <td>
                                  <button
                                    type="button"
                                    onClick={() => removeAssistant(index)}
                                    className={styles.removeBtn}
                                  >
                                    ×
                                  </button>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    <button type="button" onClick={addAssistant} className={styles.secondaryBtn}>
                      + Ajouter assistant
                    </button>
                  </>
                )}
              </div>

              <div className={styles.total}>
                <strong>Total général:</strong>
                <strong style={{fontSize: '20px', color: '#0d9488'}}>{formatCurrency(calculateTotal())}</strong>
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => { setShowForm(false); resetForm(); }} className={styles.secondaryBtn} disabled={submitting}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                  {submitting ? 'Création en cours...' : 'Créer le remboursement'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className={styles.filtersSection}>
        <div className={styles.searchBar}>
          <input
            type="text"
            placeholder="Rechercher par numéro, nature ou lieu..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <label>Statut</label>
            <select value={filterStatut} onChange={(e) => setFilterStatut(e.target.value)}>
              <option value="">Tous les statuts</option>
              <option value="brouillon">En attente</option>
              <option value="validee_tresorerie">Validée trésorerie</option>
              <option value="approuvee">Approuvée</option>
              <option value="payee">Payée</option>
              <option value="rejetee">Rejetée</option>
            </select>
          </div>
        </div>

        <div style={{marginTop: '16px', display: 'flex', gap: '16px', alignItems: 'flex-end', flexWrap: 'wrap'}}>
          <div style={{flex: '1', minWidth: '200px'}}>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500}}>Date début</label>
            <input
              type="date"
              value={dateDebut}
              onChange={(e) => setDateDebut(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px'}}
            />
          </div>
          <div style={{flex: '1', minWidth: '200px'}}>
            <label style={{display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: 500}}>Date fin</label>
            <input
              type="date"
              value={dateFin}
              onChange={(e) => setDateFin(e.target.value)}
              style={{width: '100%', padding: '10px', border: '1px solid #d1d5db', borderRadius: '6px'}}
            />
          </div>
          {(searchQuery || filterStatut || dateDebut || dateFin) && (
            <button
              onClick={() => { setSearchQuery(''); setFilterStatut(''); setDateDebut(''); setDateFin(''); }}
              style={{padding: '10px 20px', background: '#f3f4f6', color: '#374151', border: 'none', borderRadius: '6px', cursor: 'pointer'}}
            >
              Réinitialiser
            </button>
          )}
        </div>
      </div>

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>N° Remboursement</th>
              <th>Date réunion</th>
              <th>Nature</th>
              <th>Lieu</th>
              <th>Montant total</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredRemboursements.length === 0 ? (
              <tr>
                <td colSpan={7} className={styles.empty}>
                  Aucun remboursement trouvé
                </td>
              </tr>
            ) : (
              filteredRemboursements.map((r) => {
                const requisition = (r as any).requisition
                return (
                  <tr key={r.id}>
                    <td>
                      <div>
                        <strong>{r.numero_remboursement}</strong>
                        {requisition && (
                          <div style={{fontSize: '11px', color: '#6b7280', marginTop: '2px'}}>
                            Rq: {requisition.numero_requisition}
                          </div>
                        )}
                      </div>
                    </td>
                    <td>{format(new Date(r.date_reunion), 'dd/MM/yyyy')}</td>
                    <td>{r.nature_reunion}</td>
                    <td>{r.lieu}</td>
                    <td><strong>{formatCurrency(Number(r.montant_total))}</strong></td>
                    <td>{requisition ? getStatutBadge(requisition.statut) : getStatutBadge('brouillon')}</td>
                    <td>
                      <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
                        <button
                          onClick={() => viewDetails(r)}
                          className={styles.actionBtn}
                          style={{background: '#0d9488', color: 'white'}}
                          title="Voir les détails du remboursement"
                        >
                          Voir détails
                        </button>
                        <button
                          onClick={() => printRemboursement(r)}
                          className={styles.actionBtn}
                          style={{background: '#2563eb', color: 'white'}}
                          title="Imprimer le remboursement"
                        >
                          Imprimer
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {notification.show && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          background: notification.type === 'success' ? '#dcfce7' : '#fee2e2',
          border: `2px solid ${notification.type === 'success' ? '#16a34a' : '#dc2626'}`,
          borderRadius: '8px',
          padding: '16px 24px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          zIndex: 9999,
          maxWidth: '400px'
        }}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <span style={{
              color: notification.type === 'success' ? '#16a34a' : '#dc2626',
              fontWeight: 600,
              fontSize: '15px'
            }}>
              {notification.message}
            </span>
            <button
              onClick={() => setNotification({ ...notification, show: false })}
              style={{
                background: 'none',
                border: 'none',
                fontSize: '20px',
                cursor: 'pointer',
                marginLeft: '16px',
                color: notification.type === 'success' ? '#16a34a' : '#dc2626'
              }}
            >
              ×
            </button>
          </div>
        </div>
      )}

      {showDetailModal && selectedRemboursementDetails && (
        <div className={styles.modal}>
          <div className={styles.modalContent} style={{maxWidth: '1000px'}}>
            <div className={styles.modalHeader}>
              <h2>Détails du remboursement {selectedRemboursementDetails.numero_remboursement}</h2>
              <button onClick={() => setShowDetailModal(false)} className={styles.closeBtn}>×</button>
            </div>

            <div className={styles.detailContent}>
              <div className={styles.detailSection} style={{background: '#f0fdf4', borderLeft: '4px solid #16a34a'}}>
                <h3 style={{color: '#16a34a', marginBottom: '16px'}}>Traçabilité et Responsabilité</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Demandeur</label>
                    <p><strong>{selectedRemboursementUsers.demandeur ? `${selectedRemboursementUsers.demandeur.prenom} ${selectedRemboursementUsers.demandeur.nom}` : 'Non disponible'}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Date de la demande</label>
                    <p>{format(new Date((selectedRemboursementDetails as any).requisition?.created_at ?? selectedRemboursementDetails.created_at), 'dd/MM/yyyy à HH:mm')}</p>
                  </div>
                  {((selectedRemboursementDetails as any).requisition?.validee_par || (selectedRemboursementDetails as any).requisition?.approuvee_par) && (
                    <>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Validateur / Rejeteur</label>
                        <p><strong>
                          {selectedRemboursementUsers.approbateur
                            ? `${selectedRemboursementUsers.approbateur.prenom} ${selectedRemboursementUsers.approbateur.nom}`
                            : selectedRemboursementUsers.validateur
                            ? `${selectedRemboursementUsers.validateur.prenom} ${selectedRemboursementUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Date de validation / rejet</label>
                        <p>
                          {(selectedRemboursementDetails as any).requisition?.approuvee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : (selectedRemboursementDetails as any).requisition?.validee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Statut actuel</label>
                    <p>{(selectedRemboursementDetails as any).requisition ? getStatutBadge((selectedRemboursementDetails as any).requisition.statut) : getStatutBadge('brouillon')}</p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Informations générales</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Numéro</label>
                    <p><strong>{selectedRemboursementDetails.numero_remboursement}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Date de réunion</label>
                    <p>{format(new Date(selectedRemboursementDetails.date_reunion), 'dd/MM/yyyy')}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Nature de réunion</label>
                    <p>{selectedRemboursementDetails.nature_reunion}</p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Lieu</label>
                    <p>{selectedRemboursementDetails.lieu}</p>
                  </div>
                  {selectedRemboursementDetails.heure_debut && (
                    <div className={styles.detailItem}>
                      <label>Heure de début</label>
                      <p>{selectedRemboursementDetails.heure_debut}</p>
                    </div>
                  )}
                  {selectedRemboursementDetails.heure_fin && (
                    <div className={styles.detailItem}>
                      <label>Heure de fin</label>
                      <p>{selectedRemboursementDetails.heure_fin}</p>
                    </div>
                  )}
                  <div className={styles.detailItem}>
                    <label>Montant total</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{formatCurrency(Number(selectedRemboursementDetails.montant_total))}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Participants</h3>
                <table className={styles.detailTable}>
                  <thead>
                    <tr>
                      <th>Nom</th>
                      <th>Titre/Fonction</th>
                      <th>Type</th>
                      <th>Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedParticipants.map((participant) => (
                      <tr key={participant.id}>
                        <td>{participant.nom}</td>
                        <td>{participant.titre_fonction}</td>
                        <td>
                          <span style={{
                            padding: '4px 8px',
                            borderRadius: '6px',
                            background: participant.type_participant === 'principal' ? '#dbeafe' : '#fef3c7',
                            color: participant.type_participant === 'principal' ? '#1e40af' : '#92400e',
                            fontSize: '11px',
                            fontWeight: 600
                          }}>
                            {participant.type_participant === 'principal' ? 'Principal' : 'Assistant'}
                          </span>
                        </td>
                        <td><strong>{formatCurrency(Number(participant.montant))}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={3} style={{textAlign: 'right', fontWeight: 600}}>Total général:</td>
                      <td><strong style={{fontSize: '16px', color: '#0d9488'}}>{formatCurrency(Number(selectedRemboursementDetails.montant_total))}</strong></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
