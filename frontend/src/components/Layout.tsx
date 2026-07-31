import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { getCashForecast } from '../api/ai'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { useMobile } from '../hooks/useMobile'
import { useApp, detectAppFromPath } from '../contexts/AppContext'
import ChangePasswordModal from './ChangePasswordModal'
import OnecMind from './OnecMind'
import BillingAlert from './BillingAlert'
import MobileBottomNav from './MobileBottomNav'
import WaterFlow from './WaterFlow'
import AppSwitcher from './AppSwitcher'
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
  BookOpenCheck,
  Briefcase,
  Building2,
  Bot,
  Calendar,
  CalendarDays,
  ChevronDown,
  CircleDollarSign,
  Clock,
  Cog,
  FileBarChart2,
  FileText,
  FolderOpen,
  Landmark,
  LayoutDashboard,
  LogOut,
  PanelLeft,
  PanelLeftClose,
  Receipt,
  Send,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Table2,
  UserCog,
  Users,
  Wallet,
} from 'lucide-react'

interface NavItem {
  path?: string
  label: string
  permission: string | string[]
  icon: React.ReactNode
  subItems?: NavItem[]
  matchPathPrefixes?: string[]
}

const TREASURY_NAV: NavItem[] = [
  { path: '/', label: 'Tableaux de bord', permission: 'dashboard', icon: <LayoutDashboard size={18} /> },
  { path: '/encaissements', label: 'Encaissements', permission: 'encaissements', icon: <CircleDollarSign size={18} /> },
  {
    label: 'Réquisitions',
    permission: 'requisitions',
    icon: <Receipt size={18} />,
    subItems: [
      { path: '/requisitions', label: 'Réquisitions classiques', permission: 'requisitions', icon: <Receipt size={16} /> },
      { path: '/requisitions/sortie-directe', label: 'Sortie directe programmée', permission: 'sorties_fonds', icon: <Wallet size={16} /> },
      { path: '/remboursement-transport', label: 'Remboursement frais transport', permission: 'remboursement_transport', icon: <Wallet size={16} /> },
      { path: '/requisitions-ocr', label: 'Analyse PDF réquisitions', permission: 'requisitions_ocr', icon: <FileText size={16} /> },
    ],
  },
  {
    label: 'Validation',
    permission: 'validation',
    icon: <ShieldCheck size={18} />,
    subItems: [
      { path: '/validation', label: 'Validation', permission: 'validation', icon: <Send size={16} /> },
      { path: '/validation/examens', label: "Dossiers d'examen", permission: 'validation_examens', icon: <FileText size={16} /> },
    ],
  },
  {
    label: 'Sorties de fonds',
    permission: 'sorties_fonds',
    icon: <Landmark size={18} />,
    subItems: [
      { path: '/sorties-fonds', label: 'Sorties de fonds', permission: 'sorties_fonds', icon: <Wallet size={16} /> },
      { path: '/cloture-caisse', label: 'Clôture de caisse', permission: 'cloture_caisse', icon: <FileBarChart2 size={16} /> },
    ],
  },
  { path: '/budget', label: 'Budget', permission: 'budget', icon: <FileBarChart2 size={18} /> },
  {
    label: 'Rapports',
    permission: 'rapports',
    icon: <FileBarChart2 size={18} />,
    subItems: [
      { path: '/rapports', label: 'Tableaux & exports', permission: 'rapports', icon: <FileBarChart2 size={16} /> },
      { path: '/audit-logs', label: 'Audit système', permission: 'audit_logs', icon: <ShieldCheck size={16} /> },
    ],
  },
  {
    label: 'Experts-Comptables',
    permission: 'experts_comptables',
    icon: <UserCog size={18} />,
    subItems: [
      { path: '/experts-comptables', label: 'Liste des experts', permission: 'experts_comptables', icon: <UserCog size={16} /> },
      { path: '/historique-imports', label: 'Historique des imports', permission: 'historique_imports', icon: <FileText size={16} /> },
    ],
  },
  {
    label: 'Paramètres',
    permission: 'settings',
    icon: <Cog size={18} />,
    subItems: [
      { path: '/organisation-settings', label: 'Organisation', permission: 'organisation_settings', icon: <Building2 size={16} /> },
      { path: '/settings', label: 'Généraux', permission: 'settings', icon: <Settings2 size={16} /> },
      { path: '/denominations', label: 'Configuration billets', permission: 'denominations', icon: <Wallet size={16} /> },
    ],
  },
]

