import type { Denomination } from '../../api/denominations'
import styles from './ClotureFields.module.css'

export type BilletageSaisie = Record<string, string>

interface ClotureFieldsProps {
  soldeTheoriqueUsd: number
  soldeTheoriqueCdf: number
  denominations: Denomination[]
  billetageUsd: BilletageSaisie
  billetageCdf: BilletageSaisie
  physiqueManuelUsd: number
  physiqueManuelCdf: number
  autresUsd: string
  autresCdf: string
  onBilletageChange: (devise: 'USD' | 'CDF', key: string, value: string) => void
  onPhysiqueManuelChange: (devise: 'USD' | 'CDF', value: number) => void
  onAutresChange: (devise: 'USD' | 'CDF', value: string) => void
}

/** Montant « Autres » saisi (pièces, coupures non listées), 0 s'il est vide ou invalide. */
export const montantAutres = (saisie: string) => {
  const valeur = Number(saisie.replace(',', '.'))
  return Number.isFinite(valeur) && valeur > 0 ? Math.round(valeur * 100) / 100 : 0
}

export const denominationKey = (value: number) => String(Number(value))

export const totalBilletage = (
  denominations: Denomination[],
  saisie: BilletageSaisie,
) => {
  const total = denominations.reduce((sum, denomination) => {
    const quantite = Number(saisie[denominationKey(denomination.valeur)] || 0)
    return sum + denomination.valeur * (Number.isFinite(quantite) ? quantite : 0)
  }, 0)
  return Math.round((total + Number.EPSILON) * 100) / 100
}

export const serialiserBilletage = (
  denominations: Denomination[],
  saisie: BilletageSaisie,
): Record<string, number> => Object.fromEntries(
  denominations
    .map((denomination) => {
      const key = denominationKey(denomination.valeur)
      return [key, Number(saisie[key] || 0)] as const
    })
    .filter(([, quantite]) => Number.isInteger(quantite) && quantite > 0),
)

const formatUsd = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

const formatCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

function BilletageColonne({
  devise,
  soldeTheorique,
  denominations,
  saisie,
  physiqueManuel,
  autres,
  onBilletageChange,
  onPhysiqueManuelChange,
  onAutresChange,
}: {
  devise: 'USD' | 'CDF'
  soldeTheorique: number
  denominations: Denomination[]
  saisie: BilletageSaisie
  physiqueManuel: number
  autres: string
  onBilletageChange: (devise: 'USD' | 'CDF', key: string, value: string) => void
  onPhysiqueManuelChange: (devise: 'USD' | 'CDF', value: number) => void
  onAutresChange: (devise: 'USD' | 'CDF', value: string) => void
}) {
  const format = devise === 'USD' ? formatUsd : formatCdf
  const montantAutresSaisi = montantAutres(autres)
  const total = Math.round((totalBilletage(denominations, saisie) + montantAutresSaisi) * 100) / 100

  return (
    <div className={styles.column}>
      <div className={styles.currencyTitle}>
        <span className={devise === 'USD' ? styles.dotUsd : styles.dotCdf} />
        DEVISE {devise}
      </div>
      <div className={styles.summaryCard}>
        <p>Solde logiciel</p>
        <strong>{format(soldeTheorique)}</strong>
      </div>

      {denominations.length > 0 ? (
        <div className={styles.billetageBlock}>
          <div className={styles.billetageHeading}>
            <div>
              <strong>Billetage physique</strong>
              <span>Saisissez le nombre de billets pour chaque coupure.</span>
            </div>
            <span className={styles.autoBadge}>Total automatique</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.billetageTable}>
              <thead>
                <tr>
                  <th>Coupure</th>
                  <th>Quantité</th>
                  <th>Sous-total</th>
                </tr>
              </thead>
              <tbody>
                {denominations.map((denomination) => {
                  const key = denominationKey(denomination.valeur)
                  const quantite = Number(saisie[key] || 0)
                  const sousTotal = denomination.valeur * (Number.isFinite(quantite) ? quantite : 0)
                  return (
                    <tr key={denomination.id}>
                      <td className={styles.denominationLabel}>{denomination.label}</td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          inputMode="numeric"
                          value={saisie[key] ?? ''}
                          onChange={(event) => {
                            const value = event.target.value
                            if (value === '' || /^\d+$/.test(value)) {
                              onBilletageChange(devise, key, value)
                            }
                          }}
                          aria-label={`Quantité de ${denomination.label}`}
                          placeholder="0"
                        />
                      </td>
                      <td className={styles.subtotal}>{format(sousTotal)}</td>
                    </tr>
                  )
                })}
                <tr>
                  <td className={styles.denominationLabel}>
                    Autres
                    <small className={styles.autresAide}>pièces, coupures non listées — à préciser en observation</small>
                  </td>
                  <td>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={autres}
                      onChange={(event) => {
                        const value = event.target.value
                        if (value === '' || /^\d+([.,]\d{0,2})?$/.test(value)) onAutresChange(devise, value)
                      }}
                      aria-label={`Montant ${devise} compté hors des coupures listées`}
                      placeholder="0"
                    />
                  </td>
                  <td className={styles.subtotal}>{format(montantAutresSaisi)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className={styles.countedTotal}>
            <span>Solde physique compté</span>
            <strong>{format(total)}</strong>
          </div>
        </div>
      ) : (
        <div className={styles.inputBlock}>
          <div className={styles.missingDenominations}>
            Aucune coupure active n'est configurée en {devise}. Le total reste
            exceptionnellement saisissable manuellement.
          </div>
          <label htmlFor={`physique-${devise}`}>Comptage physique ({devise})</label>
          <input
            id={`physique-${devise}`}
            type="number"
            min="0"
            step="0.01"
            value={Number.isFinite(physiqueManuel) ? physiqueManuel : 0}
            onChange={(event) => onPhysiqueManuelChange(devise, Number(event.target.value || 0))}
            placeholder="0"
          />
        </div>
      )}
    </div>
  )
}

export default function ClotureFields({
  soldeTheoriqueUsd,
  soldeTheoriqueCdf,
  denominations,
  billetageUsd,
  billetageCdf,
  physiqueManuelUsd,
  physiqueManuelCdf,
  autresUsd,
  autresCdf,
  onBilletageChange,
  onPhysiqueManuelChange,
  onAutresChange,
}: ClotureFieldsProps) {
  const denominationsUsd = denominations.filter((denomination) => denomination.devise === 'USD')
  const denominationsCdf = denominations.filter((denomination) => denomination.devise === 'CDF')

  return (
    <div className={styles.grid}>
      <BilletageColonne
        devise="USD"
        soldeTheorique={soldeTheoriqueUsd}
        denominations={denominationsUsd}
        saisie={billetageUsd}
        physiqueManuel={physiqueManuelUsd}
        autres={autresUsd}
        onBilletageChange={onBilletageChange}
        onPhysiqueManuelChange={onPhysiqueManuelChange}
        onAutresChange={onAutresChange}
      />
      <BilletageColonne
        devise="CDF"
        soldeTheorique={soldeTheoriqueCdf}
        denominations={denominationsCdf}
        saisie={billetageCdf}
        physiqueManuel={physiqueManuelCdf}
        autres={autresCdf}
        onBilletageChange={onBilletageChange}
        onPhysiqueManuelChange={onPhysiqueManuelChange}
        onAutresChange={onAutresChange}
      />
    </div>
  )
}
