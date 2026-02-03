import { useEffect } from 'react'
import styles from './NotificationModal.module.css'

interface NotificationModalProps {
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message: string
  details?: string
  onClose: () => void
  autoClose?: boolean
  autoCloseDelay?: number
}

export default function NotificationModal({
  type,
  title,
  message,
  details,
  onClose,
  autoClose = false,
  autoCloseDelay = 3000
}: NotificationModalProps) {
  useEffect(() => {
    if (autoClose && type === 'success') {
      const timer = setTimeout(() => {
        onClose()
      }, autoCloseDelay)
      return () => clearTimeout(timer)
    }
  }, [autoClose, autoCloseDelay, onClose, type])

  const getIcon = () => {
    switch (type) {
      case 'success':
        return '✓'
      case 'error':
        return '✕'
      case 'warning':
        return '⚠'
      case 'info':
        return 'ℹ'
    }
  }

  const getColors = () => {
    switch (type) {
      case 'success':
        return {
          bg: 'linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%)',
          border: '#10b981',
          iconBg: '#10b981',
          titleColor: '#065f46',
          textColor: '#047857'
        }
      case 'error':
        return {
          bg: 'linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)',
          border: '#ef4444',
          iconBg: '#ef4444',
          titleColor: '#7f1d1d',
          textColor: '#991b1b'
        }
      case 'warning':
        return {
          bg: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
          border: '#f59e0b',
          iconBg: '#f59e0b',
          titleColor: '#78350f',
          textColor: '#92400e'
        }
      case 'info':
        return {
          bg: 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)',
          border: '#3b82f6',
          iconBg: '#3b82f6',
          titleColor: '#1e3a8a',
          textColor: '#1e40af'
        }
    }
  }

  const colors = getColors()

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.content} style={{ background: colors.bg, border: `2px solid ${colors.border}` }}>
          <div className={styles.header}>
            <div className={styles.iconWrapper} style={{ background: colors.iconBg }}>
              <span className={styles.icon}>{getIcon()}</span>
            </div>
            <button onClick={onClose} className={styles.closeBtn} style={{ color: colors.textColor }}>
              ×
            </button>
          </div>

          <div className={styles.body}>
            <h3 className={styles.title} style={{ color: colors.titleColor }}>
              {title}
            </h3>
            <p className={styles.message} style={{ color: colors.textColor }}>
              {message}
            </p>
            {details && (
              <div className={styles.details} style={{
                color: colors.textColor,
                background: 'rgba(255, 255, 255, 0.5)',
                borderLeft: `3px solid ${colors.border}`
              }}>
                {details}
              </div>
            )}
          </div>

          <div className={styles.footer}>
            <button
              onClick={onClose}
              className={styles.okBtn}
              style={{
                background: colors.iconBg,
                color: 'white'
              }}
            >
              {type === 'success' ? 'Parfait !' : 'Compris'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
