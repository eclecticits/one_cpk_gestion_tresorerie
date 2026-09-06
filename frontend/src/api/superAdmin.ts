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

export interface MonitoringAnomaly {
  type: string
  organisation_id: number
  count: number
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

// ── Configuration par module ──────────────────────────────────────────────────

export interface TresorerieModuleConfig {
  enabled: boolean
  requisitions: boolean
  payments: boolean
  exports: boolean
  budget_tracking: boolean
  reconciliation: boolean
}

export interface RHModuleConfig {
  enabled: boolean
  max_employees: number        // 0 = illimité
  leave_management: boolean
  contract_tracking: boolean
  payroll: boolean
  recruitment: boolean
  performance_reviews: boolean
  training: boolean
}

export interface SecretariatModuleConfig {
  enabled: boolean
  documents: boolean
  meetings: boolean
  agenda: boolean
  ai_mail: boolean
  approvals: boolean
  max_documents: number        // 0 = illimité
  max_meetings_per_month: number  // 0 = illimité
}

export interface ComptabiliteModuleConfig {
  enabled: boolean
}

export interface ModulesConfig {
  tresorerie?: TresorerieModuleConfig
  rh?: RHModuleConfig
  secretariat?: SecretariatModuleConfig
  comptabilite?: ComptabiliteModuleConfig
}

// ── Settings complets de l'organisation ──────────────────────────────────────

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
  modules_config: ModulesConfig | null
}

export interface BillingConfig {
  plan?: {
    name?: string | null
    price?: number | null
    currency?: string | null
    interval?: string | null
  } | null
  payment_methods?: {
    bank?: {
      enabled?: boolean
      bank_name?: string | null
      account_name?: string | null
      account_number?: string | null
      swift_code?: string | null
    } | null
    mobile_money?: {
      enabled?: boolean
      provider?: string | null
      merchant_number?: string | null
      instructions?: string | null
    } | null
  } | null
  // Identifiants de l'agregateur de paiement (Visa + Mobile Money).
  // Le backend masque les secrets au GET : `api_key` n'est jamais renvoyee,
  // seul `api_key_set` indique qu'une valeur est enregistree.
  platform_payments?: {
    epaielink?: {
      site_id?: string | null
      api_key?: string | null
      api_key_set?: boolean
      notify_url?: string | null
      return_url?: string | null
    } | null
  } | null
  support_contact?: string | null
  billing_portal_url?: string | null
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

export async function getBillingConfig(orgId: number): Promise<BillingConfig> {
  return apiRequest('GET', `/super-admin/organisations/${orgId}/billing-config`)
}

export async function updateBillingConfig(orgId: number, payload: BillingConfig): Promise<BillingConfig> {
  return apiRequest('PUT', `/super-admin/organisations/${orgId}/billing-config`, payload)
}

export async function resetBillingConfig(orgId: number): Promise<{ ok: boolean }> {
  return apiRequest('POST', `/super-admin/organisations/${orgId}/billing-config/reset`)
}

export async function listBankProofs(limit = 50, tenantId?: string): Promise<{ items: any[] }> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (tenantId) params.set('tenant_id', tenantId)
  return apiRequest('GET', `/super-admin/payments/bank-proofs?${params.toString()}`)
}

export async function approveBankProof(transactionId: string): Promise<{ ok: boolean }> {
  return apiRequest('POST', `/super-admin/payments/bank-proofs/${transactionId}/approve`)
}

export async function rejectBankProof(transactionId: string): Promise<{ ok: boolean }> {
  return apiRequest('POST', `/super-admin/payments/bank-proofs/${transactionId}/reject`)
}

export async function listOrgPayments(orgId: number, limit = 50): Promise<{ items: any[] }> {
  return apiRequest('GET', `/super-admin/organisations/${orgId}/payments?limit=${limit}`)
}

export async function getGlobalBillingConfig(): Promise<BillingConfig> {
  return apiRequest('GET', '/super-admin/billing-config')
}

