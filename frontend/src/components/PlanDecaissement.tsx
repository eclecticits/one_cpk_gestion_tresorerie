import { useCallback, useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { format } from 'date-fns'
import { listOrdresDecaissement, createOrdreDecaissement, annulerOrdreDecaissement } from '../api/ordresDecaissement'
import type { OrdreDecaissement, Requisition } from '../types'
import { toNumber } from '../utils/amount'
import { useToast } from '../hooks/useToast'

interface PlanDecaissementProps {
  requisition: Requisition
  currentUserId?: string | null
  canAuthorize: boolean
  isAdmin?: boolean
  onChanged?: () => void
}

const fmtUsd = (v: unknown) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(v as any))

const badgeStyle = (statut: string): CSSProperties => {
  const base: CSSProperties = {
    padding: '3px 8px',
    borderRadius: '6px',
    fontSize: '11px',
    fontWeight: 600,
    display: 'inline-block',
  }
  if (statut === 'PAYE') return { ...base, background: '#dcfce7', color: '#166534', border: '1px solid #86efac' }
  if (statut === 'ANNULE') return { ...base, background: '#fee2e2', color: '#991b1b', border: '1px solid #fca5a5' }
  return { ...base, background: '#e0e7ff', color: '#3730a3', border: '1px solid #a5b4fc' }
}

const statutLabel = (statut: string) =>
  statut === 'PAYE' ? 'Payé' : statut === 'ANNULE' ? 'Annulé' : 'Autorisé — en attente caisse'

