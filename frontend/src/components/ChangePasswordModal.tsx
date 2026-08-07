import { useState, useEffect } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { requestPasswordChange, confirmPasswordChange } from '../api/auth'
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
  const [step, setStep] = useState<'input' | 'otp'>('input')
  const [cooldown, setCooldown] = useState(0)

  const [showOldPassword, setShowOldPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const [formData, setFormData] = useState({
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
    otpCode: '',
  })

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => setCooldown((c) => c - 1), 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  const validatePassword = (password: string): string | null => {
    if (password.length < 8) return 'Le mot de passe doit contenir au moins 8 caractères'
    if (!/[A-Z]/.test(password) || !/[0-9]/.test(password)) {
      return 'Le mot de passe doit contenir au moins une majuscule et un chiffre'
    }
    return null
  }

  const handleRequestOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return

    if (formData.newPassword !== formData.confirmPassword) {
      showWarning('Mots de passe différents', 'La confirmation ne correspond pas')
      return
    }

    const passwordError = validatePassword(formData.newPassword)
    if (passwordError) {
      showWarning('Mot de passe invalide', passwordError)
      return
    }

    setLoading(true)
    try {
      await requestPasswordChange(formData.oldPassword)
      showSuccess('Code envoyé', `Un code de sécurité a été envoyé à l'adresse ${user.email}`)
      setStep('otp')
      setCooldown(60)
    } catch (error: any) {
      showError('Erreur', error.payload?.detail || 'Impossible de générer le code de sécurité')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmChange = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return

    if (formData.otpCode.length !== 6) {
      showWarning('Code invalide', 'Veuillez saisir les 6 chiffres du code reçu')
      return
    }

    setLoading(true)
    try {
      await confirmPasswordChange({
        email: user.email,
        new_password: formData.newPassword,
        otp_code: formData.otpCode,
      })
      showSuccess('Succès', 'Votre mot de passe a été modifié avec succès')
      onClose()
    } catch (error: any) {
      showError('Erreur', error.payload?.detail || 'Le code de sécurité est incorrect ou expiré')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>{step === 'input' ? 'Changer mon mot de passe' : 'Vérification de sécurité'}</h2>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        {step === 'input' ? (
          <form onSubmit={handleRequestOtp} className={styles.form}>
            <div className={styles.field}>
              <label>Mot de passe actuel</label>
              <div className={styles.passwordField}>
                <input
                  type={showOldPassword ? 'text' : 'password'}
                  value={formData.oldPassword}
                  onChange={(e) => setFormData({ ...formData, oldPassword: e.target.value })}
                  required
                />
                <button type="button" className={styles.togglePassword} onClick={() => setShowOldPassword(!showOldPassword)}>
                  {showOldPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div className={styles.field}>
              <label>Nouveau mot de passe</label>
              <div className={styles.passwordField}>
                <input
                  type={showNewPassword ? 'text' : 'password'}
                  value={formData.newPassword}
                  onChange={(e) => setFormData({ ...formData, newPassword: e.target.value })}
                  required
                />
                <button type="button" className={styles.togglePassword} onClick={() => setShowNewPassword(!showNewPassword)}>
                  {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div className={styles.field}>
              <label>Confirmer le nouveau mot de passe</label>
              <div className={styles.passwordField}>
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={formData.confirmPassword}
                  onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                  required
                />
                <button type="button" className={styles.togglePassword} onClick={() => setShowConfirmPassword(!showConfirmPassword)}>
                  {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div className={styles.actions}>
              <button type="button" onClick={onClose} className={styles.cancelBtn}>Annuler</button>
              <button type="submit" className={styles.submitBtn} disabled={loading}>
                {loading ? 'Envoi...' : 'Recevoir le code par email'}
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleConfirmChange} className={styles.form}>
            <p style={{ fontSize: '14px', color: '#64748b', textAlign: 'center', marginBottom: '10px' }}>
              Un code à 6 chiffres vous a été envoyé pour valider ce changement.
            </p>
            <div className={styles.field}>
              <input
                type="text"
                value={formData.otpCode}
                onChange={(e) => setFormData({ ...formData, otpCode: e.target.value })}
                required
                maxLength={6}
                placeholder="000000"
                style={{ textAlign: 'center', fontSize: '24px', letterSpacing: '8px', padding: '15px' }}
              />
            </div>
            
            <div className={styles.actions}>
              <button type="button" onClick={() => setStep('input')} className={styles.cancelBtn}>Retour</button>
              <button type="submit" className={styles.submitBtn} disabled={loading}>
                {loading ? 'Validation...' : 'Confirmer le changement'}
              </button>
            </div>

            <button 
              type="button" 
              className={styles.cancelBtn} 
              style={{ marginTop: '10px', fontSize: '12px' }}
              disabled={cooldown > 0 || loading}
              onClick={handleRequestOtp}
            >
              {cooldown > 0 ? `Renvoyer le code dans ${cooldown}s` : 'Renvoyer un nouveau code'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
