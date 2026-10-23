import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Plus, Search, Trash2 } from 'lucide-react'
import type { CompteBancaire } from '../../types/banque'
import type { BudgetPosteSummary } from '../../types/budget'
import type { ModePaiement } from '../../types'
import { RequisitionSection } from './NewRequisitionUi'
import styles from './RequisitionExpenseEditor.module.css'

export type RequisitionExpenseLineDraft = {
  id: string
  description: string
  quantite: number
  montant_unitaire: string | number
  montant_total: string | number
  devise?: 'USD' | 'CDF'
  mode_paiement?: ModePaiement | null
  compte_bancaire_id?: number | null
}

export type RequisitionExpenseGroupDraft = {
  id: string
  budget_poste_id: number | null
  rubrique: string
  budgetSearch: string
  showBudgetDropdown: boolean
  lignes: RequisitionExpenseLineDraft[]
}

type ExpenseEditorProps = {
  groups: RequisitionExpenseGroupDraft[]
  activeGroupId: string | null
  onActiveGroupChange: (groupId: string) => void
  budgetLinesById: Map<number, BudgetPosteSummary>
  budgetLineCount: number
  copiedRequisition: boolean
  perLinePayment: boolean
  accounts: CompteBancaire[]
  globalPaymentMode: ModePaiement
  exchangeRate: number
  alertThreshold: number
  blockOverrun: boolean
  formatCurrency: (amount: number) => string
  toUsd: (amount: string | number | null | undefined, currency: 'USD' | 'CDF') => number
  subtotalUsd: (group: RequisitionExpenseGroupDraft) => number
  totalUsd: number
  renderBudgetOptions: (groupId: string, query: string) => ReactNode[]
  onSearchBudget: (groupId: string, value: string) => void
  onDropdownChange: (groupId: string, open: boolean) => void
  onRemoveGroup: (groupId: string) => void
  onAddGroup: () => void
  onUpdateLine: (groupId: string, lineId: string, field: string, value: unknown) => void
  onChangeLinePayment: (groupId: string, lineId: string, mode: '' | 'cash' | 'virement') => void
  onRemoveLine: (groupId: string, lineId: string) => void
  onAddLine: (groupId: string) => void
  paymentLabel: (mode?: string | null) => string
  footer?: ReactNode
}

type BudgetPosteSearchProps = {
  groupId: string
  groupIndex: number
  query: string
  open: boolean
  options: ReactNode[]
  onSearch: (value: string) => void
  onOpenChange: (open: boolean) => void
  onActivate: () => void
}

const DROPDOWN_GAP = 6
const VIEWPORT_MARGIN = 12
const PREFERRED_DROPDOWN_WIDTH = 620
const MAX_DROPDOWN_HEIGHT = 380
const MIN_COMFORTABLE_HEIGHT = 220

