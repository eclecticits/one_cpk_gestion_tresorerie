import styles from './ConfirmModal.module.css'

interface ConfirmModalProps {
  isOpen: boolean
  onConfirm: () => void
  onCancel: () => void
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  type?: 'warning' | 'danger' | 'info'
}

export default function ConfirmModal({
  isOpen,
  onConfirm,
  onCancel,
  title,
  message,
  confirmText = 'Confirmer',
  cancelText = 'Annuler',
  type = 'warning',
}: ConfirmModalProps) {
  if (!isOpen) return null

  const handleConfirm = () => {
    onConfirm()
  }

  const handleCancel = () => {
    onCancel()
  }

  const getIcon = () => {
    switch (type) {
      case 'danger':
        return '⚠️'
      case 'warning':
        return '⚠️'
      case 'info':
        return 'ℹ️'
      default:
        return '⚠️'
    }
  }

  return (
    <div className={styles.overlay} onClick={handleCancel}>
      <div className={`${styles.modal} ${styles[type]}`} onClick={(e) => e.stopPropagation()}>
        <div className={styles.iconWrapper}>
          <span className={styles.icon}>{getIcon()}</span>
        </div>

        <div className={styles.content}>
          <h2 className={styles.title}>{title}</h2>
          <div className={styles.message}>
            {message.split('\n').map((line, index) => (
              line ? <p key={index}>{line}</p> : <br key={index} />
            ))}
          </div>
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            onClick={handleCancel}
            className={styles.cancelBtn}
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            className={`${styles.confirmBtn} ${styles[`${type}Btn`]}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
