import { apiRequest } from '../lib/apiClient'

export interface CaisseStatus {
  est_ouverte: boolean
  ouverte_le: string | null
  solde_usd: string
  solde_cdf: string
}

export interface OuvertureInput {
  solde_ouverture_usd: number
  solde_ouverture_cdf: number
  observation?: string | null
  // Le comptage ne remplace jamais le solde theorique : l'ecart n'est resorbe
  // que si la regularisation est demandee (encaissement si excedent, sortie si
  // deficit). Sinon la caisse s'ouvre quand meme et l'ecart reste ouvert.
  regulariser_ecart?: boolean
  motif_regularisation?: string
}

export interface OuvertureResult {
  reference_numero: string
  ecart_usd: string | number
  ecart_cdf: string | number
  regularisations?: { devise: string; sens: string; montant: string }[]
  regularisation_erreurs?: string[]
}

export async function getCaisseStatus(): Promise<CaisseStatus> {
  return apiRequest('GET', '/clotures/caisse-status')
}

export async function openCaisse(input: OuvertureInput): Promise<OuvertureResult> {
  return apiRequest('POST', '/clotures/ouverture', input)
}

export interface Ouverture {
  id: number
  reference_numero: string
  date_ouverture: string
  caissier_id: string | null
  solde_ouverture_usd: string | number
  solde_ouverture_cdf: string | number
  solde_attendu_usd: string | number
  solde_attendu_cdf: string | number
  ecart_usd: string | number
  ecart_cdf: string | number
  observation: string | null
  statut: string
}

export async function listOuvertures(limit = 50): Promise<Ouverture[]> {
  return apiRequest('GET', '/clotures/ouvertures', { params: { limit } })
}
