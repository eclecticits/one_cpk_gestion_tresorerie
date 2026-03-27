import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getBillingStatus } from '../api/billing'
import styles from './BillingAlert.module.css'

function formatDate(value?: string | null) {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('fr-FR')
}

export default function BillingAlert() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [remoteStatus, setRemoteStatus] = useState<string | null>(null)
  const [remoteExpiresAt, setRemoteExpiresAt] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const isAdmin = user?.role === 'admin' || user?.role === 'super_admin'

  const loadStatus = useCallback(async () => {
    if (!isAdmin) return
    setRefreshing(true)
    try {
      const res = await getBillingStatus()
      const nextStatus = res?.status ? String(res.status).toUpperCase() : null
      setRemoteStatus(nextStatus)
      setRemoteExpiresAt(res?.plan_expires_at || null)
    } catch {
      setRemoteStatus(null)
      setRemoteExpiresAt(null)
    } finally {
      setRefreshing(false)
    }
  }, [isAdmin])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  const status = useMemo(
    () => (remoteStatus || user?.plan_status || '').toUpperCase(),
    [remoteStatus, user?.plan_status]
  )

  if (!isAdmin || !status || status === 'ACTIVE' || status === 'TRIAL') return null

  const isCritical = ['CANCELED', 'SUSPENDED', 'EXPIRED'].includes(status)
  const isWarning = status === 'PAST_DUE'
  const label = isCritical
    ? "ACCÈS RESTREINT : votre abonnement est expiré ou suspendu."
    : isWarning
      ? 'RAPPEL : votre abonnement est en retard. Certaines actions peuvent être bloquées.'
      : "Alerte abonnement : votre statut nécessite une régularisation."

  const expiresAt = formatDate(remoteExpiresAt || user?.plan_expires_at || null)

  return (
    <div className={`${styles.banner} ${isCritical ? styles.danger : styles.warning}`} role="alert">
      <span>
        {label}
        {expiresAt ? ` Expiration : ${expiresAt}.` : ''}
      </span>
      <div className={styles.actions}>
        <button type="button" className={styles.action} onClick={loadStatus} disabled={refreshing}>
          {refreshing ? 'Actualisation...' : 'Actualiser'}
        </button>
        <button type="button" className={styles.action} onClick={() => navigate('/settings')}>
          Gérer la facturation
        </button>
      </div>
    </div>
  )
}
