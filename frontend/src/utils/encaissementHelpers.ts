import { TypeClient } from '../types'

export const TYPE_CLIENT_LABELS: Record<TypeClient, string> = {
  expert_comptable: 'Expert-comptable',
  personne_physique: 'Personne physique',
  personne_morale: 'Personne morale',
  client_externe: 'Client externe',
  banque_institution: 'Banque / Institution',
  partenaire: 'Partenaire',
  organisation: 'Organisation',
  autre: 'Autre',
}

export function getTypeClientLabel(typeClient: TypeClient): string {
  return TYPE_CLIENT_LABELS[typeClient] || typeClient
}

/**
 * Types de client derrière lesquels il y a une personne, donc un sexe.
 *
 * Une banque, une organisation, un partenaire ou une personne morale n'en ont
 * pas : leur demander le champ produirait une colonne vide dans l'export et
 * une question sans réponse à la saisie. L'expert-comptable en aurait un, mais
 * il relève d'un autre référentiel, qui ne porte pas l'information.
 */
export const TYPES_CLIENT_AVEC_SEXE: TypeClient[] = ['personne_physique', 'client_externe']

export function typeClientDemandeLeSexe(typeClient: TypeClient): boolean {
  return TYPES_CLIENT_AVEC_SEXE.includes(typeClient)
}

/** Étiquette lisible d'un sexe stocké ('M' / 'F'), pour l'affichage. */
export const SEXE_LABELS: Record<string, string> = { M: 'Masculin', F: 'Féminin' }
