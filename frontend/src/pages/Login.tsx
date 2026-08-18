import { useEffect, useState, useRef } from 'react'
import { ArrowRight, Building2, CheckCircle2, ChevronDown, Eye, EyeOff, Loader2, LockKeyhole, Mail, ShieldCheck } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { confirmPasswordChange, discoverTenants, requestPasswordReset } from '../api/auth'
import { getOrganisationPublic, listPublicOrganisations, type OrganisationPublicInfo } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import { getPortalOrigin, getTenantBaseDomain, getTenantSlug, isAdminHost, setTenantOverride } from '../utils/tenant'
import { buildUploadUrl } from '../utils/uploads'
import './LoginPortal.css'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [step, setStep] = useState<'login' | 'set-password' | 'verify-otp'>('login')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sendingOtp, setSendingOtp] = useState(false)
  const [verifyingOtp, setVerifyingOtp] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [loginLockSeconds, setLoginLockSeconds] = useState(0)
  const [loginSuccess, setLoginSuccess] = useState(false)
  const [deferUserRedirect, setDeferUserRedirect] = useState(false)
  const [parallax, setParallax] = useState({ x: 0, y: 0 })
  
  const [orgInfo, setOrgInfo] = useState<OrganisationPublicInfo | null>(null)
  const [tenantSlug, setTenantSlug] = useState<string | null>(null)
  const [publicTenants, setPublicTenants] = useState<OrganisationPublicInfo[]>([])
  const [search, setSearch] = useState('')
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { signIn, user, reloadProfile } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  
  const adminBlocked = Boolean((location.state as any)?.adminBlocked) || isAdminHost()
  const loginLockStorageKey = `onec-login-lock:${tenantSlug || 'portal'}:${email.trim().toLowerCase() || 'anonymous'}`

  const formatLoginLockTime = (seconds: number) => {
    const safeSeconds = Math.max(0, seconds)
    const minutes = Math.floor(safeSeconds / 60)
    const remainingSeconds = safeSeconds % 60
    return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`
  }

  const startLoginLock = (seconds = 180) => {
    const safeSeconds = Math.max(1, seconds)
    const until = Date.now() + safeSeconds * 1000
    setLoginLockSeconds(safeSeconds)
    try {
      window.localStorage.setItem(loginLockStorageKey, String(until))
    } catch {
      // localStorage peut être indisponible en navigation privée stricte.
    }
  }

  useEffect(() => {
    if (Boolean((location.state as any)?.sessionExpired)) {
      setError('Votre session a expiré. Veuillez vous reconnecter.')
    }
  }, [location.state])

  useEffect(() => {
    try {
      const storedUntil = window.localStorage.getItem(loginLockStorageKey)
      const until = storedUntil ? Number(storedUntil) : 0
      const remaining = Math.ceil((until - Date.now()) / 1000)
      if (Number.isFinite(remaining) && remaining > 0) {
        setLoginLockSeconds(remaining)
      } else if (storedUntil) {
        window.localStorage.removeItem(loginLockStorageKey)
      }
    } catch {
      setLoginLockSeconds(0)
    }
  }, [loginLockStorageKey])

  useEffect(() => {
    if (loginLockSeconds <= 0) return
    const timer = window.setInterval(() => {
      setLoginLockSeconds((prev) => {
        const next = Math.max(0, prev - 1)
        if (next === 0) {
          try {
            window.localStorage.removeItem(loginLockStorageKey)
          } catch {
            // Ignorer une indisponibilité de stockage.
          }
        }
        return next
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [loginLockSeconds, loginLockStorageKey])

  const validatePassword = (value: string): string | null => {
    if (value.length < 8) return 'Le mot de passe doit contenir au moins 8 caractères.'
    const hasUppercase = /[A-Z]/.test(value)
    const hasNumber = /[0-9]/.test(value)
    if (!hasUppercase || !hasNumber) return 'Le mot de passe doit contenir au moins une majuscule et un chiffre.'
    return null
  }

  const handleSendOtp = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    const pwdError = validatePassword(newPassword)
    if (pwdError) { setError(pwdError); return; }
    if (newPassword !== confirmPassword) { setError('Les mots de passe ne correspondent pas.'); return; }
    setSendingOtp(true)
    try {
      await requestPasswordReset(email)
      setStep('verify-otp')
      setCooldown(60)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible d'envoyer le code.")
    } finally { setSendingOtp(false) }
  }

  const handleConfirmOtp = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    if (otpCode.trim().length !== 6) { setError('Veuillez saisir un code à 6 chiffres.'); return; }
    setVerifyingOtp(true)
    try {
      await confirmPasswordChange({ email, new_password: newPassword, otp_code: otpCode.trim() })
      await reloadProfile()
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Code invalide.')
    } finally { setVerifyingOtp(false) }
  }

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldown])

  useEffect(() => {
    if (user && !deferUserRedirect) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, deferUserRedirect, navigate])

  useEffect(() => {
    const slug = getTenantSlug()
    setTenantSlug(slug)
    if (slug && !isAdminHost()) setTenantOverride(slug)
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
      if (!tenantSlug) { setOrgInfo(null); return; }
      try {
        const info = await getOrganisationPublic(tenantSlug)
        setOrgInfo(info)
      } catch { setOrgInfo(null) }
    }
    loadOrgInfo()
  }, [tenantSlug])

  // Fermer le dropdown si on clique ailleurs
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const filteredSites = search 
    ? publicTenants.filter(s => s.nom.toLowerCase().includes(search.toLowerCase()) || s.slug.toLowerCase().includes(search.toLowerCase()))
    : publicTenants;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (loginLockSeconds > 0) return
    setError('')
    setLoginSuccess(false)
    if (!tenantSlug && !isAdminHost()) {
      setError('Veuillez sélectionner une organisation.')
      return
    }
    setLoading(true)
    setDeferUserRedirect(true)
    try {
      if (!isAdminHost() && email.trim()) {
        try {
          const tenants = await discoverTenants(email.trim())
          if (tenants.length > 1 && !tenantSlug) {
            setError('Veuillez sélectionner une organisation.')
            setLoading(false)
            setDeferUserRedirect(false)
            return
          }
        } catch {
          // Le login peut encore être valide si l'email n'est connu que dans le tenant déjà sélectionné.
        }
      }

      const selectedTenant = !isAdminHost() && tenantSlug
        ? publicTenants.find((tenant) => tenant.slug === tenantSlug)
        : null
      const res = await signIn(email, password, selectedTenant ? { slug: selectedTenant.slug } : undefined)
      if (res.requires_otp) {
        setStep('set-password')
        setDeferUserRedirect(false)
      } else {
        setLoginSuccess(true)
        window.setTimeout(() => {
          navigate('/dashboard', { replace: true })
        }, 650)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erreur de connexion'
      if (message.includes('Organisation requise')) {
        setError('Veuillez sélectionner une organisation.')
      } else {
        setError(message)
        if (message.includes('Limite atteinte')) {
          const match = message.match(/dans\s+(\d+)\s+minute/)
          startLoginLock(match ? Number(match[1]) * 60 : 180)
        }
      }
      setDeferUserRedirect(false)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectTenant = (slug: string) => {
    setTenantOverride(slug)
    setTenantSlug(slug)
    setIsDropdownOpen(false)
    setError('')
    
    const hostname = window.location.hostname.toLowerCase()
    const protocol = window.location.protocol
    const port = window.location.port
    const portalOrigin = getPortalOrigin()
    let portalHostname = ''
    if (portalOrigin) {
      try {
        portalHostname = new URL(portalOrigin).hostname.toLowerCase()
      } catch {
        portalHostname = ''
      }
    }
    const tenantBaseDomain = getTenantBaseDomain()

    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname.endsWith('.localhost')) {
      window.location.href = `${protocol}//${slug}.localhost${port ? `:${port}` : ''}/login`
      return
    }

    if (
      tenantBaseDomain &&
      (hostname === portalHostname || hostname === tenantBaseDomain || hostname.endsWith(`.${tenantBaseDomain}`))
    ) {
      window.location.href = `${protocol}//${slug}.${tenantBaseDomain}/login`
      return
    }
  }

  if (!tenantSlug && !isAdminHost()) {
    return (
      <div className="login-portal-container">
        <div className="selection-area">
          <img src="/imge_onec.png" alt="ONEC-RDC" className="portal-logo" />
          <h1 className="portal-title">Bienvenue sur ONEC Smart</h1>
          <p className="portal-description portal-description-strong">
            Plateforme intelligente de gestion intégrée de l'ONEC-RDC
          </p>
          <p className="portal-description">
            Veuillez sélectionner votre antenne provinciale pour accéder à votre espace sécurisé.
          </p>

          <div ref={dropdownRef} className="portal-dropdown-wrap">
            <button
              type="button"
              className="dropdown-trigger"
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              aria-expanded={isDropdownOpen}
              aria-haspopup="listbox"
            >
              <span>Choisir une antenne...</span>
              <span className={`dropdown-arrow ${isDropdownOpen ? 'open' : ''}`}>▼</span>
            </button>

            <div className={`dropdown-menu ${isDropdownOpen ? 'open' : ''}`} role="listbox">
              <div className="dropdown-search-container">
                <input
                  type="text"
                  className="dropdown-search-input"
                  placeholder="Rechercher..."
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  autoFocus={isDropdownOpen}
                  onClick={(event) => event.stopPropagation()}
                />
              </div>
              {filteredSites.map((site) => (
                <button
                  key={site.slug}
                  type="button"
                  className="site-item"
                  onClick={() => handleSelectTenant(site.slug)}
                >
                  <span className="site-icon">🏢</span>
                  <span className="site-name">{site.nom}</span>
                  <span className="site-badge">{site.slug}</span>
                </button>
              ))}
              {filteredSites.length === 0 && (
                <div className="portal-empty">Aucun résultat</div>
              )}
            </div>
          </div>

          <p className="portal-help">Besoin d'aide ? Contactez l'administrateur système.</p>
        </div>
      </div>
    )
  }

  const currentTenant = tenantSlug
    ? publicTenants.find((tenant) => tenant.slug === tenantSlug) || orgInfo
    : null
  const isPortalLogin = !tenantSlug && !isAdminHost()
  const tenantDisplayName = orgInfo?.nom || currentTenant?.nom || 'Portail national ONEC RDC'
  const loginSubtitle = isPortalLogin
    ? "Sélectionnez votre organisation pour accéder à l'espace sécurisé."
    : "Plateforme numérique de gestion intégrée de l'Ordre National des Experts Comptables"

  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const { innerWidth, innerHeight } = window
    if (innerWidth < 1024) return
    const x = (event.clientX / innerWidth - 0.5)
    const y = (event.clientY / innerHeight - 0.5)
    setParallax({ x, y })
  }

  const renderTenantDropdown = () => (
    <div ref={dropdownRef} className="antenna-switcher">
      <button
        type="button"
        className="antenna-button"
        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
        aria-expanded={isDropdownOpen}
        aria-haspopup="listbox"
      >
        <Building2 size={18} className="antenna-icon" />
        <span>{currentTenant?.nom || "Changer d'antenne"}</span>
        <ChevronDown size={17} className={isDropdownOpen ? 'antenna-chevron open' : 'antenna-chevron'} />
      </button>

      <div className={`antenna-menu ${isDropdownOpen ? 'open' : ''}`} role="listbox">
        <div className="tenant-search-wrap">
          <input
            type="text"
            className="tenant-search"
            placeholder="Rechercher une antenne"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus={isDropdownOpen}
            onClick={(e) => e.stopPropagation()}
          />
        </div>
        <div className="tenant-list">
          {filteredSites.map(site => (
            <button key={site.slug} type="button" className="tenant-option" onClick={() => handleSelectTenant(site.slug)}>
              {site.logo_url ? (
                <img src={buildUploadUrl(site.logo_url)} alt="" className="tenant-option-logo" />
              ) : (
                <Building2 size={18} className="tenant-option-icon" />
              )}
              <span>
                <strong>{site.nom}</strong>
                <small>{site.slug}</small>
              </span>
            </button>
          ))}
          {filteredSites.length === 0 && (
            <div className="tenant-empty">Aucune antenne trouvée</div>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div
      className="login-page"
      onMouseMove={handleMouseMove}
      style={{
        '--login-parallax-x': `${parallax.x}px`,
        '--login-parallax-y': `${parallax.y}px`,
      } as React.CSSProperties}
    >
      <div className="login-background" aria-hidden="true">
        <svg
          className="network-svg"
          viewBox="0 0 1600 900"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden="true"
        >
          <g stroke="currentColor" strokeWidth="1" fill="none">
            <line x1="80" y1="170" x2="260" y2="260" />
            <line x1="260" y1="260" x2="420" y2="160" />
            <line x1="260" y1="260" x2="360" y2="390" />
            <line x1="420" y1="160" x2="560" y2="245" />
            <line x1="1230" y1="160" x2="1410" y2="260" />
            <line x1="1410" y1="260" x2="1510" y2="410" />
            <line x1="1230" y1="160" x2="1190" y2="330" />
            <line x1="1190" y1="330" x2="1340" y2="430" />
          </g>
          <g fill="currentColor">
            <circle cx="80" cy="170" r="5" />
            <circle cx="260" cy="260" r="7" />
            <circle cx="420" cy="160" r="4" />
            <circle cx="360" cy="390" r="5" />
            <circle cx="560" cy="245" r="4" />
            <circle cx="1230" cy="160" r="5" />
            <circle cx="1410" cy="260" r="7" />
            <circle cx="1510" cy="410" r="5" />
            <circle cx="1190" cy="330" r="4" />
            <circle cx="1340" cy="430" r="4" />
          </g>
        </svg>
        <div className="network-orbit orbit-one" />
        <div className="network-orbit orbit-two" />
        <div className="digital-grid" />
        <div className="light-beam beam-one" />
        <div className="light-beam beam-two" />
        <div className="network network-left" />
        <div className="network network-right" />
        <div className="login-skyline" />
      </div>

      {!isAdminHost() && renderTenantDropdown()}

      <main className={`login-card ${error ? 'has-error' : ''} ${loginSuccess ? 'is-success' : ''}`}>
          <div className="login-header">
            <img 
              src={orgInfo?.logo_url ? buildUploadUrl(orgInfo.logo_url) : "/imge_onec.png"} 
              alt="ONEC RDC"
              className="login-logo"
            />
            <h1 className="login-council-title">{tenantDisplayName}</h1>
            <div className="title-divider"><span /></div>
            <h2 className="login-product-title">ONEC Smart</h2>
            <p className="login-subtitle">{loginSubtitle}</p>
          </div>

          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}

          {loginSuccess && (
            <div className="login-success" role="status">
              <CheckCircle2 size={18} /> Connexion réussie
            </div>
          )}

          {step === 'login' && (
            <form onSubmit={handleSubmit} className="login-form">
              <div className="form-group">
                <label htmlFor="login-email">Adresse e-mail</label>
                <div className="input-wrapper">
                  <span className="input-icon"><Mail size={20} /></span>
                <input
                  id="login-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="nom@onec.cd"
                  autoComplete="username"
                />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="login-password">Mot de passe</label>
                <div className="input-wrapper">
                <span className="input-icon"><LockKeyhole size={20} /></span>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="Mot de passe"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="password-toggle"
                  title={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
                </div>
              </div>

              <button
                type="submit" 
                disabled={loading || loginSuccess || loginLockSeconds > 0}
                className="login-submit"
              >
                {loginSuccess ? (
                  <><span>Connexion réussie</span><CheckCircle2 size={21} /></>
                ) : loginLockSeconds > 0 ? (
                  <span>Réessayer dans {formatLoginLockTime(loginLockSeconds)}</span>
                ) : loading ? (
                  <><Loader2 size={20} className="spin" /><span>Connexion sécurisée...</span></>
                ) : (
                  <><span>Se connecter</span><ArrowRight size={21} /></>
                )}
              </button>
              
              <button 
                  type="button" 
                  onClick={() => navigate('/forgot-password')}
                  className="forgot-password"
                >
                  Mot de passe oublié ?
                </button>
            </form>
          )}

          {step === 'set-password' && (
            <form onSubmit={handleSendOtp} className="login-form">
              <p className="step-copy">
                C'est votre première connexion. Veuillez définir un mot de passe sécurisé.
              </p>
              <div className="form-group">
                <label>Nouveau mot de passe</label>
                <div className="input-wrapper">
                <span className="input-icon"><LockKeyhole size={20} /></span>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  placeholder="Nouveau mot de passe"
                  autoComplete="new-password"
                />
                </div>
              </div>
              <div className="form-group">
                <label>Confirmer le mot de passe</label>
                <div className="input-wrapper">
                <span className="input-icon"><LockKeyhole size={20} /></span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  placeholder="Confirmer le mot de passe"
                  autoComplete="new-password"
                />
                </div>
              </div>
              <button 
                type="submit" 
                disabled={sendingOtp}
                className="login-submit"
              >
                {sendingOtp ? <><Loader2 size={18} className="spin" /> Envoi du code...</> : 'Définir le mot de passe'}
              </button>
            </form>
          )}

          {step === 'verify-otp' && (
            <form onSubmit={handleConfirmOtp} className="login-form">
              <p className="step-copy">
                Un code de vérification a été envoyé à <strong>{email}</strong>.
              </p>
              <div className="form-group">
                <label>Code de vérification</label>
                <div className="input-wrapper otp-wrapper">
                <input
                  type="text"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
                  required
                  placeholder="000000"
                  maxLength={6}
                  inputMode="numeric"
                />
                </div>
                <small>{cooldown > 0 ? `Renvoyer dans ${cooldown}s` : "Vous n'avez rien reçu ?"}</small>
              </div>
              <button 
                type="submit" 
                disabled={verifyingOtp}
                className="login-submit"
              >
                {verifyingOtp ? <><Loader2 size={18} className="spin" /> Vérification...</> : 'Confirmer le code'}
              </button>
            </form>
          )}

          <footer className="login-footer">
            <ShieldCheck size={19} />
            <span>Connexion sécurisée · ONEC RDC</span>
          </footer>
      </main>

      {adminBlocked && (
        <div className="admin-mode-badge">
          Mode Administration Activé
        </div>
      )}
    </div>
  )
}
