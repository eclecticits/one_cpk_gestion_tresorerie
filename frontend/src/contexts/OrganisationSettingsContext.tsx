import { createContext, useContext, useEffect, useState } from 'react'
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

  const load = async () => {
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
  }

  useEffect(() => {
    void load()
  }, [user?.organisation_id])

  return (
    <OrganisationSettingsContext.Provider value={{ settings, loading, reload: load }}>
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
