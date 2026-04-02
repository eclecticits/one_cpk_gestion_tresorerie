import { API_BASE_URL } from '../lib/apiClient'

const secureUploadsEnabled = String((import.meta as any).env?.VITE_SECURE_UPLOADS || '').toLowerCase() === 'true'

export function buildUploadUrl(path: string): string {
  if (!path) return ''
  const apiOrigin = API_BASE_URL.replace(/\/api\/v1$/, '')
  if (secureUploadsEnabled) {
    const rel = path.startsWith('/uploads/') ? path.replace(/^\/uploads\//, '') : path.replace(/^\/+/, '')
    return `${API_BASE_URL}/secure-uploads/${rel}`
  }
  const normalized = path.startsWith('/uploads/') ? path : `/uploads/${path.replace(/^\/+/, '')}`
  return `${apiOrigin}${normalized}`
}
