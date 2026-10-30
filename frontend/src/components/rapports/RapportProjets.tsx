import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { format } from 'date-fns'
import { ArrowDownLeft, ArrowUpRight, Download, FileText, FolderKanban, Loader2, Search, Send, Settings2, X } from 'lucide-react'
import {
  getMouvementsProjet,
  getSyntheseProjets,
  listProjetsActivites,
  type MouvementsProjet,
  type PeriodeProjet,
  ProjetActivite,
  type SyntheseProjet,
} from '../../api/projetsActivites'
import { useAuth } from '../../contexts/AuthContext'
import { useNotification } from '../../contexts/NotificationContext'
import { usePermissions } from '../../hooks/usePermissions'
import { formatAmount, toNumber } from '../../utils/amount'
import { exporterProjetExcel, exporterProjetPDF, genererProjetPDF, libellePeriode, sortiesParDevise } from '../../utils/exportProjet'
import DateSaisie from '../DateSaisie'
import EnvoiRapportDialog from './EnvoiRapportDialog'
// Même habillage que l'écran de configuration : les deux vues présentent la
// même liste, l'une pour la gérer, l'autre pour en suivre l'argent.
import styles from '../settings/ProjectActivitySettings.module.css'

const debutAnnee = () => format(new Date(new Date().getFullYear(), 0, 1), 'yyyy-MM-dd')
const aujourdhui = () => format(new Date(), 'yyyy-MM-dd')
const dateCourte = (valeur: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')

type FiltreType = 'TOUS' | ProjetActivite['type']

const jour = (d: Date) => format(d, 'yyyy-MM-dd')

/** Raccourcis de période : la saisie libre reste possible à côté. */
const RACCOURCIS: { label: string; bornes: () => [string, string] }[] = [
  { label: 'Ce mois', bornes: () => { const n = new Date(); return [jour(new Date(n.getFullYear(), n.getMonth(), 1)), jour(n)] } },
  { label: 'Mois dernier', bornes: () => { const n = new Date(); return [jour(new Date(n.getFullYear(), n.getMonth() - 1, 1)), jour(new Date(n.getFullYear(), n.getMonth(), 0))] } },
  { label: 'Trimestre', bornes: () => { const n = new Date(); return [jour(new Date(n.getFullYear(), Math.floor(n.getMonth() / 3) * 3, 1)), jour(n)] } },
  { label: 'Cette année', bornes: () => [debutAnnee(), aujourdhui()] },
  { label: 'Année dernière', bornes: () => { const a = new Date().getFullYear() - 1; return [`${a}-01-01`, `${a}-12-31`] } },
]

const normaliser = (texte: string) => texte.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

/**
 * Le rapport réduit aux mouvements dont un libellé contient `filtre` : reçu,
 * payeur, canal pour les entrées ; bon, bénéficiaire, motif, réquisition pour
 * les sorties. Les totaux sont recalculés sur ce qui reste — c'est ce rapport-là
 * qui s'affiche, s'exporte et part au Bureau.
 */
function filtrerRapport(m: MouvementsProjet | null, filtre: string): MouvementsProjet | null {
  const aiguille = normaliser(filtre.trim())
  if (!m || !aiguille) return m
  const garde = (...champs: (string | null | undefined)[]) => normaliser(champs.filter(Boolean).join(' ')).includes(aiguille)
  const entrees = m.entrees.filter((e) => garde(e.numero, e.tiers, e.canal === 'BANQUE' ? 'Banque' : 'Caisse'))
  const sorties = m.sorties.filter((s) => garde(s.numero, s.beneficiaire, s.motif, s.requisition || 'Sortie directe'))
  const totalEntrees = entrees.reduce((t, e) => t + toNumber(e.montant_usd), 0)
  const parDevise: Record<string, number> = {}
  sorties.forEach((s) => { const d = (s.devise || 'USD').toUpperCase(); parDevise[d] = (parDevise[d] || 0) + toNumber(s.montant) })
  return {
    ...m,
    entrees,
    sorties,
    totaux: {
      entrees_usd: String(totalEntrees),
      sorties: Object.fromEntries(Object.entries(parDevise).map(([d, v]) => [d, String(v)])),
      solde_usd: String(totalEntrees - (parDevise.USD || 0)),
    },
  }
}

/** Début et fin, puis les raccourcis. */
function ChoixPeriode({ id, debut, fin, onChange, className = '' }: { id: string; debut: string; fin: string; onChange: (debut: string, fin: string) => void; className?: string }) {
  return (
    <div className={`${styles.periode} ${className}`}>
      <label htmlFor={`${id}-debut`}>Période</label>
      <div className={styles.periodeRange}>
        <DateSaisie id={`${id}-debut`} aria-label="Date de début" value={debut} max={fin || undefined} onChange={(v) => onChange(v, fin && fin < v ? v : fin)} />
        <span aria-hidden="true">→</span>
        <DateSaisie id={`${id}-fin`} aria-label="Date de fin" value={fin} min={debut || undefined} onChange={(v) => onChange(debut && debut > v ? v : debut, v)} />
      </div>
      <div className={styles.raccourcis}>
        {RACCOURCIS.map((r) => {
          const [d, f] = r.bornes()
          return (
            <button key={r.label} type="button" className={d === debut && f === fin ? styles.raccourciActif : ''} onClick={() => onChange(d, f)}>
              {r.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** Une ligne par devise : « 12 720,50 USD » puis « 1 250 000,00 CDF » en dessous. */
function MontantsParDevise({ sorties }: { sorties: Record<string, string> }) {
  const devises = Object.keys(sorties).sort((a, b) => (a === 'USD' ? -1 : b === 'USD' ? 1 : a.localeCompare(b)))
  if (devises.length === 0) return <strong>{formatAmount(0)} <small>USD</small></strong>
  return (
    <>
      {devises.map((d, i) => (
        <strong key={d} className={i > 0 ? styles.kpiSecondaire : undefined}>
          {formatAmount(sorties[d])} <small>{d}</small>
        </strong>
      ))}
    </>
  )
}

/**
 * Rapports › Projets & activités : ce que chaque projet a reçu et dépensé.
 * Lecture seule — la création et la modification restent dans Paramètres ›
 * Référentiels. `?projet=<id>` ouvre directement le détail d'un projet.
 */
export default function RapportProjets() {
  const { showError } = useNotification()
  const { user } = useAuth()
  const { hasPermission } = usePermissions()
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<ProjetActivite[]>([])
  const [synthese, setSynthese] = useState<Record<number, SyntheseProjet>>({})
  const [loading, setLoading] = useState(true)
  const [itemsError, setItemsError] = useState('')
  const [syntheseLoading, setSyntheseLoading] = useState(true)
  const [syntheseError, setSyntheseError] = useState('')
  const [syntheseVersion, setSyntheseVersion] = useState(0)
  const [recherche, setRecherche] = useState('')
  const [filtreType, setFiltreType] = useState<FiltreType>('TOUS')
  const [avecMouvementsSeuls, setAvecMouvementsSeuls] = useState(false)
  // Période des totaux et des rapports : l'exercice en cours par défaut.
  const [dateDebut, setDateDebut] = useState(debutAnnee)
  const [dateFin, setDateFin] = useState(aujourdhui)
  const periode: PeriodeProjet = useMemo(() => ({ date_debut: dateDebut, date_fin: dateFin }), [dateDebut, dateFin])
  const changerPeriode = (debut: string, fin: string) => { setDateDebut(debut); setDateFin(fin) }
  const [rapportBrut, setRapport] = useState<MouvementsProjet | null>(null)
  // Filtre par libellé dans le détail d'un projet.
  const [filtreLibelle, setFiltreLibelle] = useState('')
  const rapport = useMemo(() => filtrerRapport(rapportBrut, filtreLibelle), [rapportBrut, filtreLibelle])
  const filtreActif = filtreLibelle.trim() !== ''
  // Ce que les exports et l'envoi annoncent : la période, et le filtre s'il y en a un.
  const periodeExport: PeriodeProjet = useMemo(() => ({ ...periode, filtre: filtreLibelle.trim() || undefined }), [periode, filtreLibelle])
  const [ongletRapport, setOngletRapport] = useState<'entrees' | 'sorties'>('entrees')
  const [exportEnCours, setExportEnCours] = useState<'pdf' | 'excel' | null>(null)
  const [envoiOuvert, setEnvoiOuvert] = useState(false)

  // Le projet ouvert vit dans l'URL : le lien « Suivi » des Paramètres y mène
  // directement, et le retour arrière du navigateur referme le détail.
  const rapportOuvertId = Number(searchParams.get('projet')) || null
  const ouvrir = (id: number) => {
    setOngletRapport('entrees')
    setFiltreLibelle('')
    setEnvoiOuvert(false)
    setSearchParams((p) => { const suivant = new URLSearchParams(p); suivant.set('projet', String(id)); return suivant })
  }
  const fermer = useCallback(() => {
    setEnvoiOuvert(false)
    setRapport(null)
    setSearchParams((p) => { const suivant = new URLSearchParams(p); suivant.delete('projet'); return suivant })
  }, [setSearchParams])

  const chargerItems = useCallback(() => {
    setLoading(true)
    setItemsError('')
    return listProjetsActivites()
      .then(setItems)
      .catch((error: any) => {
        const message = error?.message || 'Impossible de charger les projets.'
        setItemsError(message)
        showError('Projets et activités', message)
      })
      .finally(() => setLoading(false))
  }, [showError])

  useEffect(() => { void chargerItems() }, [chargerItems])

  useEffect(() => {
    let annule = false
    setSynthese({})
    setSyntheseError('')
    setSyntheseLoading(true)
    getSyntheseProjets(periode)
      .then((lignes) => { if (!annule) setSynthese(Object.fromEntries(lignes.map((l) => [l.projet_id, l]))) })
      .catch((error: any) => {
        if (!annule) setSyntheseError(error?.message || 'Impossible de charger les totaux de la période.')
      })
      .finally(() => { if (!annule) setSyntheseLoading(false) })
    return () => { annule = true }
  }, [periode, syntheseVersion])

  // Le rapport ouvert suit la période choisie.
  useEffect(() => {
    if (rapportOuvertId === null) {
      setRapport(null)
      setEnvoiOuvert(false)
      return
    }
    let annule = false
    setRapport(null)
    getMouvementsProjet(rapportOuvertId, periode)
      .then((m) => { if (!annule) setRapport(m) })
      .catch((error: any) => {
        if (annule) return
        showError('Rapport du projet', error?.message || 'Impossible de charger les mouvements.')
        fermer()
      })
    return () => { annule = true }
  }, [rapportOuvertId, periode, fermer, showError])

  useEffect(() => {
    if (rapportOuvertId === null) return
    const fermerAvecEchap = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !envoiOuvert) fermer()
    }
    window.addEventListener('keydown', fermerAvecEchap)
    return () => window.removeEventListener('keydown', fermerAvecEchap)
  }, [rapportOuvertId, envoiOuvert, fermer])

  const emisPar = [user?.prenom, user?.nom].filter(Boolean).join(' ') || null

  // Chiffres clés repris dans le message : une ligne chacun, sans addition
  // entre devises.
  const resumeRapport = (m: MouvementsProjet) => [
    `Entrées : ${formatAmount(m.totaux.entrees_usd)} USD (${m.entrees.length} encaissement${m.entrees.length > 1 ? 's' : ''})`,
    `Sorties : ${sortiesParDevise(m.totaux.sorties)} (${m.sorties.length} décaissement${m.sorties.length > 1 ? 's' : ''})`,
    `Solde : ${formatAmount(m.totaux.solde_usd)} USD`,
  ]

  const exporter = async (type: 'pdf' | 'excel') => {
    if (!rapport) return
    setExportEnCours(type)
    try {
      if (type === 'pdf') await exporterProjetPDF(rapport, periodeExport, emisPar)
      else await exporterProjetExcel(rapport, periodeExport)
    } catch (error: any) {
      showError('Export', error?.message || "Impossible d'exporter le rapport.")
    } finally {
      setExportEnCours(null)
    }
  }

  const visibles = useMemo(() => {
    const aiguille = normaliser(recherche.trim())
    return items.filter((i) => {
      if (filtreType !== 'TOUS' && i.type !== filtreType) return false
      const s = synthese[i.id]
      if (avecMouvementsSeuls && !syntheseLoading && !syntheseError && !(s && (s.nb_entrees > 0 || s.nb_sorties > 0))) return false
      return !aiguille || normaliser(`${i.code} ${i.libelle} ${i.description || ''}`).includes(aiguille)
    })
  }, [items, synthese, recherche, filtreType, avecMouvementsSeuls, syntheseLoading, syntheseError])

  // Les chiffres clés suivent les filtres : « Activités » seules donne le
  // total des activités, pas celui de toute l'organisation.
  const totaux = useMemo(() => {
    const sorties: Record<string, number> = {}
    let entrees = 0
    visibles.forEach((item) => {
      const s = synthese[item.id]
      if (!s) return
      entrees += toNumber(s.entrees_usd)
      Object.entries(s.sorties).forEach(([d, v]) => { sorties[d] = (sorties[d] || 0) + toNumber(v) })
    })
    return { entrees, sorties, solde: entrees - (sorties.USD || 0) }
  }, [visibles, synthese])

  const actifs = visibles.filter((i) => i.is_active).length

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div className={styles.headerText}>
          <h2>Projets et activités</h2>
          <p>Ce que chaque projet a reçu et ce qu’il a dépensé sur la période. Cliquez sur un projet pour le détail de ses mouvements et ses exports PDF / Excel.</p>
        </div>
        {hasPermission('settings') && (
          <Link to="/settings?tab=general&sub=projets" className={styles.secondaryButton}>
            <Settings2 size={15} /> Gérer les projets
          </Link>
        )}
      </div>

      <div className={`${styles.toolbar} ${styles.reportToolbar}`} aria-busy={syntheseLoading}>
        <div className={styles.toolbarField}>
          <label htmlFor="rapport-projets-recherche">Recherche</label>
          <div className={styles.searchField}>
            <Search size={15} aria-hidden="true" />
            <input
              id="rapport-projets-recherche"
              type="search"
              placeholder="Code, libellé ou description…"
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
            />
          </div>
        </div>
        <div className={styles.periode}>
          <label htmlFor="rapport-projets-type">Type</label>
          <select id="rapport-projets-type" className={styles.filtreSelect} value={filtreType} onChange={(e) => setFiltreType(e.target.value as FiltreType)}>
            <option value="TOUS">Projets et activités</option>
            <option value="PROJET">Projets</option>
            <option value="ACTIVITE">Activités</option>
          </select>
        </div>
        <label className={styles.checkbox} title={syntheseError || undefined}>
          <input type="checkbox" checked={avecMouvementsSeuls} disabled={syntheseLoading || Boolean(syntheseError)} onChange={(e) => setAvecMouvementsSeuls(e.target.checked)} />
          Avec mouvements seulement
        </label>
        <ChoixPeriode className={styles.reportPeriod} id="rapport-projets" debut={dateDebut} fin={dateFin} onChange={changerPeriode} />
      </div>

      {(syntheseLoading || syntheseError) && (
        <div className={`${styles.inlineState} ${syntheseError ? styles.inlineStateError : ''}`} role={syntheseError ? 'alert' : 'status'}>
          {syntheseLoading ? (
            <><Loader2 size={15} className={styles.spin} /> Mise à jour des totaux de la période…</>
          ) : (
            <><span>{syntheseError}</span><button type="button" onClick={() => setSyntheseVersion((version) => version + 1)}>Réessayer</button></>
          )}
        </div>
      )}

      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <span>Projets actifs</span>
          <strong>{actifs}<small> / {visibles.length}</small></strong>
        </div>
        <div className={`${styles.kpi} ${styles.kpiEntree}`}>
          <span>Entrées</span>
          {syntheseLoading ? <strong>…</strong> : <strong>{formatAmount(totaux.entrees)} <small>USD</small></strong>}
        </div>
        <div className={`${styles.kpi} ${styles.kpiSortie}`}>
          <span>Sorties</span>
          {syntheseLoading ? <strong>…</strong> : <MontantsParDevise sorties={Object.fromEntries(Object.entries(totaux.sorties).map(([d, v]) => [d, String(v)]))} />}
        </div>
        <div className={`${styles.kpi} ${totaux.solde < 0 ? styles.kpiNegatif : ''}`}>
          <span>Solde (USD)</span>
          {syntheseLoading ? <strong>…</strong> : <strong>{formatAmount(totaux.solde)} <small>USD</small></strong>}
        </div>
      </div>

      {loading ? <div className={styles.empty}><Loader2 size={17} className={styles.spin} /> Chargement des projets…</div> : itemsError ? (
        <div className={`${styles.emptyState} ${styles.emptyStateError}`} role="alert">
          <strong>Chargement impossible</strong>
          <span>{itemsError}</span>
          <button type="button" className={styles.secondaryButton} onClick={() => void chargerItems()}>Réessayer</button>
        </div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>
          <FolderKanban size={28} aria-hidden="true" />
          <strong>Aucun projet ou activité configuré.</strong>
          <span>Ils se créent dans Paramètres › Référentiels.</span>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Libellé</th>
                <th>Type</th>
                <th className={styles.num}>Entrées</th>
                <th className={styles.num}>Sorties</th>
                <th className={styles.num}>Solde</th>
                <th>Statut</th>
                <th />
              </tr>
            </thead>
            <tbody>{visibles.map((item) => {
              const s = synthese[item.id]
              const solde = toNumber(s?.solde_usd ?? 0)
              return (
                <tr key={item.id} className={item.is_active ? '' : styles.rowInactive}>
                  <td data-label="Libellé">
                    <button type="button" className={styles.projetLink} onClick={() => ouvrir(item.id)}>
                      <span className={styles.code}>{item.code}</span>
                      <span className={styles.libelle}>{item.libelle}</span>
                    </button>
                    {item.description && <span className={styles.description}>{item.description}</span>}
                  </td>
                  <td data-label="Type">
                    <span className={`${styles.badge} ${item.type === 'PROJET' ? styles.badgeProjet : styles.badgeActivite}`}>
                      {item.type === 'PROJET' ? 'Projet' : 'Activité'}
                    </span>
                  </td>
                  <td data-label="Entrées" className={`${styles.num} ${styles.entree}`}>
                    {s ? `${formatAmount(s.entrees_usd)} USD` : syntheseLoading ? '…' : '—'}
                    {s && s.nb_entrees > 0 && <small>{s.nb_entrees} encaissement{s.nb_entrees > 1 ? 's' : ''}</small>}
                  </td>
                  <td data-label="Sorties" className={`${styles.num} ${styles.sortie}`}>
                    {s && s.nb_sorties > 0 ? sortiesParDevise(s.sorties) : syntheseLoading ? '…' : '—'}
                    {s && s.nb_sorties > 0 && <small>{s.nb_sorties} décaissement{s.nb_sorties > 1 ? 's' : ''}</small>}
                  </td>
                  <td data-label="Solde" className={`${styles.num} ${styles.solde} ${solde < 0 ? styles.negatif : ''}`}>
                    {s ? `${formatAmount(solde)} USD` : syntheseLoading ? '…' : '—'}
                  </td>
                  <td data-label="Statut">
                    <span className={`${styles.statut} ${item.is_active ? styles.statutActif : ''}`}>{item.is_active ? 'Actif' : 'Inactif'}</span>
                  </td>
                  <td className={styles.actionsCell}>
                    <div className={styles.actions}>
                      <button type="button" title="Rapport : entrées et sorties" aria-label={`Rapport de ${item.libelle}`} onClick={() => ouvrir(item.id)}><FileText size={15} /></button>
                    </div>
                  </td>
                </tr>
              )
            })}</tbody>
          </table>
          {visibles.length === 0 && <div className={styles.empty}>Aucun projet ne correspond aux filtres.</div>}
        </div>
      )}

      {rapportOuvertId !== null && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="projet-rapport-titre" onClick={fermer}>
          <div className={`${styles.dialog} ${styles.dialogLarge}`} onClick={(e) => e.stopPropagation()}>
            <div className={styles.dialogHeader}>
              <div>
                <h3 id="projet-rapport-titre">
                  {rapport ? <><span className={styles.code}>{rapport.projet.code}</span> {rapport.projet.libelle}</> : 'Rapport du projet'}
                </h3>
                <p className={styles.dialogSub}>Entrées et sorties {libellePeriode(periodeExport)}</p>
              </div>
              <div className={styles.dialogActions}>
                <button type="button" className={styles.secondaryButton} onClick={() => void exporter('pdf')} disabled={!rapport || exportEnCours !== null}>
                  {exportEnCours === 'pdf' ? <Loader2 size={15} className={styles.spin} /> : <FileText size={15} />} PDF
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void exporter('excel')} disabled={!rapport || exportEnCours !== null}>
                  {exportEnCours === 'excel' ? <Loader2 size={15} className={styles.spin} /> : <Download size={15} />} Excel
                </button>
                <button type="button" className={`${styles.primaryButton} ${styles.sendButton}`} onClick={() => setEnvoiOuvert(true)} disabled={!rapport}>
                  <Send size={15} /> Envoyer au Bureau
                </button>
                <button type="button" className={styles.iconButton} onClick={fermer} aria-label="Fermer"><X size={18} /></button>
              </div>
            </div>

            {!rapport ? <div className={styles.empty}><Loader2 size={18} className={styles.spin} /> Chargement…</div> : (
              <div className={styles.rapportBody}>
                <div className={`${styles.toolbar} ${styles.toolbarDetail}`}>
                  <div className={styles.searchField}>
                    <Search size={15} aria-hidden="true" />
                    <input
                      type="search"
                      placeholder="Filtrer par libellé : payeur, bénéficiaire, motif, n° de pièce…"
                      aria-label="Filtrer les mouvements par libellé"
                      value={filtreLibelle}
                      onChange={(e) => setFiltreLibelle(e.target.value)}
                    />
                  </div>
                  <ChoixPeriode id="rapport-projet-detail" debut={dateDebut} fin={dateFin} onChange={changerPeriode} />
                </div>
                {filtreActif && (
                  <p className={styles.note}>
                    {rapport.entrees.length + rapport.sorties.length} mouvement{rapport.entrees.length + rapport.sorties.length > 1 ? 's' : ''} sur {(rapportBrut?.entrees.length || 0) + (rapportBrut?.sorties.length || 0)} correspondent à « {filtreLibelle.trim()} ». Les totaux, les exports et l'envoi au Bureau portent sur cette sélection.
                  </p>
                )}
                <div className={styles.kpis}>
                  <div className={`${styles.kpi} ${styles.kpiEntree}`}>
                    <span><ArrowDownLeft size={13} /> Entrées</span>
                    <strong>{formatAmount(rapport.totaux.entrees_usd)} <small>USD</small></strong>
                  </div>
                  <div className={`${styles.kpi} ${styles.kpiSortie}`}>
                    <span><ArrowUpRight size={13} /> Sorties</span>
                    <MontantsParDevise sorties={rapport.totaux.sorties} />
                  </div>
                  <div className={`${styles.kpi} ${toNumber(rapport.totaux.solde_usd) < 0 ? styles.kpiNegatif : ''}`}>
                    <span>Solde (USD)</span>
                    <strong>{formatAmount(rapport.totaux.solde_usd)} <small>USD</small></strong>
                  </div>
                </div>

                <div className={styles.tabs} role="tablist">
                  <button type="button" role="tab" aria-selected={ongletRapport === 'entrees'} className={ongletRapport === 'entrees' ? styles.tabActive : ''} onClick={() => setOngletRapport('entrees')}>
                    Entrées <span>{rapport.entrees.length}</span>
                  </button>
                  <button type="button" role="tab" aria-selected={ongletRapport === 'sorties'} className={ongletRapport === 'sorties' ? styles.tabActive : ''} onClick={() => setOngletRapport('sorties')}>
                    Sorties <span>{rapport.sorties.length}</span>
                  </button>
                </div>

                <div className={styles.tableWrap}>
                  {ongletRapport === 'entrees' ? (
                    rapport.entrees.length === 0 ? <div className={styles.empty}>{filtreActif ? 'Aucune entrée ne correspond au filtre.' : 'Aucune entrée sur la période.'}</div> : (
                      <table className={styles.table}>
                        <thead><tr><th>Date</th><th>Reçu</th><th>Payeur</th><th>Canal</th><th className={styles.num}>Perçu</th><th className={styles.num}>Montant (USD)</th></tr></thead>
                        <tbody>{rapport.entrees.map((e) => (
                          <tr key={e.id}>
                            <td data-label="Date">{dateCourte(e.date)}</td>
                            <td data-label="Reçu">{e.numero || '—'}</td>
                            <td data-label="Payeur">{e.tiers || '—'}</td>
                            <td data-label="Canal">{e.canal === 'BANQUE' ? 'Banque' : 'Caisse'}</td>
                            <td data-label="Perçu" className={styles.num}>{formatAmount(e.montant_percu)} {e.devise_perception}</td>
                            <td data-label="Montant (USD)" className={`${styles.num} ${styles.entree}`}>{formatAmount(e.montant_usd)}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    )
                  ) : (
                    rapport.sorties.length === 0 ? <div className={styles.empty}>{filtreActif ? 'Aucune sortie ne correspond au filtre.' : 'Aucune sortie sur la période.'}</div> : (
                      <table className={styles.table}>
                        <thead><tr><th>Date</th><th>Bon</th><th>Bénéficiaire · motif</th><th>Réquisition</th><th className={styles.num}>Montant</th></tr></thead>
                        <tbody>{rapport.sorties.map((s) => (
                          <tr key={s.id}>
                            <td data-label="Date">{dateCourte(s.date)}</td>
                            <td data-label="Bon">{s.numero || '—'}</td>
                            <td data-label="Bénéficiaire">
                              <span className={styles.libelle}>{s.beneficiaire || '—'}</span>
                              {s.motif && <span className={styles.description}>{s.motif}</span>}
                            </td>
                            <td data-label="Réquisition">{s.requisition || <span className={styles.muted}>Sortie directe</span>}</td>
                            <td data-label="Montant" className={`${styles.num} ${styles.sortie}`}>{formatAmount(s.montant)} {s.devise}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    )
                  )}
                </div>
                {Object.keys(rapport.totaux.sorties).some((d) => d !== 'USD') && (
                  <p className={styles.note}>Le solde ne tient compte que des sorties en USD ; les sorties en CDF sont présentées à part.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      {envoiOuvert && rapport && (
        <EnvoiRapportDialog
          titre={`${rapport.projet.type === 'ACTIVITE' ? 'Activité' : 'Projet'} ${rapport.projet.code} - ${rapport.projet.libelle}`}
          periode={libellePeriode(periodeExport)}
          resume={resumeRapport(rapport)}
          genererPdf={() => genererProjetPDF(rapport, periodeExport, emisPar)}
          onClose={() => setEnvoiOuvert(false)}
        />
      )}
    </div>
  )
}
