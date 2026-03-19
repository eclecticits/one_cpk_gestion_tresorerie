const TENANT_OVERRIDE_KEY = 'onec_tenant_override'
let tenantOverrideCache: string | null = null

export const setTenantOverride = (slug: string | null): void => {
  const normalized = slug ? slug.trim().toLowerCase() : ''
  tenantOverrideCache = normalized || null
  if (typeof window === 'undefined') return
  try {
    if (normalized) {
      window.sessionStorage.setItem(TENANT_OVERRIDE_KEY, normalized)
    } else {
      window.sessionStorage.removeItem(TENANT_OVERRIDE_KEY)
    }
  } catch {
    // ignore storage errors
  }
}

const getTenantOverride = (): string | null => {
  if (tenantOverrideCache) return tenantOverrideCache
  if (typeof window === 'undefined') return null
  try {
    const stored = window.sessionStorage.getItem(TENANT_OVERRIDE_KEY)
    if (stored) {
      tenantOverrideCache = stored
      return stored
    }
  } catch {
    return null
  }
  return null
}

export const getTenantSlug = (): string | null => {
  if (typeof window === 'undefined') return null

  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return null

  const defaultTenant =
    (typeof import.meta !== 'undefined' &&
      typeof import.meta.env !== 'undefined' &&
      (import.meta.env as any).VITE_DEFAULT_TENANT) ||
    'cpk'

  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return getTenantOverride() || defaultTenant
  }

  const parts = hostname.split('.').filter(Boolean)
  if (parts.length <= 1) return null

  const reserved = new Set(['www', 'app', 'admin', 'signup'])

  if (hostname.endsWith('.localhost')) {
    const sub = parts[0]
    return reserved.has(sub) ? null : getTenantOverride() || sub
  }

  if (parts.length <= 2) {
    const first = parts[0]
    return reserved.has(first) ? null : null
  }

  const subdomain = parts[0]
  if (reserved.has(subdomain)) return null
  return subdomain
}

export const isAdminHost = (): boolean => {
  if (typeof window === 'undefined') return false
  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return false
  if (hostname === 'localhost' || hostname === '127.0.0.1') return false
  if (hostname.endsWith('.localhost')) return false
  const parts = hostname.split('.').filter(Boolean)
  if (!parts.length) return false
  return parts[0] === 'admin'
}