export async function updateGlobalBillingConfig(payload: BillingConfig): Promise<BillingConfig> {
  return apiRequest('PUT', '/super-admin/billing-config', payload)
}

export async function applyGlobalBillingConfig(overwrite = false): Promise<{ applied: number; overwrite: boolean }> {
  return apiRequest('POST', '/super-admin/billing-config/apply-to-all', { overwrite })
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

export async function getTenantMetrics(): Promise<{
  metrics: TenantMetric[]
  expiring: ExpiringOrg[]
  anomalies: MonitoringAnomaly[]
}> {
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

export interface GrantTrialRequest {
  plan_type: string
  duration_days: number
}

export interface GrantTrialResponse {
  ok: boolean
  organisation_id: number
  plan_type: string
  status_abonnement: string
  expires_at: string
  duration_days: number
}

export async function grantTrial(orgId: number, payload: GrantTrialRequest): Promise<GrantTrialResponse> {
  return apiRequest('POST', `/super-admin/organisations/${orgId}/grant-trial`, payload)
}

// ── Google OAuth platform settings ───────────────────────────────────────────

export interface GoogleOAuthSettingsOut {
  google_client_id: string | null
  google_oauth_redirect_uri: string | null
  google_oauth_redirect_uri_enabled: boolean
  google_oauth_redirect_uri_local: string | null
  google_oauth_redirect_uri_local_enabled: boolean
  google_client_secret_configured: boolean
  source: 'database' | 'environment' | 'none'
}

export interface GoogleOAuthSettingsUpdate {
  google_client_id?: string | null
  google_client_secret?: string | null
  google_oauth_redirect_uri?: string | null
  google_oauth_redirect_uri_enabled?: boolean | null
  google_oauth_redirect_uri_local?: string | null
  google_oauth_redirect_uri_local_enabled?: boolean | null
}

export async function getGoogleOAuthSettings(): Promise<GoogleOAuthSettingsOut> {
  return apiRequest('GET', '/super-admin/platform/google-oauth')
}

export async function updateGoogleOAuthSettings(payload: GoogleOAuthSettingsUpdate): Promise<GoogleOAuthSettingsOut> {
  return apiRequest('PUT', '/super-admin/platform/google-oauth', payload)
}

// ── Facturation émise aux tenants ───────────────────────────────────────────

export interface InvoiceIssuer {
  name: string
  tagline: string
  address: string
  city: string
  country: string
  email: string
  phone: string
  website: string
  rccm: string
  id_nat: string
  tax_id: string
  bank_name: string
  bank_account: string
  bank_swift: string
  mobile_money: string
  payment_terms_days: number
  /** Voies de règlement annoncées sur le PDF. Décocher n'est qu'un choix
   *  d'affichage : un règlement manuel reste constatable dans tous les cas. */
  online_payment_enabled: boolean
  manual_payment_enabled: boolean
  invoice_prefix: string
  footer_note: string
}

export interface InvoiceLine {
  designation: string
  quantite: number
  prix_unitaire: number
  montant?: number
}

export type InvoiceStatus = 'DRAFT' | 'ISSUED' | 'PAID' | 'CANCELLED'

export interface SaaSInvoice {
  id: string
  invoice_number: string
  organisation_id: number
  organisation_name?: string | null
  organisation_slug?: string | null
  status: InvoiceStatus
  amount: number
  currency: string
  issue_date?: string | null
  due_date?: string | null
  paid_at?: string | null
  period_start?: string | null
  period_end?: string | null
  payment_method?: string | null
  payment_method_label?: string | null
  payment_reference?: string | null
  lines: Required<InvoiceLine>[]
  notes?: string | null
  cancel_reason?: string | null
  sent_at?: string | null
  recipient_email?: string | null
  has_pdf: boolean
  is_overdue: boolean
}

export interface InvoiceListResult {
  items: SaaSInvoice[]
  total: number
  totals_by_status: Record<string, number>
}

export interface InvoiceCreatePayload {
  organisation_id: number
  lines: InvoiceLine[]
  currency?: string
  period_start?: string | null
  period_end?: string | null
  due_date?: string | null
  notes?: string | null
  issue?: boolean
  send_email?: boolean
}

export async function getInvoiceIssuer(): Promise<InvoiceIssuer> {
  return apiRequest('GET', '/super-admin/billing/issuer')
}

export async function updateInvoiceIssuer(payload: Partial<InvoiceIssuer>): Promise<InvoiceIssuer> {
  return apiRequest('PUT', '/super-admin/billing/issuer', payload)
}

/** Un plan de la grille tarifaire de l'application. */
export interface BillingPlan {
  /** Clé du plan : c'est ce que porte `plan_type` d'une organisation. */
  code: string
  name: string
  description: string
  /** Montant en texte : un flottant perdrait des centimes en chemin. */
  price: string
  currency: 'USD' | 'CDF' | string
  interval: 'monthly' | 'quarterly' | 'semiannual' | 'yearly' | string
  active: boolean
}

export interface EditorLogo {
  present: boolean
  filename: string
  content_type: string
  size: number
  uploaded_at: string
  /** Couleur imprimée sur les factures, en hexadécimal (vide si le logo n'en porte pas). */
  accent: string
  /** Celle lue dans le logo : sert à revenir en arrière après un réglage manuel. */
  accent_detecte: string
}

export async function listBillingPlans(): Promise<BillingPlan[]> {
  return apiRequest('GET', '/super-admin/billing/plans')
}

/** Le catalogue s'enregistre en bloc : on édite un tableau, on le sauve. */
export async function updateBillingPlans(plans: BillingPlan[]): Promise<BillingPlan[]> {
  return apiRequest('PUT', '/super-admin/billing/plans', { plans })
}

/** Le fichier part en multipart : apiClient laisse passer un FormData tel quel. */
export async function uploadEditorLogo(file: File): Promise<EditorLogo> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest('POST', '/super-admin/branding/logo', form)
}

export async function getEditorLogo(): Promise<EditorLogo> {
  return apiRequest('GET', '/super-admin/branding/logo')
}

export async function deleteEditorLogo(): Promise<EditorLogo> {
  return apiRequest('DELETE', '/super-admin/branding/logo')
}

/** Corrige la couleur tirée du logo ; une chaîne vide rétablit celle-ci. */
export async function updateEditorAccent(accent: string): Promise<EditorLogo> {
  return apiRequest('PUT', '/super-admin/branding/accent', { accent })
}

export async function listSaasInvoices(filters: {
  organisationId?: number | null
  status?: string | null
  search?: string | null
  limit?: number
} = {}): Promise<InvoiceListResult> {
  const params = new URLSearchParams()
  if (filters.organisationId) params.set('organisation_id', String(filters.organisationId))
  if (filters.status) params.set('invoice_status', filters.status)
  if (filters.search) params.set('search', filters.search)
  params.set('limit', String(filters.limit ?? 100))
  return apiRequest('GET', `/super-admin/invoices?${params.toString()}`)
}

export async function createSaasInvoice(payload: InvoiceCreatePayload): Promise<SaaSInvoice> {
  return apiRequest('POST', '/super-admin/invoices', payload)
}

export async function markSaasInvoicePaid(
  invoiceId: string,
  payload: { method: string; reference?: string | null; paid_at?: string | null },
): Promise<SaaSInvoice> {
  return apiRequest('POST', `/super-admin/invoices/${invoiceId}/mark-paid`, payload)
}

export async function cancelSaasInvoice(invoiceId: string, reason?: string): Promise<SaaSInvoice> {
  return apiRequest('POST', `/super-admin/invoices/${invoiceId}/cancel`, { reason: reason || null })
}

export async function sendSaasInvoice(
  invoiceId: string,
): Promise<{ ok: boolean; sent_to: string[]; detail?: string | null }> {
  return apiRequest('POST', `/super-admin/invoices/${invoiceId}/send`)
}

export function saasInvoicePdfPath(invoiceId: string): string {
  return `/super-admin/invoices/${invoiceId}/pdf`
}
