import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../lib/apiClient'

type TreasuryLockStatus = {
  is_closed: boolean
  date?: string | null
}

export const useTreasuryLock = () => {
  const [isCaisseClosed, setIsCaisseClosed] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const checkStatus = useCallback(async () => {
    try {
      const data = await apiRequest<TreasuryLockStatus>('GET', '/clotures/status-today')
      setIsCaisseClosed(Boolean(data?.is_closed))
    } catch (error) {
      setIsCaisseClosed(false)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    checkStatus()
    const handleUpdate = () => checkStatus()
    window.addEventListener('cash-closure-updated', handleUpdate)
    return () => window.removeEventListener('cash-closure-updated', handleUpdate)
  }, [checkStatus])

  return { isCaisseClosed, isLoading, checkStatus }
}
