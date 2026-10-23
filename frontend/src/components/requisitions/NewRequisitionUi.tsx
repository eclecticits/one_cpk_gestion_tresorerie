import type { ReactNode } from 'react'
import {
  Banknote,
  FileText,
  Landmark,
  Paperclip,
  ReceiptText,
  X,
} from 'lucide-react'
import type { CompteBancaire } from '../../types/banque'
import type { ModePaiement } from '../../types'
import { FormSection, FormSectionNav, type FormSectionItem } from '../form/FormSections'
import styles from './NewRequisitionUi.module.css'

export function RequisitionSectionNav({ items }: { items: FormSectionItem[] }) {
  return <FormSectionNav items={items} label="Sections de la réquisition" />
}

// Les sections de la réquisition ont la forme commune des formulaires de création.
export const RequisitionSection = FormSection

export function BeneficiarySection({ children }: { children: ReactNode }) {
  return (
    <RequisitionSection
      id="req-section-beneficiaire"
      number={2}
      title="Bénéficiaire"
      description="La personne qui recevra les fonds, si elle est déjà connue."
      optional
    >
      {children}
    </RequisitionSection>
  )
}

type PaymentSectionProps = {
  mode: ModePaiement
  onModeChange: (mode: ModePaiement) => void
  bankAccountId: string
  onBankAccountChange: (id: string) => void
  bankAccounts: CompteBancaire[]
  perLine: boolean
  onPerLineChange: (checked: boolean) => void
  aValoir: boolean
  onAValoirChange: (checked: boolean) => void
  progressive: boolean
  onProgressiveChange: (checked: boolean) => void
  progressiveLocked?: boolean
  progressiveDescription: string
  extraFields?: ReactNode
}

