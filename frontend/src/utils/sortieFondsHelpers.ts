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
  {
    label: 'Dépenses opérationnelles',
    types: [
      { value: 'achat_fournitures', label: 'Achat de fournitures' },
      { value: 'achat_materiel_informatique', label: 'Achat matériel informatique' },
      { value: 'achat_carburant', label: 'Achat carburant' },
      { value: 'achat_consommables', label: 'Achat consommables' },
    ]
  },
  {
    label: 'Paiements de services',
    types: [
      { value: 'paiement_loyer', label: 'Paiement loyer' },
      { value: 'paiement_internet', label: 'Paiement internet' },
      { value: 'paiement_electricite_eau', label: 'Paiement électricité / eau' },
      { value: 'paiement_telephone', label: 'Paiement téléphone' },
      { value: 'paiement_maintenance', label: 'Paiement maintenance' },
    ]
  },
  {
    label: 'Ressources humaines',
    types: [
      { value: 'salaire', label: 'Salaire' },
      { value: 'prime', label: 'Prime' },
      { value: 'indemnite', label: 'Indemnité' },
      { value: 'per_diem', label: 'Per diem' },
      { value: 'remboursement_transport', label: 'Remboursement transport' },
    ]
  },
  {
    label: 'Activités institutionnelles',
    types: [
      { value: 'organisation_formation', label: 'Organisation formation' },
      { value: 'organisation_reunion', label: 'Organisation réunion' },
      { value: 'organisation_atelier', label: 'Organisation atelier' },
      { value: 'frais_mission', label: 'Frais de mission' },
      { value: 'frais_deplacement', label: 'Frais de déplacement' },
    ]
  },
  {
    label: 'Autres',
    types: [
      { value: 'depense_exceptionnelle', label: 'Dépense exceptionnelle' },
      { value: 'autre_sortie', label: 'Autre sortie' },
    ]
  },
]

export const TYPES_SORTIE_LABELS: Record<TypeSortieFonds, string> = {
  requisition: 'Paiement de réquisition',
  remboursement: 'Remboursement',
  versement_banque: 'Versement à la banque',
  sortie_directe: 'Sortie directe (max 100$)',
  achat_fournitures: 'Achat de fournitures',
  achat_materiel_informatique: 'Achat matériel informatique',
  achat_carburant: 'Achat carburant',
  achat_consommables: 'Achat consommables',
  paiement_loyer: 'Paiement loyer',
  paiement_internet: 'Paiement internet',
  paiement_electricite_eau: 'Paiement électricité / eau',
  paiement_telephone: 'Paiement téléphone',
  paiement_maintenance: 'Paiement maintenance',
  salaire: 'Salaire',
  prime: 'Prime',
  indemnite: 'Indemnité',
  per_diem: 'Per diem',
  remboursement_transport: 'Remboursement transport',
  organisation_formation: 'Organisation formation',
  organisation_reunion: 'Organisation réunion',
  organisation_atelier: 'Organisation atelier',
  frais_mission: 'Frais de mission',
  frais_deplacement: 'Frais de déplacement',
  depense_exceptionnelle: 'Dépense exceptionnelle',
  autre_sortie: 'Autre sortie',
}

export function getTypeSortieLabel(type: TypeSortieFonds): string {
  return TYPES_SORTIE_LABELS[type] || type
}

export function getBeneficiairePlaceholder(type: TypeSortieFonds): string {
  if (type.includes('banque')) {
    return 'Nom de la banque (ex: Rawbank, BCDC, Equity)'
  }
  if (type.includes('salaire') || type.includes('prime') || type.includes('indemnite') || type === 'per_diem') {
    return "Nom de l'agent"
  }
  if (type.includes('achat') || type.includes('fourniture') || type.includes('materiel')) {
    return 'Nom du fournisseur'
  }
  if (type.includes('paiement')) {
    return 'Nom de la société / prestataire'
  }
  if (type === 'remboursement_transport') {
    return 'Nom du bénéficiaire'
  }
  if (type.includes('organisation') || type.includes('frais') || type.includes('mission') || type.includes('deplacement')) {
    return "Nom de l'expert ou du participant"
  }
  return 'Nom du bénéficiaire'
}

export function getMotifPlaceholder(type: TypeSortieFonds): string {
  const examples: Record<string, string> = {
    versement_banque: 'Dépôt des recettes journalières à la banque',
    paiement_internet: 'Paiement facture internet du mois de janvier',
    achat_fournitures: 'Achat urgent de papier A4 et stylos',
    per_diem: 'Per diem réunion CPK du 10 janvier 2026',
    remboursement_transport: 'Remboursement frais transport expert pour formation',
    salaire: 'Salaire du mois de janvier 2026',
    organisation_formation: 'Organisation formation professionnelle continue',
  }

  for (const [key, placeholder] of Object.entries(examples)) {
    if (type.includes(key)) return placeholder
  }

  return 'Description détaillée du motif de la sortie'
}
