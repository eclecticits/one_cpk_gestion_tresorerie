import { apiRequest } from '../lib/apiClient'
import type { HorsBudgetStatus, Money, NatureMouvement } from '../types'

/**
 * Recettes à identifier : un versement reçu en banque dont le libellé ne dit
 * pas qui a payé. Il entre en trésorerie tout de suite, au compte d'attente en
 * comptabilité, et attend qu'on retrouve le payeur pour être reclassé vers une
 * nouvelle recette ou le règlement d'une note déjà émise.
 */

export type TrancheAnciennete = '0-30' | '31-90' | '+90'

export interface IdentificationRecette {
  versement_id: string
  encaissement_id: string
  numero_recu?: string | null
  client?: string | null
  libelle?: string | null
  nature_mouvement?: NatureMouvement | null
  montant: Money
  identifie_le?: string | null
}

export interface RemboursementRecette {
  sortie_id: string
  reference_numero?: string | null
  beneficiaire?: string | null
  montant: Money
  date?: string | null
}

export interface RecetteAIdentifier {
  id: string
  numero?: string | null
  date_valeur: string
  libelle: string
  reference?: string | null
  compte_bancaire_id?: number | null
  compte_bancaire?: string | null
  devise: 'USD' | 'CDF'
  mode_paiement?: string | null
  taux_change_applique: Money
  montant_initial: Money
  montant_identifie: Money
  montant_rembourse: Money
  /** Promis au remboursement par une réquisition en cours. */
  montant_reserve: Money
  reste: Money
  /** Ce qui peut encore s'identifier ou se rembourser : le reste moins la réserve. */
  disponible: Money
  reservations: string[]
  remboursements: RemboursementRecette[]
  age_jours: number
  tranche: TrancheAnciennete
  statut?: HorsBudgetStatus | null
  statut_operation?: string | null
  identifications: IdentificationRecette[]
}

export interface TotauxRecettesAIdentifier {
  devise: 'USD' | 'CDF'
  par_tranche: Record<TrancheAnciennete, Money>
  total: Money
}

export interface RecettesAIdentifierResponse {
  items: RecetteAIdentifier[]
  totaux: TotauxRecettesAIdentifier[]
}

export interface RecetteAIdentifierPayload {
  compte_bancaire_id: number
  montant: number
  date_valeur: string
  libelle: string
  reference?: string | null
  mode_paiement?: 'virement' | 'cheque' | 'mobile_money' | 'card'
}

export interface PisteIdentification {
  encaissement_id: string
  numero_recu?: string | null
  numero_note_externe?: string | null
  client?: string | null
  libelle?: string | null
  date?: string | null
  montant_total: Money
  reste_du: Money
  devise: 'USD' | 'CDF'
  raison: 'recherche' | 'montant' | 'nom'
}

export const TRANCHE_LABELS: Record<TrancheAnciennete, string> = {
  '0-30': '0 à 30 jours',
  '31-90': '31 à 90 jours',
  '+90': 'Plus de 90 jours',
}

export function listRecettesAIdentifier(statut: 'ouvertes' | 'toutes' = 'ouvertes') {
  return apiRequest<RecettesAIdentifierResponse>('GET', `/recettes-a-identifier?statut=${statut}`)
}

export function createRecetteAIdentifier(payload: RecetteAIdentifierPayload) {
  return apiRequest<{ id: string; numero: string }>('POST', '/recettes-a-identifier', payload)
}

export function pistesIdentification(recetteId: string, q?: string) {
  const qs = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
  return apiRequest<PisteIdentification[]>('GET', `/recettes-a-identifier/${recetteId}/pistes${qs}`)
}

export interface RemboursementRequisitionPayload {
  recette: RecetteAIdentifier
  objet: string
  beneficiaire: string
  montant: number
  service_id: number
  mode_paiement: 'virement' | 'cheque' | 'mobile_money' | 'cash'
  compte_bancaire_id?: number | null
}

/** Rembourser passe par une réquisition : elle réserve le montant sur la
 *  recette pendant son circuit de validation, la sortie de fonds le paie. */
export function createRequisitionRemboursement(p: RemboursementRequisitionPayload) {
  return apiRequest<{ id: string; numero_requisition: string }>('POST', '/requisitions', {
    objet: p.objet,
    mode_paiement: p.mode_paiement,
    type_requisition: 'classique',
    nature_requisition: 'RECETTE_A_IDENTIFIER',
    recette_a_identifier_id: p.recette.id,
    montant_total: p.montant,
    devise: p.recette.devise,
    service_id: p.service_id,
    compte_bancaire_id: p.mode_paiement === 'cash' ? null : p.compte_bancaire_id ?? null,
    beneficiaire: p.beneficiaire,
  })
}

export function reglerNoteDepuisRecette(recetteId: string, encaissementId: string, montant: number) {
  return apiRequest<{ versement_id: string; encaissement_id: string; numero_recu?: string | null }>(
    'POST',
    `/recettes-a-identifier/${recetteId}/regler-note`,
    { encaissement_id: encaissementId, montant },
  )
}
