/**
 * Factures émises aux tenants — console Eclectic IT Services.
 *
 * L'écran couvre le cycle complet d'une facture : émission, envoi, règlement,
 * annulation. Le règlement se constate ici lorsqu'il a lieu hors plateforme
 * (virement, mobile money, espèces) ; un paiement en ligne, lui, solde la
 * facture tout seul côté serveur — d'où l'absence de bouton « encaisser en
 * ligne » : ce n'est pas à l'éditeur de le déclencher.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Ban,
  Download,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Wallet,
} from 'lucide-react'
import {
  cancelSaasInvoice,
  createSaasInvoice,
  listSaasInvoices,
  markSaasInvoicePaid,
  saasInvoicePdfPath,
  sendSaasInvoice,
  type InvoiceLine,
  type InvoiceStatus,
  type SaaSInvoice,
  type SuperAdminOrganisation,
} from '../../api/superAdmin'
import { downloadAuthenticatedFile } from '../../utils/download'
import { useConfirm } from '../../contexts/ConfirmContext'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './Invoicing.module.css'

type TenantInvoicesProps = {
  organisations: SuperAdminOrganisation[]
}

type DraftLine = { designation: string; quantite: string; prix_unitaire: string }

const STATUS_LABELS: Record<InvoiceStatus, string> = {
  DRAFT: 'Brouillon',
  ISSUED: 'En attente',
  PAID: 'Payée',
  CANCELLED: 'Annulée',
}

const STATUS_CLASSES: Record<InvoiceStatus, string> = {
  DRAFT: styles.badgeDraft,
  ISSUED: styles.badgeIssued,
  PAID: styles.badgePaid,
  CANCELLED: styles.badgeCancelled,
}

const PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: 'BANK_TRANSFER', label: 'Virement bancaire' },
  { value: 'MOBILE_MONEY', label: 'Mobile money' },
  { value: 'CASH', label: 'Espèces' },
  { value: 'CHECK', label: 'Chèque' },
  { value: 'OTHER', label: 'Autre' },
]

const EMPTY_LINE: DraftLine = { designation: '', quantite: '1', prix_unitaire: '' }

function toNumber(value: string): number {
  const parsed = Number(String(value).replace(',', '.'))
  return Number.isFinite(parsed) ? parsed : 0
}

function formatMoney(amount: number, currency: string): string {
  return `${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)} ${currency}`
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('fr-FR')
}

/** `YYYY-MM-DD` (valeur d'un <input type="date">) → ISO UTC, ou null. */
function dateToIso(value: string): string | null {
  if (!value) return null
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export default function TenantInvoices({ organisations }: TenantInvoicesProps) {
  const { showSuccess, showError, showWarning, showInfo } = useNotification()
  const confirm = useConfirm()

  const [invoices, setInvoices] = useState<SaaSInvoice[]>([])
  const [totalsByStatus, setTotalsByStatus] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const [filterOrg, setFilterOrg] = useState<string>('')
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [search, setSearch] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [payFor, setPayFor] = useState<SaaSInvoice | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listSaasInvoices({
        organisationId: filterOrg ? Number(filterOrg) : null,
        status: filterStatus || null,
        search: search.trim() || null,
      })
      setInvoices(res.items || [])
      setTotalsByStatus(res.totals_by_status || {})
    } catch (err: any) {
      showError('Chargement impossible', err?.message || 'Les factures n’ont pas pu être chargées.')
    } finally {
      setLoading(false)
    }
  }, [filterOrg, filterStatus, search, showError])

  useEffect(() => {
    void load()
  }, [load])

  const summary = useMemo(() => {
    const open = invoices.filter((i) => i.status === 'ISSUED')
    const overdue = open.filter((i) => i.is_overdue)
    const sum = (rows: SaaSInvoice[]) => rows.reduce((acc, row) => acc + (row.amount || 0), 0)
    return {
      encaisse: totalsByStatus.PAID || 0,
      attente: sum(open),
      attenteCount: open.length,
      retard: sum(overdue),
      retardCount: overdue.length,
    }
  }, [invoices, totalsByStatus])

  const handleDownload = async (invoice: SaaSInvoice) => {
    setBusyId(invoice.id)
    try {
      await downloadAuthenticatedFile(saasInvoicePdfPath(invoice.id), `${invoice.invoice_number}.pdf`)
    } catch (err: any) {
      showError('Téléchargement impossible', err?.message || 'Le PDF n’a pas pu être récupéré.')
    } finally {
      setBusyId(null)
    }
  }

  const handleSend = async (invoice: SaaSInvoice) => {
    setBusyId(invoice.id)
    try {
      const res = await sendSaasInvoice(invoice.id)
      if (res.ok) {
        showSuccess('Facture envoyée', `${invoice.invoice_number} → ${res.sent_to.join(', ')}`)
      } else {
        // Un envoi qui échoue n'est pas une erreur de l'utilisateur : le motif
        // (SMTP absent, aucun destinataire) est actionnable, on le restitue tel quel.
        showWarning('Envoi non abouti', res.detail || 'La facture n’a pas pu être envoyée.')
      }
      await load()
    } catch (err: any) {
      showError('Envoi impossible', err?.message || 'L’envoi a échoué.')
    } finally {
      setBusyId(null)
    }
  }

  const handleCancel = async (invoice: SaaSInvoice) => {
    const ok = await confirm({
      title: 'Annuler cette facture ?',
      description: `${invoice.invoice_number} — ${formatMoney(invoice.amount, invoice.currency)}. La facture restera visible, marquée annulée.`,
      confirmText: 'Annuler la facture',
      variant: 'danger',
    })
    if (!ok) return
    setBusyId(invoice.id)
    try {
      await cancelSaasInvoice(invoice.id)
      showSuccess('Facture annulée', invoice.invoice_number)
      await load()
    } catch (err: any) {
      showError('Annulation impossible', err?.message || 'La facture n’a pas pu être annulée.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.summary}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Encaissé</span>
          <span className={styles.summaryValue}>{formatMoney(summary.encaisse, 'USD')}</span>
          <span className={styles.summaryHint}>factures réglées, sélection courante</span>
        </div>
        <div className={`${styles.summaryCard} ${styles.summaryDue}`}>
          <span className={styles.summaryLabel}>En attente</span>
          <span className={styles.summaryValue}>{formatMoney(summary.attente, 'USD')}</span>
          <span className={styles.summaryHint}>{summary.attenteCount} facture(s) émise(s)</span>
        </div>
        <div className={`${styles.summaryCard} ${styles.summaryOverdue}`}>
          <span className={styles.summaryLabel}>En retard</span>
          <span className={styles.summaryValue}>{formatMoney(summary.retard, 'USD')}</span>
          <span className={styles.summaryHint}>{summary.retardCount} échéance(s) dépassée(s)</span>
        </div>
        <div className={`${styles.summaryCard} ${styles.summaryPaid}`}>
          <span className={styles.summaryLabel}>Tenants facturés</span>
          <span className={styles.summaryValue}>
            {new Set(invoices.map((i) => i.organisation_id)).size}
          </span>
          <span className={styles.summaryHint}>sur {organisations.length} organisation(s)</span>
        </div>
      </div>

      <div className={styles.toolbar}>
        <label className={styles.field}>
          Tenant
          <select value={filterOrg} onChange={(e) => setFilterOrg(e.target.value)}>
            <option value="">Tous</option>
            {organisations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.nom}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Statut
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">Tous</option>
            <option value="OPEN">Ouvertes (brouillon + en attente)</option>
            <option value="DRAFT">Brouillon</option>
            <option value="ISSUED">En attente de paiement</option>
            <option value="PAID">Payées</option>
            <option value="CANCELLED">Annulées</option>
          </select>
        </label>
        <label className={styles.field}>
          Numéro
          <input
            type="search"
            value={search}
            placeholder="EIS-2026-…"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className={styles.toolbarSpacer} />
        <button className={styles.iconBtn} onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} className={loading ? styles.spin : undefined} />
          Actualiser
        </button>
        <button className={`${styles.iconBtn} ${styles.iconBtnPrimary}`} onClick={() => setCreateOpen(true)}>
          <Plus size={14} />
          Nouvelle facture
        </button>
      </div>

      <div className={styles.tableWrap}>
        {loading ? (
          <div className={styles.empty}>Chargement des factures…</div>
        ) : invoices.length === 0 ? (
          <div className={styles.empty}>
            Aucune facture pour cette sélection. Utilisez « Nouvelle facture » pour en émettre une.
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Numéro</th>
                <th>Tenant</th>
                <th>Émise le</th>
                <th>Échéance</th>
                <th className={styles.numeric}>Montant</th>
                <th>Statut</th>
                <th>Règlement</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => {
                const busy = busyId === invoice.id
                return (
                  <tr key={invoice.id}>
                    <td className={styles.numberCell}>{invoice.invoice_number}</td>
                    <td>
                      <div className={styles.tenantCell}>
                        <span>{invoice.organisation_name || `#${invoice.organisation_id}`}</span>
                        {invoice.organisation_slug && (
                          <span className={styles.tenantSlug}>{invoice.organisation_slug}</span>
                        )}
                      </div>
                    </td>
                    <td>{formatDate(invoice.issue_date)}</td>
                    <td>
                      {formatDate(invoice.due_date)}
                      {invoice.is_overdue && <span className={styles.overdueFlag}>en retard</span>}
                    </td>
                    <td className={`${styles.numeric} ${styles.strong}`}>
                      {formatMoney(invoice.amount, invoice.currency)}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${STATUS_CLASSES[invoice.status]}`}>
                        {STATUS_LABELS[invoice.status]}
                      </span>
                    </td>
                    <td>
                      {invoice.status === 'PAID'
                        ? `${invoice.payment_method_label || '—'}${invoice.payment_reference ? ` · ${invoice.payment_reference}` : ''}`
                        : invoice.sent_at
                          ? `Envoyée le ${formatDate(invoice.sent_at)}`
                          : '—'}
                    </td>
                    <td>
                      <div className={styles.rowActions}>
                        <button
                          className={styles.iconBtn}
                          onClick={() => void handleDownload(invoice)}
                          disabled={busy}
                          title="Télécharger le PDF"
                        >
                          {busy ? <Loader2 size={14} className={styles.spin} /> : <Download size={14} />}
                        </button>
                        <button
                          className={styles.iconBtn}
                          onClick={() => void handleSend(invoice)}
                          disabled={busy || invoice.status === 'DRAFT' || invoice.status === 'CANCELLED'}
                          title={
                            invoice.status === 'DRAFT'
                              ? 'Un brouillon ne s’envoie pas'
                              : 'Envoyer par email aux administrateurs du tenant'
                          }
                        >
                          <Send size={14} />
                        </button>
                        <button
                          className={`${styles.iconBtn} ${styles.iconBtnPrimary}`}
                          onClick={() => setPayFor(invoice)}
                          disabled={busy || invoice.status === 'PAID' || invoice.status === 'CANCELLED'}
                          title="Constater un règlement manuel"
                        >
                          <Wallet size={14} />
                          Régler
                        </button>
                        <button
                          className={`${styles.iconBtn} ${styles.iconBtnDanger}`}
                          onClick={() => void handleCancel(invoice)}
                          disabled={busy || invoice.status === 'PAID' || invoice.status === 'CANCELLED'}
                          title="Annuler la facture"
                        >
                          <Ban size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {createOpen && (
        <CreateInvoiceModal
          organisations={organisations}
          onClose={() => setCreateOpen(false)}
          onCreated={async (message) => {
            setCreateOpen(false)
            showSuccess('Facture créée', message)
            await load()
          }}
          onError={(title, message) => showError(title, message)}
          onInfo={(title, message) => showInfo(title, message)}
        />
      )}

      {payFor && (
        <MarkPaidModal
          invoice={payFor}
          onClose={() => setPayFor(null)}
          onDone={async (message) => {
            setPayFor(null)
            showSuccess('Règlement enregistré', message)
            await load()
          }}
          onError={(title, message) => showError(title, message)}
        />
      )}
    </div>
  )
}

/* ── Modale : nouvelle facture ─────────────────────────────────────────────── */

type CreateProps = {
  organisations: SuperAdminOrganisation[]
  onClose: () => void
  onCreated: (message: string) => Promise<void> | void
  onError: (title: string, message: string) => void
  onInfo: (title: string, message: string) => void
}

function CreateInvoiceModal({ organisations, onClose, onCreated, onError }: CreateProps) {
  const [orgId, setOrgId] = useState<string>(organisations[0] ? String(organisations[0].id) : '')
  const [currency, setCurrency] = useState('USD')
  const [periodStart, setPeriodStart] = useState('')
  const [periodEnd, setPeriodEnd] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [notes, setNotes] = useState('')
  const [issue, setIssue] = useState(true)
  const [sendEmail, setSendEmail] = useState(false)
  const [lines, setLines] = useState<DraftLine[]>([{ ...EMPTY_LINE }])
  const [saving, setSaving] = useState(false)

  const total = useMemo(
    () => lines.reduce((acc, line) => acc + toNumber(line.quantite) * toNumber(line.prix_unitaire), 0),
    [lines],
  )

  const patchLine = (index: number, patch: Partial<DraftLine>) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)))
  }

  const submit = async () => {
    if (!orgId) {
      onError('Tenant manquant', 'Choisissez l’organisation à facturer.')
      return
    }
    const payloadLines: InvoiceLine[] = lines
      .filter((line) => line.designation.trim())
      .map((line) => ({
        designation: line.designation.trim(),
        quantite: toNumber(line.quantite),
        prix_unitaire: toNumber(line.prix_unitaire),
      }))
    if (payloadLines.length === 0) {
      onError('Aucune ligne', 'Renseignez au moins une désignation.')
      return
    }
    if (payloadLines.some((line) => line.quantite <= 0)) {
      onError('Quantité invalide', 'Chaque ligne doit porter une quantité strictement positive.')
      return
    }
    if (total <= 0) {
      onError('Montant nul', 'Le total de la facture doit être strictement positif.')
      return
    }

    setSaving(true)
    try {
      const created = await createSaasInvoice({
        organisation_id: Number(orgId),
        lines: payloadLines,
        currency,
        period_start: dateToIso(periodStart),
        period_end: dateToIso(periodEnd),
        due_date: dateToIso(dueDate),
        notes: notes.trim() || null,
        issue,
        send_email: sendEmail && issue,
      })
      await onCreated(
        `${created.invoice_number} — ${formatMoney(created.amount, created.currency)}${
          created.sent_at ? ' (envoyée)' : ''
        }`,
      )
    } catch (err: any) {
      onError('Création impossible', err?.payload?.detail || err?.message || 'La facture n’a pas pu être créée.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <div className={styles.modalHead}>
          <div>
            <h3 className={styles.modalTitle}>Nouvelle facture</h3>
            <p className={styles.modalSub}>
              Émise par Eclectic IT Services au nom du tenant sélectionné.
            </p>
          </div>
          <button className={styles.iconBtn} onClick={onClose} disabled={saving}>
            Fermer
          </button>
        </div>

        <div className={styles.modalBody}>
          <div className={styles.grid3}>
            <label className={styles.field}>
              Tenant *
              <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                {organisations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.nom}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              Devise
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
                <option value="EUR">EUR</option>
              </select>
            </label>
            <label className={styles.field}>
              Échéance
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </label>
            <label className={styles.field}>
              Période — début
              <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
            </label>
            <label className={styles.field}>
              Période — fin
              <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
            </label>
          </div>

          <div>
            <div className={styles.fieldsetTitle}>Lignes facturées</div>
            <div className={styles.linesHead} style={{ marginTop: 10 }}>
              <span>Désignation</span>
              <span>Quantité</span>
              <span>Prix unitaire</span>
              <span style={{ textAlign: 'right' }}>Montant</span>
              <span />
            </div>
            {lines.map((line, index) => (
              <div key={index} className={styles.lineRow} style={{ marginTop: 8 }}>
                <input
                  value={line.designation}
                  placeholder="Abonnement PRO — septembre 2026"
                  onChange={(e) => patchLine(index, { designation: e.target.value })}
                />
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={line.quantite}
                  onChange={(e) => patchLine(index, { quantite: e.target.value })}
                />
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={line.prix_unitaire}
                  placeholder="0.00"
                  onChange={(e) => patchLine(index, { prix_unitaire: e.target.value })}
                />
                <span className={styles.lineAmount}>
                  {formatMoney(toNumber(line.quantite) * toNumber(line.prix_unitaire), currency)}
                </span>
                <button
                  className={styles.lineRemove}
                  onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}
                  disabled={lines.length === 1}
                  title="Retirer la ligne"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
            <div className={styles.linesFoot} style={{ marginTop: 12 }}>
              <button className={styles.iconBtn} onClick={() => setLines((prev) => [...prev, { ...EMPTY_LINE }])}>
                <Plus size={14} />
                Ajouter une ligne
              </button>
              <div>
                <span className={styles.totalLabel}>Total&nbsp;</span>
                <span className={styles.totalValue}>{formatMoney(total, currency)}</span>
              </div>
            </div>
          </div>

          <label className={styles.field}>
            Note (imprimée sur la facture)
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={400} />
          </label>

          <div className={styles.notice}>
            <FileText size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              <strong>Brouillon</strong> : la facture reste interne, ni envoyée ni payable.{' '}
              <strong>Émise</strong> : elle prend un numéro définitif, apparaît chez le tenant et peut
              être réglée — en ligne par le tenant, ou manuellement puis constatée ici. Les modalités
              affichées sur le PDF se règlent dans l&apos;onglet « Émetteur ».
            </span>
          </div>

          <div className={styles.grid2}>
            <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={issue} onChange={(e) => setIssue(e.target.checked)} style={{ width: 'auto' }} />
              Émettre immédiatement
            </label>
            <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                checked={sendEmail}
                disabled={!issue}
                onChange={(e) => setSendEmail(e.target.checked)}
                style={{ width: 'auto' }}
              />
              Envoyer par email au tenant
            </label>
          </div>
        </div>

        <div className={styles.modalFoot}>
          <button className={styles.iconBtn} onClick={onClose} disabled={saving}>
            Annuler
          </button>
          <button className={`${styles.iconBtn} ${styles.iconBtnPrimary}`} onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 size={14} className={styles.spin} /> : <FileText size={14} />}
            {issue ? 'Émettre la facture' : 'Enregistrer le brouillon'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Modale : constater un règlement manuel ────────────────────────────────── */

type MarkPaidProps = {
  invoice: SaaSInvoice
  onClose: () => void
  onDone: (message: string) => Promise<void> | void
  onError: (title: string, message: string) => void
}

function MarkPaidModal({ invoice, onClose, onDone, onError }: MarkPaidProps) {
  const [method, setMethod] = useState('BANK_TRANSFER')
  const [reference, setReference] = useState('')
  const [paidAt, setPaidAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      await markSaasInvoicePaid(invoice.id, {
        method,
        reference: reference.trim() || null,
        paid_at: dateToIso(paidAt),
      })
      await onDone(`${invoice.invoice_number} — ${formatMoney(invoice.amount, invoice.currency)}`)
    } catch (err: any) {
      onError('Enregistrement impossible', err?.payload?.detail || err?.message || 'Le règlement n’a pas pu être enregistré.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal} style={{ width: 'min(520px, 100%)' }}>
        <div className={styles.modalHead}>
          <div>
            <h3 className={styles.modalTitle}>Constater un règlement</h3>
            <p className={styles.modalSub}>
              {invoice.invoice_number} · {invoice.organisation_name} ·{' '}
              {formatMoney(invoice.amount, invoice.currency)}
            </p>
          </div>
        </div>

        <div className={styles.modalBody}>
          <div className={`${styles.notice} ${styles.noticeWarn}`}>
            <Wallet size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              À réserver aux paiements reçus <strong>hors plateforme</strong>. Un règlement en ligne
              solde la facture automatiquement : nul besoin de le saisir ici.
            </span>
          </div>

          <label className={styles.field}>
            Moyen de paiement *
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              {PAYMENT_METHODS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            Référence (bordereau, transaction…)
            <input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={160} />
          </label>
          <label className={styles.field}>
            Date du règlement
            <input type="date" value={paidAt} onChange={(e) => setPaidAt(e.target.value)} />
          </label>
        </div>

        <div className={styles.modalFoot}>
          <button className={styles.iconBtn} onClick={onClose} disabled={saving}>
            Annuler
          </button>
          <button className={`${styles.iconBtn} ${styles.iconBtnPrimary}`} onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 size={14} className={styles.spin} /> : <Wallet size={14} />}
            Enregistrer le règlement
          </button>
        </div>
      </div>
    </div>
  )
}
