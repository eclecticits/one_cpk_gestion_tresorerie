import React, { createContext, useContext, useEffect, useState } from 'react'
import { login, logout, me, refresh, type LoginResponse } from '../api/auth'
import { setAccessToken } from '../lib/apiClient'
import { User } from '../types'
interface AuthContextType {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<LoginResponse>
  signOut: () => Promise<void>
  reloadProfile: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const reloadProfile = async () => {
    const profile = await me()
    setUser(profile)
  }

  useEffect(() => {
    ;(async () => {
      try {
        // On app load, try to refresh using the HttpOnly cookie.
        await refresh()
        await reloadProfile()
      } catch {
        setAccessToken(null)
        setUser(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const signIn = async (email: string, password: string) => {
    const res = await login(email, password)
    if (res.access_token) {
      await reloadProfile()
    } else {
      setUser(null)
    }
    return res
  }

  const signOut = async () => {
    await logout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, reloadProfile }}>
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
