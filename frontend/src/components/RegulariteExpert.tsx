import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, MinusCircle } from 'lucide-react'
import { regulariteMembres, type RegulariteMembres } from '../api/notesDebit'
import styles from '../pages/NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

interface Props {
  expertId: string
  numeroOrdre: string
}

/**
 * Le membre est-il en règle pour le Tableau de l'an prochain ? (art. 12 du RI :
 * cotisation et pénalités soldées avant le 31 décembre.)
 *
 * Trois états, chacun avec son icône et son texte — jamais la couleur seule :
 * en règle, non en règle (avec ce qui reste dû), ou rien d'émis cette année.
 */
export default function RegulariteExpert({ expertId, numeroOrdre }: Props) {
  const [donnees, setDonnees] = useState<RegulariteMembres | null>(null)
  const [indisponible, setIndisponible] = useState(false)

  useEffect(() => {
    let actif = true
    setDonnees(null)
    setIndisponible(false)
    regulariteMembres([expertId])
      .then((d) => actif && setDonnees(d))
      .catch(() => actif && setIndisponible(true))
    return () => {
      actif = false
    }
  }, [expertId])

  if (indisponible) return <p className={styles.muted}>Situation des notes de débit indisponible.</p>
  if (!donnees) return <p className={styles.muted}>Chargement…</p>

  const membre = donnees.membres[expertId]
  const lien = `/experts-comptables/notes-debit?q=${encodeURIComponent(numeroOrdre)}`

  return (
    <div className={styles.regularite}>
      {membre?.statut === 'non_en_regle' ? (
        <span className={`${styles.badge} ${styles.badgeErr}`}>
          <AlertTriangle size={12} aria-hidden /> Non en règle — Tableau {donnees.tableau}
        </span>
      ) : membre?.statut === 'en_regle' ? (
        <span className={`${styles.badge} ${styles.badgeOk}`}>
          <CheckCircle2 size={12} aria-hidden /> En règle — Tableau {donnees.tableau}
        </span>
      ) : (
        <span className={`${styles.badge} ${styles.badgeMuted}`}>
          <MinusCircle size={12} aria-hidden /> Aucune note émise en {donnees.annee}
        </span>
      )}
      {membre?.statut === 'non_en_regle' && (
        <span>
          <strong>{montant(membre.reste_du)}</strong> dû sur {membre.nb_notes_dues} note
          {membre.nb_notes_dues > 1 ? 's' : ''}
        </span>
      )}
      <Link to={lien} className={styles.lienDiscret}>
        Voir ses notes de débit
      </Link>
    </div>
  )
}
