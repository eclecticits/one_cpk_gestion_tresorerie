import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import styles from './BackButton.module.css'

type BackButtonProps = {
  fallback?: string
  label?: string
  className?: string
}

export default function BackButton({ fallback = '/dashboard', label = 'Retour', className = '' }: BackButtonProps) {
  const navigate = useNavigate()

  const handleClick = () => {
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
