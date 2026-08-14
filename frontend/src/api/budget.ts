import { apiRequest } from '../lib/apiClient'
import type { BudgetExercisesResponse, BudgetPostesResponse, BudgetPostesTreeResponse, BudgetPosteSummary } from '../types/budget'

export async function getBudgetPostes(params?: { annee?: number; type?: string; active?: boolean; service_id?: number | null }): Promise<BudgetPostesResponse> {
  return apiRequest<BudgetPostesResponse>('GET', '/budget/postes', { params })
}

export async function getBudgetPostesTree(params?: { annee?: number; type?: string; active?: boolean; service_id?: number | null }): Promise<BudgetPostesTreeResponse> {
  return apiRequest<BudgetPostesTreeResponse>('GET', '/budget/postes/tree', { params })
}

export async function getBudgetExercises(): Promise<BudgetExercisesResponse> {
  return apiRequest<BudgetExercisesResponse>('GET', '/budget/exercices')
}

export async function createBudgetExercise(input: { annee: number }): Promise<{ annee: number; statut?: string | null }> {
  return apiRequest('POST', '/budget/exercices', input)
}

export async function createBudgetPoste(input: {
  annee: number
  code: string
  libelle: string
  parent_code?: string | null
  parent_id?: number | null
  type: string
  active?: boolean
  /** Ligne comptée dans les totaux et la synthèse. Défaut : oui. */
  inclure_dans_calculs?: boolean
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
    inclure_dans_calculs?: boolean
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
  conflict_mode?: 'add_only' | 'update_existing' | 'replace_exercise'
  replace_confirmation?: string | null
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
  created?: number
  updated?: number
  skipped?: number
  error_count?: number
  total_lignes?: number
  backup_path?: string | null
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

export async function getBudgetSummary(params?: { annee?: number; service_id?: number | null }): Promise<{
  annee: number | null
  recettes: { prevu: number; reel: number }
  depenses: { prevu: number; reel: number; engage?: number; paye?: number }
  service_id?: number | null
  total_recettes?: number
  total_depenses?: number
  solde?: number
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

/** Commentaire attaché à une ligne budgétaire. Fil en ajout seul. */
export type BudgetCommentaire = {
  id: number
  exercice_id: number
  /** Ancre métier : le code survit aux réimports, contrairement à l'id du poste. */
  code: string
  budget_poste_id?: number | null
  texte: string
  /** Statut du budget au moment de l'écriture, figé (Brouillon / Voté / Clôturé). */
  statut_budget?: string | null
  auteur_id?: string | null
  auteur_nom?: string | null
  created_at: string
  /** Renseigné seulement si le texte a été retouché. */
  updated_at?: string | null
  /** Calculé côté serveur : exercice au brouillon ET utilisateur auteur. */
  modifiable?: boolean
}

export async function getBudgetCommentaires(params: {
  annee: number
  code?: string
}): Promise<{ annee: number; commentaires: BudgetCommentaire[] }> {
  return apiRequest('GET', '/budget/commentaires', { params })
}

export async function createBudgetCommentaire(input: {
  annee: number
  code: string
  texte: string
}): Promise<BudgetCommentaire> {
  return apiRequest('POST', '/budget/commentaires', input)
}

export async function updateBudgetCommentaire(
  id: number,
  input: { texte: string }
): Promise<BudgetCommentaire> {
  return apiRequest('PUT', `/budget/commentaires/${id}`, input)
}

/** Commentaire général de l'exercice : un texte par vue, rendu sous le tableau
 *  dans tous les exports budgétaires. Les deux vues arrivent ensemble, l'écran
 *  bascule de l'une à l'autre sans recharger. */
export type BudgetCommentaireGeneral = {
  annee: number
  statut?: string | null
  depense?: string | null
  recette?: string | null
  /** Calculé côté serveur : faux dès que l'exercice est clôturé. */
  modifiable?: boolean
}

export async function getBudgetCommentaireGeneral(params: {
  annee: number
}): Promise<BudgetCommentaireGeneral> {
  return apiRequest('GET', '/budget/commentaire-general', { params })
}

export async function saveBudgetCommentaireGeneral(input: {
  annee: number
  vue: 'DEPENSE' | 'RECETTE'
  texte: string
}): Promise<BudgetCommentaireGeneral> {
  return apiRequest('PUT', '/budget/commentaire-general', input)
}
