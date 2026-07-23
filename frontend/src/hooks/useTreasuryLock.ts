import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../lib/apiClient'

type CaisseStatus = {
  est_ouverte: boolean
}

// « Caisse verrouillée » = caisse non ouverte (Modèle B, sessions ouverture/
// clôture). Remplace l'ancien verrou par journée.
export const useTreasuryLock = () => {
  const [isCaisseClosed, setIsCaisseClosed] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const checkStatus = useCallback(async () => {
    try {
      const data = await apiRequest<CaisseStatus>('GET', '/clotures/caisse-status')
      setIsCaisseClosed(!data?.est_ouverte)
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
