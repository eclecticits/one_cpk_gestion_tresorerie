import { getContrastColor } from '../utils/colors'
import styles from './ColorPreview.module.css'

interface PreviewProps {
  label: string
  bgColor: string
  type: 'sidebar' | 'button' | 'text'
  textColor?: string
}

export const ColorPreview = ({ label, bgColor, type, textColor }: PreviewProps) => {
  const resolvedTextColor = type === 'text' ? bgColor : textColor || getContrastColor(bgColor)
  const backgroundColor = type === 'text' ? 'transparent' : bgColor

  return (
    <div className={styles.previewRow}>
      <span className={styles.previewLabel}>Aperçu :</span>
      <span
        className={`${styles.chip} ${type === 'text' ? styles.chipText : ''}`}
        style={{ backgroundColor, color: resolvedTextColor }}
      >
        {label}
      </span>
    </div>
  )
}
