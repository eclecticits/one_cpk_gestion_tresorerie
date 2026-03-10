export const getTenantSlug = (): string | null => {
  if (typeof window === 'undefined') return null

  const hostname = window.location.hostname.toLowerCase()
  if (!hostname) return null

  if (hostname === 'localhost' || hostname === '127.0.0.1') return null

  const parts = hostname.split('.').filter(Boolean)
  if (parts.length <= 1) return null

  const reserved = new Set(['www', 'app'])

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
