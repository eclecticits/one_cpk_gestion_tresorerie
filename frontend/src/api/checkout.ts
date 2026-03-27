import { apiRequest } from '../lib/apiClient'

export type CheckoutSession = {
  session_id: string
  tenant_id: string
  amount: number
  currency: string
  status?: string | null
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
  support_contact?: string | null
  billing_portal_url?: string | null
  success_url?: string | null
  cancel_url?: string | null
  checkout_url?: string | null
  bank_proof_url?: string | null
}

export async function getCheckoutSession(sessionId: string): Promise<CheckoutSession> {
  return apiRequest('GET', `/payments/session/${sessionId}`)
}

export async function initiateCheckoutSession(
  sessionId: string,
  payload: { method: string; phone?: string; provider?: string }
): Promise<{ checkout_url?: string | null; provider?: string; provider_ref?: string; status?: string | null }> {
  return apiRequest('POST', `/payments/session/${sessionId}/initiate`, payload)
}

export async function uploadBankProof(
  sessionId: string,
  file: File,
): Promise<{ ok: boolean; url: string }> {
  const data = new FormData()
  data.append('file', file)
  return apiRequest('POST', `/payments/session/${sessionId}/bank-proof`, data)
}
