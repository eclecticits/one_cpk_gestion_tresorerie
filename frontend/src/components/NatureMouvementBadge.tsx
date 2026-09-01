import type { HorsBudgetStatus, NatureMouvement } from '../types'
import { HORS_BUDGET_STATUS_LABELS, NATURE_MOUVEMENT_LABELS } from '../api/mouvementsHorsBudget'
import styles from './NatureMouvementBadge.module.css'

/**
 * Dit d'un coup d'œil si une ligne pèse sur le budget.
 *
 * Un mouvement budgétaire est le cas normal : on n'affiche rien, sinon la
 * pastille perdrait tout pouvoir d'alerte à force d'être partout. Ne
 * s'affichent que les exceptions — et pour un hors budget, l'état de sa
 * régularisation, qui est l'information qu'on vient chercher.
 */

interface Props {
  nature?: NatureMouvement | null
  horsBudgetStatus?: HorsBudgetStatus | null
  /** Affiche aussi la pastille neutre des lignes budgétaires. */
  afficherBudgetaire?: boolean
}

const CLASSE_PAR_NATURE: Record<NatureMouvement, string> = {
  BUDGETAIRE: styles.budgetaire,
  HORS_BUDGET_A_REGULARISER: styles.horsBudget,
  FONDS_DE_TIERS: styles.fondsTiers,
  TRANSFERT_INTERNE: styles.transfert,
}

export default function NatureMouvementBadge({
  nature,
  horsBudgetStatus,
  afficherBudgetaire = false,
}: Props) {
  const valeur: NatureMouvement = nature || 'BUDGETAIRE'
  if (valeur === 'BUDGETAIRE' && !afficherBudgetaire) return null

  const estRegularise = horsBudgetStatus === 'AFFECTE_BUDGET'
  const libelle =
    valeur === 'HORS_BUDGET_A_REGULARISER' && horsBudgetStatus
      ? HORS_BUDGET_STATUS_LABELS[horsBudgetStatus]
      : NATURE_MOUVEMENT_LABELS[valeur]

  return (
    <span
      className={`${styles.badge} ${estRegularise ? styles.regularise : CLASSE_PAR_NATURE[valeur]}`}
      title={
        valeur === 'BUDGETAIRE'
          ? 'Ce mouvement consomme le budget.'
          : "Ce mouvement a bougé la trésorerie sans consommer le budget."
      }
    >
      {libelle}
    </span>
  )
}
