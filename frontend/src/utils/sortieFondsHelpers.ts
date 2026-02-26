import { TypeSortieFonds } from '../types'

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
    label: 'Sorties bancaires',
    types: [
      { value: 'versement_banque', label: 'Versement à la banque' },
    ]
  },
]

export const TYPES_SORTIE_LABELS: Record<TypeSortieFonds, string> = {
  requisition: 'Paiement de réquisition',
  remboursement: 'Remboursement',
  versement_banque: 'Versement à la banque',
  sortie_directe: 'Sortie directe (max 100$)',
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
