import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getOrganisationSettings, type OrganisationSettings } from '../api/organisation'
import { useAuth } from './AuthContext'

interface OrganisationSettingsContextType {
  settings: OrganisationSettings | null
  loading: boolean
  reload: () => Promise<void>
}

const OrganisationSettingsContext = createContext<OrganisationSettingsContextType | undefined>(undefined)

export function OrganisationSettingsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [settings, setSettings] = useState<OrganisationSettings | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!user) {
      setSettings(null)
      return
    }
    setLoading(true)
    try {
      const res = await getOrganisationSettings()
      setSettings(res)
    } catch {
      setSettings(null)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  useEffect(() => {
    void load()
  }, [user?.organisation_id])

  const value = useMemo(
    () => ({ settings, loading, reload: load }),
    [settings, loading, load],
  )

  return (
    <OrganisationSettingsContext.Provider value={value}>
      {children}
    </OrganisationSettingsContext.Provider>
  )
}

export function useOrganisationSettings() {
  const context = useContext(OrganisationSettingsContext)
  if (!context) {
    throw new Error('useOrganisationSettings must be used within OrganisationSettingsProvider')
  }
  return context
}
