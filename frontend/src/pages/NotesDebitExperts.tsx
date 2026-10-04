import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { format } from 'date-fns'
import { History, LayoutDashboard, List, Printer, Settings2, Upload, X } from 'lucide-react'
import {
  documentsNotesDebit,
  listerImportsNotes,
  listerNotesDebit,
  PERMISSION_IMPORT_NOTES_DEBIT,
  type ImportNotesDebit,
  type ListeNotesDebit,
  type NoteDebitExpert,
  type StatutNotes,
} from '../api/notesDebit'
import NoteDebitFiche from '../components/NoteDebitFiche'
import NotesDebitImport from '../components/NotesDebitImport'
import NotesDebitTableauDeBord, { type FiltreListe } from '../components/NotesDebitTableauDeBord'
import PaymentManager from '../components/PaymentManager'
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

type Onglet = 'bord' | 'liste' | 'imports'

const LIBELLE_STATUT: Record<string, string> = {
  non_paye: 'Émise',
  partiel: 'Partiellement payée',
  complet: 'Payée',
  avance: 'Payée (avance)',
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
  const { notifyError } = useToast()
  const [ficheOuverte, setFicheOuverte] = useState<string | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [impression, setImpression] = useState(false)
  const peutEncaisser = hasPermission('encaissements')
  const [recherche, setRecherche] = useState(filtreInitial.q ?? '')
  const rechercheStable = useDebouncedValue(recherche)
  const [statut, setStatut] = useState<StatutNotes>(filtreInitial.statut ?? 'impayees')
  const [typeClient, setTypeClient] = useState(filtreInitial.type_client ?? '')
  const [page, setPage] = useState(0)
  const [donnees, setDonnees] = useState<ListeNotesDebit | null>(null)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [noteEnPaiement, setNoteEnPaiement] = useState<Encaissement | null>(null)

  useEffect(() => setPage(0), [rechercheStable, statut, typeClient, importFiltre?.id])
  useEffect(() => setSelection(new Set()), [rechercheStable, statut, typeClient, importFiltre?.id, page])

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
  }, [rechercheStable, statut, typeClient, importFiltre?.id, page])

  useEffect(() => {
    void charger()
  }, [charger])

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
        {importFiltre && (
          <span className={styles.puceFiltre}>
            Import : {importFiltre.fichier}
            <button type="button" onClick={onRetirerImport} aria-label="Retirer le filtre d'import">
              <X size={14} aria-hidden />
            </button>
          </span>
        )}
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
                <th>Membre</th>
                <th>Libellés</th>
                <th className={styles.num}>Montant</th>
                <th className={styles.num}>Payé</th>
                <th className={styles.num}>Reste</th>
                <th>Statut</th>
                {peutEncaisser && <th aria-label="Actions" />}
              </tr>
            </thead>
            <tbody>
              {chargement && !donnees ? (
                <tr>
                  <td colSpan={10} className={styles.vide}>
                    Chargement…
                  </td>
                </tr>
              ) : donnees && donnees.items.length === 0 ? (
                <tr>
                  <td colSpan={10} className={styles.vide}>
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
                        aria-label={`Sélectionner la note ${note.numero_recu ?? ''}`}
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
                        {note.numero_recu ?? '—'}
                      </button>
                    </td>
                    <td>{note.date_encaissement ? format(new Date(note.date_encaissement), 'dd/MM/yyyy') : '—'}</td>
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
                    {peutEncaisser && (
                      <td className={styles.actionsCellule} onClick={(e) => e.stopPropagation()}>
                        {Number(note.reste_du) > 0 && note.statut_operation !== 'ANNULEE' && (
                          <button type="button" className={styles.btnLigne} onClick={() => void ouvrirReglement(note)}>
                            Encaisser
                          </button>
                        )}
                      </td>
                    )}
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
  return <span className={`${styles.badge} ${classe}`}>{LIBELLE_STATUT[note.statut_paiement] ?? note.statut_paiement}</span>
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
                  <td className={styles.num}>{imp.nb_notes}</td>
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
