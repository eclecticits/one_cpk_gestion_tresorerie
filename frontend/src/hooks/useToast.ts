import { useNotification } from '../contexts/NotificationContext'

export function useToast() {
  const { showSuccess, showError, showInfo, showWarning } = useNotification()

  return {
    notifySuccess: showSuccess,
    notifyError: showError,
    notifyInfo: showInfo,
    notifyWarning: showWarning,
  }
}
