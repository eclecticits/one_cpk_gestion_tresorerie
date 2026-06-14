import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutGrid, Landmark, UsersRound, BookOpen } from 'lucide-react'
import { useApp, AppId, AppDefinition } from '../contexts/AppContext'
import styles from './AppSwitcher.module.css'

const APP_ICONS: Record<AppId, React.ReactNode> = {
  TREASURY: <Landmark size={28} />,
  HR: <UsersRound size={28} />,
  SECRETARIAT: <BookOpen size={28} />,
}

function AppTile({ app, isActive, onSelect }: { app: AppDefinition; isActive: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={`${styles.tile} ${isActive ? styles.tileActive : ''}`}
      onClick={onSelect}
      style={isActive ? { '--app-color': app.color, '--app-bg': app.bgColor } as React.CSSProperties : undefined}
    >
      <span className={styles.tileIcon} style={{ color: app.color }}>
        {APP_ICONS[app.id]}
      </span>
      <span className={styles.tileLabel}>{app.label}</span>
      {isActive && <span className={styles.tileCheck}>✓</span>}
    </button>
  )
}

export default function AppSwitcher() {
  const { activeApp, setActiveApp, availableApps, activeAppDef } = useApp()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (availableApps.length <= 1) return null

  const handleSelect = (app: AppDefinition) => {
    setActiveApp(app.id)
    setOpen(false)
    navigate(app.entryPath)
  }

  return (
    <div className={styles.wrapper}>
      <button
        ref={btnRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.triggerOpen : ''}`}
        onClick={() => setOpen(v => !v)}
        title="Changer d'application"
        aria-label="Sélecteur d'applications"
        aria-expanded={open}
      >
        <LayoutGrid size={16} />
        <span className={styles.triggerLabel}>{activeAppDef.label}</span>
      </button>

      {open && (
        <div ref={panelRef} className={styles.panel}>
          <p className={styles.panelTitle}>Applications</p>
          <div className={styles.tileGrid}>
            {availableApps.map(app => (
              <AppTile
                key={app.id}
                app={app}
                isActive={app.id === activeApp}
                onSelect={() => handleSelect(app)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
