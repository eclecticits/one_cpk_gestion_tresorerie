import { apiRequest } from '../lib/apiClient'

/** Tarif d'encaissement : ce qu'un libellé connu vaut, et où il s'impute.
 *  `montant` et `budget_poste_code` sont indépendants : l'un, l'autre, les deux
 *  ou aucun. Ce qui est défini s'impose à la saisie, le reste demeure libre. */
export interface EncaissementTarif {
  id: number
  libelle: string
  montant: number | string | null
  devise: 'USD' | 'CDF'
  budget_poste_code: string | null
  is_active: boolean
  position: number
  /** Poste de l'exercice courant auquel le code se résout aujourd'hui.
   *  Nul avec un code renseigné = code introuvable dans cet exercice. */
  budget_poste_id: number | null
  budget_poste_libelle: string | null
  /** Fenêtre de validité de CETTE version. `effet_au` nul = version en
   *  vigueur ; renseigné = version close, qui vaut encore pour les reçus
   *  qu'elle couvrait mais ne s'applique plus à une saisie d'aujourd'hui. */
  effet_du: string
  effet_au: string | null
  /** La version que celle-ci a remplacée, s'il y en a une. */
  remplace_id: number | null
  /** Lignes d'encaissement passées sous cette version. Au-delà de zéro, une
   *  modification substantielle ouvre une version neuve au lieu d'écraser
   *  celle-ci, et un retrait la clôt au lieu de l'effacer. */
  utilisations: number
  created_at: string
  updated_at: string
}

export type EncaissementTarifPayload = Partial<
  Pick<EncaissementTarif, 'libelle' | 'montant' | 'devise' | 'budget_poste_code' | 'is_active' | 'position'>
>

export function listEncaissementTarifs(
  actifs?: boolean,
  archives?: boolean,
): Promise<EncaissementTarif[]> {
  const params: Record<string, boolean> = {}
  if (actifs !== undefined) params.actifs = actifs
  if (archives !== undefined) params.archives = archives
  return apiRequest<EncaissementTarif[]>('GET', '/encaissement-tarifs', {
    params: Object.keys(params).length ? params : undefined,
  })
}

export function createEncaissementTarif(payload: EncaissementTarifPayload): Promise<EncaissementTarif> {
  return apiRequest<EncaissementTarif>('POST', '/encaissement-tarifs', payload)
}

export function updateEncaissementTarif(id: number, payload: EncaissementTarifPayload): Promise<EncaissementTarif> {
  return apiRequest<EncaissementTarif>('PATCH', `/encaissement-tarifs/${id}`, { ...payload })
}

export function deleteEncaissementTarif(id: number): Promise<void> {
  return apiRequest<void>('DELETE', `/encaissement-tarifs/${id}`)
}