export default function PlanDecaissement({ requisition, currentUserId, canAuthorize, isAdmin = false, onChanged }: PlanDecaissementProps) {
  const { notifySuccess, notifyError, notifyWarning } = useToast()
  const [ordres, setOrdres] = useState<OrdreDecaissement[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [totalPaye, setTotalPaye] = useState(0)
  const [totalAutorise, setTotalAutorise] = useState(0)
  const [reliquat, setReliquat] = useState<number>(toNumber(requisition.montant_total))
  const [showAddForm, setShowAddForm] = useState(false)
  const [beneficiaire, setBeneficiaire] = useState('')
  const [montant, setMontant] = useState('')
  const [motif, setMotif] = useState('')

  const reqStatus = String((requisition as any).status ?? requisition.statut ?? '').toUpperCase()
  const isCreator = !!currentUserId && String(requisition.created_by) === String(currentUserId)
  const peutAutoriser = canAuthorize && (isCreator || isAdmin) && ['APPROUVEE', 'EN_DECAISSEMENT'].includes(reqStatus)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listOrdresDecaissement({ requisition_id: String(requisition.id), limit: 200 })
      setOrdres(res.items || [])
      setTotalPaye(toNumber(res.total_paye))
      setTotalAutorise(toNumber(res.total_autorise_non_paye))
      setReliquat(
        res.reliquat != null
          ? toNumber(res.reliquat)
          : toNumber(requisition.montant_total) - toNumber(res.total_paye) - toNumber(res.total_autorise_non_paye)
      )
    } catch (err) {
      console.error('Error loading ordres de décaissement:', err)
    } finally {
      setLoading(false)
    }
  }, [requisition.id, requisition.montant_total])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    const montantNum = parseFloat(montant)
    if (!beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Veuillez saisir le bénéficiaire de la tranche.')
      return
    }
    if (!Number.isFinite(montantNum) || montantNum <= 0) {
      notifyWarning('Montant invalide', 'Veuillez saisir un montant supérieur à 0.')
      return
    }
    if (montantNum > reliquat) {
      notifyWarning('Plafond dépassé', `Reliquat disponible : ${fmtUsd(reliquat)}`)
      return
    }
    setSubmitting(true)
    try {
      await createOrdreDecaissement({
        requisition_id: String(requisition.id),
        beneficiaire: beneficiaire.trim(),
        montant: montantNum,
        motif: motif.trim() || null,
      })
      notifySuccess('Ordre autorisé', `${fmtUsd(montantNum)} pour ${beneficiaire.trim()} — la caisse peut payer.`)
      setBeneficiaire('')
      setMontant('')
      setMotif('')
      setShowAddForm(false)
      await load()
      onChanged?.()
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible d'autoriser cet ordre de décaissement.")
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

  const montantTotal = toNumber(requisition.montant_total)
  const pctPaye = montantTotal > 0 ? Math.min(100, (totalPaye / montantTotal) * 100) : 0
  const pctAutorise = montantTotal > 0 ? Math.min(100 - pctPaye, (totalAutorise / montantTotal) * 100) : 0

  return (
    <div style={{ background: '#eef2ff', borderLeft: '4px solid #6366f1', borderRadius: '8px', padding: '16px', marginTop: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <h3 style={{ color: '#4338ca', margin: 0 }}>Plan de décaissement progressif</h3>
        {peutAutoriser && (
          <button
            type="button"
            onClick={() => setShowAddForm((v) => !v)}
            style={{
              background: '#6366f1',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '8px 14px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {showAddForm ? 'Fermer' : '+ Autoriser une tranche'}
          </button>
        )}
      </div>

      {/* Barre de progression */}
      <div style={{ margin: '14px 0 6px' }}>
        <div style={{ display: 'flex', height: '10px', borderRadius: '5px', overflow: 'hidden', background: '#e5e7eb' }}>
          <div style={{ width: `${pctPaye}%`, background: '#16a34a' }} />
          <div style={{ width: `${pctAutorise}%`, background: '#818cf8' }} />
        </div>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: '#374151', marginTop: '6px' }}>
          <span><strong style={{ color: '#16a34a' }}>Payé :</strong> {fmtUsd(totalPaye)}</span>
          <span><strong style={{ color: '#4f46e5' }}>Autorisé (en attente caisse) :</strong> {fmtUsd(totalAutorise)}</span>
          <span><strong>Reliquat :</strong> {fmtUsd(reliquat)}</span>
          <span><strong>Enveloppe :</strong> {fmtUsd(montantTotal)}</span>
        </div>
      </div>

      {showAddForm && peutAutoriser && (
        <form
          onSubmit={handleCreate}
          style={{
            display: 'flex',
            gap: '10px',
            flexWrap: 'wrap',
            alignItems: 'flex-end',
            background: '#fff',
            border: '1px solid #c7d2fe',
            borderRadius: '8px',
            padding: '12px',
            marginTop: '10px',
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
          <div style={{ flex: '0 1 140px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Montant (USD) *</label>
            <input
              type="number"
              min="0.01"
              step="0.01"
              max={reliquat}
              value={montant}
              onChange={(e) => setMontant(e.target.value)}
              placeholder="0.00"
              style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
              required
            />
          </div>
          <div style={{ flex: '2 1 220px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Motif</label>
            <input
              type="text"
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              placeholder="Ex : première tranche fournisseur"
              style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
            />
          </div>
          <button
            type="submit"
            disabled={submitting || reliquat <= 0}
            style={{
              background: reliquat <= 0 ? '#9ca3af' : '#16a34a',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '9px 16px',
              fontWeight: 600,
              cursor: reliquat <= 0 ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? 'Autorisation…' : 'Autoriser'}
          </button>
        </form>
      )}

      {!peutAutoriser && canAuthorize && !isCreator && (
        <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '8px' }}>
          Seul le demandeur de cette réquisition peut autoriser des tranches.
        </p>
      )}

      <div style={{ marginTop: '12px', overflowX: 'auto' }}>
        {loading ? (
          <p style={{ fontSize: '13px', color: '#6b7280' }}>Chargement…</p>
        ) : ordres.length === 0 ? (
          <p style={{ fontSize: '13px', color: '#6b7280' }}>
            Aucun ordre de décaissement. {peutAutoriser ? 'Autorisez une première tranche pour permettre un paiement en caisse.' : ''}
          </p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', background: '#fff', borderRadius: '8px' }}>
            <thead>
              <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
                <th style={{ padding: '8px' }}>N° ordre</th>
                <th style={{ padding: '8px' }}>Bénéficiaire</th>
                <th style={{ padding: '8px' }}>Montant</th>
                <th style={{ padding: '8px' }}>Statut</th>
                <th style={{ padding: '8px' }}>Autorisé le</th>
                <th style={{ padding: '8px' }}>Paiement</th>
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
                  <td style={{ padding: '8px', fontWeight: 600 }}>{fmtUsd(o.montant)}</td>
                  <td style={{ padding: '8px' }}>
                    <span style={badgeStyle(String(o.statut))}>{statutLabel(String(o.statut))}</span>
                    {o.statut === 'ANNULE' && o.motif_annulation && (
                      <div style={{ fontSize: '11px', color: '#991b1b' }}>{o.motif_annulation}</div>
                    )}
                  </td>
                  <td style={{ padding: '8px' }}>
                    {o.autorise_le ? format(new Date(o.autorise_le), 'dd/MM/yyyy HH:mm') : '—'}
                    {o.autorise_par_user && (
                      <div style={{ fontSize: '11px', color: '#6b7280' }}>
                        {o.autorise_par_user.prenom} {o.autorise_par_user.nom}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '8px' }}>
                    {o.statut === 'PAYE' ? (
                      <>
                        {o.paye_le ? format(new Date(o.paye_le), 'dd/MM/yyyy HH:mm') : ''}
                        {o.sortie_reference_numero && (
                          <div style={{ fontSize: '11px', color: '#6b7280' }}>Réf. {o.sortie_reference_numero}</div>
                        )}
                        {o.paye_par_user && (
                          <div style={{ fontSize: '11px', color: '#6b7280' }}>
                            {o.paye_par_user.prenom} {o.paye_par_user.nom}
                          </div>
                        )}
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td style={{ padding: '8px' }}>
                    {o.statut === 'AUTORISE' && peutAutoriser && (
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
        )}
      </div>
    </div>
  )
}
