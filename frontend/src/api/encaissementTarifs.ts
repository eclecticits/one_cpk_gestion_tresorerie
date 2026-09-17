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
  created_at: string
  updated_at: string
}

export type EncaissementTarifPayload = Partial<
  Pick<EncaissementTarif, 'libelle' | 'montant' | 'devise' | 'budget_poste_code' | 'is_active' | 'position'>
>

export function listEncaissementTarifs(actifs?: boolean): Promise<EncaissementTarif[]> {
  return apiRequest<EncaissementTarif[]>('GET', '/encaissement-tarifs', {
    params: actifs === undefined ? undefined : { actifs },
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
