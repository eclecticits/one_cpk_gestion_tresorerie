import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { confirmPasswordChange, requestPasswordReset, discoverTenants, type TenantDiscoveryItem } from '../api/auth'
import { getOrganisationPublic, type OrganisationPublicInfo } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import { getTenantSlug, isAdminHost, setTenantOverride } from '../utils/tenant'
import TenantSelector from '../components/auth/TenantSelector'
import styles from './Login.module.css'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [otpCode, setOtpCode] = useState('')
  const [step, setStep] = useState<'login' | 'set-password' | 'verify-otp'>('login')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sendingOtp, setSendingOtp] = useState(false)
  const [verifyingOtp, setVerifyingOtp] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [orgInfo, setOrgInfo] = useState<OrganisationPublicInfo | null>(null)
  const [tenantSlug, setTenantSlug] = useState<string | null>(null)
  const [tenantOptions, setTenantOptions] = useState<TenantDiscoveryItem[]>([])
  const [selectedTenant, setSelectedTenant] = useState<TenantDiscoveryItem | null>(null)
  const [discovering, setDiscovering] = useState(false)
  const { signIn, user, reloadProfile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const adminBlocked = Boolean((location.state as any)?.adminBlocked) || isAdminHost()

  const getPostLoginPath = (_profile: typeof user) => '/dashboard'

  useEffect(() => {
    if (user) {
      navigate(getPostLoginPath(user), { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    const slug = getTenantSlug()
    setTenantSlug(slug)
  }, [])

  useEffect(() => {
    const loadOrgInfo = async () => {
      if (!tenantSlug) {
        setOrgInfo(null)
        return
      }
      try {
        const info = await getOrganisationPublic(tenantSlug)
        setOrgInfo(info)
      } catch {
        setOrgInfo(null)
      }
    }
    loadOrgInfo()
  }, [tenantSlug])

  useEffect(() => {
    if (!selectedTenant) return
    if (!tenantSlug || selectedTenant.slug !== tenantSlug) {
      setTenantSlug(selectedTenant.slug)
    }
    setOrgInfo({ nom: selectedTenant.name, slug: selectedTenant.slug })
  }, [selectedTenant, tenantSlug])

  useEffect(() => {
    if (step !== 'login') return
    const trimmed = email.trim()
    if (!trimmed || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setTenantOptions([])
      setSelectedTenant(null)
      return
    }
    let active = true
    const timer = setTimeout(async () => {
      setDiscovering(true)
      try {
        const tenants = await discoverTenants(trimmed)
        if (!active) return
        setTenantOptions(tenants)
        if (tenants.length === 1) {
          setSelectedTenant(tenants[0])
          setTenantOverride(tenants[0].slug)
        } else if (tenants.length === 0) {
          setSelectedTenant(null)
        }
      } catch {
        if (!active) return
        setTenantOptions([])
        setSelectedTenant(null)
      } finally {
        if (active) setDiscovering(false)
      }
    }, 400)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [email, step])

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

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (!selectedTenant) {
        setDiscovering(true)
        const tenants = await discoverTenants(email)
        setTenantOptions(tenants)
        if (tenants.length === 1) {
          setSelectedTenant(tenants[0])
          setTenantOverride(tenants[0].slug)
        } else {
          setError('Sélectionnez votre site avant de continuer.')
          return
        }
      }
      const targetTenant = selectedTenant || tenantOptions[0]
      if (targetTenant && !isAdminHost()) {
        const hostname = window.location.hostname.toLowerCase()
        const baseDomain =
          hostname === 'localhost' || hostname === '127.0.0.1'
            ? null
            : hostname.split('.').slice(1).join('.')
        if (baseDomain) {
          const targetHost = `${targetTenant.slug}.${baseDomain}`
          if (hostname !== targetHost) {
            window.location.href = `https://${targetHost}/login?email=${encodeURIComponent(email)}`
            return
          }
        }
      }
      if (targetTenant) {
        setTenantOverride(targetTenant.slug)
      }
      const res = await signIn(email, password)
      if (res.requires_otp) {
        setStep('set-password')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erreur de connexion'
      setError(message)
    } finally {
      setLoading(false)
      setDiscovering(false)
    }
  }

  const handleSendOtp = async (event: React.FormEvent<HTMLFormElement>) => {
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

    if (cooldown > 0) return
    setSendingOtp(true)
    try {
      await requestPasswordReset(email)
      setStep('verify-otp')
      setCooldown(60)
    } catch (err) {
      const message = err instanceof Error ? err.message : "Impossible d'envoyer le code."
      setError(message)
    } finally {
      setSendingOtp(false)
    }
  }

  const handleConfirmOtp = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    if (otpCode.trim().length !== 6) {
      setError('Veuillez saisir un code à 6 chiffres.')
      return
    }

    setVerifyingOtp(true)
    try {
      await confirmPasswordChange({ email, new_password: newPassword, otp_code: otpCode.trim() })
      const profile = await reloadProfile()
      navigate(getPostLoginPath(profile), { replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Code invalide.'
      setError(message)
    } finally {
      setVerifyingOtp(false)
    }
  }

  return (
    <div className={styles.container}>
      {adminBlocked && (
        <div style={{ marginBottom: '16px', padding: '12px 16px', borderRadius: '12px', background: '#fff5f5', color: '#b91c1c' }}>
          Accès réservé au Super Admin. Merci d’utiliser un compte habilité pour ce domaine.
        </div>
      )}
      <div className={styles.loginBox}>
        {loading && step === 'login' ? (
          <div className={styles.skeletonLogin}>
            <div className={styles.skeletonLogo} />
            <div className={styles.skeletonLine} />
            <div className={styles.skeletonField} />
            <div className={styles.skeletonField} />
            <div className={styles.skeletonButton} />
          </div>
        ) : (
          <>
            <div className={styles.header}>
              {orgInfo?.logo_url ? (
                <img src={orgInfo.logo_url} alt={`${orgInfo.nom} Logo`} className={styles.headerLogo} />
              ) : (
                <img src="/imge_onec.png" alt="ONEC Logo" className={styles.headerLogo} />
              )}
              <div className={styles.provincialTitle}>
                {orgInfo?.nom || 'ONEC-Mind Central'}
              </div>
              <p>{orgInfo?.slug ? `Connexion · ${orgInfo.slug.toUpperCase()}` : 'Connexion'}</p>
            </div>

            {!user && step === 'login' && (
              <form onSubmit={handleSubmit} className={styles.form}>
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

            {tenantOptions.length > 0 && (
              <TenantSelector
                tenants={tenantOptions}
                selectedTenant={selectedTenant}
                onSelect={(tenant) => {
                  setSelectedTenant(tenant)
                  setTenantOverride(tenant.slug)
                  setError('')
                }}
              />
            )}

            <div className={styles.field}>
              <label>Mot de passe</label>
              <div className={styles.passwordField}>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className={styles.passwordToggle}
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>

            <button type="submit" disabled={loading || discovering} className={styles.submitBtn}>
              {loading || discovering ? <span className={styles.spinner} aria-label="Chargement" /> : 'Se connecter'}
            </button>
            <div className={styles.securityNote}>
              🔒 Connexion sécurisée (SSL) - Gestion de trésorerie ONEC-CPK
            </div>
            <button type="button" className={styles.linkBtn} onClick={() => navigate('/forgot-password')}>
              Mot de passe oublié
            </button>
              </form>
            )}

            {!user && step === 'set-password' && (
              <form onSubmit={handleSendOtp} className={styles.form}>
            {error && <div className={styles.error}>{error}</div>}
            <div className={styles.field}>
              <label>Email</label>
              <input type="email" value={email} disabled />
            </div>
            <div className={styles.field}>
              <label>Nouveau mot de passe</label>
              <div className={styles.passwordField}>
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
                  className={styles.passwordToggle}
                  onClick={() => setShowNewPassword((prev) => !prev)}
                  aria-label={showNewPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showNewPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
            <div className={styles.field}>
              <label>Confirmer le mot de passe</label>
              <div className={styles.passwordField}>
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
                  className={styles.passwordToggle}
                  onClick={() => setShowConfirmPassword((prev) => !prev)}
                  aria-label={showConfirmPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showConfirmPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
            <button type="submit" disabled={sendingOtp} className={styles.submitBtn}>
              {sendingOtp ? 'Envoi en cours...' : 'Envoyer le code'}
            </button>
              </form>
            )}

            {!user && step === 'verify-otp' && (
          <form onSubmit={handleConfirmOtp} className={styles.form}>
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
            <button type="submit" disabled={verifyingOtp} className={styles.submitBtn}>
              {verifyingOtp ? 'Vérification...' : 'Valider mon compte'}
            </button>
            <button
              type="button"
              disabled={cooldown > 0 || sendingOtp}
              className={styles.submitBtn}
              style={{ marginTop: '10px', background: '#e2e8f0', color: '#1e293b' }}
              onClick={async () => {
                if (cooldown > 0) return
                setSendingOtp(true)
                try {
                  await requestPasswordReset(email)
                  setCooldown(60)
                } catch (err: any) {
                  setError(err?.message || "Impossible d'envoyer le code.")
                } finally {
                  setSendingOtp(false)
                }
              }}
            >
              {cooldown > 0 ? `Renvoyer le code (${cooldown}s)` : 'Renvoyer le code'}
            </button>
          </form>
            )}
          </>
        )}
      </div>
    </div>
  )
}
