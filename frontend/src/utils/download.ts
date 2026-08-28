import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'

type Params = Record<string, string | number | boolean | undefined | null>

export async function downloadExcel(path: string, params: Params, filename: string): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }
  const url = new URL(`${baseUrl}${path.startsWith('/') ? path : `/${path}`}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    url.searchParams.set(key, String(value))
  })

  const headers = {
    ...getAuthHeaders(),
    Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }

  const resp = await fetch(url.toString(), {
    headers,
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })
  if (!resp.ok) {
    // Le backend refuse explicitement un export trop volumineux (413) avec un
    // message qui dit quoi faire : restreindre la période ou les filtres. Sans
    // cette lecture du corps, l'utilisateur ne lisait que « Export failed (HTTP
    // 413) » — un code, aucune action possible, et le réflexe naturel est de
    // recliquer à l'identique. Le corps est du JSON FastAPI ({ detail }).
    let detail = ''
    try {
      const data = await resp.json()
      if (typeof data?.detail === 'string') detail = data.detail
    } catch {
      // Corps non JSON : 504 de nginx, page d'erreur HTML, réponse vide. On
      // retombe alors sur le code seul plutôt que d'afficher du bruit.
    }
    throw new Error(detail || `Export failed (HTTP ${resp.status})`)
  }

  const blob = await resp.blob()
  const downloadUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = downloadUrl
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(downloadUrl)
}

export async function openAuthenticatedFile(path: string): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }

  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  window.open(objectUrl, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}

export async function downloadAuthenticatedFile(path: string, filename: string): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }

  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(objectUrl)
}
