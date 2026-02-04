import { API_BASE_URL } from '../lib/apiClient'

type Params = Record<string, string | number | boolean | undefined | null>

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return (
    window.localStorage.getItem('access_token') ||
    window.localStorage.getItem('token') ||
    window.localStorage.getItem('onec_cpk_access_token')
  )
}

export async function downloadExcel(path: string, params: Params, filename: string): Promise<void> {
  const url = new URL(`${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`)
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
