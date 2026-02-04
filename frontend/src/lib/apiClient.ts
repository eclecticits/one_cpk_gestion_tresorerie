type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

const envApiBaseUrl = (import.meta as any).env?.VITE_API_BASE_URL

function normalizeApiBase(raw: string) {
  const trimmed = raw.trim().replace(/\/+$/, '')
  if (!trimmed) return ''
  if (trimmed.endsWith('/api/v1')) return trimmed
  if (trimmed.endsWith('/api')) return `${trimmed}/v1`
  return `${trimmed}/api/v1`
}

export const API_BASE_URL = normalizeApiBase(String(envApiBaseUrl || '')) || 'http://localhost:8000/api/v1'

if ((import.meta as any).env?.DEV) {
  console.log('API_BASE_URL =', API_BASE_URL)
}
const ACCESS_TOKEN_STORAGE_KEY = 'access_token'
const TOKEN_STORAGE_KEY = 'token'
const LEGACY_ACCESS_TOKEN_STORAGE_KEY = 'onec_cpk_access_token'

let accessToken: string | null = null
if (typeof window !== 'undefined') {
  accessToken =
    window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) ||
    window.localStorage.getItem(TOKEN_STORAGE_KEY)
  if (!accessToken) {
    accessToken = window.localStorage.getItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY)
    if (accessToken) {
      window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, accessToken)
      window.localStorage.removeItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY)
    }
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token
  if (typeof window === 'undefined') return
  if (token) {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token)
    window.localStorage.removeItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY)
  } else {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
    window.localStorage.removeItem(LEGACY_ACCESS_TOKEN_STORAGE_KEY)
  }
}

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

async function parseJsonSafely(resp: Response) {
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) return null
  try {
    return await resp.json()
  } catch {
    return null
  }
}

function buildUrl(path: string, params?: Record<string, any>) {
  const base = API_BASE_URL.replace(/\/+$/, '')
  let normalizedPath = path.startsWith('/') ? path : `/${path}`
  if (path.startsWith('http://') || path.startsWith('https://')) {
    const parsed = new URL(path)
    normalizedPath = `${parsed.pathname}${parsed.search}${parsed.hash}`
  }
  const fullPath = `${base}${normalizedPath}`
  const url = new URL(fullPath)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === null) return
      url.searchParams.set(k, String(v))
    })
  }
  return url.toString()
}

type ApiOptions =
  | any
  | {
      params?: Record<string, any>
      body?: any
    }

async function apiRequestInternal<T = any>(
  method: HttpMethod,
  path: string,
  options: ApiOptions | undefined,
  hasRetried: boolean
): Promise<T> {
  // Backward compatible:
  // - apiRequest('GET', '/x', { params: {...} })
  // - apiRequest('POST', '/x', payload)
  let params: Record<string, any> | undefined
  let body: any = undefined

  if (options && typeof options === 'object' && ('params' in options || 'body' in options)) {
    params = (options as any).params
    body = (options as any).body
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

  const runtimeToken =
    (typeof window !== 'undefined' &&
      (window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) ||
        window.localStorage.getItem(TOKEN_STORAGE_KEY))) ||
    accessToken
  if (runtimeToken) {
    headers.Authorization = `Bearer ${runtimeToken}`
  }

  // IMPORTANT: never send body on GET/DELETE (avoids "Failed to fetch")
  const hasBody = body !== undefined && method !== 'GET' && method !== 'DELETE'

  let payload: BodyInit | undefined
  if (hasBody) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const resp = await fetch(url, {
    method,
    headers,
    body: payload,
    credentials: 'include',
  })

  if (resp.ok) {
    const data = await parseJsonSafely(resp)
    return data as T
  }

  const errPayload = await parseJsonSafely(resp)
  const message = errPayload?.detail || errPayload?.message || `HTTP ${resp.status}`

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

export async function apiRequest<T = any>(method: HttpMethod, path: string, options?: ApiOptions): Promise<T> {
  return apiRequestInternal<T>(method, path, options, false)
}
