import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutGrid, Landmark, UsersRound, BookOpen, Calculator, Table2 } from 'lucide-react'
import { useApp, AppId, AppDefinition } from '../contexts/AppContext'
import styles from './AppSwitcher.module.css'

const APP_ICONS: Record<AppId, React.ReactNode> = {
  TREASURY: <Landmark size={28} />,
  HR: <UsersRound size={28} />,
  SECRETARIAT: <BookOpen size={28} />,
  TABLEAU: <Table2 size={28} />,
  COMPTABILITE: <Calculator size={28} />,
}

function AppTile({ app, isActive, onSelect }: { app: AppDefinition; isActive: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={`${styles.tile} ${isActive ? styles.tileActive : ''}`}
      onClick={onSelect}
      role="menuitemradio"
      aria-checked={isActive}
      style={isActive ? { '--app-color': app.color, '--app-bg': app.bgColor } as React.CSSProperties : undefined}
    >
      <span className={styles.tileIcon} style={{ color: app.color }}>
        {APP_ICONS[app.id]}
      </span>
      <span className={styles.tileLabel}>{app.label}</span>
      {isActive && <span className={styles.tileCheck} aria-hidden="true">✓</span>}
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
    const handler = (e: PointerEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', handler)

    const focusId = window.requestAnimationFrame(() => {
      const selectedItem = panelRef.current?.querySelector<HTMLButtonElement>(
        '[role="menuitemradio"][aria-checked="true"]',
      )
      const firstItem = panelRef.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"]')
      ;(selectedItem || firstItem)?.focus()
    })

    return () => {
      document.removeEventListener('pointerdown', handler)
      window.cancelAnimationFrame(focusId)
    }
  }, [open])

  if (availableApps.length <= 1) return null

  const handleSelect = (app: AppDefinition) => {
    setActiveApp(app.id)
    setOpen(false)
    navigate(app.entryPath)
  }

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      btnRef.current?.focus()
      return
    }

    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return

    const items = Array.from(
      panelRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') || [],
    )
    if (items.length === 0) return

    event.preventDefault()
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? items.length - 1
        : event.key === 'ArrowUp'
          ? (currentIndex <= 0 ? items.length - 1 : currentIndex - 1)
          : (currentIndex + 1) % items.length
    items[nextIndex]?.focus()
  }

  return (
    <div
      className={styles.wrapper}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={btnRef}
        type="button"
        className={`${styles.trigger} ${open ? styles.triggerOpen : ''}`}
        onClick={() => setOpen(v => !v)}
        title="Changer d'application"
        aria-label="Changer d'application"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={open ? 'application-switcher-menu' : undefined}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
          event.preventDefault()
          setOpen(true)
        }}
      >
        <LayoutGrid size={16} />
        <span className={styles.triggerLabel}>{activeAppDef.label}</span>
      </button>

      {open && (
        <div
          ref={panelRef}
          className={styles.panel}
        >
          <p id="application-switcher-title" className={styles.panelTitle}>Applications</p>
          <div
            id="application-switcher-menu"
            className={styles.tileGrid}
            role="menu"
            aria-labelledby="application-switcher-title"
            onKeyDown={handleMenuKeyDown}
          >
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