const HR_NAV: NavItem[] = [
  { path: '/rh/vue-ensemble', label: "Vue d'ensemble", permission: 'rh.dashboard.view', icon: <LayoutDashboard size={18} /> },
  { path: '/rh/employes', label: 'Employés', permission: 'rh.employees.view', icon: <Users size={18} /> },
  {
    label: 'Temps & présences',
    permission: 'rh.attendance.view',
    icon: <Calendar size={18} />,
    subItems: [
      { path: '/rh/presences', label: 'Présences', permission: 'rh.attendance.view', icon: <Clock size={16} /> },
      { path: '/rh/conges', label: 'Congés', permission: 'rh.leave.view', icon: <CalendarDays size={16} /> },
    ],
  },
  { path: '/rh/contrats', label: 'Contrats', permission: 'rh.contracts.view', icon: <Briefcase size={18} /> },
  {
    label: 'Paie',
    permission: 'rh.payroll.view',
    icon: <Wallet size={18} />,
    subItems: [
      { path: '/rh/paie', label: 'Préparation de paie', permission: 'rh.payroll.view', icon: <Wallet size={16} /> },
      { path: '/rh/bulletins', label: 'Bulletins de paie', permission: 'rh.payslips.view', icon: <Receipt size={16} /> },
    ],
  },
  { path: '/rh/documents', label: 'Documents', permission: 'rh.documents.view', icon: <FolderOpen size={18} /> },
  {
    label: 'Évaluations & sanctions',
    permission: 'rh.evaluations.view',
    icon: <ShieldCheck size={18} />,
    subItems: [
      { path: '/rh/evaluations', label: 'Évaluations', permission: 'rh.evaluations.view', icon: <ShieldCheck size={16} /> },
      { path: '/rh/sanctions', label: 'Sanctions', permission: 'rh.sanctions.view', icon: <ShieldCheck size={16} /> },
    ],
  },
  { path: '/rh/rapports', label: 'Rapports', permission: 'rh.reports.view', icon: <FileBarChart2 size={18} /> },
  {
    label: 'Configuration',
    permission: 'rh.settings.manage',
    icon: <Settings2 size={18} />,
    subItems: [
      { path: '/rh/parametres/services', label: 'Services', permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
      { path: '/rh/parametres/fonctions', label: 'Fonctions', permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
      { path: '/rh/parametres/types-contrats', label: 'Types de contrats', permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
      { path: '/rh/parametres/types-absences', label: "Types d'absences", permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
      { path: '/rh/parametres/types-documents', label: 'Types de documents', permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
      { path: '/rh/parametres', label: 'Paramètres RH', permission: 'rh.settings.manage', icon: <Settings2 size={16} /> },
    ],
  },
]

const SECRETARIAT_NAV: NavItem[] = [
  { path: '/secretariat', label: 'Tableau de bord', permission: 'secretariat.view', icon: <LayoutDashboard size={18} /> },
  { path: '/secretariat/courrier', label: 'Agent Courrier', permission: 'secretariat.use_agent_courrier', icon: <Send size={18} /> },
  { path: '/secretariat/reunion', label: 'Agent Réunion', permission: 'secretariat.use_agent_reunion', icon: <Users size={18} /> },
  { path: '/secretariat/agenda', label: 'Agent Agenda', permission: 'secretariat.use_agent_agenda', icon: <CalendarDays size={18} /> },
  { path: '/secretariat/documents', label: 'Agent Documents', permission: 'secretariat.use_agent_documents', icon: <FolderOpen size={18} /> },
  { path: '/secretariat/tableau', label: 'Agent Tableau', permission: 'secretariat.view', icon: <Table2 size={18} /> },
  { path: '/secretariat/manager', label: 'Agent Manager', permission: 'secretariat.use_agent_manager', icon: <Bot size={18} /> },
  { path: '/secretariat/validations', label: 'Validations', permission: 'secretariat.view_approvals', icon: <ShieldCheck size={18} /> },
  { path: '/secretariat/parametres-ia', label: 'Paramètres IA', permission: 'secretariat.manage_ai_settings', icon: <SlidersHorizontal size={18} /> },
]

const COMPTA_ANY_PERMISSION = [
  'compta.lecture',
  'compta.saisie',
  'compta.validation',
  'compta.cloture',
  'compta.parametrage',
  'compta.export',
]

const COMPTABILITE_NAV: NavItem[] = [
  { path: '/comptabilite', label: 'Écritures', permission: COMPTA_ANY_PERMISSION, icon: <BookOpenCheck size={18} /> },
]

const NAV_BY_APP = {
  TREASURY: TREASURY_NAV,
  HR: HR_NAV,
  SECRETARIAT: SECRETARIAT_NAV,
  COMPTABILITE: COMPTABILITE_NAV,
}

export default function Layout() {
  const { user, signOut } = useAuth()
  const { settings: orgSettings } = useOrganisationSettings()
  const location = useLocation()
  const navigate = useNavigate()
  const { hasPermission, loading } = usePermissions()
  const { activeApp, setActiveApp, activeAppDef } = useApp()

  const serviceIds =
    user?.service_ids && user.service_ids.length > 0
      ? user.service_ids
      : user?.service_id
        ? [user.service_id]
        : []
  const isServiceUser = serviceIds.length > 0
  const isAdminUser = user?.role === 'admin' || user?.role === 'super_admin'
  const isSuperAdmin = user?.role === 'super_admin'

  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  // Repli du menu sur desktop (mémorisé). Sur mobile, c'est le hamburger qui gère.
  const [desktopCollapsed, setDesktopCollapsed] = useState<boolean>(
    () => typeof window !== 'undefined' && window.localStorage.getItem('sidebarCollapsed') === '1'
  )
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [cashAlert, setCashAlert] = useState<any | null>(null)
  const [paymentAlert, setPaymentAlert] = useState<string | null>(null)
  const [impersonationToken, setImpersonationToken] = useState<string | null>(null)
  const isMobile = useMobile()

  const navRef = useRef<HTMLElement>(null)
  const [navIndicator, setNavIndicator] = useState({ top: 0, height: 0, opacity: 0 })

  const userMenuRef = useRef<HTMLDivElement>(null)
  const [showUserMenu, setShowUserMenu] = useState(false)

  useEffect(() => {
    if (!showUserMenu) return
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setShowUserMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showUserMenu])

  // Services nav path (only relevant in TREASURY)
  const serviceNavPath = serviceIds.length === 1 ? `/services/mon-espace/${serviceIds[0]}` : '/services'
  const serviceNavItems: NavItem[] = isServiceUser
    ? [{ path: serviceNavPath, label: 'Services', permission: 'services', icon: <Building2 size={18} />, matchPathPrefixes: ['/services', '/services/mon-espace'] }]
    : []

  const _modulesConfig = orgSettings?.modules_config as Record<string, { enabled?: boolean }> | null | undefined
  const isModuleEnabled = (key: string) => {
    if (isSuperAdmin) return true
    // Si modules_config n'est pas configuré → rétrocompatibilité, tout visible
    if (!_modulesConfig) return true
    const modCfg = _modulesConfig[key]
    // Si modules_config existe : le module doit être présent ET activé
    return !!modCfg && modCfg.enabled !== false
  }

  const MODULE_KEY: Record<string, string> = { TREASURY: 'tresorerie', HR: 'rh', SECRETARIAT: 'secretariat', COMPTABILITE: 'comptabilite' }
  const navItems: NavItem[] = isModuleEnabled(MODULE_KEY[activeApp] ?? '')
    ? activeApp === 'TREASURY'
      ? [...NAV_BY_APP.TREASURY, ...serviceNavItems]
      : NAV_BY_APP[activeApp] ?? []
    : []

  const mobileNavItems = [
    { path: '/', label: 'Tableau de bord', icon: <LayoutDashboard size={22} />, permission: 'dashboard' },
    { path: '/encaissements', label: 'Encaissements', icon: <ArrowDownCircle size={22} />, permission: 'encaissements' },
    { path: '/requisitions', label: 'Réquisitions', icon: <FileText size={22} />, permission: 'requisitions' },
    { path: '/validation', label: 'Validation', icon: <Send size={22} />, permission: 'validation' },
    { path: '/sorties-fonds', label: 'Sorties', icon: <Wallet size={22} />, permission: 'sorties_fonds' },
  ]

  // Sync activeApp with current URL
  useEffect(() => {
    const detectedApp = detectAppFromPath(location.pathname)
    if (detectedApp && detectedApp !== activeApp) {
      setActiveApp(detectedApp)
    }
  }, [location.pathname])

  useEffect(() => {
    if (!orgSettings) return
    const root = document.documentElement
    if (orgSettings.theme_primary_color) root.style.setProperty('--tenant-primary', orgSettings.theme_primary_color)
    if (orgSettings.theme_sidebar_color) root.style.setProperty('--tenant-sidebar', orgSettings.theme_sidebar_color)
    if (orgSettings.theme_sidebar_text_color) root.style.setProperty('--tenant-sidebar-text', orgSettings.theme_sidebar_text_color)
    if (orgSettings.theme_sidebar_active_color) root.style.setProperty('--tenant-sidebar-active', orgSettings.theme_sidebar_active_color)
    if (orgSettings.theme_accent_color) root.style.setProperty('--tenant-accent', orgSettings.theme_accent_color)
    if (orgSettings.theme_text_color) root.style.setProperty('--tenant-text', orgSettings.theme_text_color)
    if (orgSettings.theme_button_text_color) root.style.setProperty('--tenant-button-text', orgSettings.theme_button_text_color)
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

  const canAccessRoute = (permission: string) => hasPermission(permission)
  const canUseFinancialAi =
    hasPermission('dashboard') ||
    hasPermission('rapports') ||
    hasPermission('sorties_fonds') ||
    hasPermission('encaissements')

  const canAccessNavItem = (item: NavItem): boolean => {
    if (item.subItems) return item.subItems.some(sub => canAccessNavItem(sub))
    const permissions = Array.isArray(item.permission) ? item.permission : [item.permission]
    return permissions.some(p => canAccessRoute(p))
  }

  const toggleExpanded = (label: string) => {
    setExpandedItems(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const isPathActive = (path?: string, subItems?: NavItem[], matchPathPrefixes?: string[]): boolean => {
    if (matchPathPrefixes?.length) return matchPathPrefixes.some(p => location.pathname.startsWith(p))
    if (path) return location.pathname === path
    if (subItems) return subItems.some(item => isPathActive(item.path, item.subItems, item.matchPathPrefixes))
    return false
  }

  const handleLinkClick = () => setMobileMenuOpen(false)

  const toggleDesktopCollapsed = () => {
    setDesktopCollapsed(prev => {
      const next = !prev
      try {
        window.localStorage.setItem('sidebarCollapsed', next ? '1' : '0')
      } catch {
        /* stockage indisponible : on garde juste l'état en mémoire */
      }
      return next
    })
  }

  const renderSubNavItem = (subItem: NavItem, depth = 0): React.ReactNode => {
    if (!canAccessNavItem(subItem)) return null

    const hasNestedItems = subItem.subItems?.some(n => canAccessNavItem(n))
    const isExpanded = expandedItems.has(subItem.label)
    const isActive = isPathActive(subItem.path, subItem.subItems, subItem.matchPathPrefixes)

    if (hasNestedItems) {
      return (
        <div key={subItem.label} className={styles.subNavGroup}>
          <button
            type="button"
            className={`${styles.subNavItem} ${styles.subNavGroupButton} ${isActive ? styles.active : ''}`}
            data-depth={depth}
            onClick={() => toggleExpanded(subItem.label)}
          >
            <span className={styles.subNavLabel}>
              <span className={styles.subNavIcon}>{subItem.icon}</span>
              {subItem.label}
            </span>
            <span className={`${styles.arrow} ${isExpanded ? styles.arrowExpanded : ''}`}>
              <ChevronDown size={14} />
            </span>
          </button>
          {isExpanded && (
            <div className={styles.nestedSubMenu}>
              {subItem.subItems!.map(nested => renderSubNavItem(nested, depth + 1))}
            </div>
          )}
        </div>
      )
    }

    return (
      <Link
        key={subItem.path}
        to={subItem.path!}
        className={`${styles.subNavItem} ${location.pathname === subItem.path ? styles.active : ''}`}
        data-depth={depth}
        onClick={handleLinkClick}
      >
        <span className={styles.subNavIcon}>{subItem.icon}</span>
        {subItem.label}
      </Link>
    )
  }

  useEffect(() => {
    if (loading) return
    if (!orgSettings?.is_ai_enabled || !canUseFinancialAi) { setCashAlert(null); return }
    let cancelled = false
    const loadAlert = async () => {
      try {
        const res = await getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 })
        if (!cancelled) setCashAlert(res)
      } catch {
        if (!cancelled) setCashAlert(null)
      }
    }
    loadAlert()
    const id = window.setInterval(loadAlert, 300000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [loading, orgSettings?.is_ai_enabled, canUseFinancialAi])

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail
      setPaymentAlert(detail?.message || 'Votre abonnement a expiré. Passage en lecture seule.')
    }
    window.addEventListener('payment-required', handler as EventListener)
    return () => window.removeEventListener('payment-required', handler as EventListener)
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
    setExpandedItems(prev => {
      const next = new Set(prev)
      const expandActive = (items: NavItem[]) => {
        items.forEach(item => {
          if (item.subItems && isPathActive(item.path, item.subItems, item.matchPathPrefixes)) {
            next.add(item.label)
            expandActive(item.subItems)
          }
        })
      }
      expandActive(navItems)
      return next
    })
  }, [location.pathname, activeApp])

  useLayoutEffect(() => {
    const navEl = navRef.current
    if (!navEl) return
    const target = navEl.querySelector<HTMLElement>('[data-nav-active="true"]')
    if (!target) {
      setNavIndicator(prev => ({ ...prev, opacity: 0 }))
      return
    }
    const navRect = navEl.getBoundingClientRect()
    const targetRect = target.getBoundingClientRect()
    setNavIndicator({
      top: targetRect.top - navRect.top + navEl.scrollTop,
      height: targetRect.height,
      opacity: 1,
    })
  }, [location.pathname, expandedItems, activeApp, desktopCollapsed])

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
            data-nav-active={isActive || undefined}
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
              {item.subItems!.map(subItem => renderSubNavItem(subItem))}
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
        data-nav-active={isActive || undefined}
      >
        <span className={styles.navItemContent}>
          <span className={styles.navIcon}>{item.icon}</span>
          <span>{item.label}</span>
        </span>
      </Link>
    )
  }

  if (loading) return <div>Chargement...</div>

  return (
    <div className={`${styles.layout} ${desktopCollapsed ? styles.collapsed : ''}`}>
      <button
        className={styles.mobileMenuToggle}
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        aria-label="Toggle menu"
      >
        <span className={styles.hamburger}></span>
        <span className={styles.hamburger}></span>
        <span className={styles.hamburger}></span>
      </button>

      <button
        type="button"
        className={styles.desktopReopen}
        onClick={toggleDesktopCollapsed}
        aria-label="Afficher le menu"
        title="Afficher le menu"
      >
        <PanelLeft size={20} />
      </button>

      {mobileMenuOpen && (
        <div className={styles.overlay} onClick={() => setMobileMenuOpen(false)} />
      )}

      <aside className={`${styles.sidebar} ${mobileMenuOpen ? styles.sidebarOpen : ''}`}>
        <div className={styles.logo}>
          <div className={styles.logoHeader}>
            <img src="/imge_onec.png" alt="ONEC Logo" className={styles.logoImage} />
            <button
              type="button"
              className={styles.collapseBtn}
              onClick={toggleDesktopCollapsed}
              aria-label="Replier le menu"
              title="Replier le menu"
            >
              <PanelLeftClose size={18} />
            </button>
          </div>
          <AppSwitcher />
          <p>{activeAppDef.subtitle}</p>
          {isServiceUser && !isAdminUser && activeApp === 'TREASURY' && (
            <span className={styles.serviceBadge}>Espace Commission</span>
          )}
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

        <nav className={styles.nav} ref={navRef}>
          <div
            className={styles.activeIndicator}
            style={{
              transform: `translateY(${navIndicator.top}px)`,
              height: `${navIndicator.height}px`,
              opacity: navIndicator.opacity,
            }}
          />
          {navItems.map(item => renderNavItem(item))}
          {isSuperAdmin && (
            <Link
              to="/super-admin"
              className={`${styles.navItem} ${location.pathname === '/super-admin' ? styles.active : ''}`}
              onClick={handleLinkClick}
              data-nav-active={location.pathname === '/super-admin' || undefined}
            >
              <span className={styles.navItemContent}>
                <span className={styles.navIcon}><Cog size={18} /></span>
                <span>Console SaaS</span>
              </span>
            </Link>
          )}
          {isSuperAdmin && (
            <Link
              to="/ai-providers"
              className={`${styles.navItem} ${location.pathname.startsWith('/ai-providers') ? styles.active : ''}`}
              onClick={handleLinkClick}
              data-nav-active={location.pathname.startsWith('/ai-providers') || undefined}
            >
              <span className={styles.navItemContent}>
                <span className={styles.navIcon}><Bot size={18} /></span>
                <span>Fournisseurs IA</span>
              </span>
            </Link>
          )}
        </nav>

        <div className={styles.userInfo} ref={userMenuRef}>
          {showUserMenu && (
            <div className={styles.userMenu} role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => { setShowChangePassword(true); setMobileMenuOpen(false); setShowUserMenu(false) }}
                className={styles.userMenuItem}
              >
                <UserCog size={16} />
                <span>Mot de passe</span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => { setShowUserMenu(false); handleChangeTenant() }}
                className={styles.userMenuItem}
              >
                <Building2 size={16} />
                <span>Changer d'antenne</span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => { setShowUserMenu(false); handleSignOut() }}
                className={`${styles.userMenuItem} ${styles.userMenuItemDanger}`}
              >
                <LogOut size={16} />
                <span>Déconnexion</span>
              </button>
            </div>
          )}
          <button
            type="button"
            className={styles.userTrigger}
            onClick={() => setShowUserMenu(prev => !prev)}
            aria-expanded={showUserMenu}
          >
            <div className={styles.userAvatar}>
              {(user?.prenom?.[0] || '').toUpperCase()}
              {(user?.nom?.[0] || '').toUpperCase()}
            </div>
            <div className={styles.userTriggerText}>
              <div className={styles.userName}>{user?.prenom} {user?.nom}</div>
              <div className={styles.userRole}>{user?.role}</div>
            </div>
            <ChevronDown size={15} className={`${styles.userChevron} ${showUserMenu ? styles.userChevronOpen : ''}`} />
          </button>
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
              Voir l'analyse
            </button>
          </div>
        )}
        <div key={location.pathname} className={styles.pageTransition}>
          <Outlet />
        </div>
      </main>

      {isMobile && (
        <MobileBottomNav items={mobileNavItems} hasPermission={canAccessRoute} />
      )}

      <WaterFlow />

      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}

      {orgSettings?.is_ai_enabled && canUseFinancialAi && <OnecMind />}
    </div>
  )
}
