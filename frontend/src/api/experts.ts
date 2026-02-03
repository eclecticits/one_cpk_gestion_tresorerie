import { apiRequest } from '../lib/apiClient'

export type CategoryType = 'sec' | 'en_cabinet' | 'independant' | 'salarie'

export interface ExpertComptable {
  id: string
  numero_ordre: string
  nom_denomination: string
  type_ec: string
  categorie_personne?: string
  statut_professionnel?: string
  sexe?: string
  telephone?: string
  email?: string
  nif?: string
  cabinet_attache?: string
  nom_employeur?: string
  raison_sociale?: string
  associe_gerant?: string
  import_id?: string
  active: boolean
  created_at: string
}

export interface ExpertSearchParams {
  numero_ordre?: string
  nom?: string
  type_ec?: string
  active?: boolean
  limit?: number
  offset?: number
}

export interface ExpertImportRow {
  numero_ordre: string
  nom_denomination: string
  type_ec?: string
  categorie_personne?: string
  statut_professionnel?: string
  sexe?: string
  telephone?: string
  email?: string
  nif?: string
  cabinet_attache?: string
  nom_employeur?: string
  raison_sociale?: string
  associe_gerant?: string
}

export interface ExpertImportRequest {
  category: CategoryType
  filename: string
  rows: ExpertImportRow[]
  file_data?: Record<string, unknown>[]
}

export interface ExpertImportResponse {
  success: boolean
  imported: number
  updated?: number
  skipped?: number
  total_lignes?: number
  errors?: { ligne: number; champ: string; message: string }[]
  import_id?: string
  message: string
}

export interface CategoryChangeRequest {
  expert_id: string
  new_category: CategoryType
  reason?: string
  nif?: string
  cabinet_attache?: string
  nom_employeur?: string
  raison_sociale?: string
  associe_gerant?: string
}

export interface CategoryChangeResponse {
  id: string
  expert_id: string
  numero_ordre: string
  old_category?: string
  new_category: string
  changed_by?: string
  reason?: string
  old_data?: Record<string, unknown>
  new_data?: Record<string, unknown>
  created_at: string
}

// Liste/recherche d'experts
async function searchExperts(params: ExpertSearchParams = {}): Promise<ExpertComptable[]> {
  const queryParams = new URLSearchParams()
  if (params.numero_ordre) queryParams.append('numero_ordre', params.numero_ordre)
  if (params.nom) queryParams.append('nom', params.nom)
  if (params.type_ec) queryParams.append('type_ec', params.type_ec)
  if (params.active !== undefined) queryParams.append('active', String(params.active))
  if (params.limit) queryParams.append('limit', String(params.limit))
  if (params.offset) queryParams.append('offset', String(params.offset))

  const query = queryParams.toString()
  return apiRequest<ExpertComptable[]>('GET', `/experts-comptables${query ? `?${query}` : ''}`)
}

// Recherche par numéro d'ordre (retourne un seul expert ou null)
export async function findExpertByNumeroOrdre(numeroOrdre: string): Promise<ExpertComptable | null> {
  const results = await searchExperts({ numero_ordre: numeroOrdre, limit: 1 })
  return results.length > 0 ? results[0] : null
}

// Import batch d'experts
export async function importExperts(data: ExpertImportRequest): Promise<ExpertImportResponse> {
  return apiRequest<ExpertImportResponse>('POST', '/experts-comptables/import', data)
}

// Changement de catégorie
export async function changeCategory(data: CategoryChangeRequest): Promise<CategoryChangeResponse> {
  return apiRequest<CategoryChangeResponse>('POST', '/experts-comptables/category-change', data)
}
