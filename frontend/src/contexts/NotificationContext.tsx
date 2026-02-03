import React, { createContext, useContext, useState, useCallback } from 'react'

export type NotificationType = 'success' | 'error' | 'warning' | 'info'

interface Notification {
  id: string
  type: NotificationType
  title: string
  message: string
}

interface NotificationContextType {
  showNotification: (type: NotificationType, title: string, message: string) => void
  showSuccess: (title: string, message: string) => void
  showError: (title: string, message: string) => void
  showWarning: (title: string, message: string) => void
  showInfo: (title: string, message: string) => void
  notifications: Notification[]
  removeNotification: (id: string) => void
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([])

  const showNotification = useCallback((type: NotificationType, title: string, message: string) => {
    const id = Math.random().toString(36).substring(7)
    const notification: Notification = { id, type, title, message }

    setNotifications(prev => [...prev, notification])

    setTimeout(() => {
      setNotifications(prev => prev.filter(n => n.id !== id))
    }, 5000)
  }, [])

  const showSuccess = useCallback((title: string, message: string) => {
    showNotification('success', title, message)
  }, [showNotification])

  const showError = useCallback((title: string, message: string) => {
    showNotification('error', title, message)
  }, [showNotification])

  const showWarning = useCallback((title: string, message: string) => {
    showNotification('warning', title, message)
  }, [showNotification])

  const showInfo = useCallback((title: string, message: string) => {
    showNotification('info', title, message)
  }, [showNotification])

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id))
  }, [])

  return (
    <NotificationContext.Provider
      value={{
        showNotification,
        showSuccess,
        showError,
        showWarning,
        showInfo,
        notifications,
        removeNotification,
      }}
    >
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotification() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error('useNotification must be used within a NotificationProvider')
  }
  return context
}
