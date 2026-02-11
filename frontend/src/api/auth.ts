import { apiRequest, setAccessToken } from '../lib/apiClient'
import { User } from '../types'

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
  role: string
}

export interface LoginResponse {
  access_token?: string | null
  token_type?: string
  expires_in?: number | null
  must_change_password?: boolean
  role?: string | null
  requires_otp?: boolean
  otp_required_reason?: string | null
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await apiRequest<LoginResponse>('POST', '/auth/login', { email, password })
  if (res.access_token) {
    setAccessToken(res.access_token)
  } else {
    setAccessToken(null)
  }
  return res
}

export async function refresh(): Promise<TokenResponse> {
  const res = await apiRequest<TokenResponse>('POST', '/auth/refresh')
  setAccessToken(res.access_token)
  return res
}

export async function logout(): Promise<void> {
  await apiRequest('POST', '/auth/logout')
  setAccessToken(null)
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
  return res
}
