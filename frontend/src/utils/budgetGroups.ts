/**
 * Règle de dépassement budgétaire des groupes de dépense.
 *
 * Les lignes d'une réquisition sont groupées par poste budgétaire. Le
 * dépassement se juge sur le SOUS-TOTAL du groupe, jamais ligne à ligne : deux
 * lignes du même poste, chacune sous le disponible, le franchissent ensemble.
 * C'est toute la raison d'être de ce module — la règle est ici, isolée de
 * React, pour rester vérifiable.
 */

/** Ce dont la règle a besoin d'une ligne : son montant et sa devise. */
export type LigneMontant = {
  montant_total: number | string | null | undefined
  devise?: string | null
}

/** Ce dont la règle a besoin d'un groupe : son poste et ses lignes. */
export type GroupeMontants = {
  budget_poste_id: number | null
  lignes: LigneMontant[]
}

/** Conversion vers la devise pivot (USD), fournie par l'appelant. */
export type ConversionUsd = (montant: number | string | null | undefined, devise: 'USD' | 'CDF') => number

/**
 * Sous-total d'un groupe, en USD.
 *
 * La conversion est injectée : le taux vit dans la page (réglages du tenant),
 * et le mêler à la règle rendrait celle-ci intestable.
 */
export function sousTotalGroupeUsd(groupe: GroupeMontants, toUsd: ConversionUsd): number {
  return groupe.lignes.reduce(
    (somme, ligne) => somme + toUsd(ligne.montant_total, (ligne.devise || 'USD') as 'USD' | 'CDF'),
    0,
  )
}

/**
 * Premier groupe dont le sous-total dépasse le disponible de son poste.
 *
 * `disponiblePourPoste` rend `null` quand le poste est inconnu du référentiel.
 * `groupeSansPosteDepasse` tranche ce cas, parce que les deux appelants n'en
 * veulent pas la même chose :
 *   - à la validation de la pièce, un groupe sans poste EST un dépassement (on
 *     ne peut pas garantir qu'il tient dans un budget qu'on n'a pas) ;
 *   - au contrôle de l'allocation du service, il est simplement hors sujet.
 */
export function trouverGroupeEnDepassement<T extends GroupeMontants>(
  groupes: T[],
  options: {
    toUsd: ConversionUsd
    disponiblePourPoste: (budgetPosteId: number | null) => number | null
    groupeSansPosteDepasse: boolean
  },
): T | undefined {
  const { toUsd, disponiblePourPoste, groupeSansPosteDepasse } = options
  return groupes.find((groupe) => {
    const disponible = disponiblePourPoste(groupe.budget_poste_id)
    if (disponible === null) return groupeSansPosteDepasse
    return sousTotalGroupeUsd(groupe, toUsd) > disponible
  })
}
