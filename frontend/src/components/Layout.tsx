import { useEffect, useState } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { getCashForecast } from '../api/ai'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { useMobile } from '../hooks/useMobile'
import ChangePasswordModal from './ChangePasswordModal'
import OnecMind from './OnecMind'
import BillingAlert from './BillingAlert'
import MobileBottomNav from './MobileBottomNav'
import {
  clearImpersonationReturnToken,
  getImpersonationReturnToken,
  setAccessToken,
} from '../lib/apiClient'
import { setTenantOverride, getPortalOrigin, isTenantSubdomainHost } from '../utils/tenant'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import styles from './Layout.module.css'
import {
  ArrowDownCircle,
  Building2,
  ChevronDown,
  CircleDollarSign,
  Cog,
  FileBarChart2,
  FileText,
  Landmark,
  LayoutDashboard,
  LogOut,
  Receipt,
  Send,
  Settings2,
  ShieldCheck,
  UserCog,
  Wallet,
} from 'lucide-react'

interface NavItem {
  path?: string
  label: string
  permission: string
  icon: React.ReactNode
  subItems?: NavItem[]
  serviceOnly?: boolean
  hideForService?: boolean
  matchPathPrefixes?: string[]
}

export default function Layout() {
  const { user, signOut } = useAuth()
  const { settings: orgSettings } = useOrganisationSettings()
  const location = useLocation()
  const navigate = useNavigate()
  const { hasPermission, loading } = usePermissions()
  const serviceIds =
    user?.service_ids && user.service_ids.length > 0
      ? user.service_ids
      : user?.service_id
        ? [user.service_id]
        : []
  const isServiceUser = serviceIds.length > 0
  const isAdminUser = user?.role === 'admin' || user?.role === 'super_admin'
  const isSuperAdmin = user?.role === 'super_admin'
  const serviceNavPath = serviceIds.length === 1 ? `/services/mon-espace/${serviceIds[0]}` : '/services'
  const serviceNavLabel = 'Services'
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [cashAlert, setCashAlert] = useState<any | null>(null)
  const [paymentAlert, setPaymentAlert] = useState<string | null>(null)
  const [impersonationToken, setImpersonationToken] = useState<string | null>(null)
  const isMobile = useMobile()

  useEffect(() => {
    if (!orgSettings) return
    const root = document.documentElement
    if (orgSettings.theme_primary_color) {
      root.style.setProperty('--tenant-primary', orgSettings.theme_primary_color)
    }
    if (orgSettings.theme_sidebar_color) {
      root.style.setProperty('--tenant-sidebar', orgSettings.theme_sidebar_color)
    }
    if (orgSettings.theme_sidebar_text_color) {
      root.style.setProperty('--tenant-sidebar-text', orgSettings.theme_sidebar_text_color)
    }
    if (orgSettings.theme_sidebar_active_color) {
      root.style.setProperty('--tenant-sidebar-active', orgSettings.theme_sidebar_active_color)
    }
    if (orgSettings.theme_accent_color) {
      root.style.setProperty('--tenant-accent', orgSettings.theme_accent_color)
    }
    if (orgSettings.theme_text_color) {
      root.style.setProperty('--tenant-text', orgSettings.theme_text_color)
    }
    if (orgSettings.theme_button_text_color) {
      root.style.setProperty('--tenant-button-text', orgSettings.theme_button_text_color)
    }
  }, [orgSettings])

  const handleSignOut = async () => {
    try {
      await signOut()
      navigate('/login')
    } catch (error) {
      console.error('Error signing out:', error)
    }
  }

  const handleChangeTenant = async () => {
    const portalOrigin = getPortalOrigin()
    const portalLoginUrl = portalOrigin ? `${portalOrigin}/login` : '/login'
    
    try {
      await signOut()
    } catch (error) {
      console.error('Error signing out for tenant switch:', error)
    } finally {
      setMobileMenuOpen(false)
      setAccessToken(null)
      setTenantOverride(null)
      
      if (isTenantSubdomainHost()) {
        window.location.href = portalLoginUrl
      } else {
        navigate('/login', { replace: true })
      }
    }
  }

  const navItems: NavItem[] = [
    {
      path: serviceNavPath,
      label: serviceNavLabel,
      permission: 'services',
      icon: <Building2 size={18} />,
      serviceOnly: true,
      matchPathPrefixes: ['/services', '/services/mon-espace'],
    },
    { path: '/', label: 'Tableaux de bord', permission: 'dashboard', icon: <LayoutDashboard size={18} />, hideForService: true },
    { path: '/encaissements', label: 'Encaissements', permission: 'encaissements', icon: <CircleDollarSign size={18} />, hideForService: true },
    {
      label: 'Réquisitions',
      permission: 'requisitions',
      icon: <Receipt size={18} />,
      subItems: [
        { path: '/requisitions', label: 'Réquisitions classiques', permission: 'requisitions', icon: <Receipt size={16} /> },
        { path: '/remboursement-transport', label: 'Remboursement frais transport', permission: 'remboursement_transport', icon: <Wallet size={16} /> },
        { path: '/requisitions-ocr', label: 'Analyse PDF réquisitions', permission: 'requisitions_ocr', icon: <FileText size={16} /> },
      ]
    },
    {
      label: 'Validation',
      permission: 'validation',
      icon: <ShieldCheck size={18} />,
      hideForService: true,
      subItems: [
        { path: '/validation', label: 'Validation', permission: 'validation', icon: <Send size={16} /> },
        { path: '/validation/examens', label: "Dossiers d'examen", permission: 'validation_examens', icon: <FileText size={16} /> },
      ],
    },
    {
      label: 'Sorties de fonds',
      permission: 'sorties_fonds',
      icon: <Landmark size={18} />,
      hideForService: true,
      subItems: [
        { path: '/sorties-fonds', label: 'Sorties de fonds', permission: 'sorties_fonds', icon: <Wallet size={16} /> },
        { path: '/cloture-caisse', label: 'Clôture de caisse', permission: 'cloture_caisse', icon: <FileBarChart2 size={16} /> },
      ]
    },
    { path: '/budget', label: 'Budget', permission: 'budget', icon: <FileBarChart2 size={18} />, hideForService: true },
    { path: '/services', label: 'Services', permission: 'services', icon: <Building2 size={18} />, hideForService: true },
    {
      label: 'Rapports',
      permission: 'rapports',
      icon: <FileBarChart2 size={18} />,
      hideForService: true,
      subItems: [
        { path: '/rapports', label: 'Tableaux & exports', permission: 'rapports', icon: <FileBarChart2 size={16} /> },
        { path: '/audit-logs', label: 'Audit système', permission: 'audit_logs', icon: <ShieldCheck size={16} /> },
      ]
    },
    {
      label: 'Experts-Comptables',
      permission: 'experts_comptables',
      icon: <UserCog size={18} />,
      hideForService: true,
      subItems: [
        { path: '/experts-comptables', label: 'Liste des experts', permission: 'experts_comptables', icon: <UserCog size={16} /> },
        { path: '/historique-imports', label: 'Historique des imports', permission: 'historique_imports', icon: <FileText size={16} /> },
      ]
    },
    {
      label: 'Paramètres',
      permission: 'settings',
      icon: <Cog size={18} />,
      hideForService: true,
      subItems: [
        { path: '/organisation-settings', label: 'Organisation', permission: 'organisation_settings', icon: <Building2 size={16} /> },
        { path: '/settings', label: 'Généraux', permission: 'settings', icon: <Settings2 size={16} /> },
        { path: '/denominations', label: 'Configuration billets', permission: 'denominations', icon: <Wallet size={16} /> },
      ]
    },
  ]

  const mobileNavItems = [
    { path: '/', label: 'Tableau de bord', icon: <LayoutDashboard size={22} />, permission: 'dashboard' },
    { path: '/encaissements', label: 'Encaissements', icon: <ArrowDownCircle size={22} />, permission: 'encaissements' },
    { path: '/requisitions', label: 'Réquisitions', icon: <FileText size={22} />, permission: 'requisitions' },
    { path: '/validation', label: 'Validation', icon: <Send size={22} />, permission: 'validation' },
    { path: '/sorties-fonds', label: 'Sorties', icon: <Wallet size={22} />, permission: 'sorties_fonds' },
  ]

  const canAccessRoute = (permission: string) => hasPermission(permission)

  const canAccessNavItem = (item: NavItem): boolean => {
    if (item.serviceOnly && (!isServiceUser || isAdminUser)) return false
    if (item.hideForService && isServiceUser && !isAdminUser) return false
    if (item.subItems) {
      return item.subItems.some((subItem) => canAccessRoute(subItem.permission))
    }
    return canAccessRoute(item.permission)
  }

  const toggleExpanded = (label: string) => {
    setExpandedItems(prev => {
      const newSet = new Set(prev)
      if (newSet.has(label)) {
        newSet.delete(label)
      } else {
        newSet.add(label)
      }
      return newSet
    })
  }

  const isPathActive = (path?: string, subItems?: NavItem[], matchPathPrefixes?: string[]) => {
    if (matchPathPrefixes && matchPathPrefixes.length > 0) {
      return matchPathPrefixes.some((prefix) => location.pathname.startsWith(prefix))
    }
    if (path) {
      return location.pathname === path
    }
    if (subItems) {
      return subItems.some(item => item.path && location.pathname === item.path)
    }
    return false
  }

  const handleLinkClick = () => {
    setMobileMenuOpen(false)
  }

  useEffect(() => {
    if (loading) return
    if (!orgSettings?.is_ai_enabled) {
      setCashAlert(null)
      return
    }
    let cancelled = false

    const loadAlert = async () => {
      try {
        const res = await getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 })
        if (!cancelled) setCashAlert(res)
      } catch (error) {
        if (!cancelled) setCashAlert(null)
      }
    }

    loadAlert()
    const intervalId = window.setInterval(loadAlert, 300000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [loading, orgSettings?.is_ai_enabled])

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail
      setPaymentAlert(detail?.message || 'Votre abonnement a expiré. Passage en lecture seule.')
    }
    window.addEventListener('payment-required', handler as EventListener)
    return () => {
      window.removeEventListener('payment-required', handler as EventListener)
    }
  }, [])

  useEffect(() => {
    const status = (user?.plan_status || '').toUpperCase()
    if (status && status !== 'ACTIVE' && status !== 'TRIAL') {
      setPaymentAlert('Votre abonnement a expiré. Passage en lecture seule.')
    }
  }, [user?.plan_status])

  useEffect(() => {
    setImpersonationToken(getImpersonationReturnToken())
  }, [user?.id])

  useEffect(() => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      navItems.forEach((item) => {
        if (item.subItems && isPathActive(item.path, item.subItems, item.matchPathPrefixes)) {
          next.add(item.label)
        }
      })
      return next
    })
  }, [location.pathname])

  const renderNavItem = (item: NavItem) => {
    if (!canAccessNavItem(item)) return null

    const hasSubItems = item.subItems && item.subItems.length > 0
    const isExpanded = expandedItems.has(item.label)
    const isActive = isPathActive(item.path, item.subItems, item.matchPathPrefixes)

    if (hasSubItems) {
      return (
        <div key={item.label} className={styles.navItemWithSub}>
          <div
            className={`${styles.navItem} ${isActive ? styles.active : ''} ${styles.hasSubmenu}`}
            onClick={() => toggleExpanded(item.label)}
          >
            <span className={styles.navItemContent}>
              <span className={styles.navIcon}>{item.icon}</span>
              <span>{item.label}</span>
            </span>
            <span className={`${styles.arrow} ${isExpanded ? styles.arrowExpanded : ''}`}>
              <ChevronDown size={16} />
            </span>
          </div>
          {isExpanded && (
            <div className={styles.subMenu}>
              {item.subItems!.filter(subItem => canAccessRoute(subItem.permission)).map(subItem => (
                <Link
                  key={subItem.path}
                  to={subItem.path!}
                  className={`${styles.subNavItem} ${location.pathname === subItem.path ? styles.active : ''}`}
                  onClick={handleLinkClick}
                >
                  <span className={styles.subNavIcon}>{subItem.icon}</span>
                  {subItem.label}
                </Link>
              ))}
            </div>
          )}
        </div>
      )
    }

    return (
      <Link
        key={item.path}
        to={item.path!}
        className={`${styles.navItem} ${isActive ? styles.active : ''}`}
        onClick={handleLinkClick}
      >
        <span className={styles.navItemContent}>
          <span className={styles.navIcon}>{item.icon}</span>
          <span>{item.label}</span>
        </span>
      </Link>
    )
  }

  if (loading) {
    return <div>Chargement...</div>
  }

  return (
    <div className={styles.layout}>
      <button
        className={styles.mobileMenuToggle}
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        aria-label="Toggle menu"
      >
        <span className={styles.hamburger}></span>
        <span className={styles.hamburger}></span>
        <span className={styles.hamburger}></span>
      </button>

      {mobileMenuOpen && (
        <div
          className={styles.overlay}
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <aside className={`${styles.sidebar} ${mobileMenuOpen ? styles.sidebarOpen : ''}`}>
        <div className={styles.logo}>
          <img src="/imge_onec.png" alt="ONEC Logo" className={styles.logoImage} />
          <p>Gestion de Trésorerie</p>
          {isServiceUser && !isAdminUser && <span className={styles.serviceBadge}>Espace Commission</span>}
          {user?.plan_status && (
            <span
              className={`${styles.planBadge} ${
                user.plan_status?.toUpperCase() === 'ACTIVE'
                  ? styles.planActive
                  : user.plan_status?.toUpperCase() === 'TRIAL'
                    ? styles.planTrial
                    : styles.planExpired
              }`}
            >
              {user.plan_type ? `${user.plan_type} · ` : ''}
              {user.plan_status}
            </span>
          )}
        </div>

        <nav className={styles.nav}>
          {navItems.map(item => renderNavItem(item))}
          {isSuperAdmin && (
            <Link
              to="/super-admin"
              className={`${styles.navItem} ${location.pathname === '/super-admin' ? styles.active : ''}`}
              onClick={handleLinkClick}
            >
              <span className={styles.navItemContent}>
                <span className={styles.navIcon}><Cog size={18} /></span>
                <span>Console SaaS</span>
              </span>
            </Link>
          )}
        </nav>

        <div className={styles.userInfo}>
          <div className={styles.userIdentity}>
            <div className={styles.userAvatar}>
              {(user?.prenom?.[0] || '').toUpperCase()}
              {(user?.nom?.[0] || '').toUpperCase()}
            </div>
            <div>
              <div className={styles.userName}>
                {user?.prenom} {user?.nom}
              </div>
              <div className={styles.userRole}>{user?.role}</div>
            </div>
          </div>
          <div className={styles.userActions}>
          <button
            onClick={() => {
              setShowChangePassword(true)
              setMobileMenuOpen(false)
            }}
            className={styles.changePasswordBtn}
          >
            <UserCog size={16} />
            <span>Mot de passe</span>
          </button>
          <button onClick={handleChangeTenant} className={styles.changeTenantBtn}>
            <Building2 size={16} />
            <span>Changer d'antenne</span>
          </button>
          <button onClick={handleSignOut} className={styles.signOutBtn}>
            <LogOut size={16} />
            <span>Déconnexion</span>
          </button>
          </div>
        </div>
      </aside>

      <main className={`${styles.main} ${location.pathname === '/settings' ? styles.mainAllowXScroll : ''}`}>
        <BillingAlert />
        {paymentAlert && (
          <div className={styles.paymentBanner} role="alert">
            <span>{paymentAlert}</span>
            <button type="button" className={styles.paymentAction} onClick={() => navigate('/organisation-settings')}>
              Régulariser
            </button>
          </div>
        )}
        {impersonationToken && user?.role !== 'super_admin' && (
          <div className={styles.paymentBanner} role="alert">
            <span>Mode impersonation actif. Vos actions sont journalisées.</span>
            <button
              type="button"
              className={styles.paymentAction}
              onClick={async () => {
                setAccessToken(impersonationToken)
                clearImpersonationReturnToken()
                window.location.href = '/super-admin'
              }}
            >
              Revenir Super Admin
            </button>
          </div>
        )}
        {cashAlert?.risk_level === 'CRITICAL' && (
          <div className={styles.criticalAlertBar} role="alert">
            <span>
              ⚠️ Vigilance : Le volume des réquisitions en attente menace la réserve de sécurité à 30 jours.
            </span>
            <button
              type="button"
              className={styles.alertAction}
              onClick={() => navigate('/?focus=forecast&stress=1')}
            >
              Voir l’analyse
            </button>
          </div>
        )}
        <Outlet />
      </main>

      {isMobile && (
        <MobileBottomNav items={mobileNavItems} hasPermission={canAccessRoute} />
      )}

      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}

      {orgSettings?.is_ai_enabled && <OnecMind />}
    </div>
  )
}
