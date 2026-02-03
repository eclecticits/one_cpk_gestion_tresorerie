import { useState } from 'react'
import { format } from 'date-fns'
import styles from './RequisitionActionModal.module.css'

interface RequisitionActionModalProps {
  show: boolean
  action: 'approve' | 'reject'
  requisitionNumber: string
  onConfirm: (motif?: string) => void
  onCancel: () => void
  userName?: string
}

export default function RequisitionActionModal({
  show,
  action,
  requisitionNumber,
  onConfirm,
  onCancel,
  userName
}: RequisitionActionModalProps) {
  const [motif, setMotif] = useState('')

  if (!show) return null

  const handleConfirm = () => {
    if (action === 'reject' && !motif.trim()) {
      return
    }
    onConfirm(motif)
    setMotif('')
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header} style={{
          background: action === 'approve' ? '#dcfce7' : '#fee2e2',
          borderBottom: `3px solid ${action === 'approve' ? '#16a34a' : '#dc2626'}`
        }}>
          <div className={styles.icon} style={{
            background: action === 'approve' ? '#16a34a' : '#dc2626'
          }}>
            {action === 'approve' ? (
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            ) : (
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            )}
          </div>
          <h2 style={{color: action === 'approve' ? '#16a34a' : '#dc2626'}}>
            {action === 'approve' ? 'Approuver la réquisition' : 'Rejeter la réquisition'}
          </h2>
        </div>

        <div className={styles.content}>
          <div className={styles.infoBox}>
            <div className={styles.infoRow}>
              <strong>Numéro de réquisition :</strong>
              <span>{requisitionNumber}</span>
            </div>
            <div className={styles.infoRow}>
              <strong>Date :</strong>
              <span>{format(new Date(), 'dd/MM/yyyy')}</span>
            </div>
            {userName && (
              <div className={styles.infoRow}>
                <strong>Action effectuée par :</strong>
                <span>{userName}</span>
              </div>
            )}
          </div>

          {action === 'approve' ? (
            <div className={styles.message}>
              <p>
                Vous êtes sur le point d'approuver cette réquisition.
              </p>
              <p style={{marginTop: '12px', fontWeight: 500}}>
                Une fois approuvée, elle sera disponible dans le module <strong>Sorties de fonds</strong> pour décaissement.
              </p>
            </div>
          ) : (
            <div className={styles.message}>
              <p style={{marginBottom: '16px'}}>
                Veuillez indiquer le motif du rejet de cette réquisition :
              </p>
              <textarea
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                placeholder="Exemple : Budget dépassé, informations manquantes, etc."
                className={styles.textarea}
                rows={4}
                autoFocus
              />
              {!motif.trim() && (
                <p className={styles.warning}>
                  ⚠ Le motif du rejet est obligatoire
                </p>
              )}
            </div>
          )}
        </div>

        <div className={styles.actions}>
          <button onClick={onCancel} className={styles.cancelBtn}>
            Annuler
          </button>
          <button
            onClick={handleConfirm}
            disabled={action === 'reject' && !motif.trim()}
            className={styles.confirmBtn}
            style={{
              background: action === 'approve' ? '#16a34a' : '#dc2626',
              opacity: action === 'reject' && !motif.trim() ? 0.5 : 1,
              cursor: action === 'reject' && !motif.trim() ? 'not-allowed' : 'pointer'
            }}
          >
            {action === 'approve' ? 'Confirmer l\'approbation' : 'Confirmer le rejet'}
          </button>
        </div>
      </div>
    </div>
  )
}
