// ─────────────────────────────────────────────────────────────────────────────
// API — Bénéficiaires des sorties et justificatifs attendus
//
// Le bénéficiaire est d'abord un expert-comptable, sinon un membre du
// personnel ou un utilisateur de l'application, sinon une personne externe. Le justificatif est demandé par le
// caissier au paiement (48 h), relancé une fois à J+7, et c'est le caissier qui
// le scanne et le joint à la ligne de sortie.
// ─────────────────────────────────────────────────────────────────────────────

import { apiRequest } from '../lib/apiClient'
import type { SortieFonds } from '../types'

export type TypeBeneficiaire = 'EXPERT' | 'PERSONNEL' | 'UTILISATEUR' | 'EXTERNE'

export interface BeneficiaireSuggestion {
  type: TypeBeneficiaire
  id: string
  nom: string
  detail?: string | null
  email?: string | null
  telephone?: string | null
}

export type StatutJustificatif = 'NON_REQUIS' | 'ATTENDU' | 'EN_RETARD' | 'RECU' | 'DISPENSE'

export const TYPE_BENEFICIAIRE_LABELS: Record<TypeBeneficiaire, string> = {
  EXPERT: 'Expert-comptable',
  PERSONNEL: 'Personnel',
  UTILISATEUR: 'Utilisateur',
  EXTERNE: 'Personne externe',
}

export const STATUT_JUSTIFICATIF_LABELS: Record<StatutJustificatif, string> = {
  NON_REQUIS: 'Non requis',
  ATTENDU: 'Justificatif attendu',
  EN_RETARD: 'Justificatif en retard',
  RECU: 'Justificatif reçu',
  DISPENSE: 'Justificatif dispensé',
}

export function rechercherBeneficiaires(q: string): Promise<BeneficiaireSuggestion[]> {
  return apiRequest<BeneficiaireSuggestion[]>('GET', '/beneficiaires', { params: { q } })
}

/** La case « Pièce justificative à rapporter » doit-elle être proposée cochée ? */
export function regleJustificatif(params: { posteIds?: number[]; requisitionId?: string | null }): Promise<{ requis: boolean }> {
  return apiRequest<{ requis: boolean }>('GET', '/sorties-fonds/justificatifs/regle', {
    params: {
      poste_ids: (params.posteIds || []).join(','),
      ...(params.requisitionId ? { requisition_id: params.requisitionId } : {}),
    },
  })
}

export function listerJustificatifsEnAttente(): Promise<SortieFonds[]> {
  return apiRequest<SortieFonds[]>('GET', '/sorties-fonds/justificatifs/en-attente')
}

export function deposerJustificatif(sortieId: string, fichiers: File[]): Promise<SortieFonds> {
  const body = new FormData()
  fichiers.forEach((f) => body.append('fichiers', f, f.name))
  return apiRequest<SortieFonds>('POST', `/sorties-fonds/${sortieId}/justificatif`, { body })
}

/** Relance à la main : même message que la relance automatique, autorités en copie. */
export function relancerJustificatif(sortieId: string): Promise<SortieFonds> {
  return apiRequest<SortieFonds>('POST', `/sorties-fonds/${sortieId}/justificatif/relancer`)
}

export function deciderJustificatif(
  sortieId: string,
  action: 'exiger' | 'ne_pas_exiger' | 'dispenser',
  motif?: string,
): Promise<SortieFonds> {
  return apiRequest<SortieFonds>('PATCH', `/sorties-fonds/${sortieId}/justificatif`, { action, motif: motif || null })
}