function BudgetPosteSearch({
  groupId,
  groupIndex,
  query,
  open,
  options,
  onSearch,
  onOpenChange,
  onActivate,
}: BudgetPosteSearchProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<CSSProperties | null>(null)

  const updatePosition = useCallback(() => {
    const input = inputRef.current
    if (!input) return

    const rect = input.getBoundingClientRect()
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      onOpenChange(false)
      return
    }

    const availableWidth = Math.max(0, window.innerWidth - (VIEWPORT_MARGIN * 2))
    const width = Math.min(Math.max(rect.width, PREFERRED_DROPDOWN_WIDTH), availableWidth)
    const left = Math.min(
      Math.max(rect.left, VIEWPORT_MARGIN),
      Math.max(VIEWPORT_MARGIN, window.innerWidth - VIEWPORT_MARGIN - width),
    )
    const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN - DROPDOWN_GAP
    const spaceAbove = rect.top - VIEWPORT_MARGIN - DROPDOWN_GAP
    const placeAbove = spaceBelow < MIN_COMFORTABLE_HEIGHT && spaceAbove > spaceBelow
    const maxHeight = Math.max(80, Math.min(
      MAX_DROPDOWN_HEIGHT,
      placeAbove ? spaceAbove : spaceBelow,
    ))

    setPosition({
      position: 'fixed',
      left,
      width,
      maxHeight,
      top: placeAbove ? undefined : rect.bottom + DROPDOWN_GAP,
      bottom: placeAbove ? window.innerHeight - rect.top + DROPDOWN_GAP : undefined,
    })
  }, [onOpenChange])

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null)
      return
    }
    updatePosition()
  }, [open, query, updatePosition])

  useEffect(() => {
    if (!open) return

    let animationFrame = 0
    const scheduleUpdate = () => {
      window.cancelAnimationFrame(animationFrame)
      animationFrame = window.requestAnimationFrame(updatePosition)
    }
    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(scheduleUpdate)

    if (inputRef.current) resizeObserver?.observe(inputRef.current)
    window.addEventListener('resize', scheduleUpdate)
    window.addEventListener('scroll', scheduleUpdate, true)

    return () => {
      window.cancelAnimationFrame(animationFrame)
      resizeObserver?.disconnect()
      window.removeEventListener('resize', scheduleUpdate)
      window.removeEventListener('scroll', scheduleUpdate, true)
    }
  }, [open, updatePosition])

  const dropdown = open && typeof document !== 'undefined'
    ? createPortal(
        <div
          ref={dropdownRef}
          className={styles.dropdown}
          id={`req-poste-options-${groupId}`}
          role={options.length > 0 ? 'tree' : 'status'}
          aria-label={`Postes disponibles pour le groupe ${groupIndex + 1}`}
          data-budget-tree={groupId}
          data-tree-scroll
          data-placement={position?.bottom === undefined ? 'bottom' : 'top'}
          style={position ?? { position: 'fixed', visibility: 'hidden' }}
          onMouseDown={(event) => event.preventDefault()}
          onBlur={(event) => {
            const next = event.relatedTarget as Node | null
            if (!next || !event.currentTarget.contains(next)) onOpenChange(false)
          }}
        >
          {options.length > 0 ? options : (
            <div className={styles.dropdownEmpty}>Aucun poste trouvé pour cette recherche.</div>
          )}
        </div>,
        document.body,
      )
    : null

  return (
    <div className={styles.budgetInputWrap}>
      <span className={styles.budgetInputIcon}><Search size={14} aria-hidden="true" /></span>
      <input
        ref={inputRef}
        className={styles.budgetInput}
        id={`req-poste-${groupId}`}
        type="text"
        value={query}
        aria-required="true"
        role="combobox"
        aria-autocomplete="list"
        aria-haspopup="tree"
        aria-expanded={open}
        aria-controls={`req-poste-options-${groupId}`}
        onChange={(event) => onSearch(event.target.value)}
        onFocus={() => {
          onActivate()
          onOpenChange(true)
        }}
        onBlur={(event) => {
          const next = event.relatedTarget as Node | null
          if (next && dropdownRef.current?.contains(next)) return
          window.setTimeout(() => {
            const activeElement = document.activeElement
            if (activeElement && dropdownRef.current?.contains(activeElement)) return
            onOpenChange(false)
          }, 120)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            onOpenChange(false)
          } else if (event.key === 'ArrowDown' && open) {
            event.preventDefault()
            dropdownRef.current?.querySelector<HTMLButtonElement>('[data-budget-option]')?.focus()
          }
        }}
        placeholder="Code ou libellé du poste"
      />
      {dropdown}
    </div>
  )
}

