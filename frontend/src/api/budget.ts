import { apiRequest } from '../lib/apiClient'
import type { BudgetExercisesResponse, BudgetLinesResponse, BudgetLinesTreeResponse, BudgetLineSummary } from '../types/budget'

export async function getBudgetLines(params?: { annee?: number; type?: string; active?: boolean }): Promise<BudgetLinesResponse> {
  return apiRequest<BudgetLinesResponse>('GET', '/budget/lines', { params })
}

export async function getBudgetLinesTree(params?: { annee?: number; type?: string; active?: boolean }): Promise<BudgetLinesTreeResponse> {
  return apiRequest<BudgetLinesTreeResponse>('GET', '/budget/lines/tree', { params })
}

export async function getBudgetExercises(): Promise<BudgetExercisesResponse> {
  return apiRequest<BudgetExercisesResponse>('GET', '/budget/exercices')
}

export async function createBudgetLine(input: {
  annee: number
  code: string
  libelle: string
  parent_code?: string | null
  parent_id?: number | null
  type: string
  active?: boolean
  montant_prevu: string | number
}): Promise<BudgetLineSummary> {
  return apiRequest<BudgetLineSummary>('POST', '/budget/lines', input)
}

export async function updateBudgetLine(
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
): Promise<BudgetLineSummary> {
  return apiRequest<BudgetLineSummary>('PUT', `/budget/lines/${id}`, input)
}

export async function deleteBudgetLine(id: number): Promise<void> {
  return apiRequest('DELETE', `/budget/lines/${id}`)
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
