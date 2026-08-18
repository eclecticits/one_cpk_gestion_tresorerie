import { useEffect, useState } from 'react'
import './PageLoader.css'

interface PageLoaderProps {
  label?: string
  compact?: boolean
  /**
   * Délai avant d'afficher le visuel, en ms. La plupart des gardes de route se
   * résolvent en quelques dizaines de ms : sans ce délai le loader ne fait que
   * clignoter. Le fond reste peint pendant l'attente, seul le contenu est différé.
   */
  delay?: number
}

export default function PageLoader({
  label = 'Chargement…',
  compact = false,
  delay = 220,
}: PageLoaderProps) {
  const [visible, setVisible] = useState(delay <= 0)

  useEffect(() => {
    if (delay <= 0) return
    const timer = window.setTimeout(() => setVisible(true), delay)
    return () => window.clearTimeout(timer)
  }, [delay])

  return (
    <div
      className={`onec-page-loader ${compact ? 'compact' : ''}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      {visible && (
        <div className="onec-loader-inner">
          <div className="onec-loader-brand" aria-hidden="true">
            ONEC <span>Smart</span>
          </div>
          <div className="onec-loader-track" aria-hidden="true">
            <span />
          </div>
          <p className="onec-loader-label">{label}</p>
        </div>
      )}
    </div>
  )
}
