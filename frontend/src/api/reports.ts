import { apiRequest } from '../lib/apiClient'
import type { CloturePdfData } from './clotures'

export type RapportCloture = {
  date: string
  pv: CloturePdfData | null
  nombre_clotures: number
}

export const getRapportCloture = (params: { date_jour?: string } = {}): Promise<RapportCloture> => {
  return apiRequest('GET', '/reports/rapport-cloture', { params })
}
