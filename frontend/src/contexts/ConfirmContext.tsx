import { createContext, useCallback, useContext, useRef, useState } from 'react'
import styles from './ConfirmDialog.module.css'

export type ConfirmVariant = 'default' | 'danger'

export interface ConfirmOptions {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  variant?: ConfirmVariant
}

type ConfirmState = ConfirmOptions & { open: boolean }

interface ConfirmContextType {
  confirm: (options: ConfirmOptions) => Promise<boolean>
}

const ConfirmContext = createContext<ConfirmContextType | undefined>(undefined)

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConfirmState>({
    open: false,
    title: '',
    description: '',
    confirmText: 'Confirmer',
    cancelText: 'Annuler',
    variant: 'default',
  })
  const resolverRef = useRef<((value: boolean) => void) | null>(null)

  const confirm = useCallback((options: ConfirmOptions) => {
    setState({
      open: true,
      title: options.title,
      description: options.description ?? '',
      confirmText: options.confirmText ?? 'Confirmer',
      cancelText: options.cancelText ?? 'Annuler',
      variant: options.variant ?? 'default',
    })
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve
    })
  }, [])

  const handleClose = (result: boolean) => {
    setState((prev) => ({ ...prev, open: false }))
    if (resolverRef.current) {
      resolverRef.current(result)
      resolverRef.current = null
    }
  }

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      {state.open && (
        <div className={styles.backdrop} role="presentation" onClick={() => handleClose(false)}>
          <div className={styles.dialog} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className={styles.header}>
              <h3>{state.title}</h3>
            </div>
            {state.description && <p className={styles.description}>{state.description}</p>}
            <div className={styles.actions}>
              <button className={styles.cancelBtn} onClick={() => handleClose(false)}>
                {state.cancelText}
              </button>
              <button
                className={`${styles.confirmBtn} ${state.variant === 'danger' ? styles.confirmDanger : ''}`}
                onClick={() => handleClose(true)}
              >
                {state.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}

export function useConfirm() {
  const context = useContext(ConfirmContext)
  if (!context) {
    throw new Error('useConfirm must be used within a ConfirmProvider')
  }
  return context.confirm
}
