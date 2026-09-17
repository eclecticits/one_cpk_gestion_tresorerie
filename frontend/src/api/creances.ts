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

/** Une note de débit non soldée d'un payeur donné. */
export interface NoteImpayee {
  id: string
  numero_recu: string | null
  libelle: string
  date_encaissement: string | null
  montant_total: number
  montant_paye: number
  reste_du: number
  jours: number
  tranche: TrancheAnciennete
  statut_paiement: string
  relance_count: number
}

export interface NotesImpayees {
  /**
   * Faux quand le rapprochement ne repose que sur le nom saisi : la liste est
   * alors un minimum, comme le total des débiteurs.
   */
  identite_sure: boolean
  /** Porte sur toutes ses notes, jamais sur la seule page reçue. */
  total_du: number
  nb_notes: number
  notes: NoteImpayee[]
}

/** Sur quoi ce payeur doit encore — pour aller de la dette au règlement. */
export const listerNotesImpayees = (params: {
  client_id?: string
  expert_comptable_id?: string
  nom?: string
  limit?: number
}) =>
  apiRequest<NotesImpayees>('GET', '/encaissements/notes-impayees', {
    params: Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ),
  })
