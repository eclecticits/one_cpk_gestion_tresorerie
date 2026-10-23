import { CircleAlert, ReceiptText } from 'lucide-react'
import { FormSection, FormSectionNav, type FormSectionItem } from '../form/FormSections'
import styles from './SortieFondsUi.module.css'

export type SortieSectionItem = FormSectionItem

export function SortieSectionNav({ items }: { items: SortieSectionItem[] }) {
  return <FormSectionNav items={items} label="Sections de la sortie de fonds" />
}

// Même carte de section que la réquisition : les deux écrans se lisent pareil.
export const SortieSection = FormSection

type SortieSummaryProps = {
  amount: string
  source: string
  type: string
  service: string
  beneficiary: string
  date: string
  payment: string
  status: string
  approvedSource: boolean
  approvedAmount: string
  paidAmount: string
  remainingAmount: string
  warning?: string
}

export function SortieSummaryPanel({
  amount,
  source,
  type,
  service,
  beneficiary,
  date,
  payment,
  status,
  approvedSource,
  approvedAmount,
  paidAmount,
  remainingAmount,
  warning,
}: SortieSummaryProps) {
  return (
    <aside className={styles.summary} aria-label="Vérification de la sortie de fonds" id="sortie-section-verification">
      <div className={styles.summaryHead}>
        <span className={styles.summaryEyebrow}><ReceiptText size={14} /> Vérification</span>
        <strong className={styles.summaryTotal}>{amount}</strong>
        <span className={styles.summarySource}>{source}</span>
      </div>

      <div className={styles.summaryBody}>
        <div className={styles.summaryRows}>
          <SummaryRow label="Type" value={type} />
          <SummaryRow label="Service / Commission" value={service} placeholder={service === 'Non requis' || service === 'Non défini'} />
          <SummaryRow label="Bénéficiaire" value={beneficiary} placeholder={beneficiary === 'Non requis' || beneficiary === 'À désigner avant paiement'} />
          <SummaryRow label="Paiement" value={payment} />
          <SummaryRow label="Date" value={date} />
          <SummaryRow label="Statut" value={status} />
        </div>

        {approvedSource && (
          <>
            <div className={styles.reviewHeading}>Situation de la pièce autorisée</div>
            <div className={styles.amountReview}>
              <SummaryMetric label="Montant approuvé" value={approvedAmount} />
              <SummaryMetric label="Déjà payé" value={paidAmount} />
              <SummaryMetric label="Cette sortie" value={amount} accent />
              <SummaryMetric label="Reste après validation" value={remainingAmount} />
            </div>
          </>
        )}

        {warning && (
          <div className={styles.validationNotice} role="alert">
            <CircleAlert size={15} aria-hidden="true" />
            <span>{warning}</span>
          </div>
        )}
      </div>
    </aside>
  )
}

function SummaryRow({ label, value, placeholder }: { label: string; value: string; placeholder?: boolean }) {
  return (
    <div className={styles.summaryRow}>
      <span>{label}</span>
      <strong className={placeholder ? styles.summaryPlaceholder : undefined}>{value}</strong>
    </div>
  )
}

function SummaryMetric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={styles.summaryMetric} data-accent={accent || undefined}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
