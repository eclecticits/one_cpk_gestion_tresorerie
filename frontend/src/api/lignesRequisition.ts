import { apiRequest } from '../lib/apiClient'

/** Ligne telle que la renvoie l'API. */
export interface LigneRequisitionApi {
  id: string
  requisition_id: string
  budget_poste_id: number | null
  rubrique: string
  description: string
  quantite: number
  montant_unitaire: number | string
  montant_total: number | string
  devise?: string | null
  mode_paiement?: string | null
  compte_bancaire_id?: number | null
  budget_poste_code_snapshot?: string | null
  budget_poste_libelle_snapshot?: string | null
}

export interface LigneRequisitionPayload {
  budget_poste_id: number | null
  rubrique: string
  description: string
  quantite: number
  montant_unitaire: number
  montant_total: number
  devise?: string
  mode_paiement?: string | null
  compte_bancaire_id?: number | null
}

export function createLignesRequisition(
  lignes: (LigneRequisitionPayload & { requisition_id: string })[]
): Promise<LigneRequisitionApi[]> {
  return apiRequest<LigneRequisitionApi[]>('POST', '/lignes-requisition', lignes)
}

/** Réécrit la ligne en entier : elle repasse par les contrôles budgétaires. */
export function updateLigneRequisition(
  ligneId: string,
  payload: LigneRequisitionPayload
): Promise<LigneRequisitionApi> {
  return apiRequest<LigneRequisitionApi>('PUT', `/lignes-requisition/${ligneId}`, payload)
}

export function deleteLigneRequisition(ligneId: string): Promise<void> {
  return apiRequest<void>('DELETE', `/lignes-requisition/${ligneId}`)
}

/** En-tête de la réquisition. Le montant, lui, suit les lignes. */
export function updateRequisition(
  requisitionId: string,
  payload: Record<string, unknown>
): Promise<any> {
  return apiRequest('PUT', `/requisitions/${requisitionId}`, payload)
}
