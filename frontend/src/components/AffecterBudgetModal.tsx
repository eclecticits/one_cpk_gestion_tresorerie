import { useEffect, useMemo, useState } from 'react'
import BudgetPosteSelect from './BudgetPosteSelect'
import { getBudgetPostes } from '../api/budget'
import {
  affecterEncaissementBudget,
  affecterSortieBudget,
} from '../api/mouvementsHorsBudget'
import type { BudgetPosteSummary } from '../types/budget'
import { toNumber } from '../utils/amount'
import styles from './AffecterBudgetModal.module.css'

/**
 * Affecter au budget un mouvement encaissé ou payé hors budget.
 *
 * L'argent a déjà bougé : cet écran ne rejoue aucun paiement, il décide sur
 * quel(s) poste(s) l'imputer, et exige une justification parce que c'est une
 * décision, pas une saisie. On peut n'affecter qu'une partie du montant — le
 * reste demeure à régulariser et l'écran se rouvre pour le solde.
 */

export type CibleAffectation = 'encaissement' | 'sortie'

interface Props {
  cible: CibleAffectation
  mouvementId: string
  /** Montant encore à affecter, dans la devise du mouvement. */
  resteAAffecter: number
  devise: string
  /** Référence lisible (numéro de reçu ou de paiement) affichée en en-tête. */
  libelle: string
  onClose: () => void
  onSuccess: (message: string) => void
  onError: (title: string, message: string) => void
}

interface LigneDraft {
  key: string
  budget_poste_id: number | null
  montant: string
}

const nouvelleLigne = (): LigneDraft => ({
  key: Math.random().toString(36).slice(2),
  budget_poste_id: null,
  montant: '',
})

const formatMontant = (valeur: number, devise: string) =>
  new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: devise === 'CDF' ? 'CDF' : 'USD',
  }).format(valeur)

