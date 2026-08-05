import { apiRequest } from '../lib/apiClient'

export type ProjetActiviteType = 'PROJET' | 'ACTIVITE'

export interface ProjetActivite {
  id: number
  organisation_id: number
  code: string
  libelle: string
  type: ProjetActiviteType
  description?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export function listProjetsActivites(active?: boolean): Promise<ProjetActivite[]> {
  return apiRequest<ProjetActivite[]>('GET', '/projets-activites', {
    params: active === undefined ? undefined : { active },
  })
}

export function createProjetActivite(payload: Omit<ProjetActivite, 'id' | 'organisation_id' | 'created_at' | 'updated_at'>) {
  return apiRequest<ProjetActivite>('POST', '/projets-activites', payload)
}

export function updateProjetActivite(id: number, payload: Partial<Omit<ProjetActivite, 'id' | 'organisation_id' | 'created_at' | 'updated_at'>>) {
  return apiRequest<ProjetActivite>('PATCH', `/projets-activites/${id}`, { ...payload })
}
