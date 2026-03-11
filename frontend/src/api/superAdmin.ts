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

export interface PlatformSummary {
  total_volume_usd: number
  total_transactions: number
  active_tenants: number
  total_tenants: number
  webhook_success_rate: number
  api_errors: number
}

export interface TenantMetric {
  org_id: number
  org_nom: string
  slug: string
  plan_type: string
  status_abonnement: string
  date_expiration_abonnement?: string | null
  total_users: number
  volume_encaisse_30j: number
  echecs_paiement_24h: number
  derniere_activite?: string | null
}

export interface ExpiringOrg {
  id: number
  nom: string
  slug: string
  plan_type: string
  status_abonnement: string
  date_expiration_abonnement?: string | null
}

export interface OrgUserLite {
  id: string
  email: string
  nom?: string | null
  prenom?: string | null
  role?: string | null
  active?: boolean
}

export interface SystemEventItem {
  id: string
  organisation_id?: number | null
  level: string
  code: string
  message: string
  metadata?: Record<string, any> | null
  created_at?: string | null
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

export async function getPlatformSummary(): Promise<PlatformSummary> {
  return apiRequest<PlatformSummary>('GET', '/super-admin/monitoring/summary')
}

export async function getTenantMetrics(): Promise<{ metrics: TenantMetric[]; expiring: ExpiringOrg[] }> {
  return apiRequest('GET', '/super-admin/monitoring/tenants')
}

export async function refreshMetrics(): Promise<{ ok: boolean; alerts_sent?: number }> {
  return apiRequest('POST', '/super-admin/monitoring/refresh')
}

export async function listOrgUsers(orgId: number): Promise<{ users: OrgUserLite[] }> {
  return apiRequest('GET', `/super-admin/organisations/${orgId}/users`)
}

export async function impersonateUser(userId: string): Promise<{ access_token: string; expires_in: number }> {
  return apiRequest('POST', `/super-admin/impersonate/${userId}`)
}

export async function getMonitoringEvents(limit = 50): Promise<{ events: SystemEventItem[] }> {
  return apiRequest('GET', `/super-admin/monitoring/events?limit=${limit}`)
}

export async function runMonthlyReport(month: number, year: number): Promise<{ ok: boolean; path?: string }> {
  return apiRequest('POST', `/super-admin/reporting/monthly`, { params: { month, year } } as any)
}

export async function getMonthlyReportStatus(): Promise<any> {
  return apiRequest('GET', '/super-admin/reporting/monthly-status')
}
