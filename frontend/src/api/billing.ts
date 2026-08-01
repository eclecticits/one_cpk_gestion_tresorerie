import { API_BASE_URL, getAuthHeaders, apiRequest } from '../lib/apiClient'

export type BillingSummary = {
  plan_type: string | null
  plan_status: string | null
  plan_expires_at: string | null
  renewal_date: string | null
  currency: string | null
  plan_price: number | null
  billing_source: string
  billing_portal_url: string | null
}

export type BillingInvoice = {
  id: string
  number: string | null
  date: string | null
  amount: number | null
  currency: string | null
  status: string | null
  pdf_available: boolean
}

export type BillingInvoiceList = {
  items: BillingInvoice[]
  source: string
  configured: boolean
}

export type BillingPaymentMethod = {
  id: string
  label: string
  method_type: string | null
  last4: string | null
  status: string | null
  is_default: boolean
}

export type BillingPaymentMethodList = {
  items: BillingPaymentMethod[]
  source: string
  configured: boolean
}

export type BillingStatus = {
  status: string | null
  plan_expires_at: string | null
  source: string
}

export type BillingPaymentRequest = {
  phone: string
  provider?: string | null
  amount?: number | null
}

export type BillingPaymentLog = {
  id: number
  organisation_id: number
  phone_number: string | null
  amount: number | null
  provider: string | null
  status: string
  raw_response: Record<string, any> | null
  created_at: string
}

export type BillingPaymentLogList = {
  items: BillingPaymentLog[]
  total: number
}

export type BillingConfig = {
  configured?: boolean
  tenant_id?: string | null
  saas_error?: string | null
  plan?: {
    name?: string | null
    price?: number | null
    currency?: string | null
    interval?: string | null
  }
  payment_methods?: {
    bank?: {
      enabled?: boolean
      bank_name?: string | null
      account_name?: string | null
      account_number?: string | null
      swift_code?: string | null
    }
    mobile_money?: {
      enabled?: boolean
      provider?: string | null
      merchant_number?: string | null
      instructions?: string | null
    }
  }
  support_contact?: string | null
}

export async function getBillingSummary(): Promise<BillingSummary> {
  return apiRequest('GET', '/billing/summary')
}

export async function listBillingInvoices(): Promise<BillingInvoiceList> {
  return apiRequest('GET', '/billing/invoices')
}

export async function listBillingPaymentMethods(): Promise<BillingPaymentMethodList> {
  return apiRequest('GET', '/billing/payment-methods')
}

export async function getBillingStatus(): Promise<BillingStatus> {
  return apiRequest('GET', '/billing/status')
}

export async function initiateBillingPayment(payload: BillingPaymentRequest): Promise<any> {
  return apiRequest('POST', '/billing/initiate-payment', payload)
}

export async function listBillingPaymentLogs(params?: {
  status?: string
  provider?: string
  phone?: string
  limit?: number
  offset?: number
}): Promise<BillingPaymentLogList> {
  return apiRequest('GET', '/billing/payment-logs', { params })
}

export async function getBillingConfig(): Promise<BillingConfig> {
  return apiRequest('GET', '/billing/config')
}

export async function createCheckoutSession(): Promise<{ checkout_url: string }> {
  return apiRequest('GET', '/billing/checkout-session')
}

export async function exportBillingPaymentLogs(params?: {
  status?: string
  provider?: string
  phone?: string
}): Promise<Blob> {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.provider) searchParams.set('provider', params.provider)
  if (params?.phone) searchParams.set('phone', params.phone)

  const base = API_BASE_URL.replace(/\/+$/, '')
  const url = `${base}/billing/payment-logs/export${searchParams.toString() ? `?${searchParams.toString()}` : ''}`

  const headers = {
    ...getAuthHeaders(),
    Accept: 'text/csv',
  }

  const response = await fetch(url, { headers })
  if (!response.ok) {
    let detail = ''
    try {
      detail = await response.text()
    } catch {
      detail = ''
    }
    throw new Error(detail || 'Impossible d’exporter les logs.')
  }
  return response.blob()
}

export async function downloadBillingInvoicePdf(invoiceId: string): Promise<Blob> {
  const base = API_BASE_URL.replace(/\/+$/, '')
  const path = `/billing/invoices/${encodeURIComponent(invoiceId)}/pdf`
  const url = `${base}${path}`

  const headers = {
    ...getAuthHeaders(),
    Accept: 'application/pdf',
  }

  const response = await fetch(url, { headers })
  if (!response.ok) {
    let detail = ''
    try {
      detail = await response.text()
    } catch {
      detail = ''
    }
    throw new Error(detail || 'Impossible de télécharger la note de débit.')
  }
  return response.blob()
}
