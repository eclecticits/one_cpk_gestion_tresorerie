import { useState, useEffect, useCallback } from 'react'
import { getMenuPermissions } from '../api/permissions'
import { useAuth } from '../contexts/AuthContext'

export interface UserPermissions {
  menuPermissions: Set<string>
  permissionCodes: Set<string>
  isAdmin: boolean
  loading: boolean
  hasPermission: (permission: string) => boolean
}

export function usePermissions(): UserPermissions {
  const { user } = useAuth()
  const [menuPermissions, setMenuPermissions] = useState<Set<string>>(new Set())
  const [permissionCodes, setPermissionCodes] = useState<Set<string>>(new Set())
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadPermissions()
  }, [user?.id])

  const loadPermissions = async () => {
    if (!user) {
      setLoading(false)
      return
    }

    try {
      setLoading(true)

      const res = await getMenuPermissions()
      setIsAdmin(!!res.is_admin)
      setMenuPermissions(new Set(res.menus || []))
      setPermissionCodes(new Set(res.permissions || []))
    } catch (error) {
      console.error('Error loading permissions:', error)
    } finally {
      setLoading(false)
    }
  }

  const hasPermission = useCallback((permission: string) => {
    if (isAdmin) return true
    return menuPermissions.has(permission) || permissionCodes.has(permission)
  }, [isAdmin, menuPermissions, permissionCodes])

  return {
    menuPermissions,
    permissionCodes,
    isAdmin,
    loading,
    hasPermission
  }
}
