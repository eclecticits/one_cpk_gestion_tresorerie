import { apiRequest } from '../lib/apiClient'

export type Organisation = {
  id: number
  uuid: string
  nom: string
  slug: string
  logo_url?: string | null
  email_contact?: string | null
  telephone?: string | null
  adresse?: string | null
  devise_preferee: string
  taux_change_interne: number
  plan_type: string
  status_abonnement: string
  date_expiration_abonnement?: string | null
  limite_utilisateurs: number
}

export type OrganisationUpdate = Partial<{
  nom: string
  logo_url: string | null
  email_contact: string | null
  telephone: string | null
  adresse: string | null
  devise_preferee: string | null
  taux_change_interne: number | null
}>

export type OrganisationPublicInfo = {
  nom: string
  slug: string
  logo_url?: string | null
  icon?: string | null
  sort_order?: number | null
}

export type OrganisationOption = {
  id: number
  uuid?: string | null
  nom: string
  slug: string
  icon?: string | null
  sort_order?: number | null
}

export type OrganisationSettings = {
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
  accounting_integration_mode: 'disabled' | 'manual' | 'automatic'
  /** Bornes d'une collation de réunion en sortie directe. Le prix par tête dit
   *  que c'en est bien une ; le total dit qu'elle reste une sortie directe. */
  collation_plafond_par_personne_usd: number | string
  /** Ce qu'une réunion peut coûter. */
  collation_plafond_total_usd: number | string
  /** Ce qu'une JOURNÉE peut coûter, toutes réunions confondues : sans cette
   *  borne, il suffirait d'aligner les réunions pour vider la caisse par
   *  petites salles successives, chacune dans les clous. */
  collation_plafond_24h_usd: number | string
  modules_config: Record<string, { enabled?: boolean }> | null
  workflow_config: WorkflowConfig | null
}

export type WorkflowStepKey =
  | 'signature_service'
  | 'examen'
  | 'validation_1'
  | 'validation_2'

export type WorkflowStep = {
  enabled: boolean
  seuil_montant?: number
}

export type WorkflowConfig = {
  preset: string
  steps: Record<WorkflowStepKey, WorkflowStep>
}

export async function getOrganisation(): Promise<Organisation> {
  return apiRequest('GET', '/organisation')
}

export async function updateOrganisation(payload: OrganisationUpdate): Promise<Organisation> {
  return apiRequest('PUT', '/organisation', payload)
}

export async function getOrganisationPublic(slug: string): Promise<OrganisationPublicInfo> {
  return apiRequest('GET', `/organisation/public/${slug}`)
}

export async function listPublicOrganisations(): Promise<OrganisationPublicInfo[]> {
  return apiRequest('GET', '/organisation/public')
}

export async function listOrganisationOptions(params?: {
  q?: string
  limit?: number
}): Promise<OrganisationOption[]> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.limit) search.set('limit', String(params.limit))
  const qs = search.toString()
  return apiRequest('GET', `/organisation/options${qs ? `?${qs}` : ''}`)
}

export async function getOrganisationSettings(): Promise<OrganisationSettings> {
  return apiRequest('GET', '/organisation/settings')
}

export async function updateOrganisationSettings(
  payload: Partial<
    Pick<
      OrganisationSettings,
      | 'currency_code'
      | 'theme_primary_color'
      | 'theme_sidebar_color'
      | 'theme_sidebar_text_color'
      | 'theme_sidebar_active_color'
      | 'theme_accent_color'
      | 'theme_text_color'
      | 'theme_button_text_color'
      | 'accounting_integration_mode'
      | 'collation_plafond_par_personne_usd'
      | 'collation_plafond_total_usd'
      | 'collation_plafond_24h_usd'
    >
  > & { accounting_integration_change_motif?: string | null }
): Promise<OrganisationSettings> {
  return apiRequest('PATCH', '/organisation/settings', payload)
}

export async function updateWorkflowConfig(
  workflow_config: WorkflowConfig
): Promise<OrganisationSettings> {
  return apiRequest('PATCH', '/organisation/settings/workflow', { workflow_config })
}
