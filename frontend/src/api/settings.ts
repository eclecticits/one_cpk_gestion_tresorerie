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
  pied_de_page_legal: string
  afficher_qr_code: boolean
  show_header_logo: boolean
  show_footer_signature: boolean
  logo_url: string
  stamp_url: string
  recu_label_signature: string
  recu_nom_signataire: string
  paper_format: string
  compact_header: boolean
  req_titre_officiel: string
  req_label_gauche: string
  req_nom_gauche: string
  req_label_droite: string
  req_nom_droite: string
  trans_titre_officiel: string
  trans_label_gauche: string
  trans_nom_gauche: string
  trans_label_droite: string
  trans_nom_droite: string
  default_currency: string
  secondary_currency: string
  exchange_rate: number
  fiscal_year: number
  budget_alert_threshold: number
  budget_block_overrun: boolean
  budget_force_roles: string
  updated_by?: string
  updated_at: string
}

export type PrintSettingsUpdate = Omit<PrintSettings, 'id' | 'updated_by' | 'updated_at'>

// Récupérer les paramètres d'impression
export async function getPrintSettings(): Promise<PrintSettings> {
  return apiRequest<PrintSettings>('GET', '/print-settings')
}
