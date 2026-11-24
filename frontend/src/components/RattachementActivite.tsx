import { useState } from 'react'
import { usePilotageExterne } from '../hooks/usePilotageExterne'
import { AlertTriangle, FolderKanban, X } from 'lucide-react'
import { apiRequest, ApiError } from '../lib/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import { listProjetsActivites, type ProjetActivite } from '../api/projetsActivites'
import styles from './ReimputationBudgetaire.module.css'

interface Props {
  requisitionId: string
  projetActuelId: number | null | undefined
  onChange?: (projetId: number | null) => void
  /** Ouverture depuis un menu : compteur incrémenté par le parent ; le bouton propre disparaît. */
  declenchement?: number
  /** Dit au menu si cette correction s'applique à la réquisition. */
  onDisponible?: (disponible: boolean) => void
}

/**
 * Rattacher une réquisition à un projet ou une activité après coup, quel que
 * soit son statut, même payée : on l'avait oublié à la saisie. C'est une
 * imputation analytique — ni le poste, ni les montants ne bougent. Ses sorties
 * de fonds suivent dans le rapport du projet.
 */
export default function RattachementActivite({ requisitionId, projetActuelId, onChange, declenchement, onDisponible }: Props) {
  const { hasPermission } = usePermissions()
  const { showSuccess } = useNotification()
  const [ouvert, setOuvert] = useState(false)
  const [projets, setProjets] = useState<ProjetActivite[]>([])
  const [projetId, setProjetId] = useState('')
  const [motif, setMotif] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const disponible = hasPermission('treso.requisitions.reimputer')
  const ouvrirRef = usePilotageExterne(declenchement, disponible, onDisponible)

  if (!disponible) return null

  const actuel = projetActuelId ? projets.find((p) => p.id === projetActuelId) : undefined
  const libelle = (p: ProjetActivite) => `${p.code} — ${p.libelle}`

  const ouvrir = () => {
    setProjetId(projetActuelId ? String(projetActuelId) : '')
    setMotif('')
    setErreur(null)
    setOuvert(true)
    // Les désactivés aussi : le projet actuel doit rester lisible, même s'il ne se choisit plus.
    listProjetsActivites()
      .then(setProjets)
      .catch(() => setErreur('La liste des projets et activités est indisponible.'))
  }
  ouvrirRef.current = ouvrir

  const inchange = projetId === (projetActuelId ? String(projetActuelId) : '')
  const interdit = enCours || inchange || motif.trim().length < 3

  const valider = async () => {
    if (interdit) return
    setEnCours(true)
    setErreur(null)
    try {
      const nouveau = projetId ? Number(projetId) : null
      await apiRequest('POST', `/requisitions/${requisitionId}/projet-activite`, {
        project_activity_id: nouveau,
        motif: motif.trim(),
      })
      const choisi = projets.find((p) => p.id === nouveau)
      showSuccess(
        nouveau ? 'Réquisition rattachée' : 'Rattachement retiré',
        nouveau && choisi ? `Rattachée à ${libelle(choisi)}.` : "La réquisition n'est plus rattachée à aucun projet ni activité.",
      )
      setOuvert(false)
      onChange?.(nouveau)
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Le rattachement a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <>
      {declenchement === undefined && (
        <button
          type="button"
          className={styles.declencheur}
          onClick={ouvrir}
          title="Rattacher cette réquisition à un projet ou une activité, même payée"
        >
          <FolderKanban size={15} aria-hidden="true" />
          {projetActuelId ? "Changer l'activité" : 'Rattacher à une activité'}
        </button>
      )}

      {ouvert && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="activite-titre"
          className={styles.overlay}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOuvert(false) }}
        >
          <div className={styles.modal}>
            <div className={styles.header}>
              <div>
                <h2 id="activite-titre" className={styles.title}>Projet ou activité</h2>
                <p className={styles.subtitle}>
                  Le rattachement se corrige quel que soit le statut, même après paiement. Ni le poste budgétaire, ni
                  les montants ne bougent ; les sorties de la réquisition suivent dans le rapport du projet.
                </p>
              </div>
              <button type="button" onClick={() => setOuvert(false)} aria-label="Fermer" className={styles.close}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className={styles.body}>
              <p className={styles.aide}>
                Rattachement actuel : <strong>{projetActuelId ? (actuel ? libelle(actuel) : `#${projetActuelId}`) : 'aucun'}</strong>
              </p>
              <div className={styles.champ}>
                <label className={styles.label} htmlFor="activite-choix">Nouveau projet ou activité</label>
                <select
                  id="activite-choix"
                  className={styles.select}
                  value={projetId}
                  onChange={(e) => { setProjetId(e.target.value); setErreur(null) }}
                >
                  <option value="">Aucun (retirer le rattachement)</option>
                  {actuel && !actuel.is_active && (
                    <option value={String(actuel.id)}>{libelle(actuel)} (désactivé)</option>
                  )}
                  {projets.filter((p) => p.is_active).map((p) => (
                    <option key={p.id} value={String(p.id)}>{libelle(p)}</option>
                  ))}
                </select>
              </div>

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="activite-motif">Motif</label>
                <textarea
                  id="activite-motif"
                  className={styles.textarea}
                  value={motif}
                  onChange={(e) => setMotif(e.target.value)}
                  rows={3}
                  maxLength={500}
                  placeholder="Activité oubliée à la saisie…"
                />
                <p className={styles.aide}>Ce motif est consigné au journal avec l'ancien et le nouveau rattachement.</p>
              </div>

              {inchange && <p className={styles.aide}>C'est déjà le rattachement de cette réquisition.</p>}

              {erreur && (
                <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
                  <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
                  <span>{erreur}</span>
                </div>
              )}
            </div>

            <div className={styles.footer}>
              <button type="button" onClick={() => setOuvert(false)} className={`${styles.bouton} ${styles.secondaire}`}>
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void valider()}
                disabled={interdit}
                className={`${styles.bouton} ${styles.principal}`}
              >
                {enCours ? 'Enregistrement…' : 'Enregistrer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
