import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { confirmPasswordChange, requestPasswordReset } from '../api/auth'
import { getOrganisationPublic, listPublicOrganisations, type OrganisationPublicInfo } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import { getTenantSlug, isAdminHost, setTenantOverride } from '../utils/tenant'
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
  const [publicTenants, setPublicTenants] = useState<OrganisationPublicInfo[]>([])
  const [manualTenant, setManualTenant] = useState('')
  const [sitePanelOpen, setSitePanelOpen] = useState(false)
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
    if (slug && !isAdminHost()) {
      setTenantOverride(slug)
    }
  }, [])

  useEffect(() => {
    if (isAdminHost()) return
    const loadTenants = async () => {
      try {
        const tenants = await listPublicOrganisations()
        setPublicTenants(tenants)
      } catch {
        setPublicTenants([])
      }
    }
    loadTenants()
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
    if (!tenantSlug && !isAdminHost()) {
      setError('Sélectionnez votre site avant de continuer.')
      openSitePanel()
      return
    }
    setLoading(true)

    try {
      if (tenantSlug && !isAdminHost()) {
        const hostname = window.location.hostname.toLowerCase()
        const isIpHost = /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname)
        const envBaseDomain =
          (typeof import.meta !== 'undefined' &&
            typeof import.meta.env !== 'undefined' &&
            (import.meta.env as any).VITE_TENANT_BASE_DOMAIN) ||
          ''
        const baseDomain =
          hostname === 'localhost' || hostname === '127.0.0.1'
            ? null
            : isIpHost
              ? null
              : (envBaseDomain || hostname.split('.').slice(1).join('.'))
        if (baseDomain) {
          const targetHost = `${tenantSlug}.${baseDomain}`
          if (hostname !== targetHost) {
            window.location.href = `https://${targetHost}/login?email=${encodeURIComponent(email)}`
            return
          }
        }
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

  const handleTenantContinue = async () => {
    const normalized = manualTenant.trim().toLowerCase()
    if (!normalized) {
      setError('Entrez un site valide.')
      return
    }
    setLoading(true)
    try {
      const info = await getOrganisationPublic(normalized)
      setTenantOverride(normalized)
      setTenantSlug(normalized)
      setOrgInfo(info)
      setError('')
    } catch {
      setError("Site introuvable. Vérifiez l'orthographe.")
    } finally {
      setLoading(false)
    }
  }

  const handleSelectTenant = (slug: string) => {
    const normalized = (slug || '').trim().toLowerCase()
    if (!normalized) return
    setManualTenant(normalized)
    setTenantOverride(normalized)
    setTenantSlug(normalized)
    setSitePanelOpen(false)
    setError('')
    const matched = publicTenants.find((tenant) => tenant.slug === normalized)
    setOrgInfo(matched || null)
  }

  const openSitePanel = () => {
    setManualTenant('')
    setSitePanelOpen(true)
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
                {orgInfo?.nom || 'ONEC · Connexion'}
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

                <button type="submit" disabled={loading} className={styles.submitBtn}>
                  {loading ? <span className={styles.spinner} aria-label="Chargement" /> : 'Se connecter'}
                </button>
                <div className={styles.securityNote}>
                  🔒 Connexion sécurisée (SSL) - Gestion de trésorerie ONEC
                </div>
                <button type="button" className={styles.linkBtn} onClick={() => navigate('/forgot-password')}>
                  Mot de passe oublié
                </button>
                {!isAdminHost() && (
                  <button type="button" className={styles.siteSelectorInline} onClick={openSitePanel}>
                    Changer de site
                  </button>
                )}
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
      {!isAdminHost() && (
        <>
          <div
            className={`${styles.siteOverlay} ${sitePanelOpen ? styles.siteOverlayVisible : ''}`}
            onClick={() => setSitePanelOpen(false)}
          />
          <div className={`${styles.sitePanel} ${sitePanelOpen ? styles.sitePanelOpen : ''}`}>
            <div className={styles.sitePanelHeader}>
              <div>
                <h3>Sélectionner votre site</h3>
                <p>Choisissez l’antenne de trésorerie pour continuer.</p>
              </div>
              <button type="button" className={styles.sitePanelClose} onClick={() => setSitePanelOpen(false)}>
                ×
              </button>
            </div>
            <div className={styles.sitePanelSearch}>
              <input
                placeholder="Rechercher un site (nom ou slug)…"
                value={manualTenant}
                onChange={(e) => setManualTenant(e.target.value)}
              />
              <button type="button" onClick={handleTenantContinue} disabled={loading}>
                Choisir
              </button>
            </div>
            <div className={styles.sitePanelList}>
              {publicTenants
                .filter((tenant) => {
                  const q = manualTenant.trim().toLowerCase()
                  if (!q) return true
                  return tenant.slug.toLowerCase().includes(q) || tenant.nom.toLowerCase().includes(q)
                })
                .map((tenant) => (
                  <button
                    key={tenant.slug}
                    type="button"
                    className={`${styles.sitePanelItem} ${
                      tenant.slug === (tenantSlug || '').toLowerCase() ? styles.sitePanelItemActive : ''
                    }`}
                    onClick={() => handleSelectTenant(tenant.slug)}
                  >
                    <span className={styles.sitePanelIcon}>{tenant.icon || '🏢'}</span>
                    <span className={styles.sitePanelName}>{tenant.nom}</span>
                    <span className={styles.sitePanelSlug}>{tenant.slug}</span>
                  </button>
                ))}
              {publicTenants.length === 0 && (
                <div className={styles.sitePanelEmpty}>Aucun site disponible.</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
