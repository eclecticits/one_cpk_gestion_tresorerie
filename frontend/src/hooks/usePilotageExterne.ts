import { useEffect, useRef } from 'react'

/**
 * Laisse un composant à fenêtre (corriger le poste, changer le canal…) être
 * ouvert depuis un menu plutôt que par son propre bouton.
 *
 * - `declenchement` : compteur que le parent incrémente pour ouvrir. Tant qu'il
 *   est `undefined`, le composant garde son bouton habituel.
 * - `onDisponible` : le composant dit s'il s'applique (droit, statut, lignes),
 *   pour que le menu ne propose que ce qui est possible. Les règles restent
 *   écrites une seule fois, dans le composant.
 *
 * Renvoie la référence où le composant range sa fonction d'ouverture, une fois
 * définie : les hooks doivent passer avant ses `return null` de disponibilité.
 */
export function usePilotageExterne(
  declenchement: number | undefined,
  disponible: boolean,
  onDisponible?: (disponible: boolean) => void,
) {
  const ouvrirRef = useRef<(() => void) | null>(null)
  const signaler = useRef(onDisponible)
  signaler.current = onDisponible

  useEffect(() => {
    signaler.current?.(disponible)
  }, [disponible])

  // N'ouvre que sur un nouveau clic : remonté avec un compteur déjà avancé (la
  // fiche refermée puis rouverte), le composant ne doit pas s'ouvrir seul.
  const dernier = useRef(declenchement)
  useEffect(() => {
    if (declenchement && declenchement !== dernier.current) ouvrirRef.current?.()
    dernier.current = declenchement
  }, [declenchement])

  return ouvrirRef
}
