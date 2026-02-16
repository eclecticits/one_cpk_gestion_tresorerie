import { apiRequest } from '../lib/apiClient'

export interface RequisitionAiScore {
  requisition_id: string
  risk_score: number
  confidence_score: number
  level: 'FAIBLE' | 'MOYEN' | 'ELEVE'
  explanation: string
  reasons: string[]
  segment: string
  sample_size: number
  mean_amount: number | null
  std_amount: number | null
  z_score: number | null
  duplicate_candidates: number
}

export interface CashForecast {
  solde_actuel: number
  lookback_days: number
  horizon_days: number
  reserve_threshold: number
  encaissements_total: number
  sorties_total: number
  net_total: number
  baseline_projection: number
  stress_projection: number
  pending_total: number
  pressure_ratio: number
  autonomy_days: number | null
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  risk_message: string
}

export async function scoreRequisitions(input: {
  requisition_ids: string[]
  lookback_days?: number
  min_history?: number
}): Promise<RequisitionAiScore[]> {
  return apiRequest('POST', '/ai/score-requisitions', { body: input })
}

export async function getCashForecast(params?: {
  lookback_days?: number
  horizon_days?: number
  reserve_threshold?: number
}): Promise<CashForecast> {
  return apiRequest('GET', '/ai/cash-forecast', { params })
}

export async function chatWithMind(input: {
  message: string
  history: Array<{ role: 'user' | 'assistant'; content: string }>
}): Promise<{ answer: string; widget?: { label: string; value: string; tone?: 'ok' | 'warn' | 'critical' }; suggestions?: string[] }> {
  return apiRequest('POST', '/ai/chat', { body: input })
}
