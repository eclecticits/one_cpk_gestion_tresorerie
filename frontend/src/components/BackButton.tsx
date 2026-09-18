import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import styles from './BackButton.module.css'

type BackButtonProps = {
  fallback?: string
  /**
   * Destination FIXE. Renseignée, le bouton y va toujours, au lieu de revenir
   * sur la page précédente : une sous-page a un parent, et « Retour » qui
   * dépend du chemin emprunté renvoie ailleurs à chaque visite — sur la même
   * page, le même bouton ne mène pas deux fois au même endroit.
   */
  to?: string
  label?: string
  className?: string
}

export default function BackButton({ fallback = '/dashboard', to, label = 'Retour', className = '' }: BackButtonProps) {
  const navigate = useNavigate()

  const handleClick = () => {
    if (to) {
      navigate(to)
      return
    }
    if (window.history.length > 1) {
      navigate(-1)
      return
    }
    navigate(fallback)
  }

  return (
    <button type="button" className={`${styles.button} ${className}`.trim()} onClick={handleClick}>
      <ArrowLeft size={16} aria-hidden="true" />
      {label}
    </button>
  )
}
