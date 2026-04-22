import { format } from 'date-fns'
import type { Money } from '../types'
import { toNumber } from '../utils/amount'
import styles from './SortieFondsNotification.module.css'

interface SortieFondsNotificationProps {
  requisition: {
    numero_requisition: string
    objet: string
    montant_total: Money
    remboursement_transport?: {
      numero_remboursement?: string | null
      reference_numero?: string | null
    } | null
  }
  sortie: {
    montant_paye: Money
    mode_paiement: string
    date_paiement: string
    reference: string
    type_sortie?: string
    document_label?: string
    document_reference?: string
  }
  userName: string
  onClose: () => void
  onViewDetails?: () => void
  onPrintReceipt?: () => void
}

export default function SortieFondsNotification({
  requisition,
  sortie,
  userName,
  onClose,
  onViewDetails,
  onPrintReceipt
}: SortieFondsNotificationProps) {
  const formatCurrency = (amount: Money) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const getModeLabel = (mode: string) => {
    const labels: Record<string, string> = {
      cash: 'Caisse',
      mobile_money: 'Mobile Money',
      virement: 'Opération bancaire'
    }
    return labels[mode] || mode
  }

  const documentLabel =
    sortie.document_label ||
    (sortie.type_sortie === 'remboursement' ? 'Remboursement transport' : 'Réquisition')
  const documentReference =
    sortie.document_reference ||
    requisition.remboursement_transport?.reference_numero ||
    requisition.remboursement_transport?.numero_remboursement ||
    requisition.numero_requisition

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.iconContainer}>
            <div className={styles.icon}>✓</div>
          </div>
          <div className={styles.headerContent}>
            <h2>Sortie de fonds validée</h2>
            <p>L'opération a été enregistrée avec succès</p>
          </div>
        </div>

        <div className={styles.body}>
          <div className={styles.detailsGrid}>
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>{documentLabel}</span>
              <span className={styles.detailValue}>{documentReference}</span>
            </div>

            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Objet</span>
              <span className={styles.detailValue}>{requisition.objet}</span>
            </div>

            <div className={`${styles.detailItem} ${styles.highlight}`}>
              <span className={styles.detailLabel}>Montant payé</span>
              <span className={`${styles.detailValue} ${styles.amount}`}>
                {formatCurrency(sortie.montant_paye)}
              </span>
            </div>

            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Mode de paiement</span>
              <span className={styles.detailValue}>{getModeLabel(sortie.mode_paiement)}</span>
            </div>

            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Référence</span>
              <span className={styles.detailValue}>{sortie.reference}</span>
            </div>

            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Date de paiement</span>
              <span className={styles.detailValue}>
                {format(new Date(sortie.date_paiement), 'dd/MM/yyyy')}
              </span>
            </div>

            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Validée par</span>
              <span className={styles.detailValue}>{userName}</span>
            </div>
          </div>

          <div className={styles.actions}>
            {onViewDetails && (
              <button onClick={onViewDetails} className={`${styles.actionBtn} ${styles.secondary}`}>
                Voir détails
              </button>
            )}
            {onPrintReceipt && (
              <button onClick={onPrintReceipt} className={`${styles.actionBtn} ${styles.secondary}`}>
                Imprimer reçu
              </button>
            )}
            <button onClick={onClose} className={`${styles.actionBtn} ${styles.primary}`}>
              Retour à la liste
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
