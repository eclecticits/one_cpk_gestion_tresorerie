/**
 * Contrôleur de tilt 3D global (délégué).
 *
 * Un unique écouteur `pointermove` sur le document applique un léger effet de
 * profondeur (rotation suivant le curseur) à n'importe quel conteneur "carte"
 * de l'application, sans avoir à modifier chaque page/composant.
 *
 * - Ciblage : `.card` (classe globale) + les conteneurs CSS-modules dont le
 *   nom local est `card`/`*Card` (le suffixe `_hash` garantit le `_` final,
 *   ce qui évite d'attraper les sous-éléments type `cardHeader`, `cardGrid`…).
 * - La rotation est écrite dans `--tilt-x` / `--tilt-y` ; l'élévation (lift) et
 *   les ombres teintées par tenant sont gérées en CSS (voir index.css).
 * - Respecte `prefers-reduced-motion`, ignore le tactile, exclut les modales.
 * - Throttlé via requestAnimationFrame pour rester fluide.
 */

const SELECTOR = '.card, [class*="card_"], [class*="Card_"]'
const MAX_DEG = 3.5

function isExcluded(el: Element): boolean {
  return el.closest('[class*="modalCard"], [role="dialog"], dialog') !== null
}

export function initTilt3d(): () => void {
  if (typeof window === 'undefined') return () => {}

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  let current: HTMLElement | null = null
  let raf = 0
  let nextX = 0
  let nextY = 0

  const flush = (): void => {
    raf = 0
    if (!current) return
    current.style.setProperty('--tilt-x', `${nextX.toFixed(2)}deg`)
    current.style.setProperty('--tilt-y', `${nextY.toFixed(2)}deg`)
  }

  const clear = (el: HTMLElement | null): void => {
    if (!el) return
    el.classList.remove('is-tilting')
    el.style.removeProperty('--tilt-x')
    el.style.removeProperty('--tilt-y')
  }

  const onMove = (event: PointerEvent): void => {
    if (reduceMotion.matches || event.pointerType === 'touch') return

    const target = event.target as Element | null
    const card = target ? target.closest<HTMLElement>(SELECTOR) : null

    if (!card || isExcluded(card)) {
      if (current) {
        clear(current)
        current = null
      }
      return
    }

    if (card !== current) {
      if (current) clear(current)
      current = card
      card.classList.add('is-tilting')
    }

    const rect = card.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return
    const px = (event.clientX - rect.left) / rect.width - 0.5
    const py = (event.clientY - rect.top) / rect.height - 0.5
    nextX = -py * MAX_DEG
    nextY = px * MAX_DEG

    if (!raf) raf = requestAnimationFrame(flush)
  }

  const onLeave = (): void => {
    if (current) {
      clear(current)
      current = null
    }
  }

  document.addEventListener('pointermove', onMove, { passive: true })
  document.addEventListener('pointerleave', onLeave, { passive: true })
  window.addEventListener('blur', onLeave)

  return () => {
    document.removeEventListener('pointermove', onMove)
    document.removeEventListener('pointerleave', onLeave)
    window.removeEventListener('blur', onLeave)
    if (raf) cancelAnimationFrame(raf)
    clear(current)
    current = null
  }
}
