import { useEffect, useState } from 'react'
import { listOrgPayments } from '../../api/superAdmin'
import styles from './TenantPaymentHistory.module.css'

type TenantPaymentHistoryProps = {
  orgId: number
}

export default function TenantPaymentHistory({ orgId }: TenantPaymentHistoryProps) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    try {
      setLoading(true)
      const res = await listOrgPayments(orgId, 50)
      setItems(res.items || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [orgId])

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h3>Historique des paiements</h3>
        <button className={styles.refreshBtn} onClick={load} disabled={loading}>
          {loading ? 'Chargement...' : 'Rafraîchir'}
        </button>
      </div>
      {items.length === 0 ? (
        <div className={styles.empty}>Aucun paiement enregistré.</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Montant</th>
              <th>Statut</th>
              <th>Méthode</th>
              <th>Payé le</th>
            </tr>
          </thead>
          <tbody>
            {items.map((tx) => (
              <tr key={tx.id}>
                <td>{tx.created_at ? new Date(tx.created_at).toLocaleString() : '—'}</td>
                <td>
                  {Number(tx.amount || 0).toLocaleString()} {tx.currency || 'USD'}
                </td>
                <td>{tx.status || '—'}</td>
                <td>{tx.method || tx.provider || '—'}</td>
                <td>{tx.paid_at ? new Date(tx.paid_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
