import { useState, useEffect, useCallback } from 'react'

const BREAKPOINTS = {
  xs: 360,
  sm: 480,
  md: 768,
  lg: 1024,
  xl: 1200,
  xxl: 1400,
} as const

type Breakpoint = keyof typeof BREAKPOINTS

export function useMobile(breakpoint: Breakpoint = 'md') {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < BREAKPOINTS[breakpoint]
  })

  useEffect(() => {
    const handler = () => {
      setIsMobile(window.innerWidth < BREAKPOINTS[breakpoint])
    }

    window.addEventListener('resize', handler, { passive: true })
    return () => window.removeEventListener('resize', handler)
  }, [breakpoint])

  return isMobile
}

export function useBreakpoint(breakpoint: Breakpoint) {
  const [isMatch, setIsMatch] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth >= BREAKPOINTS[breakpoint]
  })

  useEffect(() => {
    const handler = () => {
      setIsMatch(window.innerWidth >= BREAKPOINTS[breakpoint])
    }

    window.addEventListener('resize', handler, { passive: true })
    return () => window.removeEventListener('resize', handler)
  }, [breakpoint])

  return isMatch
}

export function useBreakpoints() {
  const [breakpoints, setBreakpoints] = useState({
    xs: false,
    sm: false,
    md: false,
    lg: false,
    xl: false,
    xxl: false,
  })

  useEffect(() => {
    const update = () => {
      const width = window.innerWidth
      setBreakpoints({
        xs: width >= BREAKPOINTS.xs,
        sm: width >= BREAKPOINTS.sm,
        md: width >= BREAKPOINTS.md,
        lg: width >= BREAKPOINTS.lg,
        xl: width >= BREAKPOINTS.xl,
        xxl: width >= BREAKPOINTS.xxl,
      })
    }

    update()
    window.addEventListener('resize', update, { passive: true })
    return () => window.removeEventListener('resize', update)
  }, [])

  return breakpoints
}

export function useSwipe(onSwipeLeft?: () => void, onSwipeRight?: () => void) {
  const [touchStart, setTouchStart] = useState<number | null>(null)
  const [touchEnd, setTouchEnd] = useState<number | null>(null)

  const minSwipeDistance = 50

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    setTouchEnd(null)
    setTouchStart(e.targetTouches[0].clientX)
  }, [])

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    setTouchEnd(e.targetTouches[0].clientX)
  }, [])

  const onTouchEnd = useCallback(() => {
    if (!touchStart || !touchEnd) return
    
    const distance = touchStart - touchEnd
    const isLeftSwipe = distance > minSwipeDistance
    const isRightSwipe = distance < -minSwipeDistance

    if (isLeftSwipe && onSwipeLeft) {
      onSwipeLeft()
    }
    if (isRightSwipe && onSwipeRight) {
      onSwipeRight()
    }
  }, [touchStart, touchEnd, onSwipeLeft, onSwipeRight])

  return { onTouchStart, onTouchMove, onTouchEnd }
}

export function usePullToRefresh(onRefresh: () => void) {
  const [isPulling, setIsPulling] = useState(false)
  const [pullDistance, setPullDistance] = useState(0)

  const onTouchStart = useCallback(() => {
    if (window.scrollY === 0) {
      setIsPulling(true)
    }
  }, [])

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!isPulling) return
    const distance = Math.max(0, e.targetTouches[0].clientY)
    setPullDistance(Math.min(distance, 100))
  }, [isPulling])

  const onTouchEnd = useCallback(() => {
    if (pullDistance > 80) {
      onRefresh()
    }
    setIsPulling(false)
    setPullDistance(0)
  }, [pullDistance, onRefresh])

  return { isPulling, pullDistance, onTouchStart, onTouchMove, onTouchEnd }
}

export default useMobile
