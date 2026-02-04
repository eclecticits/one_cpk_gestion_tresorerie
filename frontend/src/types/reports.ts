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
  par_type_operation: ReportBreakdownCountTotal[]
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
