import { apiRequest } from '../lib/apiClient'

export type AuditLog = {
  id: number
  user_id?: string | null
  action: string
  target_table?: string | null
  target_id?: string | null
  old_value?: any | null
  new_value?: any | null
  ip_address?: string | null
  created_at: string
}

export type AuditLogFilters = {
  action?: string
  user_id?: string
  target_table?: string
  target_id?: string
  date_debut?: string
  date_fin?: string
  limit?: number
  offset?: number
}

export async function getAuditLogs(filters: AuditLogFilters): Promise<AuditLog[]> {
  return apiRequest('GET', '/audit-logs', { params: filters })
}

export async function getAuditActions(): Promise<string[]> {
  return apiRequest('GET', '/audit-logs/actions')
}

export type AuditUser = {
  id: string
  label: string
  email?: string
}

export async function getAuditUsers(): Promise<AuditUser[]> {
  return apiRequest('GET', '/audit-logs/users')
}
