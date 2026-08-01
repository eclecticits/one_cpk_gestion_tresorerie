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

// ── Paramétrage des mappings ────────────────────────────────────────────────
// Miroir de backend/app/modules/comptabilite/schemas/parametrage.py

export interface ComptaMappingCompteRef {
  compte_id: number | null
  compte_numero: string | null
  compte_libelle: string | null
}

export interface ComptaMappingPoste extends ComptaMappingCompteRef {
  budget_poste_id: number
  code: string
  libelle: string
  type: string | null
}

export interface ComptaMappingCompteBancaire extends ComptaMappingCompteRef {
  compte_bancaire_id: number
  intitule: string
  numero_compte: string | null
  account_type: string | null
  devise: string | null
}

export interface ComptaMappingRubrique extends ComptaMappingCompteRef {
  code_rubrique: string
  libelle: string
  description: string
}

export interface ComptaMappings {
  budget_exercice_id: number | null
  budget_exercice_annee: number | null
  caisse_defaut_compte_id: number | null
  caisse_defaut_compte_numero: string | null
  caisse_defaut_compte_libelle: string | null
  postes: ComptaMappingPoste[]
  comptes_bancaires: ComptaMappingCompteBancaire[]
  rubriques: ComptaMappingRubrique[]
  nb_non_mappes: number
}

// ── Restitutions (Grand Livre, Journal, Balance) ────────────────────────────
// Miroir de backend/app/modules/comptabilite/schemas/restitutions.py

export interface ComptaLigneBalance {
  compte_id: number
  compte_numero: string
  compte_libelle: string
  nature: NatureCompte
  total_debit: string
  total_credit: string
  solde_debiteur: string
  solde_crediteur: string
}

export interface ComptaBalance {
  exercice_id: number
  devise_tenue: string
  date_debut: string | null
  date_fin: string | null
  inclure_brouillons: boolean
  lignes: ComptaLigneBalance[]
  total_debit: string
  total_credit: string
  total_solde_debiteur: string
  total_solde_crediteur: string
  equilibree: boolean
}

export interface ComptaMouvementGrandLivre {
  ligne_id: string
  ecriture_id: string
  numero: string | null
  date_ecriture: string
  journal_code: string
  libelle: string | null
  reference_piece: string | null
  debit: string
  credit: string
  statut: StatutEcriture
  solde_cumule: string
}

export interface ComptaGrandLivre {
  exercice_id: number
  devise_tenue: string
  compte_id: number
  compte_numero: string
  compte_libelle: string
  date_debut: string | null
  date_fin: string | null
  inclure_brouillons: boolean
  solde_anterieur: string
  mouvements: ComptaMouvementGrandLivre[]
  total_debit_page: string
  total_credit_page: string
  solde_final_page: string
  curseur_suivant: string | null
}

export interface ComptaEcritureJournal {
  ecriture_id: string
  numero: string | null
  date_ecriture: string
  libelle: string
  statut: StatutEcriture
  total_debit: string
  total_credit: string
}

export interface ComptaLivreJournal {
  exercice_id: number
  devise_tenue: string
  journal_id: number
  journal_code: string
  journal_libelle: string
  date_debut: string | null
  date_fin: string | null
  inclure_brouillons: boolean
  ecritures: ComptaEcritureJournal[]
  total_debit: string
  total_credit: string
}

export interface ComptaRestitutionFiltres {
  exercice_id?: number
  date_debut?: string
  date_fin?: string
  inclure_brouillons?: boolean
}

export interface ComptaMappingsDefautResult {
  postes_mappes: number
  comptes_bancaires_mappes: number
  rubriques_mappees: number
  compte_caisse_defaut_id: number | null
}
