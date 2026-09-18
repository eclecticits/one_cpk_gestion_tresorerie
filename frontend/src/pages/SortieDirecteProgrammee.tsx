import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { format } from 'date-fns'
import {
  ArrowRight,
  AlertCircle,
  Banknote,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  FileText,
  Loader2,
  Pencil,
  Plus,
  Printer,
  ReceiptText,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  WalletCards,
  XCircle,
} from 'lucide-react'
import { getServices } from '../api/services'
import { getBudgetPostes } from '../api/budget'
import {
  listOrdresDecaissement,
  createOrdreDecaissement,
  updateOrdreDecaissement,
  annulerOrdreDecaissement,
} from '../api/ordresDecaissement'
import type { Service } from '../types'
import type { BudgetPosteSummary } from '../types/budget'
import type { OrdreDecaissement } from '../types'
import { toNumber } from '../utils/amount'
// jsPDF/jspdf-autotable sont lourds : chargement dynamique au moment de l'action.
type PdfGeneratorOrdreDirectModule = typeof import('../utils/pdfGeneratorOrdreDirect')
let _pdfGeneratorOrdreDirectModulePromise: Promise<PdfGeneratorOrdreDirectModule> | null = null
function loadPdfGeneratorOrdreDirectModule(): Promise<PdfGeneratorOrdreDirectModule> {
  if (!_pdfGeneratorOrdreDirectModulePromise) _pdfGeneratorOrdreDirectModulePromise = import('../utils/pdfGeneratorOrdreDirect')
  return _pdfGeneratorOrdreDirectModulePromise
}
const generateOrdreDirectPDF: PdfGeneratorOrdreDirectModule['generateOrdreDirectPDF'] = async (...args) => {
  const mod = await loadPdfGeneratorOrdreDirectModule()
  return mod.generateOrdreDirectPDF(...args)
}
import { useToast } from '../hooks/useToast'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import PageHeader from '../components/PageHeader'
import BackButton from '../components/BackButton'
import ResponsiveModal from '../components/ResponsiveModal'
import styles from './SortieDirecteProgrammee.module.css'

const LIMITE_USD = 100

interface LigneForm {
  clientId: string
  budget_poste_id: number | null
  description: string
  montant: string
}

let ligneSequence = 0
const emptyLigne = (): LigneForm => ({
  clientId: `direct-line-${++ligneSequence}`,
  budget_poste_id: null,
  description: '',
  montant: '',
})

const isLigneValid = (ligne: LigneForm) =>
  Boolean(ligne.budget_poste_id && Number.isFinite(parseFloat(ligne.montant)) && parseFloat(ligne.montant) > 0)

const fmtMontant = (v: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: devise === 'CDF' ? 'CDF' : 'USD' }).format(
    toNumber(v as any)
  )

const statutLabel = (s: string) =>
  s === 'PAYE' ? 'Payé par la caisse' : s === 'ANNULE' ? 'Annulé' : 'En attente caisse'

const personName = (u?: { prenom?: string | null; nom?: string | null; email?: string | null } | null) => {
  if (!u) return '—'
  const full = `${u.prenom || ''} ${u.nom || ''}`.trim()
  return full || u.email || '—'
}

