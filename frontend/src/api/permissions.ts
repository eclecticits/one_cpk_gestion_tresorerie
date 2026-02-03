import { apiRequest } from '../lib/apiClient'

export async function getMenuPermissions(): Promise<{ is_admin: boolean; menus: string[] }> {
  return apiRequest('GET', '/permissions/menu')
}
