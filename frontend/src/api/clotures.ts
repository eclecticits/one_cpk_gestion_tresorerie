import { apiRequest } from '../lib/apiClient'

export type ClotureBalance = {
  date_debut?: string | null
  date_fin: string
  taux_change: string
  solde_initial_usd: string
  solde_initial_cdf: string
  total_entrees_usd: string
  total_entrees_cdf: string
  total_sorties_usd: string
  total_sorties_cdf: string
  solde_theorique_usd: string
  solde_theorique_cdf: string
  // Ventilation des entrées : les notes de débit ne sont pas la seule source
  // d'argent qui rentre dans le tiroir.
  entrees_encaissements_usd?: string
  entrees_encaissements_cdf?: string
  entrees_approvisionnements_usd?: string
  entrees_approvisionnements_cdf?: string
  entrees_transferts_usd?: string
  entrees_transferts_cdf?: string
  entrees_retours_usd?: string
  entrees_retours_cdf?: string
  approvisionnements?: EntreeCaisseLigne[]
}

/** Entrée de caisse hors note de débit (approvisionnement banque -> caisse). */
export type EntreeCaisseLigne = {
  id: string
  date: string | null
  reference: string | null
  libelle: string
  montant: string
  devise: 'USD' | 'CDF'
  mode_paiement?: string | null
  source: string
  type_operation: string
  sens: 'ENTREE'
}

export type ClotureCreate = {
  solde_physique_usd: number | string
  solde_physique_cdf: number | string
  billetage_usd?: Record<string, number>
  billetage_cdf?: Record<string, number>
  observation?: string
  // Un ecart ne deplace le solde que si la regularisation est demandee : elle
  // cree alors un encaissement (excedent) ou une sortie (deficit). Sinon la
  // cloture aboutit quand meme et l'ecart reste ouvert.
  regulariser_ecart?: boolean
  motif_regularisation?: string
}

export type RegularisationCreee = {
  devise: string
  sens: 'EXCEDENT' | 'DEFICIT'
  montant: string
  encaissement_id?: string | null
  sortie_fonds_id?: string | null
}

export type EcartCaisse = {
  source_type: 'OUVERTURE' | 'CLOTURE'
  source_id: number
  reference_numero: string
  date: string | null
  devise: string
  ecart: string
  sens: 'EXCEDENT' | 'DEFICIT'
  regularise: boolean
}

export async function listEcartsCaisse(nonRegularisesSeulement = true): Promise<EcartCaisse[]> {
  return apiRequest('GET', '/clotures/ecarts', {
    params: { non_regularises_seulement: nonRegularisesSeulement },
  })
}

export async function regulariserEcart(
  sourceType: 'OUVERTURE' | 'CLOTURE',
  sourceId: number,
  motif: string,
  devise?: string,
): Promise<{ ok: boolean; regularisations: RegularisationCreee[]; erreurs: string[] }> {
  return apiRequest('POST', `/clotures/ecarts/${sourceType}/${sourceId}/regulariser`, {
    body: { motif, devise },
  })
}

export type ClotureOut = {
  id: number
  reference_numero: string
  date_cloture: string
  date_debut?: string | null
  caissier_id?: string | null
  solde_initial_usd: string
  solde_initial_cdf: string
  total_entrees_usd: string
  total_entrees_cdf: string
  total_sorties_usd: string
  total_sorties_cdf: string
  solde_theorique_usd: string
  solde_theorique_cdf: string
  solde_physique_usd: string
  solde_physique_cdf: string
  ecart_usd: string
  ecart_cdf: string
  regularisations?: RegularisationCreee[]
  regularisation_erreurs?: string[]
  taux_change_applique: string
  billetage_usd?: Record<string, number>
  billetage_cdf?: Record<string, number>
  observation?: string | null
  pdf_path?: string | null
  statut: string
}

export async function getClotureBalance(): Promise<ClotureBalance> {
  return apiRequest('GET', '/clotures/balance-check')
}

export async function createCloture(payload: ClotureCreate): Promise<ClotureOut> {
  return apiRequest('POST', '/clotures', { body: payload })
}

export type CloturePdfDetail = {
  reference_numero?: string | null
  beneficiaire?: string | null
  motif?: string | null
  montant_paye?: string | number | null
}

export type CloturePdfData = {
  cloture: ClotureOut
  details: CloturePdfDetail[]
}

export async function getCloturePdfData(id: number): Promise<CloturePdfData> {
  return apiRequest('GET', `/clotures/${id}/pdf-data`)
}

export async function listClotures(limit = 50, offset = 0): Promise<ClotureOut[]> {
  return apiRequest('GET', '/clotures', { params: { limit, offset } })
}

export async function getLastCloture(): Promise<ClotureOut | null> {
  const items = await listClotures(1, 0)
  return items?.[0] || null
}

export type ClotureListFilters = {
  date_debut?: string
  date_fin?: string
  caissier_id?: string
  limit?: number
  offset?: number
}

export async function listCloturesWithFilters(filters: ClotureListFilters): Promise<ClotureOut[]> {
  return apiRequest('GET', '/clotures', { params: filters })
}

export async function uploadCloturePdf(id: number, file: Blob): Promise<{ ok: boolean; pdf_path: string }> {
  const form = new FormData()
  form.append('file', file, `cloture_${id}.pdf`)
  return apiRequest('POST', `/clotures/${id}/pdf`, form)
}

export type ClotureCaissier = {
  id: string
  label: string
  email?: string
}

export async function getClotureCaissiers(): Promise<ClotureCaissier[]> {
  return apiRequest('GET', '/clotures/caissiers')
}
