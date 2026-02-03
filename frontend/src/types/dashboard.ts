export interface DashboardPeriod {
  start?: string | null
  end?: string | null
  label?: string | null
}

export interface DashboardStats {
  total_encaissements_period: number
  total_encaissements_jour: number
  total_sorties_period: number
  total_sorties_jour: number
  solde_period: number
  solde_actuel: number
  solde_jour: number
  requisitions_en_attente: number
  note?: string | null
}

export interface DashboardDailyStats {
  date: string
  encaissements: number
  sorties: number
  solde: number
}

export interface DashboardStatsResponse {
  stats: DashboardStats
  daily_stats: DashboardDailyStats[]
  period?: DashboardPeriod | null
}