export default function RequisitionExpenseEditor({
  groups,
  activeGroupId,
  onActiveGroupChange,
  budgetLinesById,
  budgetLineCount,
  copiedRequisition,
  perLinePayment,
  accounts,
  globalPaymentMode,
  exchangeRate,
  alertThreshold,
  blockOverrun,
  formatCurrency,
  toUsd,
  subtotalUsd,
  totalUsd,
  renderBudgetOptions,
  onSearchBudget,
  onDropdownChange,
  onRemoveGroup,
  onAddGroup,
  onUpdateLine,
  onChangeLinePayment,
  onRemoveLine,
  onAddLine,
  paymentLabel,
  footer,
}: ExpenseEditorProps) {
  const lineCount = groups.reduce((sum, group) => sum + group.lignes.length, 0)

  return (
    <RequisitionSection
      id="req-section-lignes"
      number={5}
      title="Lignes de dépense"
      description="Regroupez les dépenses par poste budgétaire et décrivez précisément chaque besoin."
      action={(
        <span className={styles.sectionHeaderAction} aria-live="polite">
          {groups.length} poste{groups.length > 1 ? 's' : ''} · {lineCount} ligne{lineCount > 1 ? 's' : ''}
        </span>
      )}
    >
      <div className={styles.groups}>
        {groups.map((group, groupIndex) => {
          const budgetLine = group.budget_poste_id ? budgetLinesById.get(Number(group.budget_poste_id)) : null
          const query = group.budgetSearch || ''
          const options = renderBudgetOptions(group.id, query)
          const subtotal = subtotalUsd(group)
          const available = Number(budgetLine?.montant_disponible || 0)
          const after = budgetLine ? available - subtotal : 0
          const consumption = budgetLine?.montant_prevu
            ? ((Number(budgetLine.montant_engage || 0) + subtotal) / Number(budgetLine.montant_prevu)) * 100
            : 0
          const overrun = Boolean(budgetLine && subtotal > available)

          return (
            <div
              key={group.id}
              className={styles.groupCard}
              data-active={group.id === activeGroupId}
              data-overrun={overrun}
              onFocusCapture={() => onActiveGroupChange(group.id)}
              role="group"
              aria-labelledby={`req-poste-title-${group.id}`}
            >
              <div className={styles.groupHeader}>
                <div className={styles.groupIdentity}>
                  <span className={styles.groupEyebrow}>Poste budgétaire {String(groupIndex + 1).padStart(2, '0')}</span>
                  <strong className={styles.groupTitle} id={`req-poste-title-${group.id}`}>
                    {budgetLine ? `${budgetLine.code} — ${budgetLine.libelle}` : copiedRequisition && group.budget_poste_id != null && budgetLineCount > 0 ? (
                      <span className={styles.unavailable}><AlertTriangle size={12} /> Poste fermé — à remplacer</span>
                    ) : 'Imputation à sélectionner'}
                  </strong>
                </div>
                {groups.length > 1 && (
                  <button
                    type="button"
                    className={styles.removeGroup}
                    onClick={() => onRemoveGroup(group.id)}
                    aria-label={`Supprimer le poste budgétaire ${groupIndex + 1}`}
                    title="Supprimer ce poste budgétaire"
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                )}
              </div>

              <div className={styles.groupConfig}>
                <div className={styles.budgetField}>
                  <label htmlFor={`req-poste-${group.id}`}>Rechercher un poste budgétaire *</label>
                  <BudgetPosteSearch
                    groupId={group.id}
                    groupIndex={groupIndex}
                    query={query}
                    open={group.showBudgetDropdown}
                    options={options}
                    onSearch={(value) => onSearchBudget(group.id, value)}
                    onOpenChange={(open) => onDropdownChange(group.id, open)}
                    onActivate={() => onActiveGroupChange(group.id)}
                  />
                  {budgetLineCount === 0 && (
                    <small className={styles.fieldHint}>Aucun poste disponible pour le service sélectionné.</small>
                  )}
                </div>

                {budgetLine ? (
                  <div className={styles.budgetMetrics} aria-label="Situation du poste">
                    <span className={styles.budgetMetric}>
                      <small>Disponible</small>
                      <strong>{formatCurrency(available)}</strong>
                    </span>
                    <span className={styles.budgetMetric}>
                      <small>Sous-total saisi</small>
                      <strong>{formatCurrency(subtotal)}</strong>
                    </span>
                    <span className={styles.budgetMetric} data-negative={after < 0} data-positive={after >= 0}>
                      <small>Solde après demande</small>
                      <strong>{formatCurrency(after)}</strong>
                    </span>
                  </div>
                ) : <div />}
              </div>

              {budgetLine && consumption >= alertThreshold && consumption < 100 && (
                <div className={styles.budgetNotice} role="status">
                  <AlertTriangle size={13} aria-hidden="true" /> Seuil d’alerte de {alertThreshold} % atteint.
                </div>
              )}
              {overrun && (
                <div className={styles.budgetNotice} data-danger="true" role="alert">
                  <AlertTriangle size={13} aria-hidden="true" />
                  {blockOverrun ? 'Blocage' : 'Dépassement'} : le sous-total dépasse le disponible de {formatCurrency(Math.abs(after))}.
                </div>
              )}

              <div className={styles.tableWrap}>
                <table className={styles.expenseTable} data-split={perLinePayment}>
                  <thead>
                    <tr>
                      <th scope="col" className={`${styles.descriptionCell} ${styles.descriptionHead}`}>
                        Description * <span>champ principal</span>
                      </th>
                      <th scope="col" className={styles.quantityCell}>Quantité *</th>
                      <th scope="col" className={styles.currencyCell}>Devise</th>
                      <th scope="col" className={styles.unitPriceCell}>Prix unitaire *</th>
                      {perLinePayment && <th scope="col" className={styles.paymentCell}>Règlement</th>}
                      <th scope="col" className={styles.totalCell}>Total (USD)</th>
                      <th scope="col" className={styles.actionCell}><span className={styles.srOnly}>Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.lignes.map((line, lineIndex) => (
                      <tr key={line.id}>
                        <td className={styles.descriptionCell} data-label="Description">
                          <label className={styles.lineNumber} htmlFor={`req-ligne-description-${line.id}`}>
                            Dépense {lineIndex + 1}
                          </label>
                          <textarea
                            id={`req-ligne-description-${line.id}`}
                            rows={2}
                            value={line.description}
                            aria-label={`Description de la dépense ${lineIndex + 1} du poste ${groupIndex + 1}`}
                            placeholder="Décrivez précisément le bien, le service ou le besoin…"
                            onChange={(event) => onUpdateLine(group.id, line.id, 'description', event.target.value)}
                            required
                          />
                        </td>
                        <td className={styles.quantityCell} data-label="Quantité">
                          <input
                            type="number"
                            value={line.quantite}
                            min="1"
                            inputMode="numeric"
                            aria-label={`Quantité de la dépense ${lineIndex + 1}`}
                            onChange={(event) => onUpdateLine(group.id, line.id, 'quantite', parseInt(event.target.value) || 0)}
                            required
                          />
                        </td>
                        <td className={styles.currencyCell} data-label="Devise">
                          <select
                            value={line.devise || 'USD'}
                            aria-label={`Devise de la dépense ${lineIndex + 1}`}
                            onChange={(event) => onUpdateLine(group.id, line.id, 'devise', event.target.value)}
                          >
                            <option value="USD">USD</option>
                            <option value="CDF">CDF</option>
                          </select>
                        </td>
                        <td className={styles.unitPriceCell} data-label="Prix unitaire">
                          <div className={styles.inlineInput}>
                            <input
                              type="number"
                              step="0.01"
                              min="0.01"
                              inputMode="decimal"
                              value={line.montant_unitaire}
                              aria-label={`Prix unitaire de la dépense ${lineIndex + 1}`}
                              onChange={(event) => onUpdateLine(group.id, line.id, 'montant_unitaire', parseFloat(event.target.value) || 0)}
                              onFocus={(event) => {
                                if (Number(line.montant_unitaire || 0) === 0) event.currentTarget.select()
                              }}
                              required
                            />
                            {line.devise === 'CDF' && exchangeRate > 0 && (
                              <button
                                type="button"
                                className={styles.convertButton}
                                onClick={() => {
                                  const usd = toUsd(line.montant_unitaire, 'CDF')
                                  onUpdateLine(group.id, line.id, 'devise', 'USD')
                                  onUpdateLine(group.id, line.id, 'montant_unitaire', Number(usd.toFixed(2)))
                                }}
                              >
                                Convertir en USD
                              </button>
                            )}
                            {line.devise === 'CDF' && exchangeRate === 0 && (
                              <small className={styles.fieldHint}>Taux non défini</small>
                            )}
                          </div>
                        </td>

                        {perLinePayment && (
                          <td className={styles.paymentCell} data-label="Règlement">
                            <div className={styles.linePayment}>
                              <select
                                value={line.mode_paiement ?? ''}
                                aria-label={`Règlement de la dépense ${lineIndex + 1}`}
                                onChange={(event) => onChangeLinePayment(group.id, line.id, event.target.value as '' | 'cash' | 'virement')}
                              >
                                <option value="">Global · {paymentLabel(globalPaymentMode)}</option>
                                <option value="cash">Caisse</option>
                                <option value="virement">Banque</option>
                              </select>
                              {line.mode_paiement === 'virement' && (
                                <select
                                  value={line.compte_bancaire_id ?? ''}
                                  aria-label={`Compte bancaire de la dépense ${lineIndex + 1}`}
                                  onChange={(event) => onUpdateLine(
                                    group.id,
                                    line.id,
                                    'compte_bancaire_id',
                                    event.target.value ? Number(event.target.value) : null,
                                  )}
                                  required
                                >
                                  <option value="">Compte bancaire…</option>
                                  {accounts.map((account) => (
                                    <option key={account.id} value={account.id}>
                                      {(account.banque?.nom || 'Banque')} - {account.intitule} ({account.devise})
                                    </option>
                                  ))}
                                </select>
                              )}
                            </div>
                          </td>
                        )}

                        <td className={styles.totalCell} data-label="Total (USD)">
                          {formatCurrency(line.devise === 'CDF' ? toUsd(line.montant_total, 'CDF') : Number(line.montant_total || 0))}
                        </td>
                        <td className={styles.actionCell} data-label="">
                          <button
                            type="button"
                            className={styles.removeLine}
                            onClick={() => onRemoveLine(group.id, line.id)}
                            disabled={groups.length === 1 && group.lignes.length === 1}
                            aria-label={`Supprimer la dépense ${lineIndex + 1}`}
                            title="Supprimer cette dépense"
                          >
                            <Trash2 size={14} aria-hidden="true" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className={styles.addLineRow}>
                      <td colSpan={perLinePayment ? 7 : 6}>
                        <button type="button" className={styles.addLineButton} onClick={() => onAddLine(group.id)}>
                          <Plus size={14} aria-hidden="true" /> Ajouter une dépense à ce poste
                        </button>
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )
        })}

        <button type="button" className={styles.addGroupButton} onClick={onAddGroup}>
          <Plus size={15} aria-hidden="true" /> Ajouter un poste budgétaire
        </button>

        <div className={styles.grandTotal}>
          <span className={styles.grandTotalLabel}>
            Total de la réquisition
            {exchangeRate > 0 && (
              <small>
                Équivalent CDF {new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(totalUsd * exchangeRate)}
              </small>
            )}
          </span>
          <strong>{formatCurrency(totalUsd)}</strong>
        </div>
      </div>
      {footer && <div className={styles.footerContent}>{footer}</div>}
    </RequisitionSection>
  )
}
