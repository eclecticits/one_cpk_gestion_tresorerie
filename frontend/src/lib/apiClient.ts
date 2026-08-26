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

import { getTenantRequestHint } from '../utils/tenant'

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
let sessionExpiryEventDispatched = false
let refreshPromise: Promise<boolean> | null = null
const TRANSIENT_RETRY_DELAYS = [1500, 3000, 5000]
const TRANSIENT_STATUS_CODES = new Set([502, 503, 504])

/** Mettre à jour le token en mémoire. Ne touche pas localStorage. */
export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Lire le token courant (usage interne ou debug). */
export function getAccessToken(): string | null {
  return accessToken
}

/** Générer les headers d'authentification et de tenant. */
function shouldSkipTenantHeader(path: string): boolean {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return normalized === '/auth/login'
}

export function getAuthHeaders(path = ''): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  }
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  if (!shouldSkipTenantHeader(path)) {
    const tenantHint = getTenantRequestHint()
    if (tenantHint) {
      headers['X-Tenant-ID'] = tenantHint
    }
  }
  return headers
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

function notifySessionExpired(): void {
  if (typeof window === 'undefined' || sessionExpiryEventDispatched) return
  sessionExpiryEventDispatched = true
  window.dispatchEvent(
    new CustomEvent('session-expired', {
      detail: {
        title: 'Session expirée',
        message: 'Votre session a expiré. Veuillez vous reconnecter.',
      },
    })
  )
}

export function resetSessionExpirySignal(): void {
  sessionExpiryEventDispatched = false
}

function formatApiDetail(detail: any): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const loc = Array.isArray(item.loc) ? item.loc.join(' > ') : item.loc
          const msg = item.msg || item.message || JSON.stringify(item)
          return loc ? `${loc}: ${msg}` : String(msg)
        }
        return String(item)
      })
      .filter(Boolean)
    return parts.length ? parts.join(' | ') : JSON.stringify(detail)
  }
  if (typeof detail === 'object') {
    return detail.message || JSON.stringify(detail)
  }
  return String(detail)
}

function formatRetryDelay(retryAfter: string | null): string | null {
  if (!retryAfter) return null
  const seconds = Number.parseInt(retryAfter, 10)
  if (!Number.isFinite(seconds) || seconds <= 0) return null
  if (seconds < 60) return `${seconds} seconde${seconds > 1 ? 's' : ''}`
  const minutes = Math.ceil(seconds / 60)
  return `${minutes} minute${minutes > 1 ? 's' : ''}`
}

