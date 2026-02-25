import { TypeClient } from '../types'

export const TYPE_CLIENT_LABELS: Record<TypeClient, string> = {
  expert_comptable: 'Expert-comptable',
  client_externe: 'Client externe',
  banque_institution: 'Banque / Institution',
  partenaire: 'Partenaire',
  organisation: 'Organisation',
  autre: 'Autre',
}

export function getTypeClientLabel(typeClient: TypeClient): string {
  return TYPE_CLIENT_LABELS[typeClient] || typeClient
}
