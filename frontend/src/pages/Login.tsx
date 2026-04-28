import { useEffect, useState, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { confirmPasswordChange, requestPasswordReset } from '../api/auth'
import { getOrganisationPublic, listPublicOrganisations, type OrganisationPublicInfo } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import { getPortalOrigin, getTenantSlug, isAdminHost, isTenantSubdomainHost, setTenantOverride } from '../utils/tenant'
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

  const handleResetSite = () => {
    const portalOrigin = getPortalOrigin()
    const portalLoginUrl = portalOrigin ? `${portalOrigin}/login` : '/login'
    if (isTenantSubdomainHost()) {
      window.location.href = portalLoginUrl
    } else {
      setTenantSlug(null)
      setTenantOverride(null)
    }
  }

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
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

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
    setError('')
    if (!tenantSlug && !isAdminHost()) {
      setError('Veuillez sélectionner un site')
      return
    }
    setLoading(true)
    try {
      const res = await signIn(email, password)
      if (res.requires_otp) setStep('set-password')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de connexion')
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

    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      window.location.href = `${protocol}//${slug}.localhost${port ? `:${port}` : ''}/login`
      return
    }

    if (hostname === 'www.onec-rdc.org' || hostname === 'onec-rdc.org') {
      window.location.href = `${protocol}//${slug}.onec-rdc.org/login`
      return
    }
  }

  return (
    <div className="login-portal-container">
      {!tenantSlug && !isAdminHost() ? (
        <div className="selection-area">
          <img src="/imge_onec.png" alt="ONEC-RDC" className="portal-logo" />
          <h1 className="portal-title">Bienvenue sur l'interface de gestion de la trésorerie de l'ONEC-RDC</h1>
          <p style={{ color: '#718096', marginBottom: '30px', fontSize: '16px' }}>
            Veuillez sélectionner votre antenne provinciale pour accéder à votre espace sécurisé.
          </p>
          
          <div ref={dropdownRef} style={{ position: 'relative' }}>
            <div className="dropdown-trigger" onClick={() => setIsDropdownOpen(!isDropdownOpen)}>
              <span>{tenantSlug ? tenantSlug.toUpperCase() : 'Choisir une antenne...'}</span>
              <span className={`dropdown-arrow ${isDropdownOpen ? 'open' : ''}`}>▼</span>
            </div>

            <div className={`dropdown-menu ${isDropdownOpen ? 'open' : ''}`}>
              <div className="dropdown-search-container">
                <input 
                  type="text" 
                  className="dropdown-search-input"
                  placeholder="Rechercher..." 
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus={isDropdownOpen}
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
              {filteredSites.map(site => (
                <div key={site.slug} className="site-item" onClick={() => handleSelectTenant(site.slug)}>
                  <span className="site-icon">🏢</span>
                  <span className="site-name">{site.nom}</span>
                  <span className="site-badge">{site.slug}</span>
                </div>
              ))}
              {filteredSites.length === 0 && (
                <div style={{ padding: '20px', color: '#94a3b8', fontSize: '14px', textAlign: 'center' }}>
                  Aucun résultat
                </div>
              )}
            </div>
          </div>
          
          <p style={{ marginTop: '40px', fontSize: '13px', color: '#94a3b8' }}>
            Besoin d'aide ? Contactez l'administrateur système.
          </p>
        </div>
      ) : (
        <div className="login-card">
          {!isAdminHost() && (
            <button
              type="button"
              className="back-link"
              onClick={handleResetSite}
              style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: '8px',
                color: '#00A09D', 
                fontWeight: '600',
                fontSize: '13px',
                marginBottom: '30px'
              }}
            >
              ⇄ Changer d'antenne
            </button>
          )}

          <div style={{ textAlign: 'center', marginBottom: '40px' }}>
            <img 
              src={orgInfo?.logo_url || "/imge_onec.png"} 
              alt="Logo" 
              style={{ height: '70px', marginBottom: '15px', display: 'block', margin: '0 auto 20px' }} 
            />
            <h2 style={{
              fontSize: '42px',
              fontWeight: 'normal',
              color: '#1a202c',
              margin: '0',
              fontFamily: "'Edwardian Script ITC', 'ITC Edwardian Script', 'Brush Script MT', cursive",
              lineHeight: '1.2'
            }}>
              {orgInfo?.nom || (tenantSlug ? tenantSlug.toUpperCase() : 'Connexion')}
            </h2>            <p style={{ color: '#718096', fontSize: '14px', marginTop: '5px' }}>
              Connectez-vous à votre espace de travail sécurisé.
            </p>
          </div>

          {error && (
            <div style={{ color: '#e53e3e', fontSize: '14px', marginBottom: '20px', padding: '12px', background: '#fff5f5', borderRadius: '8px' }}>
              {error}
            </div>
          )}

          {step === 'login' && (
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '20px' }}>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="dropdown-search-input"
                  placeholder="Adresse email"
                  style={{ padding: '15px' }}
                />
              </div>

              <div style={{ marginBottom: '30px', position: 'relative' }}>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="dropdown-search-input"
                  placeholder="Mot de passe"
                  style={{ padding: '15px' }}
                />
                <span 
                  onClick={() => setShowPassword(!showPassword)}
                  style={{ position: 'absolute', right: '15px', top: '50%', transform: 'translateY(-50%)', cursor: 'pointer', opacity: 0.5 }}
                >
                  {showPassword ? '🙈' : '👁️'}
                </span>
              </div>

              <button 
                type="submit" 
                disabled={loading}
                style={{ 
                  width: '100%', padding: '16px', borderRadius: '12px', background: '#1a202c', 
                  color: 'white', border: 'none', fontWeight: '600', cursor: 'pointer',
                  fontSize: '16px'
                }}
              >
                {loading ? 'Chargement...' : 'Se connecter'}
              </button>
              
              <div style={{ marginTop: '20px', textAlign: 'center' }}>
                <button 
                  type="button" 
                  onClick={() => navigate('/forgot-password')}
                  style={{ background: 'none', border: 'none', color: '#718096', cursor: 'pointer', fontSize: '13px' }}
                >
                  Mot de passe oublié ?
                </button>
              </div>
            </form>
          )}

          {step === 'set-password' && (
            <form onSubmit={handleSendOtp}>
              <p style={{ fontSize: '14px', color: '#718096', marginBottom: '20px' }}>
                C'est votre première connexion. Veuillez définir un mot de passe sécurisé.
              </p>
              <div style={{ marginBottom: '20px' }}>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  className="dropdown-search-input"
                  placeholder="Nouveau mot de passe"
                  style={{ padding: '15px' }}
                />
              </div>
              <div style={{ marginBottom: '25px' }}>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="dropdown-search-input"
                  placeholder="Confirmer le mot de passe"
                  style={{ padding: '15px' }}
                />
              </div>
              <button 
                type="submit" 
                disabled={sendingOtp}
                style={{ 
                  width: '100%', padding: '16px', borderRadius: '12px', background: '#1a202c', 
                  color: 'white', border: 'none', fontWeight: '600', cursor: 'pointer'
                }}
              >
                {sendingOtp ? 'Envoi du code...' : 'Définir le mot de passe'}
              </button>
            </form>
          )}

          {step === 'verify-otp' && (
            <form onSubmit={handleConfirmOtp}>
              <p style={{ fontSize: '14px', color: '#718096', marginBottom: '20px' }}>
                Un code de vérification a été envoyé à <strong>{email}</strong>.
              </p>
              <div style={{ marginBottom: '25px' }}>
                <input
                  type="text"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
                  required
                  className="dropdown-search-input"
                  placeholder="000000"
                  maxLength={6}
                  style={{ padding: '15px', textAlign: 'center', letterSpacing: '8px', fontSize: '20px', fontWeight: 'bold' }}
                />
                <p style={{ textAlign: 'center', fontSize: '12px', color: '#94a3b8', marginTop: '10px' }}>
                  {cooldown > 0 ? `Renvoyer dans ${cooldown}s` : "Vous n'avez rien reçu ?"}
                </p>
              </div>
              <button 
                type="submit" 
                disabled={verifyingOtp}
                style={{ 
                  width: '100%', padding: '16px', borderRadius: '12px', background: '#00A09D', 
                  color: 'white', border: 'none', fontWeight: '600', cursor: 'pointer'
                }}
              >
                {verifyingOtp ? 'Vérification...' : 'Confirmer le code'}
              </button>
            </form>
          )}
        </div>
      )}

      {adminBlocked && (
        <div style={{ position: 'fixed', bottom: '20px', background: '#1a202c', color: 'white', padding: '10px 20px', borderRadius: '50px', fontSize: '12px' }}>
          Mode Administration Activé
        </div>
      )}
    </div>
  )
}
