import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { format } from 'date-fns'
import { getServices } from '../api/services'
import { getBudgetPostes } from '../api/budget'
import {
  listOrdresDecaissement,
  createOrdreDecaissement,
  annulerOrdreDecaissement,
} from '../api/ordresDecaissement'
import type { Service } from '../types'
import type { BudgetPosteSummary } from '../types/budget'
import type { OrdreDecaissement } from '../types'
import { toNumber } from '../utils/amount'
import { useToast } from '../hooks/useToast'
import PageHeader from '../components/PageHeader'
import styles from './SortieDirecteProgrammee.module.css'

const LIMITE_USD = 100

interface LigneForm {
  budget_poste_id: number | null
  description: string
  montant: string
}

const emptyLigne = (): LigneForm => ({ budget_poste_id: null, description: '', montant: '' })

const fmtMontant = (v: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: devise === 'CDF' ? 'CDF' : 'USD' }).format(
    toNumber(v as any)
  )

const statutLabel = (s: string) =>
  s === 'PAYE' ? 'Payé par la caisse' : s === 'ANNULE' ? 'Annulé' : 'En attente caisse'

const personName = (u?: { prenom?: string | null; nom?: string | null; email?: string | null } | null) => {
  if (!u) return '—'
  const full = `${u.prenom || ''} ${u.nom || ''}`.trim()
  return full || u.email || '—'
}

