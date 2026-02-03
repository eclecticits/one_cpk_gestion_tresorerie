export interface ReportPeriod {
  start?: string | null
  end?: string | null
  label?: string | null
}

export interface ReportDailyStats {
  date: string
  encaissements: number
  sorties: number
  solde: number
}

export interface ReportTotals {
  encaissements_total: number
  sorties_total: number
  solde: number
}

export interface ReportBreakdownCountTotal {
  key: string
  count: number
  total: number
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
