import type { Money } from './index'

export interface TreasuryCaisse {
  solde_usd: Money
  solde_cdf: Money
  derniere_maj?: string | null
}

export interface TreasuryBanque {
  id: number
  nom: string
  code?: string | null
  is_active?: boolean
}

export interface TreasuryCompte {
  id: number
  banque_id: number
  intitule: string
  numero_compte?: string
  devise: 'USD' | 'CDF'
  solde_actuel: Money
  is_active?: boolean
  banque?: TreasuryBanque | null
}

export interface TreasuryOverviewData {
  caisse: TreasuryCaisse
  comptes: TreasuryCompte[]
}
