import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Banknote,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileSpreadsheet,
  FileText,
  History,
  Landmark,
  ListFilter,
  Scale,
  WalletCards,
} from 'lucide-react'
import {
  createCloture,
  getClotureBalance,
  getClotureCaissiers,
  getCloturePdfData,
  listClotures,
  listCloturesWithFilters,
  uploadCloturePdf,
  ClotureBalance,
  ClotureOut
} from '../api/clotures'
import { useToast } from '../hooks/useToast'
import { toNumber } from '../utils/amount'
// jsPDF est lourd : chargement dynamique au moment de l'impression.
type PdfClotureGeneratorModule = typeof import('../utils/pdfClotureGenerator')
let _pdfClotureGeneratorModulePromise: Promise<PdfClotureGeneratorModule> | null = null
function loadPdfClotureGeneratorModule(): Promise<PdfClotureGeneratorModule> {
  if (!_pdfClotureGeneratorModulePromise) _pdfClotureGeneratorModulePromise = import('../utils/pdfClotureGenerator')
  return _pdfClotureGeneratorModulePromise
}
const generateCloturePDF: PdfClotureGeneratorModule['generateCloturePDF'] = async (...args) => {
  const mod = await loadPdfClotureGeneratorModule()
  return mod.generateCloturePDF(...args)
}
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import styles from './ClotureCaisse.module.css'
import { useAuth } from '../contexts/AuthContext'
import ClotureFields, {
  montantAutres,
  serialiserBilletage,
  totalBilletage,
  type BilletageSaisie,
} from '../components/Treasury/ClotureFields'
import CaisseSessionBanner from '../components/CaisseSessionBanner'
import EcartsCaisseEnAttente from '../components/Treasury/EcartsCaisseEnAttente'
import PageHeader from '../components/PageHeader'
import { listOuvertures, getCaisseStatus, type Ouverture } from '../api/caisse'

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)
const formatMoneyCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

const formatBilletageResume = (
  billetage: Record<string, number | string> | null | undefined,
  devise: 'USD' | 'CDF',
) => {
  if (billetage == null) return 'Non renseigné pour cette ancienne clôture'
  // « autres » : montant compté hors des coupures listées, pas une coupure.
  const autres = Number(billetage.autres || 0)
  const entries = Object.entries(billetage)
    .filter(([valeur]) => valeur !== 'autres')
    .map(([valeur, quantite]) => ({ valeur: Number(valeur), quantite: Number(quantite) }))
    .filter((entry) => Number.isFinite(entry.valeur) && entry.valeur > 0 && entry.quantite > 0)
    .sort((a, b) => b.valeur - a.valeur)
  if (entries.length === 0 && !(autres > 0)) return 'Aucune coupure (solde physique nul)'
  const format = devise === 'USD' ? formatMoney : formatMoneyCdf
  const morceaux = entries.map(({ valeur, quantite }) => `${quantite} × ${format(valeur)}`)
  if (autres > 0) morceaux.push(`Autres : ${format(autres)}`)
  return morceaux.join('  ·  ')
}

