import { useState, useEffect } from 'react'
import { getMenuPermissions } from '../api/permissions'
import { useAuth } from '../contexts/AuthContext'

export interface UserPermissions {
  menuPermissions: Set<string>
  isAdmin: boolean
  loading: boolean
}

export function usePermissions(): UserPermissions {
  const { user } = useAuth()
  const [menuPermissions, setMenuPermissions] = useState<Set<string>>(new Set())
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

      const adminStatus = user.role === 'admin'
      setIsAdmin(adminStatus)

      if (adminStatus) {
        setMenuPermissions(new Set([
          'dashboard',
          'encaissements',
          'requisitions',
          'validation',
          'sorties_fonds',
          'budget',
          'rapports',
          'experts_comptables',
          'settings'
        ]))
      } else {
        const res = await getMenuPermissions()
        setMenuPermissions(new Set(res.menus))
      }
    } catch (error) {
      console.error('Error loading permissions:', error)
    } finally {
      setLoading(false)
    }
  }

  return {
    menuPermissions,
    isAdmin,
    loading
  }
}
