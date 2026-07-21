import { useEffect, useState } from 'react'

interface AnimatedNumberProps {
  value: number
  format: (value: number) => string
  durationMs?: number
  className?: string
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function AnimatedNumber({ value, format, durationMs = 700, className }: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value)

  useEffect(() => {
    if (prefersReducedMotion()) {
      setDisplay(value)
      return
    }

    let from = value
    setDisplay((current) => {
      from = current
      return current
    })
    if (from === value) return

    const to = value
    const start = performance.now()
    let frame: number

    const step = (now: number) => {
      const progress = Math.min((now - start) / durationMs, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(from + (to - from) * eased)
      if (progress < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value, durationMs])

  return <span className={className}>{format(display)}</span>
}
