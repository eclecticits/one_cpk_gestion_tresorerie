import { useEffect, useState } from 'react'
import styles from './SuccessNotification.module.css'

interface SuccessNotificationProps {
  title: string
  message: string
  onClose: () => void
  duration?: number
}

export default function SuccessNotification({
  title,
  message,
  onClose,
  duration = 4000
}: SuccessNotificationProps) {
  const [isExiting, setIsExiting] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => {
      handleClose()
    }, duration)

    return () => clearTimeout(timer)
  }, [duration])

  const handleClose = () => {
    setIsExiting(true)
    setTimeout(() => {
      onClose()
    }, 300)
  }

  return (
    <>
      <div className={`${styles.overlay} ${isExiting ? styles.overlayExiting : ''}`} onClick={handleClose} />
      <div className={`${styles.notification} ${isExiting ? styles.exiting : ''}`}>
        <div className={styles.icon}>
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        </div>
        <div className={styles.content}>
          <div className={styles.title}>{title}</div>
          <div className={styles.message}>{message}</div>
        </div>
        <button type="button" className={styles.closeButton} onClick={handleClose}>
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      </div>
    </>
  )
}
