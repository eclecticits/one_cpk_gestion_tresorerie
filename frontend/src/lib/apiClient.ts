// ─────────────────────────────────────────────────────────────────────────────
// apiClient.ts
//
// SÉCURITÉ : le access token JWT est conservé UNIQUEMENT en mémoire RAM
// (variable de module). Il n'est JAMAIS écrit dans localStorage ni
// sessionStorage, ce qui élimine le risque de vol par attaque XSS.
//
// Fonctionnement de la session :
//  - Au login  → le backend renvoie un access token (court) + pose un
//                HttpOnly cookie de refresh (7 jours, inaccessible au JS).
//  - En mémoire → accessToken est stocké dans cette variable de module.
//  - Sur 401    → tryRefreshToken() appelle /auth/refresh via le cookie
//                 HttpOnly, récupère un nouveau access token et relance
//                 la requête originale (une seule tentative).
//  - Au rechargement de page → le token en RAM est perdu ; AuthContext
//                 appelle refresh() au démarrage pour le réhydrater via
//                 le cookie HttpOnly.
// ─────────────────────────────────────────────────────────────────────────────

import { type } from 'react' // Place holder or just remove if line 20 is the import
// I will just remove the specific import line if I find it.


type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

// ── Configuration de l'URL de base ──────────────────────────────────────────

const envApiBaseUrl = (import.meta as any).env?.VITE_API_BASE_URL

function normalizeApiBase(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '')
  if (!trimmed) return ''
  if (trimmed.endsWith('/api/v1')) return trimmed
  if (trimmed.endsWith('/api')) return `${trimmed}/v1`
  return `${trimmed}/api/v1`
}

const defaultApiBase =
  typeof window !== 'undefined' ? '/api/v1' : 'http://localhost:8000/api/v1'

export const API_BASE_URL = normalizeApiBase(String(envApiBaseUrl || '')) || defaultApiBase

if ((import.meta as any).env?.DEV) {
  console.log('API_BASE_URL =', API_BASE_URL)
}

// ── Token en mémoire uniquement ──────────────────────────────────────────────
//
// Cette variable vit dans le module JS. Elle disparaît au rechargement de la
// page — c'est voulu : AuthContext.tsx appelle refresh() au montage pour la
// réhydrater via le cookie HttpOnly, sans jamais toucher localStorage.

let accessToken: string | null = null
let impersonationReturnToken: string | null = null

/** Mettre à jour le token en mémoire. Ne touche pas localStorage. */
export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Lire le token courant (usage interne ou debug). */
export function getAccessToken(): string | null {
  return accessToken
}

export function setImpersonationReturnToken(token: string | null): void {
  impersonationReturnToken = token
}

export function getImpersonationReturnToken(): string | null {
  return impersonationReturnToken
}

export function clearImpersonationReturnToken(): void {
  impersonationReturnToken = null
}

// ── Erreur API typée ─────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number
  payload: any

  constructor(message: string, status: number, payload: any) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

// ── Helpers internes ─────────────────────────────────────────────────────────

async function parseJsonSafely(resp: Response): Promise<any> {
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) return null
  try {
    return await resp.json()
  } catch {
    return null
  }
}

function buildUrl(path: string, params?: Record<string, any>): string {
  const base = API_BASE_URL.replace(/\/+$/, '')
  let normalizedPath = path.startsWith('/') ? path : `/${path}`
  if (path.startsWith('http://') || path.startsWith('https://')) {
    const parsed = new URL(path)
    normalizedPath = `${parsed.pathname}${parsed.search}${parsed.hash}`
  }
  const origin =
    typeof window !== 'undefined' && window.location
      ? window.location.origin
      : 'http://localhost:8000'
  let baseUrl = base
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }
  const url = new URL(`${baseUrl.replace(/\/+$/, '')}${normalizedPath}`)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === null) return
      url.searchParams.set(k, String(v))
    })
  }
  return url.toString()
}

// ── Types des options de requête ─────────────────────────────────────────────

type ApiOptions =
  | any
  | {
      params?: Record<string, any>
      body?: any
    }

// ── Requête principale ───────────────────────────────────────────────────────

async function apiRequestInternal<T = any>(
  method: HttpMethod,
  path: string,
  options: ApiOptions | undefined,
  hasRetried: boolean,
): Promise<T> {
  // Rétrocompatibilité :
  //   apiRequest('GET',  '/x', { params: {...} })
  //   apiRequest('POST', '/x', payload)
  let params: Record<string, any> | undefined
  let body: any = undefined

  if (options && typeof options === 'object') {
    if ('params' in options || 'body' in options) {
      params = (options as any).params
      body = (options as any).body
    } else {
      body = options
    }
  } else {
    body = options
  }

  const url = buildUrl(path, params)

  if ((import.meta as any).env?.VITE_DEBUG_URLS === 'true') {
    console.log('[apiRequest]', method, url)
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
  }

  // Token lu uniquement depuis la variable en mémoire — jamais depuis localStorage.
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }

  // Ne pas envoyer de body sur GET/DELETE (évite "Failed to fetch" sur certains navigateurs).
  const hasBody = body !== undefined && method !== 'GET' && method !== 'DELETE'
  let payload: BodyInit | undefined
  if (hasBody) {
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      payload = body
    } else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
  }

  const resp = await fetch(url, {
    method,
    headers,
    body: payload,
    credentials: 'include', // nécessaire pour envoyer le cookie HttpOnly de refresh
  })

  if (resp.ok) {
    const data = await parseJsonSafely(resp)
    return data as T
  }

  const errPayload = await parseJsonSafely(resp)
  const message = errPayload?.detail || errPayload?.message || `HTTP ${resp.status}`

  if (resp.status === 402 && typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('payment-required', {
        detail: { message, payload: errPayload },
      })
    )
  }

  // Sur 401, tenter un refresh silencieux (une seule fois).
  if (
    resp.status === 401 &&
    !hasRetried &&
    !url.endsWith('/auth/refresh') &&
    !url.endsWith('/auth/login')
  ) {
    const refreshed = await tryRefreshToken()
    if (refreshed) {
      return apiRequestInternal<T>(method, path, options, true)
    }
  }

  throw new ApiError(message, resp.status, errPayload)
}

// ── Refresh silencieux via cookie HttpOnly ───────────────────────────────────

async function tryRefreshToken(): Promise<boolean> {
  try {
    const url = buildUrl('/auth/refresh')
    const resp = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'include',
    })
    if (!resp.ok) {
      setAccessToken(null)
      return false
    }
    const data = await parseJsonSafely(resp)
    const token = data?.access_token
    if (token) {
      setAccessToken(token)
      return true
    }
    setAccessToken(null)
    return false
  } catch {
    setAccessToken(null)
    return false
  }
}

// ── Export public ────────────────────────────────────────────────────────────

export async function apiRequest<T = any>(
  method: HttpMethod,
  path: string,
  options?: ApiOptions,
): Promise<T> {
  return apiRequestInternal<T>(method, path, options, false)
}
