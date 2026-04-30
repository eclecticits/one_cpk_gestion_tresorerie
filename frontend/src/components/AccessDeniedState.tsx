import { Link } from 'react-router-dom'
import { LockKeyhole, ShieldAlert } from 'lucide-react'
import styles from './AccessDeniedState.module.css'

interface AccessDeniedStateProps {
  title?: string
  message: string
  actionLabel?: string
  actionTo?: string
}

export default function AccessDeniedState({
  title = 'Accès refusé',
  message,
  actionLabel = 'Retour au tableau de bord',
  actionTo = '/',
}: AccessDeniedStateProps) {
  return (
    <section className={styles.wrapper}>
      <div className={styles.card}>
        <div className={styles.iconWrap} aria-hidden="true">
          <ShieldAlert size={24} />
          <span className={styles.iconBadge}>
            <LockKeyhole size={14} />
          </span>
        </div>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.message}>{message}</p>
        <div className={styles.actions}>
          <Link to={actionTo} className={styles.primaryAction}>
            {actionLabel}
          </Link>
        </div>
      </div>
    </section>
  )
}
