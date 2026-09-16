import { apiRequest } from '../lib/apiClient'

/** Ce qu'une ré-imputation déplacerait, avant de la décider. */
export interface ApercuReimputation {
  postes_avant: number[]
  nouveau_poste_id: number
  /** Lignes qui partent, sur le total que porte la réquisition. */
  lignes: number
  lignes_total: number
  /** Sorties de fonds qui suivent en bloc. */
  sorties: number
  /**
   * Sorties couvrant la réquisition entière dont seule une part s'en va : leur
   * imputation est répartie au prorata, la pièce de décaissement ne bouge pas.
   */
  sorties_reparties: number
  imputations: number
  montant_engage_deplace: string | number
  montant_paye_deplace: string | number
  /** Le déplacement rassemble sur un poste des lignes qui en occupaient plusieurs. */
  fusionne_plusieurs_postes: boolean
  /** Sorties déjà comptabilisées : tant qu'il y en a, la correction est refusée. */
  sorties_comptabilisees: string[]
}

export interface ResultatReimputation {
  postes_avant: number[]
  nouveau_poste_id: number
  nouveau_poste_code: string
  lignes_deplacees: number
  lignes_total: number
  sorties_deplacees: number
  sorties_reparties: number
  imputations_deplacees: number
  montant_engage_deplace: string | number
  montant_paye_deplace: string | number
  postes_resynchronises: number
  fusionne_plusieurs_postes: boolean
  depassement_assume: boolean
}

/** `ligneIds` vide ou absent : toute la réquisition suit. */
export const apercuReimputation = (requisitionId: string, budgetPosteId: number, ligneIds?: string[]) =>
  apiRequest<ApercuReimputation>('GET', `/requisitions/${requisitionId}/reimputation`, {
    params: {
      budget_poste_id: budgetPosteId,
      ...(ligneIds?.length ? { ligne_ids: ligneIds } : {}),
    },
  })

export const reimputerRequisition = (
  requisitionId: string,
  payload: { budget_poste_id: number; motif: string; forcer?: boolean; ligne_ids?: string[] },
) => apiRequest<ResultatReimputation>('POST', `/requisitions/${requisitionId}/reimputation`, payload)
