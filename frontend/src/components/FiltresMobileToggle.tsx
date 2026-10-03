import { ChevronDown, SlidersHorizontal } from 'lucide-react'
import styles from './FiltresMobileToggle.module.css'

interface Props {
  /** Panneau de filtres déplié (n'a d'effet visuel que sous 768 px). */
  ouvert: boolean
  onToggle: () => void
  /** Identifiant du panneau replié, pour aria-controls. */
  controle: string
  /** Nombre de filtres actifs : signalé sur le bouton quand le panneau est replié. */
  actifs?: number
  libelle?: string
}

/**
 * Bouton « Filtres » des pages à liste, visible uniquement sur téléphone.
 *
 * Au-delà de 768 px il n'est pas rendu à l'écran (display: none) et les
 * filtres restent affichés comme avant : c'est la page qui ne replie son
 * panneau que dans sa propre media query. Sous 768 px, le panneau est replié
 * par défaut pour que la liste apparaisse sans défiler.
 */
export default function FiltresMobileToggle({ ouvert, onToggle, controle, actifs = 0, libelle = 'Filtres' }: Props) {
  return (
    <button
      type="button"
      className={`${styles.toggle} ${ouvert ? styles.toggleOuvert : ''}`}
      onClick={onToggle}
      aria-expanded={ouvert}
      aria-controls={controle}
    >
      <SlidersHorizontal size={16} aria-hidden="true" />
      <span>{libelle}</span>
      {actifs > 0 && (
        <span className={styles.compteur} aria-label={`${actifs} filtre${actifs > 1 ? 's' : ''} actif${actifs > 1 ? 's' : ''}`}>
          {actifs}
        </span>
      )}
      <ChevronDown size={16} aria-hidden="true" className={styles.chevron} />
    </button>
  )
}
