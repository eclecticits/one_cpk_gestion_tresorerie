import { useEffect, type RefObject } from 'react'

/** Le premier ancêtre qui défile verticalement ; null s'il s'agit de la fenêtre. */
function ancetreDefilant(element: HTMLElement): HTMLElement | null {
  let parent = element.parentElement
  while (parent) {
    const { overflowY } = getComputedStyle(parent)
    if ((overflowY === 'auto' || overflowY === 'scroll') && parent.scrollHeight > parent.clientHeight) return parent
    parent = parent.parentElement
  }
  return null
}

/**
 * Garde l'en-tête d'un tableau visible quand la page défile.
 *
 * Le cadre du tableau défile lui-même (overflow: auto, pour la largeur) : un
 * `position: sticky` sur les <th> ne s'accroche qu'à ce cadre, et l'en-tête
 * part avec lui dès que c'est la page qui défile. On décale alors le <thead>
 * de la portion du cadre passée au-dessus du haut de la zone visible, sans
 * jamais dépasser le bas du cadre.
 */
export function useEnteteFlottant(
  cadreRef: RefObject<HTMLElement | null>,
  enteteRef: RefObject<HTMLElement | null>,
  dependance?: unknown,
) {
  useEffect(() => {
    const cadre = cadreRef.current
    const entete = enteteRef.current
    if (!cadre || !entete) return
    let image = 0

    const placer = () => {
      image = 0
      const defilant = ancetreDefilant(cadre)
      const haut = defilant ? defilant.getBoundingClientRect().top : 0
      const rect = cadre.getBoundingClientRect()
      const maximum = Math.max(0, cadre.clientHeight - entete.offsetHeight)
      const decalage = Math.min(Math.max(0, haut - rect.top), maximum)
      entete.style.transform = decalage > 0 ? `translateY(${decalage}px)` : ''
    }
    const demander = () => {
      if (!image) image = requestAnimationFrame(placer)
    }

    // Capture : les défilements d'un conteneur ne remontent pas jusqu'au document.
    document.addEventListener('scroll', demander, { capture: true, passive: true })
    window.addEventListener('resize', demander)
    placer()
    return () => {
      document.removeEventListener('scroll', demander, { capture: true })
      window.removeEventListener('resize', demander)
      if (image) cancelAnimationFrame(image)
      entete.style.transform = ''
    }
  }, [cadreRef, enteteRef, dependance])
}