export default function SortieDirecteProgrammee() {
  const { notifySuccess, notifyError, notifyWarning } = useToast()

  const [services, setServices] = useState<Service[]>([])
  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [ordres, setOrdres] = useState<OrdreDecaissement[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [serviceId, setServiceId] = useState<string>('')
  const [beneficiaire, setBeneficiaire] = useState('')
  const [devise, setDevise] = useState<'USD' | 'CDF'>('USD')
  const [motif, setMotif] = useState('')
  const [lignes, setLignes] = useState<LigneForm[]>([emptyLigne()])

  const postesById = useMemo(() => {
    const m = new Map<number, BudgetPosteSummary>()
    postes.forEach((p) => m.set(p.id, p))
    return m
  }, [postes])

  const total = useMemo(
    () => lignes.reduce((sum, l) => sum + (Number.isFinite(parseFloat(l.montant)) ? parseFloat(l.montant) : 0), 0),
    [lignes]
  )

  const loadOrdres = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listOrdresDecaissement({ sans_requisition: true, limit: 100 })
      setOrdres(res.items || [])
    } catch (err) {
      console.error('Erreur chargement sorties directes:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const [srv, bud] = await Promise.all([
          getServices({ active: true }),
          getBudgetPostes({ type: 'DEPENSE', active: true }),
        ])
        setServices(Array.isArray(srv) ? srv : [])
        setPostes(bud?.postes || [])
      } catch (err) {
        console.error('Erreur chargement données:', err)
      }
    })()
    void loadOrdres()
  }, [loadOrdres])

  const updateLigne = (index: number, field: keyof LigneForm, value: string) => {
    setLignes((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: field === 'budget_poste_id' ? (value ? Number(value) : null) : value }
      return next
    })
  }

  const addLigne = () => setLignes((prev) => [...prev, emptyLigne()])
  const removeLigne = (index: number) =>
    setLignes((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev))

  const resetForm = () => {
    setServiceId('')
    setBeneficiaire('')
    setMotif('')
    setDevise('USD')
    setLignes([emptyLigne()])
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!serviceId) {
      notifyWarning('Service requis', 'Choisissez le service / la commission responsable.')
      return
    }
    if (!beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Saisissez le bénéficiaire.')
      return
    }
    const lignesValides = lignes.filter((l) => l.budget_poste_id && parseFloat(l.montant) > 0)
    if (lignesValides.length === 0) {
      notifyWarning('Lignes incomplètes', 'Chaque ligne doit avoir un poste budgétaire et un montant positif.')
      return
    }
    if (total <= 0) {
      notifyWarning('Montant invalide', 'Le total doit être supérieur à 0.')
      return
    }
    if (devise === 'USD' && total > LIMITE_USD) {
      notifyWarning('Plafond dépassé', `Sortie directe limitée à ${LIMITE_USD} $. Au-delà, créez une réquisition.`)
      return
    }

    setSubmitting(true)
    try {
      await createOrdreDecaissement({
        beneficiaire: beneficiaire.trim(),
        montant: total,
        devise,
        motif: motif.trim() || null,
        service_id: Number(serviceId),
        lignes: lignesValides.map((l) => ({
          budget_poste_id: l.budget_poste_id,
          rubrique: l.budget_poste_id ? postesById.get(l.budget_poste_id)?.code || '' : '',
          description: l.description.trim(),
          montant_total: parseFloat(l.montant),
          devise,
        })),
      })
      notifySuccess(
        'Sortie directe programmée',
        `${fmtMontant(total, devise)} pour ${beneficiaire.trim()} — en attente de paiement par la caisse.`
      )
      resetForm()
      await loadOrdres()
    } catch (err: any) {
      notifyError('Erreur', err?.message || 'Impossible de programmer cette sortie directe.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (ordre: OrdreDecaissement) => {
    const raison = window.prompt(`Motif d'annulation de l'ordre ${ordre.numero_ordre} :`)
    if (!raison || raison.trim().length < 3) return
    try {
      await annulerOrdreDecaissement(String(ordre.id), raison.trim())
      notifySuccess('Ordre annulé', `L'ordre ${ordre.numero_ordre} a été annulé.`)
      await loadOrdres()
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible d'annuler cet ordre.")
    }
  }

  const capDepasse = devise === 'USD' && total > LIMITE_USD

  return (
    <div className={styles.container}>
      <PageHeader
        title="Sortie directe programmée"
        subtitle={`Dépense définie en amont (service + postes budgétaires), plafonnée à ${LIMITE_USD} $, payée directement par la caisse — sans passer par les sorties de fonds.`}
      />

      <form className={styles.card} onSubmit={handleSubmit}>
        <div className={styles.row}>
          <div className={styles.field}>
            <label>Service / commission *</label>
            <select value={serviceId} onChange={(e) => setServiceId(e.target.value)} required>
              <option value="">— Choisir —</option>
              {services.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} — {s.libelle}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label>Bénéficiaire *</label>
            <input value={beneficiaire} onChange={(e) => setBeneficiaire(e.target.value)} placeholder="Nom du bénéficiaire" required />
          </div>
          <div className={styles.fieldSmall}>
            <label>Devise</label>
            <select value={devise} onChange={(e) => setDevise(e.target.value as 'USD' | 'CDF')}>
              <option value="USD">USD</option>
              <option value="CDF">CDF</option>
            </select>
          </div>
        </div>

        <div className={styles.lignesHead}>
          <span>Lignes budgétaires</span>
          <button type="button" className={styles.addBtn} onClick={addLigne}>+ Ajouter une ligne</button>
        </div>

        {lignes.map((l, i) => (
          <div key={i} className={styles.ligne}>
            <div className={styles.ligneField} style={{ flex: '2 1 220px' }}>
              <label>Poste budgétaire *</label>
              <select value={l.budget_poste_id ?? ''} onChange={(e) => updateLigne(i, 'budget_poste_id', e.target.value)}>
                <option value="">— Choisir —</option>
                {postes.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} — {p.libelle} (disp. {fmtMontant(p.montant_disponible, 'USD')})
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.ligneField} style={{ flex: '3 1 240px' }}>
              <label>Description</label>
              <input value={l.description} onChange={(e) => updateLigne(i, 'description', e.target.value)} placeholder="Détail de la dépense" />
            </div>
            <div className={styles.ligneField} style={{ flex: '0 1 130px' }}>
              <label>Montant ({devise}) *</label>
              <input type="number" min="0.01" step="0.01" value={l.montant} onChange={(e) => updateLigne(i, 'montant', e.target.value)} placeholder="0.00" />
            </div>
            <button type="button" className={styles.removeBtn} onClick={() => removeLigne(i)} disabled={lignes.length === 1} aria-label="Retirer la ligne">✕</button>
          </div>
        ))}

        <div className={styles.field} style={{ marginTop: 12 }}>
          <label>Motif</label>
          <input value={motif} onChange={(e) => setMotif(e.target.value)} placeholder="Ex : achat urgent de fournitures" />
        </div>

        <div className={styles.footer}>
          <div className={`${styles.total} ${capDepasse ? styles.totalOver : ''}`}>
            Total : <strong>{fmtMontant(total, devise)}</strong>
            {capDepasse && <span className={styles.capWarn}> — dépasse le plafond de {LIMITE_USD} $</span>}
          </div>
          <button type="submit" className={styles.submitBtn} disabled={submitting || capDepasse}>
            {submitting ? 'Programmation…' : 'Programmer la sortie'}
          </button>
        </div>
        <p className={styles.note}>
          Une fois programmée, la sortie part directement à la caisse : montant et bénéficiaire sont verrouillés, aucune validation supplémentaire.
        </p>
      </form>

      <div className={styles.card}>
        <h3 className={styles.listTitle}>Sorties directes programmées {loading && <span className={styles.muted}>— chargement…</span>}</h3>
        {ordres.length === 0 ? (
          <p className={styles.muted}>Aucune sortie directe pour le moment.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>N° ordre</th>
                  <th>Bénéficiaire</th>
                  <th>Programmé par</th>
                  <th>Montant</th>
                  <th>Statut</th>
                  <th>Programmé le</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {ordres.map((o) => (
                  <tr key={o.id}>
                    <td style={{ fontWeight: 600 }}>{o.numero_ordre}</td>
                    <td>
                      {o.beneficiaire}
                      {o.motif && <div className={styles.subtle}>{o.motif}</div>}
                    </td>
                    <td>{personName((o as any).autorise_par_user)}</td>
                    <td style={{ fontWeight: 600 }}>{fmtMontant(o.montant, String(o.devise))}</td>
                    <td>
                      <span className={`${styles.badge} ${styles['b_' + String(o.statut)] || ''}`}>{statutLabel(String(o.statut))}</span>
                    </td>
                    <td>{o.autorise_le ? format(new Date(o.autorise_le), 'dd/MM/yyyy HH:mm') : '—'}</td>
                    <td>
                      {o.statut === 'AUTORISE' && (
                        <button type="button" className={styles.cancelBtn} onClick={() => handleCancel(o)}>Annuler</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
