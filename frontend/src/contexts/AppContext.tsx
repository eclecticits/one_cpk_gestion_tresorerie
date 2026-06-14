import { createContext, useContext, useEffect, useState } from 'react'
import { usePermissionsContext } from './PermissionsContext'

export type AppId = 'TREASURY' | 'HR' | 'SECRETARIAT'

export interface AppDefinition {
  id: AppId
  label: string
  subtitle: string
  entryPath: string
  accessPermissions: string[]
  color: string
  bgColor: string
}

export const APP_DEFINITIONS: AppDefinition[] = [
  {
    id: 'TREASURY',
    label: 'Trésorerie',
    subtitle: 'Gestion de Trésorerie',
    entryPath: '/',
    accessPermissions: ['dashboard', 'encaissements', 'requisitions', 'validation', 'sorties_fonds', 'budget', 'rapports'],
    color: '#1f4d45',
    bgColor: 'rgba(31, 77, 69, 0.12)',
  },
  {
    id: 'HR',
    label: 'Ressources Humaines',
    subtitle: 'Ressources Humaines',
    entryPath: '/rh/vue-ensemble',
    accessPermissions: ['rh.dashboard.view', 'rh.employees.view', 'rh.contracts.view', 'rh.attendance.view'],
    color: '#2563eb',
    bgColor: 'rgba(37, 99, 235, 0.12)',
  },
  {
    id: 'SECRETARIAT',
    label: 'Secrétariat',
    subtitle: 'Secrétariat',
    entryPath: '/secretariat',
    accessPermissions: ['secretariat.view'],
    color: '#7c3aed',
    bgColor: 'rgba(124, 58, 237, 0.12)',
  },
]

const ROUTE_TO_APP: { prefix: string; app: AppId }[] = [
  { prefix: '/rh', app: 'HR' },
  { prefix: '/secretariat', app: 'SECRETARIAT' },
]

export function detectAppFromPath(pathname: string): AppId | null {
  for (const { prefix, app } of ROUTE_TO_APP) {
    if (pathname.startsWith(prefix)) return app
  }
  const treasuryPaths = ['/', '/encaissements', '/requisitions', '/validation', '/sorties-fonds', '/budget', '/rapports', '/cloture-caisse', '/remboursement-transport', '/services', '/experts-comptables', '/settings', '/organisation-settings', '/denominations', '/audit-logs', '/historique-imports', '/requisitions-ocr', '/super-admin', '/global-monitoring']
  if (treasuryPaths.some(p => pathname === p || pathname.startsWith(p + '/'))) {
    return 'TREASURY'
  }
  return null
}

interface AppContextValue {
  activeApp: AppId
  setActiveApp: (app: AppId) => void
  availableApps: AppDefinition[]
  activeAppDef: AppDefinition
  appsLoading: boolean
}

const AppContext = createContext<AppContextValue | null>(null)

const STORAGE_KEY = 'onec_active_app'

export function AppProvider({ children }: { children: React.ReactNode }) {
  const { hasPermission, loading } = usePermissionsContext()
  const [activeApp, setActiveAppState] = useState<AppId>(() => {
    return (localStorage.getItem(STORAGE_KEY) as AppId) || 'TREASURY'
  })

  const availableApps = loading
    ? []
    : APP_DEFINITIONS.filter(app => app.accessPermissions.some(p => hasPermission(p)))

  useEffect(() => {
    if (loading || availableApps.length === 0) return
    if (!availableApps.find(a => a.id === activeApp)) {
      const first = availableApps[0].id
      setActiveAppState(first)
      localStorage.setItem(STORAGE_KEY, first)
    }
  }, [loading, availableApps.length, activeApp])

  const setActiveApp = (app: AppId) => {
    setActiveAppState(app)
    localStorage.setItem(STORAGE_KEY, app)
  }

  const activeAppDef =
    APP_DEFINITIONS.find(a => a.id === activeApp) || APP_DEFINITIONS[0]

  return (
    <AppContext.Provider
      value={{ activeApp, setActiveApp, availableApps, activeAppDef, appsLoading: loading }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
