import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { format } from 'date-fns'
import { AlertTriangle } from 'lucide-react'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, ModePaiement, NatureMouvement, TypeClient, Service } from '../types'
import { toNumber } from '../utils/amount'
import { TYPE_CLIENT_LABELS, libelleNomClient, typeClientDemandeLeSexe } from '../utils/encaissementHelpers'
import type { ProjetActivite } from '../api/projetsActivites'
import { uploadEncaissementPiece } from '../api/encaissementPieces'
import { listerNotesImpayees } from '../api/creances'
import { listEncaissementTarifs, type EncaissementTarif } from '../api/encaissementTarifs'
import { usePermissions } from '../hooks/usePermissions'
import NotesImpayeesPanel, { type CiblePayeur } from './NotesImpayeesPanel'
import { useTreeBranchReveal } from '../hooks/useTreeBranchReveal'
import { useConfirm } from '../contexts/ConfirmContext'
import OrganisationAutocomplete, {
  ORGANISATION_OTHER_VALUE,
  type OrganisationAutocompleteValue,
} from './OrganisationAutocomplete'
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

const SEXES = [
  { value: 'M', libelle: 'Masculin' },
  { value: 'F', libelle: 'Féminin' },
] as const

const CANAUX = [
  { value: 'CAISSE', libelle: 'Caisse' },
  { value: 'BANQUE', libelle: 'Banque' },
] as const

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
  /** Poste imposé par le tarif reconnu, s'il en impose un. */
  budget_poste_id?: number | null
  /** L'utilisateur a demandé à sortir du prix tarifé sur CETTE ligne. */
  force?: boolean
}

/** Clé de reconnaissance d'un libellé : mêmes règles que le serveur
 *  (minuscules, espaces resserrés), sans quoi l'écran et lui ne
 *  reconnaîtraient pas les mêmes lignes. */
