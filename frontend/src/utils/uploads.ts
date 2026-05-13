import { API_BASE_URL, getAccessToken } from '../lib/apiClient'

const secureUploadsEnabled = String((import.meta as any).env?.VITE_SECURE_UPLOADS || '').toLowerCase() === 'true'
const BRANDING_SEGMENT = '/branding/'

function isBrandingPath(path: string): boolean {
  return path.includes(BRANDING_SEGMENT)
}

export function buildUploadUrl(path: string): string {
  if (!path) return ''
  const apiOrigin = API_BASE_URL.replace(/\/api\/v1$/, '')
  if (secureUploadsEnabled) {
    const rel = path.startsWith('/uploads/') ? path.replace(/^\/uploads\//, '') : path.replace(/^\/+/, '')
    if (isBrandingPath(rel)) {
      return `${API_BASE_URL}/public-uploads/${rel}`
    }
    const accessToken = getAccessToken()
    const tokenQuery = accessToken ? `?token=${encodeURIComponent(accessToken)}` : ''
    return `${API_BASE_URL}/secure-uploads/${rel}${tokenQuery}`
  }
  const normalized = path.startsWith('/uploads/') ? path : `/uploads/${path.replace(/^\/+/, '')}`
  return `${apiOrigin}${normalized}`
}
