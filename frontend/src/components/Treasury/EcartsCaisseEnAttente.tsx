import { useCallback, useEffect, useState } from 'react'
import { format } from 'date-fns'
import { listEcartsCaisse, regulariserEcart, type EcartCaisse } from '../../api/clotures'
import { useToast } from '../../hooks/useToast'

/**
 * Écarts de caisse constatés à un comptage mais laissés sans régularisation.
 *
 * Un écart non régularisé n'est pas une anomalie : l'utilisateur a pu refuser
 * la régularisation au moment du comptage. Il reste listé ici pour être traité
 * plus tard — sans cet écran, un refus deviendrait un oubli silencieux.
 */
export default function EcartsCaisseEnAttente({ onChanged }: { onChanged?: () => void }) {
  const { notifySuccess, notifyError } = useToast()
  const [ecarts, setEcarts] = useState<EcartCaisse[]>([])
  const [loading, setLoading] = useState(true)
  const [cible, setCible] = useState<EcartCaisse | null>(null)
  const [motif, setMotif] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setEcarts(await listEcartsCaisse(true))
    } catch {
      setEcarts([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    if (!cible || !motif.trim()) return
    setSubmitting(true)
    try {
      const res = await regulariserEcart(cible.source_type, cible.source_id, motif.trim(), cible.devise)
      const faites = res.regularisations ?? []
      notifySuccess(
        'Écart régularisé',
        faites.map((r) => `${r.montant} ${r.devise}`).join(', ') || 'Opération créée.',
      )
      setCible(null)
      setMotif('')
      await load()
      window.dispatchEvent(new Event('cash-closure-updated'))
      onChanged?.()
    } catch (e: any) {
      notifyError('Régularisation impossible', e?.payload?.detail || e?.message || 'Échec.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading || ecarts.length === 0) return null

  return (
    <section
      style={{
        background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 12,
        padding: '14px 16px', marginBottom: 16,
      }}
    >
      <strong style={{ display: 'block', marginBottom: 4, color: '#92400e', fontSize: 14 }}>
        {ecarts.length} écart{ecarts.length > 1 ? 's' : ''} de caisse en attente de régularisation
      </strong>
      <p style={{ margin: '0 0 10px', fontSize: 12.5, color: '#78350f', lineHeight: 1.5 }}>
        Ces écarts ont été constatés lors d’un comptage sans qu’une opération soit créée. Tant
        qu’ils ne sont pas régularisés, le solde du logiciel diffère du montant compté.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#92400e' }}>
              <th style={{ padding: '6px 8px' }}>Origine</th>
              <th style={{ padding: '6px 8px' }}>Référence</th>
              <th style={{ padding: '6px 8px' }}>Date</th>
              <th style={{ padding: '6px 8px', textAlign: 'right' }}>Écart</th>
              <th style={{ padding: '6px 8px' }}>Sens</th>
              <th style={{ padding: '6px 8px' }} />
            </tr>
          </thead>
          <tbody>
            {ecarts.map((e) => (
              <tr key={`${e.source_type}-${e.source_id}-${e.devise}`} style={{ borderTop: '1px solid #fde68a' }}>
                <td style={{ padding: '6px 8px' }}>
                  {e.source_type === 'OUVERTURE' ? 'Ouverture' : 'Clôture'}
                </td>
                <td style={{ padding: '6px 8px' }}>{e.reference_numero}</td>
                <td style={{ padding: '6px 8px' }}>
                  {e.date ? format(new Date(e.date), 'dd/MM/yyyy HH:mm') : '—'}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700 }}>
                  {Number(e.ecart) >= 0 ? '+' : ''}
                  {Number(e.ecart).toFixed(2)} {e.devise}
                </td>
                <td style={{ padding: '6px 8px' }}>
                  {e.sens === 'EXCEDENT' ? 'Excédent' : 'Déficit'}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                  <button
                    type="button"
                    onClick={() => { setCible(e); setMotif('') }}
                    style={{
                      background: '#b45309', color: '#fff', border: 'none', borderRadius: 8,
                      padding: '5px 12px', fontWeight: 600, fontSize: 12.5, cursor: 'pointer',
                    }}
                  >
                    Régulariser
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {cible && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
        >
          <div style={{ background: '#fff', borderRadius: 14, padding: 22, width: 'min(460px, 92vw)' }}>
            <h3 style={{ margin: '0 0 10px', fontSize: 16 }}>Régulariser l’écart</h3>
            <p style={{ margin: '0 0 14px', fontSize: 13, color: '#475569', lineHeight: 1.5 }}>
              {cible.reference_numero} — écart de{' '}
              <strong>
                {Number(cible.ecart) >= 0 ? '+' : ''}
                {Number(cible.ecart).toFixed(2)} {cible.devise}
              </strong>
              . Cette action crée{' '}
              {cible.sens === 'EXCEDENT' ? 'un encaissement' : 'une sortie'} de régularisation du
              même montant, et aligne le solde du logiciel sur le comptage.
            </p>
            <input
              value={motif}
              onChange={(ev) => setMotif(ev.target.value)}
              placeholder="Motif de la régularisation (obligatoire)"
              style={{
                width: '100%', padding: 10, border: '1px solid #cbd5e1',
                borderRadius: 10, fontSize: 13,
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 }}>
              <button
                type="button"
                onClick={() => setCible(null)}
                disabled={submitting}
                style={{ background: '#fff', border: '1px solid #cbd5e1', borderRadius: 10, padding: '9px 16px', fontWeight: 600 }}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting || !motif.trim()}
                style={{
                  background: motif.trim() ? '#b45309' : '#cbd5e1', color: '#fff', border: 'none',
                  borderRadius: 10, padding: '9px 18px', fontWeight: 700,
                  cursor: motif.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {submitting ? 'Régularisation…' : 'Confirmer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
