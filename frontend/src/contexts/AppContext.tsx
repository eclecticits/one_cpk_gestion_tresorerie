import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { usePermissionsContext } from './PermissionsContext'
import { useOrganisationSettings } from './OrganisationSettingsContext'
import { useAuth } from './AuthContext'

export type AppId = 'TREASURY' | 'HR' | 'SECRETARIAT' | 'COMPTABILITE'

export interface AppDefinition {
  id: AppId
  label: string
  subtitle: string
  entryPath: string
  accessPermissions: string[]
  color: string
  bgColor: string
  /** Clé dans modules_config pour vérifier si le module est activé */
  moduleKey?: string
}

export const APP_DEFINITIONS: AppDefinition[] = [
  {
    id: 'TREASURY',
    label: 'Trésorerie',
    subtitle: 'Module financier',
    entryPath: '/',
    accessPermissions: ['dashboard', 'encaissements', 'requisitions', 'validation', 'sorties_fonds', 'budget', 'rapports'],
    color: '#1f4d45',
    bgColor: 'rgba(31, 77, 69, 0.12)',
    moduleKey: 'tresorerie',
  },
  {
    id: 'HR',
    label: 'Ressources Humaines',
    subtitle: 'Ressources Humaines',
    entryPath: '/rh/vue-ensemble',
    accessPermissions: ['rh.dashboard.view', 'rh.employees.view', 'rh.contracts.view', 'rh.attendance.view'],
    color: '#2563eb',
    bgColor: 'rgba(37, 99, 235, 0.12)',
    moduleKey: 'rh',
  },
  {
    id: 'SECRETARIAT',
    label: 'Secrétariat',
    subtitle: 'Secrétariat',
    entryPath: '/secretariat',
    accessPermissions: ['secretariat.view'],
    color: '#7c3aed',
    bgColor: 'rgba(124, 58, 237, 0.12)',
    moduleKey: 'secretariat',
  },
  {
    id: 'COMPTABILITE',
    label: 'Comptabilité',
    subtitle: 'Comptabilité générale',
    entryPath: '/comptabilite',
    accessPermissions: [
      'compta.lecture',
      'compta.saisie',
      'compta.validation',
      'compta.cloture',
      'compta.parametrage',
      'compta.export',
    ],
    color: '#b45309',
    bgColor: 'rgba(180, 83, 9, 0.12)',
    moduleKey: 'comptabilite',
  },
]

const ROUTE_TO_APP: { prefix: string; app: AppId }[] = [
  { prefix: '/rh', app: 'HR' },
  { prefix: '/secretariat', app: 'SECRETARIAT' },
  { prefix: '/comptabilite', app: 'COMPTABILITE' },
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
  const { hasPermission, loading: permissionsLoading } = usePermissionsContext()
  const { settings: orgSettings, loading: orgSettingsLoading } = useOrganisationSettings()
  const { user } = useAuth()
  const [activeApp, setActiveAppState] = useState<AppId>(() => {
    return (localStorage.getItem(STORAGE_KEY) as AppId) || 'TREASURY'
  })

  const loading = permissionsLoading || orgSettingsLoading

  const isSuperAdmin = user?.role === 'super_admin'
  const _modulesConfig = orgSettings?.modules_config as Record<string, { enabled?: boolean }> | null | undefined

  const availableApps = useMemo(
    () =>
      loading
        ? []
        : APP_DEFINITIONS.filter(app => {
            // Vérification des permissions
            if (!app.accessPermissions.some(p => hasPermission(p))) return false
            // super_admin voit toujours toutes les apps
            if (isSuperAdmin) return true
            // Vérification de l'activation du module
            if (app.moduleKey && _modulesConfig) {
              const modCfg = _modulesConfig[app.moduleKey]
              // Si modules_config est configuré : cacher si le module n'est pas présent OU explicitement désactivé
              if (!modCfg || modCfg.enabled === false) return false
            }
            return true
          }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loading, hasPermission, isSuperAdmin, _modulesConfig],
  )

  useEffect(() => {
    if (loading || availableApps.length === 0) return
    if (!availableApps.find(a => a.id === activeApp)) {
      const first = availableApps[0].id
      setActiveAppState(first)
      localStorage.setItem(STORAGE_KEY, first)
    }
  }, [loading, availableApps, activeApp])

  const setActiveApp = useCallback((app: AppId) => {
    setActiveAppState(app)
    localStorage.setItem(STORAGE_KEY, app)
  }, [])

  const activeAppDef =
    APP_DEFINITIONS.find(a => a.id === activeApp) || APP_DEFINITIONS[0]

  const value = useMemo(
    () => ({ activeApp, setActiveApp, availableApps, activeAppDef, appsLoading: loading }),
    [activeApp, setActiveApp, availableApps, activeAppDef, loading],
  )

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
