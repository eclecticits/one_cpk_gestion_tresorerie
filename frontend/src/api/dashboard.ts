import { apiRequest } from '../lib/apiClient'
import type { DashboardStatsResponse } from '../types/dashboard'

export async function getDashboardStats(params: {
  period_type: string
  date_debut?: string
  date_fin?: string
  include_all_status?: boolean
}): Promise<DashboardStatsResponse> {
  const qs = new URLSearchParams({
    period_type: params.period_type,
  })
  if (params.date_debut) qs.set('date_debut', params.date_debut)
  if (params.date_fin) qs.set('date_fin', params.date_fin)
  if (params.include_all_status !== undefined) {
    qs.set('include_all_status', String(params.include_all_status))
  }

  return apiRequest('GET', `/dashboard/stats?${qs.toString()}`)
}
