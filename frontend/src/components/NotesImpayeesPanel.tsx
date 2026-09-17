import { useCallback, useEffect, useRef, useState } from 'react'
import { format } from 'date-fns'
import { AlertTriangle, X } from 'lucide-react'
import {
  listerNotesImpayees,
  LIBELLE_TRANCHE,
  type NoteImpayee,
  type NotesImpayees,
} from '../api/creances'
import { apiRequest, ApiError } from '../lib/apiClient'
import type { Encaissement } from '../types'
import PaymentManager from './PaymentManager'
import styles from './NotesImpayeesPanel.module.css'

const montant = (valeur: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(valeur || 0)

export interface CiblePayeur {
  client_id?: string
  expert_comptable_id?: string
  nom?: string
}

interface Props {
  /** Qui doit : identifiant du référentiel si on l'a, nom saisi sinon. */
  cible: CiblePayeur
  /** Son nom, tel qu'il s'affiche dans le formulaire. */
  libelle: string
  onClose: () => void
  /** Ce qu'il doit encore après chaque règlement : la bannière du formulaire suit. */
  onCreanceChange?: (creance: { total_du: number; nb_notes: number }) => void
}

/**
 * Sur quoi ce payeur doit encore, et de quoi le régler sans quitter la saisie.
 *
 * Encaisser le solde d'un débiteur depuis le formulaire crée une SECONDE note :
 * l'argent rentre, mais la première reste ouverte pour toujours et le client
 * garde une dette qu'il a pourtant payée. Le seul geste juste est de compléter
 * la note d'origine — c'est ce que ce panneau rend possible, là où l'erreur se
 * commet.
 *
 * Une seule note impayée : on ouvre le règlement directement. C'est le cas
 * courant, et il ne doit pas coûter un clic de plus qu'il n'en faut.
 */
export default function NotesImpayeesPanel({ cible, libelle, onClose, onCreanceChange }: Props) {
  const [donnees, setDonnees] = useState<NotesImpayees | null>(null)
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [noteEnPaiement, setNoteEnPaiement] = useState<Encaissement | null>(null)
  const [noteEnOuverture, setNoteEnOuverture] = useState<string | null>(null)
  // Ouverture automatique de l'unique note : la refermer referme le panneau,
  // sinon on retomberait sur une liste d'une seule ligne, que personne n'a
  // demandée.
  const ouvertureAutomatique = useRef(false)

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      const res = await listerNotesImpayees({ ...cible, limit: 50 })
      setDonnees(res)
      onCreanceChange?.({ total_du: res.total_du, nb_notes: res.nb_notes })
      return res
    } catch (err) {
      setErreur(
        err instanceof ApiError ? err.message : 'Impossible de charger ses notes impayées.',
      )
      setDonnees(null)
      return null
    } finally {
      setChargement(false)
    }
    // `cible` et `onCreanceChange` sont stables le temps de vie du panneau : il
    // est monté pour un payeur, et démonté quand on en change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const ouvrirReglement = useCallback(async (note: NoteImpayee) => {
    setNoteEnOuverture(note.id)
    try {
      // La note complète plutôt que la ligne de liste : le règlement affiche
      // l'historique, les relances et l'état de l'opération, qu'un résumé de
      // liste ne porte pas.
      setNoteEnPaiement(await apiRequest<Encaissement>('GET', `/encaissements/${note.id}`))
    } catch (err) {
      setErreur(
        err instanceof ApiError ? err.message : "Impossible d'ouvrir cette note de débit.",
      )
    } finally {
      setNoteEnOuverture(null)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      const res = await charger()
      if (res && res.notes.length === 1) {
        ouvertureAutomatique.current = true
        await ouvrirReglement(res.notes[0])
      }
    })()
  }, [charger, ouvrirReglement])

  // Après un règlement, la note rouverte doit dire le nouveau reste : la liste
  // se recharge, et la note ouverte avec elle — sans quoi le panneau annoncerait
  // encore le montant d'avant le paiement qu'on vient d'y saisir.
  const rafraichirApresPaiement = async (noteId: string) => {
    const [, note] = await Promise.all([
      charger(),
      apiRequest<Encaissement>('GET', `/encaissements/${noteId}`).catch(() => null),
    ])
    if (note) setNoteEnPaiement(note)
  }

  const fermerReglement = async () => {
    setNoteEnPaiement(null)
    const res = await charger()
    // Plus rien à devoir, ou on n'était venu que pour cette note : le panneau
    // n'a plus de raison de rester ouvert.
    if (ouvertureAutomatique.current || !res || res.notes.length === 0) onClose()
  }

  return (
    <>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="notes-impayees-titre"
        className={styles.overlay}
        onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
      >
        <div className={styles.panneau}>
          <div className={styles.header}>
            <div>
              <h2 id="notes-impayees-titre" className={styles.title}>
                Ce que {libelle} doit encore
              </h2>
              <p className={styles.mesure}>
                {donnees ? (
                  <>
                    <span className={styles.total}>{montant(donnees.total_du)}</span>
                    {' '}sur {donnees.nb_notes} note{donnees.nb_notes > 1 ? 's' : ''} de débit
                  </>
                ) : (
                  'Notes de débit non soldées, de la plus ancienne à la plus récente.'
                )}
              </p>
              {donnees && !donnees.identite_sure && (
                <p className={styles.reserve}>
                  <AlertTriangle size={12} aria-hidden="true" />
                  Rapproché sur le nom : une autre orthographe porterait d'autres notes.
                </p>
              )}
            </div>
            <button type="button" onClick={onClose} aria-label="Fermer" className={styles.close}>
              <X size={16} aria-hidden="true" />
            </button>
          </div>

          <div className={styles.corps}>
            {erreur && <div className={styles.erreur}>{erreur}</div>}
            {chargement && !donnees && <p className={styles.chargement}>Chargement…</p>}
            {donnees && donnees.notes.length === 0 && !erreur && (
              <p className={styles.vide}>
                Plus rien à devoir : toutes ses notes de débit sont soldées.
              </p>
            )}
            {donnees?.notes.map(note => (
              <div key={note.id} className={styles.ligne}>
                <div className={styles.identite}>
                  <div className={styles.nom}>
                    <span className={styles.numero}>{note.numero_recu || 'Sans numéro'}</span>
                    <span className={styles.nomTexte}>{note.libelle}</span>
                  </div>
                  <div className={styles.meta}>
                    {note.date_encaissement
                      ? `Du ${format(new Date(note.date_encaissement), 'dd/MM/yyyy')}`
                      : 'Sans date'}
                    {' · '}
                    {montant(note.montant_paye)} payé sur {montant(note.montant_total)}
                    {note.relance_count > 0 && (
                      <> · {note.relance_count} relance{note.relance_count > 1 ? 's' : ''}</>
                    )}
                  </div>
                </div>
                <span className={styles.montant}>{montant(note.reste_du)}</span>
                <span className={`${styles.age} ${styles[`age_${note.tranche}`]}`}>
                  {LIBELLE_TRANCHE[note.tranche]}
                </span>
                <button
                  type="button"
                  className={styles.completer}
                  onClick={() => void ouvrirReglement(note)}
                  disabled={noteEnOuverture === note.id}
                >
                  {noteEnOuverture === note.id ? 'Ouverture…' : 'Compléter'}
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {noteEnPaiement && (
        <PaymentManager
          encaissement={noteEnPaiement}
          onClose={() => void fermerReglement()}
          onUpdate={() => void rafraichirApresPaiement(noteEnPaiement.id)}
        />
      )}
    </>
  )
}
