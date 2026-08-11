import { useEffect, useState } from 'react'

/**
 * Valeur retardée, destinée aux filtres de recherche qui déclenchent un appel
 * réseau.
 *
 * Sans elle, un champ texte relié à une requête serveur provoque un
 * aller-retour par caractère saisi : la frappe devient saccadée et les réponses
 * peuvent revenir dans le désordre. On garde donc la valeur immédiate pour
 * l'affichage du champ (la saisie reste fluide) et on n'interroge le serveur
 * qu'une fois la frappe stabilisée.
 *
 * `delay` par défaut à 300 ms, cohérent avec l'écran Clients qui a introduit ce
 * comportement dans le projet.
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(id)
  }, [value, delay])

  return debounced
}
