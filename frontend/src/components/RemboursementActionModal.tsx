import { useState } from 'react'
import { format } from 'date-fns'
import { AlertTriangle } from 'lucide-react'
import styles from './RequisitionActionModal.module.css'

interface RemboursementActionModalProps {
  show: boolean
  action: 'approve' | 'reject'
  remboursementNumber: string
  requisitionNumber?: string
  onConfirm: (motif?: string) => void
  onCancel: () => void
  userName?: string
}

export default function RemboursementActionModal({
  show,
  action,
  remboursementNumber,
  requisitionNumber,
  onConfirm,
  onCancel,
  userName
}: RemboursementActionModalProps) {
  const [motif, setMotif] = useState('')

  if (!show) return null

  // Même feuille et mêmes classes que RequisitionActionModal : le régime de
  // couleur est porté par le CSS, plus par des styles en ligne.
  const approbation = action === 'approve'
  const classeEntete = approbation ? styles.headerApprove : styles.headerReject
  const classeConfirmer = approbation ? styles.confirmApprove : styles.confirmReject

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
        <div className={`${styles.header} ${classeEntete}`}>
          <div className={styles.icon}>
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
          <h2>
            {action === 'approve' ? 'Approuver le remboursement transport' : 'Rejeter le remboursement transport'}
          </h2>
        </div>

        <div className={styles.content}>
          <div className={styles.infoBox}>
            <div className={styles.infoRow}>
              <strong>Numéro de remboursement :</strong>
              <span>{remboursementNumber}</span>
            </div>
            {requisitionNumber && (
              <div className={styles.infoRow}>
                <strong>Document source :</strong>
                <span>{requisitionNumber}</span>
              </div>
            )}
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
                Vous êtes sur le point d'approuver ce remboursement de frais de transport.
              </p>
              <p className={styles.messageSuite}>
                Une fois approuvé, il sera automatiquement disponible dans le module <strong>Sorties de fonds</strong> pour paiement.
              </p>
            </div>
          ) : (
            <div className={styles.message}>
              <p className={styles.messageLabel}>
                Veuillez indiquer le motif du rejet de ce remboursement :
              </p>
              <textarea
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                placeholder="Exemple : Montants incorrects, documents manquants, non justifié, etc."
                className={styles.textarea}
                rows={3}
                autoFocus
              />
              {!motif.trim() && (
                <p className={styles.warning}>
                  <AlertTriangle size={13} aria-hidden="true" />
                  Le motif du rejet est obligatoire
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
            className={`${styles.confirmBtn} ${classeConfirmer}`}
          >
            {action === 'approve' ? 'Confirmer l\'approbation' : 'Confirmer le rejet'}
          </button>
        </div>
      </div>
    </div>
  )
}
