import { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/apiClient'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { Requisition, Money, Service, CommissionMember } from '../types'
import type { BudgetPosteSummary } from '../types/budget'
import { uploadRemboursementTransportPdf } from '../api/remboursementsTransport'
import { getServiceMembers, getServices } from '../api/services'
import { toNumber } from '../utils/amount'
import { buildBudgetDecisionSummary, formatBudgetDecisionAmount } from '../utils/budgetDecision'
import { getStatusMeta } from '../utils/statusMapper'
import { format } from 'date-fns'
import { generateRemboursementTransportPDF } from '../utils/pdfGeneratorRemboursement'
import { numberToWords } from '../utils/numberToWords'
import { getTenantSlug } from '../utils/tenant'
import { useConfirm } from '../contexts/ConfirmContext'
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import { isAssistantMember, resolveMemberFunctionLabel } from '../utils/serviceMemberFunctions'
import styles from './RemboursementTransport.module.css'

const TODAY = format(new Date(), 'yyyy-MM-dd')

interface RemboursementTransport {
  id: string
  numero_remboursement: string
  instance: string
  type_reunion: 'bureau' | 'commission' | 'commission_ad_hoc' | 'conseil' | 'atelier'
  nature_reunion: string
  nature_travail: string[]
  lieu: string
  date_reunion: string
  heure_debut?: string
  heure_fin?: string
  montant_total: Money
  requisition_id?: string
  requisition?: Requisition
  service_id?: number | null
  service_code?: string | null
  service_libelle?: string | null
  created_at: string
  created_by: string
}

type DraftDossier = {
  id: string
  reference: string
  created_at: string
  description?: string | null
  status?: string
}

interface Participant {
  id?: string
  nom: string
  titre_fonction: string
  montant: Money
  type_participant: 'principal' | 'assistant'
  expert_comptable_id?: string
}

interface ExpertComptable {
  id: string
  numero_ordre: string
  nom_denomination: string
}

type DetailBudgetMetrics = {
  budget: number | null
  engaged: number | null
  available: number | null
  remainingAfterRequest: number | null
  requested: number
}

export default function RemboursementTransport() {
  const { user } = useAuth()
  const confirm = useConfirm()
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const location = useLocation()
  const navigate = useNavigate()
  const [remboursements, setRemboursements] = useState<RemboursementTransport[]>([])
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [rubriques, setRubriques] = useState<BudgetPosteSummary[]>([])
  const [isAutoFilling, setIsAutoFilling] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [submittingExamenId, setSubmittingExamenId] = useState<string | null>(null)
  const [selectedRemboursementIds, setSelectedRemboursementIds] = useState<string[]>([])
  const [draftDossiers, setDraftDossiers] = useState<DraftDossier[]>([])
  const [selectedDraftDossierId, setSelectedDraftDossierId] = useState('')

  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedRemboursementDetails, setSelectedRemboursementDetails] = useState<RemboursementTransport | null>(null)
  const [selectedParticipants, setSelectedParticipants] = useState<Participant[]>([])
  const [selectedBudgetMetrics, setSelectedBudgetMetrics] = useState<DetailBudgetMetrics | null>(null)
  const [selectedRemboursementUsers, setSelectedRemboursementUsers] = useState<{
    demandeur?: { prenom: string; nom: string }
    validateur?: { prenom: string; nom: string }
    approbateur?: { prenom: string; nom: string }
  }>({})

  const tenantInstance = user?.organisation_slug || getTenantSlug() || ''
  const serviceParam = new URLSearchParams(location.search).get('service_id')
  const serviceStateIdRaw = (location.state as any)?.fromCommission
  const serviceStateId =
    serviceStateIdRaw !== undefined && serviceStateIdRaw !== null ? String(serviceStateIdRaw) : ''
  const serviceContextId = serviceParam || serviceStateId
  const [formData, setFormData] = useState({
    instance: tenantInstance,
    service_id: serviceContextId || '',
    budget_poste_id: '',
    type_reunion: 'bureau' as 'bureau' | 'commission' | 'commission_ad_hoc' | 'conseil' | 'atelier',
    nature_reunion: '',
    nature_travail: [''],
    lieu: '',
    date_reunion: format(new Date(), 'yyyy-MM-dd'),
    heure_debut: '',
    heure_fin: ''
  })

  const getTypeReunionLabel = (value?: string | null) => {
    switch (String(value || '')) {
      case 'bureau':
        return 'Réunion du Bureau'
      case 'commission':
        return 'Réunion de la Commission permanente'
      case 'commission_ad_hoc':
        return 'Réunion de la Commission ad hoc'
      case 'conseil':
        return 'Réunion du Conseil'
      case 'atelier':
        return 'Atelier / Séminaire / Formation'
      default:
        return value || 'N/A'
    }
  }

  const [participants, setParticipants] = useState<Participant[]>([
    { nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }
  ])

  const [assistants, setAssistants] = useState<Participant[]>([])
  const [showAssistants, setShowAssistants] = useState(false)
  const [showExpertSearch, setShowExpertSearch] = useState<number | null>(null)
  const [showAssistantExpertSearch, setShowAssistantExpertSearch] = useState<number | null>(null)

  const [notification, setNotification] = useState<{
    show: boolean
    type: 'success' | 'error' | 'warning'
    message: string
  }>({ show: false, type: 'success', message: '' })

  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterServiceId, setFilterServiceId] = useState<string>(serviceContextId || '')
  const [dateDebut, setDateDebut] = useState(TODAY)
  const [dateFin, setDateFin] = useState(TODAY)
  const [printFormat, setPrintFormat] = useState<'a4' | 'a5'>('a4')
  const [expertSearchCache, setExpertSearchCache] = useState<Record<string, ExpertComptable[]>>({})
  const [expertSearchLoading, setExpertSearchLoading] = useState(false)
  const [activeSearchTerm, setActiveSearchTerm] = useState('')
  const [expertSearchLoadingTerm, setExpertSearchLoadingTerm] = useState('')
  const searchDebounceRef = useRef<number | null>(null)

  const serviceIds = (user?.service_ids && user.service_ids.length > 0)
    ? user.service_ids
    : user?.service_id
      ? [user.service_id]
      : []
  const isServiceUser = serviceIds.length > 0 && user?.role !== 'admin' && user?.role !== 'super_admin'

  const selectableServices = isServiceUser
    ? services.filter((service) => serviceIds.includes(service.id))
    : services
  const defaultServiceId = (() => {
    if (serviceContextId) return serviceContextId
    if (isServiceUser && selectableServices.length === 1) return String(selectableServices[0].id)
    return ''
  })()
  const isServiceLockedByContext = Boolean(serviceContextId) || (isServiceUser && selectableServices.length === 1)

  const serviceLabel = (() => {
    if (!formData.service_id) return ''
    const serviceId = Number(formData.service_id)
    if (!Number.isFinite(serviceId)) return ''
    const service = services.find((s) => s.id === serviceId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${serviceId}`
  })()

  const buildBudgetMetrics = (
    lines: Array<{
      budget_poste_id?: number | null
      budget_poste_code_snapshot?: string | null
      budget_poste_libelle_snapshot?: string | null
      rubrique?: string | null
      montant_total?: number | string
      montant_alloue_snapshot?: number | string | null
      montant_disponible_snapshot?: number | string | null
    }> = [],
    requestedAmount?: number | string
  ): DetailBudgetMetrics => {
    const summary = buildBudgetDecisionSummary(lines, requestedAmount)
    return {
      budget: summary.budget,
      engaged: summary.engaged,
      available: summary.available,
      remainingAfterRequest: summary.remainingAfterRequest,
      requested: summary.requested,
    }
  }

  const renderBudgetMetric = (amount?: number | null) => {
    return formatBudgetDecisionAmount(amount)
  }

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    if (defaultServiceId && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: defaultServiceId }))
    }
  }, [defaultServiceId, formData.service_id])

  const clearNewParam = () => {
    const params = new URLSearchParams(location.search)
    if (!params.has('new')) return
    params.delete('new')
    const nextSearch = params.toString()
    navigate(
      { pathname: location.pathname, search: nextSearch ? `?${nextSearch}` : '' },
      { replace: true, state: location.state }
    )
  }

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    setShowForm(params.get('new') === '1')
  }, [location.search])

  useEffect(() => {
    if (tenantInstance && formData.instance !== tenantInstance) {
      setFormData((prev) => ({ ...prev, instance: tenantInstance }))
    }
  }, [tenantInstance, formData.instance])

  useEffect(() => {
    if (serviceContextId && formData.service_id !== serviceContextId) {
      setFormData((prev) => ({ ...prev, service_id: serviceContextId }))
    }
  }, [serviceContextId, formData.service_id])

  useEffect(() => {
    if (serviceContextId && filterServiceId !== serviceContextId) {
      setFilterServiceId(serviceContextId)
    }
  }, [serviceContextId, filterServiceId])

  const canAutofillParticipants = () => {
    const participantsEmpty = participants.every(
      (p) =>
        !p.nom.trim() &&
        !p.titre_fonction.trim() &&
        (toNumber(p.montant) || 0) === 0 &&
        !p.expert_comptable_id
    )
    const assistantsEmpty = assistants.length === 0 ||
      assistants.every(
        (a) =>
          !a.nom.trim() &&
          !a.titre_fonction.trim() &&
          (toNumber(a.montant) || 0) === 0 &&
          !a.expert_comptable_id
      )
    return participantsEmpty && assistantsEmpty
  }

  const buildParticipantFromMember = (member: CommissionMember, type: 'principal' | 'assistant'): Participant => {
    const nameFromUser = `${member.user?.prenom || ''} ${member.user?.nom || ''}`.trim()
    const fallbackName = member.email || member.matricule || ''
    const fullName = (member.full_name || '').trim() || nameFromUser || fallbackName
    return {
      nom: fullName,
      titre_fonction: (member.custom_title || '').trim() || resolveMemberFunctionLabel(member),
      montant: 0,
      type_participant: type,
    }
  }

  useEffect(() => {
    const fetchMembers = async () => {
      if (!showForm) return
      if (!formData.service_id) return
      if (isAutoFilling) return
      if (!canAutofillParticipants()) return
      const serviceId = Number(formData.service_id)
      if (!Number.isFinite(serviceId)) return
      try {
        setIsAutoFilling(true)
        const members = await getServiceMembers(serviceId)
        const principals = members
          .filter((m) => !isAssistantMember(m))
          .map((m) => buildParticipantFromMember(m, 'principal'))
          .filter((p) => p.nom.trim())
        const assistantsList = members
          .filter((m) => isAssistantMember(m))
          .map((m) => buildParticipantFromMember(m, 'assistant'))
          .filter((p) => p.nom.trim())
        if (participants.length === 0 || participants.every((p) => !p.nom.trim() && !p.titre_fonction.trim())) {
          setParticipants(
            principals.length > 0
              ? principals
              : [{ nom: '', titre_fonction: '', montant: 0, type_participant: 'principal' }]
          )
        }
        if (assistants.length === 0 || assistants.every((a) => !a.nom.trim() && !a.titre_fonction.trim())) {
          setAssistants(assistantsList)
          setShowAssistants(assistantsList.length > 0)
        }
      } catch (error) {
        console.error('Erreur lors du pré-remplissage des membres', error)
      } finally {
        setIsAutoFilling(false)
      }
    }
    fetchMembers()
  }, [showForm, formData.service_id])

  const loadData = async () => {
    try {
      const [remboursementsRes, expertsRes, servicesRes] = await Promise.all([
        apiRequest('GET', '/remboursements-transport', { params: { include: 'requisition', limit: 200, offset: 0 } }),
        apiRequest('GET', '/experts-comptables', { params: { active: true, limit: 200, offset: 0 } }),
        getServices({ active: true }),
      ])

      const remb = Array.isArray(remboursementsRes) ? remboursementsRes : (remboursementsRes as any)?.items ?? (remboursementsRes as any)?.data ?? []
      const exp = Array.isArray(expertsRes) ? expertsRes : (expertsRes as any)?.items ?? (expertsRes as any)?.data ?? []

      setRemboursements(remb as any)
      setExperts(exp as any)
      setServices(Array.isArray(servicesRes) ? servicesRes : [])
      try {
        const draftDossiersRes: any = await apiRequest('GET', '/dossiers/drafts', { params: { limit: 200 } })
        const drafts = Array.isArray(draftDossiersRes) ? draftDossiersRes : (draftDossiersRes as any)?.items ?? []
        setDraftDossiers(drafts as DraftDossier[])
      } catch (draftError) {
        console.error('Error loading draft dossiers:', draftError)
        setDraftDossiers([])
      }
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const loadRubriques = async () => {
      const effectiveServiceId = formData.service_id || defaultServiceId
      if (!effectiveServiceId) {
        setRubriques([])
        return
      }
      try {
        const serviceId = Number(effectiveServiceId)
        const rubriquesRes = await apiRequest('GET', '/budget/lines/autorisees', {
          params: {
            active: true,
            type: 'DEPENSE',
            service_id: Number.isFinite(serviceId) ? serviceId : undefined,
          },
        })
        const postes = (rubriquesRes as any)?.lignes ?? []
        setRubriques(Array.isArray(postes) ? postes : [])
      } catch (error) {
        console.error('Error loading budget postes:', error)
        setRubriques([])
      }
    }
    loadRubriques()
  }, [formData.service_id, defaultServiceId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)

    try {
      if (!formData.service_id) {
        setNotification({
          show: true,
          type: 'error',
          message: 'Veuillez sélectionner une commission / service.'
        })
        setSubmitting(false)
        return
      }
      if (!formData.budget_poste_id) {
        setNotification({
          show: true,
          type: 'error',
          message: 'Veuillez sélectionner un poste budgétaire.'
        })
        setSubmitting(false)
        return
      }
      const objetRequisition = `Remboursement transport - ${formData.nature_reunion} - ${formData.lieu} - ${format(new Date(formData.date_reunion), 'dd/MM/yyyy')}`

      const requisitionData: any = await apiRequest('POST', '/requisitions', {
        objet: objetRequisition,
        type_requisition: 'remboursement_transport',
        mode_paiement: 'cash',
        montant_total: calculateTotal(),
        service_id: Number(formData.service_id),
        created_by: user?.id,
        statut: 'BROUILLON',
      })

      const selectedRubrique = rubriques.find((r) => String(r.id) === String(formData.budget_poste_id))
      const rubriqueLabel = selectedRubrique ? `${selectedRubrique.code} - ${selectedRubrique.libelle}` : 'Remboursement transport'
      const total = calculateTotal()
      await apiRequest('POST', '/lignes-requisition', [
        {
          requisition_id: requisitionData.id,
          budget_poste_id: Number(formData.budget_poste_id),
          rubrique: rubriqueLabel,
          description: objetRequisition,
          quantite: 1,
          montant_unitaire: total,
          montant_total: total,
          devise: 'USD',
        }
      ])

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

      try {
        const selectedService = services.find((service) => String(service.id) === String(formData.service_id))
        const remboursementForPdf = {
          ...remboursementData,
          service_id: remboursementData.service_id ?? (formData.service_id ? Number(formData.service_id) : null),
          service_code: remboursementData.service_code || selectedService?.code || null,
          service_libelle: remboursementData.service_libelle || selectedService?.libelle || null,
        }
        const pdfBlob = await generateRemboursementTransportPDF(
          remboursementForPdf,
          allParticipants,
          'blob',
          `${user?.prenom} ${user?.nom}`,
          printFormat,
        )
        if (pdfBlob) {
          const rawNumber = remboursementForPdf.reference_numero || remboursementForPdf.numero_remboursement || 'remboursement_transport'
          const safeNumber = String(rawNumber).trim().replace(/[\\/:*?"<>|]+/g, '-')
          await uploadRemboursementTransportPdf(remboursementData.id, pdfBlob, `${safeNumber}.pdf`)
        }
      } catch (pdfError) {
        console.error('Error generating remboursement PDF after creation:', pdfError)
        setNotification({
          show: true,
          type: 'warning',
          message: `Remboursement ${remboursementData.numero_remboursement} créé, mais le PDF officiel n'a pas pu être généré automatiquement.`,
        })
        clearNewParam()
        setShowForm(false)
        resetForm()
        loadData()
        return
      }

      setNotification({
        show: true,
        type: 'success',
        message: `Remboursement ${remboursementData.numero_remboursement} créé avec succès. Il doit être signé puis soumis à l'examen.`
      })
      clearNewParam()
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
      instance: tenantInstance,
      service_id: defaultServiceId,
      budget_poste_id: '',
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

  useEffect(() => {
    return () => {
      if (searchDebounceRef.current) {
        window.clearTimeout(searchDebounceRef.current)
      }
    }
  }, [])

  const renderExpertDropdown = (
    searchValue: string,
    onSelect: (expert: ExpertComptable) => void
  ) => {
    const filteredExperts = getFilteredExperts(searchValue)
    const loadingExperts = isLoadingExperts(searchValue)
    return (
      <div className={styles.expertDropdown}>
        <div className={styles.expertDropdownHeader}>
          {loadingExperts ? 'Recherche en cours...' : `${filteredExperts.length} expert(s) disponible(s)`}
          {!loadingExperts &&
            expertSearchLoading &&
            normalizeSearchTerm(activeSearchTerm) === normalizeSearchTerm(searchValue) &&
            !expertSearchCache[normalizeSearchTerm(searchValue)]
            ? ' (recherche...)'
            : ''}
        </div>
        <div className={styles.expertDropdownList}>
          {filteredExperts.slice(0, 25).map(expert => (
            <div
              key={expert.id}
              onMouseDown={(e) => {
                e.preventDefault()
                onSelect(expert)
              }}
              className={styles.expertDropdownItem}
            >
              <div className={styles.expertDropdownNumero}>{expert.numero_ordre}</div>
              <div className={styles.expertDropdownName}>{expert.nom_denomination}</div>
            </div>
          ))}
        </div>
        {filteredExperts.length === 0 && (
          <div className={styles.expertDropdownEmpty}>
            {searchValue.trim() ? (
              <>
                <div className={styles.expertDropdownEmptyIcon}>🔍</div>
                <div className={styles.expertDropdownEmptyTitle}>Aucun expert trouvé</div>
                <div className={styles.expertDropdownEmptySubtitle}>pour "{searchValue}"</div>
              </>
            ) : (
              <>
                <div className={styles.expertDropdownEmptyIcon}>👨‍💼</div>
                <div className={styles.expertDropdownEmptyTitle}>{experts.length} experts disponibles</div>
                <div className={styles.expertDropdownEmptySubtitle}>Tapez pour rechercher</div>
              </>
            )}
          </div>
        )}
        {filteredExperts.length > 25 && (
          <div className={styles.expertDropdownFooter}>
            +{filteredExperts.length - 25} autres résultats
            <div className={styles.expertDropdownFooterHint}>Affinez votre recherche pour voir plus</div>
          </div>
        )}
      </div>
    )
  }

  const normalizeSearchTerm = (value: string) => value.trim().toLowerCase()

  const fetchExpertsBySearch = async (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized || expertSearchCache[normalized]) return
    setExpertSearchLoading(true)
    setExpertSearchLoadingTerm(normalized)
    try {
      const res: any = await apiRequest('GET', '/experts-comptables', {
        params: {
          q: searchTerm.trim(),
          active: true,
          limit: 200,
          offset: 0,
          order: 'nom_denomination.asc',
        },
      })
      const items = Array.isArray(res) ? res : (res?.items ?? [])
      setExpertSearchCache((prev) => ({ ...prev, [normalized]: items as any }))
    } catch (error) {
      console.error('Error searching experts:', error)
    } finally {
      setExpertSearchLoading(false)
      setExpertSearchLoadingTerm((prev) => (prev === normalized ? '' : prev))
    }
  }

  const queueExpertSearch = (searchTerm: string) => {
    setActiveSearchTerm(searchTerm)
    if (searchDebounceRef.current) {
      window.clearTimeout(searchDebounceRef.current)
    }
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized) return
    searchDebounceRef.current = window.setTimeout(() => {
      fetchExpertsBySearch(searchTerm)
    }, 150)
  }

  const getFilteredExperts = (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    if (!normalized) return experts
    const local = experts.filter(e =>
      e.nom_denomination.toLowerCase().includes(normalized) ||
      e.numero_ordre.toLowerCase().includes(normalized)
    )
    if (local.length > 0) return local
    if (expertSearchCache[normalized]) return expertSearchCache[normalized]
    return []
  }

  const isLoadingExperts = (searchTerm: string) => {
    const normalized = normalizeSearchTerm(searchTerm)
    return !!normalized && expertSearchLoadingTerm === normalized && !expertSearchCache[normalized]
  }

  const calculateTotal = () => {
    const participantsTotal = participants.reduce((sum, p) => sum + (toNumber(p.montant) || 0), 0)
    const assistantsTotal = assistants.reduce((sum, p) => sum + (toNumber(p.montant) || 0), 0)
    return participantsTotal + assistantsTotal
  }

  const previewParticipants = [...participants, ...assistants].filter(
    (p) => p.nom.trim() !== '' || p.titre_fonction.trim() !== ''
  )
  const previewTotal = calculateTotal()
  const previewMontantLettres = numberToWords(previewTotal)

  const printRemboursement = async (remboursement: RemboursementTransport) => {
    try {
      const participantsRes: any = await apiRequest('GET', '/participants-transport', { params: { remboursement_id: remboursement.id, limit: 500 } })
      const participantsData = Array.isArray(participantsRes) ? participantsRes : (participantsRes as any)?.items ?? (participantsRes as any)?.data ?? []
      const handleUpload = async (blob: Blob, filename: string) => {
        try {
          await uploadRemboursementTransportPdf(remboursement.id, blob, filename)
        } catch (error) {
          console.error('Error uploading remboursement PDF:', error)
        }
      }

      const serviceId = getRemboursementServiceId(remboursement)
      const service = services.find((item) => String(item.id) === String(serviceId))
      const remboursementForPdf = {
        ...remboursement,
        service_id: remboursement.service_id ?? (serviceId ? Number(serviceId) : null),
        service_code: remboursement.service_code || service?.code || null,
        service_libelle: remboursement.service_libelle || service?.libelle || null,
      }

      await generateRemboursementTransportPDF(
        remboursementForPdf,
        participantsData || [],
        'print',
        `${user?.prenom} ${user?.nom}`,
        printFormat,
        handleUpload
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

      const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
      if (requisitionId) {
        const lignesRes: any = await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisitionId } })
        const lignesData = Array.isArray(lignesRes) ? lignesRes : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
        setSelectedBudgetMetrics(buildBudgetMetrics(lignesData || [], remboursement.montant_total))
      } else {
        setSelectedBudgetMetrics(buildBudgetMetrics([], remboursement.montant_total))
      }

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

  const normalizeStatus = (raw?: string | null) => {
    const upper = String(raw || '').toUpperCase()
    if (upper === 'BROUILLON') return 'BROUILLON'
    if (upper === 'SIGNEE_SERVICE') return 'SIGNEE_SERVICE'
    if (upper === 'EN_ATTENTE' || upper === 'A_VALIDER') return 'EN_ATTENTE'
    if (upper === 'AUTORISEE' || upper === 'VALIDEE') return 'AUTORISEE'
    if (upper === 'APPROUVEE') return 'APPROUVEE'
    if (upper === 'PAYEE') return 'PAYEE'
    if (upper === 'REJETEE') return 'REJETEE'
    return upper
  }

  const canSignRequisition = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const hasLines = requisition?.lignes_count == null ? true : Number(requisition.lignes_count) > 0
    return Boolean(requisition?.id) && Boolean(requisition?.service_id) && status === 'BROUILLON' && hasLines
  }

  const canSubmitToExamen = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    const hasEligibleExamenStatus = examenStatus === 'NON_EXAMINE' || examenStatus === 'REJETE'
    const hasLines = requisition?.lignes_count == null ? true : Number(requisition.lignes_count) > 0
    return (
      Boolean(requisition?.id) &&
      !requisition?.dossier_id &&
      Boolean(requisition?.service_id) &&
      status === 'SIGNEE_SERVICE' &&
      hasEligibleExamenStatus &&
      Boolean(requisition?.signed_by_id) &&
      Boolean(requisition?.signed_at) &&
      hasLines
    )
  }

  const getSubmitExamenLabel = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    if (!requisition?.id && !remboursement.requisition_id) return 'Réquisition manquante'
    if (requisition?.dossier_id) return 'Dans dossier'
    if (examenStatus === 'EN_EXAMEN') return 'Déjà soumis'
    if (examenStatus === 'EXAMINE') return 'Examiné'
    if (status === 'BROUILLON') return "Signer d'abord"
    if (status !== 'SIGNEE_SERVICE') return 'Non disponible'
    if (!requisition?.signed_by_id) return 'Signature requise'
    if (!requisition?.signed_at) return 'Date de signature requise'
    if (requisition?.lignes_count != null && Number(requisition.lignes_count) <= 0) return 'Aucune ligne'
    if (examenStatus === 'REJETE') return 'Resoumettre'
    return 'Soumettre'
  }

  const canSelectForDossier = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    const requisitionId = requisition?.id || remboursement.requisition_id
    if (!requisitionId) return false
    const status = String(requisition?.status ?? requisition?.statut ?? '').toUpperCase()
    const examenStatus = String(requisition?.examen_status || '').toUpperCase()
    const isFinal = ['APPROUVEE', 'PAYEE', 'REJETEE'].includes(status)
    if (isFinal || examenStatus === 'EXAMINE') return false
    if (requisition?.dossier_id) return examenStatus === 'NON_EXAMINE'
    return true
  }

  const canDeleteRemboursement = (remboursement: RemboursementTransport) => {
    const examenStatus = String(remboursement.requisition?.examen_status || '').toUpperCase()
    return Boolean(remboursement.requisition?.id || remboursement.requisition_id) && examenStatus === 'NON_EXAMINE'
  }

  const toggleSelectRemboursement = (id: string) => {
    setSelectedRemboursementIds((prev) => (
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    ))
  }

  const clearSelection = () => {
    setSelectedRemboursementIds([])
    setSelectedDraftDossierId('')
  }

  const getRemboursementStatus = (remboursement: RemboursementTransport) => {
    const requisition = remboursement.requisition
    return normalizeStatus(requisition?.status ?? requisition?.statut)
  }

  const getRemboursementServiceId = (remboursement: RemboursementTransport) => {
    const serviceId = remboursement.requisition?.service_id
    return serviceId === undefined || serviceId === null ? '' : String(serviceId)
  }

  const getServiceLabel = (serviceId?: string | number | null) => {
    if (serviceId === undefined || serviceId === null || serviceId === '') return '—'
    const normalizedId = Number(serviceId)
    const service = services.find((item) => item.id === normalizedId)
    return service ? `${service.code} - ${service.libelle}` : `Service #${serviceId}`
  }

  const getDateOnly = (value?: string | null) => {
    return String(value || '').slice(0, 10)
  }

  const handleSignRequisition = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return
    setSigningId(String(requisitionId))
    try {
      await apiRequest('PATCH', `/requisitions/${requisitionId}/sign`)
      setNotification({
        show: true,
        type: 'success',
        message: 'Remboursement signé par le service.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Signature impossible.'
      })
    } finally {
      setSigningId(null)
    }
  }

  const handleSubmitExamen = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return
    setSubmittingExamenId(String(requisitionId))
    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/submit-examen`)
      setNotification({
        show: true,
        type: 'success',
        message: "Le remboursement a été soumis à l'examen."
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible de soumettre le remboursement à l'examen."
      })
    } finally {
      setSubmittingExamenId(null)
    }
  }

  const getRequisitionId = (remboursement: RemboursementTransport) => {
    return remboursement.requisition?.id || remboursement.requisition_id || ''
  }

  const remboursementsList = Array.isArray(remboursements) ? remboursements : []
  const selectedRemboursements = remboursementsList.filter((remboursement) =>
    selectedRemboursementIds.includes(remboursement.id)
  )
  const selectedRequisitionIds = selectedRemboursements
    .map((remboursement) => getRequisitionId(remboursement))
    .filter(Boolean)
  const selectedDossierIds = new Set(
    selectedRemboursements
      .map((remboursement) => remboursement.requisition?.dossier_id)
      .filter(Boolean) as string[]
  )
  const selectedDossierId =
    selectedDossierIds.size === 1 && selectedRemboursements.every((remboursement) => remboursement.requisition?.dossier_id)
      ? Array.from(selectedDossierIds)[0]
      : null
  const canCreateDossier =
    selectedRemboursements.length > 0 &&
    selectedRequisitionIds.length === selectedRemboursements.length &&
    selectedRemboursements.every((remboursement) => !remboursement.requisition?.dossier_id)
  const canAddToDraftDossier = canCreateDossier && draftDossiers.length > 0
  const canSubmitDossier = Boolean(selectedDossierId)
  const hasMixedDossierSelection =
    selectedRemboursements.length > 0 && !canCreateDossier && !canSubmitDossier

  const handleCreateDossier = async () => {
    if (!canCreateDossier) return
    try {
      const res: any = await apiRequest('POST', '/dossiers', { requisition_ids: selectedRequisitionIds })
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: res?.reference
          ? `Dossier ${res.reference} créé en brouillon avec les remboursements sélectionnés.`
          : 'Dossier créé en brouillon avec les remboursements sélectionnés.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Impossible de créer le dossier.'
      })
    }
  }

  const handleAddToDraftDossier = async () => {
    if (!canAddToDraftDossier || !selectedDraftDossierId) return
    try {
      await apiRequest('POST', `/dossiers/${selectedDraftDossierId}/add-requisitions`, {
        requisition_ids: selectedRequisitionIds,
      })
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: 'Les remboursements sélectionnés ont été ajoutés au dossier brouillon.'
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'Impossible d’ajouter les remboursements au dossier.'
      })
    }
  }

  const handleSubmitDossier = async (dossierId: string) => {
    try {
      await apiRequest('POST', `/dossiers/${dossierId}/submit-examen`)
      clearSelection()
      setNotification({
        show: true,
        type: 'success',
        message: "Le dossier de remboursements a été soumis à l'examen."
      })
      await loadData()
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible de soumettre le dossier à l'examen."
      })
    }
  }

  const handleDeleteRemboursement = async (remboursement: RemboursementTransport) => {
    const requisitionId = remboursement.requisition?.id || remboursement.requisition_id
    if (!requisitionId) return

    const confirmed = await confirm({
      title: 'Supprimer le remboursement',
      description: remboursement.requisition?.dossier_id
        ? 'Ce remboursement sera supprimé car son dossier est encore en brouillon.'
        : 'Supprimer ce remboursement de transport ?',
      confirmText: 'Supprimer',
      variant: 'danger',
    })
    if (!confirmed) return

    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/soft-delete`)
      setSelectedRemboursementIds((prev) => prev.filter((id) => id !== remboursement.id))
      if (selectedRemboursementDetails?.id === remboursement.id) {
        setShowDetailModal(false)
        setSelectedRemboursementDetails(null)
      }
      await loadData()
      setNotification({
        show: true,
        type: 'success',
        message: 'Le remboursement a été supprimé.',
      })
    } catch (error: any) {
      console.error('Error deleting remboursement:', error)
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || 'La suppression du remboursement a échoué.',
      })
    }
  }

  const filteredRemboursements = remboursementsList.filter(r => {
    const searchLower = searchQuery.trim().toLowerCase()
    const serviceLabelForRow = getServiceLabel(getRemboursementServiceId(r))
    const matchSearch = !searchLower ||
                        r.numero_remboursement.toLowerCase().includes(searchLower) ||
                        r.nature_reunion.toLowerCase().includes(searchLower) ||
                        r.lieu.toLowerCase().includes(searchLower) ||
                        serviceLabelForRow.toLowerCase().includes(searchLower)

    const requisitionStatut = getRemboursementStatus(r)
    const matchStatut = !filterStatut || requisitionStatut === filterStatut

    const serviceId = getRemboursementServiceId(r)
    const matchService = !filterServiceId || serviceId === filterServiceId

    const dateReunion = getDateOnly(r.date_reunion)
    const matchDateDebut = !dateDebut || dateReunion >= dateDebut
    const matchDateFin = !dateFin || dateReunion <= dateFin

    return matchSearch && matchStatut && matchService && matchDateDebut && matchDateFin
  })
  const selectableFilteredIds = filteredRemboursements.filter(canSelectForDossier).map((r) => r.id)
  const allSelectableFilteredSelected =
    selectableFilteredIds.length > 0 && selectableFilteredIds.every((id) => selectedRemboursementIds.includes(id))

  const toggleSelectVisible = () => {
    setSelectedRemboursementIds((prev) => {
      if (allSelectableFilteredSelected) {
        return prev.filter((id) => !selectableFilteredIds.includes(id))
      }
      return Array.from(new Set([...prev, ...selectableFilteredIds]))
    })
  }

  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const getStatutBadge = (statut: string) => {
    const meta = getStatusMeta(statut)
    return (
      <span
        className={styles.detailBadge}
        style={{ background: meta.bg, color: meta.color }}
      >
        {meta.label}
      </span>
    )
  }

  const openRequisitionAnnexe = async (annexe?: { id: string; filename?: string | null } | null) => {
    if (!annexe?.id) return
    try {
      if (annexe.filename) {
        await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
      } else {
        await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
      }
    } catch (error: any) {
      setNotification({
        show: true,
        type: 'error',
        message: error?.message || "Impossible d'ouvrir la pièce jointe.",
      })
    }
  }

  const canCreate = hasPermission('requisitions')

  if (loading || permissionsLoading) {
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
          <button
            onClick={() => navigate('/remboursement-transport?new=1')}
            className={styles.primaryBtn}
          >
            + Nouveau remboursement
          </button>
        )}
      </div>

      {showForm && (
        <section className={styles.workspace}>
          <div className={styles.workspaceHeader}>
            <div>
              <h2>Nouvelle demande de remboursement</h2>
              <p>Formulaire structuré et aperçu temps réel du document officiel.</p>
            </div>
            <button
              onClick={() => {
                clearNewParam()
                setShowForm(false)
                resetForm()
              }}
              className={styles.closeBtn}
            >
              ×
            </button>
          </div>

          <div className={styles.workspaceGrid}>
            <div className={styles.workspaceFormCard}>
              <form onSubmit={handleSubmit}>
                <div className={styles.formSection}>
                  <h3>Informations générales</h3>
                  <div className={styles.formGrid}>
                    <div className={styles.formGroup}>
                      <label>Service / Commission *</label>
                      {isServiceLockedByContext ? (
                        <>
                          <input type="hidden" value={formData.service_id} />
                          <div className={styles.readonlyField}>{serviceLabel || 'Service assigné'}</div>
                        </>
                      ) : (
                        <select
                          value={formData.service_id}
                          onChange={(e) => setFormData({ ...formData, service_id: e.target.value, budget_poste_id: '' })}
                          required
                        >
                          <option value="">Sélectionner un service...</option>
                          {selectableServices.map((service) => (
                            <option key={service.id} value={service.id}>
                              {service.code} - {service.libelle}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>

                    <div className={styles.formGroup}>
                      <label>Poste budgétaire *</label>
                      <select
                        value={formData.budget_poste_id}
                        onChange={(e) => setFormData({ ...formData, budget_poste_id: e.target.value })}
                        required
                      >
                        <option value="">Sélectionner un poste...</option>
                        {rubriques.map((rubrique) => (
                          <option key={rubrique.id} value={rubrique.id}>
                            {rubrique.code} - {rubrique.libelle}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className={styles.formGroup}>
                      <label>Instance *</label>
                      <input
                        type="text"
                        value={formData.instance}
                        readOnly
                        required
                      />
                    </div>

                    <div className={styles.formGroup}>
                      <label>Type de réunion *</label>
                      <select
                        value={formData.type_reunion}
                        onChange={(e) => setFormData({ ...formData, type_reunion: e.target.value as any })}
                        required
                      >
                        <option value="bureau">Réunion du Bureau</option>
                        <option value="commission">Réunion de la Commission permanente</option>
                        <option value="commission_ad_hoc">Réunion de la Commission ad hoc</option>
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
                  <h3>Participants (Experts comptables)</h3>
                  <div className={styles.tableContainer}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th style={{ width: '40px' }}>N°</th>
                          <th>Nom du participant *</th>
                          <th>Qualité / Titre / Fonction *</th>
                          <th>Montant (USD) *</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {participants.map((p, index) => (
                          <tr key={index}>
                            <td style={{ textAlign: 'center', verticalAlign: 'middle', fontWeight: 600 }}>{index + 1}</td>
                            <td className={styles.dropdownCell} style={{position: 'relative'}}>
                              <input
                                type="text"
                                value={p.nom}
                                onChange={(e) => {
                                  updateParticipant(index, 'nom', e.target.value)
                                  setShowExpertSearch(index)
                                  queueExpertSearch(e.target.value)
                                }}
                                onFocus={() => {
                                  setShowExpertSearch(index)
                                  queueExpertSearch(p.nom)
                                }}
                                placeholder="Rechercher un expert-comptable (nom ou N° ordre)..."
                                required
                                autoComplete="off"
                              />
                              {showExpertSearch === index && p.nom.trim() &&
                                renderExpertDropdown(p.nom, (expert) => selectExpert(index, expert))}
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
                            <th style={{ width: '40px' }}>N°</th>
                            <th>Nom</th>
                            <th>Fonction</th>
                            <th>Montant (USD)</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {assistants.length === 0 ? (
                            <tr>
                              <td colSpan={5} style={{textAlign: 'center', color: '#9ca3af'}}>
                                Aucun assistant administratif
                              </td>
                            </tr>
                          ) : (
                            assistants.map((a, index) => (
                              <tr key={index}>
                                <td style={{ textAlign: 'center', verticalAlign: 'middle', fontWeight: 600 }}>{index + 1}</td>
                                <td className={styles.dropdownCell} style={{position: 'relative'}}>
                                  <input
                                    type="text"
                                    value={a.nom}
                                    onChange={(e) => {
                                      updateAssistant(index, 'nom', e.target.value)
                                      setShowAssistantExpertSearch(index)
                                      queueExpertSearch(e.target.value)
                                    }}
                                    onFocus={() => {
                                      setShowAssistantExpertSearch(index)
                                      queueExpertSearch(a.nom)
                                    }}
                                    placeholder="Rechercher un expert-comptable (nom ou N° ordre)..."
                                    autoComplete="off"
                                  />
                                  {showAssistantExpertSearch === index && a.nom.trim() &&
                                    renderExpertDropdown(a.nom, (expert) => selectAssistantExpert(index, expert))}
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
                <button
                  type="button"
                  onClick={() => {
                    clearNewParam()
                    setShowForm(false)
                    resetForm()
                  }}
                  className={styles.secondaryBtn}
                  disabled={submitting}
                >
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                  {submitting ? 'Création en cours...' : 'Créer le remboursement'}
                </button>
              </div>
            </form>
          </div>

          <div className={styles.workspacePreviewCard}>
            <div className={styles.previewLabel}>Aperçu du document</div>
            <div className={styles.previewSheet}>
              <div className={styles.previewStatusBadge}>Brouillon</div>

              <div className={styles.previewHeader}>
                <div className={styles.previewHeaderLeft}>
                  <div className={styles.previewOrg}>ONEC / CPK</div>
                  <div className={styles.previewSubtitle}>Conseil Provincial de Kinshasa</div>
                  <div className={styles.previewMeta}>{serviceLabel || 'Commission / service'}</div>
                </div>
                <div className={styles.previewHeaderRight}>
                  <div className={styles.previewTitle}>État de frais de déplacement</div>
                  <div className={styles.previewDocRef}>ÉTAT DE FRAIS N° : À générer</div>
                  <div className={styles.previewMetaRight}>
                    <div>Réf: {String(formData.type_reunion || '').toUpperCase()}</div>
                    <div>{format(new Date(formData.date_reunion), 'dd/MM/yyyy')}</div>
                  </div>
                </div>
              </div>

              <div className={styles.previewSeparator} />

              <div className={styles.previewInfoGrid}>
                <div className={styles.previewInfoCol}>
                  <div className={styles.previewInfoItem}>
                    <span>Instance</span>
                    <strong>{formData.instance}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Type de réunion</span>
                    <strong>{getTypeReunionLabel(formData.type_reunion)}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Nature</span>
                    <strong>{formData.nature_reunion || '—'}</strong>
                  </div>
                </div>
                <div className={styles.previewInfoCol}>
                  <div className={styles.previewInfoItem}>
                    <span>Lieu</span>
                    <strong>{formData.lieu || '—'}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Date</span>
                    <strong>{format(new Date(formData.date_reunion), 'dd/MM/yyyy')}</strong>
                  </div>
                  <div className={styles.previewInfoItem}>
                    <span>Heure</span>
                    <strong>
                      {formData.heure_debut || '—'} {formData.heure_fin ? `→ ${formData.heure_fin}` : ''}
                    </strong>
                  </div>
                </div>
              </div>

              <div className={styles.previewBlock}>
                <div className={styles.previewBlockTitle}>Participants & Montants</div>
                {previewParticipants.length === 0 ? (
                  <div className={styles.previewEmpty}>Ajoutez des participants pour alimenter l'aperçu.</div>
                ) : (
                  <table className={styles.previewTable}>
                    <thead>
                      <tr>
                        <th style={{ width: '30px' }}>N°</th>
                        <th>Nom & Postnom</th>
                        <th>Fonction</th>
                        <th>Montant</th>
                        <th>Émargement</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewParticipants.map((p, idx) => (
                        <tr key={`${p.nom}-${idx}`}>
                          <td style={{ textAlign: 'center' }}>{idx + 1}</td>
                          <td>{p.nom || '—'}</td>
                          <td>{p.titre_fonction || '—'}</td>
                          <td>{formatCurrency(p.montant)}</td>
                          <td>________________</td>
                        </tr>
                      ))}
                    </tbody>                  </table>
                )}
              </div>

              <div className={styles.previewFooter}>
                <div className={styles.previewAmountBox}>
                  <div>
                    <span>Montant total</span>
                    <strong>{formatCurrency(previewTotal)}</strong>
                  </div>
                  <div className={styles.previewAmountLetters}>Somme en lettres : {previewMontantLettres}</div>
                </div>
                <div className={styles.previewSignatures}>
                  <div className={styles.previewSignatureBox}>Signature du demandeur</div>
                  <div className={styles.previewSignatureBox}>Visa Trésorerie</div>
                  <div className={styles.previewSignatureBox}>Bénéficiaire</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
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
              <option value="BROUILLON">Brouillon</option>
              <option value="SIGNEE_SERVICE">Signé service</option>
              <option value="EN_ATTENTE">En attente validation 1/2</option>
              <option value="AUTORISEE">Validation 1/2</option>
              <option value="APPROUVEE">Validation 2/2</option>
              <option value="PAYEE">Payée</option>
              <option value="REJETEE">Rejetée</option>
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label>Commission / service</label>
            <select
              value={filterServiceId}
              onChange={(e) => setFilterServiceId(e.target.value)}
              disabled={Boolean(serviceContextId)}
            >
              <option value="">Toutes les commissions</option>
              {selectableServices.map((service) => (
                <option key={service.id} value={String(service.id)}>
                  {service.code} - {service.libelle}
                </option>
              ))}
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
          {(searchQuery || filterStatut || filterServiceId || dateDebut || dateFin) && (
            <button
              onClick={() => {
                setSearchQuery('')
                setFilterStatut('')
                setFilterServiceId(serviceContextId || '')
                setDateDebut(TODAY)
                setDateFin(TODAY)
              }}
              style={{padding: '10px 20px', background: '#f3f4f6', color: '#374151', border: 'none', borderRadius: '6px', cursor: 'pointer'}}
            >
              Réinitialiser
            </button>
          )}
        </div>
      </div>

      {selectedRemboursementIds.length > 0 && (
        <div className={styles.groupingBar}>
          <div className={styles.groupingCount}>
            {selectedRemboursementIds.length} remboursement{selectedRemboursementIds.length > 1 ? 's' : ''} sélectionné
            {selectedRemboursementIds.length > 1 ? 's' : ''}
          </div>
          <div className={styles.groupingActions}>
            {canCreateDossier && (
              <button type="button" className={styles.groupingPrimary} onClick={handleCreateDossier}>
                Créer un dossier
              </button>
            )}
            {canAddToDraftDossier && (
              <div className={styles.groupingSelectWrap}>
                <select
                  className={styles.groupingSelect}
                  value={selectedDraftDossierId}
                  onChange={(e) => setSelectedDraftDossierId(e.target.value)}
                >
                  <option value="">Ajouter à un dossier...</option>
                  {draftDossiers.map((dossier) => (
                    <option key={dossier.id} value={dossier.id}>
                      {dossier.reference}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={styles.groupingPrimary}
                  onClick={handleAddToDraftDossier}
                  disabled={!selectedDraftDossierId}
                >
                  Ajouter au dossier
                </button>
              </div>
            )}
            {canSubmitDossier && selectedDossierId && (
              <button
                type="button"
                className={styles.groupingPrimary}
                onClick={() => handleSubmitDossier(selectedDossierId)}
              >
                Soumettre le dossier à l'examen
              </button>
            )}
            {hasMixedDossierSelection && (
              <div className={styles.groupingHint}>
                Sélection incompatible : choisissez des remboursements sans dossier ou du même dossier brouillon.
              </div>
            )}
            <button type="button" className={styles.groupingSecondary} onClick={clearSelection}>
              Annuler
            </button>
          </div>
        </div>
      )}

      <div className={`${styles.tableContainer} ${styles.listTableContainer}`}>
        <table className={`${styles.table} ${styles.listTable}`}>
          <thead>
            <tr>
              <th className={styles.selectColumn}>
                <input
                  type="checkbox"
                  checked={allSelectableFilteredSelected}
                  onChange={toggleSelectVisible}
                  disabled={selectableFilteredIds.length === 0}
                  aria-label="Sélectionner les remboursements visibles"
                />
              </th>
              <th>N° Remboursement</th>
              <th>Date réunion</th>
              <th>Commission</th>
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
                <td colSpan={9} className={styles.empty}>
                  Aucun remboursement trouvé
                </td>
              </tr>
            ) : (
              filteredRemboursements.map((r) => {
                const requisition = (r as any).requisition
                return (
                  <tr key={r.id}>
                    <td className={styles.selectColumn}>
                      <input
                        type="checkbox"
                        checked={selectedRemboursementIds.includes(r.id)}
                        onChange={() => toggleSelectRemboursement(r.id)}
                        disabled={!canSelectForDossier(r)}
                        aria-label={`Sélectionner ${r.numero_remboursement}`}
                      />
                    </td>
                    <td>
                      <div>
                        <strong>{r.numero_remboursement}</strong>
                      </div>
                    </td>
                    <td>{format(new Date(r.date_reunion), 'dd/MM/yyyy')}</td>
                    <td>{getServiceLabel(getRemboursementServiceId(r))}</td>
                    <td>{r.nature_reunion}</td>
                    <td>{r.lieu}</td>
                    <td><strong>{formatCurrency(r.montant_total)}</strong></td>
                    <td>{requisition ? getStatutBadge(getRemboursementStatus(r)) : getStatutBadge('EN_ATTENTE_COMMISSION')}</td>
                    <td>
                      <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
                        <button
                          onClick={() => viewDetails(r)}
                          className={`${styles.actionBtn} ${styles.actionIconBtn}`}
                          style={{background: '#0d9488', color: 'white'}}
                          title="Voir les détails du remboursement"
                          aria-label="Voir les détails du remboursement"
                        >
                          🔍
                        </button>
                        {requisition?.annexe?.id && (
                          <button
                            type="button"
                            onClick={() => openRequisitionAnnexe(requisition.annexe)}
                            className={`${styles.actionBtn} ${styles.actionIconBtn}`}

                            style={{background: '#7c3aed', color: 'white'}}
                            title={requisition.annexe?.filename || 'Voir la pièce jointe'}
                            aria-label="Voir la pièce jointe"
                          >
                            📎
                          </button>
                        )}
                        <select
                          className={styles.formatSelect}
                          value={printFormat}
                          onChange={(e) => setPrintFormat(e.target.value as 'a4' | 'a5')}
                          title="Format d'impression"
                        >
                          <option value="a4">A4</option>
                          <option value="a5">A5</option>
                        </select>
                        <button
                          onClick={() => printRemboursement(r)}
                          className={`${styles.actionBtn} ${styles.actionIconBtn}`}
                          style={{background: '#2563eb', color: 'white'}}
                          title="Imprimer le remboursement"
                          aria-label="Imprimer le remboursement"
                        >
                          🖨️
                        </button>
                        {canSignRequisition(r) && (
                          <button
                            type="button"
                            onClick={() => handleSignRequisition(r)}
                            className={`${styles.actionBtn} ${styles.workflowBtn}`}
                            disabled={signingId === String(requisition?.id || r.requisition_id)}
                            title="Valider et signer le remboursement"
                            aria-label="Valider et signer le remboursement"
                          >
                            {signingId === String(requisition?.id || r.requisition_id) ? 'Signature...' : 'Signer'}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleSubmitExamen(r)}
                          className={`${styles.actionBtn} ${styles.submitExamenBtn}`}
                          disabled={
                            !canSubmitToExamen(r) ||
                            submittingExamenId === String(requisition?.id || r.requisition_id)
                          }
                          title={canSubmitToExamen(r) ? "Soumettre à l'examen" : getSubmitExamenLabel(r)}
                          aria-label="Soumettre à l'examen"
                        >
                          {submittingExamenId === String(requisition?.id || r.requisition_id)
                            ? 'Envoi...'
                            : getSubmitExamenLabel(r)}
                        </button>
                        {canDeleteRemboursement(r) && (
                          <button
                            type="button"
                            onClick={() => handleDeleteRemboursement(r)}
                            className={styles.actionBtn}
                            style={{ background: '#fee2e2', color: '#b91c1c', border: '1px solid #fca5a5' }}
                            title="Supprimer le remboursement"
                            aria-label="Supprimer le remboursement"
                          >
                            Supprimer
                          </button>
                        )}
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
              <div className={`${styles.detailSection} ${styles.detailSectionAccent}`}>
                <h3 className={styles.detailSectionAccentTitle}>Traçabilité et Responsabilité</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Demandeur</label>
                    <p><strong>{selectedRemboursementUsers.demandeur ? `${selectedRemboursementUsers.demandeur.prenom} ${selectedRemboursementUsers.demandeur.nom}` : 'Non disponible'}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Date de la demande</label>
                    <p>{format(new Date((selectedRemboursementDetails as any).requisition?.created_at ?? selectedRemboursementDetails.created_at), 'dd/MM/yyyy à HH:mm')}</p>
                  </div>
                  {((selectedRemboursementDetails as any).requisition?.validee_par || (selectedRemboursementDetails as any).requisition?.approuvee_par) && (
                    <>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Validation technique</label>
                        <p><strong>
                          {selectedRemboursementUsers.validateur
                            ? `${selectedRemboursementUsers.validateur.prenom} ${selectedRemboursementUsers.validateur.nom}`
                            : 'Non disponible'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Date d'autorisation</label>
                        <p>
                          {(selectedRemboursementDetails as any).requisition?.validee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.validee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Visa Trésorerie</label>
                        <p><strong>
                          {selectedRemboursementUsers.approbateur
                            ? `${selectedRemboursementUsers.approbateur.prenom} ${selectedRemboursementUsers.approbateur.nom}`
                            : 'En attente'}
                        </strong></p>
                      </div>
                      <div className={styles.detailItem}>
                        <label className={styles.detailLabelAccent}>Date de visa</label>
                        <p>
                          {(selectedRemboursementDetails as any).requisition?.approuvee_le
                            ? format(new Date((selectedRemboursementDetails as any).requisition.approuvee_le), 'dd/MM/yyyy à HH:mm')
                            : 'En attente'}
                        </p>
                      </div>
                    </>
                  )}
                  <div className={styles.detailItem}>
                    <label className={styles.detailLabelAccent}>Statut actuel</label>
                    <p>{(selectedRemboursementDetails as any).requisition ? getStatutBadge((selectedRemboursementDetails as any).requisition.statut) : getStatutBadge('EN_ATTENTE_COMMISSION')}</p>
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
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></p>
                  </div>
                  {(selectedRemboursementDetails as any).requisition?.annexe?.id && (
                    <div className={styles.detailItem}>
                      <label>Pièce jointe</label>
                      <button
                        type="button"
                        className={styles.actionBtn}
                        onClick={() => openRequisitionAnnexe((selectedRemboursementDetails as any).requisition?.annexe)}
                      >
                        📎 Voir la pièce jointe
                      </button>
                    </div>
                  )}                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Repères budgétaires</h3>
                <div className={styles.detailGrid}>
                  <div className={styles.detailItem}>
                    <label>Budget</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{renderBudgetMetric(selectedBudgetMetrics?.budget)}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Engagé</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{renderBudgetMetric(selectedBudgetMetrics?.engaged)}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Disponible</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{renderBudgetMetric(selectedBudgetMetrics?.available)}</strong></p>
                  </div>
                  <div className={styles.detailItem}>
                    <label>Solde après cette demande</label>
                    <p><strong style={{fontSize: '18px', color: '#0d9488'}}>{renderBudgetMetric(selectedBudgetMetrics?.remainingAfterRequest)}</strong></p>
                  </div>
                </div>
              </div>

              <div className={styles.detailSection}>
                <h3>Participants</h3>
                <table className={styles.detailTable}>
                  <thead>
                    <tr>
                      <th style={{ width: '40px' }}>N°</th>
                      <th>Nom</th>
                      <th>Titre/Fonction</th>
                      <th>Type</th>
                      <th>Montant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedParticipants.map((participant, index) => (
                      <tr key={participant.id}>
                        <td style={{ textAlign: 'center', fontWeight: 600 }}>{index + 1}</td>
                        <td>{participant.nom}</td>
                        <td>{participant.titre_fonction}</td>
                        <td>
                          <span
                            className={`${styles.participantBadge} ${
                              participant.type_participant === 'principal'
                                ? styles.participantBadgePrimary
                                : styles.participantBadgeAssistant
                            }`}
                          >
                            {participant.type_participant === 'principal' ? 'Principal' : 'Assistant'}
                          </span>
                        </td>
                        <td><strong>{formatCurrency(participant.montant)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={3} style={{textAlign: 'right', fontWeight: 600}}>Total général:</td>
                      <td><strong style={{fontSize: '16px', color: '#0d9488'}}>{formatCurrency(selectedRemboursementDetails.montant_total)}</strong></td>
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
