import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { format } from 'date-fns'
import { listOrdresDecaissement, createOrdreDecaissement, annulerOrdreDecaissement } from '../api/ordresDecaissement'
import type { OrdreDecaissement } from '../types'
import { toNumber } from '../utils/amount'
import { useToast } from '../hooks/useToast'

const LIMITE_USD = 100

const fmtMontant = (v: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: devise === 'CDF' ? 'CDF' : 'USD' }).format(
    toNumber(v as any)
  )

const statutLabel = (s: string) =>
  s === 'PAYE' ? 'Payé par la caisse' : s === 'ANNULE' ? 'Annulé' : 'En attente caisse'

const statutColor = (s: string) =>
  s === 'PAYE'
    ? { background: '#dcfce7', color: '#166534', border: '1px solid #86efac' }
    : s === 'ANNULE'
      ? { background: '#fee2e2', color: '#991b1b', border: '1px solid #fca5a5' }
      : { background: '#e0e7ff', color: '#3730a3', border: '1px solid #a5b4fc' }

interface Props {
  onChanged?: () => void
}

export default function SortiesDirectesProgrammees({ onChanged }: Props) {
  const { notifySuccess, notifyError, notifyWarning } = useToast()
  const [ordres, setOrdres] = useState<OrdreDecaissement[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [beneficiaire, setBeneficiaire] = useState('')
  const [montant, setMontant] = useState('')
  const [devise, setDevise] = useState<'USD' | 'CDF'>('USD')
  const [motif, setMotif] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listOrdresDecaissement({ sans_requisition: true, limit: 100 })
      setOrdres(res.items || [])
    } catch (err) {
      console.error('Error loading sorties directes programmées:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    const montantNum = parseFloat(montant)
    if (!beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Veuillez saisir le bénéficiaire.')
      return
    }
    if (!Number.isFinite(montantNum) || montantNum <= 0) {
      notifyWarning('Montant invalide', 'Veuillez saisir un montant supérieur à 0.')
      return
    }
    if (devise === 'USD' && montantNum > LIMITE_USD) {
      notifyWarning('Plafond dépassé', `Sortie directe limitée à ${LIMITE_USD} $. Au-delà, créez une réquisition.`)
      return
    }
    setSubmitting(true)
    try {
      await createOrdreDecaissement({
        beneficiaire: beneficiaire.trim(),
        montant: montantNum,
        devise,
        motif: motif.trim() || null,
      })
      notifySuccess(
        'Sortie directe programmée',
        `${fmtMontant(montantNum, devise)} pour ${beneficiaire.trim()} — en attente de paiement par la caisse.`
      )
      setBeneficiaire('')
      setMontant('')
      setMotif('')
      await load()
      onChanged?.()
    } catch (err: any) {
      notifyError('Erreur', err?.message || 'Impossible de programmer cette sortie directe.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (ordre: OrdreDecaissement) => {
    const motifAnnulation = window.prompt(`Motif d'annulation de l'ordre ${ordre.numero_ordre} :`)
    if (!motifAnnulation || motifAnnulation.trim().length < 3) return
    try {
      await annulerOrdreDecaissement(String(ordre.id), motifAnnulation.trim())
      notifySuccess('Ordre annulé', `L'ordre ${ordre.numero_ordre} a été annulé.`)
      await load()
      onChanged?.()
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible d'annuler cet ordre.")
    }
  }

  const enAttente = ordres.filter((o) => o.statut === 'AUTORISE').length

  return (
    <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: '10px', padding: '14px 16px', marginBottom: '16px' }}>
      <div
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', gap: '8px', flexWrap: 'wrap' }}
        onClick={() => setOpen((v) => !v)}
      >
        <div>
          <strong style={{ color: '#92400e' }}>Sorties directes programmées (max {LIMITE_USD} $)</strong>
          <span style={{ marginLeft: '10px', fontSize: '12px', color: '#92400e' }}>
            {loading ? 'Chargement…' : `${enAttente} en attente de paiement par la caisse`}
          </span>
        </div>
        <button
          type="button"
          style={{ background: 'transparent', border: 'none', color: '#92400e', fontWeight: 700, cursor: 'pointer' }}
        >
          {open ? 'Réduire ▲' : 'Ouvrir ▼'}
        </button>
      </div>

      {open && (
        <>
          <form
            onSubmit={handleCreate}
            style={{
              display: 'flex',
              gap: '10px',
              flexWrap: 'wrap',
              alignItems: 'flex-end',
              background: '#fff',
              border: '1px solid #fde68a',
              borderRadius: '8px',
              padding: '12px',
              marginTop: '12px',
            }}
          >
            <div style={{ flex: '1 1 180px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Bénéficiaire *</label>
              <input
                type="text"
                value={beneficiaire}
                onChange={(e) => setBeneficiaire(e.target.value)}
                placeholder="Nom du bénéficiaire"
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
                required
              />
            </div>
            <div style={{ flex: '0 1 130px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Montant *</label>
              <input
                type="number"
                min="0.01"
                step="0.01"
                max={devise === 'USD' ? LIMITE_USD : undefined}
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder="0.00"
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
                required
              />
            </div>
            <div style={{ flex: '0 1 90px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Devise</label>
              <select
                value={devise}
                onChange={(e) => setDevise(e.target.value as 'USD' | 'CDF')}
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
              >
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div style={{ flex: '2 1 200px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Motif</label>
              <input
                type="text"
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
                placeholder="Ex : achat urgent de fournitures"
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              style={{
                background: '#d97706',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                padding: '9px 16px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {submitting ? 'Programmation…' : 'Programmer'}
            </button>
          </form>
          <p style={{ fontSize: '12px', color: '#92400e', margin: '8px 0 0' }}>
            La sortie sera exécutée uniquement par la caisse : montant et bénéficiaire seront verrouillés.
          </p>

          {ordres.length > 0 && (
            <div style={{ marginTop: '10px', overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', background: '#fff', borderRadius: '8px' }}>
                <thead>
                  <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
                    <th style={{ padding: '8px' }}>N° ordre</th>
                    <th style={{ padding: '8px' }}>Bénéficiaire</th>
                    <th style={{ padding: '8px' }}>Montant</th>
                    <th style={{ padding: '8px' }}>Statut</th>
                    <th style={{ padding: '8px' }}>Programmé le</th>
                    <th style={{ padding: '8px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {ordres.map((o) => (
                    <tr key={o.id} style={{ borderTop: '1px solid #e5e7eb' }}>
                      <td style={{ padding: '8px', fontWeight: 600 }}>{o.numero_ordre}</td>
                      <td style={{ padding: '8px' }}>
                        {o.beneficiaire}
                        {o.motif && <div style={{ fontSize: '11px', color: '#6b7280' }}>{o.motif}</div>}
                      </td>
                      <td style={{ padding: '8px', fontWeight: 600 }}>{fmtMontant(o.montant, String(o.devise))}</td>
                      <td style={{ padding: '8px' }}>
                        <span style={{ padding: '3px 8px', borderRadius: '6px', fontSize: '11px', fontWeight: 600, display: 'inline-block', ...statutColor(String(o.statut)) }}>
                          {statutLabel(String(o.statut))}
                        </span>
                        {o.statut === 'PAYE' && o.sortie_reference_numero && (
                          <div style={{ fontSize: '11px', color: '#6b7280' }}>Réf. {o.sortie_reference_numero}</div>
                        )}
                      </td>
                      <td style={{ padding: '8px' }}>
                        {o.autorise_le ? format(new Date(o.autorise_le), 'dd/MM/yyyy HH:mm') : '—'}
                      </td>
                      <td style={{ padding: '8px' }}>
                        {o.statut === 'AUTORISE' && (
                          <button
                            type="button"
                            onClick={() => handleCancel(o)}
                            style={{
                              background: 'transparent',
                              color: '#b91c1c',
                              border: '1px solid #fca5a5',
                              borderRadius: '6px',
                              padding: '4px 10px',
                              fontSize: '12px',
                              cursor: 'pointer',
                            }}
                          >
                            Annuler
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
