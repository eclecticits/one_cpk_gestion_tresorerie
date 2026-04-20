import { useLocation, Link } from 'react-router-dom'
import { useMobile } from '../hooks/useMobile'
import styles from './MobileBottomNav.module.css'

interface NavItem {
  path: string
  label: string
  icon: React.ReactNode
  permission: string
}

interface MobileBottomNavProps {
  items: NavItem[]
  hasPermission: (permission: string) => boolean
}

export function MobileBottomNav({ items, hasPermission }: MobileBottomNavProps) {
  const location = useLocation()
  const isMobile = useMobile()

  if (!isMobile) return null

  const visibleItems = items.filter(item => hasPermission(item.permission))

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/' || location.pathname === '/dashboard'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <nav className={styles.nav} role="navigation" aria-label="Navigation principale">
      {visibleItems.map(item => (
        <Link
          key={item.path}
          to={item.path}
          className={`${styles.navItem} ${isActive(item.path) ? styles.active : ''}`}
          aria-current={isActive(item.path) ? 'page' : undefined}
        >
          <span className={styles.icon}>{item.icon}</span>
          <span className={styles.label}>{item.label}</span>
        </Link>
      ))}
    </nav>
  )
}

export default MobileBottomNav