function fallbackApiMessage(status: number, path = '', retryAfter: string | null = null): string {
  if (status === 401) {
    return 'Vous devez être connecté pour accéder à cette ressource.'
  }
  if (status === 403) {
    return "Accès refusé : votre compte n'a pas les droits nécessaires pour effectuer cette action."
  }
  if (status === 404) {
    return "Ressource introuvable ou inaccessible avec vos droits actuels."
  }
  if (status === 429) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`
    const retryDelay = formatRetryDelay(retryAfter)
    if (normalizedPath === '/auth/login') {
      return `Limite atteinte : 3 tentatives de connexion maximum. Réessayez ${retryDelay ? `dans ${retryDelay}` : 'dans 3 minutes'}.`
    }
    if (normalizedPath === '/auth/request-password-reset' || normalizedPath === '/auth/bootstrap-admin') {
      return `Limite atteinte : 3 tentatives maximum par minute. Réessayez ${retryDelay ? `dans ${retryDelay}` : 'dans 1 minute'}.`
    }
    if (normalizedPath === '/auth/refresh') {
      return `Limite atteinte : 10 tentatives maximum par minute. Réessayez ${retryDelay ? `dans ${retryDelay}` : 'dans 1 minute'}.`
    }
    return `Trop de tentatives. Réessayez ${retryDelay ? `dans ${retryDelay}` : 'dans 1 minute'}.`
  }
  return `HTTP ${status}`
}

function normalizeApiMessage(message: string, status: number, path = '', retryAfter: string | null = null): string {
  const normalized = message.toLowerCase()
  if (status === 403) {
    if (
      !message ||
      message === `HTTP ${status}` ||
      normalized === 'forbidden' ||
      normalized === 'not authenticated' ||
      normalized === 'not authorized'
    ) {
      return fallbackApiMessage(status, path, retryAfter)
    }
    if (
      normalized.includes('privilèges insuffisants') ||
      normalized.includes('privileges insuffisants') ||
      normalized.includes('permissions requises') ||
      normalized.includes('permission required')
    ) {
      return `Accès refusé : ${message}`
    }
  }

  if (status === 401 && (message === `HTTP ${status}` || normalized === 'unauthorized')) {
    return fallbackApiMessage(status, path, retryAfter)
  }

  if (
    status === 401 &&
    (normalized.includes('invalid credentials') ||
      normalized.includes('incorrect username') ||
      normalized.includes('incorrect password'))
  ) {
    return 'Adresse e-mail ou mot de passe incorrect. Vérifiez vos informations puis réessayez.'
  }

  if (status === 429) {
    if (
      message === `HTTP ${status}` ||
      normalized.includes('rate limit') ||
      normalized.includes('too many') ||
      normalized.includes('many requests')
    ) {
      return fallbackApiMessage(status, path, retryAfter)
    }
  }
  if (status === 404 && message === `HTTP ${status}`) {
    return fallbackApiMessage(status, path, retryAfter)
  }
  return message
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

// ── Délai utilitaire ────────────────────────────────────────────────────────

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function normalizePath(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    const parsed = new URL(path)
    return parsed.pathname
  }
  return path.startsWith('/') ? path : `/${path}`
}

function shouldRetryTransientRequest(method: HttpMethod, path: string): boolean {
  const normalized = normalizePath(path)
  return method === 'GET' || method === 'DELETE' || normalized === '/auth/refresh'
}

// ── Requête principale ───────────────────────────────────────────────────────

async function apiRequestInternal<T = any>(
  method: HttpMethod,
  path: string,
  options: ApiOptions | undefined,
  hasRetried: boolean,
  networkRetryCount: number = 0,
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

  const headers = getAuthHeaders(path)

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

  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: payload,
      credentials: 'include', // nécessaire pour envoyer le cookie HttpOnly de refresh
    })
  } catch (networkErr: any) {
    // Erreur réseau (ECONNREFUSED, ECONNRESET, backend en démarrage…)
    // Retry avec backoff sur les méthodes sûres et le refresh de session.
    if (shouldRetryTransientRequest(method, path) && networkRetryCount < TRANSIENT_RETRY_DELAYS.length) {
      await delay(TRANSIENT_RETRY_DELAYS[networkRetryCount])
      return apiRequestInternal<T>(method, path, options, hasRetried, networkRetryCount + 1)
    }
    throw new ApiError(
      "Connexion impossible avec le serveur. Vérifiez votre réseau ou que l'application backend locale est démarrée.",
      503,
      { detail: networkErr?.message ?? 'Network error' },
    )
  }

  if (
    TRANSIENT_STATUS_CODES.has(resp.status) &&
    shouldRetryTransientRequest(method, path) &&
    networkRetryCount < TRANSIENT_RETRY_DELAYS.length
  ) {
    await delay(TRANSIENT_RETRY_DELAYS[networkRetryCount])
    return apiRequestInternal<T>(method, path, options, hasRetried, networkRetryCount + 1)
  }

  if (resp.ok) {
    const data = await parseJsonSafely(resp)
    return data as T
  }

  const errPayload = await parseJsonSafely(resp)
  const message = normalizeApiMessage(
    formatApiDetail(errPayload?.detail) ||
    formatApiDetail(errPayload?.message) ||
    fallbackApiMessage(resp.status, path, resp.headers.get('retry-after')),
    resp.status,
    path,
    resp.headers.get('retry-after'),
  )

  if (resp.status === 402 && typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('payment-required', {
        detail: { message, payload: errPayload },
      })
    )
  }

  // Sur 401, tenter un refresh silencieux (une seule fois).
  if (resp.status === 401 && !hasRetried && !url.endsWith('/auth/refresh') && !url.endsWith('/auth/login')) {
    const refreshed = await tryRefreshToken()
    if (refreshed) {
      return apiRequestInternal<T>(method, path, options, true, networkRetryCount)
    }
    setAccessToken(null)
    notifySessionExpired()
  }

  throw new ApiError(message, resp.status, errPayload)
}

// ── Refresh silencieux via cookie HttpOnly ───────────────────────────────────

async function tryRefreshToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = refreshTokenOnce().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

async function refreshTokenOnce(): Promise<boolean> {
  const url = buildUrl('/auth/refresh')
  for (let attempt = 0; attempt <= TRANSIENT_RETRY_DELAYS.length; attempt += 1) {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        credentials: 'include',
      })
      if (TRANSIENT_STATUS_CODES.has(resp.status) && attempt < TRANSIENT_RETRY_DELAYS.length) {
        await delay(TRANSIENT_RETRY_DELAYS[attempt])
        continue
      }
      if (!resp.ok) {
        setAccessToken(null)
        return false
      }
      const data = await parseJsonSafely(resp)
      const token = data?.access_token
      if (token) {
        setAccessToken(token)
        resetSessionExpirySignal()
        return true
      }
      setAccessToken(null)
      return false
    } catch {
      if (attempt < TRANSIENT_RETRY_DELAYS.length) {
        await delay(TRANSIENT_RETRY_DELAYS[attempt])
        continue
      }
      setAccessToken(null)
      return false
    }
  }
  setAccessToken(null)
  return false
}

// ── Export public ────────────────────────────────────────────────────────────

export async function apiRequest<T = any>(
  method: HttpMethod,
  path: string,
  options?: ApiOptions,
): Promise<T> {
  return apiRequestInternal<T>(method, path, options, false)
}
