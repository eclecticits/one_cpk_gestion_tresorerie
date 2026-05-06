import { apiRequest } from '../lib/apiClient'
import type { DashboardStatsResponse } from '../types/dashboard'

export async function getDashboardStats(params: {
  period_type: string
  date_debut?: string
  date_fin?: string
  include_all_status?: boolean
  canal?: string
  compte_bancaire_id?: number
  devise?: 'USD' | 'CDF'
}): Promise<DashboardStatsResponse> {
  const qs = new URLSearchParams({
    period_type: params.period_type,
  })
  if (params.date_debut) qs.set('date_debut', params.date_debut)
  if (params.date_fin) qs.set('date_fin', params.date_fin)
  if (params.include_all_status !== undefined) {
    qs.set('include_all_status', String(params.include_all_status))
  }
  if (params.canal) qs.set('canal', params.canal)
  if (params.compte_bancaire_id) qs.set('compte_bancaire_id', String(params.compte_bancaire_id))
  if (params.devise) qs.set('devise', params.devise)

  return apiRequest('GET', `/dashboard/stats?${qs.toString()}`)
}
