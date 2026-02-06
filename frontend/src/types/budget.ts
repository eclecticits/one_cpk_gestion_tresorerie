export interface BudgetLineSummary {
  id: number
  code: string
  libelle: string
  parent_code?: string | null
  type?: string | null
  active?: boolean
  montant_prevu: string | number
  montant_engage: string | number
  montant_paye: string | number
  montant_disponible: string | number
  pourcentage_consomme: string | number
}

export interface BudgetLinesResponse {
  annee?: number | null
  statut?: string | null
  lignes: BudgetLineSummary[]
}

export interface BudgetExerciseSummary {
  annee: number
  statut?: string | null
}

export interface BudgetExercisesResponse {
  exercices: BudgetExerciseSummary[]
}