const normaliserLibelle = (valeur: string) => valeur.trim().replace(/\s+/g, ' ').toLowerCase()

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
  // Antidater un encaissement revient à en réécrire la chronologie : réservé au
  // super administrateur, le serveur applique la même règle et refuse le reste.
  const peutAntidater = String(user?.role || '').toLowerCase() === 'super_admin'
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
    date_encaissement: format(new Date(), 'yyyy-MM-dd'),
    budget_poste_id: '',
    service_id: '',
    project_activity_id: '',
    nature_mouvement: 'BUDGETAIRE' as NatureMouvement,
    // Renseignés uniquement pour un fonds de tiers : de qui vient l'argent, et
    // pour qui il est gardé.
    ft_tiers_selection: null as OrganisationAutocompleteValue,
    ft_tiers_nom_libre: '',
    ft_payeur_origine: '',
    ft_motif: '',
    ft_reference: '',
  })
  const [articles, setArticles] = useState<ArticleDraft[]>([
    { libelle: '', quantite: '1', prix_unitaire: '' },
  ])
  // Tarifs actifs : ce qu'un libellé connu vaut, et où il s'impute. Le serveur
  // les impose de son côté ; ici ils évitent la frappe et annoncent le verrou.
  const [tarifs, setTarifs] = useState<EncaissementTarif[]>([])
  // Forcer un prix tarifé est réservé à qui règle les tarifs — le serveur
  // applique la même règle, l'écran ne fait que la montrer.
  const { hasPermission } = usePermissions()
  const confirm = useConfirm()
  const peutForcerTarif = hasPermission('can_edit_settings')

  const [searchEC, setSearchEC] = useState('')
  const [filteredExperts, setFilteredExperts] = useState<ExpertComptable[]>([])
  const [isSearchingExperts, setIsSearchingExperts] = useState(false)
  const [ftTiersLabel, setFtTiersLabel] = useState('')
  // Référentiel clients (anti-doublons) : suggestions pendant la saisie du nom.
  const [clientId, setClientId] = useState('')
  // Ce que le client sélectionné doit encore, s'il doit quelque chose.
  const [creanceClient, setCreanceClient] = useState<{ reste: number; notes: number } | null>(null)
  // Idem pour un expert-comptable : un expert doit comme un client, et le
  // chemin vers ses notes doit être le même. Sa dette n'accompagne pas la
  // recherche d'experts : elle est lue à la sélection, geste explicite.
  const [creanceExpert, setCreanceExpert] = useState<{ reste: number; notes: number } | null>(null)
  // Le payeur dont on ouvre les notes impayées, s'il y en a un.
  const [payeurAuxNotes, setPayeurAuxNotes] = useState<{ cible: CiblePayeur; libelle: string } | null>(null)
  const [clientEmail, setClientEmail] = useState('')
  const [clientTelephone, setClientTelephone] = useState('')
  const [clientSexe, setClientSexe] = useState('')
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

  // Un encaissement hors budget ou pour compte de tiers alimente la caisse sans
  // rien apporter au budget : le poste budgétaire n'a alors pas de sens et le
  // serveur refuse qu'on en porte un.
  const natureMouvement = formData.nature_mouvement
  const impacteLeBudget = natureMouvement === 'BUDGETAIRE'
  const estFondsDeTiers = natureMouvement === 'FONDS_DE_TIERS'
  // Le sexe n'est demandé que là où il y a une personne derrière le client.
  // Un mouvement de fonds de tiers force type_client à 'autre' : il ne
  // designe personne, la question ne se pose donc pas non plus.
  const demandeLeSexe = !estFondsDeTiers && typeClientDemandeLeSexe(formData.type_client)
  // « Autre tiers » ouvre un champ de saisie libre à côté du sélecteur.
  const ftTiersLibre = formData.ft_tiers_selection === ORGANISATION_OTHER_VALUE
  // Largeurs de l'affectation comptable : le poste budgétaire disparaît hors
  // budget, les autres champs se redistribuent pour garder des lignes pleines.
  // L'affectation se lit en deux moments : ce qui CONDITIONNE l'imputation (le
  // service borne les rubriques permises) se choisit avant les lignes ; ce que
  // les lignes DÉTERMINENT se lit après elles.
  const colAffectation = { service: styles.col2, centre: styles.col2, projet: styles.col2 }
  const colImputation = impacteLeBudget
    ? { poste: styles.col2, compte: styles.col2, total: styles.col2 }
    : { poste: styles.col2, compte: styles.col3, total: styles.col3 }
  const natureToneClass = natureMouvement === 'FONDS_DE_TIERS'
    ? styles.natureFunds
    : natureMouvement === 'HORS_BUDGET_A_REGULARISER'
      ? styles.natureOutOfBudget
      : styles.natureBudget
  const natureHelpText = natureMouvement === 'FONDS_DE_TIERS'
    ? "Fonds encaissés pour le compte d’un tiers. Ils n’appartiennent pas à l’organisation et ne consomment aucun poste budgétaire."
    : natureMouvement === 'HORS_BUDGET_A_REGULARISER'
      ? 'Recette enregistrée sans imputation budgétaire immédiate. Elle pourra être régularisée et affectée au budget ultérieurement.'
      : 'Recette rattachée au budget de l’organisation. Le client, l’affectation budgétaire, le montant et le paiement seront renseignés dans les sections suivantes.'

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

  useEffect(() => {
    let vivant = true
    listEncaissementTarifs(true)
      .then((liste) => {
        if (vivant) setTarifs(liste)
      })
      .catch(() => {
        // Sans tarifs, la saisie reste entièrement libre : c'est le
        // comportement d'avant, pas une panne à signaler au caissier.
        if (vivant) setTarifs([])
      })
    return () => {
      vivant = false
    }
  }, [])

  const tarifParLibelle = useMemo(() => {
    const index = new Map<string, EncaissementTarif>()
    for (const tarif of tarifs) index.set(normaliserLibelle(tarif.libelle), tarif)
    return index
  }, [tarifs])

  const tarifDeLigne = useCallback(
    (article: ArticleDraft) => tarifParLibelle.get(normaliserLibelle(article.libelle || '')),
    [tarifParLibelle],
  )

  /** Les tarifs arrivent après l'ouverture de l'écran. Une ligne tapée pendant
   *  ce court instant doit recevoir son prix et son poste à leur arrivée :
   *  sinon elle se retrouverait verrouillée sur un montant libre que le serveur
   *  refuserait au moment d'enregistrer. */
  useEffect(() => {
    if (tarifParLibelle.size === 0) return
    setArticles((prev) => {
      let changee = false
      const suivant = prev.map((article) => {
        const tarif = tarifParLibelle.get(normaliserLibelle(article.libelle || ''))
        if (!tarif) return article
        const poste = tarif.budget_poste_id ?? null
        const prix =
          tarif.montant !== null && tarif.montant !== undefined && !article.force
            ? String(tarif.montant)
            : article.prix_unitaire
        if (poste === (article.budget_poste_id ?? null) && prix === article.prix_unitaire) return article
        changee = true
        return { ...article, budget_poste_id: poste, prix_unitaire: prix }
      })
      return changee ? suivant : prev
    })
  }, [tarifParLibelle])

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

  /** Poste que les lignes désignent d'elles-mêmes : celui qui porte le plus
   *  gros montant. Les tarifs renversent l'ordre de saisie — on tape le
   *  libellé et l'imputation suit —, si bien qu'exiger le poste AVANT les
   *  lignes n'a plus de sens quand les lignes le disent déjà. */
  const postePrincipalDesLignes = useMemo(() => {
    const parPoste = new Map<number, number>()
    for (const article of articles) {
      const poste = article.budget_poste_id
      if (!poste) continue
      const quantite = toNumber(article.quantite || 0)
      const prix = toNumber(article.prix_unitaire || 0)
      parPoste.set(poste, (parPoste.get(poste) || 0) + quantite * prix)
    }
    let gagnant: number | null = null
    let meilleur = -1
    for (const [poste, montant] of parPoste) {
      if (montant > meilleur) {
        gagnant = poste
        meilleur = montant
      }
    }
    return gagnant
  }, [articles])

  /** Nombre de postes distincts portés par les lignes. Un reçu peut mêler deux
   *  natures — chaque ligne garde le sien —, mais l'en-tête de l'encaissement
   *  n'en retient qu'un : mieux vaut le dire que de le choisir en silence. */
  const postesDistinctsDesLignes = useMemo(
    () => new Set(articles.map((a) => a.budget_poste_id).filter(Boolean)).size,
    [articles],
  )

  /** Nom du poste que les lignes imposent, pour que l'écran le dise au lieu de
   *  laisser un champ vide sous une étoile d'obligation. */
  const postePrincipalLibelle = useMemo(() => {
    if (!postePrincipalDesLignes) return null
    const tarif = tarifs.find((t) => t.budget_poste_id === postePrincipalDesLignes)
    return tarif?.budget_poste_libelle || null
  }, [postePrincipalDesLignes, tarifs])

  /** Le poste retenu pour l'encaissement : celui que l'agent a choisi, sinon
   *  celui que ses lignes désignent. */
  const postePourEncaissement = useMemo(
    () => (formData.budget_poste_id ? Number(formData.budget_poste_id) : postePrincipalDesLignes),
    [formData.budget_poste_id, postePrincipalDesLignes],
  )

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
      // Plusieurs comptes éligibles : on impose un choix explicite, se tromper de
      // compte de dépôt ne se rattrape qu'au rapprochement. Un seul : rien à choisir.
      const nextCompteId = formData.canal !== 'BANQUE'
        ? ''
        : selectedStillAvailable
          ? prev.compte_bancaire_id
          : next.length === 1
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
    setCreanceExpert(null)
    // Sa dette doit être sous les yeux pendant qu'on saisit le montant : c'est
    // là que se décide « encaisser ici » ou « compléter sa note ».
    void (async () => {
      try {
        const res = await listerNotesImpayees({ expert_comptable_id: expert.id, limit: 1 })
        setCreanceExpert(res.nb_notes > 0 ? { reste: res.total_du, notes: res.nb_notes } : null)
      } catch {
        /* La créance est un signalement : son absence ne doit pas bloquer la saisie. */
      }
    })()
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
    // La dette suit le client sélectionné : elle doit rester sous les yeux
    // pendant qu'on saisit le montant, pas disparaître avec la liste.
    setCreanceClient(
      Number(c.nb_impayes) > 0
        ? { reste: Number(c.reste_du || 0), notes: Number(c.nb_impayes) }
        : null,
    )
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
    setClientSexe(c.sexe || '')
    setClientSuggestions([])
    setShowClientDropdown(false)
  }

  const resetClientSelection = () => {
    setClientId('')
    setCreanceClient(null)
    setCreanceExpert(null)
    setClientEmail('')
    setClientTelephone('')
    setClientSexe('')
    setClientSuggestions([])
    setShowClientDropdown(false)
  }

  /** Ce que ce payeur doit encore, et le chemin pour y verser.
   *
   *  Encaisser son règlement ici crée une SECONDE note de débit : l'argent
   *  rentre, la première reste ouverte, et il garde une dette qu'il a pourtant
   *  payée. Le bouton mène à ses notes — le seul geste qui diminue ce qu'il
   *  doit. C'est pourquoi il est plus visible que le chemin qui ne solde rien.
   *
   *  Solder n'est pas la seule issue : un acompte se verse sur la même note, et
   *  la bannière le dit. Ne parler que du solde laisserait croire qu'un client
   *  qui n'avance qu'une partie n'a pas d'autre choix que la nouvelle note —
   *  et sa dette doublerait pour de bon. */
  const banniereCreance = (
    creance: { reste: number; notes: number } | null,
    sujet: string,
    cible: CiblePayeur,
    libelle: string,
  ) =>
    creance ? (
      <div className={styles.creanceBanniere} role="status">
        <AlertTriangle size={16} aria-hidden="true" style={{ flexShrink: 0, marginTop: '1px' }} />
        <span className={styles.creanceTexte}>
          {sujet} doit encore{' '}
          <span className={styles.creanceMontant}>{formatCurrency(creance.reste)}</span>
          {' '}sur {creance.notes} note{creance.notes > 1 ? 's' : ''} de débit.
          <span className={styles.creanceReserve}>
            Tout versement, même partiel, se porte sur sa note : encaisser ici en ouvrirait
            une seconde, et la sienne resterait due.
          </span>
        </span>
        <button
          type="button"
          className={styles.creanceBouton}
          onClick={() => setPayeurAuxNotes({ cible, libelle })}
        >
          Compléter le paiement
        </button>
      </div>
    ) : null

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
    setArticles((prev) => prev.map((article, idx) => {
      if (idx !== index) return article
      const suivant: ArticleDraft = { ...article, [field]: value }
      if (field !== 'libelle') return suivant
      // Le libellé vient de changer : un tarif reconnu apporte son prix et son
      // poste. Changer de libellé remet la ligne à plat — le prix d'un tarif
      // n'a plus de raison de rester sur une ligne qui parle d'autre chose.
      const tarif = tarifParLibelle.get(normaliserLibelle(value))
      suivant.force = false
      suivant.budget_poste_id = tarif?.budget_poste_id ?? null
      if (tarif?.montant !== null && tarif?.montant !== undefined) {
        suivant.prix_unitaire = String(tarif.montant)
      } else if (article.budget_poste_id || tarifDeLigne(article)) {
        // On quitte un tarif : son prix ne doit pas rester sur la ligne.
        suivant.prix_unitaire = ''
      }
      return suivant
    }))
  }

  /** Rouvre le prix d'une ligne tarifée. Le serveur exige le même droit :
   *  ce bouton annonce la porte, il ne l'ouvre pas à lui seul. */
  const forcerMontant = (index: number) => {
    setArticles((prev) => prev.map((article, idx) => (idx === index ? { ...article, force: true } : article)))
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
      date_encaissement: format(new Date(), 'yyyy-MM-dd'),
      budget_poste_id: '',
      service_id: '',
      project_activity_id: '',
      nature_mouvement: 'BUDGETAIRE',
      ft_tiers_selection: null as OrganisationAutocompleteValue,
      ft_tiers_nom_libre: '',
      ft_payeur_origine: '',
      ft_motif: '',
      ft_reference: '',
    })
    setArticles([{ libelle: '', quantite: '1', prix_unitaire: '' }])
    setSearchEC('')
    setSelectedExpert(null)
    resetClientSelection()
    setFtTiersLabel('')
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
      // Le poste du tarif, quand il en impose un : c'est lui qui rend possible
      // un reçu mêlant deux natures. Sinon la ligne suit le poste choisi plus
      // haut pour l'encaissement.
      budget_poste_id: article.budget_poste_id ?? null,
    }))
  }

  const getMainLibelle = () => {
    const labels = validArticleRows.map((article) => article.libelle.trim())
    const value = labels.length <= 1 ? labels[0] : labels.join(', ')
    return (value || 'Encaissement').slice(0, 255)
  }

  const revealBudgetBranch = useTreeBranchReveal()

  const toggleBudgetNode = (id: number, row?: HTMLElement | null) => {
    setExpandedBudgetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    // Recentrage seulement à l'ouverture : replier n'a rien à montrer.
    if (!expandedBudgetIds.has(id)) revealBudgetBranch(row ?? null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitLockRef.current) return
    if (!validateForm()) return

    // Zéro payé n'est pas une faute en soi : c'est ainsi qu'on enregistre une
    // note de débit à recouvrer, et tout le suivi des créances en vit. Mais
    // c'est aussi ce qu'on obtient en oubliant de saisir le montant, et le
    // bouton dit « Enregistrer et valider », pas « Reconnaître une dette ».
    // On ne refuse donc pas : on fait dire à l'agent ce qu'il enregistre.
    if (toNumber(formData.montant_paye) === 0) {
      const assume = await confirm({
        title: 'Aucun montant payé',
        description:
          `Rien n'est encaissé : cet enregistrement créera une note de débit de `
          + `${formatCurrency(montantTotalArticles)} à recouvrer, et la caisse ne bougera pas. `
          + `Si le client a payé, fermez cette fenêtre et saisissez le montant reçu.`,
        confirmText: 'Enregistrer la dette',
        cancelText: 'Saisir le montant',
        variant: 'danger',
      })
      if (!assume) return
    }

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
        type_client: estFondsDeTiers ? 'autre' : formData.type_client,
        expert_comptable_id: !estFondsDeTiers && formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: !estFondsDeTiers && formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        client_id: !estFondsDeTiers && formData.type_client !== 'expert_comptable' && clientId ? clientId : null,
        client_email: !estFondsDeTiers && formData.type_client !== 'expert_comptable' ? (clientEmail.trim() || null) : null,
        client_telephone: !estFondsDeTiers && formData.type_client !== 'expert_comptable' ? (clientTelephone.trim() || null) : null,
        client_sexe: demandeLeSexe ? (clientSexe || null) : null,
        libelle: getMainLibelle(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: montantPaye,
        montant_percu: montantPercu,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: impacteLeBudget ? postePourEncaissement : null,
        nature_mouvement: natureMouvement,
        fonds_tiers: estFondsDeTiers
          ? {
              tiers_organisation_id:
                typeof formData.ft_tiers_selection === 'number'
                  ? formData.ft_tiers_selection
                  : null,
              tiers_nom_libre:
                formData.ft_tiers_selection === ORGANISATION_OTHER_VALUE
                  ? formData.ft_tiers_nom_libre.trim()
                  : null,
              payeur_origine: formData.ft_payeur_origine.trim() || null,
              motif: formData.ft_motif.trim() || null,
              reference: formData.ft_reference.trim() || null,
            }
          : null,
        service_id: formData.service_id ? Number(formData.service_id) : null,
        project_activity_id: formData.project_activity_id ? Number(formData.project_activity_id) : null,
        statut_paiement: statutPaiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
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
        client_sexe: demandeLeSexe ? (clientSexe || null) : null,
        libelle: getMainLibelle(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: 0,
        montant_percu: 0,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: postePourEncaissement,
        service_id: formData.service_id ? Number(formData.service_id) : null,
        project_activity_id: formData.project_activity_id ? Number(formData.project_activity_id) : null,
        statut_paiement: 'non_paye',
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
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
    // Une proforma est une promesse de recette budgétaire ; elle n'a pas encore
    // touché la trésorerie et n'a donc rien à faire hors budget.
    if (isProforma && !impacteLeBudget) {
      onError(
        'Proforma impossible',
        "Une proforma ne peut être émise que pour un encaissement budgétaire. Repassez la nature sur « Budgétaire ».",
      )
      return false
    }
    if (!estFondsDeTiers && formData.type_client === 'expert_comptable' && !formData.expert_comptable_id) {
      onError('Expert-comptable non sélectionné', 'Veuillez sélectionner un expert-comptable depuis la liste.')
      return false
    }
    if (!estFondsDeTiers && formData.type_client !== 'expert_comptable' && !formData.client_nom.trim()) {
      onError('Nom du client requis', 'Veuillez saisir le nom complet du client.')
      return false
    }
    if (demandeLeSexe && !clientSexe) {
      onError('Sexe requis', 'Veuillez indiquer le sexe du client (M ou F).')
      return false
    }
    if (
      !estFondsDeTiers && formData.type_client !== 'expert_comptable' &&
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
    // Un encaissement fait entrer de l'argent : un montant négatif n'a pas de
    // sens ici. Zéro reste permis (note de débit), mais se confirme à l'envoi.
    // Pas toNumber : il ramène l'illisible à 0, qu'on prendrait pour une dette.
    const montantPayeSaisi = Number(String(formData.montant_paye).trim().replace(',', '.'))
    if (!isProforma && !Number.isFinite(montantPayeSaisi)) {
      onError('Montant payé invalide', 'Le montant payé doit être un nombre.')
      return false
    }
    if (!isProforma && montantPayeSaisi < 0) {
      onError(
        'Montant payé négatif',
        "Un encaissement fait entrer de l'argent. Pour en faire sortir, passez par une sortie de fonds ou un retour en trésorerie.",
      )
      return false
    }

    if (formData.canal === 'BANQUE' && !formData.compte_bancaire_id) {
      onError('Compte requis', 'Veuillez sélectionner un compte de dépôt.')
      return false
    }
    if (impacteLeBudget && !postePourEncaissement) {
      onError(
        'Poste requis',
        'Sélectionnez un poste budgétaire, ou choisissez un libellé tarifé qui porte le sien.',
      )
      return false
    }
    if (estFondsDeTiers && !formData.ft_tiers_selection) {
      onError('Tiers requis', "Indiquez pour quel tiers ces fonds sont encaissés.")
      return false
    }
    if (
      estFondsDeTiers &&
      formData.ft_tiers_selection === ORGANISATION_OTHER_VALUE &&
      !formData.ft_tiers_nom_libre.trim()
    ) {
      onError('Nom du tiers requis', 'Veuillez saisir le nom du tiers externe.')
      return false
    }
    if (estFondsDeTiers && !isProforma && toNumber(formData.montant_paye) <= 0) {
      onError(
        'Encaissement immédiat requis',
        "Un fonds de tiers est reçu en une fois : il ne peut pas rester impayé ni être encaissé par tranches.",
      )
      return false
    }
    if (mustSelectService && !formData.service_id) {
      onError('Service requis', 'Veuillez sélectionner la commission concernée.')
      return false
    }
    return true
  }

  // La commission concernée vaut pour toutes les natures : un fonds de tiers
  // est détenu par un service identifiable, et `validateForm` l'exige dès que
  // l'organisation a des services. Rendu ici une seule fois, puis placé dans la
  // section « Fonds de tiers » ou « Affectation comptable » selon la nature —
  // sans le champ à l'écran, un utilisateur multi-commissions se retrouvait
  // bloqué par une erreur qu'il ne pouvait pas corriger.
  const renderServiceField = (colClass: string) => (
    <div className={`${styles.field} ${colClass}`}>
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
  )

  const BudgetDropdownNode = ({ node, depth }: { node: any; depth: number }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = budgetSearch.trim().length > 0 || expandedBudgetIds.has(node.id)
    return (
      <>
        <div
          className={`${styles.dropdownItem} ${hasChildren ? styles.parentItem : ''}`}
          style={{ paddingLeft: `${10 + depth * 16}px` }}
          data-tree-node={hasChildren ? node.id : undefined}
          onClick={(event) => hasChildren ? toggleBudgetNode(node.id, event.currentTarget) : selectBudgetPoste(node)}
        >
          {hasChildren && <span className={`${styles.treeToggle} ${isExpanded ? styles.treeToggleOpen : ''}`} />}
          <strong>{node.code}</strong> - {node.libelle}
          {hasChildren && <span className={styles.parentBadge}>Parent</span>}
        </div>
        {hasChildren && isExpanded && (
          <div className={styles.treeBranch} data-tree-branch={node.id}>
            {node.children.map((child: any) => (
              <BudgetDropdownNode key={child.id} node={child} depth={depth + 1} />
            ))}
          </div>
        )}
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
    const compte = comptesBancaires.find((item) => String(item.id) === String(formData.compte_bancaire_id))
    if (!compte) return 'Compte non sélectionné'
    const numeroCompte = String(compte.numero_compte || '').replace(/\s+/g, '')
    const numeroMasque = numeroCompte ? `••••${numeroCompte.slice(-4)}` : ''
    return [compte.banque?.nom || 'Banque', compte.devise, numeroMasque, compte.intitule]
      .filter(Boolean)
      .join(' — ')
  }, [comptesBancaires, formData.compte_bancaire_id])

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
    virement: 'Opération bancaire',
    card: 'Carte',
    cheque: 'Chèque',
  }
  const referenceLabel = formData.mode_paiement === 'cheque'
    ? 'Numéro du chèque *'
    : formData.mode_paiement === 'mobile_money'
      ? 'Opérateur et référence *'
      : formData.mode_paiement === 'virement'
        ? "Référence de l'opération bancaire *"
        : 'Référence de paiement'

  const selectCanal = (nextCanal: 'CAISSE' | 'BANQUE') => {
    setFormData(prev => ({
      ...prev,
      canal: nextCanal,
      mode_paiement: nextCanal === 'CAISSE'
        ? 'cash'
        : prev.mode_paiement === 'cash'
          ? 'virement'
          : prev.mode_paiement,
      reference: nextCanal === 'CAISSE' ? '' : prev.reference,
    }))
  }

  const renderCanalControl = () => (
    <div className={styles.destinationControlStack}>
      <div className={styles.destinationControl}>
        <span id={`${formId}-canal-label`} className={styles.destinationControlLabel}>Encaisser sur</span>
        <div
          className={styles.segmented}
          role="radiogroup"
          aria-labelledby={`${formId}-canal-label`}
          // Le bouton Caisse désactivé sort du parcours clavier : sans cela, la
          // raison de son absence ne serait lue nulle part.
          aria-describedby={isCashClosed ? `${formId}-canal-warning` : undefined}
        >
          {CANAUX.map(({ value, libelle }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={formData.canal === value}
              className={
                formData.canal === value
                  ? `${styles.segmentedItem} ${styles.segmentedItemActive}`
                  : styles.segmentedItem
              }
              onClick={() => selectCanal(value)}
              disabled={value === 'CAISSE' && isCashClosed}
            >
              {libelle}
            </button>
          ))}
        </div>
      </div>
      {isCashClosed && (
        <small id={`${formId}-canal-warning`} className={styles.destinationWarning}>
          Caisse fermée : seule la banque est disponible.
        </small>
      )}
    </div>
  )

  return (
    <>
    <div className={isPage ? styles.createPageShell : styles.modal}>
      <div className={isPage ? styles.createPageContent : styles.modalContent}>
        {!isPage && (
          <div className={styles.modalHeader}>
            <h2>Nouvel encaissement</h2>
            <div className={styles.topControls}>
            <div className={styles.natureControlStack}>
            <div className={`${styles.natureControl} ${natureToneClass}`}>
              <label htmlFor={`${formId}-nature`}>Nature</label>
              <select
                id={`${formId}-nature`}
                value={formData.nature_mouvement}
                onChange={(e) => {
                  const nature = e.target.value as NatureMouvement
                  setFormData(prev => ({
                    ...prev,
                    nature_mouvement: nature,
                    type_client: nature === 'FONDS_DE_TIERS' ? 'autre' : prev.type_client,
                    expert_comptable_id: nature === 'FONDS_DE_TIERS' ? '' : prev.expert_comptable_id,
                    client_nom: nature === 'FONDS_DE_TIERS' ? '' : prev.client_nom,
                    budget_poste_id: nature === 'BUDGETAIRE' ? prev.budget_poste_id : '',
                    ft_tiers_selection: nature === 'FONDS_DE_TIERS' ? prev.ft_tiers_selection : null,
                    ft_tiers_nom_libre: nature === 'FONDS_DE_TIERS' ? prev.ft_tiers_nom_libre : '',
                    ft_payeur_origine: nature === 'FONDS_DE_TIERS' ? prev.ft_payeur_origine : '',
                    ft_motif: nature === 'FONDS_DE_TIERS' ? prev.ft_motif : '',
                    ft_reference: nature === 'FONDS_DE_TIERS' ? prev.ft_reference : '',
                  }))
                  if (nature !== 'BUDGETAIRE') setBudgetSearch('')
                  if (nature !== 'FONDS_DE_TIERS') setFtTiersLabel('')
                  if (nature === 'FONDS_DE_TIERS') {
                    setSelectedExpert(null)
                    setSearchEC('')
                    resetClientSelection()
                  }
                }}
              >
                <option value="BUDGETAIRE">Budgétaire</option>
                <option value="HORS_BUDGET_A_REGULARISER">Hors budget</option>
                <option value="FONDS_DE_TIERS">Fonds de tiers</option>
              </select>
            </div>
            <p className={styles.natureHelp}>{natureHelpText}</p>
            </div>
            {renderCanalControl()}
            </div>
            <button onClick={onClose} className={styles.closeBtn} disabled={activeSubmitAction !== null}>×</button>
          </div>
        )}

        <form id={formId} onSubmit={handleSubmit} className={`${styles.form} ${isPage ? styles.createForm : ''}`} aria-busy={activeSubmitAction !== null}>
          {isPage && (
            <div className={styles.createFormIntro}>
              <div className={styles.createIntroCopy}>
                <span className={styles.sectionEyebrow}>Recette</span>
                <h2>Informations principales</h2>
                <p>
                  {estFondsDeTiers
                    ? 'Tiers, objet du fonds, montant et paiement sont regroupés pour une saisie rapide.'
                    : natureMouvement === 'HORS_BUDGET_A_REGULARISER'
                      ? 'Client, montant et paiement sont regroupés sans affectation budgétaire obligatoire.'
                      : 'Client, affectation, articles et paiement sont regroupés sur une grille large pour une saisie rapide.'}
                </p>
              </div>
              <div className={styles.topControls}>
              <div className={styles.natureControlStack}>
              <div className={`${styles.natureControl} ${natureToneClass}`}>
                <label htmlFor={`${formId}-nature`}>Nature</label>
                <select
                  id={`${formId}-nature`}
                  value={formData.nature_mouvement}
                  onChange={(e) => {
                    const nature = e.target.value as NatureMouvement
                    setFormData(prev => ({
                      ...prev,
                      nature_mouvement: nature,
                      type_client: nature === 'FONDS_DE_TIERS' ? 'autre' : prev.type_client,
                      expert_comptable_id: nature === 'FONDS_DE_TIERS' ? '' : prev.expert_comptable_id,
                      client_nom: nature === 'FONDS_DE_TIERS' ? '' : prev.client_nom,
                      budget_poste_id: nature === 'BUDGETAIRE' ? prev.budget_poste_id : '',
                      ft_tiers_selection: nature === 'FONDS_DE_TIERS' ? prev.ft_tiers_selection : null,
                      ft_tiers_nom_libre: nature === 'FONDS_DE_TIERS' ? prev.ft_tiers_nom_libre : '',
                      ft_payeur_origine: nature === 'FONDS_DE_TIERS' ? prev.ft_payeur_origine : '',
                      ft_motif: nature === 'FONDS_DE_TIERS' ? prev.ft_motif : '',
                      ft_reference: nature === 'FONDS_DE_TIERS' ? prev.ft_reference : '',
                    }))
                    if (nature !== 'BUDGETAIRE') setBudgetSearch('')
                    if (nature !== 'FONDS_DE_TIERS') setFtTiersLabel('')
                    if (nature === 'FONDS_DE_TIERS') {
                      setSelectedExpert(null)
                      setSearchEC('')
                      resetClientSelection()
                    }
                  }}
                >
                  <option value="BUDGETAIRE">Budgétaire</option>
                  <option value="HORS_BUDGET_A_REGULARISER">Hors budget</option>
                  <option value="FONDS_DE_TIERS">Fonds de tiers</option>
              </select>
              </div>
              <p className={styles.natureHelp}>{natureHelpText}</p>
              </div>
              {renderCanalControl()}
              </div>
            </div>
          )}
          <div className={isPage ? styles.createLayout : undefined}>
          <div className={isPage ? styles.createMain : undefined}>
          {estFondsDeTiers && (
          <div className={styles.formSection}>
            <h4 className={styles.formSectionTitle}>Fonds de tiers</h4>
            <div className={styles.compactGrid}>
              <div className={`${styles.field} ${ftTiersLibre ? styles.col3 : styles.col6}`}>
                <label>Tiers concerné *</label>
                <OrganisationAutocomplete
                  value={formData.ft_tiers_selection}
                  onChange={(value, organisation) => {
                    setFormData(prev => ({
                      ...prev,
                      ft_tiers_selection: value,
                      ft_tiers_nom_libre: '',
                    }))
                    setFtTiersLabel(value === ORGANISATION_OTHER_VALUE ? 'Autre tiers' : organisation?.nom || '')
                  }}
                  excludeCurrentOrganisation
                  allowOther
                  otherLabel="Autre tiers"
                  placeholder="Rechercher un Conseil ou une organisation"
                />
              </div>
              {formData.ft_tiers_selection === ORGANISATION_OTHER_VALUE && (
                <div className={`${styles.field} ${styles.col3}`}>
                  <label>Nom du tiers *</label>
                  <input
                    type="text"
                    maxLength={255}
                    value={formData.ft_tiers_nom_libre}
                    onChange={e => setFormData(prev => ({ ...prev, ft_tiers_nom_libre: e.target.value }))}
                    placeholder="Ex : Association ABC"
                    required
                  />
                </div>
              )}
              <div className={`${styles.field} ${styles.col4}`}>
                <label>Motif / objet du fonds</label>
                <input
                  type="text"
                  value={formData.ft_motif}
                  onChange={e => setFormData(prev => ({ ...prev, ft_motif: e.target.value }))}
                  placeholder="Pourquoi ces fonds transitent par l'organisation"
                />
              </div>
              <div className={`${styles.field} ${styles.col2}`}>
                <label>Référence</label>
                <input
                  type="text"
                  maxLength={100}
                  value={formData.ft_reference}
                  onChange={e => setFormData(prev => ({ ...prev, ft_reference: e.target.value }))}
                  placeholder="N° de courrier, convention…"
                />
              </div>
              <div className={`${styles.field} ${styles.col3}`}>
                <label>Payeur d'origine</label>
                <input
                  type="text"
                  maxLength={255}
                  value={formData.ft_payeur_origine}
                  onChange={e => setFormData(prev => ({ ...prev, ft_payeur_origine: e.target.value }))}
                  placeholder="Qui a versé les fonds (facultatif)"
                />
              </div>
              {renderServiceField(styles.col3)}
            </div>
          </div>
          )}

          {!estFondsDeTiers && (
          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Client</h4>
          <div className={styles.compactGrid}>
          <div className={`${styles.field} ${styles.col2}`}>
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
            <div className={`${styles.field} ${styles.col4}`}>
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
              {banniereCreance(
                creanceExpert,
                'Cet expert-comptable',
                { expert_comptable_id: formData.expert_comptable_id },
                selectedExpert?.nom_denomination || 'cet expert-comptable',
              )}
              {isSearchingExperts && <small>Recherche en cours…</small>}
            </div>
          ) : (
            <>
              <div className={`${styles.field} ${styles.col4}`}>
                <label>{libelleNomClient(formData.type_client)} *</label>
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
                        {Number(c.nb_impayes) > 0 && (
                          // Dès la frappe : la dette annoncée devient le chemin
                          // vers la note à solder, sans passer par la sélection.
                          <button
                            type="button"
                            className={styles.creanceLigneBouton}
                            onClick={(e) => {
                              e.stopPropagation()
                              selectClient(c)
                              setPayeurAuxNotes({ cible: { client_id: String(c.id) }, libelle: c.nom })
                            }}
                          >
                            <AlertTriangle size={12} aria-hidden="true" />
                            Doit <span className={styles.creanceMontant}>{formatCurrency(c.reste_du)}</span>
                            {' '}sur {c.nb_impayes} note{Number(c.nb_impayes) > 1 ? 's' : ''}
                            {' — Compléter le paiement'}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {banniereCreance(
                  creanceClient,
                  'Ce client',
                  clientId ? { client_id: clientId } : { nom: formData.client_nom },
                  formData.client_nom || 'ce client',
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
                {/* Le sexe tient dans une seule colonne : deux valeurs,
                    deux boutons, à côté de l'email et du téléphone. */}
                {demandeLeSexe && (
                  <div className={`${styles.field} ${styles.col1}`}>
                    <label id="client-sexe-label">Sexe *</label>
                    <div
                      className={styles.segmented}
                      role="radiogroup"
                      aria-labelledby="client-sexe-label"
                      aria-required="true"
                    >
                      {SEXES.map(({ value, libelle }) => (
                        <button
                          key={value}
                          type="button"
                          role="radio"
                          aria-checked={clientSexe === value}
                          aria-label={libelle}
                          title={libelle}
                          className={
                            clientSexe === value
                              ? `${styles.segmentedItem} ${styles.segmentedItemActive}`
                              : styles.segmentedItem
                          }
                          onClick={() => setClientSexe(value)}
                        >
                          {value}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className={`${styles.field} ${styles.col3}`}>
                  <label>Email du client</label>
                  <input
                    type="email"
                    value={clientEmail}
                    onChange={(e) => setClientEmail(e.target.value)}
                    placeholder="exemple@domaine.com"
                  />
                </div>
                <div className={`${styles.field} ${demandeLeSexe ? styles.col2 : styles.col3}`}>
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
          )}

          {!estFondsDeTiers && (
          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Affectation comptable</h4>
          <div className={styles.compactGrid}>
            {renderServiceField(colAffectation.service)}

            <div className={`${styles.field} ${colAffectation.centre}`}>
              <label>Centre de coût</label>
              <input type="text" value={selectedServiceLabel} disabled />
            </div>
            <div className={`${styles.field} ${colAffectation.projet}`}>
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
          </div>
          </div>
          )}

          <div className={styles.formSection}>
          <div className={styles.articleSection}>
            <div className={styles.articleHeader}>
              <h3>{estFondsDeTiers ? 'Détail du fonds' : 'Articles du poste budgétaire'}</h3>
              <button type="button" onClick={addArticle} className={styles.secondaryBtn}>Ajouter une ligne</button>
            </div>
            <datalist id="encaissement-libelles">
              {/* Un tarif annonce ce qu'il engage : prix, poste, ou les deux.
                  Les libellés sans tarif restent de simples suggestions. */}
              {tarifs.map((tarif) => (
                <option key={`tarif-${tarif.id}`} value={tarif.libelle}>
                  {[
                    tarif.montant !== null && tarif.montant !== undefined
                      ? `${formatCurrency(toNumber(tarif.montant))} ${tarif.devise}`
                      : null,
                    tarif.budget_poste_id ? tarif.budget_poste_libelle : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </option>
              ))}
              {libellePresets
                .filter((l) => !tarifParLibelle.has(normaliserLibelle(l)))
                .map((l) => <option key={l} value={l} />)}
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
                    const tarifLigne = tarifDeLigne(article)
                    const prixVerrouille =
                      !!tarifLigne &&
                      tarifLigne.montant !== null &&
                      tarifLigne.montant !== undefined &&
                      !article.force
                    return (
                      <tr key={`article-${index}`}>
                        <td data-label="Libellé">
                      <input
                        type="text"
                        value={article.libelle}
                        onChange={(e) => updateArticle(index, 'libelle', e.target.value)}
                        onKeyDown={(e) => handleArticleKeyDown(e, index)}
                        list="encaissement-libelles"
                        placeholder="Libellé de l'article"
                        required
                      />
                      {/* Le poste tenu par le tarif se lit sous le libellé : le
                          caissier voit où tombe la recette sans quitter la ligne. */}
                      {tarifLigne?.budget_poste_id && (
                        <span className={styles.tarifPoste}>
                          → {tarifLigne.budget_poste_libelle}
                        </span>
                      )}
                        </td>
                        <td data-label="Quantité">
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
                        <td data-label="Prix unitaire">
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={article.prix_unitaire}
                        onChange={(e) => updateArticle(index, 'prix_unitaire', e.target.value)}
                        onKeyDown={(e) => handleArticleKeyDown(e, index)}
                        disabled={prixVerrouille}
                        title={prixVerrouille ? `Prix fixé par le tarif « ${tarifLigne?.libelle} »` : undefined}
                        required
                      />
                      {prixVerrouille && peutForcerTarif && (
                        <button
                          type="button"
                          className={styles.tarifForcer}
                          onClick={() => forcerMontant(index)}
                        >
                          Forcer le montant
                        </button>
                      )}
                      {article.force && tarifLigne?.montant !== null && tarifLigne?.montant !== undefined && (
                        <span className={styles.tarifForce}>
                          Tarif : {formatCurrency(toNumber(tarifLigne.montant))} — l'écart sera journalisé
                        </span>
                      )}
                        </td>
                        <td data-label="Total"><strong>{formatCurrency(row?.montant || 0)}</strong></td>
                        <td data-label="Action">
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
                    <td colSpan={3} className={styles.articleTotalLabel}>Total général</td>
                    <td className={styles.articleTotalValue} data-label="Total général">{formatCurrency(montantTotalArticles)}</td>
                    <td className={styles.articleTotalSpacer} />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
          </div>

          {/* L'imputation se lit APRÈS les lignes : un libellé tarifé porte son
              poste, si bien que les lignes répondent souvent d'elles-mêmes à la
              question que cette section posait auparavant. */}
          {!estFondsDeTiers && (
          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Imputation budgétaire</h4>
          <div className={styles.compactGrid}>
            {impacteLeBudget && (
            <div className={`${styles.field} ${colImputation.poste}`}>
              <label>
                Poste budgétaire *
                {!formData.budget_poste_id && postePrincipalDesLignes && (
                  <span className={styles.tarifPoste}>
                    {postePrincipalLibelle
                      ? `Défini par les lignes : ${postePrincipalLibelle}`
                      : 'Défini par les libellés tarifés'}
                  </span>
                )}
              </label>
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
                  placeholder={
                    postePrincipalLibelle && !formData.budget_poste_id
                      ? `Déduit des lignes : ${postePrincipalLibelle}`
                      : 'Rechercher par code, libellé ou catégorie'
                  }
                />
                {showBudgetDropdown && filteredBudgetTree.length > 0 && (
                  <div className={`${styles.dropdown} ${styles.dropdownWide}`} data-tree-scroll onMouseDown={e => e.preventDefault()}>
                    {filteredBudgetTree.map(node => <BudgetDropdownNode key={node.id} node={node} depth={0} />)}
                  </div>
                )}
              </div>
            </div>
            )}
            <div className={`${styles.field} ${colImputation.compte}`}>
              <label>Compte comptable</label>
              <input
                type="text"
                value={impacteLeBudget ? (budgetSearch || 'Déduit du poste budgétaire') : 'Sans imputation budgétaire'}
                disabled
              />
            </div>
            <div className={`${styles.field} ${colImputation.total}`}>
              <label>Total comptable (USD)</label>
              <input type="text" value={formatCurrency(montantTotalArticles)} disabled />
            </div>
            {impacteLeBudget && postesDistinctsDesLignes > 1 && (
              <div className={`${styles.field} ${styles.col6}`}>
                <small className={styles.warningText}>
                  Les lignes portent {postesDistinctsDesLignes} postes différents. Chacune garde le sien ;
                  l'encaissement, lui, sera rattaché à {postePrincipalLibelle || 'celui qui porte le plus gros montant'}.
                </small>
              </div>
            )}
          </div>
          </div>
          )}

          <div className={styles.formSection}>
          <h4 className={styles.formSectionTitle}>Paiement</h4>
          <div className={styles.compactGrid}>
            {/* Ligne 1 — les montants : total dû, devise, montant remis. */}
            <div className={`${styles.field} ${styles.col3}`}>
              <label>Montant total</label>
              <input type="text" value={formatCurrency(montantTotalArticles)} disabled />
            </div>
            {/* Trois lettres : le champ n'a pas besoin d'une colonne entière. */}
            <div className={`${styles.field} ${styles.col1}`}>
              <label>Devise *</label>
              <select
                value={formData.devise_perception}
                onChange={(e) => setFormData(prev => ({ ...prev, devise_perception: e.target.value }))}
              >
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div className={`${styles.field} ${styles.col2}`}>
              <label>Montant payé ({formData.devise_perception}) *</label>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0"
                value={formData.montant_paye}
                onChange={e => setFormData(prev => ({ ...prev, montant_paye: e.target.value }))}
                required
              />
            </div>

            {/* Ligne 2 — le canal est choisi une seule fois, en haut du formulaire. */}
            {formData.canal === 'BANQUE' ? (
              <div className={`${styles.field} ${styles.col3}`}>
                <label>Compte bancaire *</label>
                <select
                  value={formData.compte_bancaire_id}
                  onChange={(e) => setFormData(prev => ({ ...prev, compte_bancaire_id: e.target.value }))}
                  required
                >
                  <option value="">Sélectionner un compte bancaire</option>
                  {filteredComptes.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.banque?.nom || 'Banque'} - {c.intitule} ({c.devise})
                    </option>
                  ))}
                </select>
                {filteredComptes.length === 0 && <small className={styles.warningText}>Aucun compte bancaire disponible pour cette devise.</small>}
              </div>
            ) : null}
            {/* En caisse, le mode est nécessairement les espèces : une liste à une
                seule entrée ne se choisit pas, le récapitulatif l'affiche. */}
            {formData.canal === 'BANQUE' && (
              <div className={`${styles.field} ${styles.col3}`}>
                <label>Mode de paiement *</label>
                <select
                  value={formData.mode_paiement}
                  onChange={e => setFormData(prev => ({ ...prev, mode_paiement: e.target.value as ModePaiement }))}
                >
                  <option value="mobile_money">Mobile Money</option>
                  <option value="card">Carte</option>
                  <option value="virement">Opération bancaire</option>
                  <option value="cheque">Chèque</option>
                </select>
              </div>
            )}
            {/* Ligne 3 — référence de l'opération et date. */}
            {formData.mode_paiement !== 'cash' && (
              <div className={`${styles.field} ${styles.col4}`}>
                <label>{referenceLabel}</label>
                <input
                  type="text"
                  value={formData.reference}
                  onChange={e => setFormData(prev => ({ ...prev, reference: e.target.value }))}
                  placeholder={formData.mode_paiement === 'cheque' ? 'N° chèque' : 'Référence'}
                />
              </div>
            )}
            <div className={`${styles.field} ${styles.col2}`}>
              <label>Date d’encaissement *</label>
              <input
                type="date"
                value={formData.date_encaissement}
                onChange={e => setFormData(prev => ({ ...prev, date_encaissement: e.target.value }))}
                required
                disabled={!peutAntidater}
                title={
                  peutAntidater
                    ? 'Super administrateur : vous pouvez régulariser une saisie à une date antérieure'
                    : "L'opération est horodatée par le serveur"
                }
              />
              {!peutAntidater && (
                <small className={styles.fieldHint}>
                  Horodatage automatique par le serveur.
                </small>
              )}
            </div>
            <div className={`${styles.field} ${formData.mode_paiement !== 'cash' ? styles.col6 : styles.col4}`}>
              <label>Description</label>
              <textarea
                value={formData.description}
                onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                rows={2}
                placeholder="Objet de l'encaissement (repris dans la liste et les exports)"
              />
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
              <small>Facture, bordereau, reçu, preuve d'opération…</small>
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
                  {estFondsDeTiers ? (
                    <div><span>Tiers concerné</span><strong>{formData.ft_tiers_selection === ORGANISATION_OTHER_VALUE ? formData.ft_tiers_nom_libre || 'Autre tiers' : ftTiersLabel || 'Organisation à sélectionner'}</strong></div>
                  ) : (
                    <>
                      <div><span>Client</span><strong>{clientSummary}</strong></div>
                      <div><span>Type de client</span><strong>{TYPE_CLIENT_LABELS[formData.type_client] || formData.type_client}</strong></div>
                      <div><span>Service / Commission</span><strong>{selectedServiceLabel}</strong></div>
                      <div><span>Projet / Activité</span><strong>{selectedProjectActivityLabel}</strong></div>
                      <div><span>Poste budgétaire</span><strong>{budgetSearch || 'Non sélectionné'}</strong></div>
                    </>
                  )}
                  <div><span>Articles</span><strong>{validArticleRows.length} ligne{validArticleRows.length > 1 ? 's' : ''}</strong></div>
                </div>
                <div className={styles.amountReview}>
                  <div><span>Sous-total</span><strong>{formatCurrency(montantTotalArticles)}</strong></div>
                  <div><span>Montant payé</span><strong>{formatCurrency(montantPayeUSD)}</strong></div>
                  <div className={solde > 0 ? styles.amountWarning : styles.amountCurrent}>
                    <span>Solde éventuel</span><strong>{formatCurrency(solde)}</strong>
                  </div>
                </div>
                <div className={styles.summaryDestination} data-canal={formData.canal.toLowerCase()}>
                  <div><span>Encaisser sur</span><strong>{formData.canal === 'CAISSE' ? 'Caisse' : 'Banque'}</strong></div>
                  {formData.canal === 'BANQUE' && (
                    <div><span>Compte bancaire</span><strong>{selectedCompteLabel}</strong></div>
                  )}
                </div>
                <div className={styles.summaryRows}>
                  <div><span>Mode</span><strong>{modePaiementLabel[formData.mode_paiement]}</strong></div>
                  <div><span>Devise</span><strong>{formData.devise_perception}</strong></div>
                  <div><span>Statut prévu</span><strong>{expectedStatus}</strong></div>
                </div>
              </aside>
            )}
          </div>

          <div className={styles.formActions}>
            <button type="button" onClick={onClose} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>Annuler</button>
            <button type="button" onClick={handleCreateProforma} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>
              {activeSubmitAction === 'proforma' ? 'Génération en cours…' : 'Générer la pro forma'}
            </button>
            <button type="button" onClick={resetForm} className={styles.secondaryBtn} disabled={activeSubmitAction !== null}>Réinitialiser</button>
            <button type="submit" className={styles.primaryBtn} disabled={activeSubmitAction !== null}>
              {activeSubmitAction === 'submit' ? 'Enregistrement en cours…' : 'Enregistrer et valider'}
            </button>
          </div>
        </form>
      </div>
    </div>

    {/* Hors du formulaire à dessein : le règlement en porte un, et deux
        formulaires imbriqués ne sont pas du HTML valide. */}
    {payeurAuxNotes && (
      <NotesImpayeesPanel
        cible={payeurAuxNotes.cible}
        libelle={payeurAuxNotes.libelle}
        onClose={() => setPayeurAuxNotes(null)}
        onCreanceChange={({ total_du, nb_notes }) => {
          const creance = nb_notes > 0 ? { reste: total_du, notes: nb_notes } : null
          if (payeurAuxNotes.cible.expert_comptable_id) setCreanceExpert(creance)
          else setCreanceClient(creance)
        }}
      />
    )}
    </>
  )
}
