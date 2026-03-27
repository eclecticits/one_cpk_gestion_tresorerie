import { useEffect, useState } from 'react'
import { listBankProofs, approveBankProof, rejectBankProof } from '../../api/superAdmin'
import { useConfirmWithInput } from '../../contexts/ConfirmContext'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './TenantBankProofs.module.css'

type TenantBankProofsProps = {
  tenantId: string
}

export default function TenantBankProofs({ tenantId }: TenantBankProofsProps) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const confirmWithInput = useConfirmWithInput()
  const { showSuccess, showError, showWarning } = useNotification()

  const load = async () => {
    try {
      setLoading(true)
      const res = await listBankProofs(20, tenantId)
      setItems(res.items || [])
    } catch (err: any) {
      showError('Erreur', err?.message || 'Impossible de charger les preuves.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [tenantId])

  const approve = async (txId: string) => {
    const result = await confirmWithInput({
      title: 'Valider la preuve bancaire',
      description: 'Tapez VALIDER pour activer immédiatement l’abonnement.',
      inputPlaceholder: 'VALIDER',
      confirmText: 'Valider',
      variant: 'danger',
    })
    if (!result.confirmed || result.value.toUpperCase() !== 'VALIDER') return
    try {
      await approveBankProof(txId)
      showSuccess('Paiement validé', 'La preuve bancaire a été approuvée.')
      await load()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Validation impossible.')
    }
  }

  const reject = async (txId: string) => {
    const result = await confirmWithInput({
      title: 'Rejeter la preuve bancaire',
      description: 'Tapez REJETER pour marquer ce paiement comme échoué.',
      inputPlaceholder: 'REJETER',
      confirmText: 'Rejeter',
      variant: 'danger',
    })
    if (!result.confirmed || result.value.toUpperCase() !== 'REJETER') return
    try {
      await rejectBankProof(txId)
      showWarning('Preuve rejetée', 'La transaction est marquée comme échouée.')
      await load()
    } catch (err: any) {
      showError('Erreur', err?.message || 'Rejet impossible.')
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <h3>Preuves bancaires (tenant)</h3>
        <button className={styles.refreshBtn} onClick={load} disabled={loading}>
          {loading ? 'Chargement...' : 'Rafraîchir'}
        </button>
      </div>
      {items.length === 0 ? (
        <div className={styles.empty}>Aucune preuve reçue.</div>
      ) : (
        <div className={styles.list}>
          {items.map((proof) => (
            <div key={proof.id} className={styles.item}>
              <div>
                <strong>{proof.id}</strong>
                <div className={styles.meta}>
                  {Number(proof.amount || 0).toLocaleString()} {proof.currency || 'USD'} · {proof.status || '—'}
                </div>
                <div className={styles.meta}>
                  Reçu le {proof.proof_uploaded_at ? new Date(proof.proof_uploaded_at).toLocaleString() : '—'}
                </div>
              </div>
              <div className={styles.actions}>
                {proof.proof_url && (
                  <a className={styles.link} href={proof.proof_url} target="_blank" rel="noreferrer">
                    Ouvrir
                  </a>
                )}
                <button onClick={() => approve(proof.id)} disabled={(proof.status || '').toLowerCase() === 'success'}>
                  Valider
                </button>
                <button onClick={() => reject(proof.id)} disabled={(proof.status || '').toLowerCase() === 'failed'}>
                  Rejeter
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
