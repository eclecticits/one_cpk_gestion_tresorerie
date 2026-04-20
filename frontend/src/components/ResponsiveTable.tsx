import { ReactNode } from 'react'
import { useMobile } from '../hooks/useMobile'
import styles from './ResponsiveTable.module.css'

interface Column<T> {
  key: string
  header: string
  render?: (item: T, index: number) => ReactNode
  className?: string
  width?: string | number
  hideOnMobile?: boolean
}

interface ResponsiveTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyExtractor: (item: T) => string
  emptyMessage?: string
  loading?: boolean
  onRowClick?: (item: T) => void
  className?: string
  stickyHeader?: boolean
}

export function ResponsiveTable<T extends Record<string, any>>({
  columns,
  data,
  keyExtractor,
  emptyMessage = 'Aucune donnée disponible',
  loading = false,
  onRowClick,
  className = '',
  stickyHeader = true,
}: ResponsiveTableProps<T>) {
  const isMobile = useMobile()

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.skeleton}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className={styles.skeletonRow}>
              {columns.slice(0, isMobile ? 3 : 5).map((_, j) => (
                <div key={j} className={styles.skeletonCell} />
              ))}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
            <polyline points="13 2 13 9 20 9" />
          </svg>
          <p>{emptyMessage}</p>
        </div>
      </div>
    )
  }

  const visibleColumns = isMobile 
    ? columns.filter(col => !col.hideOnMobile)
    : columns

  return (
    <div className={`${styles.container} ${className}`}>
      <div className={styles.tableWrapper}>
        <table className={`${styles.table} ${stickyHeader ? styles.stickyHeader : ''}`}>
          <thead className={styles.thead}>
            <tr>
              {visibleColumns.map(column => (
                <th 
                  key={column.key} 
                  className={`${styles.th} ${column.className || ''}`}
                  style={{ width: column.width }}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={styles.tbody}>
            {data.map((item, index) => (
              <tr 
                key={keyExtractor(item)} 
                className={`${styles.tr} ${onRowClick ? styles.clickable : ''}`}
                onClick={() => onRowClick?.(item)}
              >
                {visibleColumns.map(column => (
                  <td 
                    key={column.key} 
                    className={`${styles.td} ${column.className || ''}`}
                    data-label={isMobile ? column.header : undefined}
                  >
                    {column.render 
                      ? column.render(item, index)
                      : item[column.key]
                    }
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default ResponsiveTable
