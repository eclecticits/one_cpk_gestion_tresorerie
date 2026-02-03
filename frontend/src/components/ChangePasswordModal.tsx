import { useState } from 'react'
import { changePassword } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'
import { useNotification } from '../contexts/NotificationContext'
import styles from './ChangePasswordModal.module.css'

interface ChangePasswordModalProps {
  onClose: () => void
}

export default function ChangePasswordModal({ onClose }: ChangePasswordModalProps) {
  const { user } = useAuth()
  const { showSuccess, showError, showWarning } = useNotification()
  const [loading, setLoading] = useState(false)
  const [showOldPassword, setShowOldPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const [formData, setFormData] = useState({
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
  })

  const validatePassword = (password: string): string | null => {
    if (password.length < 6) {
      return 'Le mot de passe doit contenir au moins 6 caractères'
    }

    const hasLetter = /[a-zA-Z]/.test(password)
    const hasNumber = /[0-9]/.test(password)

    if (!hasLetter || !hasNumber) {
      return 'Le mot de passe doit contenir au moins une lettre et un chiffre'
    }

    return null
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!user) {
      showError('Erreur', 'Utilisateur non connecté')
      return
    }

    if (formData.newPassword !== formData.confirmPassword) {
      showWarning(
        'Mots de passe différents',
        'Le nouveau mot de passe et sa confirmation ne correspondent pas'
      )
      return
    }

    const passwordError = validatePassword(formData.newPassword)
    if (passwordError) {
      showWarning('Mot de passe invalide', passwordError)
      return
    }

    if (formData.newPassword === 'ONECCPK') {
      showWarning(
        'Mot de passe non sécurisé',
        'Vous ne pouvez pas utiliser le mot de passe par défaut. Veuillez choisir un mot de passe personnel.'
      )
      return
    }

    setLoading(true)

    try {
      await changePassword(formData.oldPassword, formData.newPassword)

      showSuccess(
        'Mot de passe modifié',
        'Votre mot de passe a été changé avec succès'
      )

      onClose()
    } catch (error: any) {
      console.error('Error changing password:', error)
      showError(
        'Erreur',
        'Une erreur est survenue lors de la modification du mot de passe'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>Changer mon mot de passe</h2>
          <button className={styles.closeBtn} onClick={onClose} title="Fermer">
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label>Mot de passe actuel *</label>
            <div className={styles.passwordField}>
              <input
                type={showOldPassword ? 'text' : 'password'}
                value={formData.oldPassword}
                onChange={(e) => setFormData({ ...formData, oldPassword: e.target.value })}
                required
                autoComplete="current-password"
              />
              <button
                type="button"
                className={styles.togglePassword}
                onClick={() => setShowOldPassword(!showOldPassword)}
                title={showOldPassword ? 'Masquer' : 'Afficher'}
              >
                {showOldPassword ? '👁️' : '👁️‍🗨️'}
              </button>
            </div>
          </div>

          <div className={styles.field}>
            <label>Nouveau mot de passe *</label>
            <div className={styles.passwordField}>
              <input
                type={showNewPassword ? 'text' : 'password'}
                value={formData.newPassword}
                onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
                required
                minLength={6}
                autoComplete="new-password"
              />
              <button
                type="button"
                className={styles.togglePassword}
                onClick={() => setShowNewPassword(!showNewPassword)}
                title={showNewPassword ? 'Masquer' : 'Afficher'}
              >
                {showNewPassword ? '👁️' : '👁️‍🗨️'}
              </button>
            </div>
            <small className={styles.hint}>
              Au moins 6 caractères avec lettres et chiffres
            </small>
          </div>

          <div className={styles.field}>
            <label>Confirmer le nouveau mot de passe *</label>
            <div className={styles.passwordField}>
              <input
                type={showConfirmPassword ? 'text' : 'password'}
                value={formData.confirmPassword}
                onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                required
                minLength={6}
                autoComplete="new-password"
              />
              <button
                type="button"
                className={styles.togglePassword}
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                title={showConfirmPassword ? 'Masquer' : 'Afficher'}
              >
                {showConfirmPassword ? '👁️' : '👁️‍🗨️'}
              </button>
            </div>
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              onClick={onClose}
              className={styles.cancelBtn}
              disabled={loading}
            >
              Annuler
            </button>
            <button type="submit" className={styles.submitBtn} disabled={loading}>
              {loading ? 'Modification...' : 'Changer le mot de passe'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
