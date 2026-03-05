import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../lib/apiClient'
import type { ReportAnnualSynthese } from '../types/reports'

type AnnualReportParams = {
  year: number
  devise: 'USD' | 'CDF'
  canal: 'ALL' | 'CAISSE' | 'BANQUE'
  auto?: boolean
}

export const useAnnualReport = ({ year, devise, canal, auto = false }: AnnualReportParams) => {
  const [data, setData] = useState<ReportAnnualSynthese | null>(null)
  const [loading, setLoading] = useState(false)

  const refetch = useCallback(async () => {
    setLoading(true)
    try {
      const params = { year, devise, canal }
      const res = await apiRequest<ReportAnnualSynthese>('GET', '/reports/synthese-annuelle', { params })
      setData(res)
      return res
    } finally {
      setLoading(false)
    }
  }, [year, devise, canal])

  useEffect(() => {
    if (auto) {
      refetch().catch(() => undefined)
    }
  }, [auto, refetch])

  return { data, loading, refetch }
}
