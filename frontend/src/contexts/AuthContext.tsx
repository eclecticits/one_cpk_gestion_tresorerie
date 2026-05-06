import React, { createContext, useContext, useEffect, useState } from 'react'
import { clearClientSession, hasRefreshMarker, login, logout, me, refresh, type LoginResponse } from '../api/auth'
import { User } from '../types'
interface AuthContextType {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string, tenant?: { id?: number | null; slug?: string | null }) => Promise<LoginResponse>
  signOut: () => Promise<void>
  reloadProfile: () => Promise<User | null>
  clearSession: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const reloadProfile = async () => {
    const profile = await me()
    setUser(profile)
    return profile
  }

  const clearSession = () => {
    clearClientSession()
    setUser(null)
    setLoading(false)
  }

  useEffect(() => {
    ;(async () => {
      try {
        // On app load, try to refresh using the HttpOnly cookie.
        if (hasRefreshMarker()) {
          await refresh()
          await reloadProfile()
        }
      } catch {
        clearSession()
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const signIn = async (email: string, password: string, tenant?: { id?: number | null; slug?: string | null }) => {
    const res = await login(email, password, tenant)
    if (res.access_token) {
      await reloadProfile()
    } else {
      setUser(null)
    }
    return res
  }

  const signOut = async () => {
    try {
      await logout()
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, reloadProfile, clearSession }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
