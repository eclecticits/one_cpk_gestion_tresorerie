import { useEffect, useMemo, useState } from 'react'
import { format } from 'date-fns'
import { ArrowDownLeft, ArrowUpRight, Download, FileText, FolderKanban, Loader2, Pencil, Plus, Power, Search, X } from 'lucide-react'
import {
  createProjetActivite,
  getMouvementsProjet,
  getSyntheseProjets,
  listProjetsActivites,
  type MouvementsProjet,
  type PeriodeProjet,
  ProjetActivite,
  ProjetActiviteType,
  type SyntheseProjet,
  updateProjetActivite,
} from '../../api/projetsActivites'
import { useAuth } from '../../contexts/AuthContext'
import { useNotification } from '../../contexts/NotificationContext'
import { formatAmount, toNumber } from '../../utils/amount'
import { exporterProjetExcel, exporterProjetPDF, libellePeriode, sortiesParDevise } from '../../utils/exportProjet'
import DateSaisie from '../DateSaisie'
import styles from './ProjectActivitySettings.module.css'

const emptyForm = { code: '', libelle: '', type: 'PROJET' as ProjetActiviteType, description: '', is_active: true }

const debutAnnee = () => format(new Date(new Date().getFullYear(), 0, 1), 'yyyy-MM-dd')
const aujourdhui = () => format(new Date(), 'yyyy-MM-dd')
const dateCourte = (valeur: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')

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

export default function ProjectActivitySettings() {
  const { showSuccess, showError } = useNotification()
  const { user } = useAuth()
  const [items, setItems] = useState<ProjetActivite[]>([])
  const [synthese, setSynthese] = useState<Record<number, SyntheseProjet>>({})
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [recherche, setRecherche] = useState('')
  // Période des totaux et des rapports : l'exercice en cours par défaut.
  const [dateDebut, setDateDebut] = useState(debutAnnee)
  const [dateFin, setDateFin] = useState(aujourdhui)
  const periode: PeriodeProjet = useMemo(() => ({ date_debut: dateDebut, date_fin: dateFin }), [dateDebut, dateFin])
  const [rapport, setRapport] = useState<MouvementsProjet | null>(null)
  const [rapportOuvertId, setRapportOuvertId] = useState<number | null>(null)
  const [ongletRapport, setOngletRapport] = useState<'entrees' | 'sorties'>('entrees')
  const [exportEnCours, setExportEnCours] = useState<'pdf' | 'excel' | null>(null)

  const load = async () => {
    try {
      setLoading(true)
      setItems(await listProjetsActivites())
    } catch (error: any) {
      showError('Projets et activités', error?.message || 'Impossible de charger le référentiel.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    let annule = false
    getSyntheseProjets(periode)
      .then((lignes) => { if (!annule) setSynthese(Object.fromEntries(lignes.map((l) => [l.projet_id, l]))) })
      .catch(() => { if (!annule) setSynthese({}) })
    return () => { annule = true }
  }, [periode])

  // Le rapport ouvert suit la période choisie.
  useEffect(() => {
    if (rapportOuvertId === null) return
    let annule = false
    setRapport(null)
    getMouvementsProjet(rapportOuvertId, periode)
      .then((m) => { if (!annule) setRapport(m) })
      .catch((error: any) => {
        if (annule) return
        showError('Rapport du projet', error?.message || 'Impossible de charger les mouvements.')
        setRapportOuvertId(null)
      })
    return () => { annule = true }
  }, [rapportOuvertId, periode])

  const reset = () => {
    setForm(emptyForm)
    setEditingId(null)
    setShowForm(false)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      setSaving(true)
      const payload = { ...form, code: form.code.trim(), libelle: form.libelle.trim(), description: form.description.trim() || null }
      if (editingId) await updateProjetActivite(editingId, payload)
      else await createProjetActivite(payload)
      showSuccess('Projets et activités', editingId ? 'Élément mis à jour.' : 'Élément ajouté.')
      reset()
      await load()
    } catch (error: any) {
      showError('Projets et activités', error?.message || 'Impossible de sauvegarder cet élément.')
    } finally {
      setSaving(false)
    }
  }

  const exporter = async (type: 'pdf' | 'excel') => {
    if (!rapport) return
    setExportEnCours(type)
    try {
      if (type === 'pdf') await exporterProjetPDF(rapport, periode, [user?.prenom, user?.nom].filter(Boolean).join(' ') || null)
      else await exporterProjetExcel(rapport, periode)
    } catch (error: any) {
      showError('Export', error?.message || "Impossible d'exporter le rapport.")
    } finally {
      setExportEnCours(null)
    }
  }

  const visibles = useMemo(() => {
    const aiguille = recherche.trim().toLowerCase()
    if (!aiguille) return items
    return items.filter((i) => `${i.code} ${i.libelle} ${i.description || ''}`.toLowerCase().includes(aiguille))
  }, [items, recherche])

  const totaux = useMemo(() => {
    const sorties: Record<string, number> = {}
    let entrees = 0
    Object.values(synthese).forEach((s) => {
      entrees += toNumber(s.entrees_usd)
      Object.entries(s.sorties).forEach(([d, v]) => { sorties[d] = (sorties[d] || 0) + toNumber(v) })
    })
    return { entrees, sorties, solde: entrees - (sorties.USD || 0) }
  }, [synthese])

  const actifs = items.filter((i) => i.is_active).length

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div className={styles.headerText}>
          <h2>Projets et activités</h2>
          <p>Ce que chaque projet a reçu et ce qu’il a dépensé. Le rattachement reste facultatif sur les encaissements, les réquisitions et les sorties directes.</p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={() => { reset(); setShowForm(true) }}>
          <Plus size={16} /> Ajouter
        </button>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.searchField}>
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            placeholder="Rechercher un projet…"
            aria-label="Rechercher un projet ou une activité"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </div>
        <div className={styles.periode}>
          <label htmlFor="projets-date-debut">Période</label>
          <div className={styles.periodeRange}>
            <DateSaisie id="projets-date-debut" aria-label="Date de début" value={dateDebut} max={dateFin || undefined} onChange={setDateDebut} />
            <span aria-hidden="true">→</span>
            <DateSaisie id="projets-date-fin" aria-label="Date de fin" value={dateFin} min={dateDebut || undefined} onChange={setDateFin} />
          </div>
        </div>
      </div>

      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <span>Projets actifs</span>
          <strong>{actifs}<small> / {items.length}</small></strong>
        </div>
        <div className={`${styles.kpi} ${styles.kpiEntree}`}>
          <span>Entrées</span>
          <strong>{formatAmount(totaux.entrees)} <small>USD</small></strong>
        </div>
        <div className={`${styles.kpi} ${styles.kpiSortie}`}>
          <span>Sorties</span>
          <MontantsParDevise sorties={Object.fromEntries(Object.entries(totaux.sorties).map(([d, v]) => [d, String(v)]))} />
        </div>
        <div className={`${styles.kpi} ${totaux.solde < 0 ? styles.kpiNegatif : ''}`}>
          <span>Solde (USD)</span>
          <strong>{formatAmount(totaux.solde)} <small>USD</small></strong>
        </div>
      </div>

      {loading ? <div className={styles.empty}>Chargement...</div> : items.length === 0 ? (
        <div className={styles.emptyState}>
          <FolderKanban size={28} aria-hidden="true" />
          <strong>Aucun projet ou activité configuré.</strong>
          <span>Créez-en un pour suivre ses entrées et ses sorties.</span>
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
                    <button type="button" className={styles.projetLink} onClick={() => { setOngletRapport('entrees'); setRapportOuvertId(item.id) }}>
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
                    {s ? `${formatAmount(s.entrees_usd)} USD` : '—'}
                    {s && s.nb_entrees > 0 && <small>{s.nb_entrees} encaissement{s.nb_entrees > 1 ? 's' : ''}</small>}
                  </td>
                  <td data-label="Sorties" className={`${styles.num} ${styles.sortie}`}>
                    {s && s.nb_sorties > 0 ? sortiesParDevise(s.sorties) : '—'}
                    {s && s.nb_sorties > 0 && <small>{s.nb_sorties} décaissement{s.nb_sorties > 1 ? 's' : ''}</small>}
                  </td>
                  <td data-label="Solde" className={`${styles.num} ${styles.solde} ${solde < 0 ? styles.negatif : ''}`}>
                    {s ? `${formatAmount(solde)} USD` : '—'}
                  </td>
                  <td data-label="Statut">
                    <span className={`${styles.statut} ${item.is_active ? styles.statutActif : ''}`}>{item.is_active ? 'Actif' : 'Inactif'}</span>
                  </td>
                  <td className={styles.actionsCell}>
                    <div className={styles.actions}>
                    <button type="button" title="Rapport : entrées et sorties" aria-label={`Rapport de ${item.libelle}`} onClick={() => { setOngletRapport('entrees'); setRapportOuvertId(item.id) }}><FileText size={15} /></button>
                    <button type="button" title="Modifier" aria-label={`Modifier ${item.libelle}`} onClick={() => { setEditingId(item.id); setForm({ code: item.code, libelle: item.libelle, type: item.type, description: item.description || '', is_active: item.is_active }); setShowForm(true) }}><Pencil size={15} /></button>
                    <button type="button" title={item.is_active ? 'Désactiver' : 'Activer'} aria-label={item.is_active ? `Désactiver ${item.libelle}` : `Activer ${item.libelle}`} onClick={async () => { try { await updateProjetActivite(item.id, { is_active: !item.is_active }); await load() } catch (error: any) { showError('Projets et activités', error?.message || 'Impossible de modifier le statut.') } }}><Power size={15} /></button>
                    </div>
                  </td>
                </tr>
              )
            })}</tbody>
          </table>
          {visibles.length === 0 && <div className={styles.empty}>Aucun résultat pour « {recherche} ».</div>}
        </div>
      )}

      {showForm && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="projet-form-titre" onClick={reset}>
          <form className={styles.dialog} onSubmit={submit} onClick={(e) => e.stopPropagation()}>
            <div className={styles.dialogHeader}>
              <h3 id="projet-form-titre">{editingId ? 'Modifier' : 'Ajouter'} un projet ou une activité</h3>
              <button type="button" className={styles.iconButton} onClick={reset} aria-label="Fermer"><X size={18} /></button>
            </div>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span>Code</span>
                <input placeholder="Ex. FORM-2026" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} required />
              </label>
              <label className={styles.field}>
                <span>Type</span>
                <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value as ProjetActiviteType })}>
                  <option value="PROJET">Projet</option>
                  <option value="ACTIVITE">Activité</option>
                </select>
              </label>
              <label className={`${styles.field} ${styles.fieldWide}`}>
                <span>Libellé</span>
                <input placeholder="Ex. Formation continue 2026" value={form.libelle} onChange={e => setForm({ ...form, libelle: e.target.value })} required />
              </label>
              <label className={`${styles.field} ${styles.fieldWide}`}>
                <span>Description (facultatif)</span>
                <textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
              </label>
              <label className={styles.checkbox}><input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} /> Actif</label>
            </div>
            <div className={styles.dialogFooter}>
              <button type="button" className={styles.secondaryButton} onClick={reset}>Annuler</button>
              <button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? 'Enregistrement...' : editingId ? 'Mettre à jour' : 'Enregistrer'}</button>
            </div>
          </form>
        </div>
      )}

      {rapportOuvertId !== null && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="projet-rapport-titre" onClick={() => setRapportOuvertId(null)}>
          <div className={`${styles.dialog} ${styles.dialogLarge}`} onClick={(e) => e.stopPropagation()}>
            <div className={styles.dialogHeader}>
              <div>
                <h3 id="projet-rapport-titre">
                  {rapport ? <><span className={styles.code}>{rapport.projet.code}</span> {rapport.projet.libelle}</> : 'Rapport du projet'}
                </h3>
                <p className={styles.dialogSub}>Entrées et sorties {libellePeriode(periode)}</p>
              </div>
              <div className={styles.dialogActions}>
                <button type="button" className={styles.secondaryButton} onClick={() => void exporter('pdf')} disabled={!rapport || exportEnCours !== null}>
                  {exportEnCours === 'pdf' ? <Loader2 size={15} className={styles.spin} /> : <FileText size={15} />} PDF
                </button>
                <button type="button" className={styles.secondaryButton} onClick={() => void exporter('excel')} disabled={!rapport || exportEnCours !== null}>
                  {exportEnCours === 'excel' ? <Loader2 size={15} className={styles.spin} /> : <Download size={15} />} Excel
                </button>
                <button type="button" className={styles.iconButton} onClick={() => setRapportOuvertId(null)} aria-label="Fermer"><X size={18} /></button>
              </div>
            </div>

            {!rapport ? <div className={styles.empty}><Loader2 size={18} className={styles.spin} /> Chargement…</div> : (
              <div className={styles.rapportBody}>
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
                    rapport.entrees.length === 0 ? <div className={styles.empty}>Aucune entrée sur la période.</div> : (
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
                    rapport.sorties.length === 0 ? <div className={styles.empty}>Aucune sortie sur la période.</div> : (
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
    </div>
  )
}
