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
  theme_accent_color: string
  theme_text_color: string
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

export async function getOrganisationSettings(): Promise<OrganisationSettings> {
  return apiRequest('GET', '/organisation/settings')
}

export async function updateOrganisationSettings(
  payload: Partial<
    Pick<
      OrganisationSettings,
      'theme_primary_color' | 'theme_sidebar_color' | 'theme_accent_color' | 'theme_text_color'
    >
  >
): Promise<OrganisationSettings> {
  return apiRequest('PATCH', '/organisation/settings', payload)
}
