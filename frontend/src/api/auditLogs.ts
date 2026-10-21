import { apiRequest, apiRequestWithTotal } from '../lib/apiClient'

export type AuditLog = {
  id: string
  user_id?: string | null
  action: string
  entity_type?: string | null
  entity_id?: string | null
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

/** Une page du journal et le nombre total d'entrées pour ces filtres. */
export async function getAuditLogsPage(filters: AuditLogFilters): Promise<{ data: AuditLog[]; total: number | null }> {
  return apiRequestWithTotal<AuditLog[]>('/audit-logs', { params: filters })
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