export function PaymentSection({
  mode,
  onModeChange,
  bankAccountId,
  onBankAccountChange,
  bankAccounts,
  perLine,
  onPerLineChange,
  aValoir,
  onAValoirChange,
  progressive,
  onProgressiveChange,
  progressiveLocked,
  progressiveDescription,
  extraFields,
}: PaymentSectionProps) {
  return (
    <RequisitionSection
      id="req-section-paiement"
      number={3}
      title="Paiement"
      description="Définissez le canal principal et activez seulement les options utiles."
    >
      <div className={styles.paymentGrid}>
        <div>
          <span className={styles.fieldLabel}>Mode de paiement *</span>
          <div className={styles.methodPicker} role="group" aria-label="Mode de paiement">
            <button
              type="button"
              className={styles.methodOption}
              data-active={mode === 'cash'}
              aria-pressed={mode === 'cash'}
              onClick={() => onModeChange('cash')}
            >
              <Banknote size={15} aria-hidden="true" /> Caisse
            </button>
            <button
              type="button"
              className={styles.methodOption}
              data-active={mode === 'virement'}
              aria-pressed={mode === 'virement'}
              onClick={() => onModeChange('virement')}
            >
              <Landmark size={15} aria-hidden="true" /> Banque
            </button>
          </div>
        </div>

        {mode === 'virement' ? (
          <label className={styles.bankField} htmlFor="req-compte-bancaire">
            <span className={styles.fieldLabel}>Compte bancaire *</span>
            <select
              id="req-compte-bancaire"
              value={bankAccountId}
              onChange={(event) => onBankAccountChange(event.target.value)}
              required
            >
              <option value="">Sélectionner un compte bancaire</option>
              {bankAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {(account.banque?.nom || 'Banque')} - {account.intitule} ({account.devise})
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className={styles.bankField} aria-hidden="true" />
        )}
      </div>

      <div className={styles.toggleGrid}>
        <PaymentToggle
          id="reglement-par-ligne"
          label="Règlement par ligne"
          description="Un canal différent selon la dépense."
          checked={perLine}
          onChange={onPerLineChange}
        />
        <PaymentToggle
          id="a_valoir"
          label="À valoir"
          description="Dépense remboursée par une autre instance."
          checked={aValoir}
          onChange={onAValoirChange}
        />
        <PaymentToggle
          id="decaissement_progressif"
          label="Décaissement progressif"
          description={progressiveDescription}
          checked={progressive}
          onChange={onProgressiveChange}
          disabled={progressiveLocked}
          locked={progressiveLocked}
        />
      </div>

      {progressive && (
        <p className={styles.paymentNote}>
          Les paiements pourront être autorisés par tranches, dans la limite du total approuvé.
        </p>
      )}
      {extraFields && <div className={styles.extraFields}>{extraFields}</div>}
    </RequisitionSection>
  )
}

type PaymentToggleProps = {
  id: string
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  locked?: boolean
}

function PaymentToggle({ id, label, description, checked, onChange, disabled, locked }: PaymentToggleProps) {
  return (
    <label className={styles.toggleCard} htmlFor={id} data-checked={checked} data-locked={locked || undefined}>
      <span className={styles.toggleText}>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <input
        className={styles.switchInput}
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  )
}

type AttachmentSectionProps = {
  file: File | null
  error: string
  onFileChange: (file: File | null) => void
}

export function AttachmentSection({ file, error, onFileChange }: AttachmentSectionProps) {
  return (
    <RequisitionSection
      id="req-section-justificatif"
      number={4}
      title="Pièce justificative"
      description="Un seul fichier. Regroupez plusieurs pièces dans un PDF."
      optional
    >
      <div
        className={styles.dropzone}
        data-error={Boolean(error)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          const droppedFile = event.dataTransfer.files?.[0]
          if (droppedFile) onFileChange(droppedFile)
        }}
      >
        <input
          id="req-annexe"
          type="file"
          accept=".pdf,image/png,image/jpeg"
          aria-label="Ajouter un justificatif au format PDF, PNG ou JPEG, 3 Mo maximum"
          onChange={(event) => onFileChange(event.target.files?.[0] || null)}
        />
        <div className={styles.dropContent}>
          <span className={styles.dropIcon}><Paperclip size={16} aria-hidden="true" /></span>
          <span className={styles.dropText}>
            <strong>Déposer un justificatif ou parcourir</strong>
            <span>PDF, PNG ou JPEG · 3 Mo maximum</span>
          </span>
        </div>
      </div>
      {file && !error && (
        <div className={styles.selectedFile}>
          <FileText size={15} aria-hidden="true" />
          <span>{file.name}</span>
          <button
            type="button"
            className={styles.clearFile}
            onClick={() => onFileChange(null)}
            aria-label="Retirer le justificatif"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}
      {error && <p className={styles.fileError} role="alert">{error}</p>}
    </RequisitionSection>
  )
}

export type ActiveBudgetSummary = {
  code: string
  label: string
  current: string
  after: string
  expense: string
  consumption: number
  overrun: boolean
}

type SummaryPanelProps = {
  total: string
  service: string
  date: string
  payment: string
  nature: string
  beneficiary: string
  lineCount: number | null
  groupCount: number | null
  budgetary: boolean
  activeBudget?: ActiveBudgetSummary | null
}

export function RequisitionSummaryPanel({
  total,
  service,
  date,
  payment,
  nature,
  beneficiary,
  lineCount,
  groupCount,
  budgetary,
  activeBudget,
}: SummaryPanelProps) {
  const formattedLines = lineCount == null
    ? 'Sans lignes budgétaires'
    : `${lineCount} dépense${lineCount > 1 ? 's' : ''} · ${groupCount} poste${(groupCount || 0) > 1 ? 's' : ''}`

  return (
    <aside className={styles.summary} aria-label="Vérification et analyse budgétaire" id="req-section-verification">
      <div className={styles.summaryHead}>
        <span className={styles.summaryEyebrow}><ReceiptText size={14} /> Vérification</span>
        <strong className={styles.summaryTotal}>{total}</strong>
      </div>
      <div className={styles.summaryBody}>
        <div className={styles.summaryRows}>
          <SummaryRow label="Service / Commission" value={service} placeholder={service === 'Non sélectionné'} />
          <SummaryRow label="Date" value={date} />
          <SummaryRow label="Mode de paiement" value={payment} />
          <SummaryRow label="Nature" value={nature} />
          <SummaryRow label="Bénéficiaire" value={beneficiary} placeholder={beneficiary === 'Non renseigné (facultatif)'} />
          <SummaryRow label="Saisie" value={formattedLines} />
        </div>

        <div className={styles.budgetHeading}>Analyse budgétaire du poste actif</div>
        {!budgetary ? (
          <div className={styles.summaryEmpty}>Cette réquisition n’impute pas le budget initial.</div>
        ) : activeBudget ? (
          <div className={styles.budgetCard}>
            <div className={styles.budgetTitle}>{activeBudget.code} — {activeBudget.label}</div>
            <div className={styles.budgetMetric}>
              <span>Solde actuel</span>
              <strong>{activeBudget.current}</strong>
            </div>
            <div className={styles.budgetMetric}>
              <span>Dépense saisie</span>
              <strong>{activeBudget.expense}</strong>
            </div>
            <div className={styles.budgetMetric} data-negative={activeBudget.overrun}>
              <span>Reste à vivre</span>
              <strong>{activeBudget.after}</strong>
            </div>
            <div className={styles.progressTrack} aria-hidden="true">
              <div
                className={styles.progressFill}
                data-overrun={activeBudget.overrun}
                style={{ width: `${Math.min(100, Math.max(0, activeBudget.consumption))}%` }}
              />
            </div>
            <div className={styles.progressLabel}>Consommation après demande : {activeBudget.consumption.toFixed(1)} %</div>
          </div>
        ) : (
          <div className={styles.summaryEmpty}>
            Sélectionnez un poste pour visualiser son solde et l’impact de la demande.
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
