import { apiRequest } from '../lib/apiClient'

export type Denomination = {
  id: number
  devise: string
  valeur: number
  label: string
  est_actif: boolean
  ordre: number
}

export type DenominationCreate = {
  devise: string
  valeur: number
  label: string
  est_actif: boolean
  ordre: number
}

export type DenominationUpdate = Partial<DenominationCreate>

export async function listDenominations(params?: { active?: boolean; devise?: string }): Promise<Denomination[]> {
  return apiRequest('GET', '/denominations', { params })
}

export async function createDenomination(payload: DenominationCreate): Promise<Denomination> {
  return apiRequest('POST', '/denominations', { body: payload })
}

export async function updateDenomination(id: number, payload: DenominationUpdate): Promise<Denomination> {
  return apiRequest('PATCH', `/denominations/${id}`, { body: payload })
}

export async function deleteDenomination(id: number): Promise<{ ok: boolean }> {
  return apiRequest('DELETE', `/denominations/${id}`)
}
