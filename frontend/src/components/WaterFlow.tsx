import { createPortal } from 'react-dom'
import styles from './WaterFlow.module.css'

interface WaterFlowProps {
  /** Hauteur de la bande d'eau en pixels (défaut 120). */
  height?: number
  className?: string
}

/**
 * Bande d'eau animée FIXÉE en bas de l'écran (toujours visible, ne défile pas
 * avec le contenu). Rendue via un portail vers document.body pour échapper au
 * wrapper de page animé (translate) qui casserait un position:fixed classique.
 *
 * Trois couches de vagues défilent horizontalement (vitesses/sens différents)
 * pour l'effet d'eau qui coule. Teintée par --tenant-primary (défini sur :root,
 * donc hérité même depuis body). z-index sous la sidebar/nav/modales.
 * Coupée si prefers-reduced-motion.
 */
export default function WaterFlow({ height = 120, className }: WaterFlowProps) {
  if (typeof document === 'undefined') return null

  return createPortal(
    <div
      className={`${styles.water}${className ? ` ${className}` : ''}`}
      style={{ height }}
      aria-hidden="true"
    >
      <svg className={styles.layerBack} viewBox="0 0 2880 150" preserveAspectRatio="none">
        <path d="M0,78 C240,48 480,48 720,78 C960,108 1200,108 1440,78 C1680,48 1920,48 2160,78 C2400,108 2640,108 2880,78 L2880,150 L0,150 Z" />
      </svg>
      <svg className={styles.layerMid} viewBox="0 0 2880 150" preserveAspectRatio="none">
        <path d="M0,92 C240,60 480,60 720,92 C960,124 1200,124 1440,92 C1680,60 1920,60 2160,92 C2400,124 2640,124 2880,92 L2880,150 L0,150 Z" />
      </svg>
      <svg className={styles.layerFront} viewBox="0 0 2880 150" preserveAspectRatio="none">
        <path d="M0,108 C240,132 480,132 720,108 C960,84 1200,84 1440,108 C1680,132 1920,132 2160,108 C2400,84 2640,84 2880,108 L2880,150 L0,150 Z" />
      </svg>
    </div>,
    document.body,
  )
}
