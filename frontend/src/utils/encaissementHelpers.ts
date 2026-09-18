import { TypeClient } from '../types'

export const TYPE_CLIENT_LABELS: Record<TypeClient, string> = {
  expert_comptable: 'Expert-comptable',
  personne_physique: 'Personne physique',
  personne_morale: 'Personne morale',
  partenaire: 'Partenaire',
  autre: 'Autre',
}

export function getTypeClientLabel(typeClient: TypeClient): string {
  return TYPE_CLIENT_LABELS[typeClient] || typeClient
}

/**
 * Seule la personne physique a un sexe, et il est alors obligatoire.
 *
 * Une personne morale ou un partenaire n'en ont pas. L'expert-comptable en
 * aurait un, mais il relève d'un autre référentiel, qui ne porte pas
 * l'information. Même liste que TYPES_CLIENT_AVEC_SEXE côté serveur.
 */
export const TYPES_CLIENT_AVEC_SEXE: TypeClient[] = ['personne_physique']

/** Libellé du champ nom selon ce qu'il désigne. */
export function libelleNomClient(typeClient: TypeClient): string {
  if (typeClient === 'personne_morale') return 'Raison sociale'
  if (typeClient === 'partenaire') return 'Nom du partenaire'
  return 'Nom du client'
}

export function typeClientDemandeLeSexe(typeClient: TypeClient): boolean {
  return TYPES_CLIENT_AVEC_SEXE.includes(typeClient)
}

/** Étiquette lisible d'un sexe stocké ('M' / 'F'), pour l'affichage. */
export const SEXE_LABELS: Record<string, string> = { M: 'Masculin', F: 'Féminin' }
