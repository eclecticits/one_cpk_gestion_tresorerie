import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

// Un module chargé à la demande peut manquer sans que le code soit en faute :
// en production, un déploiement a remplacé les fichiers que l'onglet ouvert
// connaissait ; en développement, Vite recharge pendant qu'un fichier s'écrit.
// React.lazy garde alors l'échec pour toujours, et l'écran reste en erreur
// alors qu'un simple rechargement suffirait. On le fait à la place de l'agent.

const CHUNK_ERROR =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS/i

const RELOAD_KEY = 'onec:chunk-reload-at'
// Un seul rechargement automatique par fenêtre : si le module manque encore
// après, c'est une vraie panne, et elle doit se voir au lieu de boucler.
const RELOAD_WINDOW_MS = 10_000
const RETRY_DELAY_MS = 500

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return CHUNK_ERROR.test(message)
}

/** Recharge la page, sauf si on vient déjà de le faire. Dit si elle recharge. */
export function reloadOnceForChunkError(): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
    if (Date.now() - last < RELOAD_WINDOW_MS) return false
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  } catch {
    // Sans stockage, pas de garde contre la boucle : on laisse l'erreur se voir.
    return false
  }
  window.location.reload()
  return true
}

const wait = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

export function lazyWithRetry<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      return await factory()
    } catch (error) {
      if (!isChunkLoadError(error)) throw error
      await wait(RETRY_DELAY_MS)
      try {
        return await factory()
      } catch (retryError) {
        // La page se recharge : on reste sur l'écran de chargement d'ici là.
        if (isChunkLoadError(retryError) && reloadOnceForChunkError()) {
          return new Promise<never>(() => {})
        }
        throw retryError
      }
    }
  })
}
