import { apiRequest } from '../lib/apiClient'
import type { OrdreDecaissement } from '../types'

export interface OrdresDecaissementListResponse {
  items: OrdreDecaissement[]
  total: number
  montant_total_requisition?: number | string | null
  total_paye: number | string
  total_autorise_non_paye: number | string
  reliquat?: number | string | null
}

export async function listOrdresDecaissement(params: {
  requisition_id?: string
  sans_requisition?: boolean
  statut?: 'AUTORISE' | 'PAYE' | 'ANNULE'
  limit?: number
  offset?: number
}): Promise<OrdresDecaissementListResponse> {
  return apiRequest('GET', '/ordres-decaissement', { params })
}

export interface OrdreDirectLigne {
  budget_poste_id: number | null
  rubrique: string
  description: string
  montant_total: number
  devise: 'USD' | 'CDF'
}

/** Répartition d'une tranche progressive sur un poste budgétaire précis. */
export interface OrdreRepartitionLigne {
  budget_poste_id: number
  montant: number
  libelle?: string | null
}

export async function createOrdreDecaissement(input: {
  /** Omis = ordre de sortie directe (sans réquisition, plafond 100 USD) */
  requisition_id?: string | null
  beneficiaire: string
  /** Pour une collation, le total est DÉRIVÉ côté serveur du nombre de
   *  participants et du prix par tête : ce qui est envoyé ici sert l'affichage. */
  montant: number
  devise?: 'USD' | 'CDF'
  motif?: string | null
  /** 'COLLATION' déplace le plafond du montant vers le prix par personne. */
  type_sortie?: 'SIMPLE' | 'COLLATION'
  reunion_intitule?: string | null
  /** Format ISO (yyyy-MM-dd) : la réunion et sa date forment la clé qui
   *  empêche de découper une même assemblée en plusieurs ordres. */
  reunion_date?: string | null
  participants?: number | null
  montant_par_personne?: number | null
  /** Sortie directe « type réquisition » : service + lignes budgétaires. */
  service_id?: number | null
  /** Répartition de la tranche par poste (progressif) ou lignes directes. */
  lignes?: Array<OrdreDirectLigne | OrdreRepartitionLigne> | null
  /**
   * Volet réglé par la tranche. Obligatoire dès que la réquisition mêle
   * plusieurs modes : le mode saisi par le demandeur n'est qu'une proposition,
   * l'ordre porte la décision.
   */
  mode_paiement?: string | null
  compte_bancaire_id?: number | null
}): Promise<OrdreDecaissement> {
  return apiRequest('POST', '/ordres-decaissement', input)
}

/**
 * Corrige un ordre de sortie directe que la caisse n'a pas encore payé.
 *
 * Le serveur rejoue tous les contrôles de la création — habilitation, plafond
 * des 100 USD, cumul anti-fractionnement sur 24 h — et refuse un ordre payé,
 * annulé, ou rattaché à une réquisition.
 */
export async function updateOrdreDecaissement(
  ordreId: string,
  input: {
    beneficiaire: string
    montant: number
    devise?: 'USD' | 'CDF'
    motif?: string | null
    // La correction rejoue TOUS les contrôles de la création : le type et ses
    // champs voyagent donc aussi, sinon corriger une collation en ferait une
    // sortie simple de 200 USD, aussitôt refusée.
    type_sortie?: 'SIMPLE' | 'COLLATION'
    reunion_intitule?: string | null
    reunion_date?: string | null
    participants?: number | null
    montant_par_personne?: number | null
    service_id?: number | null
    lignes?: Array<OrdreDirectLigne | OrdreRepartitionLigne> | null
    mode_paiement?: string | null
    compte_bancaire_id?: number | null
  }
): Promise<OrdreDecaissement> {
  return apiRequest('PUT', `/ordres-decaissement/${ordreId}`, input)
}

export async function annulerOrdreDecaissement(
  ordreId: string,
  motif_annulation: string
): Promise<OrdreDecaissement> {
  return apiRequest('POST', `/ordres-decaissement/${ordreId}/annuler`, { motif_annulation })
}
