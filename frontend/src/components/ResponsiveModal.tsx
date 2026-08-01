import { ReactNode, useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useMobile } from '../hooks/useMobile'
import styles from './ResponsiveModal.module.css'

interface ResponsiveModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full'
  showCloseButton?: boolean
  className?: string
  contentClassName?: string
}

export function ResponsiveModal({
  isOpen,
  onClose,
  title,
  children,
  footer,
  size = 'md',
  showCloseButton = true,
  className = '',
  contentClassName = '',
}: ResponsiveModalProps) {
  const isMobile = useMobile()
  const titleId = useId()
  const modalRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!isOpen) return

    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    window.requestAnimationFrame(() => {
      const firstFocusable = getFocusableElements(modalRef.current)[0]
      ;(firstFocusable || modalRef.current)?.focus()
    })

    return () => {
      document.body.style.overflow = previousOverflow
      previousFocusRef.current?.focus()
    }
  }, [isOpen])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (!isOpen) return

      if (e.key === 'Escape') {
        onClose()
        return
      }

      if (e.key === 'Tab') {
        const focusable = getFocusableElements(modalRef.current)
        if (focusable.length === 0) {
          e.preventDefault()
          modalRef.current?.focus()
          return
        }

        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        const active = document.activeElement

        if (e.shiftKey && active === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && active === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }

  const modalSize = isMobile ? 'full' : size

  const modal = (
    <div className={styles.backdrop} onClick={handleBackdropClick}>
      <div 
        ref={modalRef}
        className={`${styles.modal} ${styles[modalSize]} ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={styles.header}>
          <h2 id={titleId} className={styles.title}>{title}</h2>
          {showCloseButton && (
            <button 
              className={styles.closeButton}
              onClick={onClose}
              aria-label="Fermer"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
        <div className={`${styles.content} ${contentClassName}`}>
          {children}
        </div>
        {footer && (
          <div className={styles.footer}>
            {footer}
          </div>
        )}
      </div>
    </div>
  )

  return createPortal(modal, document.body)
}

export default ResponsiveModal

function getFocusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) return []

  return Array.from(
    root.querySelectorAll<HTMLElement>(
      [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
      ].join(',')
    )
  ).filter((element) => !element.hasAttribute('hidden') && element.offsetParent !== null)
}
