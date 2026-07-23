import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'

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
    return `${API_BASE_URL}/secure-uploads/${rel}`
  }
  const normalized = path.startsWith('/uploads/') ? path : `/uploads/${path.replace(/^\/+/, '')}`
  return `${apiOrigin}${normalized}`
}

export async function openUploadUrl(url: string): Promise<void> {
  if (!url) return
  const shouldAuthenticate = secureUploadsEnabled && url.includes('/secure-uploads/')
  if (!shouldAuthenticate) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  const response = await fetch(url, {
    headers: getAuthHeaders('/secure-uploads'),
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error("Impossible d'ouvrir le fichier sécurisé")
  }
  const blobUrl = URL.createObjectURL(await response.blob())
  window.open(blobUrl, '_blank', 'noopener,noreferrer')
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60000)
}
