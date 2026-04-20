import { ReactNode, useState, useCallback, useRef, useEffect } from 'react'
import styles from './PullToRefresh.module.css'

interface PullToRefreshProps {
  children: ReactNode
  onRefresh: () => Promise<void>
  disabled?: boolean
}

export function PullToRefresh({ children, onRefresh, disabled = false }: PullToRefreshProps) {
  const [_isPulling, setIsPulling] = useState(false)
  const [pullDistance, setPullDistance] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const startY = useRef(0)
  const isPullable = useRef(false)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (disabled || isRefreshing) return
    if (window.scrollY <= 0) {
      isPullable.current = true
      startY.current = e.touches[0].clientY
      setIsPulling(true)
    }
  }, [disabled, isRefreshing])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (!isPullable.current || disabled || isRefreshing) return
    
    const currentY = e.touches[0].clientY
    const distance = Math.max(0, currentY - startY.current)
    
    if (distance > 0 && window.scrollY <= 0) {
      e.preventDefault()
      const pullRatio = Math.min(distance / 120, 1)
      setPullDistance(distance * pullRatio)
    }
  }, [disabled, isRefreshing])

  const handleTouchEnd = useCallback(async () => {
    if (!isPullable.current) return
    
    isPullable.current = false
    setIsPulling(false)
    
    if (pullDistance > 80 && !isRefreshing) {
      setIsRefreshing(true)
      try {
        await onRefresh()
      } finally {
        setIsRefreshing(false)
        setPullDistance(0)
      }
    } else {
      setPullDistance(0)
    }
  }, [pullDistance, isRefreshing, onRefresh])

  useEffect(() => {
    const preventDefaultScroll = (e: Event) => {
      if (pullDistance > 0) {
        e.preventDefault()
      }
    }
    
    document.addEventListener('touchmove', preventDefaultScroll, { passive: false })
    return () => document.removeEventListener('touchmove', preventDefaultScroll)
  }, [pullDistance])

  return (
    <div 
      className={styles.container}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      <div 
        className={styles.indicator}
        style={{ height: pullDistance }}
      >
        <div className={`${styles.spinner} ${isRefreshing ? styles.refreshing : ''}`}>
          {pullDistance > 80 ? (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          ) : (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          )}
        </div>
      </div>
      <div className={styles.content} style={{ marginTop: pullDistance }}>
        {children}
      </div>
    </div>
  )
}

export default PullToRefresh
