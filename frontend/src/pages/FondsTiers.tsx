import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import {
  FONDS_TIERS_STATUT_LABELS,
  listFondsTiers,
  type FondsTiersOperation,
} from '../api/mouvementsHorsBudget'
import { toNumber } from '../utils/amount'
import styles from './FondsTiers.module.css'

/**
 * Argent détenu pour le compte d'autrui.
 *
 * Ces fonds sont entrés en trésorerie sans jamais appartenir à l'organisation :
 * ils n'ont alimenté aucun poste budgétaire et doivent repartir. L'écran répond
 * donc à une seule question — combien reste-t-il à reverser, et à qui.
 */

const formatMontant = (valeur: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: devise === 'CDF' ? 'CDF' : 'USD',
  }).format(toNumber(valeur as any) || 0)

type FiltreStatut = 'A_REVERSER' | 'TOUS' | FondsTiersOperation['statut']

export default function FondsTiers() {
  const [operations, setOperations] = useState<FondsTiersOperation[]>([])
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [filtre, setFiltre] = useState<FiltreStatut>('A_REVERSER')

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      setOperations(await listFondsTiers())
    } catch (e: any) {
      setErreur(e?.message || 'Impossible de charger les fonds de tiers.')
      setOperations([])
    } finally {
      setChargement(false)
    }
  }, [])

  useEffect(() => {
    charger()
  }, [charger])

  const visibles = useMemo(() => {
    if (filtre === 'TOUS') return operations
    if (filtre === 'A_REVERSER') {
      return operations.filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE')
    }
    return operations.filter((op) => op.statut === filtre)
  }, [operations, filtre])

  // Un total par devise : additionner des dollars et des francs ne dirait rien.
  const soldesParDevise = useMemo(() => {
    const cumul = new Map<string, number>()
    operations
      .filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE')
      .forEach((op) => {
        cumul.set(op.devise, (cumul.get(op.devise) || 0) + (toNumber(op.solde_restant) || 0))
      })
    return Array.from(cumul.entries())
  }, [operations])

  return (
    <div className={styles.page}>
      <PageHeader
        title="Fonds de tiers"
        subtitle="Argent encaissé pour le compte d'un tiers : présent en trésorerie, absent du budget, à reverser."
        actions={
          <div className={styles.headerActions}>
            <Link to="/sorties-fonds/nouvelle" className={styles.primaryLink}>
              Reverser des fonds
            </Link>
            <button type="button" className={styles.iconBtn} onClick={charger} title="Rafraîchir">
              <RefreshCw size={16} />
            </button>
          </div>
        }
      />

      <div className={styles.summary}>
        {soldesParDevise.length === 0 ? (
          <div className={styles.summaryCard}>
            <span className={styles.summaryLabel}>Reste à reverser</span>
            <strong className={styles.summaryValue}>Aucun</strong>
          </div>
        ) : (
          soldesParDevise.map(([devise, total]) => (
            <div key={devise} className={styles.summaryCard}>
              <span className={styles.summaryLabel}>Reste à reverser ({devise})</span>
              <strong className={styles.summaryValue}>{formatMontant(total, devise)}</strong>
            </div>
          ))
        )}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Dossiers ouverts</span>
          <strong className={styles.summaryValue}>
            {operations.filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE').length}
          </strong>
        </div>
      </div>

      <div className={styles.filters}>
        {([
          ['A_REVERSER', 'À reverser'],
          ['REGULARISE', 'Soldés'],
          ['ANNULE', 'Annulés'],
          ['TOUS', 'Tous'],
        ] as [FiltreStatut, string][]).map(([valeur, label]) => (
          <button
            key={valeur}
            type="button"
            className={`${styles.filterBtn} ${filtre === valeur ? styles.filterBtnActive : ''}`}
            onClick={() => setFiltre(valeur)}
          >
            {label}
          </button>
        ))}
      </div>

      {erreur && <div className={styles.error}>{erreur}</div>}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Tiers</th>
              <th>Bénéficiaire réel</th>
              <th>Payeur d'origine</th>
              <th>Reçu</th>
              <th>Reversé</th>
              <th>Reste</th>
              <th>Statut</th>
              <th>Reçu le</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {chargement ? (
              <tr>
                <td colSpan={9} className={styles.empty}>Chargement…</td>
              </tr>
            ) : visibles.length === 0 ? (
              <tr>
                <td colSpan={9} className={styles.empty}>
                  {filtre === 'A_REVERSER'
                    ? 'Aucun fonds de tiers en attente de reversement.'
                    : 'Aucun fonds de tiers pour ce filtre.'}
                </td>
              </tr>
            ) : (
              visibles.map((op) => (
                <tr key={op.id}>
                  <td>
                    <strong>{op.tiers_display_name}</strong>
                    <div className={styles.sub}>
                      {op.tiers_type === 'ORGANISATION'
                        ? 'Tenant ONEC'
                        : op.tiers_type === 'EXTERNE'
                          ? 'Tiers externe'
                          : 'Historique'}
                    </div>
                    {op.motif && <div className={styles.sub}>{op.motif}</div>}
                  </td>
                  <td>{op.beneficiaire_reel || '—'}</td>
                  <td>{op.payeur_origine || '—'}</td>
                  <td>{formatMontant(op.montant_recu, op.devise)}</td>
                  <td>{formatMontant(op.montant_rembourse, op.devise)}</td>
                  <td>
                    <strong className={toNumber(op.solde_restant) > 0 ? styles.soldeDu : styles.soldeNul}>
                      {formatMontant(op.solde_restant, op.devise)}
                    </strong>
                  </td>
                  <td>
                    <span className={styles.statut} data-statut={op.statut}>
                      {FONDS_TIERS_STATUT_LABELS[op.statut]}
                    </span>
                  </td>
                  <td>{new Date(op.created_at).toLocaleDateString('fr-FR')}</td>
                  <td>
                    {(op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE') && (
                      <Link
                        to={`/sorties-fonds/nouvelle?type_sortie=remboursement_fonds_tiers&fonds_tiers_operation_id=${op.id}`}
                        className={styles.primaryLink}
                      >
                        Rembourser
                      </Link>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
