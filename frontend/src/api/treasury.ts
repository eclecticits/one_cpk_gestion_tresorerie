import { apiRequest } from '../lib/apiClient'
import type { TreasuryOverviewData } from '../types/treasury'

export async function getTreasuryBalances(): Promise<TreasuryOverviewData> {
  return apiRequest<TreasuryOverviewData>('GET', '/tresorerie/soldes')
}
