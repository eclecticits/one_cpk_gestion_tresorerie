import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { format } from 'date-fns'
import { Ban, Banknote, FileSpreadsheet, FileText, History, LayoutDashboard, List, Printer, Settings2, Upload, UsersRound, X } from 'lucide-react'
import {
  documentsNotesDebit,
  LIBELLE_STATUT_NOTE,
  listerImportsNotes,
  listerNotesDebit,
  listerToutesNotesDebit,
  PERMISSION_IMPORT_NOTES_DEBIT,
  situationCompleteNotesDebit,
  situationNotesDebit,
  type ImportNotesDebit,
  type ListeNotesDebit,
  type NoteDebitExpert,
  type SituationNotesDebit,
  type StatutSituationMembre,
  type StatutNotes,
} from '../api/notesDebit'
import NoteDebitFiche from '../components/NoteDebitFiche'
import NotesDebitImport from '../components/NotesDebitImport'
import NotesDebitTableauDeBord, { type FiltreListe } from '../components/NotesDebitTableauDeBord'
import PaymentManager from '../components/PaymentManager'
import RowActionsMenu, { type ActionLigne } from '../components/RowActionsMenu'
import { useAuth } from '../contexts/AuthContext'
import { useConfirmWithInput } from '../contexts/ConfirmContext'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { usePermissions } from '../hooks/usePermissions'
import { useToast } from '../hooks/useToast'
import { apiRequest, ApiError } from '../lib/apiClient'
import type { Encaissement } from '../types'
import { generateNotesDebitPDF } from '../utils/pdfNotesDebit'
import styles from './NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

const PAR_PAGE = 50

/** Imprime des notes en un seul PDF, une page par note. */
async function imprimerNotes(params: { ids?: string[]; import_id?: string }) {
  const { notes, comptes } = await documentsNotesDebit(params)
  await generateNotesDebitPDF(notes, comptes)
  return notes.length
}

type Onglet = 'bord' | 'situation' | 'liste' | 'imports'

/**
 * Le poste de recette d'une colonne de la situation, sous son titre. Un poste
 * par catégorie s'abrège ; le détail est dans l'infobulle. Une colonne sans
 * rattachement le dit, pour qu'on aille la régler dans les paramètres.
 */
function PosteEntete({ postes }: { postes?: Array<{ categorie_membre: string; code: string; libelle: string | null }> }) {
  if (!postes) return null
  if (postes.length === 0) {
    return <span className={styles.posteEnteteManquant} title="Aucun poste : à régler dans Paramètres notes de débit">sans poste</span>
  }
  const detail = postes
    .map(p => `${p.categorie_membre === '*' ? 'Toutes catégories' : p.categorie_membre} : ${p.code}${p.libelle ? ` — ${p.libelle}` : ''}`)
    .join('\n')
  const codes = [...new Set(postes.map(p => p.code))]
  return <span className={styles.posteEntete} title={detail}>{codes.length === 1 ? codes[0] : `${codes.length} postes`}</span>
}

/**
 * Notes de débit des experts-comptables et des SEC.
 *
 * Une note de débit est un encaissement non payé rattaché à un expert : la
 * liste lit les mêmes données que les encaissements, et « Encaisser » ouvre le
 * règlement de la note elle-même — jamais une seconde note qui laisserait la
 * première ouverte.
 */
