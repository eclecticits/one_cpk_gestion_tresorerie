import styles from './ClotureFields.module.css'

interface ClotureFieldsProps {
  soldeTheoriqueUsd: number
  soldeTheoriqueCdf: number
  physiqueUsd: number
  physiqueCdf: number
  onPhysiqueUsdChange: (value: number) => void
  onPhysiqueCdfChange: (value: number) => void
}

const formatUsd = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

const formatCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

export default function ClotureFields({
  soldeTheoriqueUsd,
  soldeTheoriqueCdf,
  physiqueUsd,
  physiqueCdf,
  onPhysiqueUsdChange,
  onPhysiqueCdfChange,
}: ClotureFieldsProps) {
  return (
    <div className={styles.grid}>
      <div className={styles.column}>
        <div className={styles.currencyTitle}>
          <span className={styles.dotUsd} />
          DEVISE USD
        </div>
        <div className={styles.summaryCard}>
          <p>Solde logiciel</p>
          <strong>{formatUsd(soldeTheoriqueUsd)}</strong>
        </div>
        <div className={styles.inputBlock}>
          <label>Comptage physique ($)</label>
          <input
            type="number"
            value={Number.isFinite(physiqueUsd) ? physiqueUsd : 0}
            onChange={(e) => onPhysiqueUsdChange(Number(e.target.value || 0))}
            placeholder="0.00"
          />
        </div>
      </div>

      <div className={styles.column}>
        <div className={styles.currencyTitle}>
          <span className={styles.dotCdf} />
          DEVISE CDF
        </div>
        <div className={styles.summaryCard}>
          <p>Solde logiciel</p>
          <strong>{formatCdf(soldeTheoriqueCdf)}</strong>
        </div>
        <div className={styles.inputBlock}>
          <label>Comptage physique (FC)</label>
          <input
            type="number"
            value={Number.isFinite(physiqueCdf) ? physiqueCdf : 0}
            onChange={(e) => onPhysiqueCdfChange(Number(e.target.value || 0))}
            placeholder="0"
          />
        </div>
      </div>
    </div>
  )
}
