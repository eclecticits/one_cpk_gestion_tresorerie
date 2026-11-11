import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Download, RefreshCw, Search } from 'lucide-react'
import * as XLSX from 'xlsx'
import { getComptaBalanceAgee } from '../../api/comptabilite'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import type { ComptaBalanceAgee } from '../../types/comptabilite'
import { toNumber } from '../../utils/amount'
import styles from './ComptaBalanceAgeePanel.module.css'

const TRANCHES = [
  ['non_echu', 'Non échu', 'À venir', 'future'],
  ['j0_30', '0 à 30 j', 'Récent', 'fresh'],
  ['j31_60', '31 à 60 j', 'À suivre', 'watch'],
  ['j61_90', '61 à 90 j', 'En retard', 'late'],
  ['plus_90', 'Plus de 90 j', 'Critique', 'critical'],
] as const

function montant(value: string | number, zero = '—'): string {
  const nombre = toNumber(value)
  if (!nombre) return zero
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(nombre)
}

function jour(value: string | null): string {
  if (!value) return '—'
  const [annee, mois, j] = value.slice(0, 10).split('-')
  return annee && mois && j ? `${j}/${mois}/${annee}` : value
}

function aujourdhui(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function exporter(balance: ComptaBalanceAgee) {
  const entetes = ['Compte', 'Libellé', 'Lignes', 'Plus ancienne', ...TRANCHES.map(([, l]) => l), 'Reste dû']
  const lignes = balance.lignes.map(l => [
    l.compte_numero,
    l.compte_libelle,
    l.lignes,
    jour(l.plus_ancienne),
    ...TRANCHES.map(([cle]) => toNumber(l[cle])),
    toNumber(l.solde),
  ])
  const total = ['', 'Total', '', '', ...TRANCHES.map(([cle]) => toNumber(balance[cle])), toNumber(balance.total)]
  const feuille = XLSX.utils.aoa_to_sheet([entetes, ...lignes, total])
  feuille['!cols'] = [
    { wch: 16 },
    { wch: 44 },
    { wch: 8 },
    { wch: 14 },
    ...TRANCHES.map(() => ({ wch: 14 })),
    { wch: 14 },
  ]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, feuille, 'Balance âgée')
  XLSX.writeFile(wb, `balance_agee_${balance.sens.toLowerCase()}_${balance.date_arret}.xlsx`)
}