export default function NotesDebitExperts() {
  const { hasPermission } = usePermissions()
  const peutImporter = hasPermission(PERMISSION_IMPORT_NOTES_DEBIT)
  // `?q=` : on arrive de la fiche d'un expert, directement sur ses notes.
  const [parametres] = useSearchParams()
  const qInitial = parametres.get('q') ?? ''
  const [onglet, setOnglet] = useState<Onglet>(qInitial ? 'liste' : 'bord')
  const [importFiltre, setImportFiltre] = useState<ImportNotesDebit | { id: string; fichier: string } | null>(null)
  // Le filtre posé par le tableau de bord ; la clé remonte la liste pour l'appliquer.
  const [filtreListe, setFiltreListe] = useState<{ cle: number; filtre: FiltreListe }>({
    cle: 0,
    filtre: qInitial ? { q: qInitial, statut: 'toutes' } : {},
  })

  const voirNotesImport = (imp: { id: string; fichier: string }) => {
    setImportFiltre(imp)
    setOnglet('liste')
  }

  const [importOuvert, setImportOuvert] = useState(false)

  const ouvrirListe = (filtre: FiltreListe) => {
    setImportFiltre(null)
    setFiltreListe((avant) => ({ cle: avant.cle + 1, filtre }))
    setOnglet('liste')
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <h1>Notes de débit</h1>
          <p>Cotisations, pénalités et arriérés des experts-comptables et des SEC.</p>
        </div>
        <div className={styles.actionsLigne}>
          {hasPermission('settings') && (
            <Link to="/settings?tab=general&sub=encaissements" className={styles.lienDiscret}>
              <Settings2 size={16} aria-hidden /> Montants par défaut (tarifs)
            </Link>
          )}
          {peutImporter && (
            <button type="button" className={styles.primaryBtn} onClick={() => setImportOuvert(true)}>
              <Upload size={16} aria-hidden /> Importer (Excel)
            </button>
          )}
        </div>
      </header>

      <div className={styles.onglets} role="tablist" aria-label="Notes de débit">
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'bord'}
          className={onglet === 'bord' ? styles.ongletActif : styles.onglet}
          onClick={() => setOnglet('bord')}
        >
          <LayoutDashboard size={16} aria-hidden /> Tableau de bord
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'situation'}
          className={onglet === 'situation' ? styles.ongletActif : styles.onglet}
          onClick={() => setOnglet('situation')}
        >
          <UsersRound size={16} aria-hidden /> Situation des membres
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={onglet === 'liste'}
          className={onglet === 'liste' ? styles.ongletActif : styles.onglet}
          onClick={() => setOnglet('liste')}
        >
          <List size={16} aria-hidden /> Liste
        </button>
        {peutImporter && (
          <button
            type="button"
            role="tab"
            aria-selected={onglet === 'imports'}
            className={onglet === 'imports' ? styles.ongletActif : styles.onglet}
            onClick={() => setOnglet('imports')}
          >
            <History size={16} aria-hidden /> Imports
          </button>
        )}
      </div>

      {onglet === 'bord' && <NotesDebitTableauDeBord onOuvrirListe={ouvrirListe} />}
      {onglet === 'situation' && (
        <SituationMembres
          onVoirNotes={(numeroOrdre) => ouvrirListe({ q: numeroOrdre, statut: 'toutes' })}
        />
      )}
      {onglet === 'liste' && (
        <ListeNotes
          key={filtreListe.cle}
          filtreInitial={filtreListe.filtre}
          importFiltre={importFiltre}
          onRetirerImport={() => setImportFiltre(null)}
          onVoirImport={(imp) => setImportFiltre(imp)}
        />
      )}
      {importOuvert && peutImporter && (
        <NotesDebitImport
          onClose={() => setImportOuvert(false)}
          onImported={(resultat) => voirNotesImport({ id: resultat.import_id, fichier: resultat.fichier })}
        />
      )}
      {onglet === 'imports' && peutImporter && <HistoriqueImports onVoirNotes={voirNotesImport} />}
    </div>
  )
}

const SITUATION_PAR_PAGE = 25

