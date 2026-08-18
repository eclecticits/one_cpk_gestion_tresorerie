import { useState, useEffect } from 'react'
import { CheckCircle2, Eye, EyeOff, KeyRound, Loader2, Mail, ShieldCheck } from 'lucide-react'
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
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [success, setSuccess] = useState(false)
  const { user, reloadProfile } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user && !success) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, success, navigate])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  const validatePassword = (value: string): string | null => {
    if (value.length < 8) return 'Le mot de passe doit contenir au moins 8 caractères.'
    const hasUppercase = /[A-Z]/.test(value)
    const hasNumber = /[0-9]/.test(value)
    if (!hasUppercase || !hasNumber) return 'Le mot de passe doit contenir au moins une majuscule et un chiffre.'
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
      setSuccess(true)
      await reloadProfile()
      window.setTimeout(() => navigate('/dashboard', { replace: true }), 650)
    } catch (err: any) {
      setError(err?.message || 'Code invalide.')
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.bg} aria-hidden="true" />
      <div className={`${styles.resetOrbit} ${styles.orbitOne}`} aria-hidden="true" />
      <div className={`${styles.resetOrbit} ${styles.orbitTwo}`} aria-hidden="true" />
      <div className={styles.resetGrid} aria-hidden="true" />
      <div className={`${styles.resetBeam} ${styles.beamOne}`} aria-hidden="true" />
      <div className={`${styles.resetBeam} ${styles.beamTwo}`} aria-hidden="true" />
      <div className={styles.loginBox}>
        <div className={styles.header}>
          <img src="/imge_onec.png" alt="ONEC Logo" className={styles.headerLogo} />
          <p className={styles.eyebrow}>Conseil Provincial de Kinshasa</p>
          <p className={styles.resetTitle}>Réinitialisation sécurisée</p>
          <p>Insérez vos informations, puis le code reçu par e-mail.</p>
        </div>

        {step === 'request' && !sending && (
          <form onSubmit={handleRequest} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}

            <div className={styles.field}>
              <label>Adresse e-mail</label>
              <div className={styles.inputShell}>
                <Mail size={17} />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="nom@onec.cd"
                  autoComplete="username"
                />
              </div>
            </div>

            <div className={styles.field}>
              <label>Nouveau mot de passe</label>
              <div className={styles.inputShell}>
                <KeyRound size={17} />
                <input
                  type={showNewPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  placeholder="Nouveau mot de passe"
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  title={showNewPassword ? 'Masquer' : 'Afficher'}
                >
                  {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div className={styles.field}>
              <label>Confirmer le mot de passe</label>
              <div className={styles.inputShell}>
                <KeyRound size={17} />
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  placeholder="Confirmez le mot de passe"
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  title={showConfirmPassword ? 'Masquer' : 'Afficher'}
                >
                  {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={sending} className={styles.submitBtn}>
              {sending ? <><Loader2 size={18} className={styles.spin} /> Envoi en cours...</> : 'Envoyer le code'}
            </button>
            <button type="button" className={styles.secondaryBtn} onClick={() => navigate('/login')}>
              Retour
            </button>
            <div className={styles.securityNote}>
              <ShieldCheck size={15} /> Connexion sécurisée · ONEC RDC
            </div>
          </form>
        )}

        {step === 'request' && sending && (
          <div className={styles.processing}>
            <Loader2 size={22} className={styles.spin} />
            <strong>Envoi du code...</strong>
          </div>
        )}

        {step === 'verify' && !verifying && (
          <form onSubmit={handleVerify} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}
            {success && <div className={styles.success}><CheckCircle2 size={18} /> Mot de passe confirmé</div>}

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
                className={styles.otpInput}
              />
            </div>

            <button type="submit" disabled={verifying} className={styles.submitBtn}>
              {verifying ? <><Loader2 size={18} className={styles.spin} /> Vérification...</> : 'Valider mon compte'}
            </button>
            <button
              type="button"
              disabled={cooldown > 0 || sending}
              className={styles.secondaryBtn}
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
            <button type="button" className={styles.secondaryBtn} onClick={() => navigate('/login')}>
              Retour
            </button>
            <div className={styles.securityNote}>
              <ShieldCheck size={15} /> Connexion sécurisée · ONEC RDC
            </div>
          </form>
        )}

        {step === 'verify' && verifying && (
          <div className={styles.processing}>
            <Loader2 size={22} className={styles.spin} />
            <strong>Vérification du code...</strong>
          </div>
        )}
      </div>
    </div>
  )
}
