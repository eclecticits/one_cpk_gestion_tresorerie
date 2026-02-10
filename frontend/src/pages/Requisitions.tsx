import { useState, useEffect, useMemo } from 'react'
import { apiRequest, API_BASE_URL } from '../lib/apiClient'
import { getBudgetLines } from '../api/budget'
import { getPrintSettings } from '../api/settings'
import { useAuth } from '../contexts/AuthContext'
import { toNumber } from '../utils/amount'
import type { Money } from '../types'
import { Requisition, LigneRequisition, StatutRequisition, ModePatement } from '../types'
import type { BudgetLineSummary } from '../types/budget'
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
  const [budgetLines, setBudgetLines] = useState<BudgetLineSummary[]>([])
  const [printSettings, setPrintSettings] = useState<any | null>(null)
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
  const [showValidationColumns, setShowValidationColumns] = useState(true)

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
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(1)

  const [formData, setFormData] = useState({
    objet: '',
    mode_paiement: 'cash' as ModePatement,
    type_requisition: 'classique' as 'classique' | 'mini' | 'remboursement_transport',
    a_valoir: false,
    instance_beneficiaire: '',
    notes_a_valoir: ''
  })
  const [annexeFile, setAnnexeFile] = useState<File | null>(null)
  const [annexeError, setAnnexeError] = useState('')

  const [lignes, setLignes] = useState<Array<Omit<LigneRequisition, 'id' | 'requisition_id'> & { devise?: 'USD' | 'CDF' }>>([
    { budget_ligne_id: null, rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0, devise: 'USD' }
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

  const loadBudgetLines = async () => {
    const resp = await getBudgetLines({ type: 'DEPENSE', active: true })
    const items = resp?.lignes ?? []
    setBudgetLines(items)
  }
  
  const loadSettings = async () => {
    try {
      const settings = await getPrintSettings()
      setPrintSettings(settings)
    } catch (error) {
      console.error('Error loading settings:', error)
      setPrintSettings(null)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      await Promise.all([
        loadRequisitions(),
        loadRubriques(),
        loadBudgetLines(),
        loadSettings(),
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
    setLignes([
      ...lignes,
      { budget_ligne_id: null, rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0, devise: 'USD' }
    ])
  }

  const removeLigne = (index: number) => {
    setLignes(lignes.filter((_, i) => i !== index))
  }

  const updateLigne = (index: number, field: string, value: any) => {
    const newLignes = [...lignes]
    newLignes[index] = { ...newLignes[index], [field]: value }

    if (field === 'budget_ligne_id') {
      const selected = budgetLinesById.get(Number(value))
      newLignes[index].rubrique = selected ? `${selected.code} - ${selected.libelle}` : ''
    }

    if (field === 'quantite' || field === 'montant_unitaire') {
      newLignes[index].montant_total = newLignes[index].quantite * newLignes[index].montant_unitaire
    }

    setLignes(newLignes)
  }

  const exchangeRate = printSettings?.exchange_rate ? Number(printSettings.exchange_rate) : 0
  const toUsd = (amount: number, devise: 'USD' | 'CDF') => {
    if (devise === 'USD') return amount
    if (!exchangeRate) return amount
    return amount / exchangeRate
  }

  const calculateTotalUsd = () => {
    return lignes.reduce((sum, ligne) => {
      const devise = (ligne as any).devise || 'USD'
      return sum + toUsd(ligne.montant_total, devise)
    }, 0)
  }

  const calculateTotal = () => {
    return lignes.reduce((sum, ligne) => sum + ligne.montant_total, 0)
  }

  const MAX_ANNEXE_SIZE = 3 * 1024 * 1024
  const ALLOWED_ANNEXE_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']

  const validateAnnexe = (file: File) => {
    if (!ALLOWED_ANNEXE_TYPES.includes(file.type)) {
      return 'Format non autorisé (PDF, JPG, PNG).'
    }
    if (file.size > MAX_ANNEXE_SIZE) {
      return 'Fichier trop volumineux (max 3 Mo).'
    }
    return ''
  }

  const setAnnexeSelection = (file: File | null) => {
    if (!file) {
      setAnnexeFile(null)
      setAnnexeError('')
      return
    }
    const error = validateAnnexe(file)
    setAnnexeError(error)
    if (!error) {
      setAnnexeFile(file)
    } else {
      setAnnexeFile(null)
    }
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

    const invalidLigne = lignes.find(l => !l.budget_ligne_id || !l.description || l.montant_unitaire <= 0)
    if (invalidLigne) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Lignes incomplètes',
        message: 'Toutes les lignes doivent avoir une ligne budgétaire, une description et un montant positif.'
      })
      return
    }

    const depassement = lignes.find(l => {
      const budgetLine = budgetLinesById.get(Number(l.budget_ligne_id))
      if (!budgetLine) return true
      const devise = (l as any).devise || 'USD'
      const totalUsd = toUsd(l.montant_total, devise)
      return totalUsd > toNumber(budgetLine.montant_disponible)
    })
    if (depassement && printSettings?.budget_block_overrun) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Dépassement budgétaire',
        message: 'Au moins une ligne dépasse le disponible budgétaire.'
      })
      return
    }

    if (annexeError) {
      setNotification({
        show: true,
        type: 'error',
        title: 'Annexe invalide',
        message: annexeError
      })
      return
    }

    setSubmitting(true)
    try {
      const reqRes: any = await apiRequest('POST', '/requisitions', {
        objet: formData.objet,
        mode_paiement: formData.mode_paiement,
        type_requisition: formData.type_requisition,
        montant_total: calculateTotalUsd(),
        status: 'EN_ATTENTE',
        created_by: user?.id,
        a_valoir: formData.a_valoir,
        instance_beneficiaire: formData.a_valoir ? formData.instance_beneficiaire : null,
        notes_a_valoir: formData.a_valoir ? formData.notes_a_valoir : null
      })

      const reqData = reqRes as any
      const numeroData = reqData.numero_requisition

      const lignesData = lignes.map(l => {
        const devise = (l as any).devise || 'USD'
        const montantUnitaireUsd = toUsd(l.montant_unitaire, devise)
        const montantTotalUsd = toUsd(l.montant_total, devise)
        return {
          requisition_id: reqData.id,
          ...l,
          montant_unitaire: montantUnitaireUsd,
          montant_total: montantTotalUsd,
        }
      })

      await apiRequest('POST', '/lignes-requisition', lignesData)

      try {
        const pdfBlob = await generateSingleRequisitionPDF(
          reqData,
          lignesData,
          'blob',
          `${user?.prenom} ${user?.nom}`
        )
        if (pdfBlob) {
          const pdfForm = new FormData()
          pdfForm.append(
            'file',
            pdfBlob,
            `requisition_${reqData.numero_requisition || reqData.id}.pdf`
          )
          await apiRequest('POST', `/requisitions/${reqData.id}/pdf`, pdfForm)
        }
      } catch (pdfError) {
        console.error('Error uploading requisition PDF:', pdfError)
      }

      if (annexeFile) {
        const form = new FormData()
        form.append('file', annexeFile)
        await apiRequest('POST', `/requisitions/${reqData.id}/annexe`, { params: { notify: true }, body: form })
      }

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
    setLignes([{ budget_ligne_id: null, rubrique: '', description: '', quantite: 1, montant_unitaire: 0, montant_total: 0, devise: 'USD' }])
    setAnnexeFile(null)
    setAnnexeError('')
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
  const budgetLinesById = useMemo(() => {
    return new Map(budgetLines.map(line => [line.id, line]))
  }, [budgetLines])
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
        aVal = toNumber(aVal)
        bVal = toNumber(bVal)
      }

      if (sortDirection === 'asc') {
        return aVal > bVal ? 1 : -1
      } else {
        return aVal < bVal ? 1 : -1
      }
    })

  const hasActiveFilters = searchQuery !== '' || filterStatut !== '' || filterModePaiement !== '' || filterObjet !== '' || filterRubrique !== ''

  useEffect(() => {
    setPage(1)
  }, [activeTab, searchQuery, filterStatut, filterModePaiement, filterObjet, filterRubrique, dateDebut, dateFin, sortField, sortDirection, pageSize])

  const totalPages = Math.max(1, Math.ceil(filteredRequisitions.length / pageSize))
  const safePage = Math.min(page, totalPages)

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const startIndex = filteredRequisitions.length === 0 ? 0 : (safePage - 1) * pageSize + 1
  const endIndex = Math.min(safePage * pageSize, filteredRequisitions.length)
  const paginatedRequisitions = filteredRequisitions.slice((safePage - 1) * pageSize, safePage * pageSize)

  const clearFilters = () => {
    setSearchQuery('')
    setFilterStatut('')
    setFilterModePaiement('')
    setFilterObjet('')
    setFilterRubrique('')
    setSortField('')
    setSortDirection('desc')
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const formatCdf = (amount: number) => {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(amount)
  }

  const getStatutBadge = (statut: StatutRequisition | string) => {
    const styles: any = {
      EN_ATTENTE: { bg: '#f3f4f6', color: '#374151' },
      VALIDEE: { bg: '#dbeafe', color: '#1e40af' },
      AUTORISEE: { bg: '#dbeafe', color: '#1e40af' },
      REJETEE: { bg: '#fee2e2', color: '#dc2626' },
      brouillon: { bg: '#f3f4f6', color: '#374151' },
      validee_tresorerie: { bg: '#dbeafe', color: '#1e40af' },
      approuvee: { bg: '#dcfce7', color: '#16a34a' },
      APPROUVEE: { bg: '#dcfce7', color: '#16a34a' },
      payee: { bg: '#e0e7ff', color: '#4f46e5' },
      rejetee: { bg: '#fee2e2', color: '#dc2626' },
    }

    const labels: any = {
      EN_ATTENTE: 'En attente',
      VALIDEE: 'Autorisée (1/2)',
      AUTORISEE: 'Autorisée (1/2)',
      REJETEE: 'Rejetée',
      brouillon: 'Brouillon',
      validee_tresorerie: 'Validée trésorerie',
      approuvee: 'Approuvée',
      APPROUVEE: 'Approuvée',
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

  const getVisaBadge = (req: any) => {
    const statusValue = String(req?.status ?? req?.statut ?? '').toLowerCase()
    if (!statusValue) return null
    if (statusValue === 'approuvee' || statusValue === 'payee' || statusValue === 'rejetee') return null
    return (
      <span className={styles.visaBadge} title="Validation croisée requise avant décaissement.">
        Visa 2/2 requis
      </span>
    )
  }

  const getPaymentStatusBadge = (req: Requisition) => {
    const statutValue = String((req as any).status ?? req.statut ?? '').toLowerCase()
    if (statutValue !== 'approuvee' && statutValue !== 'APPROUVEE' && statutValue !== 'payee') {
      return null
    }

    const total = toNumber(req.montant_total)
    const paid = toNumber((req as any).montant_deja_paye ?? 0)
    const remaining = total - paid

    if (remaining <= 0) {
      return (
        <span
          style={{
            padding: '4px 10px',
            borderRadius: '12px',
            background: '#dcfce7',
            color: '#166534',
            fontWeight: 600,
            fontSize: '12px',
            border: '1px solid #bbf7d0',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          ✅ Payé
        </span>
      )
    }

    if (paid > 0) {
      return (
        <span
          style={{
            padding: '4px 10px',
            borderRadius: '12px',
            background: '#fef3c7',
            color: '#92400e',
            fontWeight: 600,
            fontSize: '12px',
            border: '1px solid #fbbf24',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          🧾 Partiellement payée ({formatCurrency(remaining)})
        </span>
      )
    }

    return (
      <span
        className={styles.paymentPulse}
        style={{
          padding: '4px 10px',
          borderRadius: '12px',
          background: '#fef3c7',
          color: '#92400e',
          fontWeight: 600,
          fontSize: '12px',
          border: '1px solid #fbbf24',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
        }}
      >
        ⏳ À payer ({formatCurrency(remaining)})
      </span>
    )
  }

  const canCreate = user?.role === 'secretariat' || user?.role === 'admin'

  const totalRequisitions = filteredRequisitions.reduce((sum, r) => sum + toNumber(r.montant_total), 0)

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
      if (normalized === 'autorisee') return 'Autorisée (1/2)'
      if (normalized === 'payee') return 'Payée'
      return normalized ? normalized : ''
    }

    try {
      const results = await Promise.allSettled(
        filteredRequisitions.map(async (req) => {
          const demandeurData = (req as any).demandeur || null
          const approbateurData = (req as any).approbateur || null
          const autorisateurData = (req as any).validateur || null
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
            'Montant (USD)': toNumber(req.montant_total || 0),
            'Statut': formatStatut(statutValue),
            'Demandeur': demandeurData ? `${demandeurData.nom} ${demandeurData.prenom}` : '',
            'Autorisateur': autorisateurData ? `${autorisateurData.nom} ${autorisateurData.prenom}` : '',
            'Date autorisation': formatDate(req.validee_le),
            'Viseur': approbateurData ? `${approbateurData.nom} ${approbateurData.prenom}` : '',
            'Date visa': formatDate(req.approuvee_le),
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
        'Autorisateur': '',
        'Date autorisation': '',
        'Viseur': '',
        'Date visa': '',
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
              <option value="VALIDEE">Autorisée (1/2)</option>
              <option value="AUTORISEE">Autorisée (1/2)</option>
              <option value="APPROUVEE">Approuvée</option>
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
        <div className={styles.validationToggle}>
          <label>
            <input
              type="checkbox"
              checked={showValidationColumns}
              onChange={(e) => setShowValidationColumns(e.target.checked)}
            />
            Afficher Autorisateur/Viseur
          </label>
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
              {exchangeRate > 0 && (
                <span className={styles.recapSubValue}>
                  {formatCdf(totalRequisitions * exchangeRate)}
                </span>
              )}
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
                <label>Justificatif (PDF / Image, max 3 Mo)</label>
                <div
                  className={`${styles.annexeDrop} ${annexeError ? styles.annexeDropError : ''}`}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault()
                    const file = e.dataTransfer.files?.[0]
                    if (file) setAnnexeSelection(file)
                  }}
                >
                  <input
                    type="file"
                    accept=".pdf,image/png,image/jpeg"
                    onChange={(e) => setAnnexeSelection(e.target.files?.[0] || null)}
                  />
                  <div className={styles.annexeDropContent}>
                    <span className={styles.annexeIcon}>📎</span>
                    <div>
                      <strong>Glissez-déposez un fichier</strong>
                      <div className={styles.annexeHint}>ou cliquez pour sélectionner</div>
                    </div>
                  </div>
                </div>
                {annexeFile && !annexeError && (
                  <div className={styles.annexePreview}>
                    <span className={styles.annexeFileIcon}>📄</span>
                    <span>{annexeFile.name}</span>
                  </div>
                )}
                {annexeError && (
                  <div className={styles.annexeError}>{annexeError}</div>
                )}
                {!annexeError && (
                  <div className={styles.annexeHint}>
                    1 seul fichier. Si plusieurs factures, scannez-les en un seul PDF.
                  </div>
                )}
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
                          value={ligne.budget_ligne_id ?? ''}
                          onChange={(e) => updateLigne(index, 'budget_ligne_id', e.target.value ? Number(e.target.value) : null)}
                          required
                        >
                          <option value="">Sélectionner...</option>
                          {budgetLines.map(line => (
                            <option key={line.id} value={line.id}>{line.code} - {line.libelle}</option>
                          ))}
                        </select>
                        {budgetLines.length === 0 && (
                          <small className={styles.budgetHint}>
                            Aucune rubrique budget trouvée. Vérifie la page Budget (Dépenses).
                          </small>
                        )}
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

                      <div className={styles.field} style={{flex: 0.6}}>
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
                        <label>Devise</label>
                        <select
                          value={(ligne as any).devise || 'USD'}
                          onChange={(e) => updateLigne(index, 'devise', e.target.value)}
                        >
                          <option value="USD">USD</option>
                          <option value="CDF">CDF</option>
                        </select>
                      </div>

                      <div className={styles.field}>
                        <label>Prix unit. *</label>
                        <div className={styles.inlineInputRow}>
                          <input
                            type="number"
                            step="0.01"
                            value={ligne.montant_unitaire}
                            onChange={(e) => updateLigne(index, 'montant_unitaire', parseFloat(e.target.value) || 0)}
                            required
                          />
                          {(ligne as any).devise === 'CDF' && exchangeRate > 0 && (
                            <button
                              type="button"
                              className={styles.convertBtn}
                              onClick={() => {
                                const usd = toUsd(ligne.montant_unitaire, 'CDF')
                                updateLigne(index, 'devise', 'USD')
                                updateLigne(index, 'montant_unitaire', parseFloat(usd.toFixed(2)))
                              }}
                            >
                              Convertir
                            </button>
                          )}
                        </div>
                        {(ligne as any).devise === 'CDF' && exchangeRate === 0 && (
                          <small className={styles.budgetHint}>Taux de change non défini.</small>
                        )}
                      </div>

                      <div className={styles.field}>
                        <label>Total</label>
                        <input
                          type="text"
                          value={formatCurrency((ligne as any).devise === 'CDF' ? toUsd(ligne.montant_total, 'CDF') : ligne.montant_total)}
                          readOnly
                          disabled
                        />
                      </div>
                    </div>

                    {(() => {
                      const budgetLine = ligne.budget_ligne_id ? budgetLinesById.get(Number(ligne.budget_ligne_id)) : null
                      if (!budgetLine) return null
                      const disponible = toNumber(budgetLine.montant_disponible)
                      const devise = (ligne as any).devise || 'USD'
                      const totalUsd = toUsd(ligne.montant_total, devise)
                      const depasse = totalUsd > disponible
                      const resteCdf = exchangeRate ? disponible * exchangeRate : null
                      const seuil = printSettings?.budget_alert_threshold ?? 80
                      const pourcentage = budgetLine.montant_prevu ? ((toNumber(budgetLine.montant_engage) + totalUsd) / toNumber(budgetLine.montant_prevu)) * 100 : 0
                      return (
                        <div className={styles.budgetInfo}>
                          <span>Budget: {formatCurrency(budgetLine.montant_prevu)}</span>
                          <span>Engagé: {formatCurrency(budgetLine.montant_engage)}</span>
                          <span className={depasse ? styles.budgetAlert : undefined}>
                            Disponible: {formatCurrency(budgetLine.montant_disponible)}
                          </span>
                          {resteCdf !== null && (
                            <span className={styles.budgetHint}>
                              Disponible (CDF): {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(resteCdf)}
                            </span>
                          )}
                          {pourcentage >= seuil && pourcentage < 100 && (
                            <span className={styles.budgetWarn}>⚠ Seuil {seuil}% atteint</span>
                          )}
                          {depasse && (
                            <span className={styles.budgetAlert}>
                              {printSettings?.budget_block_overrun ? 'BLOCAGE' : 'Dépassement'}
                            </span>
                          )}
                        </div>
                      )
                    })()}

                    {lignes.length > 1 && (
                      <button type="button" onClick={() => removeLigne(index)} className={styles.removeBtn}>
                        ×
                      </button>
                    )}
                  </div>
                ))}

              <div className={styles.total}>
                <strong>Total général:</strong>
                <strong>{formatCurrency(calculateTotalUsd())}</strong>
              </div>
              {exchangeRate > 0 && (
                <div className={styles.budgetHint}>
                  Total (CDF): {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(calculateTotalUsd() * exchangeRate)}
                </div>
              )}
            </div>

            <div className={styles.formActions}>
              <button type="button" onClick={() => { setShowForm(false); resetForm(); }} className={styles.secondaryBtn} disabled={submitting}>
                Annuler
              </button>
              <button
                type="submit"
                className={`${styles.primaryBtn} ${printSettings?.budget_block_overrun && lignes.some(l => {
                  const line = budgetLinesById.get(Number(l.budget_ligne_id))
                  if (!line) return false
                  const devise = (l as any).devise || 'USD'
                  return toUsd(l.montant_total, devise) > toNumber(line.montant_disponible)
                }) ? styles.primaryBtnDisabled : ''}`}
                disabled={submitting || (printSettings?.budget_block_overrun && lignes.some(l => {
                  const line = budgetLinesById.get(Number(l.budget_ligne_id))
                  if (!line) return false
                  const devise = (l as any).devise || 'USD'
                  return toUsd(l.montant_total, devise) > toNumber(line.montant_disponible)
                }))}
              >
                {submitting ? 'Création en cours...' : 'Créer la réquisition'}
              </button>
            </div>
            </form>
          </div>
        </div>
      )}

      <div className={styles.listControls}>
        <div className={styles.pageSize}>
          <label>Affichage</label>
          <select value={String(pageSize)} onChange={(e) => setPageSize(Number(e.target.value))}>
            <option value="20">20 / page</option>
            <option value="50">50 / page</option>
            <option value="100">100 / page</option>
          </select>
        </div>
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage <= 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {safePage} / {totalPages} · {startIndex}-{endIndex} sur {filteredRequisitions.length}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage >= totalPages}
          >
            Suivant →
          </button>
        </div>
      </div>

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
              {showValidationColumns && <th>Autorisateur</th>}
              {showValidationColumns && <th>Viseur</th>}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedRequisitions.length === 0 ? (
              <tr>
                <td colSpan={showValidationColumns ? 9 : 7} className={styles.empty}>
                  Aucune réquisition trouvée
                </td>
              </tr>
            ) : (
              paginatedRequisitions.map((req) => (
                <tr key={req.id}>
                <td>{req.numero_requisition}</td>
                  <td>{format(new Date(req.created_at), 'dd/MM/yyyy')}</td>
                  <td>{req.objet}</td>
                  <td>
                    <div>
                      <div>{formatCurrency(req.montant_total)}</div>
                      {exchangeRate > 0 && (
                        <div className={styles.amountSubValue}>
                          {formatCdf(toNumber(req.montant_total) * exchangeRate)}
                        </div>
                      )}
                    </div>
                  </td>
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
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {getStatutBadge((req as any).status ?? req.statut)}
                      {getPaymentStatusBadge(req)}
                      {getVisaBadge(req)}
                    </div>
                  </td>
                  {showValidationColumns && (
                    <td>
                      {(req as any).validateur
                        ? `${(req as any).validateur.prenom || ''} ${(req as any).validateur.nom || ''}`.trim() || '—'
                        : '—'}
                    </td>
                  )}
                  {showValidationColumns && (
                    <td className={(req as any).approbateur ? '' : styles.missingViseur}>
                      {(req as any).approbateur
                        ? `${(req as any).approbateur.prenom || ''} ${(req as any).approbateur.nom || ''}`.trim() || '—'
                        : 'En attente'}
                    </td>
                  )}
                  <td>
                    <div className={styles.actions}>
                      <button
                        onClick={() => viewDetails(req)}
                        className={styles.viewBtn}
                        title="Voir les détails"
                      >
                        Voir détails
                      </button>
                      {(req as any).annexe?.id && (
                        <button
                          onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${(req as any).annexe?.id}`, '_blank')}
                          className={styles.actionBtn}
                          title="Voir la pièce jointe"
                        >
                          📎 Voir pièce jointe
                        </button>
                      )}
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
                        <label style={{color: '#16a34a', fontWeight: 600}}>Autorisateur (1/2)</label>
                        <p><strong>
                          {selectedRequisitionUsers.validateur
                            ? `${selectedRequisitionUsers.validateur.prenom} ${selectedRequisitionUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Date d'autorisation</label>
                        <p>
                          {(selectedRequisition as any).validee_le
                            ? format(new Date((selectedRequisition as any).validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Viseur (2/2)</label>
                        <p><strong>
                      {selectedRequisitionUsers.approbateur
                            ? `${selectedRequisitionUsers.approbateur.prenom} ${selectedRequisitionUsers.approbateur.nom}`
                            : 'En attente'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label style={{color: '#16a34a', fontWeight: 600}}>Date de visa</label>
                        <p>
                          {(selectedRequisition as any).approuvee_le
                            ? format(new Date((selectedRequisition as any).approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label style={{color: '#16a34a', fontWeight: 600}}>Statut actuel</label>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {getStatutBadge((selectedRequisition as any).status ?? selectedRequisition.statut)}
                      {getPaymentStatusBadge(selectedRequisition)}
                    </div>
                  </div>
                  {selectedRequisition.annexe?.id && (
                    <div className={styles.detailItem}>
                      <label style={{color: '#16a34a', fontWeight: 600}}>Pièce jointe</label>
                      <button
                        className={styles.viewBtn}
                        onClick={() => window.open(`${API_BASE_URL}/requisitions/annexe/${selectedRequisition.annexe?.id}`, '_blank')}
                      >
                        👁️ Voir la pièce jointe
                      </button>
                    </div>
                  )}
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
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{formatCurrency(selectedRequisition.montant_total)}</strong></p>
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
                        <td>{formatCurrency(ligne.montant_unitaire)}</td>
                        <td><strong>{formatCurrency(ligne.montant_total)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={4} style={{textAlign: 'right', fontWeight: 600}}>Total général:</td>
                      <td><strong style={{fontSize: '16px', color: '#0d9488'}}>{formatCurrency(selectedRequisition.montant_total)}</strong></td>
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