function SituationMembres({ onVoirNotes }: { onVoirNotes: (numeroOrdre: string) => void }) {
  // N suit l'exercice budgétaire en cours (voir le tableau de bord).
  const [annee, setAnnee] = useState<number | null>(null)
  const [exerciceCourant, setExerciceCourant] = useState<number | null>(null)
  const [recherche, setRecherche] = useState('')
  const rechercheStable = useDebouncedValue(recherche)
  const [typeClient, setTypeClient] = useState('')
  const [statut, setStatut] = useState<StatutSituationMembre>('toutes')
  const [page, setPage] = useState(0)
  // Un filtre qui change ramène à la première page, dans le même rendu : un
  // effet séparé lancerait d'abord une requête sur l'ancienne page.
  const [filtresVus, setFiltresVus] = useState({ annee, rechercheStable, typeClient, statut })
  if (
    filtresVus.annee !== annee ||
    filtresVus.rechercheStable !== rechercheStable ||
    filtresVus.typeClient !== typeClient ||
    filtresVus.statut !== statut
  ) {
    setFiltresVus({ annee, rechercheStable, typeClient, statut })
    setPage(0)
  }
  const [donnees, setDonnees] = useState<SituationNotesDebit | null>(null)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    let actif = true
    setChargement(true)
    setErreur(null)
    situationNotesDebit({
      annee: annee ?? undefined,
      q: rechercheStable.trim(),
      type_client: typeClient,
      statut,
      limit: SITUATION_PAR_PAGE,
      offset: page * SITUATION_PAR_PAGE,
    })
      .then((reponse) => {
        if (!actif) return
        setDonnees(reponse)
        setExerciceCourant(reponse.exercice_courant)
      })
      .catch((err) => {
        if (actif) setErreur(err instanceof ApiError ? err.message : 'Impossible de charger la situation des membres.')
      })
      .finally(() => {
        if (actif) setChargement(false)
      })
    return () => {
      actif = false
    }
  }, [annee, rechercheStable, typeClient, statut, page])

  const { user } = useAuth()
  const { notifyError } = useToast()
  const [export_, setExport] = useState<'pdf' | 'excel' | null>(null)

  /** Toute la situation filtrée, pas la seule page affichée. */
  const exporter = async (formatExport: 'pdf' | 'excel') => {
    setExport(formatExport)
    try {
      const situation = await situationCompleteNotesDebit({
        annee: annee ?? undefined,
        q: rechercheStable.trim(),
        type_client: typeClient,
        statut,
      })
      const filtres = [
        { label: 'Exercice N', value: String(situation.annee) },
        { label: 'Membres', value: typeClient === 'sec' ? 'SEC' : typeClient ? 'Experts-comptables' : 'EC et SEC' },
        statut !== 'toutes' && {
          label: 'Situation',
          value: { en_retard: 'En retard', partiel: 'Paiement partiel', en_regle: 'En règle', en_avance: 'En avance N+1' }[statut],
        },
        rechercheStable.trim() && { label: 'Recherche', value: rechercheStable.trim() },
      ].filter((f): f is { label: string; value: string } => Boolean(f))
      const mod = await import('../utils/exportNotesDebit')
      const params = {
        situation,
        filtres,
        organisation: user?.organisation_name || user?.organisation_slug || 'ONEC',
      }
      await (formatExport === 'pdf' ? mod.exporterSituationPDF(params) : mod.exporterSituationExcel(params))
    } catch (err) {
      notifyError('Export', err instanceof ApiError ? err.message : "Impossible d'exporter la situation des membres.")
    } finally {
      setExport(null)
    }
  }

  const total = donnees?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / SITUATION_PAR_PAGE))
  const totaux = donnees?.totaux
  // L'année choisie, à défaut celle que le serveur a retenue.
  const n = annee ?? donnees?.annee ?? null
  const an = (decalage: number, repli: string) => (n == null ? repli : String(n + decalage))

  return (
    <div className={styles.situationPage}>
      <section className={styles.filtres} aria-label="Filtres de la situation des membres">
        <input
          type="search"
          className={styles.recherche}
          placeholder="Rechercher par n° d’ordre ou nom…"
          value={recherche}
          onChange={(e) => setRecherche(e.target.value)}
        />
        <label className={styles.filtreAvecLabel}>
          <span>Exercice N</span>
          <select value={n ?? ''} onChange={(e) => setAnnee(Number(e.target.value))} disabled={exerciceCourant == null}>
            {exerciceCourant != null &&
              [0, 1, 2, 3].map((decalage) => (
                <option key={decalage} value={exerciceCourant - decalage}>
                  {exerciceCourant - decalage}
                </option>
              ))}
          </select>
        </label>
        <select value={typeClient} onChange={(e) => setTypeClient(e.target.value)} aria-label="Type de membre">
          <option value="">EC et SEC</option>
          <option value="expert_comptable">Experts-comptables</option>
          <option value="sec">SEC</option>
        </select>
        <select
          value={statut}
          onChange={(e) => setStatut(e.target.value as StatutSituationMembre)}
          aria-label="Situation financière"
        >
          <option value="toutes">Toutes les situations</option>
          <option value="en_retard">En retard</option>
          <option value="partiel">Paiement partiel</option>
          <option value="en_regle">En règle</option>
          <option value="en_avance">En avance N+1</option>
        </select>
        <div className={styles.exports}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('pdf')}
            disabled={export_ !== null || total === 0}
            title="Exporter toute la situation filtrée en PDF"
          >
            <FileText size={16} aria-hidden /> {export_ === 'pdf' ? 'Export…' : 'PDF'}
          </button>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('excel')}
            disabled={export_ !== null || total === 0}
            title="Exporter toute la situation filtrée en Excel"
          >
            <FileSpreadsheet size={16} aria-hidden /> {export_ === 'excel' ? 'Export…' : 'Excel'}
          </button>
        </div>
      </section>

      <section className={styles.summaryStrip} aria-label={`Synthèse N ${an(0, '')}`}>
        <SituationKpi libelle="Membres" valeur={String(total)} />
        <SituationKpi libelle={`Cotisations ≤ ${an(-1, 'N-1')}`} valeur={montant(totaux?.cotisations_anterieures ?? 0)} />
        <SituationKpi libelle={`Pénalités ≤ ${an(-1, 'N-1')}`} valeur={montant(totaux?.penalites_anterieures ?? 0)} ton="warn" />
        <SituationKpi libelle={`Cotisation N (${an(0, '…')})`} valeur={montant(totaux?.cotisation_n ?? 0)} />
        <SituationKpi libelle={`Pénalités N (${an(0, '…')})`} valeur={montant(totaux?.penalites_n ?? 0)} ton="warn" />
        <SituationKpi libelle="Autres créances" valeur={montant(totaux?.autres_creances ?? 0)} ton="info" />
        <SituationKpi libelle="Reste exigible" valeur={montant(totaux?.reste_du ?? 0)} ton="err" />
        <SituationKpi libelle={`Avances N+1 (${an(1, '…')})`} valeur={montant(totaux?.avance_n_plus_1 ?? 0)} ton="ok" />
      </section>

      {erreur && <p className={styles.erreurBloc}>{erreur}</p>}

      <section className={styles.card}>
        <div className={styles.cardHeader}>
          <div>
            <h2>Situation consolidée par membre</h2>
            <span className={styles.muted}>N = {an(0, '…')} · les paiements anticipatifs sont isolés en N+1</span>
          </div>
          {chargement && <span className={styles.muted}>Mise à jour…</span>}
        </div>
        <div className={styles.tableContainer}>
          <table className={`${styles.table} ${styles.situationTable}`}>
            <thead>
              <tr>
                <th>Membre</th>
                <th>N° d’ordre</th>
                <th className={styles.num}>Cotisations ≤ N-1<PosteEntete postes={donnees?.rattachements?.cotisations_anterieures} /></th>
                <th className={styles.num}>Pénalités ≤ N-1<PosteEntete postes={donnees?.rattachements?.penalites_anterieures} /></th>
                <th className={styles.num}>Cotisation N<PosteEntete postes={donnees?.rattachements?.cotisation_n} /></th>
                <th className={styles.num}>Pénalités N<PosteEntete postes={donnees?.rattachements?.penalites_n} /></th>
                <th>Autres créances<PosteEntete postes={donnees?.rattachements?.autres_creances} /></th>
                <th className={styles.num}>Total</th>
                <th className={styles.num}>Règlements</th>
                <th className={styles.num}>Reste dû</th>
                <th className={styles.num}>Avance N+1</th>
                <th>Situation</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {chargement && !donnees ? (
                <tr><td colSpan={13} className={styles.vide}>Chargement…</td></tr>
              ) : donnees?.items.length === 0 ? (
                <tr><td colSpan={13} className={styles.vide}>Aucune situation pour ces critères.</td></tr>
              ) : (
                donnees?.items.map((ligne) => {
                  const detailsAutres = ligne.autres_details.map((detail) => `${detail.libelle} (${detail.exercice})`).join(' · ')
                  return (
                    <tr key={ligne.expert.id}>
                      <td>
                        <button type="button" className={styles.identiteMembre} onClick={() => onVoirNotes(ligne.expert.numero_ordre)}>
                          <strong>{ligne.expert.nom}</strong>
                          <small>{ligne.type_client === 'sec' ? 'SEC' : ligne.expert.statut_professionnel || 'Expert-comptable'}</small>
                        </button>
                      </td>
                      <td className={styles.numero}>{ligne.expert.numero_ordre}</td>
                      <td className={styles.num}>{montant(ligne.cotisations_anterieures)}</td>
                      <td className={`${styles.num} ${Number(ligne.penalites_anterieures) > 0 ? styles.montantPenalite : ''}`}>{montant(ligne.penalites_anterieures)}</td>
                      <td className={styles.num}>{montant(ligne.cotisation_n)}</td>
                      <td className={`${styles.num} ${Number(ligne.penalites_n) > 0 ? styles.montantPenalite : ''}`}>{montant(ligne.penalites_n)}</td>
                      <td className={styles.autresCreances} title={detailsAutres || undefined}>
                        <strong>{montant(ligne.autres_creances)}</strong>
                        {ligne.autres_details.length > 0 && (
                          <small>
                            {ligne.autres_details.length === 1
                              ? ligne.autres_details[0].libelle
                              : `${ligne.autres_details.length} créances · ${ligne.autres_details[0].libelle}`}
                          </small>
                        )}
                      </td>
                      <td className={`${styles.num} ${styles.fort}`}>{montant(ligne.total_creances)}</td>
                      <td className={`${styles.num} ${styles.montantReglement}`}>{montant(ligne.reglements)}</td>
                      <td className={`${styles.num} ${styles.fort}`}>{montant(ligne.reste_du)}</td>
                      <td className={`${styles.num} ${Number(ligne.avance_n_plus_1) > 0 ? styles.montantAvance : ''}`}>{montant(ligne.avance_n_plus_1)}</td>
                      <td><SituationBadge statut={ligne.statut} /></td>
                      <td className={styles.actionsCellule}>
                        <button type="button" className={styles.btnLigne} onClick={() => onVoirNotes(ligne.expert.numero_ordre)}>
                          Voir les notes
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <nav className={styles.pagination} aria-label="Pagination de la situation">
            <button type="button" className={styles.secondaryBtn} disabled={page === 0} onClick={() => setPage(page - 1)}>Précédent</button>
            <span>Page {page + 1} / {pages}</span>
            <button type="button" className={styles.secondaryBtn} disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Suivant</button>
          </nav>
        )}
      </section>
    </div>
  )
}

function SituationKpi({ libelle, valeur, ton }: { libelle: string; valeur: string; ton?: 'ok' | 'warn' | 'err' | 'info' }) {
  const classeTon = ton === 'ok' ? styles.chipOk : ton === 'warn' ? styles.chipWarn : ton === 'err' ? styles.chipErr : ton === 'info' ? styles.chipInfo : ''
  return (
    <div className={`${styles.summaryChip} ${classeTon}`}>
      <span>{libelle}</span>
      <strong>{valeur}</strong>
    </div>
  )
}

function SituationBadge({ statut }: { statut: 'en_retard' | 'partiel' | 'en_regle' | 'en_avance' }) {
  const configuration = {
    en_retard: { libelle: 'En retard', classe: styles.badgeErr },
    partiel: { libelle: 'Partiel', classe: styles.badgeWarn },
    en_regle: { libelle: 'En règle', classe: styles.badgeOk },
    en_avance: { libelle: 'En avance N+1', classe: styles.badgeInfo },
  }[statut]
  return <span className={`${styles.badge} ${configuration.classe}`}>{configuration.libelle}</span>
}

function ListeNotes({
  filtreInitial,
  importFiltre,
  onRetirerImport,
  onVoirImport,
}: {
  filtreInitial: FiltreListe
  importFiltre: { id: string; fichier: string } | null
  onRetirerImport: () => void
  onVoirImport: (imp: { id: string; fichier: string }) => void
}) {
  const { hasPermission } = usePermissions()
  const { notifyError, notifySuccess } = useToast()
  const confirmWithInput = useConfirmWithInput()
  const peutAnnuler = hasPermission('cancel_encaissement')
  const [ficheOuverte, setFicheOuverte] = useState<string | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [impression, setImpression] = useState(false)
  const peutEncaisser = hasPermission('encaissements')
  const [recherche, setRecherche] = useState(filtreInitial.q ?? '')
  const rechercheStable = useDebouncedValue(recherche)
  const [statut, setStatut] = useState<StatutNotes>(filtreInitial.statut ?? 'impayees')
  const [typeClient, setTypeClient] = useState(filtreInitial.type_client ?? '')
  const [exercice, setExercice] = useState('')
  const [page, setPage] = useState(0)
  const [donnees, setDonnees] = useState<ListeNotesDebit | null>(null)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [noteEnPaiement, setNoteEnPaiement] = useState<Encaissement | null>(null)

  useEffect(() => setPage(0), [rechercheStable, statut, typeClient, exercice, importFiltre?.id])
  useEffect(() => setSelection(new Set()), [rechercheStable, statut, typeClient, exercice, importFiltre?.id, page])

  const basculer = (id: string) =>
    setSelection((avant) => {
      const suivante = new Set(avant)
      if (suivante.has(id)) suivante.delete(id)
      else suivante.add(id)
      return suivante
    })

  const imprimerSelection = async () => {
    setImpression(true)
    try {
      await imprimerNotes({ ids: [...selection] })
    } catch (err) {
      notifyError('Impression', err instanceof ApiError ? err.message : "Impossible d'imprimer ces notes.")
    } finally {
      setImpression(false)
    }
  }

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      setDonnees(
        await listerNotesDebit({
          q: rechercheStable.trim(),
          statut,
          type_client: typeClient,
          exercice: exercice ? Number(exercice) : undefined,
          import_id: importFiltre?.id,
          limit: PAR_PAGE,
          offset: page * PAR_PAGE,
        }),
      )
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Impossible de charger les notes de débit.')
    } finally {
      setChargement(false)
    }
  }, [rechercheStable, statut, typeClient, exercice, importFiltre?.id, page])

  useEffect(() => {
    void charger()
  }, [charger])

  const numeroNote = (note: NoteDebitExpert) => note.numero_note_externe || note.numero_recu || '—'

  /**
   * Annuler une note passe par le menu « … » : un réimport ne retire jamais
   * une note absente du fichier. Ses versements sont annulés avec elle — et
   * sortent de la caisse, sauf une avance reportée, qui retourne à sa note.
   */
  const annulerNote = async (note: NoteDebitExpert) => {
    const paye = Number(note.montant_paye) > 0
    const reponse = await confirmWithInput({
      title: `Annuler la note ${numeroNote(note)} ?`,
      description: paye
        ? `La note ne réclamera plus rien. Ses versements (${montant(note.montant_paye)}) sont annulés avec elle et retirés de la caisse ou du compte où ils sont entrés.`
        : 'La note ne réclamera plus rien. Elle reste visible dans la liste, marquée annulée.',
      confirmText: 'Annuler la note',
      variant: 'danger',
      inputLabel: 'Motif d’annulation (obligatoire)',
      inputPlaceholder: 'Ex. : note émise deux fois',
      inputRequired: true,
      inputMultiline: true,
      inputRows: 3,
    })
    if (!reponse.confirmed || !reponse.value?.trim()) return
    try {
      await apiRequest('POST', `/encaissements/${note.id}/cancel-operation`, { motif_annulation: reponse.value.trim() })
      notifySuccess('Note annulée', `La note ${numeroNote(note)} a été annulée.`)
      void charger()
    } catch (err) {
      notifyError('Annulation impossible', err instanceof ApiError ? err.message : "La note n'a pas pu être annulée.")
    }
  }

  const actionsNote = (note: NoteDebitExpert): ActionLigne[] => {
    const annulee = note.statut_operation === 'ANNULEE'
    const items: ActionLigne[] = []
    if (peutEncaisser && !annulee && Number(note.reste_du) > 0) {
      items.push({ cle: 'encaisser', libelle: 'Encaisser', icone: <Banknote size={15} aria-hidden />, onSelect: () => void ouvrirReglement(note) })
    }
    items.push(
      { cle: 'fiche', libelle: 'Voir la fiche', icone: <FileText size={15} aria-hidden />, onSelect: () => setFicheOuverte(note.id) },
      {
        cle: 'imprimer',
        libelle: 'Imprimer la note',
        icone: <Printer size={15} aria-hidden />,
        onSelect: () =>
          void imprimerNotes({ ids: [note.id] }).catch((err) =>
            notifyError('Impression', err instanceof ApiError ? err.message : "Impossible d'imprimer cette note."),
          ),
      },
    )
    if (peutAnnuler && !annulee) {
      items.push({
        cle: 'annuler',
        libelle: 'Annuler la note',
        icone: <Ban size={15} aria-hidden />,
        destructive: true,
        description: Number(note.montant_paye) > 0 ? 'Ses versements sont annulés avec elle' : undefined,
        onSelect: () => void annulerNote(note),
      })
    }
    return items
  }

  const ouvrirReglement = async (note: NoteDebitExpert) => {
    try {
      // La note complète : le règlement a besoin de l'historique et de l'expert,
      // qu'une ligne de liste ne porte pas.
      setNoteEnPaiement(
        await apiRequest<Encaissement>('GET', `/encaissements/${note.id}`, {
          params: { include: 'expert_comptable' },
        }),
      )
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "Impossible d'ouvrir cette note de débit.")
    }
  }

  const { user } = useAuth()
  const [export_, setExport] = useState<'pdf' | 'excel' | null>(null)

  /** Toute la sélection filtrée, pas la seule page affichée. */
  const exporter = async (formatExport: 'pdf' | 'excel') => {
    setExport(formatExport)
    try {
      const { items, totaux } = await listerToutesNotesDebit({
        q: rechercheStable.trim(),
        statut,
        type_client: typeClient,
        exercice: exercice ? Number(exercice) : undefined,
        import_id: importFiltre?.id,
      })
      const filtres = [
        { label: 'Statut', value: { impayees: 'Non soldées', soldees: 'Soldées', toutes: 'Toutes' }[statut] },
        { label: 'Membres', value: typeClient === 'sec' ? 'SEC' : typeClient ? 'Experts-comptables' : 'EC et SEC' },
        rechercheStable.trim() && { label: 'Recherche', value: rechercheStable.trim() },
        exercice && { label: 'Exercice', value: exercice },
        importFiltre && { label: 'Import', value: importFiltre.fichier },
      ].filter((f): f is { label: string; value: string } => Boolean(f))
      const mod = await import('../utils/exportNotesDebit')
      const params = {
        notes: items,
        totaux,
        filtres,
        organisation: user?.organisation_name || user?.organisation_slug || 'ONEC',
      }
      await (formatExport === 'pdf' ? mod.exporterListeNotesPDF(params) : mod.exporterListeNotesExcel(params))
    } catch (err) {
      notifyError('Export', err instanceof ApiError ? err.message : "Impossible d'exporter ces notes de débit.")
    } finally {
      setExport(null)
    }
  }

  const total = donnees?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAR_PAGE))
  const idsPage = donnees?.items.map((n) => n.id) ?? []
  const toutCoche = idsPage.length > 0 && idsPage.every((id) => selection.has(id))

  return (
    <>
      <section className={styles.filtres}>
        <input
          type="search"
          className={styles.recherche}
          placeholder="Rechercher : n° d'ordre, nom, n° de note…"
          value={recherche}
          onChange={(e) => setRecherche(e.target.value)}
          aria-label="Rechercher une note de débit"
        />
        <select value={statut} onChange={(e) => setStatut(e.target.value as StatutNotes)} aria-label="Statut">
          <option value="impayees">Non soldées</option>
          <option value="soldees">Soldées</option>
          <option value="toutes">Toutes</option>
        </select>
        <select value={typeClient} onChange={(e) => setTypeClient(e.target.value)} aria-label="Type de membre">
          <option value="">EC et SEC</option>
          <option value="expert_comptable">Experts-comptables</option>
          <option value="sec">SEC</option>
        </select>
        <input
          type="number"
          min={1900}
          max={2100}
          className={styles.filtreAnnee}
          placeholder="Exercice"
          value={exercice}
          onChange={(e) => setExercice(e.target.value)}
          aria-label="Exercice de la note"
        />
        {importFiltre && (
          <span className={styles.puceFiltre}>
            Import : {importFiltre.fichier}
            <button type="button" onClick={onRetirerImport} aria-label="Retirer le filtre d'import">
              <X size={14} aria-hidden />
            </button>
          </span>
        )}
        <div className={styles.exports}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('pdf')}
            disabled={export_ !== null || total === 0}
            title="Exporter toutes les notes de la sélection en PDF"
          >
            <FileText size={16} aria-hidden /> {export_ === 'pdf' ? 'Export…' : 'PDF'}
          </button>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('excel')}
            disabled={export_ !== null || total === 0}
            title="Exporter toutes les notes de la sélection en Excel"
          >
            <FileSpreadsheet size={16} aria-hidden /> {export_ === 'excel' ? 'Export…' : 'Excel'}
          </button>
        </div>
      </section>

      <section className={styles.summaryStrip} aria-label="Totaux de la sélection">
        <div className={styles.summaryChip}>
          <span>Notes</span>
          <strong>{total}</strong>
        </div>
        <div className={styles.summaryChip}>
          <span>Émis</span>
          <strong>{montant(donnees?.totaux.montant_total ?? 0)}</strong>
        </div>
        <div className={`${styles.summaryChip} ${styles.chipOk}`}>
          <span>Encaissé</span>
          <strong>{montant(donnees?.totaux.montant_paye ?? 0)}</strong>
        </div>
        <div className={`${styles.summaryChip} ${styles.chipErr}`}>
          <span>Reste à recouvrer</span>
          <strong>{montant(donnees?.totaux.reste_du ?? 0)}</strong>
        </div>
      </section>

      {erreur && (
        <p className={styles.erreurBloc} role="alert">
          {erreur}
        </p>
      )}

      {selection.size > 0 && (
        <div className={styles.barreSelection} role="region" aria-label="Actions sur la sélection">
          <strong>
            {selection.size} note{selection.size > 1 ? 's' : ''} sélectionnée{selection.size > 1 ? 's' : ''}
          </strong>
          <button type="button" className={styles.secondaryBtn} onClick={() => void imprimerSelection()} disabled={impression}>
            <Printer size={16} aria-hidden /> {impression ? 'Préparation…' : 'Imprimer les notes'}
          </button>
          <button type="button" className={styles.lienBtn} onClick={() => setSelection(new Set())}>
            Désélectionner
          </button>
        </div>
      )}

      <section className={styles.card}>
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.colCase}>
                  <input
                    type="checkbox"
                    checked={toutCoche}
                    onChange={() =>
                      setSelection((avant) => {
                        const suivante = new Set(avant)
                        idsPage.forEach((id) => (toutCoche ? suivante.delete(id) : suivante.add(id)))
                        return suivante
                      })
                    }
                    aria-label="Sélectionner toute la page"
                  />
                </th>
                <th>N° note</th>
                <th>Date</th>
                <th>Exercice</th>
                <th>Membre</th>
                <th>Libellés</th>
                <th className={styles.num}>Montant</th>
                <th className={styles.num}>Payé</th>
                <th className={styles.num}>Reste</th>
                <th>Statut</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {chargement && !donnees ? (
                <tr>
                  <td colSpan={11} className={styles.vide}>
                    Chargement…
                  </td>
                </tr>
              ) : donnees && donnees.items.length === 0 ? (
                <tr>
                  <td colSpan={11} className={styles.vide}>
                    Aucune note de débit pour ces critères.
                  </td>
                </tr>
              ) : (
                donnees?.items.map((note) => (
                  <tr
                    key={note.id}
                    className={`${styles.ligneCliquable} ${note.statut_operation === 'ANNULEE' ? styles.ligneAnnulee : ''}`}
                    onClick={() => setFicheOuverte(note.id)}
                  >
                    <td className={styles.colCase} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selection.has(note.id)}
                        onChange={() => basculer(note.id)}
                        aria-label={`Sélectionner la note ${note.numero_note_externe || note.numero_recu || ''}`}
                      />
                    </td>
                    <td className={styles.numero}>
                      <button
                        type="button"
                        className={styles.lienBtn}
                        onClick={(e) => {
                          e.stopPropagation()
                          setFicheOuverte(note.id)
                        }}
                      >
                        {note.numero_note_externe || note.numero_recu || '—'}
                      </button>
                      {note.numero_note_externe && <small className={styles.muted}>{note.numero_recu || '—'}</small>}
                    </td>
                    <td>{note.date_encaissement ? format(new Date(note.date_encaissement), 'dd/MM/yyyy') : '—'}</td>
                    <td>{note.exercice ?? '—'}</td>
                    <td>
                      <div className={styles.membre}>
                        <strong>{note.expert.nom}</strong>
                        <small>
                          {note.expert.numero_ordre}
                          {note.type_client === 'sec' && <span className={`${styles.tag} ${styles.tagSec}`}>SEC</span>}
                        </small>
                      </div>
                    </td>
                    <td className={styles.libelles} title={note.libelle}>
                      {note.libelle}
                    </td>
                    <td className={styles.num}>{montant(note.montant_total)}</td>
                    <td className={styles.num}>{montant(note.montant_paye)}</td>
                    <td className={`${styles.num} ${styles.fort}`}>{montant(note.reste_du)}</td>
                    <td>
                      <StatutNote note={note} />
                    </td>
                    <td className={styles.actionsCellule} onClick={(e) => e.stopPropagation()}>
                      <div className={styles.actionsLigneNote}>
                        {peutEncaisser && Number(note.reste_du) > 0 && note.statut_operation !== 'ANNULEE' && (
                          <button type="button" className={styles.btnLigne} onClick={() => void ouvrirReglement(note)}>
                            Encaisser
                          </button>
                        )}
                        <RowActionsMenu items={actionsNote(note)} libelle={`Actions de la note ${numeroNote(note)}`} />
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <nav className={styles.pagination} aria-label="Pagination">
            <button type="button" className={styles.secondaryBtn} disabled={page === 0} onClick={() => setPage(page - 1)}>
              Précédent
            </button>
            <span>
              Page {page + 1} / {pages}
            </span>
            <button
              type="button"
              className={styles.secondaryBtn}
              disabled={page + 1 >= pages}
              onClick={() => setPage(page + 1)}
            >
              Suivant
            </button>
          </nav>
        )}
      </section>

      {noteEnPaiement && (
        <PaymentManager
          encaissement={noteEnPaiement}
          onClose={() => setNoteEnPaiement(null)}
          onUpdate={() => void charger()}
        />
      )}

      {ficheOuverte && (
        <NoteDebitFiche
          noteId={ficheOuverte}
          onClose={() => setFicheOuverte(null)}
          onChange={() => void charger()}
          onVoirImport={(imp) => {
            setFicheOuverte(null)
            onVoirImport(imp)
          }}
        />
      )}
    </>
  )
}

