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
  rib?: string | null
  identifiant_client?: string | null
  code_swift_bic?: string | null
  compte_comptable_associe?: string | null
  journal_comptable_associe?: string | null
  date_ouverture?: string | null
  agence_bancaire?: string | null
  devise: 'USD' | 'CDF' | string
  solde_initial?: Money
  solde_actuel?: Money
  is_active?: boolean
  is_principal?: boolean
  observations?: string | null
  account_type?: 'BANK' | 'CASH'
  banque?: Banque | null
}
