import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, X } from 'lucide-react'
import { validerComptaEcrituresEnLot } from '../../api/comptabilite'
import { useToast } from '../../hooks/useToast'
import type {
  ComptaExercice,
  ComptaJournal,
  ComptaValidationLotResult,
} from '../../types/comptabilite'
import styles from './ValidationLotModal.module.css'

interface Props {
  exerciceId?: number
  journalId?: number
  exercices: ComptaExercice[]
  journaux: ComptaJournal[]
  onClose: () => void
  onValide: (result: ComptaValidationLotResult) => void
}

/**
 * Validation en lot des écritures au brouillon.
 *
 * La simulation est lancée d'office à l'ouverture et le bouton de validation
 * réelle n'apparaît qu'ensuite : valider est irréversible (l'écriture devient
 * immuable) et porte ici sur des centaines de pièces. L'utilisateur doit voir
 * ce qui passerait et ce qui bloquerait avant de figer quoi que ce soit.
 */
export default function ValidationLotModal({
  exerciceId,
  journalId,
  exercices,
  journaux,
  onClose,
  onValide,
}: Props) {
  const { notifyError } = useToast()
  const [simulation, setSimulation] = useState<ComptaValidationLotResult | null>(null)
  const [enCours, setEnCours] = useState(true)
  const [validation, setValidation] = useState(false)

  const criteres = {
    exercice_id: exerciceId,
    journal_id: journalId,
    limite: 2000,
  }

  useEffect(() => {
    let annule = false
    setEnCours(true)
    validerComptaEcrituresEnLot({ ...criteres, simulation: true })
      .then(result => {
        if (!annule) setSimulation(result)
      })
      .catch(err => {
        if (!annule) notifyError('Simulation impossible', err?.message || 'Erreur inattendue.')
      })
      .finally(() => {
        if (!annule) setEnCours(false)
      })
    return () => {
      annule = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exerciceId, journalId])

  const lancerValidation = async () => {
    setValidation(true)
    try {
      const result = await validerComptaEcrituresEnLot({ ...criteres, simulation: false })
      onValide(result)
    } catch (err: any) {
      notifyError('Validation interrompue', err?.message || 'Erreur inattendue.')
    } finally {
      setValidation(false)
    }
  }

  const perimetre = [
    exerciceId ? exercices.find(e => e.id === exerciceId)?.code : null,
    journalId ? journaux.find(j => j.id === journalId)?.code : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="vl-titre">
      <div className={styles.modal}>
        <header className={styles.entete}>
          <h2 id="vl-titre">Valider les brouillons</h2>
          <button type="button" className={styles.fermer} onClick={onClose} aria-label="Fermer">
            <X size={18} />
          </button>
        </header>

        <div className={styles.corps}>
          <p className={styles.perimetre}>
            Périmètre : <strong>{perimetre || 'tous les brouillons de l’organisation'}</strong>.
            Les numéros de pièce seront attribués dans l’ordre chronologique.
          </p>

          {enCours && <div className={styles.attente}>Simulation en cours…</div>}

          {!enCours && simulation && (
            <>
              {simulation.total_examinees === 0 ? (
                <div className={styles.attente}>Aucune écriture au brouillon sur ce périmètre.</div>
              ) : (
                <>
                  <div className={styles.resume}>
                    <div className={styles.carte}>
                      <span className={styles.chiffre}>{simulation.total_examinees}</span>
                      <span className={styles.libelleCarte}>examinées</span>
                    </div>
                    <div className={`${styles.carte} ${styles.carteOk}`}>
                      <span className={styles.chiffre}>{simulation.validees}</span>
                      <span className={styles.libelleCarte}>seront validées</span>
                    </div>
                    <div
                      className={`${styles.carte} ${
                        simulation.echecs.length > 0 ? styles.carteAlerte : ''
                      }`}
                    >
                      <span className={styles.chiffre}>{simulation.echecs.length}</span>
                      <span className={styles.libelleCarte}>seront refusées</span>
                    </div>
                  </div>

                  {simulation.reste_a_traiter && (
                    <div className={styles.avertissement}>
                      <AlertTriangle size={16} />
                      <span>
                        D’autres brouillons dépassent la limite de ce lot. Relancez l’opération
                        après celle-ci pour les traiter.
                      </span>
                    </div>
                  )}

                  {simulation.echecs.length > 0 ? (
                    <div className={styles.echecs}>
                      <h3>Écritures qui resteront au brouillon</h3>
                      <p className={styles.echecsAide}>
                        Elles ne bloquent pas les autres : le lot les ignore et poursuit. Corrigez-les
                        puis relancez.
                      </p>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Libellé</th>
                            <th>Motif du refus</th>
                          </tr>
                        </thead>
                        <tbody>
                          {simulation.echecs.map(echec => (
                            <tr key={echec.ecriture_id}>
                              <td className={styles.dateCell}>{echec.date_ecriture}</td>
                              <td>{echec.libelle}</td>
                              <td className={styles.motif}>{echec.motif}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className={styles.toutBon}>
                      <CheckCircle2 size={16} />
                      <span>Toutes les écritures du périmètre passent les contrôles.</span>
                    </div>
                  )}

                  <div className={styles.avertissement}>
                    <AlertTriangle size={16} />
                    <span>
                      La validation est <strong>irréversible</strong> : une écriture validée devient
                      immuable et ne peut plus être corrigée que par contre-passation.
                    </span>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <footer className={styles.pied}>
          <button type="button" className={styles.annuler} onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className={styles.confirmer}
            disabled={enCours || validation || !simulation || simulation.validees === 0}
            onClick={lancerValidation}
          >
            {validation
              ? 'Validation en cours…'
              : `Valider ${simulation?.validees ?? 0} écriture(s)`}
          </button>
        </footer>
      </div>
    </div>
  )
}
