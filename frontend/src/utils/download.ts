import { API_BASE_URL, getAccessToken } from '../lib/apiClient'

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

  const headers: Record<string, string> = {}
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(url.toString(), {
    headers: { Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', ...headers },
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })
  if (!resp.ok) {
    throw new Error(`Export failed (HTTP ${resp.status})`)
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
