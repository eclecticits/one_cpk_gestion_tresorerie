import { apiRequest } from '../lib/apiClient'
import type { Banque, CompteBancaire } from '../types/banque'

export async function listBanques(active?: boolean): Promise<Banque[]> {
  const params: any = {}
  if (active !== undefined) params.active = active
  return apiRequest<Banque[]>('GET', '/banques', { params })
}

export async function createBanque(payload: { nom: string; code?: string | null; is_active?: boolean }): Promise<Banque> {
  return apiRequest<Banque>('POST', '/banques', payload)
}

export async function updateBanque(
  banqueId: number,
  payload: { nom?: string | null; code?: string | null; is_active?: boolean | null }
): Promise<Banque> {
  return apiRequest<Banque>('PATCH', `/banques/${banqueId}`, payload)
}

export async function deleteBanque(banqueId: number): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('DELETE', `/banques/${banqueId}`)
}

export async function listComptesBancaires(params?: {
  active?: boolean
  banque_id?: number
  devise?: string
}): Promise<CompteBancaire[]> {
  return apiRequest<CompteBancaire[]>('GET', '/comptes-bancaires', { params })
}

export async function createCompteBancaire(payload: {
  banque_id: number
  intitule: string
  numero_compte: string
  devise: string
  solde_initial?: number
  solde_actuel?: number
  is_active?: boolean
}): Promise<CompteBancaire> {
  return apiRequest<CompteBancaire>('POST', '/comptes-bancaires', payload)
}

export async function updateCompteBancaire(
  compteId: number,
  payload: {
    banque_id?: number
    intitule?: string
    numero_compte?: string
    devise?: string
    solde_initial?: number
    solde_actuel?: number
    is_active?: boolean
  }
): Promise<CompteBancaire> {
  return apiRequest<CompteBancaire>('PATCH', `/comptes-bancaires/${compteId}`, payload)
}

export async function deleteCompteBancaire(compteId: number): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('DELETE', `/comptes-bancaires/${compteId}`)
}
