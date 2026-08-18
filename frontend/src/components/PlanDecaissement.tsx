import { useCallback, useEffect, useMemo, useState, type CSSProperties, type FormEvent } from 'react'
import { format } from 'date-fns'
import { listOrdresDecaissement, createOrdreDecaissement, annulerOrdreDecaissement } from '../api/ordresDecaissement'
import { listComptesBancaires } from '../api/banques'
import type { OrdreDecaissement, Requisition, VoletReglement } from '../types'
import type { CompteBancaire } from '../types/banque'
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

const MODE_LABELS: Record<string, string> = {
  cash: 'Espèces (caisse)',
  virement: 'Virement bancaire',
  mobile_money: 'Mobile money',
  cheque: 'Chèque',
  card: 'Carte bancaire',
}
// Modes proposés quand la réquisition n'a aucune ligne pour dicter ses volets.
const MODES_PAR_DEFAUT = ['cash', 'virement', 'mobile_money', 'cheque', 'card']

const normaliserMode = (mode: unknown) => String(mode ?? '').trim().toLowerCase()
// Seules les espèces sortent de la caisse ; tout le reste part d'un compte.
const canalDuMode = (mode: unknown) => (normaliserMode(mode) === 'cash' ? 'CAISSE' : 'BANQUE')
const modeLabel = (mode: unknown) => MODE_LABELS[normaliserMode(mode)] || normaliserMode(mode) || '—'
/** Identité d'un volet : le couple (mode, compte) et rien d'autre. */
const cleVolet = (mode: unknown, compteId: unknown) =>
  `${normaliserMode(mode)}|${compteId == null || compteId === '' ? '' : String(compteId)}`

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
  const [montantsPoste, setMontantsPoste] = useState<Record<number, string>>({})
  const [modeTranche, setModeTranche] = useState('')
  const [compteTranche, setCompteTranche] = useState('')
  const [comptes, setComptes] = useState<CompteBancaire[]>([])

  // Volets de règlement de la réquisition. Le détail serveur les fournit ; quand
  // l'écran appelant n'a chargé qu'un résumé, on les relit des lignes avec la
  // même règle (le compte ne qualifie un volet que du côté banque).
  const volets = useMemo<VoletReglement[]>(() => {
    const fournis = requisition.volets_reglement
    if (fournis && fournis.length > 0) return fournis
    const map = new Map<string, VoletReglement>()
    for (const l of requisition.lignes || []) {
      const mode = normaliserMode(l.mode_paiement) || normaliserMode(requisition.mode_paiement) || 'cash'
      const canal = canalDuMode(mode)
      const compte = canal === 'CAISSE' ? null : l.compte_bancaire_id ?? null
      const cle = cleVolet(mode, compte)
      const courant = map.get(cle) || {
        mode_paiement: mode,
        canal,
        compte_bancaire_id: compte,
        montant_total: 0,
        lignes_ids: [] as string[],
      }
      courant.montant_total = toNumber(courant.montant_total) + toNumber(l.montant_total)
      courant.lignes_ids = [...(courant.lignes_ids || []), String(l.id)]
      map.set(cle, courant)
    }
    return Array.from(map.values())
  }, [requisition.volets_reglement, requisition.lignes, requisition.mode_paiement])

  const compteLabel = useCallback(
    (compteId: unknown) => {
      if (compteId == null || compteId === '') return 'Compte non désigné'
      const compte = comptes.find((c) => String(c.id) === String(compteId))
      if (!compte) return `Compte #${compteId}`
      return `${compte.banque?.nom || 'Banque'} — ${compte.intitule} (${compte.devise})`
    },
    [comptes]
  )
  const voletLabel = useCallback(
    (volet: { mode_paiement: unknown; compte_bancaire_id?: number | null }) =>
      canalDuMode(volet.mode_paiement) === 'CAISSE'
        ? modeLabel(volet.mode_paiement)
        : `${modeLabel(volet.mode_paiement)} · ${compteLabel(volet.compte_bancaire_id)}`,
    [compteLabel]
  )

  // Déjà engagé (autorisé + payé) volet par volet : le plafond d'un volet lui
  // est propre, une tranche caisse ne consomme pas l'enveloppe de la banque.
  const engagePerVolet = useMemo(() => {
    const acc: Record<string, { paye: number; autorise: number }> = {}
    for (const o of ordres) {
      if (o.statut !== 'AUTORISE' && o.statut !== 'PAYE') continue
      const cle = cleVolet(o.mode_paiement, o.compte_bancaire_id)
      const bucket = acc[cle] || { paye: 0, autorise: 0 }
      if (o.statut === 'PAYE') bucket.paye += toNumber(o.montant)
      else bucket.autorise += toNumber(o.montant)
      acc[cle] = bucket
    }
    return acc
  }, [ordres])

  const modesDisponibles = useMemo(() => {
    const modes = Array.from(new Set(volets.map((v) => normaliserMode(v.mode_paiement)))).filter(Boolean)
    return modes.length > 0 ? modes : MODES_PAR_DEFAUT
  }, [volets])
  // Comptes proposés : ceux des volets du mode retenu. Envoyer un autre compte
  // ne réglerait aucun volet et serait refusé par l'API.
  const comptesDuMode = useMemo(() => {
    const cibles = volets
      .filter((v) => normaliserMode(v.mode_paiement) === normaliserMode(modeTranche))
      .map((v) => v.compte_bancaire_id ?? null)
    if (cibles.length > 0) return Array.from(new Set(cibles))
    return comptes
      .filter((c) => String(c.account_type || 'BANK').toUpperCase() === 'BANK' && c.is_active !== false)
      .map((c) => c.id as number | null)
  }, [volets, modeTranche, comptes])
  const canalTranche = canalDuMode(modeTranche)
  const voletCible = useMemo(
    () =>
      volets.find(
        (v) => cleVolet(v.mode_paiement, v.compte_bancaire_id) === cleVolet(modeTranche, canalTranche === 'CAISSE' ? null : compteTranche)
      ) || null,
    [volets, modeTranche, compteTranche, canalTranche]
  )
  const reliquatVolet = useMemo(() => {
    if (!voletCible) return null
    const engage = engagePerVolet[cleVolet(voletCible.mode_paiement, voletCible.compte_bancaire_id)]
    return toNumber(voletCible.montant_total) - (engage?.paye || 0) - (engage?.autorise || 0)
  }, [voletCible, engagePerVolet])

  // Postes budgétaires de la réquisition (enveloppe par poste).
  const postes = useMemo(() => {
    const map = new Map<number, { id: number; libelle: string; enveloppe: number }>()
    for (const l of requisition.lignes || []) {
      if (l.budget_poste_id == null) continue
      const id = Number(l.budget_poste_id)
      const cur = map.get(id) || {
        id,
        libelle: l.budget_poste_libelle_snapshot || l.rubrique || `Poste ${id}`,
        enveloppe: 0,
      }
      cur.enveloppe += toNumber(l.montant_total)
      map.set(id, cur)
    }
    return Array.from(map.values())
  }, [requisition.lignes])
  const isMulti = postes.length > 1

  // Déjà engagé (autorisé + payé) par poste, lu dans les lignes des ordres.
  const engagePerPoste = useMemo(() => {
    const acc: Record<number, number> = {}
    for (const o of ordres) {
      if (o.statut !== 'AUTORISE' && o.statut !== 'PAYE') continue
      for (const l of o.lignes || []) {
        if (l.budget_poste_id == null) continue
        const id = Number(l.budget_poste_id)
        acc[id] = (acc[id] || 0) + toNumber(l.montant ?? l.montant_total)
      }
    }
    return acc
  }, [ordres])
  // Détail par statut (payé / autorisé en attente) par poste, pour présenter à
  // chaque nouvelle tranche ce qui a déjà été libéré et ce qui reste.
  const detailPerPoste = useMemo(() => {
    const paye: Record<number, number> = {}
    const autorise: Record<number, number> = {}
    for (const o of ordres) {
      const bucket = o.statut === 'PAYE' ? paye : o.statut === 'AUTORISE' ? autorise : null
      if (!bucket) continue
      for (const l of o.lignes || []) {
        if (l.budget_poste_id == null) continue
        const id = Number(l.budget_poste_id)
        bucket[id] = (bucket[id] || 0) + toNumber(l.montant ?? l.montant_total)
      }
    }
    return { paye, autorise }
  }, [ordres])
  const totalReparti = useMemo(
    () => postes.reduce((s, p) => s + (parseFloat(montantsPoste[p.id] || '') || 0), 0),
    [postes, montantsPoste]
  )

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

  // Les comptes ne servent qu'à nommer le volet bancaire : un échec de
  // chargement dégrade l'affichage (numéro de compte brut) sans bloquer.
  useEffect(() => {
    let annule = false
    listComptesBancaires({ active: true })
      .then((res) => {
        if (!annule) setComptes(res || [])
      })
      .catch(() => {
        if (!annule) setComptes([])
      })
    return () => {
      annule = true
    }
  }, [])

  // Volet proposé par défaut : le premier qui n'est pas encore soldé, sinon le
  // premier tout court. Le demandeur a proposé un règlement, l'autorisateur
  // n'a plus qu'à confirmer — ou à le changer.
  useEffect(() => {
    if (modeTranche && modesDisponibles.includes(normaliserMode(modeTranche))) return
    const ouvert =
      volets.find((v) => {
        const engage = engagePerVolet[cleVolet(v.mode_paiement, v.compte_bancaire_id)]
        return toNumber(v.montant_total) - (engage?.paye || 0) - (engage?.autorise || 0) > 0.001
      }) || volets[0]
    const mode = normaliserMode(ouvert?.mode_paiement) || normaliserMode(requisition.mode_paiement) || 'cash'
    setModeTranche(modesDisponibles.includes(mode) ? mode : modesDisponibles[0])
    setCompteTranche(ouvert?.compte_bancaire_id != null ? String(ouvert.compte_bancaire_id) : '')
  }, [volets, modesDisponibles, engagePerVolet, modeTranche, requisition.mode_paiement])

  // Le compte suit le mode : changer de mode invalide le compte du volet
  // précédent, on retombe sur l'unique compte du nouveau mode quand il n'y a
  // pas d'ambiguïté.
  useEffect(() => {
    if (canalTranche === 'CAISSE') {
      if (compteTranche !== '') setCompteTranche('')
      return
    }
    const valeurs = comptesDuMode.map((c) => (c == null ? '' : String(c)))
    if (valeurs.includes(compteTranche)) return
    setCompteTranche(valeurs.length === 1 ? valeurs[0] : '')
  }, [canalTranche, comptesDuMode, compteTranche])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!beneficiaire.trim()) {
      notifyWarning('Bénéficiaire requis', 'Veuillez saisir le bénéficiaire de la tranche.')
      return
    }

    let montantNum: number
    let lignes: { budget_poste_id: number; montant: number }[] | undefined

    if (isMulti) {
      lignes = postes
        .map((p) => ({ budget_poste_id: p.id, montant: parseFloat(montantsPoste[p.id] || '') || 0 }))
        .filter((l) => l.montant > 0)
      if (lignes.length === 0) {
        notifyWarning('Montant requis', 'Saisissez un montant sur au moins un poste budgétaire.')
        return
      }
      for (const p of postes) {
        const m = parseFloat(montantsPoste[p.id] || '') || 0
        const reste = p.enveloppe - (engagePerPoste[p.id] || 0)
        if (m > reste + 0.001) {
          notifyWarning('Enveloppe du poste dépassée', `${p.libelle} : reste ${fmtUsd(reste)}`)
          return
        }
      }
      montantNum = lignes.reduce((s, l) => s + l.montant, 0)
    } else {
      montantNum = parseFloat(montant)
      if (!Number.isFinite(montantNum) || montantNum <= 0) {
        notifyWarning('Montant invalide', 'Veuillez saisir un montant supérieur à 0.')
        return
      }
    }

    if (montantNum > reliquat + 0.001) {
      notifyWarning('Plafond dépassé', `Reliquat disponible : ${fmtUsd(reliquat)}`)
      return
    }

    if (!modeTranche) {
      notifyWarning('Volet requis', 'Précisez le mode de règlement de cette tranche.')
      return
    }
    if (canalTranche === 'BANQUE' && !compteTranche) {
      notifyWarning('Compte requis', 'Un règlement bancaire doit désigner le compte à débiter.')
      return
    }
    // Chaque volet est une enveloppe autonome : le reliquat global ne dit rien
    // de ce qui reste sur celui que cette tranche règle.
    if (reliquatVolet != null && montantNum > reliquatVolet + 0.001) {
      notifyWarning(
        'Enveloppe du volet dépassée',
        `${voletCible ? voletLabel(voletCible) : 'Volet'} : reste ${fmtUsd(reliquatVolet)}`
      )
      return
    }
    setSubmitting(true)
    try {
      await createOrdreDecaissement({
        requisition_id: String(requisition.id),
        beneficiaire: beneficiaire.trim(),
        montant: montantNum,
        motif: motif.trim() || null,
        lignes,
        mode_paiement: modeTranche,
        compte_bancaire_id: canalTranche === 'BANQUE' && compteTranche ? Number(compteTranche) : null,
      })
      notifySuccess('Ordre autorisé', `${fmtUsd(montantNum)} pour ${beneficiaire.trim()} — la caisse peut payer.`)
      setBeneficiaire('')
      setMontant('')
      setMotif('')
      setMontantsPoste({})
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

      {/* Suivi par poste budgétaire : enveloppe, payé, autorisé, reste. Permet de
          libérer plusieurs tranches sans dépasser ce que la réquisition a défini. */}
      {postes.length > 0 && (
        <div style={{ marginTop: '10px', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', background: '#fff', borderRadius: '8px' }}>
            <thead>
              <tr style={{ background: '#eef2ff', textAlign: 'left', color: '#4338ca' }}>
                <th style={{ padding: '6px 8px' }}>Poste budgétaire</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Enveloppe</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Payé</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Autorisé</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Reste</th>
              </tr>
            </thead>
            <tbody>
              {postes.map((p) => {
                const paye = detailPerPoste.paye[p.id] || 0
                const autorise = detailPerPoste.autorise[p.id] || 0
                const reste = p.enveloppe - paye - autorise
                return (
                  <tr key={p.id} style={{ borderTop: '1px solid #e5e7eb' }}>
                    <td style={{ padding: '6px 8px' }}>{p.libelle}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtUsd(p.enveloppe)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', color: '#16a34a' }}>{fmtUsd(paye)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', color: '#4f46e5' }}>{fmtUsd(autorise)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: reste <= 0.001 ? '#991b1b' : '#111827' }}>{fmtUsd(reste)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Volets de règlement : la réquisition peut sortir de plusieurs endroits.
          Chaque volet a sa propre enveloppe et se solde indépendamment. */}
      {volets.length > 0 && (
        <div style={{ marginTop: '10px', overflowX: 'auto' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#4338ca', marginBottom: '4px' }}>
            Volets de règlement {volets.length > 1 ? `(${volets.length})` : ''}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', background: '#fff', borderRadius: '8px' }}>
            <thead>
              <tr style={{ background: '#eef2ff', textAlign: 'left', color: '#4338ca' }}>
                <th style={{ padding: '6px 8px' }}>Volet</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Enveloppe</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Payé</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Autorisé</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Reliquat</th>
              </tr>
            </thead>
            <tbody>
              {volets.map((v) => {
                const cle = cleVolet(v.mode_paiement, v.compte_bancaire_id)
                const engage = engagePerVolet[cle]
                const paye = engage?.paye || 0
                const autorise = engage?.autorise || 0
                const reste = toNumber(v.montant_total) - paye - autorise
                return (
                  <tr key={cle} style={{ borderTop: '1px solid #e5e7eb' }}>
                    <td style={{ padding: '6px 8px' }}>
                      {voletLabel(v)}
                      <span style={{ color: '#6b7280', fontSize: '11px' }}> — {canalDuMode(v.mode_paiement) === 'CAISSE' ? 'sort de la caisse' : 'sort de la banque'}</span>
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtUsd(v.montant_total)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', color: '#16a34a' }}>{fmtUsd(paye)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', color: '#4f46e5' }}>{fmtUsd(autorise)}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: reste <= 0.001 ? '#991b1b' : '#111827' }}>{fmtUsd(reste)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

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
          {isMulti ? (
            <div style={{ flex: '1 1 100%' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '6px' }}>
                Répartition par poste budgétaire *
              </label>
              <div style={{ display: 'grid', gap: '6px' }}>
                {postes.map((p) => {
                  const reste = p.enveloppe - (engagePerPoste[p.id] || 0)
                  return (
                    <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <span style={{ flex: '1 1 220px', fontSize: '13px', color: '#374151' }}>
                        {p.libelle}
                        <span style={{ color: '#6b7280', fontSize: '11px' }}> — reste {fmtUsd(reste)}</span>
                      </span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        max={reste}
                        value={montantsPoste[p.id] || ''}
                        onChange={(e) => setMontantsPoste((prev) => ({ ...prev, [p.id]: e.target.value }))}
                        placeholder="0.00"
                        style={{ flex: '0 1 130px', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
                      />
                    </div>
                  )
                })}
              </div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#4338ca', marginTop: '6px' }}>
                Total de la tranche : {fmtUsd(totalReparti)}
              </div>
            </div>
          ) : (
            <div style={{ flex: '0 1 140px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>Montant (USD) *</label>
              <input
                type="number"
                min="0.01"
                step="0.01"
                max={reliquatVolet != null ? Math.min(reliquat, reliquatVolet) : reliquat}
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder="0.00"
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
              />
            </div>
          )}
          {/* Volet réglé par la tranche : c'est ici que la décision se prend. Le
              mode saisi par le demandeur n'est qu'une proposition, et la caisse
              n'aura plus rien à choisir en aval. */}
          <div style={{ flex: '1 1 100%', display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ flex: '1 1 200px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>
                Volet réglé — mode *
              </label>
              <select
                value={modeTranche}
                onChange={(e) => setModeTranche(e.target.value)}
                style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
                required
              >
                {modesDisponibles.map((m) => (
                  <option key={m} value={m}>
                    {canalDuMode(m) === 'CAISSE' ? 'Caisse' : 'Banque'} — {modeLabel(m)}
                  </option>
                ))}
              </select>
            </div>
            {canalTranche === 'BANQUE' && (
              <div style={{ flex: '2 1 260px' }}>
                <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '4px' }}>
                  Compte à débiter *
                </label>
                <select
                  value={compteTranche}
                  onChange={(e) => setCompteTranche(e.target.value)}
                  style={{ width: '100%', padding: '8px', border: '1px solid #d1d5db', borderRadius: '6px' }}
                  required
                >
                  <option value="">Sélectionner un compte…</option>
                  {comptesDuMode.map((c) => (
                    <option key={String(c ?? 'aucun')} value={c == null ? '' : String(c)}>
                      {compteLabel(c)}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div style={{ flex: '1 1 200px', fontSize: '12px', color: reliquatVolet != null && reliquatVolet <= 0.001 ? '#991b1b' : '#4338ca', paddingBottom: '9px' }}>
              {voletCible ? (
                <>
                  Enveloppe du volet : <strong>{fmtUsd(voletCible.montant_total)}</strong> — reste{' '}
                  <strong>{fmtUsd(reliquatVolet ?? 0)}</strong>
                </>
              ) : volets.length > 0 ? (
                <span style={{ color: '#92400e' }}>
                  Ce couple mode / compte ne correspond à aucun volet de la réquisition.
                </span>
              ) : null}
            </div>
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
                  <td style={{ padding: '8px', fontWeight: 600 }}>
                    {fmtUsd(o.montant)}
                    {/* Rappel du volet : c'est ce que la caisse exécutera, sans le rediscuter. */}
                    {o.mode_paiement && (
                      <div style={{ fontSize: '11px', fontWeight: 400, color: '#6b7280' }}>
                        {voletLabel({ mode_paiement: o.mode_paiement, compte_bancaire_id: o.compte_bancaire_id })}
                      </div>
                    )}
                  </td>
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
