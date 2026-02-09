import { createContext, useCallback, useContext, useRef, useState } from 'react'
import styles from './ConfirmDialog.module.css'

export type ConfirmVariant = 'default' | 'danger'

export interface ConfirmOptions {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  variant?: ConfirmVariant
  inputLabel?: string
  inputPlaceholder?: string
  inputRequired?: boolean
  inputMultiline?: boolean
  inputRows?: number
  inputInitialValue?: string
}

type ConfirmState = ConfirmOptions & { open: boolean }

interface ConfirmContextType {
  confirm: (options: ConfirmOptions) => Promise<boolean>
  confirmWithInput: (options: ConfirmOptions) => Promise<{ confirmed: boolean; value: string }>
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
  const inputResolverRef = useRef<((value: { confirmed: boolean; value: string }) => void) | null>(null)
  const [inputValue, setInputValue] = useState('')

  const confirm = useCallback((options: ConfirmOptions) => {
    setInputValue(options.inputInitialValue ?? '')
    setState({
      open: true,
      title: options.title,
      description: options.description ?? '',
      confirmText: options.confirmText ?? 'Confirmer',
      cancelText: options.cancelText ?? 'Annuler',
      variant: options.variant ?? 'default',
      inputLabel: options.inputLabel,
      inputPlaceholder: options.inputPlaceholder,
      inputRequired: options.inputRequired,
      inputMultiline: options.inputMultiline,
      inputRows: options.inputRows,
      inputInitialValue: options.inputInitialValue,
    })
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve
    })
  }, [])

  const confirmWithInput = useCallback((options: ConfirmOptions) => {
    setInputValue(options.inputInitialValue ?? '')
    setState({
      open: true,
      title: options.title,
      description: options.description ?? '',
      confirmText: options.confirmText ?? 'Confirmer',
      cancelText: options.cancelText ?? 'Annuler',
      variant: options.variant ?? 'default',
      inputLabel: options.inputLabel ?? 'Motif',
      inputPlaceholder: options.inputPlaceholder ?? '',
      inputRequired: options.inputRequired ?? true,
      inputMultiline: options.inputMultiline ?? true,
      inputRows: options.inputRows ?? 3,
      inputInitialValue: options.inputInitialValue,
    })
    return new Promise<{ confirmed: boolean; value: string }>((resolve) => {
      inputResolverRef.current = resolve
    })
  }, [])

  const handleClose = (result: boolean) => {
    setState((prev) => ({ ...prev, open: false }))
    if (resolverRef.current) {
      resolverRef.current(result)
      resolverRef.current = null
    }
    if (inputResolverRef.current) {
      inputResolverRef.current({ confirmed: result, value: inputValue.trim() })
      inputResolverRef.current = null
    }
  }

  return (
    <ConfirmContext.Provider value={{ confirm, confirmWithInput }}>
      {children}
      {state.open && (
        <div className={styles.backdrop} role="presentation" onClick={() => handleClose(false)}>
          <div className={styles.dialog} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className={styles.header}>
              <h3>{state.title}</h3>
            </div>
            {state.description && <p className={styles.description}>{state.description}</p>}
            {state.inputLabel && (
              <div className={styles.inputField}>
                <label>{state.inputLabel}</label>
                {state.inputMultiline ? (
                  <textarea
                    rows={state.inputRows ?? 3}
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder={state.inputPlaceholder}
                  />
                ) : (
                  <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder={state.inputPlaceholder}
                  />
                )}
              </div>
            )}
            <div className={styles.actions}>
              <button className={styles.cancelBtn} onClick={() => handleClose(false)}>
                {state.cancelText}
              </button>
              <button
                className={`${styles.confirmBtn} ${state.variant === 'danger' ? styles.confirmDanger : ''}`}
                onClick={() => handleClose(true)}
                disabled={state.inputRequired && state.inputLabel ? inputValue.trim().length === 0 : false}
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

export function useConfirmWithInput() {
  const context = useContext(ConfirmContext)
  if (!context) {
    throw new Error('useConfirmWithInput must be used within a ConfirmProvider')
  }
  return context.confirmWithInput
}
