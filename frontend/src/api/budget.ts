import { apiRequest } from '../lib/apiClient'
import type { BudgetExercisesResponse, BudgetPostesResponse, BudgetPostesTreeResponse, BudgetPosteSummary } from '../types/budget'

export async function getBudgetPostes(params?: { annee?: number; type?: string; active?: boolean }): Promise<BudgetPostesResponse> {
  return apiRequest<BudgetPostesResponse>('GET', '/budget/postes', { params })
}

export async function getBudgetPostesTree(params?: { annee?: number; type?: string; active?: boolean }): Promise<BudgetPostesTreeResponse> {
  return apiRequest<BudgetPostesTreeResponse>('GET', '/budget/postes/tree', { params })
}

export async function getBudgetExercises(): Promise<BudgetExercisesResponse> {
  return apiRequest<BudgetExercisesResponse>('GET', '/budget/exercices')
}

export async function createBudgetPoste(input: {
  annee: number
  code: string
  libelle: string
  parent_code?: string | null
  parent_id?: number | null
  type: string
  active?: boolean
  montant_prevu: string | number
}): Promise<BudgetPosteSummary> {
  return apiRequest<BudgetPosteSummary>('POST', '/budget/postes', input)
}

export async function updateBudgetPoste(
  id: number,
  input: Partial<{
    code: string
    libelle: string
    parent_code?: string | null
    parent_id?: number | null
    type: string
    active?: boolean
    montant_prevu: string | number
  }>
): Promise<BudgetPosteSummary> {
  return apiRequest<BudgetPosteSummary>('PUT', `/budget/postes/${id}`, input)
}

export async function deleteBudgetPoste(id: number): Promise<void> {
  return apiRequest('DELETE', `/budget/postes/${id}`)
}

export async function importBudgetPostes(input: {
  annee: number
  type: string
  filename?: string
  rows: Array<{
    code: string
    libelle: string
    plafond: number
    parent_code?: string | null
    parent_id?: number | null
  }>
}): Promise<{
  success: boolean
  imported: number
  skipped?: number
  total_lignes?: number
  errors?: { ligne: number; champ: string; message: string }[]
  message: string
}> {
  return apiRequest('POST', '/budget/postes/import', input)
}

export async function closeBudgetExercise(annee: number): Promise<{ ok: boolean; statut?: string }> {
  return apiRequest('POST', `/budget/exercices/${annee}/cloture`)
}

export async function reopenBudgetExercise(annee: number): Promise<{ ok: boolean; statut?: string }> {
  return apiRequest('POST', `/budget/exercices/${annee}/ouvrir`)
}

export async function getBudgetSummary(params?: { annee?: number }): Promise<{
  annee: number | null
  recettes: { prevu: number; reel: number }
  depenses: { prevu: number; reel: number; engage?: number; paye?: number }
}> {
  return apiRequest('GET', '/budget/summary', { params })
}

export async function initializeBudgetExercise(input: {
  annee_source: number
  annee_cible?: number
  coefficient?: number
  overwrite?: boolean
}): Promise<{ ok: boolean; annee_source?: number; annee_cible?: number }> {
  const params = {
    annee_cible: input.annee_cible,
    coefficient: input.coefficient,
    overwrite: input.overwrite,
  }
  return apiRequest('POST', `/budget/exercices/${input.annee_source}/initialiser`, { params })
}
