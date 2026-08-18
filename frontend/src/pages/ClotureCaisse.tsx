import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
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
import ClotureFields from '../components/Treasury/ClotureFields'
import CaisseSessionBanner from '../components/CaisseSessionBanner'
import EcartsCaisseEnAttente from '../components/Treasury/EcartsCaisseEnAttente'
import { listOuvertures, getCaisseStatus, type Ouverture } from '../api/caisse'

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)
const formatMoneyCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

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
  const [physiqueUsd, setPhysiqueUsd] = useState(0)
  const [physiqueCdf, setPhysiqueCdf] = useState(0)
  const [regulariser, setRegulariser] = useState(false)
  const [motifRegul, setMotifRegul] = useState('')
  const [showVentilation, setShowVentilation] = useState(false)

  useEffect(() => {
    const loadBalance = async () => {
      setLoading(true)
      try {
        const data = await getClotureBalance()
        setBalance(data)
        setPhysiqueUsd(toNumber(data.solde_theorique_usd || 0))
        setPhysiqueCdf(toNumber(data.solde_theorique_cdf || 0))
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
  const ecartUsd = physiqueUsd - soldeTheoUsd
  const ecartCdf = physiqueCdf - soldeTheoCdf
  // Approvisionnements banque -> caisse de la période : ils sont déjà dans le
  // total des entrées, on les détaille pour que le caissier les rapproche.
  const approvisionnements = balance?.approvisionnements ?? []
  const approUsd = toNumber(balance?.entrees_approvisionnements_usd || 0)
  const approCdf = toNumber(balance?.entrees_approvisionnements_cdf || 0)

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
    setSaving(true)
    try {
      const payload = {
        solde_physique_usd: physiqueUsd,
        solde_physique_cdf: physiqueCdf,
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
      <header className={styles.header}>
        <h1>Clôture de caisse</h1>
        <p>Comptage journalier et comparaison avec le solde théorique.</p>
      </header>

      <CaisseSessionBanner onChanged={refreshCaisse} />
      <EcartsCaisseEnAttente onChanged={refreshCaisse} />

      {ouvertures.length > 0 && (
        <section className={styles.history}>
          <div className={styles.historyHeader}>
            <h3>Ouvertures récentes</h3>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', background: '#f8fafc' }}>
                  <th style={{ padding: 8 }}>Référence</th>
                  <th style={{ padding: 8 }}>Date</th>
                  <th style={{ padding: 8 }}>Fond compté</th>
                  <th style={{ padding: 8 }}>Attendu</th>
                  <th style={{ padding: 8 }}>Écart</th>
                </tr>
              </thead>
              <tbody>
                {ouvertures.map((o) => {
                  const eUsd = Number(o.ecart_usd || 0)
                  const eCdf = Number(o.ecart_cdf || 0)
                  const hasEcart = Math.abs(eUsd) > 0.009 || Math.abs(eCdf) > 0.009
                  return (
                    <tr key={o.id} style={{ borderTop: '1px solid #eef2f7' }}>
                      <td style={{ padding: 8, fontWeight: 600 }}>{o.reference_numero}</td>
                      <td style={{ padding: 8 }}>{new Date(o.date_ouverture).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: 8 }}>{Number(o.solde_ouverture_usd).toFixed(2)} $ / {Number(o.solde_ouverture_cdf).toFixed(2)} FC</td>
                      <td style={{ padding: 8 }}>{Number(o.solde_attendu_usd).toFixed(2)} $ / {Number(o.solde_attendu_cdf).toFixed(2)} FC</td>
                      <td style={{ padding: 8, color: hasEcart ? '#b45309' : '#16a34a', fontWeight: 600 }}>
                        {hasEcart ? `${eUsd >= 0 ? '+' : ''}${eUsd.toFixed(2)} $ / ${eCdf >= 0 ? '+' : ''}${eCdf.toFixed(2)} FC` : 'Conforme'}
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
        <section className={styles.summary}>
          <div>
            <span>Taux de change</span>
            <strong>{tauxChange.toFixed(2)}</strong>
          </div>
          <div>
            <span>Solde initial USD</span>
            <strong>{formatMoney(toNumber(balance.solde_initial_usd))}</strong>
          </div>
          <div>
            <span>Entrées USD</span>
            <strong>{formatMoney(toNumber(balance.total_entrees_usd))}</strong>
          </div>
          <div>
            <span>Sorties USD</span>
            <strong>{formatMoney(toNumber(balance.total_sorties_usd))}</strong>
          </div>
          <div>
            <span>Solde théorique USD</span>
            <strong>{formatMoney(soldeTheoUsd)}</strong>
          </div>
          <div>
            <span>Solde théorique CDF</span>
            <strong>{formatMoneyCdf(soldeTheoCdf)}</strong>
          </div>
        </section>
      )}

      {balance && ventilationDisponible && (
        <section className={styles.history}>
          <div className={styles.historyHeader}>
            <h3>D'où viennent les entrées</h3>
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
            <>
              <p className={styles.ventilationHint}>
                Le total doit redonner la tuile « Entrées » ci-dessus.
              </p>
              <table id="ventilation-entrees">
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
                        <div>{ligne.label}</div>
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
            </>
          )}
        </section>
      )}

      {balance && (approvisionnements.length > 0 || approUsd > 0 || approCdf > 0) && (
        <section className={styles.history}>
          <div className={styles.historyHeader}>
            <h3>Entrées de caisse hors notes de débit</h3>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              Approvisionnements banque → caisse : sortie côté banque, entrée côté caisse.
              Déjà compris dans « Entrées ».
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', background: '#f8fafc' }}>
                  <th style={{ padding: 8 }}>Référence</th>
                  <th style={{ padding: 8 }}>Date</th>
                  <th style={{ padding: 8 }}>Banque source</th>
                  <th style={{ padding: 8 }}>Libellé</th>
                  <th style={{ padding: 8, textAlign: 'right' }}>Entrée</th>
                </tr>
              </thead>
              <tbody>
                {approvisionnements.map((ligne) => (
                  <tr key={ligne.id} style={{ borderTop: '1px solid #eef2f7' }}>
                    <td style={{ padding: 8, fontWeight: 600 }}>{ligne.reference || '—'}</td>
                    <td style={{ padding: 8 }}>
                      {ligne.date ? new Date(ligne.date).toLocaleString('fr-FR') : '—'}
                    </td>
                    <td style={{ padding: 8 }}>{ligne.source}</td>
                    <td style={{ padding: 8 }}>{ligne.libelle}</td>
                    <td style={{ padding: 8, textAlign: 'right', color: '#16a34a', fontWeight: 600 }}>
                      + {ligne.devise === 'CDF'
                        ? formatMoneyCdf(toNumber(ligne.montant))
                        : formatMoney(toNumber(ligne.montant))}
                    </td>
                  </tr>
                ))}
                <tr style={{ borderTop: '2px solid #e2e8f0', background: '#f8fafc' }}>
                  <td style={{ padding: 8, fontWeight: 700 }} colSpan={4}>
                    Total approvisionnements
                  </td>
                  <td style={{ padding: 8, textAlign: 'right', fontWeight: 700 }}>
                    {formatMoney(approUsd)} / {formatMoneyCdf(approCdf)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ClotureFields
        soldeTheoriqueUsd={soldeTheoUsd}
        soldeTheoriqueCdf={soldeTheoCdf}
        physiqueUsd={physiqueUsd}
        physiqueCdf={physiqueCdf}
        onPhysiqueUsdChange={setPhysiqueUsd}
        onPhysiqueCdfChange={setPhysiqueCdf}
      />

      <section className={styles.verdict}>
        <div>
          <span>Solde physique USD</span>
          <strong>{formatMoney(physiqueUsd)}</strong>
        </div>
        <div>
          <span>Écart USD</span>
          <strong className={ecartUsd === 0 ? styles.okText : ecartUsd < 0 ? styles.dangerText : styles.warnText}>
            {formatMoney(ecartUsd)}
          </strong>
        </div>
        <div>
          <span>Solde physique CDF</span>
          <strong>{formatMoneyCdf(physiqueCdf)}</strong>
        </div>
        <div>
          <span>Écart CDF</span>
          <strong className={ecartCdf === 0 ? styles.okText : ecartCdf < 0 ? styles.dangerText : styles.warnText}>
            {formatMoneyCdf(ecartCdf)}
          </strong>
        </div>
        <div className={`${styles.verdictBadge} ${verdict().tone}`}>{verdict().label}</div>
      </section>

      {(ecartUsd !== 0 || ecartCdf !== 0) && (
        <section
          style={{
            background: '#fff7ed', border: '1px solid #fdba74', borderRadius: 12,
            padding: '14px 16px', marginTop: 12, fontSize: 13.5, color: '#7c2d12',
          }}
        >
          <strong style={{ display: 'block', marginBottom: 6 }}>
            Écart constaté entre le comptage et le solde théorique
          </strong>
          <p style={{ margin: '0 0 10px', lineHeight: 1.5 }}>
            Le comptage physique ne remplace pas le solde du logiciel. Pour que les deux
            correspondent, l’écart doit donner lieu à une opération identifiable :{' '}
            <strong>
              {ecartUsd + ecartCdf >= 0
                ? 'un encaissement de régularisation'
                : 'une sortie de régularisation'}
            </strong>
            .
          </p>
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontWeight: 600, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={regulariser}
              onChange={(e) => setRegulariser(e.target.checked)}
              style={{ marginTop: 3 }}
            />
            <span>
              Créer l’opération de régularisation
              <span style={{ display: 'block', fontWeight: 400, marginTop: 2 }}>
                Sans cela, la clôture est enregistrée, le solde reste au théorique et l’écart
                reste à traiter.
              </span>
            </span>
          </label>
          {regulariser && (
            <input
              value={motifRegul}
              onChange={(e) => setMotifRegul(e.target.value)}
              placeholder="Motif de la régularisation (obligatoire)"
              style={{
                width: '100%', marginTop: 10, padding: 10,
                border: `1px solid ${motifRegul.trim() ? '#cbd5e1' : '#f59e0b'}`,
                borderRadius: 10, fontSize: 13,
              }}
            />
          )}
        </section>
      )}

      <section className={styles.observation}>
        <label>Observations</label>
        <textarea
          value={observation}
          onChange={(e) => setObservation(e.target.value)}
          placeholder="Notes ou explications (optionnel)."
        />
      </section>

      <div className={styles.actions}>
        {caisseOuverte === false ? (
          <span style={{ color: '#92400e', fontWeight: 600, fontSize: 13, alignSelf: 'center' }}>
            Caisse fermée — ouvrez-la (bandeau ci-dessus) pour pouvoir la clôturer.
          </span>
        ) : (
          <button type="button" onClick={handleSubmit} disabled={saving || loading}>
            {saving ? 'Enregistrement...' : 'Valider la clôture'}
          </button>
        )}
        <button type="button" className={styles.secondary} onClick={handlePrint} disabled={!lastCloture}>
          Imprimer PV
        </button>
        <button type="button" className={styles.secondary} onClick={handleExportHistory} disabled={exporting}>
          {exporting ? 'Export...' : 'Export historique'}
        </button>
      </div>

      <section className={styles.history}>
        <div className={styles.historyHeader}>
          <h3>Historique des clôtures</h3>
        </div>
        <div className={styles.historySelector}>
          <label>Consulter une clôture</label>
          <select value={selectedClotureId ?? ''} onChange={(e) => handleSelectCloture(e.target.value)}>
            <option value="">Sélectionner une date</option>
            {history.map((c) => (
              <option key={c.id} value={c.id}>
                {new Date(c.date_cloture).toLocaleString('fr-FR')} · {c.reference_numero}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.historyFilters}>
          <input
            type="date"
            value={historyFilters.date_debut}
            onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_debut: e.target.value }))}
          />
          <input
            type="date"
            value={historyFilters.date_fin}
            onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_fin: e.target.value }))}
          />
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
          <button type="button" className={styles.secondary} onClick={applyHistoryFilters}>
            Filtrer
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Référence</th>
              <th>Solde théorique USD</th>
              <th>Solde physique USD</th>
              <th>Écart USD</th>
              <th>Solde théorique CDF</th>
              <th>Solde physique CDF</th>
              <th>Écart CDF</th>
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
                <td>{c.reference_numero}</td>
                <td>{formatMoney(toNumber(c.solde_theorique_usd))}</td>
                <td>{formatMoney(toNumber(c.solde_physique_usd))}</td>
                <td className={toNumber(c.ecart_usd) === 0 ? styles.okText : toNumber(c.ecart_usd) < 0 ? styles.dangerText : styles.warnText}>
                  {formatMoney(toNumber(c.ecart_usd))}
                </td>
                <td>{formatMoneyCdf(toNumber(c.solde_theorique_cdf))}</td>
                <td>{formatMoneyCdf(toNumber(c.solde_physique_cdf))}</td>
                <td className={toNumber(c.ecart_cdf) === 0 ? styles.okText : toNumber(c.ecart_cdf) < 0 ? styles.dangerText : styles.warnText}>
                  {formatMoneyCdf(toNumber(c.ecart_cdf))}
                </td>
                <td>
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => downloadArchivedPdf(c)}
                    disabled={!c.pdf_path}
                  >
                    Télécharger
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
