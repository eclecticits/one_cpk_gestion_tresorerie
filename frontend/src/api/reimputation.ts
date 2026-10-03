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

/** Ce qu'une ré-imputation d'encaissement déplacerait, avant de la décider. */
export interface ApercuReimputationEncaissement {
  postes_avant: number[]
  nouveau_poste_id: number
  /** Lignes qui partent, sur le total que porte la note. */
  lignes: number
  lignes_total: number
  /** Versements dont une part du réalisé change de poste. */
  versements: number
  imputations: number
  montant_paye_deplace: string | number
  /** Écritures comptables au brouillon dont le compte de produit sera refait. */
  ecritures_reecrites: number
}

export interface ResultatReimputationEncaissement {
  postes_avant: number[]
  nouveau_poste_id: number
  nouveau_poste_code: string
  lignes_deplacees: number
  lignes_total: number
  versements_deplaces: number
  imputations_deplacees: number
  montant_paye_deplace: string | number
  ecritures_reecrites: number
}

/** `articleIds` vide ou absent : toute la note suit. */
export const apercuReimputationEncaissement = (encaissementId: string, budgetPosteId: number, articleIds?: string[]) =>
  apiRequest<ApercuReimputationEncaissement>('GET', `/encaissements/${encaissementId}/reimputation`, {
    params: {
      budget_poste_id: budgetPosteId,
      ...(articleIds?.length ? { article_ids: articleIds } : {}),
    },
  })

export const reimputerEncaissement = (
  encaissementId: string,
  payload: { budget_poste_id: number; motif: string; article_ids?: string[] },
) => apiRequest<ResultatReimputationEncaissement>('POST', `/encaissements/${encaissementId}/reimputation`, payload)
