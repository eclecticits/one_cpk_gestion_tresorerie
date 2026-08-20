import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  createCheckoutSession,
  downloadBillingInvoicePdf,
  exportBillingPaymentLogs,
  getBillingConfig,
  getBillingSummary,
  initiateBillingPayment,
  listBillingInvoices,
  listBillingPaymentLogs,
  type BillingConfig,
  type BillingInvoice,
  type BillingPaymentLog,
  type BillingSummary,
} from '../../api/billing'
import { useAuth } from '../../contexts/AuthContext'
import { useNotification } from '../../contexts/NotificationContext'
import billingStyles from '../../pages/Settings.module.css'

const PAID_INVOICE_STATUSES = ['paid', 'payee', 'payée', 'settled']
const DUE_INVOICE_STATUSES = ['pending', 'unpaid', 'past_due', 'due']

export default function BillingPanel() {
  const location = useLocation()
  const { user } = useAuth()
  const { showError, showSuccess, showWarning } = useNotification()

  const [billingSubTab, setBillingSubTab] = useState<'overview' | 'logs'>('overview')
  const [billingSummary, setBillingSummary] = useState<BillingSummary | null>(null)
  const [billingInvoices, setBillingInvoices] = useState<BillingInvoice[]>([])
  const [billingLoading, setBillingLoading] = useState(false)
  const [billingError, setBillingError] = useState<string | null>(null)
  const [billingInvoicesConfigured, setBillingInvoicesConfigured] = useState(true)
  const [billingCheckoutLoading, setBillingCheckoutLoading] = useState(false)
  const [billingConfig, setBillingConfig] = useState<BillingConfig | null>(null)
  const [billingConfigLoading, setBillingConfigLoading] = useState(false)
  const [billingLogs, setBillingLogs] = useState<BillingPaymentLog[]>([])
  const [billingLogsLoading, setBillingLogsLoading] = useState(false)
  const [billingLogsTotal, setBillingLogsTotal] = useState(0)
  const [billingLogsStatus, setBillingLogsStatus] = useState('')
  const [billingLogsProvider, setBillingLogsProvider] = useState('')
  const [billingLogsPhone, setBillingLogsPhone] = useState('')
  const [billingLogsPage, setBillingLogsPage] = useState(1)
  const [momoPhone, setMomoPhone] = useState('')
  const [momoProvider, setMomoProvider] = useState('mobile_money')
  const [momoLoading, setMomoLoading] = useState(false)
  const [referenceCopied, setReferenceCopied] = useState(false)
  const billingLogsPageSize = 25
  const billingInvoicesRef = useRef<BillingInvoice[]>([])
  const invoicePollRef = useRef<number | null>(null)
  const invoicePollAttemptsRef = useRef(0)
  const paymentMethodsRef = useRef<HTMLDivElement | null>(null)

  const scrollToPaymentMethods = () => {
    paymentMethodsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const formatBillingDate = (value?: string | null) => {
    if (!value) return '—'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleDateString('fr-FR')
  }

  const formatBillingAmount = (amount: number | null | undefined, currency?: string | null) => {
    if (amount == null) return '—'
    const code = currency || 'USD'
    try {
      return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: code }).format(amount)
    } catch {
      return `${amount} ${code}`
    }
  }

  // Nombre de jours (calendaires) entre aujourd'hui et l'échéance. Négatif = dépassée.
  const getDaysUntil = (value?: string | null) => {
    if (!value) return null
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return null
    const startOfToday = new Date()
    startOfToday.setHours(0, 0, 0, 0)
    const startOfTarget = new Date(parsed)
    startOfTarget.setHours(0, 0, 0, 0)
    return Math.round((startOfTarget.getTime() - startOfToday.getTime()) / 86400000)
  }

  const formatCountdown = (days: number | null) => {
    if (days === null) return null
    if (days < 0) return `Dépassée de ${Math.abs(days)} jour${Math.abs(days) > 1 ? 's' : ''}`
    if (days === 0) return "Aujourd'hui"
    if (days === 1) return 'Demain'
    return `Dans ${days} jours`
  }

  const getPlanStatusLabel = (status?: string | null) => {
    const normalized = (status || '').toUpperCase()
    const labels: Record<string, string> = {
      ACTIVE: 'Actif',
      TRIAL: 'Essai',
      SUSPENDED: 'Suspendu',
      EXPIRED: 'Expiré',
      CANCELED: 'Résilié',
      PAST_DUE: 'En retard',
      PENDING_ACTIVATION: 'En attente',
    }
    return labels[normalized] || (status ? status : '—')
  }

  const getInvoiceStatusLabel = (status?: string | null) => {
    const normalized = (status || '').toLowerCase()
    if (PAID_INVOICE_STATUSES.includes(normalized)) return 'Payée'
    if (DUE_INVOICE_STATUSES.includes(normalized)) return 'À payer'
    if (normalized === 'draft') return 'Brouillon'
    if (normalized === 'void' || normalized === 'canceled') return 'Annulée'
    return status || '—'
  }

  const getLogStatusLabel = (status?: string | null) => {
    const labels: Record<string, string> = {
      INITIATED: 'Initié',
      PUSH_SENT: 'Push envoyé',
      SUCCESS: 'Réussi',
      FAILED: 'Échoué',
      ERROR: 'Erreur',
    }
    return labels[(status || '').toUpperCase()] || status || '—'
  }

  const handleDownloadInvoice = async (invoice: BillingInvoice) => {
    if (!invoice?.id) return
    try {
      const blob = await downloadBillingInvoicePdf(invoice.id)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `note-de-debit-${invoice.number || invoice.id}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error: any) {
      console.error('Erreur téléchargement note de débit:', error)
      showError('Téléchargement', error?.message || 'Impossible de télécharger la note de débit.')
    }
  }

  const pendingInvoice = billingInvoices.find((invoice) =>
    DUE_INVOICE_STATUSES.includes((invoice.status || '').toLowerCase())
  )

  const saasConfigured = billingConfig?.configured !== false && billingConfig !== null
  const configPlanPrice = billingConfig?.plan?.price ?? null
  const configCurrency = billingConfig?.plan?.currency ?? null
  const mobileMoneyMethod = billingConfig?.payment_methods?.mobile_money
  const supportContact = billingConfig?.support_contact || null

  const payableAmount = pendingInvoice?.amount ?? configPlanPrice ?? null
  const payableCurrency =
    pendingInvoice?.currency || configCurrency || billingSummary?.currency || 'USD'
  const paymentAmountLabel =
    payableAmount != null ? formatBillingAmount(payableAmount, payableCurrency) : null
  const hasPayableAmount = payableAmount != null && payableAmount > 0

  const planStatus = (billingSummary?.plan_status || '').toUpperCase()
  const dueDate = billingSummary?.renewal_date || billingSummary?.plan_expires_at || null
  const daysUntilDue = getDaysUntil(dueDate)
  const countdownLabel = formatCountdown(daysUntilDue)

  // Ton du bandeau : rouge si le plan est déjà bloqué, ambre si l'échéance arrive,
  // vert si tout est en ordre.
  const statusTone = useMemo(() => {
    if (['SUSPENDED', 'EXPIRED', 'CANCELED', 'PAST_DUE'].includes(planStatus)) return 'danger'
    if (daysUntilDue !== null && daysUntilDue < 0) return 'danger'
    if (daysUntilDue !== null && daysUntilDue <= 7) return 'warning'
    if (['ACTIVE', 'TRIAL'].includes(planStatus)) return 'ok'
    return 'neutral'
  }, [planStatus, daysUntilDue])

  const toneClass =
    statusTone === 'danger'
      ? billingStyles.planCardDanger
      : statusTone === 'warning'
        ? billingStyles.planCardWarning
        : statusTone === 'ok'
          ? billingStyles.planCardOk
          : billingStyles.planCardNeutral

  const statusBadgeClass =
    statusTone === 'danger'
      ? billingStyles.badgeInactive
      : statusTone === 'warning'
        ? billingStyles.badgeWarning
        : statusTone === 'ok'
          ? billingStyles.badgeActive
          : billingStyles.badgeNeutral

  const bankReference = user?.organisation_slug || user?.organisation_id || '—'

  const handleCopyReference = async () => {
    const value = String(bankReference)
    if (!value || value === '—') return
    try {
      await navigator.clipboard.writeText(value)
      setReferenceCopied(true)
      window.setTimeout(() => setReferenceCopied(false), 2000)
    } catch {
      showWarning('Copie', "Copie impossible. Notez la référence manuellement : " + value)
    }
  }

  const stopInvoicePolling = () => {
    if (invoicePollRef.current !== null) {
      window.clearInterval(invoicePollRef.current)
      invoicePollRef.current = null
    }
    invoicePollAttemptsRef.current = 0
  }

  const startInvoicePolling = () => {
    if (invoicePollRef.current !== null) return
    invoicePollAttemptsRef.current = 0
    invoicePollRef.current = window.setInterval(async () => {
      invoicePollAttemptsRef.current += 1
      await loadBilling()
      const hasPdf = billingInvoicesRef.current.some((invoice) => invoice.pdf_available)
      if (hasPdf || invoicePollAttemptsRef.current >= 10) {
        stopInvoicePolling()
      }
    }, 6000)
  }

  const redirectToCheckout = async () => {
    if (!hasPayableAmount) {
      showWarning('Paiement', 'Montant indisponible. Veuillez actualiser ou contacter le siège.')
      return
    }
    try {
      setBillingCheckoutLoading(true)
      const res = await createCheckoutSession()
      if (res?.checkout_url) {
        window.location.href = res.checkout_url
      } else {
        showWarning('Paiement', 'Lien de paiement indisponible.')
      }
    } catch (error: any) {
      console.error('Erreur checkout paiement:', error)
      showError('Paiement', error?.message || "Impossible de générer le lien de paiement.")
    } finally {
      setBillingCheckoutLoading(false)
    }
  }

  const handleMobileMoneyPayment = async () => {
    const phone = momoPhone.trim()
    if (!phone) {
      showWarning('Paiement', 'Saisissez le numéro de téléphone à débiter.')
      return
    }
    if (!hasPayableAmount) {
      showWarning('Paiement', 'Montant indisponible. Veuillez actualiser ou contacter le siège.')
      return
    }
    try {
      setMomoLoading(true)
      await initiateBillingPayment({
        phone,
        provider: momoProvider || undefined,
        amount: payableAmount,
      })
      showSuccess(
        'Demande envoyée',
        `Validez le paiement de ${paymentAmountLabel} sur le téléphone ${phone} avec votre code PIN.`
      )
      startInvoicePolling()
    } catch (error: any) {
      console.error('Erreur paiement mobile money:', error)
      showError('Paiement', error?.message || "Impossible d'initier le paiement mobile.")
    } finally {
      setMomoLoading(false)
    }
  }

  const loadBilling = async () => {
    setBillingLoading(true)
    setBillingError(null)
    setBillingConfigLoading(true)

    const [summaryResult, invoicesResult, configResult] = await Promise.allSettled([
      getBillingSummary(),
      listBillingInvoices(),
      getBillingConfig(),
    ])

    // Summary — données locales toujours disponibles sauf erreur réseau/auth
    if (summaryResult.status === 'fulfilled') {
      setBillingSummary(summaryResult.value)
    } else {
      console.error('Erreur chargement summary:', summaryResult.reason)
      const msg = summaryResult.reason?.message
      // N'afficher l'erreur que si ce n'est pas un simple "non configuré"
      if (msg && !msg.includes('non configurée') && !msg.includes('indisponible')) {
        setBillingError(msg)
      }
      setBillingSummary(null)
    }

    // Notes de débit : peut être vide sans SaaS
    if (invoicesResult.status === 'fulfilled') {
      setBillingInvoices(Array.isArray(invoicesResult.value?.items) ? invoicesResult.value.items : [])
      setBillingInvoicesConfigured(!!invoicesResult.value?.configured)
    } else {
      setBillingInvoices([])
      setBillingInvoicesConfigured(false)
    }

    // Config — maintenant retourne {configured:false} au lieu de 503
    if (configResult.status === 'fulfilled') {
      setBillingConfig(configResult.value || null)
    } else {
      console.error('Erreur chargement config billing:', configResult.reason)
      setBillingConfig(null)
    }

    setBillingLoading(false)
    setBillingConfigLoading(false)
  }

  const loadBillingLogs = async (
    page = billingLogsPage,
    overrides?: { status?: string; provider?: string; phone?: string }
  ) => {
    try {
      setBillingLogsLoading(true)
      const offset = (page - 1) * billingLogsPageSize
      const nextStatus = overrides?.status ?? billingLogsStatus
      const nextProvider = overrides?.provider ?? billingLogsProvider
      const nextPhone = overrides?.phone ?? billingLogsPhone
      const res = await listBillingPaymentLogs({
        status: nextStatus || undefined,
        provider: nextProvider || undefined,
        phone: nextPhone || undefined,
        limit: billingLogsPageSize,
        offset,
      })
      setBillingLogs(Array.isArray(res?.items) ? res.items : [])
      setBillingLogsTotal(res?.total || 0)
      setBillingLogsPage(page)
    } catch (error: any) {
      console.error('Erreur chargement logs paiement:', error)
      setBillingLogs([])
      setBillingLogsTotal(0)
    } finally {
      setBillingLogsLoading(false)
    }
  }

  useEffect(() => {
    loadBilling()
  }, [])

  useEffect(() => {
    billingInvoicesRef.current = billingInvoices
  }, [billingInvoices])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const status = params.get('status')
    if (!status) return
    if (status === 'success') {
      showSuccess('Paiement confirmé', 'Votre paiement a été traité avec succès.')
      startInvoicePolling()
    } else if (status === 'cancel') {
      showWarning('Paiement annulé', 'Le paiement a été annulé. Vous pouvez réessayer.')
    }
    params.delete('status')
    const nextQuery = params.toString()
    const nextUrl = nextQuery ? `${location.pathname}?${nextQuery}` : location.pathname
    window.history.replaceState({}, '', nextUrl)
    void loadBilling()
  }, [location.pathname, location.search, showSuccess, showWarning])

  useEffect(() => {
    if (billingSubTab !== 'logs') return
    void loadBillingLogs(1)
  }, [billingSubTab])

  useEffect(() => {
    return () => {
      stopInvoicePolling()
    }
  }, [])

  const planName = billingConfig?.plan?.name || billingSummary?.plan_type || 'Plan non défini'
  const planInterval = billingConfig?.plan?.interval || null
  const portalUrl = billingSummary?.billing_portal_url || null
  const canPayOnline = saasConfigured && hasPayableAmount
  // Le push mobile passe par la console SaaS : sans elle, l'endpoint renvoie 503.
  const momoEnabled = saasConfigured && mobileMoneyMethod?.enabled !== false

  return (
    <div className={billingStyles.billingContainer}>
      <div className={billingStyles.subNav}>
        <button
          className={`${billingStyles.subNavButton} ${billingSubTab === 'overview' ? billingStyles.subNavActive : ''}`}
          onClick={() => setBillingSubTab('overview')}
        >
          Vue d'ensemble
        </button>
        <button
          className={`${billingStyles.subNavButton} ${billingSubTab === 'logs' ? billingStyles.subNavActive : ''}`}
          onClick={() => setBillingSubTab('logs')}
        >
          Tentatives de paiement
        </button>
      </div>

      {billingSubTab === 'logs' && (
        <div className={billingStyles.section}>
          <div className={billingStyles.sectionHeader}>
            <div>
              <h3>Tentatives de paiement mobile</h3>
              <span className={billingStyles.mutedText}>
                Chaque demande envoyée à l'opérateur, avec son statut et son éventuelle erreur.
              </span>
            </div>
          </div>
          <div className={billingStyles.tableToolbar}>
            <div className={billingStyles.tableMeta}>
              {billingLogsTotal === 0
                ? 'Aucune tentative'
                : `Affichage ${1 + (billingLogsPage - 1) * billingLogsPageSize}-${Math.min(
                    billingLogsPage * billingLogsPageSize,
                    billingLogsTotal
                  )} sur ${billingLogsTotal}`}
            </div>
            <div className={billingStyles.tableFilters}>
              <select
                className={billingStyles.pageSizeSelect}
                value={billingLogsStatus}
                onChange={(e) => {
                  const next = e.target.value
                  setBillingLogsStatus(next)
                  void loadBillingLogs(1, { status: next })
                }}
              >
                <option value="">Tous statuts</option>
                <option value="INITIATED">Initié</option>
                <option value="PUSH_SENT">Push envoyé</option>
                <option value="SUCCESS">Réussi</option>
                <option value="FAILED">Échoué</option>
                <option value="ERROR">Erreur</option>
              </select>
              <select
                className={billingStyles.pageSizeSelect}
                value={billingLogsProvider}
                onChange={(e) => {
                  const next = e.target.value
                  setBillingLogsProvider(next)
                  void loadBillingLogs(1, { provider: next })
                }}
              >
                <option value="">Tous opérateurs</option>
                <option value="mobile_money">Mobile Money</option>
                <option value="mpesa">M‑Pesa</option>
                <option value="orange_money">Orange Money</option>
                <option value="airtel_money">Airtel Money</option>
              </select>
              <input
                type="search"
                className={billingStyles.searchInput}
                placeholder="Rechercher un numéro..."
                value={billingLogsPhone}
                onChange={(e) => setBillingLogsPhone(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void loadBillingLogs(1, { phone: billingLogsPhone })
                }}
              />
              <button
                type="button"
                className={billingStyles.secondaryBtn}
                onClick={() => loadBillingLogs(1, { phone: billingLogsPhone })}
                disabled={billingLogsLoading}
              >
                {billingLogsLoading ? 'Chargement...' : 'Filtrer'}
              </button>
              <button
                type="button"
                className={billingStyles.secondaryBtn}
                onClick={async () => {
                  try {
                    const blob = await exportBillingPaymentLogs({
                      status: billingLogsStatus || undefined,
                      provider: billingLogsProvider || undefined,
                      phone: billingLogsPhone || undefined,
                    })
                    const url = window.URL.createObjectURL(blob)
                    const link = document.createElement('a')
                    link.href = url
                    link.download = 'payment_logs.csv'
                    document.body.appendChild(link)
                    link.click()
                    link.remove()
                    window.URL.revokeObjectURL(url)
                  } catch (error: any) {
                    showError('Export', error?.message || 'Impossible d’exporter les logs.')
                  }
                }}
                disabled={billingLogsLoading}
              >
                Export CSV
              </button>
            </div>
          </div>
          <div className={billingStyles.tableContainer}>
            <table className={`${billingStyles.table} ${billingStyles.invoiceTable}`}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Téléphone</th>
                  <th>Montant</th>
                  <th>Opérateur</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {billingLogsLoading && (
                  <tr>
                    <td colSpan={5} className={billingStyles.tableEmptyRow}>
                      Chargement des tentatives...
                    </td>
                  </tr>
                )}
                {!billingLogsLoading && billingLogs.length === 0 && (
                  <tr>
                    <td colSpan={5} className={billingStyles.tableEmptyRow}>
                      Aucune tentative de paiement enregistrée.
                    </td>
                  </tr>
                )}
                {!billingLogsLoading &&
                  billingLogs.map((log) => (
                    <tr key={log.id}>
                      <td>{formatBillingDate(log.created_at)}</td>
                      <td>{log.phone_number || '—'}</td>
                      <td>{formatBillingAmount(log.amount, configCurrency || billingSummary?.currency || 'USD')}</td>
                      <td>{log.provider || '—'}</td>
                      <td>
                        <span className={billingStyles.badge}>{getLogStatusLabel(log.status)}</span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <div className={billingStyles.paginationControls} style={{ marginTop: '12px' }}>
            <button
              type="button"
              className={billingStyles.paginationButton}
              onClick={() => loadBillingLogs(Math.max(1, billingLogsPage - 1))}
              disabled={billingLogsPage === 1 || billingLogsLoading}
            >
              ‹
            </button>
            <span className={billingStyles.paginationInfo}>
              Page {billingLogsPage} / {Math.max(1, Math.ceil(billingLogsTotal / billingLogsPageSize))}
            </span>
            <button
              type="button"
              className={billingStyles.paginationButton}
              onClick={() =>
                loadBillingLogs(
                  Math.min(Math.max(1, Math.ceil(billingLogsTotal / billingLogsPageSize)), billingLogsPage + 1)
                )
              }
              disabled={billingLogsPage >= Math.ceil(billingLogsTotal / billingLogsPageSize) || billingLogsLoading}
            >
              ›
            </button>
          </div>
        </div>
      )}

      {billingSubTab === 'overview' && (
        <>
          {billingError && (
            <div className={billingStyles.infoBox}>
              <strong>Erreur :</strong> {billingError}
            </div>
          )}

          <div className={`${billingStyles.planCard} ${toneClass}`}>
            <div className={billingStyles.planCardTop}>
              <div className={billingStyles.planIdentity}>
                <span className={statusBadgeClass}>{getPlanStatusLabel(billingSummary?.plan_status)}</span>
                <div>
                  <div className={billingStyles.planName}>{planName}</div>
                  {planInterval && <div className={billingStyles.planInterval}>Cycle {planInterval}</div>}
                </div>
              </div>
              <button
                type="button"
                onClick={() => loadBilling()}
                disabled={billingLoading}
                className={billingStyles.btnSecondary}
              >
                {billingLoading ? 'Actualisation...' : 'Actualiser'}
              </button>
            </div>

            <div className={billingStyles.billingMeta}>
              <div>
                <div className={billingStyles.billingLabel}>
                  {pendingInvoice ? 'Montant dû' : 'Montant du plan'}
                </div>
                <div className={billingStyles.planAmount}>{paymentAmountLabel || '—'}</div>
              </div>
              <div>
                <div className={billingStyles.billingLabel}>Prochaine échéance</div>
                <div className={billingStyles.billingValue}>{formatBillingDate(dueDate)}</div>
                {countdownLabel && (
                  <div
                    className={`${billingStyles.countdown} ${
                      statusTone === 'danger'
                        ? billingStyles.countdownDanger
                        : statusTone === 'warning'
                          ? billingStyles.countdownWarning
                          : ''
                    }`}
                  >
                    {countdownLabel}
                  </div>
                )}
              </div>
              <div>
                <div className={billingStyles.billingLabel}>Référence à rappeler</div>
                <div className={billingStyles.billingValue}>
                  {bankReference}
                  {bankReference !== '—' && (
                    <button type="button" className={billingStyles.copyBtn} onClick={handleCopyReference}>
                      {referenceCopied ? 'Copiée' : 'Copier'}
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className={billingStyles.billingActionRow}>
              <button
                className={billingStyles.btnPrimary}
                onClick={scrollToPaymentMethods}
                disabled={!canPayOnline}
              >
                {paymentAmountLabel ? `Payer ${paymentAmountLabel}` : 'Payer mon abonnement'}
              </button>
              {portalUrl && (
                <a
                  className={billingStyles.btnOutline}
                  href={portalUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Portail de facturation
                </a>
              )}
            </div>

            {!canPayOnline && !billingConfigLoading && (
              <div className={billingStyles.planCardFootnote}>
                {!saasConfigured
                  ? "Le paiement en ligne n'est pas encore activé pour votre province."
                  : "Aucun montant à régler pour le moment."}
                {supportContact ? ` Contact : ${supportContact}` : ''}
              </div>
            )}
          </div>

          <div className={billingStyles.payMethodsHeader} ref={paymentMethodsRef}>
            <h3>Comment payer</h3>
            <span className={billingStyles.mutedText}>
              Réglez votre abonnement par carte bancaire ou par Mobile Money.
            </span>
          </div>

          {saasConfigured && (
            <div className={billingStyles.checkoutCard}>
              <div>
                <div className={billingStyles.paymentMethodTitle}>Carte bancaire — Visa / Mastercard</div>
                <div className={billingStyles.paymentMethodSub}>
                  Vous êtes redirigé vers la page de paiement sécurisée. Vos données de carte ne
                  transitent jamais par One CPK.
                </div>
              </div>
              <div className={billingStyles.paymentActions}>
                <button
                  type="button"
                  className={billingStyles.btnPrimary}
                  onClick={redirectToCheckout}
                  disabled={billingCheckoutLoading || !canPayOnline}
                >
                  {billingCheckoutLoading
                    ? 'Ouverture...'
                    : paymentAmountLabel
                      ? `Payer ${paymentAmountLabel} par carte`
                      : 'Payer par carte'}
                </button>
              </div>
              <div className={billingStyles.paymentLogos}>
                <span>VISA</span>
                <span>MASTERCARD</span>
              </div>
            </div>
          )}

          {momoEnabled && (
            <div className={billingStyles.paymentBox}>
              <div>
                <div className={billingStyles.paymentMethodTitle}>Mobile Money</div>
                <div className={billingStyles.paymentMethodSub}>
                  {mobileMoneyMethod?.instructions ||
                    "Saisissez le numéro à débiter : une demande de validation est envoyée sur le téléphone."}
                </div>
              </div>
              <div className={billingStyles.paymentInputs}>
                <input
                  type="tel"
                  inputMode="tel"
                  placeholder="Numéro à débiter (ex. 0812345678)"
                  value={momoPhone}
                  onChange={(e) => setMomoPhone(e.target.value)}
                  disabled={momoLoading}
                />
                <select
                  value={momoProvider}
                  onChange={(e) => setMomoProvider(e.target.value)}
                  disabled={momoLoading}
                >
                  <option value="mobile_money">Opérateur par défaut</option>
                  <option value="mpesa">M‑Pesa</option>
                  <option value="orange_money">Orange Money</option>
                  <option value="airtel_money">Airtel Money</option>
                </select>
              </div>
              <div className={billingStyles.paymentActions}>
                <button
                  type="button"
                  className={billingStyles.btnPrimary}
                  onClick={handleMobileMoneyPayment}
                  disabled={momoLoading || !hasPayableAmount || !momoPhone.trim()}
                >
                  {momoLoading
                    ? 'Envoi en cours...'
                    : paymentAmountLabel
                      ? `Envoyer la demande de ${paymentAmountLabel}`
                      : 'Envoyer la demande'}
                </button>
              </div>
            </div>
          )}

          {!billingConfigLoading && !saasConfigured && (
            <div className={billingStyles.billingNotice}>
              Le paiement en ligne n'est pas encore activé pour votre organisation. Contactez le
              siège pour connaître les modalités de règlement
              {supportContact ? ` : ${supportContact}` : '.'}
            </div>
          )}

          <div className={billingStyles.payMethodsHeader}>
            <h3>Notes de débit</h3>
            <span className={billingStyles.mutedText}>Vos documents de facturation et leur statut.</span>
          </div>

          <div className={billingStyles.invoiceTableWrapper}>
            <table className={billingStyles.invoiceTable}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Numéro</th>
                  <th>Montant</th>
                  <th>Statut</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {billingLoading && (
                  <tr>
                    <td colSpan={5} className={billingStyles.tableEmptyRow}>
                      Chargement...
                    </td>
                  </tr>
                )}
                {!billingLoading && billingInvoices.length === 0 && (
                  <tr>
                    <td colSpan={5} className={billingStyles.tableEmptyRow}>
                      {billingInvoicesConfigured
                        ? 'Aucune note de débit enregistrée.'
                        : "L'historique des notes de débit n'est pas disponible en mode autonome."}
                    </td>
                  </tr>
                )}
                {!billingLoading &&
                  billingInvoices.map((invoice) => (
                    <tr key={invoice.id}>
                      <td>{formatBillingDate(invoice.date)}</td>
                      <td>{invoice.number || '—'}</td>
                      <td className={billingStyles.invoiceAmount}>
                        {formatBillingAmount(invoice.amount, invoice.currency || payableCurrency)}
                      </td>
                      <td>
                        <span
                          className={
                            PAID_INVOICE_STATUSES.includes((invoice.status || '').toLowerCase())
                              ? billingStyles.badgeActive
                              : billingStyles.badgeWarning
                          }
                        >
                          {getInvoiceStatusLabel(invoice.status)}
                        </span>
                      </td>
                      <td>
                        {invoice.pdf_available ? (
                          <button
                            onClick={() => handleDownloadInvoice(invoice)}
                            className={billingStyles.btnDownload}
                          >
                            Télécharger
                          </button>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          <div className={billingStyles.billingHint}>
            La facturation est gérée par le siège. Les données d'abonnement affichées ici sont celles
            enregistrées pour votre province.
          </div>
        </>
      )}
    </div>
  )
}
