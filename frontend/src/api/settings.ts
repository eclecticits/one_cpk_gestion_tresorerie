import { apiRequest } from '../lib/apiClient'

export interface PrintSettings {
  id: string
  organization_name: string
  organization_subtitle: string
  header_text: string
  address: string
  phone: string
  email: string
  website: string
  bank_name: string
  bank_account: string
  mobile_money_name: string
  mobile_money_number: string
  footer_text: string
  show_header_logo: boolean
  show_footer_signature: boolean
  logo_url: string
  stamp_url: string
  signature_name: string
  signature_title: string
  paper_format: string
  compact_header: boolean
  updated_by?: string
  updated_at: string
}

export type PrintSettingsUpdate = Omit<PrintSettings, 'id' | 'updated_by' | 'updated_at'>

// Récupérer les paramètres d'impression
export async function getPrintSettings(): Promise<PrintSettings> {
  return apiRequest<PrintSettings>('GET', '/print-settings')
}
