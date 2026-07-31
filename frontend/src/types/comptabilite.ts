// Types du module Comptabilité (Lot 1 — fondations).
// Miroir des schémas Pydantic de backend/app/modules/comptabilite/schemas/ecritures.py

export type TypeReferentiel = 'SYSCOHADA' | 'SYSCEBNL'

export type NatureCompte = 'ACTIF' | 'PASSIF' | 'CHARGE' | 'PRODUIT' | 'ENGAGEMENT'
export type SensNormal = 'DEBIT' | 'CREDIT'

export interface ComptaCompte {
  id: number
  numero: string
  libelle: string
  classe: string | null
  nature: NatureCompte
  sens_normal: SensNormal
  is_collectif: boolean
  is_auxiliaire: boolean
  actif: boolean
  parent_id: number | null
}

export interface ComptaJournal {
  id: number
  code: string
  libelle: string
  type_journal: string
  actif: boolean
}

export type StatutExercice = string

export interface ComptaExercice {
  id: number
  code: string
  libelle: string | null
  date_debut: string
  date_fin: string
  statut: StatutExercice
  devise_tenue: string
}

export type StatutEcriture = 'BROUILLON' | 'VALIDEE' | 'CLOTUREE' | 'ANNULEE'

export interface ComptaLigneEcriture {
  id: string
  compte_id: number
  compte_numero: string | null
  compte_libelle: string | null
  compte_auxiliaire_id: number | null
  libelle: string | null
  debit: string
  credit: string
  devise: string
}

export interface ComptaEcriture {
  id: string
  numero: string | null
  journal_id: number
  exercice_id: number
  date_ecriture: string
  date_piece: string | null
  reference_piece: string | null
  libelle: string
  statut: StatutEcriture
  devise: string
  module_origine: string | null
  est_automatique: boolean
  valide_par: string | null
  valide_le: string | null
  contrepasse_ecriture_id: string | null
  motif_annulation: string | null
  created_at: string
  lignes: ComptaLigneEcriture[]
}

export interface ComptaEcritureListResponse {
  items: ComptaEcriture[]
  total: number
}

export interface ComptaStatut {
  provisionne: boolean
  societe_id: number | null
}

export interface ComptaSetupInput {
  type_referentiel: TypeReferentiel
  exercice_date_debut: string
  exercice_date_fin: string
}

export interface ComptaSetupResult {
  societe_id: number
  referentiel_id: number
  exercice_id: number
  journaux_ids: number[]
  nb_comptes: number
  deja_existant: boolean
}

export interface ComptaLigneEcritureInput {
  compte_id: number
  compte_auxiliaire_id?: number | null
  libelle?: string | null
  debit: string
  credit: string
}

export interface ComptaEcritureCreateInput {
  journal_id: number
  exercice_id: number
  date_ecriture: string
  date_piece?: string | null
  reference_piece?: string | null
  libelle: string
  devise: string
  lignes: ComptaLigneEcritureInput[]
}

export interface ComptaEcrituresListParams {
  statut?: string
  journal_id?: number
  exercice_id?: number
  limit?: number
  offset?: number
}
