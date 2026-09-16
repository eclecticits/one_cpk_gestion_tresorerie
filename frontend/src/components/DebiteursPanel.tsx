import { useCallback, useEffect, useState } from 'react'
import { format } from 'date-fns'
import { AlertTriangle, HandCoins, X } from 'lucide-react'
import {
  listerDebiteurs,
  LIBELLE_TRANCHE,
  type Debiteur,
  type ListeDebiteurs,
} from '../api/creances'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { ApiError } from '../lib/apiClient'
import styles from './DebiteursPanel.module.css'

const montant = (valeur: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(valeur || 0)

const SEUILS = [
  { valeur: 0, libelle: 'Toutes les créances' },
  { valeur: 30, libelle: 'Plus de 30 jours' },
  { valeur: 60, libelle: 'Plus de 60 jours' },
  { valeur: 90, libelle: 'Plus de 90 jours' },
]

/**
 * Qui nous doit de l'argent, et depuis combien de temps.
 *
 * La dette existe note de débit par note de débit ; personne n'en fait jamais
 * la somme par personne. Un client avec trois règlements partiels apparaît
 * trois fois dans la liste des encaissements, et son ardoise n'est affichée
 * nulle part.
 *
 * L'ordre suit l'ancienneté, pas le montant : une liste de débiteurs sert à
 * savoir qui relancer, et c'est le temps écoulé qui le décide.
 */
export default function DebiteursPanel() {
  const [ouvert, setOuvert] = useState(false)
  const [recherche, setRecherche] = useState('')
  const [anciennete, setAnciennete] = useState(0)
  const [donnees, setDonnees] = useState<ListeDebiteurs | null>(null)
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const rechercheDifferee = useDebouncedValue(recherche)

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      setDonnees(await listerDebiteurs({
        q: rechercheDifferee.trim() || undefined,
        anciennete_min: anciennete || undefined,
        limit: 200,
      }))
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Impossible de charger les créances.')
      setDonnees(null)
    } finally {
      setChargement(false)
    }
  }, [rechercheDifferee, anciennete])

  useEffect(() => {
    if (ouvert) void charger()
  }, [ouvert, charger])

  const fermer = () => {
    setOuvert(false)
    setRecherche('')
    setAnciennete(0)
    setDonnees(null)
    setErreur(null)
  }

  const ligne = (d: Debiteur) => (
    <div key={`${d.famille}:${d.cle}`} className={styles.ligne}>
      <div className={styles.identite}>
        <div className={styles.nom}>
          <span className={styles.nomTexte}>{d.libelle}</span>
          {d.detail && <span className={styles.numero}>{d.detail}</span>}
        </div>
        <div className={styles.meta}>
          {d.nb_notes} note{d.nb_notes > 1 ? 's' : ''}
          {d.plus_ancienne_le && ` · depuis le ${format(new Date(d.plus_ancienne_le), 'dd/MM/yyyy')}`}
          {d.relances > 0 && (
            <>
              {' · '}{d.relances} relance{d.relances > 1 ? 's' : ''}
              {d.derniere_relance_le
                ? `, la dernière le ${format(new Date(d.derniere_relance_le), 'dd/MM')}`
                : ''}
            </>
          )}
          {!d.identite_sure && (
            <>
              {' · '}
              <span className={styles.reserve}>
                <AlertTriangle size={11} aria-hidden="true" />
                rapproché sur le nom — montant minimal
              </span>
            </>
          )}
        </div>
      </div>
      <span className={styles.montant}>{montant(d.reste_du)}</span>
      <span className={`${styles.age} ${styles[`age_${d.tranche}`]}`}>
        {LIBELLE_TRANCHE[d.tranche]}
      </span>
    </div>
  )

  return (
    <>
      <button
        type="button"
        className={styles.declencheur}
        onClick={() => setOuvert(true)}
        title="Voir qui doit encore de l'argent"
      >
        <HandCoins size={15} aria-hidden="true" />
        Créances
      </button>

      {ouvert && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="debiteurs-titre"
          className={styles.overlay}
          onMouseDown={e => { if (e.target === e.currentTarget) fermer() }}
        >
          <div className={styles.panneau}>
            <div className={styles.header}>
              <div>
                <h2 id="debiteurs-titre" className={styles.title}>Qui nous doit</h2>
                <p className={styles.mesure}>
                  {donnees ? (
                    <>
                      <span className={styles.total}>{montant(donnees.total_du)}</span>
                      {' '}à recouvrer · {donnees.nb_debiteurs} débiteur
                      {donnees.nb_debiteurs > 1 ? 's' : ''}
                    </>
                  ) : (
                    'Notes de débit non soldées, regroupées par payeur.'
                  )}
                </p>
              </div>
              <button type="button" onClick={fermer} aria-label="Fermer" className={styles.close}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className={styles.filtres}>
              <input
                className={styles.recherche}
                value={recherche}
                onChange={e => setRecherche(e.target.value)}
                placeholder="Nom, dénomination ou numéro d'ordre…"
                aria-label="Rechercher un débiteur"
              />
              <select
                className={styles.select}
                value={anciennete}
                onChange={e => setAnciennete(Number(e.target.value))}
                aria-label="Ancienneté minimale"
              >
                {SEUILS.map(s => (
                  <option key={s.valeur} value={s.valeur}>{s.libelle}</option>
                ))}
              </select>
            </div>

            <div className={styles.corps}>
              {erreur && <div className={styles.erreur}>{erreur}</div>}
              {chargement && !donnees && <p className={styles.chargement}>Chargement…</p>}
              {donnees && donnees.debiteurs.length === 0 && !erreur && (
                <p className={styles.vide}>
                  {recherche.trim() || anciennete
                    ? 'Aucun débiteur ne répond à ces critères.'
                    : 'Personne ne doit rien : toutes les notes de débit sont soldées.'}
                </p>
              )}
              {donnees?.debiteurs.map(ligne)}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
