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
}

export type ClotureCreate = {
  solde_physique_usd: number | string
  solde_physique_cdf: number | string
  billetage_usd?: Record<string, number>
  billetage_cdf?: Record<string, number>
  observation?: string
}

export type ClotureOut = {
  id: number
  reference_numero: string
  date_cloture: string
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
  taux_change_applique: string
  billetage_usd?: Record<string, number>
  billetage_cdf?: Record<string, number>
  observation?: string | null
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
