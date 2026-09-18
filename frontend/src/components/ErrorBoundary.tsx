import React from 'react'
import { isChunkLoadError, reloadOnceForChunkError } from '../utils/lazyWithRetry'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Un module qui n'a pas pu se charger n'est pas une panne du code : la
    // page se recharge d'elle-même, une fois, avant d'afficher quoi que ce soit.
    if (isChunkLoadError(error) && reloadOnceForChunkError()) return
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      const chargementInterrompu = isChunkLoadError(this.state.error)
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
          padding: '20px',
          backgroundColor: '#f8fafc'
        }}>
          <div style={{
            maxWidth: '600px',
            padding: '40px',
            backgroundColor: 'white',
            borderRadius: '8px',
            boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)'
          }}>
            <h1 style={{ color: '#dc2626', marginBottom: '16px', fontSize: '24px' }}>
              Erreur de chargement
            </h1>
            <p style={{ color: '#64748b', marginBottom: '16px' }}>
              {chargementInterrompu
                ? "Une partie de l'application n'a pas pu être chargée, probablement parce qu'une nouvelle version vient d'être installée. Rechargez la page."
                : "Une erreur est survenue lors du chargement de l'application."}
            </p>
            <div style={{
              padding: '12px',
              backgroundColor: '#fee2e2',
              borderRadius: '4px',
              marginBottom: '24px'
            }}>
              <code style={{ fontSize: '12px', color: '#991b1b', wordBreak: 'break-word' }}>
                {this.state.error?.message || 'Erreur inconnue'}
              </code>
            </div>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '12px 24px',
                backgroundColor: '#2563eb',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: '500'
              }}
            >
              Recharger la page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
