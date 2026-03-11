import type { Money } from './index'

export interface Banque {
  id: number
  nom: string
  code?: string | null
  is_active?: boolean
}

export interface CompteBancaire {
  id: number
  banque_id: number | null
  intitule: string
  numero_compte?: string
  devise: 'USD' | 'CDF' | string
  solde_initial?: Money
  solde_actuel?: Money
  is_active?: boolean
  account_type?: 'BANK' | 'CASH'
  banque?: Banque | null
}
