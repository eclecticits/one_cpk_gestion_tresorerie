import styles from './NetworkGlobe.module.css'

interface NetworkGlobeProps {
  /** Diamètre en pixels (défaut 52). */
  size?: number
  className?: string
}

/**
 * Globe filaire « réseau » animé, teinté par la couleur du tenant
 * (hérite de --tenant-primary via `color`). Les méridiens se resserrent
 * puis s'élargissent en décalé pour donner l'illusion d'une rotation.
 * Respecte prefers-reduced-motion (voir le module CSS).
 */
export default function NetworkGlobe({ size = 52, className }: NetworkGlobeProps) {
  return (
    <span
      className={`${styles.globe}${className ? ` ${className}` : ''}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 200 200" className={styles.svg}>
        <circle cx="100" cy="100" r="82" className={styles.halo} />
        <circle cx="100" cy="100" r="82" className={styles.outline} />

        <g className={styles.lat}>
          <line x1="18" y1="100" x2="182" y2="100" />
          <ellipse cx="100" cy="100" rx="81" ry="30" />
          <ellipse cx="100" cy="100" rx="81" ry="55" />
          <ellipse cx="100" cy="100" rx="81" ry="74" />
        </g>

        <g className={styles.meridians}>
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '0s' }} />
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '-1.5s' }} />
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '-3s' }} />
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '-4.5s' }} />
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '-6s' }} />
          <ellipse cx="100" cy="100" rx="81" ry="81" style={{ animationDelay: '-7.5s' }} />
        </g>

        <circle cx="100" cy="19" r="3.4" className={styles.pole} />
        <circle cx="100" cy="181" r="3.4" className={styles.pole} />

        <circle cx="140" cy="70" r="3" className={styles.node} style={{ animationDelay: '0s' }} />
        <circle cx="62" cy="118" r="3" className={styles.node} style={{ animationDelay: '-1.1s' }} />
        <circle cx="128" cy="140" r="3" className={styles.node} style={{ animationDelay: '-2.2s' }} />
      </svg>
    </span>
  )
}
