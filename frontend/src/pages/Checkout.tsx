import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getCheckoutSession, initiateCheckoutSession, uploadBankProof, type CheckoutSession } from '../api/checkout'
import styles from './Checkout.module.css'

export default function Checkout() {
  const { sessionId } = useParams()
  const [session, setSession] = useState<CheckoutSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [method, setMethod] = useState<string>('VISA')
  const [phone, setPhone] = useState('')
  const [initiating, setInitiating] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [bankProof, setBankProof] = useState<File | null>(null)
  const [uploadingProof, setUploadingProof] = useState(false)

  useEffect(() => {
    let active = true
    const load = async (silent = false) => {
      if (!sessionId) {
        setError('Session manquante.')
        setLoading(false)
        return
      }
      try {
        if (!silent) setLoading(true)
        const res = await getCheckoutSession(sessionId)
        if (active) {
          setSession(res)
          setError(null)
          const status = (res.status || '').toLowerCase()
          if (status === 'success' && res.success_url) {
            window.location.href = res.success_url
          } else if (status === 'success') {
            setStatusMessage('Paiement confirmé. Vous pouvez fermer cette page.')
          } else if (status === 'validation') {
            setStatusMessage('Preuve reçue. Validation en cours par l’équipe.')
          } else if (status === 'failed') {
            setStatusMessage('Paiement refusé. Réessayez ou contactez le support.')
          }
        }
      } catch (err: any) {
        if (active) {
          setError(err?.message || 'Session introuvable.')
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return
    if (!session || (session.status || '').toLowerCase() !== 'pending') return
    const timer = setInterval(async () => {
      try {
        const res = await getCheckoutSession(sessionId)
        setSession(res)
        const status = (res.status || '').toLowerCase()
        if (status === 'success') {
          if (res.success_url) {
            window.location.href = res.success_url
          } else {
            setStatusMessage('Paiement confirmé. Vous pouvez fermer cette page.')
          }
        } else if (status === 'validation') {
          setStatusMessage('Preuve reçue. Validation en cours par l’équipe.')
        } else if (status === 'failed') {
          setStatusMessage('Paiement refusé. Réessayez ou contactez le support.')
        }
      } catch {
        // ignore polling errors
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [sessionId, session])

  const amountLabel = useMemo(() => {
    if (!session) return ''
    const currency = session.currency || 'USD'
    return `${Number(session.amount || 0).toLocaleString()} ${currency}`
  }, [session])

  if (loading) {
    return <div className={styles.loading}>Chargement du checkout...</div>
  }

  if (!session || error) {
    return (
      <div className={styles.error}>
        <h1>Session indisponible</h1>
        <p>{error || 'Veuillez réessayer ou contacter le support.'}</p>
      </div>
    )
  }

  const bank = session.payment_methods?.bank
  const mobile = session.payment_methods?.mobile_money
  const hasMobile = !!mobile?.enabled
  const hasBank = !!bank?.enabled

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.header}>
          <div>
            <h1>Paiement sécurisé</h1>
            <p>Session: {session.session_id}</p>
          </div>
          <div className={styles.amount}>{amountLabel}</div>
        </div>

        <div className={styles.methods}>
          {hasMobile && (
            <div className={styles.methodCard}>
              <h3>Mobile Money</h3>
              <p className={styles.meta}>Opérateur: {mobile.provider || '—'}</p>
              <p className={styles.meta}>Numéro marchand: {mobile.merchant_number || '—'}</p>
              {mobile.instructions && <p className={styles.instructions}>{mobile.instructions}</p>}
            </div>
          )}
          {hasBank && (
            <div className={styles.methodCard}>
              <h3>Virement bancaire</h3>
              <p className={styles.meta}>Banque: {bank.bank_name || '—'}</p>
              <p className={styles.meta}>Compte: {bank.account_number || '—'}</p>
              <p className={styles.meta}>Nom: {bank.account_name || '—'}</p>
              {bank.swift_code && <p className={styles.meta}>SWIFT: {bank.swift_code}</p>}
            </div>
          )}
        </div>

        <div className={styles.paymentPanel}>
          <div className={styles.paymentOptions}>
            <label className={styles.option}>
              <input
                type="radio"
                name="method"
                value="VISA"
                checked={method === 'VISA'}
                onChange={() => setMethod('VISA')}
              />
              Carte (VISA)
            </label>
            {hasMobile && (
              <>
                <label className={styles.option}>
                  <input
                    type="radio"
                    name="method"
                    value="MOMO_MPESA"
                    checked={method === 'MOMO_MPESA'}
                    onChange={() => setMethod('MOMO_MPESA')}
                  />
                  Mobile Money — M-Pesa
                </label>
                <label className={styles.option}>
                  <input
                    type="radio"
                    name="method"
                    value="MOMO_AIRTEL"
                    checked={method === 'MOMO_AIRTEL'}
                    onChange={() => setMethod('MOMO_AIRTEL')}
                  />
                  Mobile Money — Airtel
                </label>
                <label className={styles.option}>
                  <input
                    type="radio"
                    name="method"
                    value="MOMO_ORANGE"
                    checked={method === 'MOMO_ORANGE'}
                    onChange={() => setMethod('MOMO_ORANGE')}
                  />
                  Mobile Money — Orange
                </label>
              </>
            )}
            {hasBank && (
              <label className={styles.option}>
                <input
                  type="radio"
                  name="method"
                  value="BANK"
                  checked={method === 'BANK'}
                  onChange={() => setMethod('BANK')}
                />
                Virement bancaire (manuel)
              </label>
            )}
          </div>

          {method !== 'VISA' && method !== 'BANK' && (
            <label className={styles.phoneField}>
              Numéro Mobile Money
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+243 ..."
              />
            </label>
          )}

          {method === 'BANK' && (
            <div className={styles.bankProof}>
              <div className={styles.notice}>
                Effectuez le virement puis chargez la preuve (PDF ou image).
              </div>
              <input
                type="file"
                accept=".pdf,image/*"
                onChange={(e) => setBankProof(e.target.files?.[0] || null)}
              />
              <button
                className={styles.secondaryButton}
                onClick={async () => {
                  if (!bankProof || !sessionId) return
                  setUploadingProof(true)
                  setStatusMessage(null)
                  try {
                    const res = await uploadBankProof(sessionId, bankProof)
                    setStatusMessage('Preuve envoyée. Notre équipe validera le paiement.')
                    setSession((prev) => (prev ? { ...prev, bank_proof_url: res.url } : prev))
                  } catch (err: any) {
                    setStatusMessage(err?.message || 'Échec du téléchargement.')
                  } finally {
                    setUploadingProof(false)
                  }
                }}
                disabled={!bankProof || uploadingProof}
              >
                {uploadingProof ? 'Envoi...' : 'Envoyer la preuve'}
              </button>
              {session.bank_proof_url && (
                <div className={styles.uploadedHint}>Preuve déjà reçue.</div>
              )}
            </div>
          )}
        </div>

        <div className={styles.actions}>
          <button
            className={styles.primaryButton}
            onClick={async () => {
              if (method === 'BANK') return
              setInitiating(true)
              setStatusMessage(null)
              try {
                const res = await initiateCheckoutSession(session.session_id, {
                  method,
                  phone: method === 'VISA' ? undefined : phone,
                })
                if (res.checkout_url) {
                  window.location.href = res.checkout_url
                } else {
                  setStatusMessage('Lien de paiement non disponible. Réessayez.')
                }
              } catch (err: any) {
                setStatusMessage(err?.message || 'Impossible d’initier le paiement.')
              } finally {
                setInitiating(false)
              }
            }}
            disabled={
              initiating ||
              method === 'BANK' ||
              (method !== 'VISA' && method !== 'BANK' && !phone)
            }
          >
            {initiating ? 'Initialisation...' : 'Payer maintenant'}
          </button>
          {session.cancel_url && (
            <a className={styles.secondaryButton} href={session.cancel_url}>
              Retour à One CPK
            </a>
          )}
          <button
            className={styles.secondaryButton}
            onClick={async () => {
              if (!sessionId) return
              const res = await getCheckoutSession(sessionId)
              setSession(res)
              const st = (res.status || '').toLowerCase()
              if (st === 'success' && res.success_url) {
                window.location.href = res.success_url
              } else if (st === 'validation') {
                setStatusMessage('Preuve reçue. Validation en cours par l’équipe.')
              }
            }}
          >
            Actualiser le statut
          </button>
        </div>

        {statusMessage && <div className={styles.status}>{statusMessage}</div>}

          {session.support_contact && (
            <div className={styles.support}>Support: {session.support_contact}</div>
          )}
      </div>
    </div>
  )
}
