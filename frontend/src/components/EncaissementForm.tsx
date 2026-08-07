import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { format } from 'date-fns'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, ModePaiement, TypeClient, Service } from '../types'
import { toNumber } from '../utils/amount'
import { TYPE_CLIENT_LABELS } from '../utils/encaissementHelpers'
import type { ProjetActivite } from '../api/projetsActivites'
import { uploadEncaissementPiece } from '../api/encaissementPieces'
import styles from '../pages/Encaissements.module.css'

interface EncaissementFormProps {
  user: any
  services: Service[]
  projetsActivites: ProjetActivite[]
  comptesBancaires: any[]
  isCashClosed: boolean
  tauxChange: number
  libellePresets: string[]
  budgetTree: any[]
  onClose: () => void
  onSuccess: (message: string, details?: string) => void
  onError: (title: string, message: string, details?: string) => void
  onProformaCreated: (numero: string, montant: number) => void
  loadData: () => Promise<void>
  loadBudgetLines: (serviceId: number | null) => Promise<void>
  variant?: 'modal' | 'page'
  formId?: string
}

const roundMoney = (value: number): number => {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

const formatCurrency = (amount: string | number | null | undefined) => {
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(amount))
}

const normalizeDecimalInput = (value: string) => {
  const normalized = value.replace(/,/g, '.').replace(/[^\d.]/g, '')
  const [integerPart, ...decimalParts] = normalized.split('.')
  return decimalParts.length === 0 ? integerPart : `${integerPart}.${decimalParts.join('')}`
}

type ArticleDraft = {
  libelle: string
  quantite: string
  prix_unitaire: string
}

