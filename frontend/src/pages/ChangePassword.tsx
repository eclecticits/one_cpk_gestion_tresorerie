import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { confirmPasswordChange, requestPasswordChange, requestPasswordReset } from '../api/auth'
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
  const [sendingOtp, setSendingOtp] = useState(false)
  const [verifyingOtp, setVerifyingOtp] = useState(false)
  const [otpCode, setOtpCode] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [step, setStep] = useState<'form' | 'verify'>('form')
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [showOldPassword, setShowOldPassword] = useState(false)

  const [formData, setFormData] = useState({
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
  })

  const email = user?.email || ''

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  const startCooldown = () => setCooldown(60)

  const resetOtpState = () => {
    setOtpCode('')
    setCooldown(0)
    setStep('form')
  }

  const validatePassword = (password: string): string | null => {
    if (password.length < 8) {
      return 'Le mot de passe doit contenir au moins 8 caractères'
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

    if (!required && !formData.oldPassword) {
      showWarning('Champ obligatoire', 'Veuillez renseigner tous les champs obligatoires.')
      return
    }

    if (!formData.newPassword || !formData.confirmPassword) {
      showWarning('Champs obligatoires', 'Veuillez renseigner tous les champs obligatoires.')
      return
    }

    if (formData.newPassword !== formData.confirmPassword) {
      showWarning(
        'Mots de passe différents',
        'Les mots de passe ne correspondent pas. Veuillez vérifier le nouveau mot de passe et sa confirmation.'
      )
      return
    }

    if (!required && formData.oldPassword && formData.oldPassword === formData.newPassword) {
      showWarning(
        'Mot de passe identique',
        'Le nouveau mot de passe doit être différent de l’ancien.'
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
      if (required) {
        await requestPasswordReset(email)
      } else {
        await requestPasswordChange(formData.oldPassword)
      }
      setStep('verify')
      startCooldown()
      showSuccess('Code envoyé', 'Un code de vérification a été envoyé à votre adresse email.')
    } catch (error: any) {
      const errorMessage = error.message || "Impossible d'envoyer le code."
      showError('Erreur', errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email) {
      showError('Erreur', 'Email utilisateur introuvable.')
      return
    }
    if (otpCode.trim().length !== 6) {
      showWarning('Code invalide', 'Veuillez saisir un code à 6 chiffres.')
      return
    }

    setVerifyingOtp(true)
    try {
      await confirmPasswordChange({
        email,
        new_password: formData.newPassword,
        otp_code: otpCode.trim(),
      })
      showSuccess(
        'Mot de passe modifié avec succès',
        'Veuillez vous reconnecter avec votre nouveau mot de passe.'
      )
      await signOut()
      setTimeout(() => {
        navigate('/login', { replace: true })
      }, 2000)
    } catch (error: any) {
      const errorMessage = error.message || 'Code invalide.'
      showError('Erreur', errorMessage)
    } finally {
      setVerifyingOtp(false)
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

        {step === 'form' && (
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
              <small className={styles.hint}>Au moins 8 caractères avec lettres et chiffres</small>
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
              <button type="submit" className={styles.submitBtn} disabled={loading}>
                {loading ? 'Envoi...' : 'Envoyer le code'}
              </button>
            </div>
          </form>
        )}

        {step === 'verify' && (
          <form onSubmit={handleVerify} className={styles.form}>
            <div className={styles.field}>
              <label>Temps restant</label>
              <input type="text" value={cooldown > 0 ? `${cooldown} seconde(s)` : 'Code expiré'} disabled />
            </div>
            <div className={styles.field}>
              <label>Code de vérification *</label>
              <input
                type="text"
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value)}
                required
                placeholder="123456"
                maxLength={6}
                inputMode="numeric"
                style={{ textAlign: 'center', letterSpacing: '6px' }}
              />
            </div>

            <div className={styles.actions}>
              <button type="button" onClick={resetOtpState} className={styles.cancelBtn} disabled={verifyingOtp}>
                Retour
              </button>
              <button type="submit" className={styles.submitBtn} disabled={verifyingOtp}>
                {verifyingOtp ? 'Vérification...' : 'Valider'}
              </button>
              <button
                type="button"
                className={styles.submitBtn}
                disabled={cooldown > 0 || sendingOtp}
                style={{ background: '#e2e8f0', color: '#1e293b' }}
                onClick={async () => {
                  if (cooldown > 0) return
                  setSendingOtp(true)
                  try {
                    if (required) {
                      await requestPasswordReset(email)
                    } else {
                      await requestPasswordChange(formData.oldPassword)
                    }
                    startCooldown()
                  } catch (error: any) {
                    showError('Erreur', error.message || "Impossible d'envoyer le code.")
                  } finally {
                    setSendingOtp(false)
                  }
                }}
              >
                {cooldown > 0 ? `Renvoyer (${cooldown}s)` : 'Renvoyer le code'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
