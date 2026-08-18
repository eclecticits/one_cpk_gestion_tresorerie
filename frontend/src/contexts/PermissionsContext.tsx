import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getMenuPermissions } from '../api/permissions'
import { useAuth } from './AuthContext'

export interface UserPermissions {
  menuPermissions: Set<string>
  permissionCodes: Set<string>
  isAdmin: boolean
  loading: boolean
  hasPermission: (permission: string) => boolean
}

type PermissionsState = UserPermissions

const PermissionsContext = createContext<PermissionsState | null>(null)

export function PermissionsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [menuPermissions, setMenuPermissions] = useState<Set<string>>(new Set())
  const [permissionCodes, setPermissionCodes] = useState<Set<string>>(new Set())
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!user) {
      setMenuPermissions(new Set())
      setPermissionCodes(new Set())
      setIsAdmin(false)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)

    getMenuPermissions()
      .then(res => {
        if (cancelled) return
        setIsAdmin(!!res.is_admin)
        setMenuPermissions(new Set(res.menus || []))
        setPermissionCodes(new Set(res.permissions || []))
      })
      .catch(err => {
        if (!cancelled) console.error('Error loading permissions:', err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [user?.id])

  const hasPermission = useCallback(
    (permission: string) => {
      if (isAdmin) return true
      return menuPermissions.has(permission) || permissionCodes.has(permission)
    },
    [isAdmin, menuPermissions, permissionCodes],
  )

  const value = useMemo(
    () => ({ menuPermissions, permissionCodes, isAdmin, loading, hasPermission }),
    [menuPermissions, permissionCodes, isAdmin, loading, hasPermission],
  )

  return (
    <PermissionsContext.Provider value={value}>
      {children}
    </PermissionsContext.Provider>
  )
}

export function usePermissionsContext(): PermissionsState {
  const ctx = useContext(PermissionsContext)
  if (!ctx) throw new Error('usePermissionsContext must be used within PermissionsProvider')
  return ctx
}