function StatutNote({ note }: { note: NoteDebitExpert }) {
  if (note.statut_operation === 'ANNULEE') return <span className={`${styles.badge} ${styles.badgeMuted}`}>Annulée</span>
  const classe =
    note.statut_paiement === 'non_paye'
      ? styles.badgeInfo
      : note.statut_paiement === 'partiel'
        ? styles.badgeWarn
        : styles.badgeOk
  return <span className={`${styles.badge} ${classe}`}>{LIBELLE_STATUT_NOTE[note.statut_paiement] ?? note.statut_paiement}</span>
}

function HistoriqueImports({ onVoirNotes }: { onVoirNotes: (imp: ImportNotesDebit) => void }) {
  const { notifyError } = useToast()
  const [imports, setImports] = useState<ImportNotesDebit[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [impression, setImpression] = useState<string | null>(null)

  const imprimer = async (imp: ImportNotesDebit) => {
    setImpression(imp.id)
    try {
      await imprimerNotes({ import_id: imp.id })
    } catch (err) {
      notifyError('Impression', err instanceof ApiError ? err.message : "Impossible d'imprimer les notes de cet import.")
    } finally {
      setImpression(null)
    }
  }

  useEffect(() => {
    listerImportsNotes()
      .then(setImports)
      .catch((err) => setErreur(err instanceof ApiError ? err.message : 'Impossible de charger les imports.'))
  }, [])

  return (
    <section className={styles.card}>
      {erreur && (
        <p className={styles.erreurBloc} role="alert">
          {erreur}
        </p>
      )}
      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Fichier</th>
              <th>Libellés</th>
              <th className={styles.num}>Notes</th>
              <th className={styles.num}>Écartées</th>
              <th className={styles.num}>Total</th>
              <th className={styles.num}>dont arriérés</th>
              <th>Par</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {imports === null ? (
              <tr>
                <td colSpan={9} className={styles.vide}>
                  Chargement…
                </td>
              </tr>
            ) : imports.length === 0 ? (
              <tr>
                <td colSpan={9} className={styles.vide}>
                  Aucun import pour l'instant.
                </td>
              </tr>
            ) : (
              imports.map((imp) => (
                <tr key={imp.id}>
                  <td>{imp.created_at ? format(new Date(imp.created_at), 'dd/MM/yyyy HH:mm') : '—'}</td>
                  <td className={styles.fort}>{imp.fichier}</td>
                  <td className={styles.libelles}>{imp.colonnes.map((c) => c.libelle).join(', ')}</td>
                  <td className={styles.num}>
                    {imp.nb_notes}
                    {(imp.nb_notes_actualisees ?? 0) > 0 && (
                      <small className={styles.muted}> + {imp.nb_notes_actualisees} actualisée{(imp.nb_notes_actualisees ?? 0) > 1 ? 's' : ''}</small>
                    )}
                  </td>
                  <td className={styles.num}>{imp.nb_lignes_ecartees}</td>
                  <td className={styles.num}>{montant(imp.montant_total)}</td>
                  <td className={styles.num}>{montant(imp.montant_arrieres)}</td>
                  <td>{imp.auteur ?? '—'}</td>
                  <td className={styles.actionsCellule}>
                    <button type="button" className={styles.btnLigne} onClick={() => onVoirNotes(imp)}>
                      Voir les notes
                    </button>{' '}
                    <button
                      type="button"
                      className={styles.btnLigne}
                      onClick={() => void imprimer(imp)}
                      disabled={impression === imp.id}
                      title="Imprimer toutes les notes de cet import"
                    >
                      <Printer size={14} aria-hidden /> {impression === imp.id ? '…' : 'Imprimer'}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
