import { NatureMouvement, TypeSortieFonds } from '../types'

export interface CategorieTypeSortie {
  label: string
  types: { value: TypeSortieFonds; label: string }[]
}

export const CATEGORIES_SORTIE: CategorieTypeSortie[] = [
  {
    label: 'Système (réquisitions)',
    types: [
      { value: 'requisition', label: 'Paiement de réquisition' },
      { value: 'remboursement', label: 'Remboursement' },
      { value: 'sortie_directe', label: 'Sortie directe (max 100$)' },
    ]
  },
  {
    label: 'Transferts caisse / banque',
    types: [
      { value: 'versement_banque', label: 'Versement à la banque (caisse → banque)' },
      { value: 'approvisionnement_caisse', label: 'Approvisionnement caisse (banque → caisse)' },
    ]
  },
  {
    // Deux sorties réelles de trésorerie qui ne consomment aucun budget : l'une
    // parce que l'argent appartenait à un tiers, l'autre parce que l'imputation
    // reste à décider.
    label: 'Hors budget',
    types: [
      { value: 'remboursement_fonds_tiers', label: 'Reversement de fonds de tiers' },
      { value: 'depense_hors_budget', label: 'Dépense hors budget (à régulariser)' },
    ]
  },
]

export const TYPES_SORTIE_LABELS: Record<TypeSortieFonds, string> = {
  requisition: 'Paiement de réquisition',
  remboursement: 'Remboursement',
  versement_banque: 'Versement à la banque',
  approvisionnement_caisse: 'Approvisionnement caisse',
  sortie_directe: 'Sortie directe (max 100$)',
  remboursement_fonds_tiers: 'Reversement de fonds de tiers',
  depense_hors_budget: 'Dépense hors budget',
}

/** Nature imposée par le type de sortie. Le type dit ce qu'on fait ; la nature
 *  en tire la seule conséquence qui compte pour le budget. */
export function natureDuTypeSortie(type: TypeSortieFonds): NatureMouvement {
  if (type === 'remboursement_fonds_tiers') return 'FONDS_DE_TIERS'
  if (type === 'depense_hors_budget') return 'HORS_BUDGET_A_REGULARISER'
  if (type === 'versement_banque' || type === 'approvisionnement_caisse') return 'TRANSFERT_INTERNE'
  return 'BUDGETAIRE'
}

export function getTypeSortieLabel(type: TypeSortieFonds): string {
  return TYPES_SORTIE_LABELS[type] || type
}

export function getBeneficiairePlaceholder(type: TypeSortieFonds): string {
  if (type.includes('banque')) {
    return 'Nom de la banque (ex: Rawbank, BCDC, Equity)'
  }
  if (type === 'remboursement') {
    return 'Nom du bénéficiaire'
  }
  return 'Nom du bénéficiaire'
}

export function getMotifPlaceholder(type: TypeSortieFonds): string {
  const examples: Record<string, string> = {
    versement_banque: 'Dépôt des recettes journalières à la banque',
    remboursement: 'Remboursement transport / frais autorisés',
  }

  for (const [key, placeholder] of Object.entries(examples)) {
    if (type.includes(key)) return placeholder
  }

  return 'Description détaillée du motif de la sortie'
}
