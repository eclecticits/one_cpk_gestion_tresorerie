import { apiRequest } from '../lib/apiClient'
import type { TreasuryOverviewData } from '../types/treasury'

export async function getTreasuryBalances(): Promise<TreasuryOverviewData> {
  return apiRequest<TreasuryOverviewData>('GET', '/tresorerie/soldes')
}

export interface TreasuryImportResult {
  date?: string | null
  label: string
  amount: number
  ai_classification?: {
    compte?: string
    categorie?: string
    explication?: string
    taux_confiance?: number
    error?: string
    source?: 'memory' | 'ai'
  }
}

export async function importTreasuryExcel(file: File): Promise<{ count: number; data: TreasuryImportResult[] }> {
  const formData = new FormData()
  formData.append('file', file)
  return apiRequest('POST', '/tresorerie/import-excel', { body: formData })
}

export async function confirmTreasuryClassification(input: {
  label: string
  account: string
  confidence_score?: number
}): Promise<{ status: string }> {
  return apiRequest('POST', '/tresorerie/confirm-classification', { body: input })
}
