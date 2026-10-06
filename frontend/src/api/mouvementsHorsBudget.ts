import { apiRequest } from '../lib/apiClient'
import type { HorsBudgetStatus, Money, NatureMouvement } from '../types'

/**
 * Mouvements qui bougent la trésorerie sans bouger le budget : recettes et
 * dépenses hors budget en attente d'affectation, et fonds encaissés pour le
 * compte d'un tiers. Deux notions distinctes, un même principe : l'argent est
 * bien là, le budget n'a pas encore (ou ne doit jamais) le voir.
 */

export interface FondsTiersOperation {
  id: string
  organisation_id: number
  encaissement_id: string
  statut: 'OUVERT' | 'PARTIELLEMENT_REMBOURSE' | 'REGULARISE' | 'ANNULE'
  tiers_concerne?: string | null
  tiers_organisation_id?: number | null
  tiers_nom_libre?: string | null
  tiers_display_name: string
  tiers_type: 'ORGANISATION' | 'EXTERNE' | 'LEGACY'
  payeur_origine?: string | null
  beneficiaire_reel?: string | null
  motif?: string | null
  reference?: string | null
  piece_justificative?: string | null
  montant_recu: Money
  devise: 'USD' | 'CDF'
  montant_rembourse: Money
  solde_restant: Money
  /** Part du solde déjà promise par des réquisitions en cours. */
  montant_reserve?: Money
  /** Ce qui reste libre pour un nouveau versement. */
  disponible?: Money
  requisitions_en_cours?: string[]
  created_by?: string | null
  created_at: string
  updated_at: string
}

export interface BudgetAffectationLine {
  budget_poste_id: number
  montant: number
}

export interface AffecterBudgetPayload {
  lignes: BudgetAffectationLine[]
  justification: string
  reference?: string | null
  idempotency_key: string
}

export interface AffecterBudgetResult {
  id: string
  status: string
}

export const NATURE_MOUVEMENT_LABELS: Record<NatureMouvement, string> = {
  BUDGETAIRE: 'Budgétaire',
  HORS_BUDGET_A_REGULARISER: 'Hors budget',
  FONDS_DE_TIERS: 'Fonds de tiers',
  TRANSFERT_INTERNE: 'Transfert interne',
  A_IDENTIFIER: 'Recette à identifier',
}

export const HORS_BUDGET_STATUS_LABELS: Record<HorsBudgetStatus, string> = {
  A_REGULARISER: 'À régulariser',
  PARTIELLEMENT_AFFECTE: 'Partiellement affecté',
  AFFECTE_BUDGET: 'Affecté au budget',
  MAINTENU_HORS_BUDGET: 'Maintenu hors budget',
  ANNULE: 'Annulé',
  A_IDENTIFIER: 'À identifier',
  PARTIELLEMENT_IDENTIFIE: 'Partiellement identifiée',
  IDENTIFIE: 'Identifiée',
  REMBOURSEE: 'Remboursée',
}

export const FONDS_TIERS_STATUT_LABELS: Record<FondsTiersOperation['statut'], string> = {
  OUVERT: 'À rembourser',
  PARTIELLEMENT_REMBOURSE: 'Partiellement remboursé',
  REGULARISE: 'Soldé',
  ANNULE: 'Annulé',
}

/** Un mouvement est-il encore en attente d'une décision d'affectation ? */
export function estAffectable(mouvement: {
  nature_mouvement?: NatureMouvement | null
  statut_operation?: string | null
  statut?: string | null
}): boolean {
  if ((mouvement.nature_mouvement || 'BUDGETAIRE') !== 'HORS_BUDGET_A_REGULARISER') return false
  const statut = String(mouvement.statut_operation ?? mouvement.statut ?? 'ACTIVE').toUpperCase()
  return statut !== 'ANNULEE'
}

/** Libre pour un nouveau versement : le solde moins ce que d'autres
 *  réquisitions en cours ont déjà promis. */
export function fondsTiersDisponible(op: FondsTiersOperation): number {
  const solde = Number(op.solde_restant) || 0
  if (op.disponible === undefined || op.disponible === null) return solde
  return Math.max(0, Number(op.disponible) || 0)
}

export async function listFondsTiers(statut?: string): Promise<FondsTiersOperation[]> {
  const qs = statut ? `?statut=${encodeURIComponent(statut)}` : ''
  return apiRequest<FondsTiersOperation[]>('GET', `/fonds-tiers${qs}`)
}

export async function getFondsTiers(operationId: string): Promise<FondsTiersOperation> {
  return apiRequest<FondsTiersOperation>('GET', `/fonds-tiers/${operationId}`)
}

export async function affecterEncaissementBudget(
  encaissementId: string,
  payload: AffecterBudgetPayload,
): Promise<AffecterBudgetResult> {
  return apiRequest<AffecterBudgetResult>('POST', `/encaissements/${encaissementId}/affecter-budget`, payload)
}

export async function affecterSortieBudget(
  sortieId: string,
  payload: AffecterBudgetPayload,
): Promise<AffecterBudgetResult> {
  return apiRequest<AffecterBudgetResult>('POST', `/sorties-fonds/${sortieId}/affecter-budget`, payload)
}