/** Balance âgée des tiers : ce qui reste dû, rangé par ancienneté. */
export default function ComptaBalanceAgeePanel() {
  const [dateArret, setDateArret] = useState(aujourdhui())
  const [sens, setSens] = useState<'CREANCES' | 'DETTES'>('CREANCES')
  const [prefixe, setPrefixe] = useState('')
  const prefixeDiffere = useDebouncedValue(prefixe.trim(), 300)

  const balanceQuery = useQuery({
    queryKey: ['compta-balance-agee', dateArret, sens, prefixeDiffere],
    queryFn: () => getComptaBalanceAgee({
      date_arret: dateArret,
      sens,
      prefixe: prefixeDiffere || undefined,
    }),
    enabled: Boolean(dateArret),
    placeholderData: previous => previous,
  })
  const balance = balanceQuery.data

  const repartition = useMemo(() => {
    const total = Math.abs(toNumber(balance?.total ?? 0))
    return TRANCHES.map(([cle, libelle, statut, ton]) => {
      const valeur = Math.max(0, toNumber(balance?.[cle] ?? 0))
      return { cle, libelle, statut, ton, valeur, part: total > 0 ? (valeur / total) * 100 : 0 }
    })
  }, [balance])

  return (
    <div className={styles.workspace}>
      <section className={styles.controlPanel} aria-label="Filtres de la balance âgée">
        <div className={styles.heading}>
          <div>
            <span className={styles.eyebrow}>Pilotage du recouvrement</span>
            <h2>{sens === 'CREANCES' ? 'Ce que les tiers doivent' : 'Ce qui est dû aux tiers'}</h2>
            <p>Situation au {jour(dateArret)}, calculée uniquement sur les mouvements non lettrés.</p>
          </div>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.iconButton}
              aria-label="Actualiser la balance"
              title="Actualiser"
              disabled={balanceQuery.isFetching}
              onClick={() => balanceQuery.refetch()}
            >
              <RefreshCw size={16} className={balanceQuery.isFetching ? styles.spin : undefined} />
            </button>
            <button
              type="button"
              className={styles.exportButton}
              disabled={!balance || balance.lignes.length === 0}
              onClick={() => balance && exporter(balance)}
            >
              <Download size={15} /> Exporter Excel
            </button>
          </div>
        </div>

        <div className={styles.toolbar}>
          <div className={styles.segmented} aria-label="Sens de la balance">
            <button
              type="button"
              className={sens === 'CREANCES' ? styles.segmentActive : undefined}
              aria-pressed={sens === 'CREANCES'}
              onClick={() => setSens('CREANCES')}
            >
              Créances clients
            </button>
            <button
              type="button"
              className={sens === 'DETTES' ? styles.segmentActive : undefined}
              aria-pressed={sens === 'DETTES'}
              onClick={() => setSens('DETTES')}
            >
              Dettes fournisseurs
            </button>
          </div>
          <label className={styles.field}>
            <span>Date d’arrêt</span>
            <input type="date" value={dateArret} onChange={e => setDateArret(e.target.value)} />
          </label>
          <label className={`${styles.field} ${styles.searchField}`}>
            <span>Filtrer par compte</span>
            <div>
              <Search size={15} aria-hidden="true" />
              <input
                type="text"
                inputMode="numeric"
                placeholder="Ex. 411"
                value={prefixe}
                onChange={e => setPrefixe(e.target.value.replace(/[^0-9A-Za-z]/g, ''))}
              />
            </div>
          </label>
        </div>
      </section>

      <section className={styles.summary} aria-label="Répartition par ancienneté">
        <div className={styles.totalCard}>
          <span>{sens === 'CREANCES' ? 'Total à recouvrer' : 'Total à régler'}</span>
          <strong>{montant(balance?.total ?? 0, '0,00')}</strong>
          <small>{balance?.lignes.length ?? 0} compte{(balance?.lignes.length ?? 0) > 1 ? 's' : ''} concerné{(balance?.lignes.length ?? 0) > 1 ? 's' : ''}</small>
        </div>
        <div className={styles.ageCards}>
          {repartition.map(item => (
            <div key={item.cle} className={`${styles.ageCard} ${styles[item.ton]}`}>
              <div>
                <span>{item.libelle}</span>
                <small>{item.statut}</small>
              </div>
              <strong>{montant(item.valeur, '0,00')}</strong>
              <div className={styles.progress} aria-label={`${item.part.toFixed(0)} % du total`}>
                <span style={{ width: `${Math.min(100, item.part)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.listPanel} aria-label="Détail de la balance âgée">
        <div className={styles.listHeader}>
          <div>
            <span className={styles.eyebrow}>Détail par tiers</span>
            <h3>Échéancier des comptes</h3>
          </div>
          {balanceQuery.isFetching && !balanceQuery.isLoading && <span className={styles.updating}>Actualisation…</span>}
        </div>

        {balanceQuery.isLoading ? (
          <div className={styles.state}>Calcul de la balance…</div>
        ) : balanceQuery.isError ? (
          <div className={`${styles.state} ${styles.errorState}`} role="alert">
            <AlertCircle size={20} />
            <strong>La balance n’a pas pu être calculée.</strong>
            <button type="button" onClick={() => balanceQuery.refetch()}>Réessayer</button>
          </div>
        ) : !balance || balance.lignes.length === 0 ? (
          <div className={styles.state}>
            <strong>Aucun reste dû pour cette sélection.</strong>
            <span>Modifiez la date, le sens ou le préfixe de compte pour élargir la recherche.</span>
          </div>
        ) : (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Compte</th>
                  <th>Libellé</th>
                  <th className={styles.center}>Lignes</th>
                  <th>Plus ancienne</th>
                  {TRANCHES.map(([cle, libelle]) => (
                    <th key={cle} className={styles.amount}>{libelle}</th>
                  ))}
                  <th className={styles.amount}>Reste dû</th>
                </tr>
              </thead>
              <tbody>
                {balance.lignes.map(l => (
                  <tr key={l.compte_id}>
                    <td className={styles.accountNumber}>{l.compte_numero}</td>
                    <td className={styles.accountName}>{l.compte_libelle}</td>
                    <td className={styles.center}><span className={styles.lineCount}>{l.lignes}</span></td>
                    <td>{jour(l.plus_ancienne)}</td>
                    {TRANCHES.map(([cle]) => (
                      <td key={cle} className={styles.amount}>{montant(l[cle])}</td>
                    ))}
                    <td className={`${styles.amount} ${styles.balance}`}><strong>{montant(l.solde)}</strong></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td />
                  <td><strong>Total général</strong></td>
                  <td className={styles.center}><strong>{balance.lignes.length}</strong></td>
                  <td />
                  {TRANCHES.map(([cle]) => (
                    <td key={cle} className={styles.amount}><strong>{montant(balance[cle], '0,00')}</strong></td>
                  ))}
                  <td className={`${styles.amount} ${styles.balance}`}><strong>{montant(balance.total, '0,00')}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      <p className={styles.footnote}>
        L’âge part de l’échéance de la pièce, ou de sa date comptable si aucune échéance n’est renseignée.
        Une balance fiable suppose un lettrage à jour.
      </p>
    </div>
  )
}
