import { useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { format } from 'date-fns'
import styles from './AuditSortie.module.css'
import { API_BASE_URL } from '../lib/apiClient'
import { toNumber } from '../utils/amount'

type AuditSortieResponse =
  | {
      status: 'VALID' | 'CANCELLED'
      statut_sortie?: string | null
      reference_numero: string | null
      requisition_numero: string | null
      beneficiaire: string | null
      montant_paye: number
      date_paiement: string | null
      motif_annulation?: string | null
    }
  | { status: 'NOT_FOUND'; message: string }

const useQuery = () => {
  const { search } = useLocation()
  return useMemo(() => new URLSearchParams(search), [search])
}

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

export default function AuditSortie() {
  const query = useQuery()
  const ref = query.get('ref') || ''
  const id = query.get('id') || ''
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<AuditSortieResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        if (ref) params.set('ref', ref)
        if (id && !ref) params.set('id', id)
        const resp = await fetch(`${API_BASE_URL}/audit/sortie?${params.toString()}`, {
          headers: { Accept: 'application/json' },
        })
        const payload = await resp.json()
        setData(payload)
      } catch (err: any) {
        setError(err?.message || 'Impossible de vérifier le document.')
      } finally {
        setLoading(false)
      }
    }

    run()
  }, [ref, id])

  const isValid = data?.status === 'VALID'
  const isCancelled = data?.status === 'CANCELLED'
  const isRefunded = false
  const dateLabel =
    data && 'date_paiement' in data && data.date_paiement
      ? format(new Date(data.date_paiement), 'dd/MM/yyyy')
      : '-'
  const statusLabel = isCancelled ? 'Annulée' : 'Validée'

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <img src="/imge_onec.png" alt="ONEC/CPK" className={styles.brandLogo} />
          <div>
            <div className={styles.brandTitle}>ONEC / CPK</div>
            <div className={styles.brandSubtitle}>République Démocratique du Congo</div>
          </div>
        </div>
        <div className={styles.header}>
          <div
            className={`${styles.statusIcon} ${
              isValid
                ? styles.statusIconValid
                : isCancelled
                ? styles.statusIconCancelled
                : styles.statusIconInvalid
            }`}
          >
            {loading ? '⏳' : isValid ? '✅' : isCancelled ? '⛔' : '⚠️'}
          </div>
          <div>
            <h1 className={styles.title}>
              {loading
                ? 'Vérification en cours...'
                : isValid
                ? 'Sortie de fonds validée'
                : isCancelled
                ? 'Sortie de fonds annulée'
                : 'Document introuvable'}
            </h1>
            <p className={styles.subtitle}>
              {loading
                ? 'Merci de patienter.'
                : isValid
                ? 'Ce document correspond à un enregistrement officiel.'
                : isCancelled
                ? 'Ce paiement a été annulé dans le système.'
                : 'La référence fournie ne correspond à aucune sortie de fonds.'}
            </p>
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {!loading && data?.status !== 'NOT_FOUND' && data && (
          <div className={styles.details}>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Référence</span>
              <span className={styles.detailValue}>{data.reference_numero || '-'}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Statut</span>
              <span
                className={`${styles.statusBadge} ${
                  isValid
                    ? styles.statusBadgeValid
                    : isCancelled
                    ? styles.statusBadgeCancelled
                    : ''
                }`}
              >
                {statusLabel}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Réquisition liée</span>
              <span className={styles.detailValue}>{data.requisition_numero || '-'}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Bénéficiaire</span>
              <span className={styles.detailValue}>{data.beneficiaire || '-'}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Montant</span>
              <span className={styles.detailValue}>
                {formatMoney(toNumber(data.montant_paye || 0))}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Date de paiement</span>
              <span className={styles.detailValue}>{dateLabel}</span>
            </div>
            {isCancelled && (
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Motif</span>
                <span className={styles.detailValue}>{data.motif_annulation || '-'}</span>
              </div>
            )}
          </div>
        )}

        {!loading && !isValid && data?.status === 'NOT_FOUND' && (
          <p className={styles.hint}>{data.message}</p>
        )}

        <p className={styles.hint}>
          Si ce document vous a été remis physiquement, contactez la trésorerie en cas de doute.
        </p>
      </div>
    </div>
  )
}
