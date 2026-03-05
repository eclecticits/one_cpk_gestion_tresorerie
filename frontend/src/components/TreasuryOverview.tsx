import { Wallet, Landmark, ArrowUpRight, ArrowDownLeft } from 'lucide-react'
import { toNumber } from '../utils/amount'
import type { Money } from '../types'
import type { TreasuryOverviewData } from '../types/treasury'
import styles from './TreasuryOverview.module.css'

interface TreasuryOverviewProps {
  data: TreasuryOverviewData
  fluxEntrees?: Money
  fluxSorties?: Money
  formatCurrency: (amount: Money) => string
  isLoading?: boolean
  errorMessage?: string | null
}

export default function TreasuryOverview({
  data,
  fluxEntrees = 0,
  fluxSorties = 0,
  formatCurrency,
  isLoading = false,
  errorMessage = null,
}: TreasuryOverviewProps) {
  const formatNumber = (value: Money) =>
    toNumber(value).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const totalBanqueUsd = data.comptes.reduce((acc, compte) => {
    if ((compte.devise || 'USD').toUpperCase() !== 'USD') return acc
    return acc + toNumber(compte.solde_actuel)
  }, 0)

  const totalBanqueCdf = data.comptes.reduce((acc, compte) => {
    if ((compte.devise || 'USD').toUpperCase() !== 'CDF') return acc
    return acc + toNumber(compte.solde_actuel)
  }, 0)

  return (
    <div className={styles.wrapper}>
      <div className={styles.grid}>
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div className={styles.cardTitle}>
              <span className={styles.iconWrap}>
                <Wallet size={18} />
              </span>
              <span>Caisse Centrale</span>
            </div>
            <span className={styles.liveBadge}>LIVE</span>
          </div>
          <div className={styles.cardBody}>
            <div className={styles.amountRow}>
              <span className={styles.amountLabel}>Solde USD</span>
              <span className={styles.amountValue}>{formatCurrency(data.caisse.solde_usd)}</span>
            </div>
            <div className={styles.amountRow}>
              <span className={styles.amountLabel}>Solde CDF</span>
              <span className={styles.amountValueSecondary}>
                {formatNumber(data.caisse.solde_cdf)} FC
              </span>
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div className={styles.cardTitle}>
              <span className={`${styles.iconWrap} ${styles.bankIcon}`}>
                <Landmark size={18} />
              </span>
              <span>Total Banques</span>
            </div>
          </div>
          <div className={styles.cardBody}>
            <div className={styles.amountInline}>
              <span className={styles.amountLabel}>Disponibilité USD</span>
              <span className={styles.amountValueBank}>{formatCurrency(totalBanqueUsd)}</span>
            </div>
            <div className={styles.pillRow}>
              <span className={styles.pill}>USD</span>
              <span className={styles.pillValue}>{formatCurrency(totalBanqueUsd)}</span>
            </div>
            <div className={styles.pillRow}>
              <span className={`${styles.pill} ${styles.pillCdf}`}>CDF</span>
              <span className={styles.pillValue}>{formatNumber(totalBanqueCdf)} FC</span>
            </div>
          </div>
        </div>

        <div className={styles.cardAccent}>
          <div className={styles.accentTitle}>Flux du mois</div>
          <div className={styles.accentRows}>
            <div className={styles.accentRow}>
              <span className={styles.accentIcon}>
                <ArrowUpRight size={14} />
              </span>
              <span>Entrées : +{formatCurrency(fluxEntrees)}</span>
            </div>
            <div className={styles.accentRow}>
              <span className={`${styles.accentIcon} ${styles.accentIconDown}`}>
                <ArrowDownLeft size={14} />
              </span>
              <span>Sorties : -{formatCurrency(fluxSorties)}</span>
            </div>
          </div>
        </div>
      </div>
      {(isLoading || errorMessage) && (
        <div className={styles.statusRow}>
          {isLoading && <span>Synchronisation des soldes…</span>}
          {!isLoading && errorMessage && <span>{errorMessage}</span>}
        </div>
      )}
    </div>
  )
}