export default function AffecterBudgetModal({
  cible,
  mouvementId,
  resteAAffecter,
  devise,
  libelle,
  onClose,
  onSuccess,
  onError,
}: Props) {
  // Le sens du mouvement décide du type de poste : une recette hors budget
  // s'impute sur un poste RECETTE, une dépense sur un poste DEPENSE. Proposer
  // les deux n'aurait aucun sens et le serveur refuserait de toute façon.
  const typePoste = cible === 'encaissement' ? 'RECETTE' : 'DEPENSE'

  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [chargement, setChargement] = useState(true)
  const [lignes, setLignes] = useState<LigneDraft[]>([nouvelleLigne()])
  const [justification, setJustification] = useState('')
  const [reference, setReference] = useState('')
  const [envoiEnCours, setEnvoiEnCours] = useState(false)

  // Clé d'idempotence figée à l'ouverture : un double clic, ou un renvoi après
  // une réponse perdue, retombe sur la même régularisation au lieu d'en créer
  // une seconde.
  const [idempotencyKey] = useState(
    () => `aff-${cible}-${mouvementId}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
  )

  useEffect(() => {
    let annule = false
    setChargement(true)
    getBudgetPostes({ type: typePoste, active: true })
      .then((res) => {
        if (annule) return
        setPostes(res.postes || [])
      })
      .catch(() => {
        if (!annule) setPostes([])
      })
      .finally(() => {
        if (!annule) setChargement(false)
      })
    return () => {
      annule = true
    }
  }, [typePoste])

  const totalSaisi = useMemo(
    () => lignes.reduce((somme, ligne) => somme + (toNumber(ligne.montant) || 0), 0),
    [lignes],
  )
  const restant = Math.round((resteAAffecter - totalSaisi + Number.EPSILON) * 100) / 100

  const majLigne = (key: string, champ: Partial<LigneDraft>) => {
    setLignes((prev) => prev.map((l) => (l.key === key ? { ...l, ...champ } : l)))
  }

  const supprimerLigne = (key: string) => {
    setLignes((prev) => (prev.length === 1 ? prev : prev.filter((l) => l.key !== key)))
  }

  const remplirLeReste = (key: string) => {
    const autres = lignes
      .filter((l) => l.key !== key)
      .reduce((somme, l) => somme + (toNumber(l.montant) || 0), 0)
    const reste = Math.round((resteAAffecter - autres + Number.EPSILON) * 100) / 100
    if (reste > 0) majLigne(key, { montant: String(reste) })
  }

  const valider = (): string | null => {
    if (justification.trim().length < 3) {
      return "La justification doit expliquer la décision (3 caractères minimum)."
    }
    if (lignes.some((l) => !l.budget_poste_id)) {
      return 'Chaque ligne doit viser un poste budgétaire.'
    }
    if (lignes.some((l) => (toNumber(l.montant) || 0) <= 0)) {
      return 'Chaque ligne doit porter un montant supérieur à zéro.'
    }
    if (totalSaisi > resteAAffecter + 0.001) {
      return `Le total réparti (${formatMontant(totalSaisi, devise)}) dépasse le reste à affecter (${formatMontant(resteAAffecter, devise)}).`
    }
    return null
  }

  const soumettre = async () => {
    const erreur = valider()
    if (erreur) {
      onError('Affectation impossible', erreur)
      return
    }
    setEnvoiEnCours(true)
    try {
      const payload = {
        lignes: lignes.map((l) => ({
          budget_poste_id: Number(l.budget_poste_id),
          montant: toNumber(l.montant) || 0,
        })),
        justification: justification.trim(),
        reference: reference.trim() || null,
        idempotency_key: idempotencyKey,
      }
      if (cible === 'encaissement') {
        await affecterEncaissementBudget(mouvementId, payload)
      } else {
        await affecterSortieBudget(mouvementId, payload)
      }
      const soldeApres = Math.round((resteAAffecter - totalSaisi + Number.EPSILON) * 100) / 100
      onSuccess(
        soldeApres > 0
          ? `${formatMontant(totalSaisi, devise)} affectés au budget. Reste ${formatMontant(soldeApres, devise)} à régulariser.`
          : `${formatMontant(totalSaisi, devise)} affectés au budget. Mouvement entièrement régularisé.`,
      )
      onClose()
    } catch (e: any) {
      onError('Affectation refusée', e?.message || "L'affectation budgétaire a échoué.")
    } finally {
      setEnvoiEnCours(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <div>
            <h2 className={styles.title}>Affecter au budget</h2>
            <p className={styles.subtitle}>
              {libelle} · reste à affecter <strong>{formatMontant(resteAAffecter, devise)}</strong>
            </p>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            ×
          </button>
        </header>

        <p className={styles.note}>
          La trésorerie a déjà bougé lors de l'opération. Cette décision ne touche que le budget :
          elle impute le montant sur {typePoste === 'RECETTE' ? 'un ou plusieurs postes de recette' : 'un ou plusieurs postes de dépense'} et
          reste tracée avec son auteur et sa justification.
        </p>

        <div className={styles.lignes}>
          {lignes.map((ligne) => (
            <div key={ligne.key} className={styles.ligne}>
              <div className={styles.ligneChamp}>
                <label>Poste budgétaire</label>
                <BudgetPosteSelect
                  postes={postes}
                  value={ligne.budget_poste_id}
                  onChange={(id) => majLigne(ligne.key, { budget_poste_id: id })}
                  disabled={chargement}
                  placeholder={chargement ? 'Chargement des postes…' : 'Rechercher un poste'}
                  emptyHint={`Aucun poste ${typePoste.toLowerCase()} actif sur l'exercice.`}
                />
              </div>
              <div className={styles.ligneMontant}>
                <label>Montant ({devise})</label>
                <div className={styles.montantRow}>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={ligne.montant}
                    onChange={(e) => majLigne(ligne.key, { montant: e.target.value })}
                    placeholder="0.00"
                  />
                  <button type="button" className={styles.linkBtn} onClick={() => remplirLeReste(ligne.key)}>
                    Le reste
                  </button>
                </div>
              </div>
              <button
                type="button"
                className={styles.removeBtn}
                onClick={() => supprimerLigne(ligne.key)}
                disabled={lignes.length === 1}
                aria-label="Retirer cette ligne"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={() => setLignes((prev) => [...prev, nouvelleLigne()])}
        >
          Ajouter un poste
        </button>

        <div className={styles.totaux}>
          <span>Total réparti <strong>{formatMontant(totalSaisi, devise)}</strong></span>
          <span className={restant < 0 ? styles.totalNegatif : undefined}>
            Restera à régulariser <strong>{formatMontant(Math.max(restant, 0), devise)}</strong>
          </span>
        </div>

        <div className={styles.champ}>
          <label>Justification *</label>
          <textarea
            rows={3}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Pourquoi ce mouvement est affecté ainsi (décision, pièce, instruction reçue)"
          />
        </div>

        <div className={styles.champ}>
          <label>Référence de la décision (facultatif)</label>
          <input
            type="text"
            maxLength={100}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="N° de PV, note de service…"
          />
        </div>

        <footer className={styles.footer}>
          <button type="button" className={styles.secondaryBtn} onClick={onClose} disabled={envoiEnCours}>
            Annuler
          </button>
          <button type="button" className={styles.primaryBtn} onClick={soumettre} disabled={envoiEnCours}>
            {envoiEnCours ? 'Affectation…' : 'Affecter au budget'}
          </button>
        </footer>
      </div>
    </div>
  )
}
