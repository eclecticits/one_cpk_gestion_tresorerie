import styles from './PageHeader.module.css'

export default function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: React.ReactNode
}) {
  return (
    <header className={`${styles.header} pageHeader`}>
      <div>
        <h1 className={`${styles.title} pageTitle`}>{title}</h1>
        {subtitle && <p className={`${styles.subtitle} pageSubtitle`}>{subtitle}</p>}
      </div>
      {actions && <div className={`${styles.actions} toolbar`}>{actions}</div>}
    </header>
  )
}
