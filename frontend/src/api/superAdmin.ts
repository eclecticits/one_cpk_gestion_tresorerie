import { apiRequest } from '../lib/apiClient'

export interface SuperAdminOrganisation {
  id: number
  uuid: string
  nom: string
  slug: string
  plan_type: string
  status_abonnement: string
  date_expiration_abonnement?: string | null
  limite_utilisateurs: number
  is_active: boolean
  user_count: number
  created_at: string
}

export interface SuperAdminOrganisationCreate {
  nom: string
  slug: string
  plan_type?: string | null
  status_abonnement?: string | null
  trial_days?: number | null
  limite_utilisateurs?: number | null
  admin_email: string
  admin_password: string
}

export interface SuperAdminOrganisationUpdate {
  plan_type?: string | null
  status_abonnement?: string | null
  date_expiration_abonnement?: string | null
  limite_utilisateurs?: number | null
  is_active?: boolean | null
}

export async function listOrganisations(): Promise<SuperAdminOrganisation[]> {
  return apiRequest<SuperAdminOrganisation[]>('GET', '/super-admin/organisations')
}

export async function createOrganisation(payload: SuperAdminOrganisationCreate): Promise<SuperAdminOrganisation> {
  return apiRequest<SuperAdminOrganisation>('POST', '/super-admin/organisations', payload)
}

export async function updateOrganisation(
  id: number,
  payload: SuperAdminOrganisationUpdate,
): Promise<SuperAdminOrganisation> {
  return apiRequest<SuperAdminOrganisation>('PATCH', `/super-admin/organisations/${id}`, payload)
}
