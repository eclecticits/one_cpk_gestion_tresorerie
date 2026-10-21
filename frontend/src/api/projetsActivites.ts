import { apiRequest } from '../lib/apiClient'

export type ProjetActiviteType = 'PROJET' | 'ACTIVITE'

export interface ProjetActivite {
  id: number
  organisation_id: number
  code: string
  libelle: string
  type: ProjetActiviteType
  description?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export function listProjetsActivites(active?: boolean): Promise<ProjetActivite[]> {
  return apiRequest<ProjetActivite[]>('GET', '/projets-activites', {
    params: active === undefined ? undefined : { active },
  })
}

export function createProjetActivite(payload: Omit<ProjetActivite, 'id' | 'organisation_id' | 'created_at' | 'updated_at'>) {
  return apiRequest<ProjetActivite>('POST', '/projets-activites', payload)
}

export function updateProjetActivite(id: number, payload: Partial<Omit<ProjetActivite, 'id' | 'organisation_id' | 'created_at' | 'updated_at'>>) {
  return apiRequest<ProjetActivite>('PATCH', `/projets-activites/${id}`, { ...payload })
}

// ── Entrées et sorties d'un projet ───────────────────────────────────────

export type PeriodeProjet = { date_debut?: string; date_fin?: string }

/** Totaux par projet. Les sorties sont gardées par devise (USD, CDF). */
export interface SyntheseProjet {
  projet_id: number
  nb_entrees: number
  entrees_usd: string
  nb_sorties: number
  sorties: Record<string, string>
  solde_usd: string
}

export interface EntreeProjet {
  id: string
  date: string | null
  numero: string | null
  tiers: string | null
  montant_usd: string
  montant_percu: string
  devise_perception: string
  canal: string
  statut_paiement: string
}

export interface SortieProjet {
  id: string
  date: string | null
  numero: string | null
  beneficiaire: string | null
  motif: string | null
  montant: string
  devise: string
  canal: string
  requisition: string | null
}

export interface MouvementsProjet {
  projet: { id: number; code: string; libelle: string; type: ProjetActiviteType }
  totaux: { entrees_usd: string; sorties: Record<string, string>; solde_usd: string }
  entrees: EntreeProjet[]
  sorties: SortieProjet[]
}

const nettoyer = (periode: PeriodeProjet) =>
  Object.fromEntries(Object.entries(periode).filter(([, v]) => Boolean(v)))

export function getSyntheseProjets(periode: PeriodeProjet = {}): Promise<SyntheseProjet[]> {
  return apiRequest<SyntheseProjet[]>('GET', '/projets-activites/synthese', { params: nettoyer(periode) })
}

export function getMouvementsProjet(id: number, periode: PeriodeProjet = {}): Promise<MouvementsProjet> {
  return apiRequest<MouvementsProjet>('GET', `/projets-activites/${id}/mouvements`, { params: nettoyer(periode) })
}
