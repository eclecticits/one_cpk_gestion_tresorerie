import type { Money } from './index'

export interface ReportPeriod {
  start?: string | null
  end?: string | null
  label?: string | null
}

export interface ReportDailyStats {
  date: string
  encaissements: Money
  sorties: Money
  solde: Money
}

export interface ReportTotals {
  encaissements_total: Money
  sorties_total: Money
  solde_initial: Money
  solde: Money
  solde_final: Money
}

export interface ReportBreakdownCountTotal {
  key: string
  count: number
  total: Money
}

export interface ReportBreakdownCount {
  key: string
  count: number
}

export interface ReportModePaiementBreakdown {
  encaissements: ReportBreakdownCountTotal[]
  sorties: ReportBreakdownCountTotal[]
}

export interface ReportRequisitionsSummary {
  total: number
  en_attente: number
  approuvees: number
}

export interface ReportBreakdowns {
  par_statut_paiement: ReportBreakdownCountTotal[]
  par_mode_paiement: ReportModePaiementBreakdown
  par_poste_budgetaire: ReportBreakdownCountTotal[]
  par_statut_requisition: ReportBreakdownCount[]
  requisitions: ReportRequisitionsSummary
}

export interface ReportAvailability {
  encaissements: boolean
  sorties: boolean
  requisitions: boolean
}

export interface ReportSummaryStats {
  totals: ReportTotals
  breakdowns: ReportBreakdowns
  availability: ReportAvailability
}

export interface ReportSummaryResponse {
  stats: ReportSummaryStats
  daily_stats: ReportDailyStats[]
  period?: ReportPeriod | null
}

export interface ReportJournalLine {
  date: string
  libelle?: string | null
  reference?: string | null
  compte_label?: string | null
  entree: Money
  sortie: Money
  solde: Money
  type_operation?: string | null
  transaction_id?: string | null
  transaction_type?: string | null
  is_reconciled?: boolean | null
  reconciled_at?: string | null
  bank_statement_ref?: string | null
}

export interface ReportJournalResponse {
  canal: string
  devise: string
  compte_bancaire_id?: number | null
  compte_bancaire_label?: string | null
  solde_initial: Money
  total_entrees: Money
  total_sorties: Money
  solde_final: Money
  period?: ReportPeriod | null
  lignes: ReportJournalLine[]
}

export interface ReportAnnualMonth {
  mois: number
  total_entrees: Money
  total_sorties: Money
  solde: Money
}

export interface ReportAnnualCanalSplit {
  caisse: Money
  banque: Money
}

export interface ReportAnnualSynthese {
  year: number
  devise: string
  canal: string
  months: ReportAnnualMonth[]
  total_entrees: Money
  total_sorties: Money
  solde_net: Money
  coverage_rate?: Money | null
  critical_month?: number | null
  encaissements_par_canal: ReportAnnualCanalSplit
  sorties_par_canal: ReportAnnualCanalSplit
}
