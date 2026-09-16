import { apiRequest } from '../lib/apiClient'

/** Tranche d'ancienneté d'une créance : c'est par tranche qu'on décide quoi faire. */
export type TrancheAnciennete = 'moins_30' | '30_60' | '60_90' | 'plus_90'

export const LIBELLE_TRANCHE: Record<TrancheAnciennete, string> = {
  moins_30: 'moins de 30 j',
  '30_60': '30 à 60 j',
  '60_90': '60 à 90 j',
  plus_90: 'plus de 90 j',
}

export interface Debiteur {
  cle: string
  /** `expert` et `client` viennent d'un référentiel ; `libre` d'un nom saisi. */
  famille: 'expert' | 'client' | 'libre'
  libelle: string
  /** Numéro d'ordre, pour un expert. */
  detail: string | null
  type_client: string | null
  reste_du: number
  nb_notes: number
  plus_ancienne_le: string | null
  jours: number
  tranche: TrancheAnciennete
  relances: number
  derniere_relance_le: string | null
  /**
   * Faux quand le regroupement ne repose que sur le nom saisi : deux
   * orthographes font deux débiteurs, et le montant est alors un minimum.
   */
  identite_sure: boolean
}

export interface ListeDebiteurs {
  /** Porte sur l'ensemble filtré, jamais sur la seule page affichée. */
  total_du: number
  nb_debiteurs: number
  debiteurs: Debiteur[]
}

export const listerDebiteurs = (params: {
  q?: string
  type_client?: string
  anciennete_min?: number
  limit?: number
  offset?: number
} = {}) =>
  apiRequest<ListeDebiteurs>('GET', '/encaissements/debiteurs', {
    params: Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ),
  })
