import { apiRequest } from '../lib/apiClient'

export async function getMenuPermissions(): Promise<{
  is_admin: boolean
  menus: string[]
  permissions: string[]
  /** Codes que `is_admin` n'ouvre pas d'office : seuls comptent ceux de `permissions`. */
  explicit_permissions?: string[]
}> {
  return apiRequest('GET', '/permissions/menu')
}
