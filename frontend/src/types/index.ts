export type UserRole = 'reception' | 'tresorerie' | 'rapporteur' | 'secretariat' | 'comptabilite' | 'admin'
export type SystemRole = 'admin' | 'caissier' | 'reporting_viewer'
export type Money = string | number

export interface User {
  id: string
  email: string
  nom: string
  prenom: string
  role: UserRole
  active: boolean
  must_change_password: boolean
  created_at: string
}

export interface UserRoleAssignment {
  id: string
  user_id: string
  role: SystemRole
  created_at: string
  created_by: string
}

export type CategoriePersonne = 'Personne Physique' | 'Personne Morale'
export type StatutProfessionnel = 'En Cabinet' | 'Indépendant' | 'Salarié' | 'Cabinet'

export interface ExpertComptable {
  id: string
  numero_ordre: string
  nom_denomination: string
  type_ec: string
  email?: string
  telephone?: string
  categorie_personne?: CategoriePersonne
  statut_professionnel?: StatutProfessionnel
  cabinet_attache?: string
  active?: boolean
  created_at: string
}

export type ModePatement = 'cash' | 'mobile_money' | 'virement'

export type TypeClient =
  | 'expert_comptable'
  | 'client_externe'
  | 'banque_institution'
  | 'partenaire'
  | 'organisation'
  | 'autre'

export type TypeOperationExpertComptable =
  | 'cotisation_annuelle'
  | 'cotisation_trimestrielle'
  | 'inscription_tableau'
  | 'reinscription'
  | 'formation'
  | 'seminaire_atelier'
  | 'achat_documents'
  | 'penalites_amendes'
  | 'regularisation'
  | 'contribution_speciale'
  | 'autres_paiements_pro'

export type TypeOperationClientExterne =
  | 'achat_formation'
  | 'frais_participation_evenement'
  | 'achat_documents_client'
  | 'frais_attestation'
  | 'frais_certification'
  | 'frais_service'
  | 'contribution'
  | 'don_soutien'

export type TypeOperationBanque =
  | 'depot_bancaire'
  | 'versement_bancaire'
  | 'virement_bancaire_recu'
  | 'subvention'
  | 'appui_financier'
  | 'financement_projet'
  | 'interets_bancaires'
  | 'remboursement_bancaire'
  | 'don_institutionnel'
  | 'transfert_fonds'

export type TypeOperationAutre =
  | 'partenariat'
  | 'sponsoring'
  | 'financement_activite'
  | 'autre_encaissement'

export type TypeOperation =
  | TypeOperationExpertComptable
  | TypeOperationClientExterne
  | TypeOperationBanque
  | TypeOperationAutre
  | 'livre'
  | 'autre'

export type StatutPaiement = 'non_paye' | 'partiel' | 'complet' | 'avance'

export interface PaymentHistory {
  id: string
  encaissement_id: string
  montant: Money
  mode_paiement: ModePatement
  reference?: string
  notes?: string
  created_at: string
  created_by: string
}

export interface Encaissement {
  id: string
  numero_recu: string
  type_client: TypeClient
  expert_comptable_id?: string
  expert_comptable?: ExpertComptable
  client_nom?: string
  type_operation: TypeOperation
  description: string
  montant: Money
  montant_total: Money
  montant_paye: Money
  statut_paiement: StatutPaiement
  mode_paiement: ModePatement
  reference?: string
  date_encaissement: string
  created_by: string
  created_at: string
  payment_history?: PaymentHistory[]
}

export type StatutRequisition = 'brouillon' | 'validee_tresorerie' | 'approuvee' | 'payee' | 'rejetee'

export interface LigneRequisition {
  id: string
  requisition_id: string
  rubrique: string
  description: string
  quantite: number
  montant_unitaire: Money
  montant_total: Money
}

export interface Requisition {
  id: string
  numero_requisition: string
  objet: string
  statut: StatutRequisition
  mode_paiement: ModePatement
  montant_total: Money
  created_by: string
  validee_par?: string
  validee_le?: string
  approuvee_par?: string
  approuvee_le?: string
  payee_par?: string
  payee_le?: string
  motif_rejet?: string
  a_valoir?: boolean
  instance_beneficiaire?: string
  notes_a_valoir?: string
  created_at: string
  updated_at: string
  lignes?: LigneRequisition[]
  demandeur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  validateur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  approbateur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  caissier?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
}

export type TypeSortieFonds =
  | 'requisition'
  | 'remboursement'
  | 'versement_banque'
  | 'sortie_directe'
  | 'achat_fournitures'
  | 'achat_materiel_informatique'
  | 'achat_carburant'
  | 'achat_consommables'
  | 'paiement_loyer'
  | 'paiement_internet'
  | 'paiement_electricite_eau'
  | 'paiement_telephone'
  | 'paiement_maintenance'
  | 'salaire'
  | 'prime'
  | 'indemnite'
  | 'per_diem'
  | 'remboursement_transport'
  | 'organisation_formation'
  | 'organisation_reunion'
  | 'organisation_atelier'
  | 'frais_mission'
  | 'frais_deplacement'
  | 'depense_exceptionnelle'
  | 'autre_sortie'

export interface SortieFonds {
  id: string
  type_sortie: TypeSortieFonds
  requisition_id?: string
  requisition?: Requisition
  montant_paye: Money
  date_paiement: string
  mode_paiement: ModePatement
  reference: string
  motif: string
  rubrique_code?: string
  beneficiaire: string
  piece_justificative?: string
  commentaire?: string
  created_by: string
  created_at: string
}

export interface Rubrique {
  id: string
  code: string
  libelle: string
  description?: string
  active: boolean
}
