import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Cache "stale-while-revalidate" léger, SANS dépendance externe.
 *
 * Objectif rapidité : afficher immédiatement les données déjà connues (cache),
 * puis rafraîchir en arrière-plan. Évite les rechargements complets à chaque
 * navigation, sans introduire de bibliothèque (react-query/SWR).
 *
 * ⚠️ Pour des LISTES financières mutables (réquisitions, sorties…), pensez à
 * appeler `invalidate()` / `invalidateResource(key)` après chaque mutation
 * (création, validation, paiement) pour ne jamais afficher un état périmé.
 * Idéal d'emblée pour les données de RÉFÉRENCE peu changeantes : services,
 * postes budgétaires, rubriques, paramètres d'impression.
 */

interface CacheEntry<T> {
  data: T
  ts: number
}

const cache = new Map<string, CacheEntry<unknown>>()

/** Invalide une clé précise, ou tout le cache si aucune clé n'est fournie. */
export function invalidateResource(key?: string): void {
  if (key) cache.delete(key)
  else cache.clear()
}

/** Écrit/mets à jour manuellement une entrée (ex. après une mutation optimiste). */
export function primeResource<T>(key: string, data: T): void {
  cache.set(key, { data, ts: Date.now() })
}

interface UseCachedResourceOptions {
  /** Durée (ms) avant de considérer l'entrée périmée et rafraîchir. Défaut 60 s. */
  ttlMs?: number
  /** Désactive le chargement (ex. dépend d'un id pas encore prêt). Défaut true. */
  enabled?: boolean
}

interface UseCachedResourceResult<T> {
  data: T | undefined
  loading: boolean
  error: unknown
  /** Force un rechargement immédiat et met à jour le cache. */
  revalidate: () => Promise<T | undefined>
  /** Invalide l'entrée de cache de cette ressource. */
  invalidate: () => void
}

export function useCachedResource<T>(
  key: string,
  fetcher: () => Promise<T>,
  options?: UseCachedResourceOptions,
): UseCachedResourceResult<T> {
  const ttlMs = options?.ttlMs ?? 60_000
  const enabled = options?.enabled ?? true

  const initial = cache.get(key) as CacheEntry<T> | undefined
  const [data, setData] = useState<T | undefined>(initial?.data)
  const [loading, setLoading] = useState<boolean>(!initial)
  const [error, setError] = useState<unknown>(null)

  // Garde la dernière version du fetcher sans relancer l'effet à chaque render.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const revalidate = useCallback(async (): Promise<T | undefined> => {
    try {
      const result = await fetcherRef.current()
      cache.set(key, { data: result, ts: Date.now() })
      setData(result)
      setError(null)
      return result
    } catch (e) {
      setError(e)
      return undefined
    } finally {
      setLoading(false)
    }
  }, [key])

  useEffect(() => {
    if (!enabled) return
    const entry = cache.get(key) as CacheEntry<T> | undefined
    if (entry) {
      setData(entry.data) // affichage immédiat des données en cache (éventuellement périmées)
      const isFresh = Date.now() - entry.ts < ttlMs
      if (isFresh) {
        setLoading(false)
      } else {
        void revalidate() // rafraîchissement silencieux en arrière-plan
      }
    } else {
      setLoading(true)
      void revalidate()
    }
  }, [key, enabled, ttlMs, revalidate])

  const invalidate = useCallback(() => invalidateResource(key), [key])

  return { data, loading, error, revalidate, invalidate }
}
