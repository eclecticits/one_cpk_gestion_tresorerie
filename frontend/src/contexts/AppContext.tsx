import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { usePermissionsContext } from './PermissionsContext'
import { useOrganisationSettings } from './OrganisationSettingsContext'
import { useAuth } from './AuthContext'

export type AppId = 'TREASURY' | 'HR' | 'SECRETARIAT' | 'TABLEAU' | 'COMPTABILITE'

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
    entryPath: '/dashboard',
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
    id: 'TABLEAU',
    label: 'Tableau',
    subtitle: "Tableau de l'Ordre",
    entryPath: '/tableau',
    accessPermissions: ['tableau.view'],
    color: '#0f766e',
    bgColor: 'rgba(15, 118, 110, 0.12)',
    moduleKey: 'tableau',
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

/** Clés de module, dans l'ordre par défaut (repris de `services.modules_accueil`). */
export const MODULES_ORDRE_DEFAUT = ['tresorerie', 'tableau', 'comptabilite', 'rh', 'secretariat']

const COMPTA_PERMISSIONS = ['compta.lecture', 'compta.saisie', 'compta.validation', 'compta.cloture', 'compta.parametrage', 'compta.export']

/**
 * Les pages par lesquelles on peut entrer dans un module, avec la permission
 * que leur route exige. La première est le tableau de bord du module ; les
 * suivantes servent à qui n'a pas ce tableau de bord, plutôt qu'un refus.
 */
const PAGES_ENTREE: Record<AppId, { path: string; permissions: string[] }[]> = {
  TREASURY: [
    { path: '/dashboard', permissions: ['dashboard'] },
    { path: '/encaissements', permissions: ['encaissements'] },
    { path: '/requisitions', permissions: ['requisitions'] },
    { path: '/validation', permissions: ['validation'] },
    { path: '/sorties-fonds', permissions: ['sorties_fonds'] },
    { path: '/budget', permissions: ['budget'] },
    { path: '/rapports/synthese', permissions: ['rapports'] },
  ],
  HR: [
    { path: '/rh/vue-ensemble', permissions: ['rh.dashboard.view'] },
    { path: '/rh/employes', permissions: ['rh.employees.view'] },
    { path: '/rh/contrats', permissions: ['rh.contracts.view'] },
    { path: '/rh/presences', permissions: ['rh.attendance.view'] },
  ],
  SECRETARIAT: [{ path: '/secretariat', permissions: ['secretariat.view'] }],
  TABLEAU: [{ path: '/tableau', permissions: ['tableau.view'] }],
  COMPTABILITE: [{ path: '/comptabilite', permissions: COMPTA_PERMISSIONS }],
}

const ROUTE_TO_APP: { prefix: string; app: AppId }[] = [
  { prefix: '/rh', app: 'HR' },
  { prefix: '/secretariat', app: 'SECRETARIAT' },
  { prefix: '/comptabilite', app: 'COMPTABILITE' },
  { prefix: '/tableau', app: 'TABLEAU' },
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
  /** Première page du module que l'utilisateur peut ouvrir, ou null. */
  cheminEntree: (app: AppId) => string | null
  /** Où arriver après la connexion ; null : aucun module accessible. */
  cheminAccueil: string | null
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

  const serviceIds = useMemo(
    () => (user?.service_ids?.length ? user.service_ids : user?.service_id ? [user.service_id] : []),
    [user?.service_ids, user?.service_id],
  )

  const cheminEntree = useCallback(
    (app: AppId): string | null => {
      const pages = PAGES_ENTREE[app] ?? []
      const [tableauDeBord, ...autres] = pages
      if (tableauDeBord && tableauDeBord.permissions.some(p => hasPermission(p))) return tableauDeBord.path
      // Sans le tableau de bord de la Trésorerie, l'agent d'un service arrive
      // dans l'espace de son service, comme avant.
      if (app === 'TREASURY' && serviceIds.length > 0) {
        return serviceIds.length === 1 ? `/services/mon-espace/${serviceIds[0]}` : '/services'
      }
      return autres.find(page => page.permissions.some(p => hasPermission(p)))?.path ?? null
    },
    [hasPermission, serviceIds],
  )

  // Le module d'accueil choisi pour l'utilisateur d'abord, puis l'ordre de
  // l'organisation ; un module qu'il ne peut pas ouvrir est simplement passé.
  const cheminAccueil = useMemo(() => {
    if (loading) return null
    const choisi = availableApps.find(app => app.moduleKey && app.moduleKey === user?.module_accueil)
    const cheminChoisi = choisi ? cheminEntree(choisi.id) : null
    if (cheminChoisi) return cheminChoisi
    const ordre = [...(orgSettings?.modules_priorite ?? []), ...MODULES_ORDRE_DEFAUT]
    const rang = (app: AppDefinition) => {
      const index = app.moduleKey ? ordre.indexOf(app.moduleKey) : -1
      return index === -1 ? ordre.length : index
    }
    const parPriorite = [...availableApps].sort((a, b) => rang(a) - rang(b))
    // Un module dont on a le tableau de bord passe avant un module où l'on
    // n'ouvre qu'une page intérieure.
    const avecTableauDeBord = parPriorite.find(app => {
      const tableauDeBord = PAGES_ENTREE[app.id]?.[0]
      return tableauDeBord?.permissions.some(p => hasPermission(p))
    })
    if (avecTableauDeBord) return PAGES_ENTREE[avecTableauDeBord.id][0].path
    for (const app of parPriorite) {
      const chemin = cheminEntree(app.id)
      if (chemin) return chemin
    }
    if (serviceIds.length > 0) {
      return serviceIds.length === 1 ? `/services/mon-espace/${serviceIds[0]}` : '/services'
    }
    return null
  }, [loading, user?.module_accueil, orgSettings?.modules_priorite, availableApps, hasPermission, cheminEntree, serviceIds])

  const value = useMemo(
    () => ({ activeApp, setActiveApp, availableApps, activeAppDef, appsLoading: loading, cheminEntree, cheminAccueil }),
    [activeApp, setActiveApp, availableApps, activeAppDef, loading, cheminEntree, cheminAccueil],
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
