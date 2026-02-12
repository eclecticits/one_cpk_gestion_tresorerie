import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { confirmPasswordChange, requestPasswordReset } from '../api/auth'
import { useAuth } from '../contexts/AuthContext'
import styles from './Login.module.css'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [step, setStep] = useState<'request' | 'verify'>('request')
  const [error, setError] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [sending, setSending] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const { user, reloadProfile } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  const validatePassword = (value: string): string | null => {
    if (value.length < 8) return 'Le mot de passe doit contenir au moins 8 caractères.'
    const hasLetter = /[a-zA-Z]/.test(value)
    const hasNumber = /[0-9]/.test(value)
    if (!hasLetter || !hasNumber) return 'Le mot de passe doit contenir au moins une lettre et un chiffre.'
    if (value === 'ONECCPK') return 'Vous ne pouvez pas utiliser le mot de passe par défaut.'
    return null
  }

  const handleRequest = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')

    const pwdError = validatePassword(newPassword)
    if (pwdError) {
      setError(pwdError)
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Les mots de passe ne correspondent pas.')
      return
    }

    setSending(true)
    try {
      await requestPasswordReset(email)
      setStep('verify')
      setCooldown(60)
    } catch (err: any) {
      setError(err?.message || "Impossible d'envoyer le code.")
    } finally {
      setSending(false)
    }
  }

  const handleVerify = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    if (otpCode.trim().length !== 6) {
      setError('Veuillez saisir un code à 6 chiffres.')
      return
    }

    setVerifying(true)
    try {
      await confirmPasswordChange({ email, new_password: newPassword, otp_code: otpCode.trim() })
      await reloadProfile()
      navigate('/dashboard', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Code invalide.')
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.loginBox}>
        {(sending || verifying) ? (
          <div className={styles.skeletonLogin}>
            <div className={styles.skeletonLogo} />
            <div className={styles.skeletonLine} />
            <div className={styles.skeletonField} />
            <div className={styles.skeletonField} />
            <div className={styles.skeletonButton} />
          </div>
        ) : (
          <div className={styles.header}>
            <img src="/imge_onec.png" alt="ONEC Logo" className={styles.headerLogo} />
            <div className={styles.provincialTitle}>Conseil Provincial de Kinshasa</div>
            <p>Mot de passe oublié</p>
          </div>
        )}

        {step === 'request' && !sending && (
          <form onSubmit={handleRequest} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}

            <div className={styles.field}>
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="votre@email.com"
                autoComplete="username"
              />
            </div>

            <div className={styles.field}>
              <label>Nouveau mot de passe</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                placeholder="Nouveau mot de passe"
                autoComplete="new-password"
              />
            </div>

            <div className={styles.field}>
              <label>Confirmer le mot de passe</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                placeholder="Confirmez le mot de passe"
                autoComplete="new-password"
              />
            </div>

            <button type="submit" disabled={sending} className={styles.submitBtn}>
              {sending ? 'Envoi en cours...' : 'Envoyer le code'}
            </button>
            <div className={styles.securityNote}>
              🔒 Connexion sécurisée (SSL) - Gestion de trésorerie ONEC-CPK
            </div>
          </form>
        )}

        {step === 'verify' && !verifying && (
          <form onSubmit={handleVerify} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}

            <div className={styles.field}>
              <label>Temps restant</label>
              <input type="text" value={cooldown > 0 ? `${cooldown} seconde(s)` : 'Code expiré'} disabled />
            </div>

            <div className={styles.field}>
              <label>Code de vérification</label>
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

            <button type="submit" disabled={verifying} className={styles.submitBtn}>
              {verifying ? 'Vérification...' : 'Valider mon compte'}
            </button>
            <button
              type="button"
              disabled={cooldown > 0 || sending}
              className={styles.submitBtn}
              style={{ marginTop: '10px', background: '#e2e8f0', color: '#1e293b' }}
              onClick={async () => {
                if (cooldown > 0) return
                setSending(true)
                try {
                  await requestPasswordReset(email)
                  setCooldown(60)
                } catch (err: any) {
                  setError(err?.message || "Impossible d'envoyer le code.")
                } finally {
                  setSending(false)
                }
              }}
            >
              {cooldown > 0 ? `Renvoyer le code (${cooldown}s)` : 'Renvoyer le code'}
            </button>
            <div className={styles.securityNote}>
              🔒 Connexion sécurisée (SSL) - Gestion de trésorerie ONEC-CPK
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
