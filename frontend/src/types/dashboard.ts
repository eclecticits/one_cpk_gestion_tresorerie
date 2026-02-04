import type { Money } from './index'

export interface DashboardPeriod {
  start?: string | null
  end?: string | null
  label?: string | null
}

export interface DashboardStats {
  total_encaissements_period: Money
  total_encaissements_jour: Money
  total_sorties_period: Money
  total_sorties_jour: Money
  solde_period: Money
  solde_actuel: Money
  solde_jour: Money
  requisitions_en_attente: number
  note?: string | null
}

export interface DashboardDailyStats {
  date: string
  encaissements: Money
  sorties: Money
  solde: Money
}

export interface DashboardStatsResponse {
  stats: DashboardStats
  daily_stats: DashboardDailyStats[]
  period?: DashboardPeriod | null
}
