import { apiRequest, setAccessToken } from '../lib/apiClient'
import { User } from '../types'

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
  role: string
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await apiRequest<TokenResponse>('POST', '/auth/login', { email, password })
  setAccessToken(res.access_token)
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
