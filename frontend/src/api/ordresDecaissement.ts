import { apiRequest } from '../lib/apiClient'
import type { OrdreDecaissement } from '../types'

export interface OrdresDecaissementListResponse {
  items: OrdreDecaissement[]
  total: number
  montant_total_requisition?: number | string | null
  total_paye: number | string
  total_autorise_non_paye: number | string
  reliquat?: number | string | null
}

export async function listOrdresDecaissement(params: {
  requisition_id?: string
  sans_requisition?: boolean
  statut?: 'AUTORISE' | 'PAYE' | 'ANNULE'
  limit?: number
  offset?: number
}): Promise<OrdresDecaissementListResponse> {
  return apiRequest('GET', '/ordres-decaissement', { params })
}

export interface OrdreDirectLigne {
  budget_poste_id: number | null
  rubrique: string
  description: string
  montant_total: number
  devise: 'USD' | 'CDF'
}

export async function createOrdreDecaissement(input: {
  /** Omis = ordre de sortie directe (sans réquisition, plafond 100 USD) */
  requisition_id?: string | null
  beneficiaire: string
  montant: number
  devise?: 'USD' | 'CDF'
  motif?: string | null
  /** Sortie directe « type réquisition » : service + lignes budgétaires. */
  service_id?: number | null
  lignes?: OrdreDirectLigne[] | null
}): Promise<OrdreDecaissement> {
  return apiRequest('POST', '/ordres-decaissement', input)
}

export async function annulerOrdreDecaissement(
  ordreId: string,
  motif_annulation: string
): Promise<OrdreDecaissement> {
  return apiRequest('POST', `/ordres-decaissement/${ordreId}/annuler`, { motif_annulation })
}
