const TENANT_OVERRIDE_KEY = 'onec_tenant_override'
const TENANT_STORAGE_KEY = 'current_tenant_id'
let tenantOverrideCache: string | null = null

const getTenantBaseDomain = (): string | null => {
  if (typeof import.meta === 'undefined' || typeof import.meta.env === 'undefined') {
    return null
  }
  const envDomain = String((import.meta.env as any).VITE_TENANT_BASE_DOMAIN || '').trim().toLowerCase()
  return envDomain || null
}

export const getPortalOrigin = (): string | null => {
  if (typeof window === 'undefined') return null
  if (typeof import.meta !== 'undefined' && typeof import.meta.env !== 'undefined') {
    const envOrigin = String((import.meta.env as any).VITE_PORTAL_ORIGIN || '').trim()
    if (envOrigin) return envOrigin.replace(/\/+$/, '')
  }
  const { protocol, port, hostname } = window.location
  const currentPort = port ? `:${port}` : ''
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname.endsWith('.localhost')) {
    return `${protocol}//localhost${currentPort}`
  }
  const baseDomain = getTenantBaseDomain()
  if (baseDomain) {
    return `${protocol}//www.${baseDomain}`
  }
  const parts = hostname.split('.').filter(Boolean)
  if (parts.length >= 2) {
    return `${protocol}//www.${parts.slice(-2).join('.')}${currentPort}`
  }
  return `${protocol}//${hostname}${currentPort}`
}

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
  try {
    if (normalized) {
      window.localStorage.setItem(TENANT_STORAGE_KEY, normalized)
    } else {
      window.localStorage.removeItem(TENANT_STORAGE_KEY)
    }
  } catch {
    // ignore storage errors
  }
}

export const getLastTenant = (): string | null => {
  if (typeof window === 'undefined') return null
  try {
    const stored = window.localStorage.getItem(TENANT_STORAGE_KEY)
    if (stored) return stored.trim().toLowerCase()
  } catch {
    // ignore storage errors
  }
  try {
    const stored = window.sessionStorage.getItem(TENANT_OVERRIDE_KEY)
    if (stored) return stored.trim().toLowerCase()
  } catch {
    // ignore storage errors
  }
  return null
}

export const getTenantRequestHint = (): string | null => {
  const hostTenant = getTenantSlug()
  if (hostTenant) return hostTenant
  return getLastTenant()
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
  try {
    const stored = window.localStorage.getItem(TENANT_STORAGE_KEY)
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
  const isIpHost = /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname)
  const baseDomainOverride = getTenantBaseDomain()

  if (hostname === 'localhost' || hostname === '127.0.0.1' || isIpHost) {
    return null
  }

  const parts = hostname.split('.').filter(Boolean)
  if (parts.length <= 1) return null

  const reserved = new Set(['www', 'app', 'admin', 'signup', 'api'])

  if (hostname.endsWith('.localhost')) {
    const sub = parts[0]
    return reserved.has(sub) ? null : getTenantOverride() || sub
  }

  if (baseDomainOverride && hostname.endsWith(`.${baseDomainOverride}`)) {
    const sub = parts[0]
    return reserved.has(sub) ? null : sub
  }

  if (parts.length <= 2) {
    const first = parts[0]
    return reserved.has(first) ? null : null
  }

  const subdomain = parts[0]
  if (reserved.has(subdomain)) return null
  return subdomain
}

export const isTenantSubdomainHost = (): boolean => {
  if (typeof window === 'undefined') return false
  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return false
  const isIpHost = /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname)
  if (hostname === 'localhost' || hostname === '127.0.0.1' || isIpHost) return false
  if (hostname.endsWith('.localhost')) {
    const slug = getTenantSlug()
    return Boolean(slug && !isAdminHost())
  }
  const parts = hostname.split('.').filter(Boolean)
  if (parts.length <= 2) return false
  return Boolean(getTenantSlug() && !isAdminHost())
}

export const isAdminHost = (): boolean => {
  if (typeof window === 'undefined') return false
  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return false
  if (hostname === 'localhost' || hostname === '127.0.0.1') return false
  if (hostname.endsWith('.localhost')) return false
  const baseDomainOverride = getTenantBaseDomain()
  if (baseDomainOverride && hostname === baseDomainOverride) return false
  const parts = hostname.split('.').filter(Boolean)
  if (!parts.length) return false
  return parts[0] === 'admin'
}
