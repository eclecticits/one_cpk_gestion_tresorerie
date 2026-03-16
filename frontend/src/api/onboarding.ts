import { apiRequest } from '../lib/apiClient'

export interface Plan {
  id: number
  name: string
  monthly_price_usd: string
  features?: Record<string, any> | null
  discounts?: Record<string, number> | null
}

export interface SignupPayload {
  organisation_name: string
  slug: string
  admin_email: string
  admin_phone?: string | null
  plan_id: number
  billing_months: number
}

export interface SignupResponse {
  id: string
  reference: string
  status: string
  plan_id: number
}

export interface CheckoutResponse {
  checkout_url: string
  transaction_id?: string | null
  status: string
}

export interface InvitationCheckResponse {
  organisation_id: number
  organisation_name: string
  slug: string
  plan_id: number
  plan_name: string
  monthly_price_usd: string
  discounts?: Record<string, number> | null
}

export async function listPlans(): Promise<Plan[]> {
  return apiRequest('GET', '/onboarding/plans')
}

export async function createSignup(payload: SignupPayload): Promise<SignupResponse> {
  return apiRequest('POST', '/onboarding/signup', payload)
}

export async function createCheckout(reference: string): Promise<CheckoutResponse> {
  return apiRequest('POST', '/onboarding/checkout', { reference })
}

export async function checkInvitation(email: string): Promise<InvitationCheckResponse> {
  return apiRequest('POST', '/onboarding/check-invitation', { email })
}