export default function ClotureCaisse() {
  const { user } = useAuth()
  const { notifyError, notifySuccess } = useToast()
  const [balance, setBalance] = useState<ClotureBalance | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [observation, setObservation] = useState('')
  const [lastCloture, setLastCloture] = useState<ClotureOut | null>(null)
  const [history, setHistory] = useState<ClotureOut[]>([])
  const [exporting, setExporting] = useState(false)
  const [selectedClotureId, setSelectedClotureId] = useState<number | null>(null)
  const [historyFilters, setHistoryFilters] = useState({
    date_debut: '',
    date_fin: '',
    caissier_id: '',
  })
  const [caissiers, setCaissiers] = useState<{ id: string; label: string }[]>([])
  const [billetageUsd, setBilletageUsd] = useState<BilletageSaisie>({})
  const [billetageCdf, setBilletageCdf] = useState<BilletageSaisie>({})
  const [physiqueManuelUsd, setPhysiqueManuelUsd] = useState(0)
  const [physiqueManuelCdf, setPhysiqueManuelCdf] = useState(0)
  const [autresUsd, setAutresUsd] = useState('')
  const [autresCdf, setAutresCdf] = useState('')
  const [comptageConfirme, setComptageConfirme] = useState(false)
  const [regulariser, setRegulariser] = useState(false)
  const [motifRegul, setMotifRegul] = useState('')
  const [showVentilation, setShowVentilation] = useState(false)

  useEffect(() => {
    const loadBalance = async () => {
      setLoading(true)
      try {
        const data = await getClotureBalance()
        setBalance(data)
        // Un nouveau comptage repart de zéro. Préremplir le physique avec le
        // théorique permettrait de clôturer sans avoir ouvert le tiroir.
        setBilletageUsd({})
        setBilletageCdf({})
        setPhysiqueManuelUsd(0)
        setPhysiqueManuelCdf(0)
        setAutresUsd('')
        setAutresCdf('')
        setComptageConfirme(false)
      } catch (error: any) {
        notifyError('Erreur', error?.payload?.detail || error?.message || 'Impossible de charger le solde.')
      } finally {
        setLoading(false)
      }
    }
    loadBalance()
  }, [notifyError])

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const items = await listClotures(20, 0)
        setHistory(items || [])
      } catch (error) {
        console.error('Erreur chargement clôtures:', error)
      }
    }
    loadHistory()
  }, [])

  useEffect(() => {
    const loadCaissiers = async () => {
      try {
        const data = await getClotureCaissiers()
        setCaissiers(data || [])
      } catch (error) {
        console.error('Erreur chargement caissiers:', error)
      }
    }
    loadCaissiers()
  }, [])

  const tauxChange = toNumber(balance?.taux_change || 1)
  const soldeTheoUsd = toNumber(balance?.solde_theorique_usd || 0)
  const soldeTheoCdf = toNumber(balance?.solde_theorique_cdf || 0)
  const denominations = balance?.denominations ?? []
  const denominationsUsd = denominations.filter((denomination) => denomination.devise === 'USD')
  const denominationsCdf = denominations.filter((denomination) => denomination.devise === 'CDF')
  // « Autres » n'existe qu'à côté des coupures : sans elles, le total est saisi.
  const autresUsdMontant = denominationsUsd.length > 0 ? montantAutres(autresUsd) : 0
  const autresCdfMontant = denominationsCdf.length > 0 ? montantAutres(autresCdf) : 0
  const physiqueUsd = denominationsUsd.length > 0
    ? Math.round((totalBilletage(denominationsUsd, billetageUsd) + autresUsdMontant) * 100) / 100
    : physiqueManuelUsd
  const physiqueCdf = denominationsCdf.length > 0
    ? Math.round((totalBilletage(denominationsCdf, billetageCdf) + autresCdfMontant) * 100) / 100
    : physiqueManuelCdf
  const ecartUsd = physiqueUsd - soldeTheoUsd
  const ecartCdf = physiqueCdf - soldeTheoCdf
  // Approvisionnements banque -> caisse de la période : ils sont déjà dans le
  // total des entrées, on les détaille pour que le caissier les rapproche.
  const approvisionnements = balance?.approvisionnements ?? []
  const approUsd = toNumber(balance?.entrees_approvisionnements_usd || 0)
  const approCdf = toNumber(balance?.entrees_approvisionnements_cdf || 0)
  const selectedCloture = selectedClotureId == null
    ? null
    : history.find((cloture) => cloture.id === selectedClotureId) ?? null

  // Ventilation des entrées. La tuile « Entrées USD » agrège quatre sources ;
  // sans le détail, un caissier qui ne compte que ses notes de débit croit à un
  // écart. La somme des lignes DOIT redonner `total_entrees_*` — c'est ce qui
  // rend la tuile vérifiable, donc on affiche aussi le total pour comparaison.
  const ventilationEntrees = [
    {
      cle: 'encaissements',
      label: 'Notes de débit encaissées',
      hint: 'Recettes clients réglées en espèces au guichet',
      usd: toNumber(balance?.entrees_encaissements_usd || 0),
      cdf: toNumber(balance?.entrees_encaissements_cdf || 0),
    },
    {
      cle: 'approvisionnements',
      label: 'Approvisionnements banque → caisse',
      hint: 'Sortie côté banque, entrée côté caisse (détail ci-dessous)',
      usd: approUsd,
      cdf: approCdf,
    },
    {
      cle: 'transferts',
      label: 'Transferts internes reçus',
      hint: 'Transferts dont la caisse est la destination',
      usd: toNumber(balance?.entrees_transferts_usd || 0),
      cdf: toNumber(balance?.entrees_transferts_cdf || 0),
    },
    {
      cle: 'retours',
      label: 'Retours en caisse',
      hint: "Reliquats d'avances rendus par les bénéficiaires",
      usd: toNumber(balance?.entrees_retours_usd || 0),
      cdf: toNumber(balance?.entrees_retours_cdf || 0),
    },
  ]
  // Ancien backend (avant la ventilation) : tous les champs valent 0 alors que
  // le total ne l'est pas. Mieux vaut ne rien afficher qu'un détail faux.
  const ventilationDisponible = ventilationEntrees.some((l) => l.usd !== 0 || l.cdf !== 0)

  const entreesUsd = toNumber(balance?.total_entrees_usd || 0)
  const entreesCdf = toNumber(balance?.total_entrees_cdf || 0)
  // Contrôle de cohérence, pas de décor : si une source d'entrées est ajoutée au
  // total sans être ventilée, le caissier doit le voir plutôt que de chercher un
  // écart de comptage qui n'existe pas. Tolérance au centime (arrondis Decimal).
  const ecartVentilationUsd =
    entreesUsd - ventilationEntrees.reduce((somme, l) => somme + l.usd, 0)
  const ecartVentilationCdf =
    entreesCdf - ventilationEntrees.reduce((somme, l) => somme + l.cdf, 0)
  const ventilationIncomplete =
    Math.abs(ecartVentilationUsd) > 0.009 || Math.abs(ecartVentilationCdf) > 0.009

  // Panneau replié par défaut : c'est un détail de rapprochement, la clôture
  // courante reste la tâche principale. Exception, une ventilation incohérente
  // s'ouvre d'office — l'utilisateur peut la refermer, mais pas la manquer.
  useEffect(() => {
    if (ventilationIncomplete) setShowVentilation(true)
  }, [ventilationIncomplete])

  const verdict = () => {
    if (ecartUsd === 0 && ecartCdf === 0) return { label: 'Caisse équilibrée', tone: styles.ok }
    if (ecartUsd < 0 || ecartCdf < 0) return { label: 'Manquant de caisse', tone: styles.danger }
    return { label: 'Excédent de caisse', tone: styles.warn }
  }

  const handleSubmit = async () => {
    if (!comptageConfirme) {
      notifyError('Comptage non confirmé', 'Confirmez le billetage physique avant de valider la clôture.')
      return
    }
    if ((autresUsdMontant > 0 || autresCdfMontant > 0) && !observation.trim()) {
      notifyError('Observation requise', 'Précisez dans l’observation ce que contient la ligne « Autres » du billetage.')
      return
    }
    setSaving(true)
    try {
      const payload = {
        solde_physique_usd: physiqueUsd,
        solde_physique_cdf: physiqueCdf,
        billetage_usd: denominationsUsd.length > 0
          ? serialiserBilletage(denominationsUsd, billetageUsd)
          : undefined,
        billetage_cdf: denominationsCdf.length > 0
          ? serialiserBilletage(denominationsCdf, billetageCdf)
          : undefined,
        autres_usd: autresUsdMontant,
        autres_cdf: autresCdfMontant,
        observation: observation.trim() || undefined,
        regulariser_ecart: regulariser,
        motif_regularisation: regulariser ? motifRegul.trim() : undefined,
      }
      const res = await createCloture(payload)
      setLastCloture(res)
      setHistory((prev) => [res, ...prev].slice(0, 20))
      const erreurs = res.regularisation_erreurs ?? []
      const faites = res.regularisations ?? []
      if (erreurs.length > 0) {
        // La clôture est enregistrée quoi qu'il arrive : on ne bloque jamais.
        notifyError('Écart non régularisé', erreurs.join(' / '))
      } else if (faites.length > 0) {
        notifySuccess(
          'Clôture enregistrée',
          `Réf: ${res.reference_numero} — écart régularisé : ${faites
            .map((r) => `${r.montant} ${r.devise}`)
            .join(', ')}.`,
        )
      } else {
        notifySuccess('Clôture enregistrée', `Réf: ${res.reference_numero}`)
      }
      setRegulariser(false)
      setMotifRegul('')
      setComptageConfirme(false)
      window.dispatchEvent(new Event('cash-closure-updated'))
      setCaisseOuverte(false) // la caisse est désormais fermée
      refreshCaisse()
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Impossible d’enregistrer la clôture.')
    } finally {
      setSaving(false)
    }
  }

  const handlePrint = () => {
    const run = async () => {
      if (!lastCloture) return
      const data = await getCloturePdfData(lastCloture.id)
      const blob = await generateCloturePDF({
        date: data.cloture.date_cloture,
        reference_numero: data.cloture.reference_numero,
        caissier_nom: [user?.prenom, user?.nom].filter(Boolean).join(' ') || user?.email,
        solde_theorique_usd: data.cloture.solde_theorique_usd,
        solde_physique_usd: data.cloture.solde_physique_usd,
        ecart_usd: data.cloture.ecart_usd,
        solde_theorique_cdf: data.cloture.solde_theorique_cdf,
        solde_physique_cdf: data.cloture.solde_physique_cdf,
        ecart_cdf: data.cloture.ecart_cdf,
        billetage_usd: data.cloture.billetage_usd,
        billetage_cdf: data.cloture.billetage_cdf,
        observation: data.cloture.observation,
      }, { returnBlob: true })
      if (blob) {
        await uploadCloturePdf(lastCloture.id, blob)
      }
    }
    run().catch((error) => {
      notifyError('Erreur PDF', error?.message || 'Impossible de générer le PV.')
    })
  }

  const handleSelectCloture = (value: string) => {
    const id = Number(value)
    if (!Number.isFinite(id)) {
      setSelectedClotureId(null)
      return
    }
    const selected = history.find((c) => c.id === id) || null
    setSelectedClotureId(id)
    if (selected) {
      setLastCloture(selected)
    }
  }

  const handleExportHistory = async () => {
    setExporting(true)
    try {
      const url = `${API_BASE_URL}/clotures/export-xlsx`
      const resp = await fetch(url, {
        headers: getAuthHeaders(),
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `clotures_${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error: any) {
      notifyError('Export impossible', error?.message || 'Erreur inconnue')
    } finally {
      setExporting(false)
    }
  }

  const applyHistoryFilters = async () => {
    try {
      const items = await listCloturesWithFilters({
        date_debut: historyFilters.date_debut || undefined,
        date_fin: historyFilters.date_fin || undefined,
        caissier_id: historyFilters.caissier_id || undefined,
        limit: 50,
        offset: 0,
      })
      setHistory(items || [])
    } catch (error) {
      notifyError('Erreur', 'Impossible de filtrer les clôtures.')
    }
  }

  const downloadArchivedPdf = async (cloture: ClotureOut) => {
    try {
      const url = `${API_BASE_URL}/clotures/${cloture.id}/pdf`
      const resp = await fetch(url, {
        headers: getAuthHeaders(),
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = cloture.pdf_path || `cloture_${cloture.reference_numero}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error: any) {
      notifyError('Téléchargement impossible', error?.message || 'PV introuvable')
    }
  }

  const [ouvertures, setOuvertures] = useState<Ouverture[]>([])
  const [caisseOuverte, setCaisseOuverte] = useState<boolean | null>(null)
  const refreshCaisse = () => {
    listOuvertures(20).then(setOuvertures).catch(() => {})
    getCaisseStatus().then((s) => setCaisseOuverte(s.est_ouverte)).catch(() => {})
  }
  useEffect(() => {
    refreshCaisse()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={styles.container}>
      <PageHeader
        title="Clôture de caisse"
        subtitle="Comptez les espèces, rapprochez-les du solde théorique et archivez le procès-verbal de la journée."
        actions={
          <div className={styles.headerMeta}>
            {balance && (
              <span className={styles.periodBadge}>
                <CalendarDays size={15} aria-hidden="true" />
                {balance.date_debut
                  ? `${new Date(balance.date_debut).toLocaleDateString('fr-FR')} – ${new Date(balance.date_fin).toLocaleDateString('fr-FR')}`
                  : `Situation au ${new Date(balance.date_fin).toLocaleDateString('fr-FR')}`}
              </span>
            )}
            <span
              className={`${styles.cashStatus} ${
                caisseOuverte === true
                  ? styles.cashStatusOpen
                  : caisseOuverte === false
                    ? styles.cashStatusClosed
                    : styles.cashStatusLoading
              }`}
            >
              <span className={styles.statusDot} aria-hidden="true" />
              {caisseOuverte === true ? 'Caisse ouverte' : caisseOuverte === false ? 'Caisse fermée' : 'Statut en cours…'}
            </span>
          </div>
        }
      />

      <CaisseSessionBanner onChanged={refreshCaisse} />
      <EcartsCaisseEnAttente onChanged={refreshCaisse} />

      {ouvertures.length > 0 && (
        <section className={styles.panel}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={styles.sectionIcon}><Landmark size={18} aria-hidden="true" /></span>
              <div>
                <p className={styles.eyebrow}>Contexte de caisse</p>
                <h2>Ouvertures récentes</h2>
                <p>Contrôlez le fond de caisse avant de commencer le comptage de clôture.</p>
              </div>
            </div>
            <span className={styles.countBadge}>{ouvertures.length} ouverture{ouvertures.length > 1 ? 's' : ''}</span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>Référence</th>
                  <th>Date</th>
                  <th className={styles.money}>Fond compté</th>
                  <th className={styles.money}>Attendu</th>
                  <th className={styles.money}>Écart</th>
                </tr>
              </thead>
              <tbody>
                {ouvertures.map((o) => {
                  const eUsd = Number(o.ecart_usd || 0)
                  const eCdf = Number(o.ecart_cdf || 0)
                  const hasEcart = Math.abs(eUsd) > 0.009 || Math.abs(eCdf) > 0.009
                  return (
                    <tr key={o.id}>
                      <td className={styles.referenceCell}>{o.reference_numero}</td>
                      <td>{new Date(o.date_ouverture).toLocaleString('fr-FR')}</td>
                      <td className={styles.money}>{Number(o.solde_ouverture_usd).toFixed(2)} $ / {Number(o.solde_ouverture_cdf).toFixed(2)} FC</td>
                      <td className={styles.money}>{Number(o.solde_attendu_usd).toFixed(2)} $ / {Number(o.solde_attendu_cdf).toFixed(2)} FC</td>
                      <td className={`${styles.money} ${hasEcart ? styles.warnText : styles.okText}`}>
                        {hasEcart
                          ? `${eUsd >= 0 ? '+' : ''}${eUsd.toFixed(2)} $ / ${eCdf >= 0 ? '+' : ''}${eCdf.toFixed(2)} FC`
                          : <span className={styles.conformBadge}><CheckCircle2 size={13} /> Conforme</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {loading && <div className={styles.loading}>Chargement du solde théorique…</div>}

      {balance && (
        <section className={`${styles.panel} ${styles.overviewPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={styles.sectionIcon}><WalletCards size={18} aria-hidden="true" /></span>
              <div>
                <p className={styles.eyebrow}>Situation théorique</p>
                <h2>Mouvements depuis la dernière clôture</h2>
                <p>Les montants USD et CDF restent séparés pour un rapprochement sans conversion implicite.</p>
              </div>
            </div>
            <span className={styles.rateBadge}>1 USD = {tauxChange.toLocaleString('fr-FR')} CDF</span>
          </div>

          <div className={styles.summary}>
            <article className={styles.metricCard}>
              <span className={`${styles.metricIcon} ${styles.metricIconNeutral}`}><Banknote size={19} /></span>
              <div className={styles.metricContent}>
                <span className={styles.metricLabel}>Solde initial</span>
                <strong>{formatMoney(toNumber(balance.solde_initial_usd))}</strong>
                <small>{formatMoneyCdf(toNumber(balance.solde_initial_cdf))}</small>
              </div>
            </article>
            <article className={styles.metricCard}>
              <span className={`${styles.metricIcon} ${styles.metricIconPositive}`}><ArrowDownToLine size={19} /></span>
              <div className={styles.metricContent}>
                <span className={styles.metricLabel}>Entrées</span>
                <strong className={styles.positiveAmount}>{formatMoney(toNumber(balance.total_entrees_usd))}</strong>
                <small>{formatMoneyCdf(toNumber(balance.total_entrees_cdf))}</small>
              </div>
            </article>
            <article className={styles.metricCard}>
              <span className={`${styles.metricIcon} ${styles.metricIconNegative}`}><ArrowUpFromLine size={19} /></span>
              <div className={styles.metricContent}>
                <span className={styles.metricLabel}>Sorties</span>
                <strong className={styles.negativeAmount}>{formatMoney(toNumber(balance.total_sorties_usd))}</strong>
                <small>{formatMoneyCdf(toNumber(balance.total_sorties_cdf))}</small>
              </div>
            </article>
            <article className={`${styles.metricCard} ${styles.metricCardPrimary}`}>
              <span className={`${styles.metricIcon} ${styles.metricIconPrimary}`}><Scale size={19} /></span>
              <div className={styles.metricContent}>
                <span className={styles.metricLabel}>Solde théorique</span>
                <strong>{formatMoney(soldeTheoUsd)}</strong>
                <small>{formatMoneyCdf(soldeTheoCdf)}</small>
              </div>
            </article>
          </div>
        </section>
      )}

      {balance && ventilationDisponible && (
        <section className={`${styles.panel} ${styles.detailPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={`${styles.sectionIcon} ${styles.sectionIconPositive}`}>
                <ArrowDownToLine size={18} aria-hidden="true" />
              </span>
              <div>
                <p className={styles.eyebrow}>Rapprochement</p>
                <h2>D'où viennent les entrées</h2>
                <p>Ventilation des recettes, approvisionnements, transferts et retours reçus en caisse.</p>
              </div>
            </div>
            <button
              type="button"
              className={styles.ventilationToggle}
              onClick={() => setShowVentilation((ouvert) => !ouvert)}
              aria-expanded={showVentilation}
              aria-controls="ventilation-entrees"
            >
              {showVentilation ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              {showVentilation ? 'Masquer la ventilation' : 'Voir la ventilation'}
              {/* Une anomalie ne doit pas pouvoir se cacher derrière un panneau
                  replié : le badge la signale même fermé. */}
              {ventilationIncomplete && !showVentilation && (
                <span className={styles.ventilationBadge}>à vérifier</span>
              )}
            </button>
          </div>
          {showVentilation && (
            <div id="ventilation-entrees" className={styles.panelBody}>
              <p className={styles.ventilationHint}>
                Le total doit redonner la tuile « Entrées » ci-dessus.
              </p>
              <div className={styles.tableScroll}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th className={styles.money}>USD</th>
                      <th className={styles.money}>CDF</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ventilationEntrees.map((ligne) => (
                      <tr key={ligne.cle}>
                        <td>
                          <div className={styles.sourceLabel}>{ligne.label}</div>
                          <div className={styles.ventilationHint}>{ligne.hint}</div>
                        </td>
                        <td className={styles.money}>{formatMoney(ligne.usd)}</td>
                        <td className={styles.money}>{formatMoneyCdf(ligne.cdf)}</td>
                      </tr>
                    ))}
                    <tr className={styles.totalRow}>
                      <td>Total des entrées</td>
                      <td className={styles.money}>{formatMoney(entreesUsd)}</td>
                      <td className={styles.money}>{formatMoneyCdf(entreesCdf)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {ventilationIncomplete && (
                <p className={styles.ventilationWarn}>
                  Le détail ne redonne pas le total des entrées
                  {ecartVentilationUsd !== 0 &&
                    ` (${formatMoney(ecartVentilationUsd)} d'écart en USD)`}
                  {ecartVentilationCdf !== 0 &&
                    ` (${formatMoneyCdf(ecartVentilationCdf)} d'écart en CDF)`}
                  . Le solde théorique reste juste : c'est la ventilation qui est incomplète —
                  signale-le avant de clôturer.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      {balance && (approvisionnements.length > 0 || approUsd > 0 || approCdf > 0) && (
        <section className={`${styles.panel} ${styles.detailPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={`${styles.sectionIcon} ${styles.sectionIconPositive}`}>
                <Landmark size={18} aria-hidden="true" />
              </span>
              <div>
                <p className={styles.eyebrow}>Flux complémentaires</p>
                <h2>Entrées hors notes de débit</h2>
                <p>Les approvisionnements banque → caisse sont déjà compris dans le total des entrées.</p>
              </div>
            </div>
            <span className={styles.amountBadge}>+ {formatMoney(approUsd)} · {formatMoneyCdf(approCdf)}</span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>Référence</th>
                  <th>Date</th>
                  <th>Banque source</th>
                  <th>Libellé</th>
                  <th className={styles.money}>Entrée</th>
                </tr>
              </thead>
              <tbody>
                {approvisionnements.map((ligne) => (
                  <tr key={ligne.id}>
                    <td className={styles.referenceCell}>{ligne.reference || '—'}</td>
                    <td>
                      {ligne.date ? new Date(ligne.date).toLocaleString('fr-FR') : '—'}
                    </td>
                    <td>{ligne.source}</td>
                    <td>{ligne.libelle}</td>
                    <td className={`${styles.money} ${styles.okText}`}>
                      + {ligne.devise === 'CDF'
                        ? formatMoneyCdf(toNumber(ligne.montant))
                        : formatMoney(toNumber(ligne.montant))}
                    </td>
                  </tr>
                ))}
                <tr className={styles.totalRow}>
                  <td colSpan={4}>
                    Total approvisionnements
                  </td>
                  <td className={styles.money}>
                    {formatMoney(approUsd)} / {formatMoneyCdf(approCdf)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}

      {balance && (
        <section className={`${styles.panel} ${styles.workflowPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={styles.stepNumber}>1</span>
              <div>
                <p className={styles.eyebrow}>Étape 1</p>
                <h2>Compter les espèces</h2>
                <p>Saisissez le nombre de billets par coupure ; les totaux physiques sont calculés automatiquement.</p>
              </div>
            </div>
            <span className={styles.stepBadge}>Comptage physique</span>
          </div>
          <ClotureFields
            soldeTheoriqueUsd={soldeTheoUsd}
            soldeTheoriqueCdf={soldeTheoCdf}
            denominations={denominations}
            billetageUsd={billetageUsd}
            billetageCdf={billetageCdf}
            physiqueManuelUsd={physiqueManuelUsd}
            physiqueManuelCdf={physiqueManuelCdf}
            autresUsd={autresUsd}
            autresCdf={autresCdf}
            onAutresChange={(devise, value) => {
              if (devise === 'USD') setAutresUsd(value)
              else setAutresCdf(value)
              setComptageConfirme(false)
              setRegulariser(false)
              setMotifRegul('')
            }}
            onBilletageChange={(devise, key, value) => {
              if (devise === 'USD') {
                setBilletageUsd((prev) => ({ ...prev, [key]: value }))
              } else {
                setBilletageCdf((prev) => ({ ...prev, [key]: value }))
              }
              setComptageConfirme(false)
              setRegulariser(false)
              setMotifRegul('')
            }}
            onPhysiqueManuelChange={(devise, value) => {
              if (devise === 'USD') setPhysiqueManuelUsd(value)
              else setPhysiqueManuelCdf(value)
              setComptageConfirme(false)
              setRegulariser(false)
              setMotifRegul('')
            }}
          />
          <section className={styles.countConfirmation}>
            <label>
              <input
                type="checkbox"
                checked={comptageConfirme}
                onChange={(event) => setComptageConfirme(event.target.checked)}
              />
              <span>
                <strong>Je confirme avoir compté le contenu physique de la caisse.</strong>
                <small>
                  Les soldes physiques ci-dessous proviennent du billetage saisi et seront
                  conservés avec la clôture.
                </small>
              </span>
            </label>
          </section>
        </section>
      )}

      {balance && (
        <section className={`${styles.panel} ${styles.reconciliationPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={styles.stepNumber}>2</span>
              <div>
                <p className={styles.eyebrow}>Étape 2</p>
                <h2>Rapprocher le physique et le théorique</h2>
                <p>Un écart nul signifie que le contenu du tiroir correspond aux mouvements enregistrés.</p>
              </div>
            </div>
            <div className={`${styles.verdictBadge} ${verdict().tone}`}>
              {ecartUsd === 0 && ecartCdf === 0
                ? <CheckCircle2 size={16} aria-hidden="true" />
                : <AlertTriangle size={16} aria-hidden="true" />}
              {verdict().label}
            </div>
          </div>
          <div className={styles.verdict}>
            <div className={styles.verdictMetric}>
              <span>Solde physique USD</span>
              <strong>{formatMoney(physiqueUsd)}</strong>
              <small>Théorique : {formatMoney(soldeTheoUsd)}</small>
            </div>
            <div className={styles.verdictMetric}>
              <span>Écart USD</span>
              <strong className={ecartUsd === 0 ? styles.okText : ecartUsd < 0 ? styles.dangerText : styles.warnText}>
                {formatMoney(ecartUsd)}
              </strong>
              <small>{ecartUsd === 0 ? 'Aucune différence' : ecartUsd < 0 ? 'Montant manquant' : 'Montant excédentaire'}</small>
            </div>
            <div className={styles.verdictMetric}>
              <span>Solde physique CDF</span>
              <strong>{formatMoneyCdf(physiqueCdf)}</strong>
              <small>Théorique : {formatMoneyCdf(soldeTheoCdf)}</small>
            </div>
            <div className={styles.verdictMetric}>
              <span>Écart CDF</span>
              <strong className={ecartCdf === 0 ? styles.okText : ecartCdf < 0 ? styles.dangerText : styles.warnText}>
                {formatMoneyCdf(ecartCdf)}
              </strong>
              <small>{ecartCdf === 0 ? 'Aucune différence' : ecartCdf < 0 ? 'Montant manquant' : 'Montant excédentaire'}</small>
            </div>
          </div>
        </section>
      )}

      {(ecartUsd !== 0 || ecartCdf !== 0) && (
        <section className={styles.regularisationPanel}>
          <div className={styles.regularisationIcon}><AlertTriangle size={19} aria-hidden="true" /></div>
          <div className={styles.regularisationContent}>
            <strong>Écart constaté entre le comptage et le solde théorique</strong>
            <p>
            Le comptage physique ne remplace pas le solde du logiciel. Pour que les deux
            correspondent, l’écart doit donner lieu à une opération identifiable :{' '}
            <strong>
              {((ecartUsd > 0 || ecartCdf > 0) && (ecartUsd < 0 || ecartCdf < 0))
                ? 'des opérations de régularisation distinctes par devise'
                : (ecartUsd > 0 || ecartCdf > 0)
                  ? 'un encaissement de régularisation'
                  : 'une sortie de régularisation'}
            </strong>
            .
            </p>
            <label className={styles.regularisationChoice}>
            <input
              type="checkbox"
              checked={regulariser}
              onChange={(e) => setRegulariser(e.target.checked)}
            />
            <span>
              Créer l’opération de régularisation
              <small>
                Sans cela, la clôture est enregistrée, le solde reste au théorique et l’écart
                reste à traiter.
              </small>
            </span>
            </label>
            {regulariser && (
              <input
                className={`${styles.regularisationInput} ${motifRegul.trim() ? '' : styles.regularisationInputRequired}`}
                value={motifRegul}
                onChange={(e) => setMotifRegul(e.target.value)}
                placeholder="Motif de la régularisation (obligatoire)"
              />
            )}
          </div>
        </section>
      )}

      {balance && (
        <section className={`${styles.panel} ${styles.finalizationPanel}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionHeading}>
              <span className={styles.stepNumber}>3</span>
              <div>
                <p className={styles.eyebrow}>Étape 3</p>
                <h2>Finaliser la clôture</h2>
                <p>Ajoutez une explication si nécessaire, puis enregistrez définitivement la situation de caisse.</p>
              </div>
            </div>
            <span className={styles.stepBadge}>{comptageConfirme ? 'Prête à valider' : 'Confirmation requise'}</span>
          </div>

          <div className={styles.observation}>
            <label htmlFor="cloture-observation">
              Observations
              <small>Optionnel, sauf si la ligne « Autres » du billetage contient un montant.</small>
            </label>
            <textarea
              id="cloture-observation"
              value={observation}
              onChange={(e) => setObservation(e.target.value)}
              placeholder="Expliquez un écart, une coupure non listée ou tout élément utile au procès-verbal…"
            />
          </div>

          <div className={styles.actions}>
            <div className={styles.primaryActionGroup}>
              {caisseOuverte === false ? (
                <span className={styles.closedMessage}>
                  <AlertTriangle size={17} aria-hidden="true" />
                  Caisse fermée — ouvrez-la avec le bandeau ci-dessus avant de la clôturer.
                </span>
              ) : (
                <button
                  type="button"
                  className={styles.primaryButton}
                  onClick={handleSubmit}
                  disabled={saving || loading || !comptageConfirme}
                >
                  <CheckCircle2 size={17} aria-hidden="true" />
                  {saving ? 'Enregistrement…' : 'Valider la clôture'}
                </button>
              )}
              {!comptageConfirme && caisseOuverte !== false && (
                <span className={styles.actionHint}>Confirmez d’abord le comptage physique à l’étape 1.</span>
              )}
            </div>
            <div className={styles.secondaryActions}>
              <button type="button" className={styles.secondaryButton} onClick={handlePrint} disabled={!lastCloture}>
                <FileText size={16} aria-hidden="true" />
                Générer le PV
              </button>
              <button type="button" className={styles.secondaryButton} onClick={handleExportHistory} disabled={exporting}>
                <FileSpreadsheet size={16} aria-hidden="true" />
                {exporting ? 'Export en cours…' : 'Exporter l’historique'}
              </button>
            </div>
          </div>
        </section>
      )}

      <section className={`${styles.panel} ${styles.history}`}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionHeading}>
            <span className={styles.sectionIcon}><History size={18} aria-hidden="true" /></span>
            <div>
              <p className={styles.eyebrow}>Archives</p>
              <h2>Historique des clôtures</h2>
              <p>Consultez le billetage conservé, filtrez les opérations ou récupérez un procès-verbal.</p>
            </div>
          </div>
          <span className={styles.countBadge}>{history.length} résultat{history.length > 1 ? 's' : ''}</span>
        </div>
        <label className={`${styles.filterField} ${styles.historySelector}`}>
          <span>Consulter une clôture</span>
          <select value={selectedClotureId ?? ''} onChange={(e) => handleSelectCloture(e.target.value)}>
            <option value="">Sélectionner une date</option>
            {history.map((c) => (
              <option key={c.id} value={c.id}>
                {new Date(c.date_cloture).toLocaleString('fr-FR')} · {c.reference_numero}
              </option>
            ))}
          </select>
        </label>
        {selectedCloture && (
          <div className={styles.archivedBilletage}>
            <strong>Billetage enregistré — {selectedCloture.reference_numero}</strong>
            <div>
              <span>USD</span>
              <p>{formatBilletageResume(selectedCloture.billetage_usd, 'USD')}</p>
            </div>
            <div>
              <span>CDF</span>
              <p>{formatBilletageResume(selectedCloture.billetage_cdf, 'CDF')}</p>
            </div>
          </div>
        )}
        <div className={styles.historyFilters}>
          <label className={styles.filterField}>
            <span>Date de début</span>
            <input
              type="date"
              value={historyFilters.date_debut}
              onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_debut: e.target.value }))}
            />
          </label>
          <label className={styles.filterField}>
            <span>Date de fin</span>
            <input
              type="date"
              value={historyFilters.date_fin}
              onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_fin: e.target.value }))}
            />
          </label>
          <label className={`${styles.filterField} ${styles.filterFieldGrow}`}>
            <span>Caissier</span>
            <select
              value={historyFilters.caissier_id}
              onChange={(e) => setHistoryFilters((prev) => ({ ...prev, caissier_id: e.target.value }))}
            >
              <option value="">Tous les caissiers</option>
              {caissiers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className={styles.filterButton} onClick={applyHistoryFilters}>
            <ListFilter size={16} aria-hidden="true" />
            Appliquer
          </button>
        </div>
        <div className={styles.tableScroll}>
          <table className={`${styles.dataTable} ${styles.historyTable}`}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Référence</th>
              <th className={styles.money}>Théorique USD</th>
              <th className={styles.money}>Physique USD</th>
              <th className={styles.money}>Écart USD</th>
              <th className={styles.money}>Théorique CDF</th>
              <th className={styles.money}>Physique CDF</th>
              <th className={styles.money}>Écart CDF</th>
              <th>PV</th>
            </tr>
          </thead>
          <tbody>
            {history.length === 0 && (
              <tr>
                <td colSpan={9} className={styles.emptyCell}>
                  Aucune clôture enregistrée.
                </td>
              </tr>
            )}
            {history.map((c) => (
              <tr key={c.id}>
                <td>{new Date(c.date_cloture).toLocaleString('fr-FR')}</td>
                <td className={styles.referenceCell}>{c.reference_numero}</td>
                <td className={styles.money}>{formatMoney(toNumber(c.solde_theorique_usd))}</td>
                <td className={styles.money}>{formatMoney(toNumber(c.solde_physique_usd))}</td>
                <td className={`${styles.money} ${toNumber(c.ecart_usd) === 0 ? styles.okText : toNumber(c.ecart_usd) < 0 ? styles.dangerText : styles.warnText}`}>
                  {formatMoney(toNumber(c.ecart_usd))}
                </td>
                <td className={styles.money}>{formatMoneyCdf(toNumber(c.solde_theorique_cdf))}</td>
                <td className={styles.money}>{formatMoneyCdf(toNumber(c.solde_physique_cdf))}</td>
                <td className={`${styles.money} ${toNumber(c.ecart_cdf) === 0 ? styles.okText : toNumber(c.ecart_cdf) < 0 ? styles.dangerText : styles.warnText}`}>
                  {formatMoneyCdf(toNumber(c.ecart_cdf))}
                </td>
                <td>
                  <button
                    type="button"
                    className={styles.tableAction}
                    onClick={() => downloadArchivedPdf(c)}
                    disabled={!c.pdf_path}
                  >
                    <Download size={14} aria-hidden="true" />
                    Télécharger
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
