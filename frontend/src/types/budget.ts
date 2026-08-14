export interface BudgetPosteSummary {
  id: number
  code: string
  libelle: string
  parent_code?: string | null
  parent_id?: number | null
  type?: string | null
  active?: boolean
  is_global?: boolean
  /** Ligne comptée dans les totaux et la synthèse. Faux = visible partout,
   *  ignorée de tous les agrégats (report d'exercice antérieur, ligne pour
   *  mémoire). L'exclusion couvre toute la branche du poste. */
  inclure_dans_calculs?: boolean
  montant_prevu: string | number
  montant_engage: string | number
  montant_paye: string | number
  montant_disponible: string | number
  pourcentage_consomme: string | number
}

export interface BudgetPostesResponse {
  annee?: number | null
  statut?: string | null
  postes: BudgetPosteSummary[]
}

export interface BudgetPosteTree extends BudgetPosteSummary {
  children?: BudgetPosteTree[]
}

export interface BudgetPostesTreeResponse {
  annee?: number | null
  statut?: string | null
  postes: BudgetPosteTree[]
}

export interface BudgetExerciseSummary {
  annee: number
  statut?: string | null
}

export interface BudgetExercisesResponse {
  exercices: BudgetExerciseSummary[]
}
