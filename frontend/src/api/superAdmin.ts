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

export interface SuperAdminReservationCreate {
  nom: string
  slug: string
  admin_email: string
  admin_phone?: string | null
  plan_id: number
  max_users?: number
  storage_quota_mb?: number
  is_ai_enabled?: boolean
  is_mobile_money_enabled?: boolean
  is_audit_logs_enabled?: boolean
  fiscal_year_start?: number
  currency_code?: string
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

export interface OrganisationSettings {
  organisation_id: number
  max_users: number
  storage_quota_mb: number
  is_ai_enabled: boolean
  is_mobile_money_enabled: boolean
  is_audit_logs_enabled: boolean
  fiscal_year_start: number
  currency_code: string
  theme_primary_color: string
  theme_sidebar_color: string
  theme_sidebar_text_color: string
  theme_sidebar_active_color: string
  theme_accent_color: string
  theme_text_color: string
  theme_button_text_color: string
}

export interface SimulatePaymentPayload {
  admin_email?: string
  billing_months?: number
}

export interface SimulatePaymentResponse {
  ok: boolean
  organisation_id: number
  admin_email: string
  reference: string
  temp_password?: string
}

export interface GlobalStat {
  id: number
  name: string
  slug: string
  balance: number
  usage: number
  is_active: boolean
}

export interface TreasuryStat {
  organisation_id: number
  organisation_name: string
  organisation_slug: string
  total_encaisse: number
  success_tx: number
}

export async function listOrganisations(): Promise<SuperAdminOrganisation[]> {
  return apiRequest<SuperAdminOrganisation[]>('GET', '/super-admin/organisations')
}

export async function createOrganisation(payload: SuperAdminOrganisationCreate): Promise<SuperAdminOrganisation> {
  return apiRequest<SuperAdminOrganisation>('POST', '/super-admin/organisations', payload)
}

export async function reserveOrganisation(payload: SuperAdminReservationCreate): Promise<SuperAdminOrganisation> {
  return apiRequest<SuperAdminOrganisation>('POST', '/super-admin/organisations/reserve', payload)
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

export async function getTreasuryStats(): Promise<{ items: TreasuryStat[] }> {
  return apiRequest('GET', '/super-admin/monitoring/treasury')
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

export async function getGlobalStats(): Promise<GlobalStat[]> {
  return apiRequest('GET', '/super-admin/global-stats')
}

export async function getOrganisationSettings(orgId: number): Promise<OrganisationSettings> {
  return apiRequest('GET', `/super-admin/organisations/${orgId}/settings`)
}

export async function updateOrganisationSettings(
  orgId: number,
  payload: Partial<OrganisationSettings>
): Promise<OrganisationSettings> {
  return apiRequest('PUT', `/super-admin/organisations/${orgId}/settings`, payload)
}

export async function simulatePayment(
  orgId: number,
  payload: SimulatePaymentPayload
): Promise<SimulatePaymentResponse> {
  return apiRequest('POST', `/super-admin/organisations/${orgId}/simulate-payment`, payload)
}
