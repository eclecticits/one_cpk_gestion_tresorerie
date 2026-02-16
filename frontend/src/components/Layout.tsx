import { useEffect, useState } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { getCashForecast } from '../api/ai'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import ChangePasswordModal from './ChangePasswordModal'
import OnecMind from './OnecMind'
import styles from './Layout.module.css'

interface NavItem {
  path?: string
  label: string
  permission: string
  subItems?: NavItem[]
}

export default function Layout() {
  const { user, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const { hasPermission, loading } = usePermissions()
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [cashAlert, setCashAlert] = useState<any | null>(null)

  const handleSignOut = async () => {
    try {
      await signOut()
      navigate('/login')
    } catch (error) {
      console.error('Error signing out:', error)
    }
  }

  const navItems: NavItem[] = [
    { path: '/', label: 'Tableau de bord', permission: 'dashboard' },
    { path: '/encaissements', label: 'Encaissements', permission: 'encaissements' },
    {
      label: 'Réquisitions',
      permission: 'requisitions',
      subItems: [
        { path: '/requisitions', label: 'Réquisitions classiques', permission: 'requisitions' },
        { path: '/remboursement-transport', label: 'Remboursement frais transport', permission: 'requisitions' },
      ]
    },
    { path: '/validation', label: 'Validation', permission: 'validation' },
    {
      label: 'Sorties de fonds',
      permission: 'sorties_fonds',
      subItems: [
        { path: '/sorties-fonds', label: 'Sorties de fonds', permission: 'sorties_fonds' },
        { path: '/cloture-caisse', label: 'Clôture de caisse', permission: 'sorties_fonds' },
      ]
    },
    { path: '/budget', label: 'Budget', permission: 'budget' },
    {
      label: 'Rapports',
      permission: 'rapports',
      subItems: [
        { path: '/rapports', label: 'Tableaux & exports', permission: 'rapports' },
        { path: '/audit-logs', label: 'Audit système', permission: 'rapports' },
      ]
    },
    {
      label: 'Experts-Comptables',
      permission: 'experts_comptables',
      subItems: [
        { path: '/experts-comptables', label: 'Liste des experts', permission: 'experts_comptables' },
        { path: '/historique-imports', label: 'Historique des imports', permission: 'settings' },
      ]
    },
    {
      label: 'Paramètres',
      permission: 'settings',
      subItems: [
        { path: '/settings', label: 'Généraux', permission: 'settings' },
        { path: '/denominations', label: 'Configuration billets', permission: 'settings' },
      ]
    },
  ]

  const canAccessRoute = (permission: string) => hasPermission(permission)

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

  const isPathActive = (path?: string, subItems?: NavItem[]) => {
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
  }, [loading])

  const renderNavItem = (item: NavItem) => {
    if (!canAccessRoute(item.permission)) return null

    const hasSubItems = item.subItems && item.subItems.length > 0
    const isExpanded = expandedItems.has(item.label)
    const isActive = isPathActive(item.path, item.subItems)

    if (hasSubItems) {
      return (
        <div key={item.label} className={styles.navItemWithSub}>
          <div
            className={`${styles.navItem} ${isActive ? styles.active : ''} ${styles.hasSubmenu}`}
            onClick={() => toggleExpanded(item.label)}
          >
            <span>{item.label}</span>
            <span className={`${styles.arrow} ${isExpanded ? styles.arrowExpanded : ''}`}>▼</span>
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
        {item.label}
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
        </div>

        <nav className={styles.nav}>
          {navItems.map(item => renderNavItem(item))}
        </nav>

        <div className={styles.userInfo}>
          <div className={styles.userName}>
            {user?.prenom} {user?.nom}
          </div>
          <div className={styles.userRole}>{user?.role}</div>
          <button
            onClick={() => {
              setShowChangePassword(true)
              setMobileMenuOpen(false)
            }}
            className={styles.changePasswordBtn}
          >
            🔒 Changer mon mot de passe
          </button>
          <button onClick={handleSignOut} className={styles.signOutBtn}>
            Déconnexion
          </button>
        </div>
      </aside>

      <main className={styles.main}>
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

      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}

      <OnecMind />
    </div>
  )
}
