import { apiRequest } from '../lib/apiClient'
import type {
  ComptaCompte,
  ComptaEcriture,
  ComptaEcritureCreateInput,
  ComptaEcritureListResponse,
  ComptaEcrituresListParams,
  ComptaExercice,
  ComptaJournal,
  ComptaSetupInput,
  ComptaSetupResult,
  ComptaStatut,
} from '../types/comptabilite'

export async function getComptaStatut(): Promise<ComptaStatut> {
  return apiRequest<ComptaStatut>('GET', '/comptabilite/statut')
}

export async function setupComptabilite(input: ComptaSetupInput): Promise<ComptaSetupResult> {
  return apiRequest<ComptaSetupResult>('POST', '/comptabilite/setup', input)
}

export async function getComptaComptes(): Promise<ComptaCompte[]> {
  return apiRequest<ComptaCompte[]>('GET', '/comptabilite/comptes')
}

export async function getComptaJournaux(): Promise<ComptaJournal[]> {
  return apiRequest<ComptaJournal[]>('GET', '/comptabilite/journaux')
}

export async function getComptaExercices(): Promise<ComptaExercice[]> {
  return apiRequest<ComptaExercice[]>('GET', '/comptabilite/exercices')
}

export async function getComptaEcritures(
  params?: ComptaEcrituresListParams
): Promise<ComptaEcritureListResponse> {
  return apiRequest<ComptaEcritureListResponse>('GET', '/comptabilite/ecritures', { params })
}

export async function getComptaEcriture(id: string): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('GET', `/comptabilite/ecritures/${id}`)
}

export async function createComptaEcriture(
  input: ComptaEcritureCreateInput
): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', '/comptabilite/ecritures', input)
}

export async function validerComptaEcriture(id: string): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', `/comptabilite/ecritures/${id}/valider`)
}

export async function contrepasserComptaEcriture(
  id: string,
  motif: string
): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', `/comptabilite/ecritures/${id}/contrepasser`, { motif })
}
