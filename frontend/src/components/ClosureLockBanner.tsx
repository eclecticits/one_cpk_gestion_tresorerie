import { Lock } from 'lucide-react'
import styles from './ClosureLockBanner.module.css'

interface ClosureLockBannerProps {
  isClosed: boolean
}

export default function ClosureLockBanner({ isClosed }: ClosureLockBannerProps) {
  if (!isClosed) return null
  return (
    <div className={styles.banner}>
      <div className={styles.iconWrap}>
        <Lock size={18} />
      </div>
      <div>
        <p className={styles.title}>Caisse clôturée pour aujourd&apos;hui</p>
        <p className={styles.subtitle}>
          Les opérations en espèces sont désactivées jusqu&apos;à demain. Les opérations bancaires restent disponibles.
        </p>
      </div>
    </div>
  )
}
