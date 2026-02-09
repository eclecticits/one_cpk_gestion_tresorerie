import { apiRequest } from '../lib/apiClient'

export const getRapportCloture = (params: { date_jour?: string } = {}) => {
  return apiRequest('GET', '/reports/rapport-cloture', { params })
}
