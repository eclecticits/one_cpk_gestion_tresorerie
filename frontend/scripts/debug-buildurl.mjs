// Repro for buildUrl relative base behavior.

function beforeBuildUrl(base, path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return new URL(`${base}${normalizedPath}`)
}

function afterBuildUrl(base, path, origin) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const fullPath = `${base}${normalizedPath}`
  return base.startsWith('/') ? new URL(fullPath, origin) : new URL(fullPath)
}

const base = '/api/v1'
const path = '/auth/login'
const origin = 'http://localhost:5173'

console.log('Base =', base, 'Path =', path)

try {
  const url = beforeBuildUrl(base, path)
  console.log('BEFORE URL =', url.toString())
} catch (err) {
  console.log('BEFORE ERROR =', err instanceof Error ? err.message : String(err))
}

try {
  const url = afterBuildUrl(base, path, origin)
  console.log('AFTER URL =', url.toString())
} catch (err) {
  console.log('AFTER ERROR =', err instanceof Error ? err.message : String(err))
}
