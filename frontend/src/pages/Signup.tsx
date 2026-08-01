import { useEffect, useMemo, useState } from 'react'
import {
  createCheckout,
  createSignup,
  listPlans,
  type Plan,
  checkInvitation,
  type InvitationCheckResponse,
} from '../api/onboarding'
import styles from './Signup.module.css'

type Step = 1 | 2 | 3 | 4

export default function Signup() {
  const [step, setStep] = useState<Step>(1)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loadingPlans, setLoadingPlans] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [reference, setReference] = useState<string | null>(null)
  const [invitation, setInvitation] = useState<InvitationCheckResponse | null>(null)

  const [form, setForm] = useState({
    organisation_name: '',
    slug: '',
    admin_email: '',
    admin_phone: '',
    plan_id: 0,
    billing_months: 1,
  })
  const [consentAccepted, setConsentAccepted] = useState(false)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const res = await listPlans()
        if (mounted) {
          setPlans(res || [])
          if (res?.length && !form.plan_id) {
            setForm((prev) => ({ ...prev, plan_id: res[0].id }))
          }
        }
      } catch {
        if (mounted) setPlans([])
      } finally {
        if (mounted) setLoadingPlans(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  const selectablePlans = useMemo(() => {
    if (invitation?.plan_id) {
      return plans.filter((p) => p.id === invitation.plan_id)
    }
    return plans
  }, [plans, invitation])

  const selectedPlan = useMemo(
    () => selectablePlans.find((p) => p.id === form.plan_id) || null,
    [selectablePlans, form.plan_id]
  )

  const onNext = async () => {
    setError('')
    if (step === 1) {
      if (!form.admin_email) {
        setError('Veuillez saisir votre email officiel.')
        return
      }
      setLoading(true)
      try {
        const res = await checkInvitation(form.admin_email)
        setInvitation(res)
        setForm((prev) => ({
          ...prev,
          organisation_name: res.organisation_name,
          slug: res.slug,
          plan_id: res.plan_id,
        }))
        setStep(2)
      } catch (err: any) {
        setError(err?.message || "Aucune invitation trouvée pour cet email.")
      } finally {
        setLoading(false)
      }
      return
    }
    if (step === 2) {
      if (!form.plan_id) {
        setError('Veuillez sélectionner un plan.')
        return
      }
      if (!consentAccepted) {
        setError("Veuillez accepter les Conditions Générales d'Utilisation et la Politique de confidentialité.")
        return
      }
      setLoading(true)
      try {
        const signup = await createSignup({
          organisation_name: form.organisation_name,
          slug: form.slug,
          admin_email: form.admin_email,
          admin_phone: form.admin_phone || null,
          plan_id: form.plan_id,
          billing_months: form.billing_months,
        })
        setReference(signup.reference)
        setStep(3)
      } catch (err: any) {
        setError(err?.message || "Impossible d'enregistrer la demande.")
      } finally {
        setLoading(false)
      }
      return
    }
    if (step === 3 && reference) {
      setLoading(true)
      try {
        const checkout = await createCheckout(reference)
        if (checkout.status === 'provisioned') {
          setStep(4)
          return
        }
        if (checkout.checkout_url) {
          window.location.href = checkout.checkout_url
        } else {
          setError('URL de paiement indisponible.')
        }
      } catch (err: any) {
        setError(err?.message || 'Paiement impossible.')
      } finally {
        setLoading(false)
      }
    }
  }

  const onBack = () => {
    setError('')
    if (step > 1) setStep((step - 1) as Step)
  }

  const discountRate = (months: number) => {
    const map = selectedPlan?.discounts || {}
    const key = String(months)
    return Number(map[key] || 0)
  }

  const estimatedTotal = () => {
    if (!selectedPlan) return 0
    const price = Number(selectedPlan.monthly_price_usd || 0)
    const rate = discountRate(form.billing_months)
    return price * form.billing_months * (1 - rate)
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>Inscription Conseil Provincial</h1>
          <p className={styles.subtitle}>
            Créez votre espace sécurisé, choisissez votre plan et activez votre sous-domaine.
          </p>
        </div>

        <div className={styles.stepBar}>
          {[1, 2, 3, 4].map((n) => (
            <div key={n} className={`${styles.step} ${step >= n ? styles.stepActive : ''}`} />
          ))}
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {step === 1 && (
          <div className={styles.card}>
            <div className={styles.grid}>
              <label className={styles.field}>
                Email officiel*
                <input
                  className={styles.input}
                  value={form.admin_email}
                  onChange={(e) => setForm((prev) => ({ ...prev, admin_email: e.target.value }))}
                  placeholder="admin@province.cd"
                />
              </label>
              <label className={styles.field}>
                Téléphone
                <input
                  className={styles.input}
                  value={form.admin_phone}
                  onChange={(e) => setForm((prev) => ({ ...prev, admin_phone: e.target.value }))}
                  placeholder="+243 ..."
                />
              </label>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className={styles.card}>
            <div className={styles.status}>
              Province : <strong>{invitation?.organisation_name || form.organisation_name}</strong> (
              {invitation?.slug || form.slug})
            </div>
            <div className={styles.planGrid}>
              {loadingPlans && <div className={styles.status}>Chargement des plans...</div>}
              {!loadingPlans &&
                selectablePlans.map((plan) => (
                  <div
                    key={plan.id}
                    className={`${styles.planCard} ${plan.id === form.plan_id ? styles.planActive : ''}`}
                    onClick={() => setForm((prev) => ({ ...prev, plan_id: plan.id }))}
                  >
                    <div className={styles.planTitle}>{plan.name}</div>
                    <div className={styles.planPrice}>{Number(plan.monthly_price_usd).toLocaleString()} USD / mois</div>
                    {plan.features?.max_users && (
                      <div className={styles.planFeature}>Utilisateurs max: {plan.features.max_users}</div>
                    )}
                    {plan.features?.ai_reports !== undefined && (
                      <div className={styles.planFeature}>
                        IA: {plan.features.ai_reports ? 'incluse' : 'non incluse'}
                      </div>
                    )}
                  </div>
                ))}
            </div>
            <div className={styles.durationRow}>
              {[1, 3, 6, 12].map((months) => (
                <button
                  key={months}
                  type="button"
                  className={`${styles.durationBtn} ${form.billing_months === months ? styles.durationActive : ''}`}
                  onClick={() => setForm((prev) => ({ ...prev, billing_months: months }))}
                >
                  {months} mois{months > 1 ? ` (-${discountRate(months) * 100}%)` : ''}
                </button>
              ))}
            </div>
            <div className={styles.status}>
              Total estimé: {estimatedTotal().toLocaleString()} USD
            </div>
            <label
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
                marginTop: '16px',
                fontSize: '13px',
                color: '#374151',
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={consentAccepted}
                onChange={(e) => setConsentAccepted(e.target.checked)}
                style={{ marginTop: '3px', width: '16px', height: '16px', cursor: 'pointer' }}
              />
              <span>
                J'ai lu et j'accepte les{' '}
                <a href="https://onec-rdc.org/cgu" target="_blank" rel="noopener noreferrer" style={{ color: '#0d9488', textDecoration: 'underline' }}>
                  Conditions Générales d'Utilisation
                </a>{' '}
                et la{' '}
                <a href="https://onec-rdc.org/confidentialite" target="_blank" rel="noopener noreferrer" style={{ color: '#0d9488', textDecoration: 'underline' }}>
                  Politique de confidentialité
                </a>
                .
              </span>
            </label>
          </div>
        )}

        {step === 3 && (
          <div className={styles.card}>
            <div className={styles.status}>
              Plan choisi: <strong>{selectedPlan?.name}</strong>
            </div>
            <div className={styles.status}>
              Vous allez être redirigé vers la page de paiement FedaPay.
            </div>
          </div>
        )}

        {step === 4 && (
          <div className={styles.card}>
            <div className={styles.status}>
              Votre espace est en cours de préparation. Vous recevrez un email de confirmation.
            </div>
          </div>
        )}

        <div className={styles.actions}>
          {step > 1 && step < 4 && (
            <button type="button" className={styles.secondary} onClick={onBack} disabled={loading}>
              Retour
            </button>
          )}
          {step < 4 && (
            <button type="button" className={styles.primary} onClick={onNext} disabled={loading}>
              {loading ? 'Traitement...' : step === 3 ? 'Payer et activer' : 'Continuer'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
