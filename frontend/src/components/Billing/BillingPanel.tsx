import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  createCheckoutSession,
  downloadBillingInvoicePdf,
  exportBillingPaymentLogs,
  getBillingConfig,
  getBillingSummary,
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
  const billingLogsPageSize = 25
  const billingInvoicesRef = useRef<BillingInvoice[]>([])
  const invoicePollRef = useRef<number | null>(null)
  const invoicePollAttemptsRef = useRef(0)

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

  const getPlanStatusLabel = (status?: string | null) => {
    const normalized = (status || '').toUpperCase()
    const labels: Record<string, string> = {
      ACTIVE: 'Actif',
      TRIAL: 'Essai',
      SUSPENDED: 'Suspendu',
      EXPIRED: 'Expiré',
      PENDING_ACTIVATION: 'En attente',
    }
    return labels[normalized] || (status ? status : '—')
  }

  const getPlanStatusClass = (status?: string | null) => {
    const normalized = (status || '').toUpperCase()
    return ['ACTIVE', 'TRIAL'].includes(normalized) ? billingStyles.badgeActive : billingStyles.badgeInactive
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

  const handleOpenBillingPortal = () => {
    const portalUrl = billingSummary?.billing_portal_url
    if (!portalUrl) {
      showWarning(
        'Portail indisponible',
        "Le portail de facturation n'est pas configuré. Contactez l'hébergeur pour l'activation."
      )
      return
    }
    window.open(portalUrl, '_blank', 'noopener,noreferrer')
  }

  const pendingInvoice = billingInvoices.find((invoice) => {
    const status = (invoice.status || '').toLowerCase()
    return ['pending', 'unpaid', 'past_due', 'due'].includes(status)
  })

  const saasConfigured = billingConfig?.configured !== false && billingConfig !== null
  const configPlanPrice = billingConfig?.plan?.price ?? null
  const configCurrency = billingConfig?.plan?.currency ?? null
  const paymentAmountLabel = pendingInvoice
    ? formatBillingAmount(pendingInvoice.amount, pendingInvoice.currency || configCurrency || 'USD')
    : configPlanPrice
      ? formatBillingAmount(configPlanPrice, configCurrency || 'USD')
      : null

  const hasPayableAmount = !!pendingInvoice?.amount || !!configPlanPrice

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
  const bankReference = user?.organisation_slug || user?.organisation_id || '—'

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
          Logs paiements
        </button>
      </div>

      {billingSubTab === 'logs' && (
        <div className={billingStyles.section}>
          <div className={billingStyles.sectionHeader}>
            <div>
              <h3>Historique des tentatives Mobile Money</h3>
              <span className={billingStyles.mutedText}>Suivi des erreurs et statuts de paiement</span>
            </div>
          </div>
          <div className={billingStyles.tableToolbar}>
            <div className={billingStyles.tableMeta}>
              {billingLogsTotal === 0
                ? 'Aucun log'
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
                <option value="INITIATED">INITIATED</option>
                <option value="PUSH_SENT">PUSH_SENT</option>
                <option value="ERROR">ERROR</option>
                <option value="SUCCESS">SUCCESS</option>
                <option value="FAILED">FAILED</option>
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
                    <td colSpan={5} style={{ textAlign: 'center', padding: '20px', color: '#64748b' }}>
                      Chargement des logs...
                    </td>
                  </tr>
                )}
                {!billingLogsLoading && billingLogs.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ textAlign: 'center', padding: '20px', color: '#9ca3af' }}>
                      Aucun log disponible.
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
                        <span className={billingStyles.badge}>{log.status}</span>
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
          <div className={billingStyles.billingActionRow}>
            <button onClick={() => loadBilling()} disabled={billingLoading} className={billingStyles.btnSecondary}>
              {billingLoading ? 'Actualisation...' : 'Actualiser'}
            </button>
            <button onClick={handleOpenBillingPortal} className={billingStyles.btnOutline}>
              Ouvrir le portail
            </button>
          </div>

          {billingError && (
            <div className={billingStyles.infoBox}>
              <strong>Erreur :</strong> {billingError}
            </div>
          )}

          <div className={billingStyles.planCard}>
            <div className={billingStyles.planInfo}>
              <span>
                Plan actuel : <strong>{billingConfig?.plan?.name || billingSummary?.plan_type || '—'}</strong>
              </span>
              <span>
                Renouvellement : {formatBillingDate(billingSummary?.renewal_date || billingSummary?.plan_expires_at)}
              </span>
              {billingConfig?.plan?.interval && <span>Cycle : {billingConfig.plan.interval}</span>}
              {paymentAmountLabel && <span>Montant : {paymentAmountLabel}</span>}
              <span>Référence : {bankReference}</span>
            </div>
            <span className={getPlanStatusClass(billingSummary?.plan_status)}>
              {getPlanStatusLabel(billingSummary?.plan_status)}
            </span>
          </div>

          <div className={billingStyles.billingHint}>
            La facturation est gérée par le siège. Les données d'abonnement affichées ci-dessus
            sont celles enregistrées pour votre province.
          </div>

          {billingConfigLoading && (
            <div className={billingStyles.billingNotice}>Chargement de la configuration des notes de débit...</div>
          )}
          {!billingConfigLoading && !saasConfigured && (
            <div className={billingStyles.billingNotice}>
              Le paiement en ligne n'est pas encore activé pour votre province.
              Contactez le siège pour les modalités de règlement.
            </div>
          )}

          {!billingInvoicesConfigured && (
            <div className={billingStyles.billingNotice}>
              L'historique des notes de débit n'est pas disponible en mode autonome.
            </div>
          )}

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
                    <td colSpan={5}>Chargement...</td>
                  </tr>
                )}
                {!billingLoading && billingInvoices.length === 0 && (
                  <tr>
                    <td colSpan={5}>Aucune note de débit enregistrée.</td>
                  </tr>
                )}
                {!billingLoading &&
                  billingInvoices.map((invoice) => (
                    <tr key={invoice.id}>
                      <td>{formatBillingDate(invoice.date)}</td>
                      <td>{invoice.number || '—'}</td>
                      <td>{formatBillingAmount(invoice.amount, invoice.currency || 'USD')}</td>
                      <td>{invoice.status || '—'}</td>
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

          <div className={billingStyles.checkoutCard}>
            <div>
              <h3>Réactivation rapide</h3>
              {saasConfigured
                ? <p>Payez votre abonnement via notre checkout sécurisé.</p>
                : <p>Le paiement en ligne sera disponible une fois activé par le siège.</p>
              }
            </div>
            <div className={billingStyles.checkoutActions}>
              <button
                className={billingStyles.btnPrimary}
                onClick={redirectToCheckout}
                disabled={billingCheckoutLoading || !hasPayableAmount || !saasConfigured}
                title={!saasConfigured ? "Paiement en ligne non activé pour cette province" : undefined}
              >
                {billingCheckoutLoading ? 'Chargement...' : 'Payer mon abonnement'}
              </button>
              <button className={billingStyles.btnOutline} onClick={loadBilling} disabled={billingLoading}>
                Vérifier le statut
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