export default function SortieDirecteProgrammee() {
  const { notifySuccess, notifyError, notifyWarning } = useToast()
  // Les bornes d'une collation sont réglées par l'organisation : l'écran les
  // annonce avant que le serveur ne refuse. Un plafond qu'on découvre au refus
  // n'est pas un garde-fou, c'est une porte fermée sans écriteau.
  const { settings } = useOrganisationSettings()
  const plafondParPersonne = toNumber(settings?.collation_plafond_par_personne_usd ?? 5)
  const plafondCollationTotal = toNumber(settings?.collation_plafond_total_usd ?? 100)
  const plafondCollation24h = toNumber(settings?.collation_plafond_24h_usd ?? 400)

  const [services, setServices] = useState<Service[]>([])
  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [ordres, setOrdres] = useState<OrdreDecaissement[]>([])
  const [ordersTotal, setOrdersTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [referencesLoading, setReferencesLoading] = useState(true)
  const [referencesError, setReferencesError] = useState<string | null>(null)
  const [ordersError, setOrdersError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [validationAttempted, setValidationAttempted] = useState(false)
  const [confirmationOpen, setConfirmationOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<OrdreDecaissement | null>(null)
  const [cancelTarget, setCancelTarget] = useState<OrdreDecaissement | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  const [cancelling, setCancelling] = useState(false)

  // Bon en attente de caisse qu'on corrige : son identifiant tant que le
  // formulaire sert à le reprendre, `null` quand il sert à en programmer un.
  const [ordreEnCorrection, setOrdreEnCorrection] = useState<string | null>(null)
  const [serviceId, setServiceId] = useState<string>('')
  const [beneficiaire, setBeneficiaire] = useState('')
  // Une collation ne se mesure pas au montant mais au prix par tête : le mode
  // ne dispense d'aucun contrôle, il change l'unité de ce qui est mesuré.
  const [typeSortie, setTypeSortie] = useState<'SIMPLE' | 'COLLATION'>('SIMPLE')
  const [reunionIntitule, setReunionIntitule] = useState('')
  const [reunionDate, setReunionDate] = useState(format(new Date(), 'yyyy-MM-dd'))
  const [participants, setParticipants] = useState('')
  const [montantParPersonne, setMontantParPersonne] = useState('')
  const [devise, setDevise] = useState<'USD' | 'CDF'>('USD')
  const [motif, setMotif] = useState('')
  const [lignes, setLignes] = useState<LigneForm[]>([emptyLigne()])
  const formRef = useRef<HTMLFormElement>(null)

  const postesById = useMemo(() => {
    const m = new Map<number, BudgetPosteSummary>()
    postes.forEach((p) => m.set(p.id, p))
    return m
  }, [postes])

  const selectedService = useMemo(
    () => services.find((service) => service.id === Number(serviceId)),
    [serviceId, services]
  )

  const estCollation = typeSortie === 'COLLATION'
  const nbParticipants = Number.isFinite(parseInt(participants, 10)) ? parseInt(participants, 10) : 0
  const prixParTete = Number.isFinite(parseFloat(montantParPersonne)) ? parseFloat(montantParPersonne) : 0

  /** Le total d'une collation est DÉRIVÉ, jamais tapé : c'est ce qui le rend
   *  vérifiable, et c'est aussi ce que le serveur recalcule de son côté. */
  const total = useMemo(
    () =>
      estCollation
        ? Math.round(nbParticipants * prixParTete * 100) / 100
        : lignes.reduce((sum, l) => sum + (Number.isFinite(parseFloat(l.montant)) ? parseFloat(l.montant) : 0), 0),
    [estCollation, nbParticipants, prixParTete, lignes]
  )

  /** Le plafond qui s'applique, et ce qui le fait dépasser. Deux bornes pour
   *  une collation : le prix par tête dit que c'en est bien une, le total dit
   *  qu'elle reste une sortie directe. */
  const plafondActif = estCollation ? plafondCollationTotal : LIMITE_USD
  const prixParTeteDepasse = estCollation && devise === 'USD' && prixParTete > plafondParPersonne

  const formIsDirty = useMemo(
    () => Boolean(
      serviceId ||
      beneficiaire.trim() ||
      motif.trim() ||
      lignes.some((ligne) => ligne.budget_poste_id || ligne.description.trim() || ligne.montant.trim())
    ),
    [beneficiaire, lignes, motif, serviceId]
  )

  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'TOUS' | 'AUTORISE' | 'PAYE' | 'ANNULE'>('TOUS')

  const ordreStats = useMemo(
    () => ({
      pending: ordres.filter((ordre) => ordre.statut === 'AUTORISE').length,
      paid: ordres.filter((ordre) => ordre.statut === 'PAYE').length,
      cancelled: ordres.filter((ordre) => ordre.statut === 'ANNULE').length,
    }),
    [ordres]
  )

  const filteredOrdres = useMemo(() => {
    const query = searchTerm.trim().toLocaleLowerCase('fr')
    return ordres.filter((ordre) => {
      if (statusFilter !== 'TOUS' && ordre.statut !== statusFilter) return false
      if (!query) return true
      const searchable = [
        ordre.numero_ordre,
        ordre.beneficiaire,
        ordre.motif,
        personName(ordre.autorise_par_user),
      ]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase('fr')
      return searchable.includes(query)
    })
  }, [ordres, searchTerm, statusFilter])

  const loadOrdres = useCallback(async () => {
    setLoading(true)
    setOrdersError(null)
    try {
      const res = await listOrdresDecaissement({ sans_requisition: true, limit: 100 })
      setOrdres(res.items || [])
      setOrdersTotal(res.total || (res.items || []).length)
    } catch (err) {
      console.error('Erreur chargement sorties directes:', err)
      setOrdersError('Impossible de charger les sorties directes. Vérifiez votre connexion puis réessayez.')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadReferences = useCallback(async () => {
    setReferencesLoading(true)
    setReferencesError(null)
    try {
      const [srv, bud] = await Promise.all([
        getServices({ active: true }),
        getBudgetPostes({ type: 'DEPENSE', active: true }),
      ])
      setServices(Array.isArray(srv) ? srv : [])
      setPostes(bud?.postes || [])
    } catch (err) {
      console.error('Erreur chargement données:', err)
      setReferencesError('Les services et postes budgétaires n’ont pas pu être chargés.')
    } finally {
      setReferencesLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadReferences()
    void loadOrdres()
  }, [loadOrdres, loadReferences])

  const updateLigne = (index: number, field: keyof LigneForm, value: string) => {
    setLignes((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: field === 'budget_poste_id' ? (value ? Number(value) : null) : value }
      return next
    })
  }

  const addLigne = () => setLignes((prev) => [...prev, emptyLigne()])
  const removeLigne = (index: number) =>
    setLignes((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev))

  const resetForm = () => {
    setOrdreEnCorrection(null)
    setServiceId('')
    setBeneficiaire('')
    setMotif('')
    setDevise('USD')
    setLignes([emptyLigne()])
    setTypeSortie('SIMPLE')
    setReunionIntitule('')
    setReunionDate(format(new Date(), 'yyyy-MM-dd'))
    setParticipants('')
    setMontantParPersonne('')
    setValidationAttempted(false)
  }

  /**
   * Reprend un bon que la caisse n'a pas encore payé.
   *
   * Rien n'a bougé tant qu'il est en attente : ni trésorerie, ni budget. Le
   * corriger vaut mieux que l'annuler et le ressaisir, qui laissait deux pièces
   * au journal pour une seule dépense. Le serveur rejoue de toute façon le
   * plafond et le cumul anti-fractionnement.
   */
  const corrigerOrdre = (ordre: OrdreDecaissement) => {
    const brut = ordre as any
    setOrdreEnCorrection(String(ordre.id))
    setServiceId(brut.service_id ? String(brut.service_id) : '')
    setBeneficiaire(brut.beneficiaire || '')
    setMotif(brut.motif || '')
    setDevise((brut.devise === 'CDF' ? 'CDF' : 'USD') as 'USD' | 'CDF')
    // La correction rejoue tous les contrôles : reprendre une collation sans
    // son type en ferait une sortie simple de 200 USD, aussitôt refusée.
    const collation = String(brut.type_sortie || 'SIMPLE').toUpperCase() === 'COLLATION'
    setTypeSortie(collation ? 'COLLATION' : 'SIMPLE')
    setReunionIntitule(collation ? String(brut.reunion_intitule || '') : '')
    setReunionDate(collation && brut.reunion_date ? String(brut.reunion_date).slice(0, 10) : format(new Date(), 'yyyy-MM-dd'))
    setParticipants(collation && brut.participants ? String(brut.participants) : '')
    setMontantParPersonne(collation ? String(toNumber(brut.montant_par_personne) || '') : '')
    const reprises: LigneForm[] = Array.isArray(brut.lignes)
      ? brut.lignes.map((l: any) => ({
          clientId: emptyLigne().clientId,
          budget_poste_id: l?.budget_poste_id ? Number(l.budget_poste_id) : null,
          description: String(l?.description || ''),
          montant: String(toNumber(l?.montant_total ?? l?.montant) || ''),
        }))
      : []
    // Un ordre sans répartition garde son montant sur une ligne unique, sinon
    // le total retomberait à zéro et le formulaire refuserait de l'enregistrer.
    setLignes(
      reprises.length > 0
        ? reprises
        : [{ ...emptyLigne(), budget_poste_id: null, description: brut.motif || '', montant: String(toNumber(brut.montant) || '') }]
    )
    window.requestAnimationFrame(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const requestCorrection = (ordre: OrdreDecaissement) => {
    if (ordreEnCorrection === String(ordre.id)) {
      window.requestAnimationFrame(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
      return
    }
    if (formIsDirty) {
      setEditTarget(ordre)
      return
    }
    corrigerOrdre(ordre)
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setValidationAttempted(true)
    if (!serviceId) {
      notifyWarning('Service requis', 'Choisissez le service / la commission responsable.')
      return
    }
    if (!beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Saisissez le bénéficiaire.')
      return
    }
    if (!estCollation && !motif.trim()) {
      notifyWarning('Motif requis', 'Précisez le motif de cette dépense directe.')
      return
    }
    if (estCollation) {
      if (!reunionIntitule.trim()) {
        notifyWarning('Motif requis', "Nommez la réunion : c'est elle qui justifie le nombre de têtes.")
        return
      }
      if (!reunionDate) {
        notifyWarning('Date requise', 'Indiquez la date de la réunion.')
        return
      }
      if (nbParticipants < 1) {
        notifyWarning('Participants requis', 'Indiquez le nombre de participants.')
        return
      }
      if (prixParTete <= 0) {
        notifyWarning('Montant par personne requis', 'Indiquez ce que coûte une collation par personne.')
        return
      }
      if (!lignes[0]?.budget_poste_id) {
        notifyWarning('Poste requis', 'Choisissez le poste budgétaire de la collation.')
        return
      }
    } else {
      const lignesValides = lignes.filter(isLigneValid)
      if (lignesValides.length !== lignes.length) {
        notifyWarning('Lignes incomplètes', 'Chaque ligne doit avoir un poste budgétaire et un montant positif.')
        return
      }
    }
    if (total <= 0) {
      notifyWarning('Montant invalide', 'Le total doit être supérieur à 0.')
      return
    }
    if (devise === 'USD' && prixParTeteDepasse) {
      notifyWarning(
        'Prix par personne trop élevé',
        `Une collation est limitée à ${plafondParPersonne} $ par personne. Au-delà, créez une réquisition.`,
      )
      return
    }
    if (devise === 'USD' && total > plafondActif) {
      notifyWarning(
        'Plafond dépassé',
        estCollation
          ? `Collation limitée à ${plafondCollationTotal} $ au total. Au-delà, créez une réquisition.`
          : `Sortie directe limitée à ${LIMITE_USD} $. Au-delà, créez une réquisition.`,
      )
      return
    }

    setConfirmationOpen(true)
  }

  const confirmSubmit = async () => {
    // Une collation tient sur une ligne : le poste, et le total que les têtes
    // produisent. Répartir une collation sur plusieurs postes reviendrait à
    // servir deux salles sous un seul ordre.
    const lignesValides = estCollation
      ? lignes.slice(0, 1).filter((l) => Boolean(l.budget_poste_id))
      : lignes.filter(isLigneValid)
    if ((!estCollation && lignesValides.length !== lignes.length) || lignesValides.length === 0) {
      setConfirmationOpen(false)
      notifyWarning('Lignes incomplètes', 'Vérifiez les lignes budgétaires avant de continuer.')
      return
    }
    const submittedTotal = estCollation
      ? total
      : lignesValides.reduce((sum, ligne) => sum + parseFloat(ligne.montant), 0)
    setSubmitting(true)
    try {
      const corps = {
        beneficiaire: beneficiaire.trim(),
        montant: submittedTotal,
        devise,
        // En collation, le motif est le libellé saisi plus haut : l'ordre
        // porte alors exactement ce que l'agent a écrit, et non une phrase
        // reconstituée.
        motif: estCollation ? reunionIntitule.trim() : (motif.trim() || null),
        type_sortie: typeSortie,
        reunion_intitule: estCollation ? reunionIntitule.trim() : null,
        reunion_date: estCollation ? reunionDate : null,
        participants: estCollation ? nbParticipants : null,
        montant_par_personne: estCollation ? prixParTete : null,
        service_id: Number(serviceId),
        lignes: lignesValides.map((l) => ({
          budget_poste_id: l.budget_poste_id,
          rubrique: l.budget_poste_id ? postesById.get(l.budget_poste_id)?.code || '' : '',
          description: estCollation ? reunionIntitule.trim() : l.description.trim(),
          montant_total: estCollation ? submittedTotal : parseFloat(l.montant),
          devise,
        })),
      }
      if (ordreEnCorrection) {
        await updateOrdreDecaissement(ordreEnCorrection, corps)
        notifySuccess(
          'Sortie directe corrigée',
          `${fmtMontant(submittedTotal, devise)} pour ${beneficiaire.trim()} — toujours en attente de la caisse.`
        )
      } else {
        await createOrdreDecaissement(corps)
        notifySuccess(
          'Sortie directe programmée',
          `${fmtMontant(submittedTotal, devise)} pour ${beneficiaire.trim()} — en attente de paiement par la caisse.`
        )
      }
      setConfirmationOpen(false)
      resetForm()
      await loadOrdres()
    } catch (err: any) {
      notifyError(
        'Erreur',
        err?.message ||
          (ordreEnCorrection
            ? 'Impossible de corriger cette sortie directe.'
            : 'Impossible de programmer cette sortie directe.')
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handlePrint = async (ordre: OrdreDecaissement) => {
    try {
      const serviceId = Number((ordre as any).service_id)
      const service = Number.isFinite(serviceId) ? services.find((s) => s.id === serviceId) : undefined
      const posteLabels = new Map<number, string>()
      postes.forEach((p) => posteLabels.set(p.id, `${p.code} - ${p.libelle}`))
      await generateOrdreDirectPDF(ordre, {
        serviceLabel: service ? `${service.code} — ${service.libelle}` : undefined,
        posteLabels,
      })
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible de générer le bon d'ordre.")
    }
  }

  const handleCancel = (ordre: OrdreDecaissement) => {
    setCancelTarget(ordre)
    setCancelReason('')
  }

  const confirmCancel = async () => {
    if (!cancelTarget || cancelReason.trim().length < 3) return
    setCancelling(true)
    try {
      await annulerOrdreDecaissement(String(cancelTarget.id), cancelReason.trim())
      notifySuccess('Ordre annulé', `L'ordre ${cancelTarget.numero_ordre} a été annulé.`)
      setCancelTarget(null)
      setCancelReason('')
      await loadOrdres()
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible d'annuler cet ordre.")
    } finally {
      setCancelling(false)
    }
  }

  const capDepasse = devise === 'USD' && (total > plafondActif || prixParTeteDepasse)
  const limitProgress = devise === 'USD' ? Math.min((total / plafondActif) * 100, 100) : 0

  return (
    <div className={styles.container}>
      <PageHeader
        title="Sortie directe programmée"
        subtitle="Préparez une dépense de faible montant, envoyée directement à la caisse pour paiement, sans réquisition."
        actions={<BackButton fallback="/requisitions" />}
      />

      <section className={styles.contextPanel} aria-label="Fonctionnement de la sortie directe">
        <div className={styles.contextIntro}>
          <span className={styles.contextIcon}><WalletCards size={22} aria-hidden="true" /></span>
          <div>
            <span className={styles.eyebrow}>Circuit de paiement court</span>
            <h2>De la programmation à la caisse, sans étape intermédiaire</h2>
            <p>Préparez une dépense ponctuelle et transmettez un ordre complet, prêt à être payé.</p>
          </div>
        </div>
        <div className={styles.flow} aria-label="Étapes du traitement">
          <span><strong>1</strong> Programmer</span>
          <ArrowRight size={15} aria-hidden="true" />
          <span><strong>2</strong> Transmettre</span>
          <ArrowRight size={15} aria-hidden="true" />
          <span><strong>3</strong> Payer en caisse</span>
        </div>
        <div className={styles.limitCard}>
          <CircleDollarSign size={20} aria-hidden="true" />
          <div><span>Plafond en USD</span><strong>{LIMITE_USD} $</strong></div>
        </div>
      </section>

      <form ref={formRef} className={styles.formCard} onSubmit={handleSubmit} noValidate>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}><ReceiptText size={20} aria-hidden="true" /></span>
          <div>
            <span className={styles.eyebrow}>{ordreEnCorrection ? 'Correction' : 'Nouvel ordre'}</span>
            <h2>{ordreEnCorrection ? 'Corriger une sortie directe' : 'Programmer une sortie directe'}</h2>
            <p>
              {ordreEnCorrection
                ? "Ce bon n'est pas encore payé : le plafond et le contrôle anti-fractionnement sont rejoués à l'enregistrement."
                : 'Les champs marqués d’un astérisque sont obligatoires.'}
            </p>
          </div>
        </div>

        <div className={styles.formBody}>
          {referencesError && (
            <div className={styles.inlineError} role="alert">
              <AlertCircle size={19} aria-hidden="true" />
              <div><strong>Référentiels indisponibles</strong><span>{referencesError}</span></div>
              <button type="button" onClick={() => void loadReferences()}>
                <RefreshCw size={15} aria-hidden="true" /> Réessayer
              </button>
            </div>
          )}
          {/* Deux natures de sortie directe, deux unités de mesure. Le montant
              borne la première ; le prix par tête borne la seconde, parce que
              quarante participants à cinq dollars restent une collation que le
              plafond de montant refuserait pourtant. */}
          <div className={styles.modeSwitch} role="group" aria-label="Nature de la sortie directe">
            <button
              type="button"
              className={!estCollation ? styles.modeActif : styles.modeInactif}
              aria-pressed={!estCollation}
              onClick={() => setTypeSortie('SIMPLE')}
            >
              Sortie directe simple
              <small>Plafond {LIMITE_USD} $ par ordre</small>
            </button>
            <button
              type="button"
              className={estCollation ? styles.modeActif : styles.modeInactif}
              aria-pressed={estCollation}
              onClick={() => {
                setTypeSortie('COLLATION')
                // Le tarif réglé est le cas courant : le proposer évite une
                // frappe, sans empêcher de descendre en dessous.
                if (!montantParPersonne) setMontantParPersonne(String(plafondParPersonne))
              }}
            >
              Collation de réunion
              <small>
                {plafondParPersonne} $ par personne, {plafondCollationTotal} $ par réunion,
                {' '}{plafondCollation24h} $ sur 24 h
              </small>
            </button>
          </div>

          <div className={styles.identityGrid}>
            <div className={styles.field}>
              <label htmlFor="direct-service">Service / commission <span aria-hidden="true">*</span></label>
              <select id="direct-service" value={serviceId} onChange={(e) => setServiceId(e.target.value)} disabled={referencesLoading || Boolean(referencesError)} required aria-required="true">
                <option value="">{referencesLoading ? 'Chargement des services…' : 'Choisir le service responsable'}</option>
                {services.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} — {s.libelle}
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label htmlFor="direct-beneficiary">Bénéficiaire <span aria-hidden="true">*</span></label>
              <input id="direct-beneficiary" value={beneficiaire} onChange={(e) => setBeneficiaire(e.target.value)} placeholder="Nom complet ou raison sociale" required aria-required="true" />
            </div>
            <div className={`${styles.field} ${styles.currencyField}`}>
              <label htmlFor="direct-currency">Devise</label>
              <select id="direct-currency" value={devise} onChange={(e) => setDevise(e.target.value as 'USD' | 'CDF')}>
                <option value="USD">USD — Dollar</option>
                <option value="CDF">CDF — Franc congolais</option>
              </select>
            </div>
          </div>

          {estCollation && (
            <div className={styles.collationGrid}>
              {/* Ce champ EST le motif de la dépense, et c'est aussi ce qui
                  regroupe les collations d'une même réunion sous un seul
                  plafond : deux formulations d'une même salle feraient deux
                  salles. D'où l'exemple, qui pousse à nommer la réunion. */}
              <div className={styles.field}>
                <label htmlFor="direct-reunion">Motif de la dépense <span aria-hidden="true">*</span></label>
                <input
                  id="direct-reunion"
                  value={reunionIntitule}
                  onChange={(e) => setReunionIntitule(e.target.value)}
                  placeholder="Ex. : Collation du Conseil d'administration"
                  required
                  aria-required="true"
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="direct-reunion-date">Date de la réunion <span aria-hidden="true">*</span></label>
                <input
                  id="direct-reunion-date"
                  type="date"
                  value={reunionDate}
                  onChange={(e) => setReunionDate(e.target.value)}
                  required
                  aria-required="true"
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="direct-participants">Participants <span aria-hidden="true">*</span></label>
                <input
                  id="direct-participants"
                  type="number"
                  min="1"
                  step="1"
                  value={participants}
                  onChange={(e) => setParticipants(e.target.value)}
                  placeholder="0"
                  required
                  aria-required="true"
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="direct-par-personne">Montant par personne ({devise}) <span aria-hidden="true">*</span></label>
                <input
                  id="direct-par-personne"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={montantParPersonne}
                  onChange={(e) => setMontantParPersonne(e.target.value)}
                  placeholder="0,00"
                  aria-invalid={prixParTeteDepasse}
                  required
                  aria-required="true"
                />
                {prixParTeteDepasse && (
                  <small className={styles.fieldError}>
                    Au-delà de {plafondParPersonne} $ par personne, ce n'est plus une collation : créez une réquisition.
                  </small>
                )}
              </div>
              {/* Le total ne se tape pas : il se lit. C'est ce qui le rend
                  vérifiable, et c'est ce que le serveur recalcule de son côté. */}
              <div className={styles.collationTotal} aria-live="polite">
                <span>{nbParticipants || 0} × {fmtMontant(prixParTete, devise)}</span>
                <strong>{fmtMontant(total, devise)}</strong>
              </div>
            </div>
          )}

          <div className={styles.linesSection}>
            <div className={styles.linesHeader}>
              <div>
                <h3>
                  {estCollation ? 'Imputation budgétaire' : 'Lignes budgétaires'}
                  {!estCollation && <span className={styles.countBadge}>{lignes.length}</span>}
                </h3>
                <p>
                  {estCollation
                    ? "Une collation tient sur une ligne : le poste, et le total que les têtes produisent."
                    : 'Ventilez précisément la dépense sur les postes concernés.'}
                </p>
              </div>
              {!estCollation && (
                <button type="button" className={styles.addBtn} onClick={addLigne}>
                  <Plus size={16} aria-hidden="true" /> Ajouter une ligne
                </button>
              )}
            </div>

            <div className={styles.linesList}>
              {(estCollation ? lignes.slice(0, 1) : lignes).map((ligne, index) => (
                <div key={ligne.clientId} className={`${styles.lineItem} ${validationAttempted && !(estCollation ? Boolean(ligne.budget_poste_id) : isLigneValid(ligne)) ? styles.lineInvalid : ''}`}>
                  <span className={styles.lineNumber} aria-label={`Ligne ${index + 1}`}>{index + 1}</span>
                  <div className={`${styles.lineField} ${styles.budgetField}`}>
                    <label htmlFor={`direct-budget-${index}`}>Poste budgétaire <span aria-hidden="true">*</span></label>
                    <select
                      id={`direct-budget-${index}`}
                      value={ligne.budget_poste_id ?? ''}
                      onChange={(e) => updateLigne(index, 'budget_poste_id', e.target.value)}
                      disabled={referencesLoading || Boolean(referencesError)}
                      aria-invalid={validationAttempted && !ligne.budget_poste_id}
                      aria-describedby={validationAttempted && !ligne.budget_poste_id ? `direct-budget-error-${index}` : undefined}
                      aria-required="true"
                      required
                    >
                      <option value="">{referencesLoading ? 'Chargement des postes…' : 'Choisir un poste'}</option>
                      {postes.map((poste) => (
                        <option key={poste.id} value={poste.id}>
                          {poste.code} — {poste.libelle} (disp. {fmtMontant(poste.montant_disponible, 'USD')})
                        </option>
                      ))}
                    </select>
                    {validationAttempted && !ligne.budget_poste_id && <small id={`direct-budget-error-${index}`} className={styles.fieldError}>Sélectionnez un poste.</small>}
                  </div>
                  {/* En collation, la description EST le motif : deux champs
                      pour une même phrase finiraient par se contredire, et
                      c'est la description qui part sur la pièce. */}
                  <div className={`${styles.lineField} ${styles.descriptionField}`}>
                    <label htmlFor={`direct-description-${index}`}>Description</label>
                    <input
                      id={`direct-description-${index}`}
                      value={estCollation ? reunionIntitule : ligne.description}
                      onChange={(e) => updateLigne(index, 'description', e.target.value)}
                      placeholder="Détail de la dépense"
                      disabled={estCollation}
                      title={estCollation ? 'Reprend le motif de la dépense' : undefined}
                    />
                  </div>
                  <div className={`${styles.lineField} ${styles.amountField}`}>
                    <label htmlFor={`direct-amount-${index}`}>Montant ({devise}) <span aria-hidden="true">*</span></label>
                    <input
                      id={`direct-amount-${index}`}
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={estCollation ? (total || '') : ligne.montant}
                      onChange={(e) => updateLigne(index, 'montant', e.target.value)}
                      placeholder="0,00"
                      disabled={estCollation}
                      title={estCollation ? 'Produit du nombre de participants par le montant par personne' : undefined}
                      aria-invalid={!estCollation && validationAttempted && !(parseFloat(ligne.montant) > 0)}
                      aria-describedby={!estCollation && validationAttempted && !(parseFloat(ligne.montant) > 0) ? `direct-amount-error-${index}` : undefined}
                      aria-required="true"
                      required={!estCollation}
                    />
                    {!estCollation && validationAttempted && !(parseFloat(ligne.montant) > 0) && <small id={`direct-amount-error-${index}`} className={styles.fieldError}>Saisissez un montant positif.</small>}
                  </div>
                  {!estCollation && (
                  <button
                    type="button"
                    className={styles.removeBtn}
                    onClick={() => removeLigne(index)}
                    disabled={lignes.length === 1}
                    title="Retirer cette ligne"
                    aria-label={`Retirer la ligne ${index + 1}`}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Une collation dit déjà son motif plus haut : le redemander ici
              ferait recopier la même phrase, et deux motifs pour une dépense
              finiraient par se contredire. */}
          {!estCollation && (
          <div className={styles.field}>
            <label htmlFor="direct-reason">Motif de la dépense <span aria-hidden="true">*</span></label>
            <textarea
              id="direct-reason"
              rows={2}
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              placeholder="Ex. : achat urgent de fournitures pour la commission…"
              required
              aria-required="true"
            />
          </div>
          )}
        </div>

        <div className={styles.formFooter}>
          <div className={styles.controlSummary}>
            {devise === 'USD' ? (
              <div className={styles.limitProgress}>
                <div className={styles.progressLabels}>
                  <span>{capDepasse ? 'Plafond dépassé' : 'Plafond disponible'}</span>
                  <strong>{Math.max(plafondActif - total, 0).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} $ restant</strong>
                </div>
                <div
                  className={styles.progressTrack}
                  role="progressbar"
                  aria-label="Utilisation du plafond de sortie directe"
                  aria-valuemin={0}
                  aria-valuemax={plafondActif}
                  aria-valuenow={Math.min(total, plafondActif)}
                >
                  <span
                    className={`${styles.progressFill} ${capDepasse ? styles.progressOver : ''}`}
                    style={{ width: `${limitProgress}%` }}
                  />
                </div>
              </div>
            ) : (
              <div className={styles.cdfNotice}>
                <CircleDollarSign size={18} aria-hidden="true" />
                <span>L’équivalent de {plafondActif} USD sera contrôlé au taux de change actif lors de la transmission.</span>
              </div>
            )}
            <div className={styles.securityNote}>
              <ShieldCheck size={17} aria-hidden="true" />
              <span>L’ordre part directement à la caisse et reste corrigeable uniquement avant son paiement.</span>
            </div>
          </div>

          <div className={`${styles.totalPanel} ${capDepasse ? styles.totalOver : ''}`} aria-live="polite">
            <span>Total de l’ordre</span>
            <strong>{fmtMontant(total, devise)}</strong>
            {capDepasse && (
              <small>
                {prixParTeteDepasse
                  ? `Dépasse ${plafondParPersonne} $ par personne`
                  : `Dépasse le plafond autorisé de ${plafondActif} $`}
              </small>
            )}
            <button type="submit" className={styles.submitBtn} disabled={submitting || capDepasse || referencesLoading || Boolean(referencesError)}>
              {submitting ? <Loader2 className={styles.spin} size={18} aria-hidden="true" /> : <Banknote size={18} aria-hidden="true" />}
              {submitting
                ? ordreEnCorrection ? 'Enregistrement…' : 'Programmation…'
                : ordreEnCorrection ? 'Enregistrer les corrections' : 'Programmer et transmettre'}
            </button>
            {ordreEnCorrection && (
              <button type="button" className={styles.ghostBtn} onClick={resetForm} disabled={submitting}>
                Abandonner la correction
              </button>
            )}
          </div>
        </div>
      </form>

      <section className={styles.historyCard}>
        <div className={styles.historyHeader}>
          <div className={styles.sectionHeaderCompact}>
            <span className={styles.sectionIcon}><FileText size={20} aria-hidden="true" /></span>
            <div>
              <span className={styles.eyebrow}>Suivi</span>
              <h2>Ordres récents</h2>
              <p className={styles.historyScope}>
                {ordersTotal > ordres.length
                  ? `${ordres.length} derniers ordres affichés sur ${ordersTotal}`
                  : `${ordres.length} ordre${ordres.length === 1 ? '' : 's'} chargé${ordres.length === 1 ? '' : 's'}`}
                {' '}— compteurs et recherche sur les éléments affichés
              </p>
            </div>
          </div>
          <div className={styles.statusSummary} aria-label="Résumé des statuts">
            <span className={styles.summaryPending}><Clock3 size={14} /> {ordreStats.pending} en attente</span>
            <span className={styles.summaryPaid}><CheckCircle2 size={14} /> {ordreStats.paid} payée{ordreStats.paid > 1 ? 's' : ''}</span>
            <span className={styles.summaryCancelled}><XCircle size={14} /> {ordreStats.cancelled} annulée{ordreStats.cancelled > 1 ? 's' : ''}</span>
          </div>
        </div>

        <div className={styles.historyToolbar}>
          <div className={styles.searchField}>
            <Search size={17} aria-hidden="true" />
            <label htmlFor="direct-search" className={styles.srOnly}>Rechercher une sortie directe</label>
            <input
              id="direct-search"
              type="search"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Rechercher dans les ordres affichés…"
            />
          </div>
          <label className={styles.filterField}>
            <span>Statut</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}>
              <option value="TOUS">Tous les statuts</option>
              <option value="AUTORISE">En attente caisse</option>
              <option value="PAYE">Payé</option>
              <option value="ANNULE">Annulé</option>
            </select>
          </label>
        </div>

        {ordersError ? (
          <div className={styles.errorState} role="alert">
            <AlertCircle size={24} aria-hidden="true" />
            <h3>Historique indisponible</h3>
            <p>{ordersError}</p>
            <button type="button" onClick={() => void loadOrdres()}>
              <RefreshCw size={15} aria-hidden="true" /> Réessayer
            </button>
          </div>
        ) : loading && ordres.length === 0 ? (
          <div className={styles.loadingState}><Loader2 className={styles.spin} size={22} /> Chargement des ordres…</div>
        ) : filteredOrdres.length === 0 ? (
          <div className={styles.emptyState}>
            <span><ReceiptText size={24} aria-hidden="true" /></span>
            <h3>{ordres.length === 0 ? 'Aucune sortie directe programmée' : 'Aucun résultat'}</h3>
            <p>{ordres.length === 0 ? 'Les ordres créés apparaîtront ici pour leur suivi et leur impression.' : 'Modifiez votre recherche ou le filtre de statut.'}</p>
            {ordres.length > 0 && (
              <button type="button" onClick={() => { setSearchTerm(''); setStatusFilter('TOUS') }}>Réinitialiser les filtres</button>
            )}
          </div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className={styles.srOnly}>Historique des sorties directes programmées</caption>
              <thead>
                <tr>
                  <th scope="col">N° ordre</th>
                  <th scope="col">Bénéficiaire</th>
                  <th scope="col">Programmé par</th>
                  <th scope="col">Montant</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Programmé le</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrdres.map((o) => (
                  <tr key={o.id}>
                    <td data-label="N° ordre"><strong className={styles.orderNumber}>{o.numero_ordre}</strong></td>
                    <td data-label="Bénéficiaire">
                      <strong className={styles.beneficiary}>{o.beneficiaire}</strong>
                      {o.motif && <div className={styles.subtle}>{o.motif}</div>}
                    </td>
                    <td data-label="Programmé par">{personName(o.autorise_par_user)}</td>
                    <td data-label="Montant"><strong className={styles.amount}>{fmtMontant(o.montant, String(o.devise))}</strong></td>
                    <td data-label="Statut">
                      <span className={`${styles.badge} ${styles['b_' + String(o.statut)] || ''}`}>{statutLabel(String(o.statut))}</span>
                    </td>
                    <td data-label="Programmé le" className={styles.dateCell}>{o.autorise_le ? format(new Date(o.autorise_le), 'dd/MM/yyyy HH:mm') : '—'}</td>
                    <td data-label="Actions">
                      <div className={styles.rowActions}>
                        <button
                          type="button"
                          className={styles.printBtn}
                          onClick={() => handlePrint(o)}
                          title="Imprimer le bon de sortie directe pour signature"
                          aria-label={`Imprimer l'ordre ${o.numero_ordre}`}
                        >
                          <Printer size={15} aria-hidden="true" /> Imprimer
                        </button>
                        {o.statut === 'AUTORISE' && (
                          <button
                            type="button"
                            className={styles.editBtn}
                            onClick={() => requestCorrection(o)}
                            title="Corriger ce bon : la caisse ne l'a pas encore payé"
                          >
                            <Pencil size={15} aria-hidden="true" /> Modifier
                          </button>
                        )}
                        {o.statut === 'AUTORISE' && (
                          <button type="button" className={styles.cancelBtn} onClick={() => handleCancel(o)}>
                            <XCircle size={15} aria-hidden="true" /> Annuler
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ResponsiveModal
        isOpen={confirmationOpen}
        onClose={() => { if (!submitting) setConfirmationOpen(false) }}
        title={ordreEnCorrection ? 'Confirmer les corrections' : 'Confirmer la programmation'}
        size="sm"
        footer={
          <div className={styles.modalActions}>
            <button type="button" className={styles.modalSecondaryBtn} onClick={() => setConfirmationOpen(false)} disabled={submitting}>
              Revenir au formulaire
            </button>
            <button type="button" className={styles.modalPrimaryBtn} onClick={confirmSubmit} disabled={submitting}>
              {submitting ? <Loader2 className={styles.spin} size={17} aria-hidden="true" /> : <Banknote size={17} aria-hidden="true" />}
              {submitting ? 'Transmission…' : ordreEnCorrection ? 'Enregistrer' : 'Confirmer et transmettre'}
            </button>
          </div>
        }
      >
        <div className={styles.confirmContent}>
          <div className={styles.confirmNotice}>
            <ShieldCheck size={19} aria-hidden="true" />
            <p>
              {ordreEnCorrection
                ? 'Vérifiez les informations corrigées avant de les renvoyer à la caisse.'
                : 'Cet ordre sera immédiatement disponible à la caisse. Il restera corrigeable uniquement tant qu’il n’est pas payé.'}
            </p>
          </div>
          <dl className={styles.confirmList}>
            <div><dt>Service</dt><dd>{selectedService ? `${selectedService.code} — ${selectedService.libelle}` : '—'}</dd></div>
            <div><dt>Bénéficiaire</dt><dd>{beneficiaire || '—'}</dd></div>
            <div><dt>Imputations</dt><dd>{lignes.length} ligne{lignes.length > 1 ? 's' : ''} budgétaire{lignes.length > 1 ? 's' : ''}</dd></div>
            <div className={styles.confirmTotal}><dt>Total à transmettre</dt><dd>{fmtMontant(total, devise)}</dd></div>
          </dl>
          <div className={styles.confirmLines}>
            <h3>Détail des imputations</h3>
            {lignes.map((ligne) => {
              const poste = ligne.budget_poste_id ? postesById.get(ligne.budget_poste_id) : undefined
              return (
                <div key={ligne.clientId}>
                  <span>
                    <strong>{poste ? `${poste.code} — ${poste.libelle}` : 'Poste non renseigné'}</strong>
                    {ligne.description && <small>{ligne.description}</small>}
                  </span>
                  <b>{fmtMontant(ligne.montant, devise)}</b>
                </div>
              )
            })}
          </div>
        </div>
      </ResponsiveModal>

      <ResponsiveModal
        isOpen={Boolean(editTarget)}
        onClose={() => setEditTarget(null)}
        title="Remplacer la saisie en cours ?"
        size="sm"
        footer={
          <div className={styles.modalActions}>
            <button type="button" className={styles.modalSecondaryBtn} onClick={() => setEditTarget(null)}>
              Garder mon brouillon
            </button>
            <button
              type="button"
              className={styles.modalDangerBtn}
              onClick={() => {
                if (editTarget) corrigerOrdre(editTarget)
                setEditTarget(null)
              }}
            >
              Remplacer et modifier
            </button>
          </div>
        }
      >
        <div className={styles.replaceWarning}>
          <AlertCircle size={20} aria-hidden="true" />
          <p>Les informations déjà saisies seront remplacées par celles de l’ordre <strong>{editTarget?.numero_ordre}</strong>.</p>
        </div>
      </ResponsiveModal>

      <ResponsiveModal
        isOpen={Boolean(cancelTarget)}
        onClose={() => { if (!cancelling) setCancelTarget(null) }}
        title={`Annuler ${cancelTarget?.numero_ordre || "l'ordre"}`}
        size="sm"
        footer={
          <div className={styles.modalActions}>
            <button type="button" className={styles.modalSecondaryBtn} onClick={() => setCancelTarget(null)} disabled={cancelling}>
              Conserver l’ordre
            </button>
            <button type="button" className={styles.modalDangerBtn} onClick={confirmCancel} disabled={cancelling || cancelReason.trim().length < 3}>
              {cancelling ? <Loader2 className={styles.spin} size={17} aria-hidden="true" /> : <XCircle size={17} aria-hidden="true" />}
              {cancelling ? 'Annulation…' : 'Confirmer l’annulation'}
            </button>
          </div>
        }
      >
        <div className={styles.cancelContent}>
          <p>Indiquez pourquoi cet ordre ne doit plus être présenté à la caisse.</p>
          <label htmlFor="direct-cancel-reason">Motif d’annulation <span aria-hidden="true">*</span></label>
          <textarea
            id="direct-cancel-reason"
            rows={4}
            value={cancelReason}
            onChange={(event) => setCancelReason(event.target.value)}
            placeholder="Saisissez un motif précis (3 caractères minimum)…"
            aria-describedby="direct-cancel-help"
            aria-required="true"
            required
          />
          <small id="direct-cancel-help">{cancelReason.trim().length}/3 caractères minimum</small>
        </div>
      </ResponsiveModal>
    </div>
  )
}
