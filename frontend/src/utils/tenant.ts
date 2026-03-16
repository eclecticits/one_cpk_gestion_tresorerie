export const getTenantSlug = (): string | null => {
  if (typeof window === 'undefined') return null

  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return null

  const defaultTenant =
    (typeof import.meta !== 'undefined' &&
      typeof import.meta.env !== 'undefined' &&
      (import.meta.env as any).VITE_DEFAULT_TENANT) ||
    'cpk'

  if (hostname === 'localhost' || hostname === '127.0.0.1') return defaultTenant

  const parts = hostname.split('.').filter(Boolean)
  if (parts.length <= 1) return null

  const reserved = new Set(['www', 'app', 'admin', 'signup'])

  if (hostname.endsWith('.localhost')) {
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
