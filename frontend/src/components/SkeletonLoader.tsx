import styles from './SkeletonLoader.module.css'

interface SkeletonLoaderProps {
  type?: 'card' | 'text' | 'table' | 'chart' | 'form'
  count?: number
  className?: string
}

export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`${styles.card} ${className}`}>
      <div className={styles.cardHeader}>
        <div className={styles.skeletonLine} style={{ width: '60%', height: 16 }} />
        <div className={styles.skeletonLine} style={{ width: '40%', height: 12 }} />
      </div>
      <div className={styles.cardBody}>
        <div className={styles.skeletonLine} style={{ width: '100%' }} />
        <div className={styles.skeletonLine} style={{ width: '80%' }} />
      </div>
    </div>
  )
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className={styles.textBlock}>
      {Array.from({ length: lines }).map((_, i) => (
        <div 
          key={i} 
          className={styles.skeletonLine} 
          style={{ width: i === lines - 1 ? '70%' : '100%' }} 
        />
      ))}
    </div>
  )
}

export function SkeletonTable({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className={styles.table}>
      <div className={styles.tableHeader}>
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className={styles.skeletonLine} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className={styles.tableRow}>
          {Array.from({ length: cols }).map((_, colIndex) => (
            <div key={colIndex} className={styles.skeletonLine} style={{ width: colIndex === 0 ? '80%' : '60%' }} />
          ))}
        </div>
      ))}
    </div>
  )
}

export function SkeletonChart() {
  return (
    <div className={styles.chart}>
      <div className={styles.chartBars}>
        {Array.from({ length: 7 }).map((_, i) => (
          <div 
            key={i} 
            className={styles.chartBar}
            style={{ height: `${30 + Math.random() * 60}%` }}
          />
        ))}
      </div>
      <div className={styles.chartLegend}>
        <div className={styles.skeletonLine} style={{ width: 120 }} />
        <div className={styles.skeletonLine} style={{ width: 100 }} />
      </div>
    </div>
  )
}

export function SkeletonForm({ fields = 4 }: { fields?: number }) {
  return (
    <div className={styles.form}>
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className={styles.formField}>
          <div className={styles.skeletonLine} style={{ width: 100, height: 14 }} />
          <div className={styles.skeletonLine} style={{ height: 44 }} />
        </div>
      ))}
    </div>
  )
}

export function SkeletonLoader({ type = 'card', count = 3, className = '' }: SkeletonLoaderProps) {
  const items = Array.from({ length: count })

  switch (type) {
    case 'card':
      return (
        <div className={`${styles.cardGrid} ${className}`}>
          {items.map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )
    case 'text':
      return (
        <div className={`${styles.textContainer} ${className}`}>
          {items.map((_, i) => (
            <SkeletonText key={i} />
          ))}
        </div>
      )
    case 'table':
      return <SkeletonTable />
    case 'chart':
      return <SkeletonChart />
    case 'form':
      return <SkeletonForm />
    default:
      return null
  }
}

export default SkeletonLoader
