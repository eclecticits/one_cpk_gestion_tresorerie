import { apiRequest } from '../lib/apiClient'
import { Rubrique, User, UserRoleAssignment } from '../types'

export async function adminListUsers(): Promise<User[]> {
  return apiRequest('GET', '/admin/users')
}

export async function adminCreateUser(input: { email: string; nom: string; prenom: string; role: string }): Promise<User> {
  return apiRequest('POST', '/admin/users', input)
}

export async function adminUpdateUser(userId: string, input: { email?: string; nom?: string; prenom?: string; role?: string }): Promise<User> {
  return apiRequest('PATCH', `/admin/users/${userId}`, input)
}

export async function adminToggleUserStatus(userId: string, currentStatus: boolean): Promise<{ ok: boolean; active: boolean }> {
  return apiRequest('POST', '/admin/users/toggle-status', {
    user_id: userId,
    current_status: currentStatus,
  })
}

export async function adminResetUserPassword(userId: string): Promise<{ ok: boolean }> {
  return apiRequest('POST', '/admin/users/reset-password', { user_id: userId })
}

export async function adminSetUserPassword(userId: string, password: string, forceChange = false): Promise<{ ok: boolean }> {
  return apiRequest('POST', '/admin/users/set-password', {
    user_id: userId,
    password,
    force_change: forceChange,
  })
}

export async function adminDeleteUser(userId: string): Promise<{ ok: boolean }> {
  return apiRequest('POST', '/admin/users/delete', { user_id: userId })
}

export async function adminGetUserMenuPermissions(userId: string): Promise<{ menus: string[] }> {
  return apiRequest('GET', `/admin/users/${userId}/menu-permissions`)
}

export async function adminSetUserMenuPermissions(userId: string, menus: string[]): Promise<{ ok: boolean }> {
  return apiRequest('PUT', `/admin/users/${userId}/menu-permissions`, { menus })
}

export async function adminGetRoleMenuPermissions(role: string): Promise<{ menus: string[] }> {
  return apiRequest('GET', `/admin/role-menu-permissions`, { params: { role } })
}

export async function adminSetRoleMenuPermissions(role: string, menus: string[]): Promise<{ ok: boolean }> {
  return apiRequest('PUT', `/admin/role-menu-permissions`, { params: { role }, body: { menus } })
}

export async function adminListRoleMenuPermissionsRoles(): Promise<{ roles: string[] }> {
  return apiRequest('GET', `/admin/role-menu-permissions/roles`)
}

export async function adminListRubriques(): Promise<Rubrique[]> {
  return apiRequest('GET', '/admin/rubriques')
}

export async function adminCreateRubrique(input: { code: string; libelle: string; description?: string; active?: boolean }): Promise<Rubrique> {
  return apiRequest('POST', '/admin/rubriques', input)
}

export async function adminUpdateRubrique(rubriqueId: string, input: { code?: string; libelle?: string; description?: string; active?: boolean }): Promise<Rubrique> {
  return apiRequest('PATCH', `/admin/rubriques/${rubriqueId}`, input)
}

export type PrintSettings = {
  id?: string
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
  default_currency: string
  secondary_currency: string
  exchange_rate: number
  fiscal_year: number
  budget_alert_threshold: number
  budget_block_overrun: boolean
  budget_force_roles: string
}

export async function adminGetPrintSettings(): Promise<{ data: PrintSettings | null }> {
  return apiRequest('GET', '/admin/print-settings')
}

export async function adminSavePrintSettings(input: Partial<PrintSettings>): Promise<{ ok: boolean }> {
  return apiRequest('PUT', '/admin/print-settings', input)
}

export async function adminUploadAsset(kind: 'logo' | 'stamp', file: File): Promise<{ url: string }> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest('POST', `/admin/uploads/${kind}`, form)
}

export async function adminListUserRoles(): Promise<UserRoleAssignment[]> {
  return apiRequest('GET', '/admin/user-roles')
}

export async function adminAssignUserRole(input: { user_id: string; role: string }): Promise<UserRoleAssignment> {
  return apiRequest('POST', '/admin/user-roles', input)
}

export async function adminRemoveUserRole(roleAssignmentId: string): Promise<{ ok: boolean }> {
  return apiRequest('DELETE', `/admin/user-roles/${roleAssignmentId}`)
}

export type RequisitionApprover = {
  id: string
  user_id: string
  active: boolean
  added_at: string
  notes?: string | null
  user?: { nom?: string | null; prenom?: string | null; email: string } | null
}

export async function adminListRequisitionApprovers(): Promise<RequisitionApprover[]> {
  return apiRequest('GET', '/admin/requisition-approvers')
}

export async function adminCreateRequisitionApprover(input: { user_id: string; active?: boolean; notes?: string | null }): Promise<RequisitionApprover> {
  return apiRequest('POST', '/admin/requisition-approvers', input)
}

export async function adminUpdateRequisitionApprover(approverId: string, input: { active?: boolean; notes?: string | null }): Promise<RequisitionApprover> {
  return apiRequest('PATCH', `/admin/requisition-approvers/${approverId}`, input)
}

export async function adminDeleteRequisitionApprover(approverId: string): Promise<{ ok: boolean }> {
  return apiRequest('DELETE', `/admin/requisition-approvers/${approverId}`)
}
