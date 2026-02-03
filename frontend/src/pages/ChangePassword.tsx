import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { changePassword } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'
import { useNotification } from '../contexts/NotificationContext'
import styles from './ChangePassword.module.css'

interface ChangePasswordProps {
  required?: boolean
}

export default function ChangePassword({ required = false }: ChangePasswordProps) {
  const navigate = useNavigate()
  const { user, signOut } = useAuth()
  const { showSuccess, showError, showWarning } = useNotification()
  const [loading, setLoading] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [showOldPassword, setShowOldPassword] = useState(false)

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

    // Vérification des champs obligatoires
    if (!required && !formData.oldPassword) {
      showWarning('Champ obligatoire', 'Veuillez renseigner tous les champs obligatoires.')
      return
    }

    if (!formData.newPassword || !formData.confirmPassword) {
      showWarning('Champs obligatoires', 'Veuillez renseigner tous les champs obligatoires.')
      return
    }

    // Validation A : Nouveau mot de passe ≠ Confirmation
    if (formData.newPassword !== formData.confirmPassword) {
      showWarning(
        'Mots de passe différents',
        'Les mots de passe ne correspondent pas. Veuillez vérifier le nouveau mot de passe et sa confirmation.'
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
      await changePassword(required ? null : formData.oldPassword, formData.newPassword)

      // Afficher le message de succès
      showSuccess(
        'Mot de passe modifié avec succès',
        'Veuillez vous reconnecter avec votre nouveau mot de passe.'
      )

      // Déconnexion automatique pour des raisons de sécurité
      await signOut()

      // Redirection vers la page de connexion après 2 secondes
      setTimeout(() => {
        navigate('/login', { replace: true })
      }, 2000)
    } catch (error: any) {
      const errorMessage = error.message || 'Une erreur est survenue lors de la modification du mot de passe'
      showError(
        'Erreur',
        errorMessage
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.header}>
          <img src="/imge_onec.png" alt="ONEC Logo" className={styles.logo} />
          <h1>Changement de mot de passe</h1>
          {required && (
            <p className={styles.requiredMessage}>
              Pour des raisons de sécurité, vous devez changer votre mot de passe avant de continuer
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {!required && (
            <div className={styles.field}>
              <label>Mot de passe actuel *</label>
              <div className={styles.passwordField}>
                <input
                  type={showOldPassword ? 'text' : 'password'}
                  value={formData.oldPassword}
                  onChange={(e) => setFormData({ ...formData, oldPassword: e.target.value })}
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
          )}

          <div className={styles.field}>
            <label>Nouveau mot de passe *</label>
            <div className={styles.passwordField}>
              <input
                type={showNewPassword ? 'text' : 'password'}
                value={formData.newPassword}
                onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
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
            {!required && (
              <button
                type="button"
                onClick={() => navigate(-1)}
                className={styles.cancelBtn}
                disabled={loading}
              >
                Annuler
              </button>
            )}
            <button
              type="submit"
              className={styles.submitBtn}
              disabled={loading}
            >
              {loading ? 'Modification...' : 'Changer le mot de passe'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
