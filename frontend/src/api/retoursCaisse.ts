// ─────────────────────────────────────────────────────────────────────────────
// API — Retours en caisse (remboursement après une sortie de fonds)
//
// Miroir côté front des endpoints `/retours-caisse` : reliquat d'une avance à
// valoir, correction d'une sortie erronée, ou trop-perçu rendu.
// ─────────────────────────────────────────────────────────────────────────────

import { apiRequest } from '../lib/apiClient'

export type TypeRetourCaisse = 'reliquat_avance' | 'correction' | 'trop_percu'

export interface RetourCaisse {
  id: string
  organisation_id: number
  sortie_fonds_id: string
  requisition_id?: string | null
  type_retour: TypeRetourCaisse
  budget_poste_id?: number | null
  budget_poste_code?: string | null
  budget_poste_libelle?: string | null
  ajuste_budget: boolean
  service_id?: number | null
  montant: number | string
  devise: 'USD' | 'CDF'
  canal: 'CAISSE' | 'BANQUE'
  compte_bancaire_id?: number | null
  mode: string
  reference?: string | null
  reference_numero?: string | null
  motif?: string | null
  commentaire?: string | null
  statut: string
  statut_comptabilisation: string
  message_comptabilisation?: string | null
  date_retour: string
  created_at: string
}

export interface RetoursCaisseSummary {
  items: RetourCaisse[]
  total: number
  total_montant: number | string
  // Renseignés uniquement quand la liste est filtrée sur une sortie de fonds.
  sortie_montant_paye?: number | string | null
  total_retourne?: number | string | null
  reste_a_justifier?: number | string | null
}

export interface RetourCaisseCreatePayload {
  sortie_fonds_id: string
  montant: number
  type_retour?: TypeRetourCaisse
  devise?: 'USD' | 'CDF'
  canal?: 'CAISSE' | 'BANQUE'
  compte_bancaire_id?: number | null
  budget_poste_id?: number | null
  ajuste_budget?: boolean
  mode?: string
  reference?: string | null
  motif?: string | null
  commentaire?: string | null
  date_retour?: string | null
}

/** Liste les retours d'une sortie et renvoie le résumé (reste à justifier). */
export async function listRetoursForSortie(sortieFondsId: string): Promise<RetoursCaisseSummary> {
  return apiRequest<RetoursCaisseSummary>('GET', '/retours-caisse', {
    params: { sortie_fonds_id: sortieFondsId, include_summary: true },
  })
}

/** Enregistre un retour en caisse. */
export async function createRetourCaisse(payload: RetourCaisseCreatePayload): Promise<RetourCaisse> {
  return apiRequest<RetourCaisse>('POST', '/retours-caisse', payload)
}

/** Annule un retour (fenêtre de 30 min ; rétablit trésorerie + budget + compta). */
export async function cancelRetourCaisse(id: string, motifAnnulation?: string): Promise<RetourCaisse> {
  return apiRequest<RetourCaisse>('PATCH', `/retours-caisse/${id}/statut`, {
    statut: 'ANNULEE',
    motif_annulation: motifAnnulation,
  })
}
