import { useCallback, useEffect, useState } from 'react'
import { format } from 'date-fns'
import { getCaisseStatus, openCaisse, type CaisseStatus } from '../api/caisse'
import { useToast } from '../hooks/useToast'

interface Props {
  /** Appelé après une ouverture réussie (pour rafraîchir la page parente). */
  onChanged?: () => void
}

/**
 * Bandeau d'état de la caisse (Modèle B). Affiche si la caisse est ouverte ou
 * fermée. Fermée, il propose de l'ouvrir (comptage du fond de caisse) — tant
 * qu'elle n'est pas ouverte, le backend refuse toute opération de caisse.
 */
export default function CaisseSessionBanner({ onChanged }: Props) {
  const { notifySuccess, notifyError } = useToast()
  const [status, setStatus] = useState<CaisseStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [usd, setUsd] = useState('')
  const [cdf, setCdf] = useState('')
  const [obs, setObs] = useState('')
  const [regulariser, setRegulariser] = useState(false)
  const [motifRegul, setMotifRegul] = useState('')

  const load = useCallback(async () => {
    try {
      setStatus(await getCaisseStatus())
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    setSubmitting(true)
    try {
      const res = await openCaisse({
        solde_ouverture_usd: parseFloat(usd) || 0,
        solde_ouverture_cdf: parseFloat(cdf) || 0,
        observation: obs.trim() || null,
        regulariser_ecart: regulariser,
        motif_regularisation: regulariser ? motifRegul.trim() : undefined,
      })
      const erreurs = res?.regularisation_erreurs ?? []
      const faites = res?.regularisations ?? []
      if (erreurs.length > 0) {
        // La caisse est ouverte malgré tout : on ne bloque jamais sur un écart.
        notifyError('Écart non régularisé', erreurs.join(' / '))
      } else if (faites.length > 0) {
        notifySuccess(
          'Caisse ouverte',
          `Écart régularisé : ${faites.map((r) => `${r.montant} ${r.devise}`).join(', ')}.`,
        )
      } else {
        notifySuccess('Caisse ouverte', 'Les opérations de caisse sont maintenant autorisées.')
      }
      setShowModal(false)
      setUsd(''); setCdf(''); setObs(''); setRegulariser(false); setMotifRegul('')
      window.dispatchEvent(new Event('cash-closure-updated'))
      await load()
      onChanged?.()
    } catch (e: any) {
      notifyError('Erreur', e?.message || "Impossible d'ouvrir la caisse.")
    } finally {
      setSubmitting(false)
    }
  }

  if (loading || !status) return null

  if (status.est_ouverte) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        background: '#ecfdf5', border: '1px solid #6ee7b7', color: '#065f46',
        borderRadius: 12, padding: '10px 14px', marginBottom: 16, fontSize: 13, fontWeight: 600,
      }}>
        <span>● Caisse ouverte</span>
        {status.ouverte_le && (
          <span style={{ fontWeight: 400 }}>depuis le {format(new Date(status.ouverte_le), 'dd/MM/yyyy HH:mm')}</span>
        )}
      </div>
    )
  }

  return (
    <>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
        background: '#fff4dd', border: '1px solid #fcd34d', color: '#92400e',
        borderRadius: 12, padding: '12px 16px', marginBottom: 16,
      }}>
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>
          ● Caisse fermée — les opérations de caisse sont bloquées.
          <span style={{ fontWeight: 400, marginLeft: 6 }}>Ouvrez la caisse pour opérer.</span>
        </div>
        {(
          <button
            type="button"
            onClick={() => {
              // Pré-remplir avec le solde attendu (report de la dernière clôture).
              setUsd(status.solde_usd ? String(Number(status.solde_usd)) : '')
              setCdf(status.solde_cdf ? String(Number(status.solde_cdf)) : '')
              setShowModal(true)
            }}
            style={{ background: '#d97706', color: '#fff', border: 'none', borderRadius: 10, padding: '9px 16px', fontWeight: 700 }}
          >
            Ouvrir la caisse
          </button>
        )}
      </div>

      {showModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', zIndex: 500,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div style={{ background: '#fff', borderRadius: 16, padding: 22, width: 'min(440px, 100%)', boxShadow: '0 20px 50px -12px rgba(15,23,42,0.35)' }}>
            <h3 style={{ margin: '0 0 4px' }}>Ouverture de caisse</h3>
            <p style={{ margin: '0 0 16px', color: '#64748b', fontSize: 13 }}>
              Saisis le fond de caisse compté au démarrage. Ce montant devient le solde d'ouverture.
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <label style={{ flex: '1 1 140px', fontSize: 12, fontWeight: 600, color: '#475569' }}>
                Fond USD
                <input type="number" min="0" step="0.01" value={usd} onChange={(e) => setUsd(e.target.value)} placeholder="0.00"
                  style={{ width: '100%', marginTop: 4, padding: 10, border: '1px solid #cbd5e1', borderRadius: 10 }} />
              </label>
              <label style={{ flex: '1 1 140px', fontSize: 12, fontWeight: 600, color: '#475569' }}>
                Fond CDF
                <input type="number" min="0" step="0.01" value={cdf} onChange={(e) => setCdf(e.target.value)} placeholder="0"
                  style={{ width: '100%', marginTop: 4, padding: 10, border: '1px solid #cbd5e1', borderRadius: 10 }} />
              </label>
            </div>
            {(() => {
              const attenduUsd = Number(status.solde_usd || 0)
              const attenduCdf = Number(status.solde_cdf || 0)
              const ecartUsd = (parseFloat(usd) || 0) - attenduUsd
              const ecartCdf = (parseFloat(cdf) || 0) - attenduCdf
              const hasEcart = Math.abs(ecartUsd) > 0.009 || Math.abs(ecartCdf) > 0.009
              return (
                <div style={{
                  marginTop: 12, padding: '10px 12px', borderRadius: 10, fontSize: 12.5,
                  background: hasEcart ? '#fff4dd' : '#f1f5f9',
                  border: `1px solid ${hasEcart ? '#fcd34d' : '#e2e8f0'}`,
                  color: hasEcart ? '#92400e' : '#475569',
                }}>
                  Solde attendu (dernière clôture) : <strong>{attenduUsd.toFixed(2)} USD</strong> / <strong>{attenduCdf.toFixed(2)} CDF</strong>
                  {hasEcart && (
                    <>
                      <div style={{ marginTop: 4, fontWeight: 600 }}>
                        ⚠ Écart : {ecartUsd >= 0 ? '+' : ''}{ecartUsd.toFixed(2)} USD, {ecartCdf >= 0 ? '+' : ''}{ecartCdf.toFixed(2)} CDF
                      </div>
                      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 10, fontWeight: 600, cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={regulariser}
                          onChange={(e) => setRegulariser(e.target.checked)}
                          style={{ marginTop: 2 }}
                        />
                        <span>
                          Régulariser cet écart
                          <span style={{ display: 'block', fontWeight: 400, marginTop: 2 }}>
                            Crée {ecartUsd + ecartCdf >= 0 ? 'un encaissement' : 'une sortie'} de
                            régularisation. Sans cela, la caisse s’ouvre sur le solde théorique et
                            l’écart reste à traiter.
                          </span>
                        </span>
                      </label>
                      {regulariser && (
                        <input
                          value={motifRegul}
                          onChange={(e) => setMotifRegul(e.target.value)}
                          placeholder="Motif de la régularisation (obligatoire)"
                          style={{
                            width: '100%', marginTop: 8, padding: 9,
                            border: `1px solid ${motifRegul.trim() ? '#cbd5e1' : '#f59e0b'}`,
                            borderRadius: 10, fontSize: 13,
                          }}
                        />
                      )}
                    </>
                  )}
                </div>
              )
            })()}

            <label style={{ display: 'block', marginTop: 12, fontSize: 12, fontWeight: 600, color: '#475569' }}>
              Observation
              <input value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Optionnel"
                style={{ width: '100%', marginTop: 4, padding: 10, border: '1px solid #cbd5e1', borderRadius: 10 }} />
            </label>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 }}>
              <button type="button" onClick={() => setShowModal(false)} disabled={submitting}
                style={{ background: '#fff', border: '1px solid #cbd5e1', borderRadius: 10, padding: '9px 16px', fontWeight: 600 }}>
                Annuler
              </button>
              <button type="button" onClick={submit} disabled={submitting}
                style={{ background: '#0f766e', color: '#fff', border: 'none', borderRadius: 10, padding: '9px 18px', fontWeight: 700 }}>
                {submitting ? 'Ouverture…' : 'Confirmer l’ouverture'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