export default function EncaissementForm({
  user,
  services,
  projetsActivites,
  comptesBancaires,
  isCashClosed,
  tauxChange,
  libellePresets,
  budgetTree,
  onClose,
  onSuccess,
  onError,
  onProformaCreated,
  loadData,
  loadBudgetLines,
  variant = 'modal',
  formId = 'encaissement-form',
}: EncaissementFormProps) {
  const [formData, setFormData] = useState({
    type_client: 'expert_comptable' as TypeClient,
    expert_comptable_id: '',
    client_nom: '',
    libelle: '',
    description: '',
    devise_perception: 'USD',
    montant: '',
    montant_paye: '',
    canal: 'CAISSE' as 'CAISSE' | 'BANQUE',
    compte_bancaire_id: '',
    mode_paiement: 'cash' as ModePaiement,
    reference: '',
    notes_paiement: '',
    date_encaissement: format(new Date(), 'yyyy-MM-dd'),
    budget_poste_id: '',
    service_id: '',
    project_activity_id: '',
  })
  const [articles, setArticles] = useState<ArticleDraft[]>([
    { libelle: '', quantite: '1', prix_unitaire: '' },
  ])

  const [searchEC, setSearchEC] = useState('')
  const [filteredExperts, setFilteredExperts] = useState<ExpertComptable[]>([])
  const [isSearchingExperts, setIsSearchingExperts] = useState(false)
  // Référentiel clients (anti-doublons) : suggestions pendant la saisie du nom.
  const [clientId, setClientId] = useState('')
  const [clientEmail, setClientEmail] = useState('')
  const [clientTelephone, setClientTelephone] = useState('')
  const [clientSuggestions, setClientSuggestions] = useState<any[]>([])
  const [isSearchingClients, setIsSearchingClients] = useState(false)
  const [showClientDropdown, setShowClientDropdown] = useState(false)
  const [activeSubmitAction, setActiveSubmitAction] = useState<'submit' | 'proforma' | null>(null)
  const [budgetSearch, setBudgetSearch] = useState('')
  const [showBudgetDropdown, setShowBudgetDropdown] = useState(false)
  const [expandedBudgetIds, setExpandedBudgetIds] = useState<Set<number>>(() => new Set())
  const [filteredComptes, setFilteredComptes] = useState<any[]>([])
  const [selectedExpert, setSelectedExpert] = useState<ExpertComptable | null>(null)
  const [justificatifs, setJustificatifs] = useState<File[]>([])
  const submitLockRef = useRef(false)
  const isPage = variant === 'page'

  const userServiceIds = useMemo(() => {
    if (user?.service_ids && user.service_ids.length > 0) {
      return user.service_ids.map((id: string | number) => Number(id)).filter(Number.isFinite)
    }
    if (user?.service_id) return [Number(user.service_id)].filter(Number.isFinite)
    return []
  }, [user?.service_ids, user?.service_id])

  const isServiceUser = useMemo(() => {
    return userServiceIds.length > 0 && user?.role !== 'admin' && user?.role !== 'super_admin'
  }, [userServiceIds, user?.role])

  const mustSelectService = useMemo(() => {
    return user?.role !== 'admin' && user?.role !== 'super_admin' && services.length > 0
  }, [user?.role, services.length])

  const articleRows = useMemo(() => {
    return articles.map((article) => {
      const quantite = toNumber(article.quantite || 0)
      const prixUnitaire = toNumber(article.prix_unitaire || 0)
      return {
        ...article,
        quantite,
        prixUnitaire,
        montant: roundMoney(quantite * prixUnitaire),
      }
    })
  }, [articles])

  const montantTotalArticles = useMemo(() => {
    return roundMoney(articleRows.reduce((total, article) => total + article.montant, 0))
  }, [articleRows])

  const validArticleRows = useMemo(() => {
    return articleRows.filter((article) => article.libelle.trim() && article.quantite > 0 && article.prixUnitaire >= 0)
  }, [articleRows])

  const getMontantPayeUSD = useCallback(() => {
    const raw = toNumber(formData.montant_paye || 0)
    if (formData.devise_perception === 'CDF') {
      return tauxChange > 0 ? raw / tauxChange : 0
    }
    return raw
  }, [formData.montant_paye, formData.devise_perception, tauxChange])

  useEffect(() => {
    if (isCashClosed && formData.canal === 'CAISSE') {
      setFormData((prev) => ({
        ...prev,
        canal: 'BANQUE',
        mode_paiement: 'virement',
        reference: prev.reference || '',
      }))
    }
  }, [isCashClosed, formData.canal])

  useEffect(() => {
    if (formData.canal === 'BANQUE' && formData.mode_paiement === 'cash') {
      setFormData((prev) => ({ ...prev, mode_paiement: 'virement', reference: prev.reference || '' }))
    }
    if (formData.canal === 'CAISSE' && formData.mode_paiement !== 'cash') {
      setFormData((prev) => ({ ...prev, mode_paiement: 'cash', reference: '' }))
    }
  }, [formData.canal, formData.mode_paiement])

  useEffect(() => {
    const devise = formData.devise_perception || 'USD'
    const next = formData.canal === 'BANQUE'
      ? comptesBancaires.filter(
          (compte) =>
            String(compte.devise || '').toUpperCase() === devise &&
            String(compte.account_type || 'BANK').toUpperCase() === 'BANK'
        )
      : []
    setFilteredComptes(next)

    setFormData((prev) => {
      const selectedStillAvailable = next.some((c) => String(c.id) === String(prev.compte_bancaire_id))
      const nextCompteId = formData.canal === 'CAISSE'
        ? ''
        : selectedStillAvailable
          ? prev.compte_bancaire_id
          : next.length > 0
            ? String(next[0].id)
            : ''
      return prev.compte_bancaire_id === nextCompteId
        ? prev
        : { ...prev, compte_bancaire_id: nextCompteId }
    })
  }, [formData.devise_perception, formData.canal, formData.compte_bancaire_id, comptesBancaires])

  useEffect(() => {
    if (isServiceUser && userServiceIds.length === 1 && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: String(userServiceIds[0]) }))
    }
  }, [isServiceUser, userServiceIds, formData.service_id])

  useEffect(() => {
    if (mustSelectService && services.length === 1 && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: String(services[0].id) }))
    }
  }, [mustSelectService, services, formData.service_id])

  useEffect(() => {
    const serviceId = formData.service_id ? Number(formData.service_id) : null
    loadBudgetLines(Number.isFinite(serviceId as number) ? serviceId : null)
  }, [formData.service_id, loadBudgetLines])

  useEffect(() => {
    if (!searchEC) {
      setFilteredExperts([])
      return
    }
    const timer = window.setTimeout(async () => {
      try {
        setIsSearchingExperts(true)
        const res = await apiRequest<ExpertComptable[]>('GET', `/experts-comptables?q=${searchEC.trim()}&active=true&limit=20`)
        setFilteredExperts(Array.isArray(res) ? res : [])
      } catch (error) {
        console.error('Error searching experts:', error)
        setFilteredExperts([])
      } finally {
        setIsSearchingExperts(false)
      }
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchEC])

  const selectExpert = (expert: ExpertComptable) => {
    setFormData((prev) => ({ ...prev, expert_comptable_id: expert.id, client_nom: '' }))
    setSearchEC(`${expert.numero_ordre} - ${expert.nom_denomination}`)
    setSelectedExpert(expert)
    setFilteredExperts([])
  }

  // Recherche de clients existants pendant la saisie (anti-doublons) :
  // un client revenu après des mois est proposé au lieu d'être recréé.
  useEffect(() => {
    if (formData.type_client === 'expert_comptable') return
    const term = formData.client_nom.trim()
    if (clientId || term.length < 2) {
      setClientSuggestions([])
      return
    }
    const timer = window.setTimeout(async () => {
      try {
        setIsSearchingClients(true)
        const res = await apiRequest<any[]>('GET', '/clients', { params: { search: term, limit: 8, active: true } })
        setClientSuggestions(Array.isArray(res) ? res : [])
        setShowClientDropdown(true)
      } catch (error) {
        console.error('Error searching clients:', error)
        setClientSuggestions([])
      } finally {
        setIsSearchingClients(false)
      }
    }, 300)
    return () => window.clearTimeout(timer)
  }, [formData.client_nom, formData.type_client, clientId])

  const selectClient = (c: any) => {
    setClientId(String(c.id))
    setFormData((prev) => ({
      ...prev,
      client_nom: c.nom,
      // Reprendre automatiquement le type défini du client sélectionné dans le
      // référentiel (hors expert_comptable, géré via son propre sélecteur). Si
      // le client n'a pas de type enregistré, on conserve le type courant.
      type_client:
        c.type_client && c.type_client !== 'expert_comptable'
          ? (c.type_client as TypeClient)
          : prev.type_client,
    }))
    setClientEmail(c.email || '')
    setClientTelephone(c.telephone || '')
    setClientSuggestions([])
    setShowClientDropdown(false)
  }

  const resetClientSelection = () => {
    setClientId('')
    setClientEmail('')
    setClientTelephone('')
    setClientSuggestions([])
    setShowClientDropdown(false)
  }

  const filteredBudgetTree = useMemo(() => {
    const query = budgetSearch.trim().toLowerCase()
    if (!query) return budgetTree

    const matches = (node: any) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      const categorie = String(node.categorie || node.category || node.type || '').toLowerCase()
      return code.includes(query) || libelle.includes(query) || categorie.includes(query)
    }

    const filterNodes = (nodes: any[]): any[] => {
      return nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean)
    }
    return filterNodes(budgetTree)
  }, [budgetTree, budgetSearch])

  const selectBudgetPoste = (line: any) => {
    if ((line.children?.length || 0) > 0) return
    setFormData((prev) => ({ ...prev, budget_poste_id: String(line.id) }))
    setBudgetSearch(`${line.code} - ${line.libelle}`)
    setShowBudgetDropdown(false)
  }

  const updateArticle = (index: number, field: keyof ArticleDraft, value: string) => {
    setArticles((prev) => prev.map((article, idx) => (
      idx === index ? { ...article, [field]: value } : article
    )))
  }

  const addArticle = () => {
    setArticles((prev) => [...prev, { libelle: '', quantite: '1', prix_unitaire: '' }])
  }

  const removeArticle = (index: number) => {
    setArticles((prev) => prev.length === 1 ? prev : prev.filter((_, idx) => idx !== index))
  }

  const resetForm = () => {
    setFormData({
      type_client: 'expert_comptable',
      expert_comptable_id: '',
      client_nom: '',
      libelle: '',
      description: '',
      devise_perception: 'USD',
      montant: '',
      montant_paye: '',
      canal: isCashClosed ? 'BANQUE' : 'CAISSE',
      compte_bancaire_id: '',
      mode_paiement: isCashClosed ? 'virement' : 'cash',
      reference: '',
      notes_paiement: '',
      date_encaissement: format(new Date(), 'yyyy-MM-dd'),
      budget_poste_id: '',
      service_id: '',
      project_activity_id: '',
    })
    setArticles([{ libelle: '', quantite: '1', prix_unitaire: '' }])
    setSearchEC('')
    setSelectedExpert(null)
    resetClientSelection()
    setBudgetSearch('')
    setJustificatifs([])
  }

  const handleArticleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>, index: number) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    if (index === articles.length - 1) addArticle()
  }

  const buildArticlePayload = () => {
    return validArticleRows.map((article) => ({
      libelle: article.libelle.trim(),
      quantite: article.quantite,
      prix_unitaire: article.prixUnitaire,
      montant: article.montant,
    }))
  }

  const getMainLibelle = () => {
    const labels = validArticleRows.map((article) => article.libelle.trim())
    const value = labels.length <= 1 ? labels[0] : labels.join(', ')
    return (value || 'Encaissement').slice(0, 255)
  }

  const toggleBudgetNode = (id: number) => {
    setExpandedBudgetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitLockRef.current) return
    if (!validateForm()) return

    try {
      submitLockRef.current = true
      setActiveSubmitAction('submit')
      const devise = formData.devise_perception === 'CDF' ? 'CDF' : 'USD'
      const montantTotal = montantTotalArticles
      const montantPayeInput = roundMoney(parseFloat(formData.montant_paye))
      const montantPaye = devise === 'CDF'
        ? roundMoney(tauxChange > 0 ? montantPayeInput / tauxChange : 0)
        : montantPayeInput
      const montantPercu = montantPayeInput

      const statutPaiement = montantPaye >= montantTotal ? 'complet' : montantPaye > 0 ? 'partiel' : 'non_paye'

      const created = await apiRequest<any>('POST', '/encaissements', {
        type_client: formData.type_client,
        expert_comptable_id: formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        client_id: formData.type_client !== 'expert_comptable' && clientId ? clientId : null,
        client_email: formData.type_client !== 'expert_comptable' ? (clientEmail.trim() || null) : null,
        client_telephone: formData.type_client !== 'expert_comptable' ? (clientTelephone.trim() || null) : null,
        libelle: getMainLibelle(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: montantPaye,
        montant_percu: montantPercu,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: Number(formData.budget_poste_id),
        service_id: formData.service_id ? Number(formData.service_id) : null,
        project_activity_id: formData.project_activity_id ? Number(formData.project_activity_id) : null,
        statut_paiement: statutPaiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        notes_paiement: formData.notes_paiement || null,
        date_encaissement: formData.date_encaissement,
        canal: formData.canal,
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        created_by: user?.id,
        articles: buildArticlePayload(),
      })

      const encCreated = Array.isArray(created) ? created[0] : created
      if (encCreated?.id && justificatifs.length > 0) {
        for (const file of justificatifs) await uploadEncaissementPiece(String(encCreated.id), file)
      }
      onClose()
      await loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))

      const statutMessage = statutPaiement === 'complet' 
        ? 'Payé en totalité' 
        : `Paiement partiel - Reste à payer : ${formatCurrency(montantTotal - montantPaye)}`
      
      onSuccess(
        `La note de débit ${encCreated?.numero_recu || '—'} a été enregistrée.`,
        `Statut : ${statutMessage}\nMontant total : ${formatCurrency(montantTotal)}\nMontant payé : ${formatCurrency(montantPaye)}`
      )
    } catch (error: any) {
      submitLockRef.current = false
      setActiveSubmitAction(null)
      onError('Erreur d\'enregistrement', error?.message || 'Une erreur inconnue est survenue.')
    }
  }

  const handleCreateProforma = async () => {
    if (submitLockRef.current) return
    if (!validateForm(true)) return

    try {
      submitLockRef.current = true
      setActiveSubmitAction('proforma')
      const devise = formData.devise_perception === 'CDF' ? 'CDF' : 'USD'
      const montantTotal = montantTotalArticles

      const created = await apiRequest<any>('POST', '/encaissements/proformas', {
        type_client: formData.type_client,
        expert_comptable_id: formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        client_id: formData.type_client !== 'expert_comptable' && clientId ? clientId : null,
        client_email: formData.type_client !== 'expert_comptable' ? (clientEmail.trim() || null) : null,
        client_telephone: formData.type_client !== 'expert_comptable' ? (clientTelephone.trim() || null) : null,
        libelle: getMainLibelle(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: 0,
        montant_percu: 0,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: Number(formData.budget_poste_id),
        service_id: formData.service_id ? Number(formData.service_id) : null,
        project_activity_id: formData.project_activity_id ? Number(formData.project_activity_id) : null,
        statut_paiement: 'non_paye',
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        notes_paiement: formData.notes_paiement || null,
        date_encaissement: formData.date_encaissement,
        canal: formData.canal,
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        created_by: user?.id,
        articles: buildArticlePayload(),
      })

      const proCreated = Array.isArray(created) ? created[0] : created
      if (proCreated?.id && justificatifs.length > 0) {
        for (const file of justificatifs) await uploadEncaissementPiece(String(proCreated.id), file)
      }
      onClose()
      await loadData()
      onProformaCreated(proCreated?.numero_proforma || '—', montantTotal)
    } catch (error: any) {
      submitLockRef.current = false
      setActiveSubmitAction(null)
      onError('Erreur de création', error?.message || 'Une erreur inconnue est survenue.')
    }
  }

  const validateForm = (isProforma = false) => {
    if (formData.type_client === 'expert_comptable' && !formData.expert_comptable_id) {
      onError('Expert-comptable non sélectionné', 'Veuillez sélectionner un expert-comptable depuis la liste.')
      return false
    }
    if (formData.type_client !== 'expert_comptable' && !formData.client_nom.trim()) {
      onError('Nom du client requis', 'Veuillez saisir le nom complet du client.')
      return false
    }
    if (
      formData.type_client !== 'expert_comptable' &&
      clientEmail.trim() &&
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail.trim())
    ) {
      onError('Email invalide', 'L’adresse email du client n’est pas au bon format (ex : nom@domaine.com).')
      return false
    }
    if (validArticleRows.length === 0) {
      onError('Article requis', 'Veuillez renseigner au moins un article avec une quantité et un prix.')
      return false
    }
    if (validArticleRows.length !== articles.length) {
      onError('Article incomplet', 'Chaque article doit avoir un libellé, une quantité et un prix unitaire.')
      return false
    }
    if (montantTotalArticles <= 0) {
      onError('Montant requis', 'Le total des articles doit être supérieur à zéro.')
      return false
    }
    if (!isProforma && !formData.montant_paye) {
      onError('Montant payé requis', 'Veuillez saisir le montant payé.')
      return false
    }
    if (formData.canal === 'BANQUE' && !formData.compte_bancaire_id) {
      onError('Compte requis', 'Veuillez sélectionner un compte de dépôt.')
      return false
    }
    if (!formData.budget_poste_id) {
      onError('Poste requis', 'Veuillez sélectionner un poste budgétaire.')
      return false
    }
    if (mustSelectService && !formData.service_id) {
      onError('Service requis', 'Veuillez sélectionner la commission concernée.')
      return false
    }
    return true
  }

  const BudgetDropdownNode = ({ node, depth }: { node: any; depth: number }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = budgetSearch.trim().length > 0 || expandedBudgetIds.has(node.id)
    return (
      <>
        <div
          className={`${styles.dropdownItem} ${hasChildren ? styles.parentItem : ''}`}
          style={{ paddingLeft: `${10 + depth * 16}px` }}
          onClick={() => hasChildren ? toggleBudgetNode(node.id) : selectBudgetPoste(node)}
        >
          {hasChildren && <span className={`${styles.treeToggle} ${isExpanded ? styles.treeToggleOpen : ''}`} />}
          <strong>{node.code}</strong> - {node.libelle}
          {hasChildren && <span className={styles.parentBadge}>Parent</span>}
        </div>
        {hasChildren && isExpanded && node.children.map((child: any) => (
          <BudgetDropdownNode key={child.id} node={child} depth={depth + 1} />
        ))}
      </>
    )
  }

  const selectedServiceLabel = useMemo(() => {
    const service = services.find((item) => String(item.id) === String(formData.service_id))
    return service ? `${service.code} - ${service.libelle}` : 'Recette générale'
  }, [services, formData.service_id])

  const selectedProjectActivityLabel = useMemo(() => {
    const item = projetsActivites.find((entry) => String(entry.id) === String(formData.project_activity_id))
    return item ? `${item.code} - ${item.libelle}` : 'Aucun'
  }, [projetsActivites, formData.project_activity_id])

  const selectedCompteLabel = useMemo(() => {
    if (formData.canal === 'CAISSE') return 'Caisse du tenant'
    const compte = comptesBancaires.find((item) => String(item.id) === String(formData.compte_bancaire_id))
    if (!compte) return 'Compte non sélectionné'
    return `${compte.banque?.nom || 'Banque'} - ${compte.intitule} (${compte.devise})`
  }, [comptesBancaires, formData.compte_bancaire_id, formData.canal])

  const montantPayeUSD = getMontantPayeUSD()
  const solde = roundMoney(Math.max(0, montantTotalArticles - montantPayeUSD))
  const expectedStatus = montantPayeUSD >= montantTotalArticles && montantTotalArticles > 0
    ? 'Complet'
    : montantPayeUSD > 0
      ? 'Partiel'
      : 'Non payé'
  const clientSummary = formData.type_client === 'expert_comptable'
    ? selectedExpert?.nom_denomination || searchEC || 'Expert-comptable non sélectionné'
    : formData.client_nom || 'Client non renseigné'
  const modePaiementLabel: Record<ModePaiement, string> = {
    cash: 'Espèces',
    mobile_money: 'Mobile Money',
    virement: 'Virement bancaire',
    card: 'Carte',
    cheque: 'Chèque',
  }
  const referenceLabel = formData.mode_paiement === 'cheque'
    ? 'Numéro du chèque *'
    : formData.mode_paiement === 'mobile_money'
      ? 'Opérateur et référence *'
      : formData.mode_paiement === 'virement'
        ? 'Référence du virement *'
        : 'Référence de paiement'

  return (
    <div className={isPage ? styles.createPageShell : styles.modal}>
      <div className={isPage ? styles.createPageContent : styles.modalContent}>
        {!isPage && (
          <div className={styles.modalHeader}>
            <h2>Nouvel encaissement</h2>
            <button onClick={onClose} className={styles.closeBtn} disabled={activeSubmitAction !== null}>×</button>
          </div>
        )}

        <form id={formId} onSubmit={handleSubmit} className={`${styles.form} ${isPage ? styles.createForm : ''}`} aria-busy={activeSubmitAction !== null}>
          {isPage && (
            <div className={styles.createFormIntro}>
              <div>
                <span className={styles.sectionEyebrow}>Recette</span>
                <h2>Informations principales</h2>
              </div>
              <p>Client, affectation, articles et paiement sont regroupés sur une grille large pour une saisie rapide.</p>
            </div>
          )}
          <div className={isPage ? styles.createLayout : undefined}>
            <div className={isPage ? styles.createMain : undefined}>
          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Client</h4>
          <div className={styles.compactGrid}>
          <div className={styles.field}>
            <label>Type de client *</label>
            <select
              value={formData.type_client}
              onChange={(e) => {
                setFormData(prev => ({
                  ...prev,
                  type_client: e.target.value as TypeClient,
                  expert_comptable_id: '',
                  client_nom: ''
                }))
                setSelectedExpert(null)
                setSearchEC('')
                resetClientSelection()
              }}
            >
              {Object.entries(TYPE_CLIENT_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          {formData.type_client === 'expert_comptable' ? (
            <div className={`${styles.field} ${styles.span2}`}>
              <label>Expert-Comptable *</label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  value={searchEC}
                  onChange={(e) => setSearchEC(e.target.value)}
                  placeholder="Rechercher par numéro d'ordre ou nom"
                  style={{ borderColor: formData.expert_comptable_id ? '#10b981' : undefined }}
                />
                {formData.expert_comptable_id && <span style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: '#10b981', fontWeight: 'bold' }}>✓</span>}
              </div>
              {filteredExperts.length > 0 && (
                <div className={styles.dropdown}>
                  {filteredExperts.map(expert => (
                    <div key={expert.id} onClick={() => selectExpert(expert)} className={styles.dropdownItem}>
                      <strong>{expert.numero_ordre}</strong> - {expert.nom_denomination}
                    </div>
                  ))}
                </div>
              )}
              {isSearchingExperts && <small>Recherche en cours…</small>}
            </div>
          ) : (
            <>
              <div className={`${styles.field} ${styles.span2}`}>
                <label>Nom du client *</label>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    value={formData.client_nom}
                    onChange={(e) => {
                      // Nouvelle saisie : on quitte le client sélectionné.
                      if (clientId) resetClientSelection()
                      setFormData(prev => ({ ...prev, client_nom: e.target.value }))
                    }}
                    onFocus={() => {
                      if (clientSuggestions.length > 0) setShowClientDropdown(true)
                    }}
                    onBlur={() => {
                      window.setTimeout(() => setShowClientDropdown(false), 150)
                    }}
                    placeholder="Tapez le nom : les clients existants seront proposés"
                    style={{ borderColor: clientId ? '#10b981' : undefined }}
                    required
                  />
                  {clientId && (
                    <span style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: '#10b981', fontWeight: 'bold' }}>✓</span>
                  )}
                </div>
                {showClientDropdown && clientSuggestions.length > 0 && (
                  <div className={styles.dropdown} onMouseDown={(e) => e.preventDefault()}>
                    {clientSuggestions.map((c) => (
                      <div key={c.id} onClick={() => selectClient(c)} className={styles.dropdownItem}>
                        <strong>{c.nom}</strong>
                        {(c.email || c.telephone) && (
                          <span style={{ color: '#6b7280', fontSize: '12px' }}>
                            {' '}— {[c.email, c.telephone].filter(Boolean).join(' · ')}
                          </span>
                        )}
                        {typeof c.nb_encaissements === 'number' && c.nb_encaissements > 0 && (
                          <div style={{ fontSize: '11px', color: '#0369a1' }}>
                            {c.nb_encaissements} encaissement{c.nb_encaissements > 1 ? 's' : ''}
                            {c.dernier_encaissement
                              ? ` · dernier le ${format(new Date(c.dernier_encaissement), 'dd/MM/yyyy')}`
                              : ''}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {isSearchingClients && <small>Recherche de clients…</small>}
                {clientId ? (
                  <small style={{ color: '#059669' }}>
                    ✓ Client existant sélectionné — ses informations seront réutilisées (pas de doublon).
                  </small>
                ) : formData.client_nom.trim().length >= 2 && !isSearchingClients && clientSuggestions.length === 0 ? (
                  <small style={{ color: '#92400e' }}>
                    Nouveau client : il sera enregistré dans la base avec ses coordonnées ci-dessous.
                  </small>
                ) : null}
              </div>
                <div className={styles.field}>
                  <label>Email du client</label>
                  <input
                    type="email"
                    value={clientEmail}
                    onChange={(e) => setClientEmail(e.target.value)}
                    placeholder="exemple@domaine.com"
                  />
                </div>
                <div className={styles.field}>
                  <label>Téléphone du client</label>
                  <input
                    type="text"
                    value={clientTelephone}
                    onChange={(e) => setClientTelephone(e.target.value)}
                    placeholder="+243 ..."
                  />
                </div>
            </>
          )}
          </div>
          </div>

          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Affectation comptable</h4>
          <div className={styles.compactGrid}>
            <div className={styles.field}>
              <label>Service / Commission {mustSelectService ? '*' : '(optionnel)'}</label>
              <select
                value={formData.service_id}
                onChange={(e) => {
                  setFormData(prev => ({ ...prev, service_id: e.target.value, budget_poste_id: '' }))
                  setBudgetSearch('')
                }}
                disabled={isServiceUser && userServiceIds.length === 1}
              >
                {!mustSelectService && <option value="">-- Recette générale --</option>}
                {services.filter(s => !isServiceUser || userServiceIds.includes(Number(s.id))).map(s => (
                  <option key={s.id} value={s.id}>{s.code} - {s.libelle}</option>
                ))}
              </select>
            </div>

            <div className={`${styles.field} ${styles.span2}`}>
              <label>Poste budgétaire *</label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  value={budgetSearch}
                  onChange={(e) => {
                    setBudgetSearch(e.target.value)
                    setFormData(prev => ({ ...prev, budget_poste_id: '' }))
                    setShowBudgetDropdown(true)
                  }}
                  onFocus={() => setShowBudgetDropdown(true)}
                  onBlur={() => setTimeout(() => setShowBudgetDropdown(false), 120)}
                  placeholder="Rechercher par code, libellé ou catégorie"
                />
                {showBudgetDropdown && filteredBudgetTree.length > 0 && (
                  <div className={`${styles.dropdown} ${styles.dropdownWide}`} onMouseDown={e => e.preventDefault()}>
                    {filteredBudgetTree.map(node => <BudgetDropdownNode key={node.id} node={node} depth={0} />)}
                  </div>
                )}
              </div>
            </div>

            <div className={styles.field}>
              <label>Compte comptable</label>
              <input type="text" value={budgetSearch || 'Déduit du poste budgétaire'} disabled />
            </div>
            <div className={styles.field}>
              <label>Centre de coût</label>
              <input type="text" value={selectedServiceLabel} disabled />
            </div>
            <div className={styles.field}>
              <label>Projet / Activité</label>
              <select
                value={formData.project_activity_id}
                onChange={e => setFormData(prev => ({ ...prev, project_activity_id: e.target.value }))}
              >
                <option value="">Aucun (facultatif)</option>
                {projetsActivites.map(item => (
                  <option key={item.id} value={item.id}>
                    {item.code} - {item.libelle} ({item.type === 'PROJET' ? 'Projet' : 'Activité'})
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label>Total comptable (USD)</label>
              <input type="text" value={formatCurrency(montantTotalArticles)} disabled />
            </div>
          </div>
          </div>

          <div className={styles.formSection}>
          <div className={styles.articleSection}>
            <div className={styles.articleHeader}>
              <h3>Articles du poste budgétaire</h3>
              <button type="button" onClick={addArticle} className={styles.secondaryBtn}>Ajouter une ligne</button>
            </div>
            <datalist id="encaissement-libelles">
              {libellePresets.map(l => <option key={l} value={l} />)}
            </datalist>
            <div className={styles.articleTableWrap}>
              <table className={styles.articleTable}>
                <thead>
                  <tr>
                    <th>Libellé</th>
                    <th>Quantité</th>
                    <th>Prix unitaire</th>
                    <th>Total</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {articles.map((article, index) => {
                    const row = articleRows[index]
                    return (
                      <tr key={`article-${index}`}>
                        <td>
                      <input
                        type="text"
                        value={article.libelle}
                        onChange={(e) => updateArticle(index, 'libelle', e.target.value)}
                        onKeyDown={(e) => handleArticleKeyDown(e, index)}
                        list="encaissement-libelles"
                        placeholder="Libellé de l'article"
                        required
                      />
                        </td>
                        <td>
                      <input
                        type="text"
                        inputMode="decimal"
                        pattern="[0-9]+(\\.[0-9]+)?"
                        value={article.quantite}
                        onChange={(e) => updateArticle(index, 'quantite', normalizeDecimalInput(e.target.value))}
                        onKeyDown={(e) => handleArticleKeyDown(e, index)}
                        required
                      />
                        </td>
                        <td>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={article.prix_unitaire}
                        onChange={(e) => updateArticle(index, 'prix_unitaire', e.target.value)}
                        onKeyDown={(e) => handleArticleKeyDown(e, index)}
                        required
                      />
                        </td>
                        <td><strong>{formatCurrency(row?.montant || 0)}</strong></td>
                        <td>
                    <button
                      type="button"
                      className={styles.iconBtn}
                      onClick={() => removeArticle(index)}
                      disabled={articles.length === 1}
                      aria-label="Retirer l'article"
                      title="Retirer l'article"
                    >
                      ×
                    </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3}>Total général</td>
                    <td>{formatCurrency(montantTotalArticles)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
          </div>

          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Paiement</h4>
          <div className={styles.compactGrid}>
            <div className={styles.field}>
              <label>Montant total</label>
              <input type="text" value={formatCurrency(montantTotalArticles)} disabled />
            </div>
            <div className={styles.field}>
              <label>Devise de perception *</label>
              <select
                value={formData.devise_perception}
                onChange={(e) => setFormData(prev => ({ ...prev, devise_perception: e.target.value }))}
              >
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>{formData.canal === 'CAISSE' ? 'Caisse' : 'Banque'} *</label>
              <select
                value={formData.canal}
                onChange={(e) => {
                  const nextCanal = e.target.value as 'CAISSE' | 'BANQUE'
                  setFormData(prev => ({
                    ...prev,
                    canal: nextCanal,
                    mode_paiement: nextCanal === 'CAISSE' ? 'cash' : prev.mode_paiement === 'cash' ? 'virement' : prev.mode_paiement,
                    reference: nextCanal === 'CAISSE' ? '' : prev.reference,
                  }))
                }}
              >
                <option value="CAISSE" disabled={isCashClosed}>Caisse</option>
                <option value="BANQUE">Banque</option>
              </select>
              {isCashClosed && <small className={styles.warningText}>Caisse fermée : encaissement en caisse indisponible.</small>}
            </div>
            {formData.canal === 'BANQUE' ? (
              <div className={styles.field}>
                <label>Compte bancaire *</label>
                <select
                  value={formData.compte_bancaire_id}
                  onChange={(e) => setFormData(prev => ({ ...prev, compte_bancaire_id: e.target.value }))}
                  required
                >
                  <option value="">Sélectionner un compte</option>
                  {filteredComptes.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.banque?.nom || 'Banque'} - {c.intitule} ({c.devise})
                    </option>
                  ))}
                </select>
                {filteredComptes.length === 0 && <small className={styles.warningText}>Aucun compte bancaire disponible pour cette devise.</small>}
              </div>
            ) : (
              <div className={styles.field}>
                <label>Caisse</label>
                <input type="text" value="Caisse du tenant" disabled />
                {isCashClosed && <small className={styles.warningText}>Caisse fermée : encaissement en caisse indisponible.</small>}
              </div>
            )}
            <div className={styles.field}>
              <label>Montant payé ({formData.devise_perception}) *</label>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                value={formData.montant_paye}
                onChange={e => setFormData(prev => ({ ...prev, montant_paye: e.target.value }))}
                required
              />
            </div>
            <div className={styles.field}>
              <label>Mode de paiement *</label>
              <select
                value={formData.mode_paiement}
                onChange={e => {
                  const nextMode = e.target.value as ModePaiement
                  setFormData(prev => ({
                    ...prev,
                    mode_paiement: nextMode,
                    canal: nextMode === 'cash' && !isCashClosed ? 'CAISSE' : 'BANQUE',
                    reference: nextMode === 'cash' ? '' : prev.reference,
                  }))
                }}
              >
                {formData.canal === 'CAISSE' ? (
                  <option value="cash" disabled={isCashClosed}>Espèces</option>
                ) : (
                  <>
                    <option value="mobile_money">Mobile Money</option>
                    <option value="card">Carte</option>
                    <option value="virement">Virement</option>
                    <option value="cheque">Chèque</option>
                  </>
                )}
              </select>
            </div>
            {formData.mode_paiement !== 'cash' && (
              <div className={styles.field}>
                <label>{referenceLabel}</label>
                <input
                  type="text"
                  value={formData.reference}
                  onChange={e => setFormData(prev => ({ ...prev, reference: e.target.value }))}
                  placeholder={formData.mode_paiement === 'cheque' ? 'N° chèque' : 'Référence'}
                />
              </div>
            )}
            <div className={styles.field}>
              <label>Date d’encaissement *</label>
              <input
                type="date"
                value={formData.date_encaissement}
                onChange={e => setFormData(prev => ({ ...prev, date_encaissement: e.target.value }))}
                required
              />
            </div>
            <div className={`${styles.field} ${styles.span2}`}>
              <label>Description</label>
              <textarea value={formData.description} onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))} rows={2} />
            </div>
            <div className={styles.field}>
              <label>Notes de paiement</label>
              <textarea value={formData.notes_paiement} onChange={e => setFormData(prev => ({ ...prev, notes_paiement: e.target.value }))} rows={2} />
            </div>
          </div>
          </div>

          <div className={styles.formSection}>
            <h4 className={styles.formSectionTitle}>Pièces justificatives</h4>
            <label className={styles.fileDropZone}>
              <input
                type="file"
                multiple
                onChange={(event) => setJustificatifs(Array.from(event.target.files || []))}
              />
              <span>Déposer ou sélectionner des fichiers</span>
              <small>Facture, bordereau, preuve de virement, reçu ou autre document.</small>
            </label>
            {justificatifs.length > 0 && (
              <div className={styles.fileList}>
                {justificatifs.map((file, index) => (
                  <div className={styles.fileItem} key={`${file.name}-${file.lastModified}`}>
                    <div>
                      <strong>{file.name}</strong>
                      <span>{file.type || 'Type inconnu'} · {(file.size / 1024).toFixed(1)} Ko</span>
                    </div>
                    <button type="button" onClick={() => setJustificatifs((prev) => prev.filter((_, idx) => idx !== index))}>
                      Supprimer
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
            </div>
            {isPage && (
              <aside className={styles.encaissementSummaryPanel} aria-label="Résumé de l'encaissement">
                <div className={styles.summaryPanelHeader}>
                  <span>Résumé</span>
                  <strong>{montantTotalArticles > 0 ? formatCurrency(montantTotalArticles) : 'Aucun montant'}</strong>
                </div>
                <div className={styles.balanceStatus} data-balanced={solde <= 0 && montantTotalArticles > 0 ? 'true' : 'false'}>
                  {solde <= 0 && montantTotalArticles > 0 ? 'Encaissement équilibré' : 'Montant à compléter'}
                </div>
                <div className={styles.summaryRows}>
                  <div><span>Client</span><strong>{clientSummary}</strong></div>
                  <div><span>Type de client</span><strong>{TYPE_CLIENT_LABELS[formData.type_client] || formData.type_client}</strong></div>
                  <div><span>Service / Commission</span><strong>{selectedServiceLabel}</strong></div>
                  <div><span>Projet / Activité</span><strong>{selectedProjectActivityLabel}</strong></div>
                  <div><span>Poste budgétaire</span><strong>{budgetSearch || 'Non sélectionné'}</strong></div>
                  <div><span>Articles</span><strong>{validArticleRows.length} ligne{validArticleRows.length > 1 ? 's' : ''}</strong></div>
                </div>
                <div className={styles.amountReview}>
                  <div><span>Sous-total</span><strong>{formatCurrency(montantTotalArticles)}</strong></div>
                  <div><span>Montant payé</span><strong>{formatCurrency(montantPayeUSD)}</strong></div>
                  <div className={solde > 0 ? styles.amountWarning : styles.amountCurrent}>
                    <span>Solde éventuel</span><strong>{formatCurrency(solde)}</strong>
                  </div>
                </div>
                <div className={styles.summaryRows}>
                  <div><span>Mode</span><strong>{modePaiementLabel[formData.mode_paiement]}</strong></div>
                  <div><span>Caisse / Banque</span><strong>{selectedCompteLabel}</strong></div>
                  <div><span>Devise</span><strong>{formData.devise_perception}</strong></div>
                  <div><span>Statut prévu</span><strong>{expectedStatus}</strong></div>
                </div>
              </aside>
            )}
          </div>

          <div className={styles.formActions}>
            <button type="button" onClick={onClose} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>Annuler</button>
            <button type="button" onClick={handleCreateProforma} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>
              {activeSubmitAction === 'proforma' ? 'Enregistrement du brouillon…' : 'Enregistrer le brouillon'}
            </button>
            <button type="button" onClick={resetForm} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>Réinitialiser</button>
            <button type="submit" className={styles.primaryBtn} disabled={activeSubmitAction !== null}>
              {activeSubmitAction === 'submit' ? 'Enregistrement en cours…' : 'Enregistrer et valider'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
