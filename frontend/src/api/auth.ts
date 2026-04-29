import { apiRequest, resetSessionExpirySignal, setAccessToken } from '../lib/apiClient'
import { setTenantOverride } from '../utils/tenant'
import { User } from '../types'

const REFRESH_MARKER_KEY = 'onec_has_refresh'

export function hasRefreshMarker(): boolean {
  try {
    return window.localStorage.getItem(REFRESH_MARKER_KEY) === '1'
  } catch {
    return false
  }
}

function setRefreshMarker(enabled: boolean): void {
  try {
    if (enabled) {
      window.localStorage.setItem(REFRESH_MARKER_KEY, '1')
    } else {
      window.localStorage.removeItem(REFRESH_MARKER_KEY)
    }
  } catch {
    // ignore storage errors
  }
}

export function clearClientSession(): void {
  setAccessToken(null)
  setRefreshMarker(false)
  resetSessionExpirySignal()
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
  role: string
  organisation_id?: number | null
  organisation_uuid?: string | null
  organisation_slug?: string | null
  plan_status?: string | null
  plan_type?: string | null
}

export interface LoginResponse {
  access_token?: string | null
  token_type?: string
  expires_in?: number | null
  must_change_password?: boolean
  role?: string | null
  requires_otp?: boolean
  otp_required_reason?: string | null
  organisation_id?: number | null
  organisation_uuid?: string | null
  organisation_slug?: string | null
  organisation_name?: string | null
  plan_status?: string | null
  plan_type?: string | null
}

export interface TenantDiscoveryItem {
  id: number
  name: string
  slug: string
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await apiRequest<LoginResponse>('POST', '/auth/login', { email, password })
  if (res.access_token) {
    setAccessToken(res.access_token)
    setRefreshMarker(true)
    if (res.organisation_slug) {
      setTenantOverride(res.organisation_slug)
    }
    resetSessionExpirySignal()
  } else {
    setAccessToken(null)
  }
  return res
}

export async function refresh(): Promise<TokenResponse> {
  const res = await apiRequest<TokenResponse>('POST', '/auth/refresh')
  setAccessToken(res.access_token)
  setRefreshMarker(true)
  if (res.organisation_slug) {
    setTenantOverride(res.organisation_slug)
  }
  resetSessionExpirySignal()
  return res
}

export async function logout(): Promise<void> {
  try {
    await apiRequest('POST', '/auth/logout')
  } catch (error) {
    console.warn('Logout request failed; clearing local session anyway.', error)
  } finally {
    clearClientSession()
    setTenantOverride(null)
  }
}

export async function me(): Promise<User> {
  return apiRequest<User>('GET', '/auth/me')
}

export async function changePassword(currentPassword: string | null, newPassword: string): Promise<void> {
  await apiRequest('POST', '/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

export async function requestPasswordReset(email: string): Promise<{ ok: boolean; message?: string }> {
  return apiRequest('POST', '/auth/request-password-reset', { email })
}

export async function requestPasswordChange(currentPassword: string | null): Promise<{ ok: boolean; message?: string }> {
  return apiRequest('POST', '/auth/request-password-change', {
    current_password: currentPassword,
  })
}

export async function confirmPasswordChange(input: {
  email: string
  new_password: string
  otp_code: string
}): Promise<TokenResponse> {
  const res = await apiRequest<TokenResponse>('POST', '/auth/confirm-password-change', input)
  setAccessToken(res.access_token)
  setRefreshMarker(true)
  if (res.organisation_slug) {
    setTenantOverride(res.organisation_slug)
  }
  resetSessionExpirySignal()
  return res
}

export async function discoverTenants(email: string): Promise<TenantDiscoveryItem[]> {
  const encoded = encodeURIComponent(email)
  return apiRequest<TenantDiscoveryItem[]>('GET', `/auth/discover-tenants?email=${encoded}`)
}
