import { apiRequest } from '../lib/apiClient'
import { TypeClient } from '../types'

export interface Client {
  id: string
  nom: string
  type_client: TypeClient | null
  email: string | null
  telephone: string | null
  /** 'M', 'F', ou rien : renseigné pour les personnes physiques et clients externes. */
  sexe: string | null
  adresse: string | null
  notes: string | null
  active: boolean
  nb_encaissements: number | null
  dernier_encaissement: string | null
  created_at: string
}

export interface ClientUpdatePayload {
  nom?: string
  type_client?: TypeClient | null
  email?: string | null
  telephone?: string | null
  sexe?: string | null
  adresse?: string | null
  notes?: string | null
  active?: boolean
}

export interface ListClientsParams {
  search?: string
  /** true = actifs, false = bloqués, undefined = tous. */
  active?: boolean
  limit?: number
  offset?: number
}

export async function listClients(params: ListClientsParams = {}): Promise<Client[]> {
  const query: Record<string, unknown> = { limit: params.limit ?? 100, offset: params.offset ?? 0 }
  if (params.search && params.search.trim()) query.search = params.search.trim()
  if (params.active !== undefined) query.active = params.active
  return apiRequest<Client[]>('GET', '/clients', { params: query })
}

export async function updateClient(id: string, body: ClientUpdatePayload): Promise<Client> {
  return apiRequest<Client>('PUT', `/clients/${id}`, { body })
}

export async function deleteClient(id: string): Promise<void> {
  await apiRequest<void>('DELETE', `/clients/${id}`)
}
