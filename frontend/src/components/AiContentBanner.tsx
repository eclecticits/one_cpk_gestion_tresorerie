import { Sparkles } from 'lucide-react'

interface AiContentBannerProps {
  /** Message optionnel pour préciser le contexte (ex. « avant envoi »). */
  message?: string
  compact?: boolean
}

/**
 * Bandeau de transparence IA (conformité Google/Apple + RGPD).
 * À afficher sur toute vue produisant du contenu généré par intelligence
 * artificielle (synthèses, classifications, brouillons de courrier/PV…).
 */
export default function AiContentBanner({ message, compact = false }: AiContentBannerProps) {
  return (
    <div
      role="note"
      aria-label="Avertissement contenu généré par intelligence artificielle"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: compact ? '8px 12px' : '10px 14px',
        margin: compact ? '0 0 10px' : '0 0 16px',
        background: '#eef2ff',
        border: '1px solid #c7d2fe',
        borderRadius: '8px',
        color: '#3730a3',
        fontSize: compact ? '12px' : '13px',
        lineHeight: 1.4,
      }}
    >
      <Sparkles size={compact ? 14 : 16} style={{ flexShrink: 0 }} aria-hidden="true" />
      <span>
        {message ||
          "Contenu généré par une intelligence artificielle. Il peut comporter des erreurs : relisez-le et validez-le avant toute utilisation ou envoi. Aucune action sensible n'est exécutée automatiquement."}
      </span>
    </div>
  )
}
