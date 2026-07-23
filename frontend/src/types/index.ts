export type UserRole = string
export type SystemRole = 'admin' | 'caissier' | 'reporting_viewer'
export type Money = string | number

export interface User {
  id: string
  email: string
  nom: string
  prenom: string
  role: UserRole
  role_id?: number | null
  service_id?: number | null
  service_ids?: number[]
  active: boolean
  must_change_password: boolean
  is_email_verified: boolean
  is_first_login: boolean
  created_at: string
  organisation_id?: number | null
  organisation_uuid?: string | null
  organisation_slug?: string | null
  organisation_name?: string | null
  plan_status?: string | null
  plan_type?: string | null
  plan_expires_at?: string | null
  user_limit?: number | null
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

export type ModePaiement = 'cash' | 'mobile_money' | 'virement' | 'card' | 'cheque'

export type TypeClient =
  | 'expert_comptable'
  | 'client_externe'
  | 'banque_institution'
  | 'partenaire'
  | 'organisation'
  | 'autre'

export type StatutPaiement = 'non_paye' | 'partiel' | 'complet' | 'avance'

export interface PaymentHistory {
  id: string
  encaissement_id: string
  montant: Money
  mode_paiement: ModePaiement
  reference?: string
  notes?: string
  created_at: string
  created_by: string
}

export interface EncaissementArticle {
  id: string
  encaissement_id: string
  libelle: string
  description?: string | null
  quantite: Money
  prix_unitaire: Money
  montant: Money
  sort_order: number
  created_at: string
}

export interface Encaissement {
  id: string
  numero_recu?: string | null
  numero_proforma?: string | null
  est_proforma?: boolean
  source_proforma_id?: string | null
  type_client: TypeClient
  expert_comptable_id?: string
  expert_comptable?: ExpertComptable
  client_nom?: string
  libelle: string
  description: string
  montant: Money
  montant_total: Money
  montant_paye: Money
  montant_percu: Money
  devise_perception: 'USD' | 'CDF'
  taux_change_applique: Money
  canal?: 'CAISSE' | 'BANQUE'
  compte_bancaire_id?: number | null
  budget_poste_id?: number | null
  budget_poste_code?: string | null
  budget_poste_libelle?: string | null
  service_id?: number | null
  statut_paiement: StatutPaiement
  statut_operation?: 'ACTIVE' | 'ANNULEE'
  motif_annulation?: string | null
  annulee_le?: string | null
  annulee_par_id?: string | null
  annulation_ip?: string | null
  ancien_statut_operation?: string | null
  mode_paiement: ModePaiement
  reference?: string
  date_encaissement: string
  date_paiement?: string | null
  created_by: string
  created_by_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  annulee_par_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  created_at: string
  payment_history?: PaymentHistory[]
  articles?: EncaissementArticle[]
}

export type StatutRequisition =
  | 'EN_ATTENTE_COMMISSION'
  | 'EN_ATTENTE'
  | 'SIGNEE_SERVICE'
  | 'AUTORISEE'
  | 'APPROUVEE'
  | 'PAYEE'
  | 'REJETEE'
  | 'PENDING_VALIDATION_IMPORT'

export type StatutExamenRequisition = 'NON_EXAMINE' | 'EN_EXAMEN' | 'EXAMINE' | 'REJETE'

export interface LigneRequisition {
  id: string
  requisition_id: string
  budget_poste_id?: number | null
  rubrique: string
  description: string
  quantite: number
  montant_unitaire: Money
  montant_total: Money
  budget_poste_code_snapshot?: string | null
  budget_poste_libelle_snapshot?: string | null
  montant_alloue_snapshot?: Money | null
  montant_disponible_snapshot?: Money | null
}

export interface RequisitionAnnexe {
  id: string
  requisition_id: string
  file_path: string
  filename: string
  file_type: string
  upload_date: string
}

export interface OrdreDecaissement {
  id: string
  organisation_id: number
  /** null = ordre de sortie directe (sans réquisition) */
  requisition_id?: string | null
  numero_ordre: string
  beneficiaire: string
  montant: Money
  devise: 'USD' | 'CDF' | string
  motif?: string | null
  statut: 'AUTORISE' | 'PAYE' | 'ANNULE' | string
  autorise_par?: string | null
  autorise_le?: string | null
  autorise_par_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  paye_par?: string | null
  paye_le?: string | null
  paye_par_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  sortie_fonds_id?: string | null
  sortie_reference_numero?: string | null
  annule_par?: string | null
  annule_le?: string | null
  motif_annulation?: string | null
  created_at: string
  requisition_numero?: string | null
  requisition_objet?: string | null
  requisition_montant_total?: Money | null
  requisition_status?: string | null
}

export interface Requisition {
  id: string
  numero_requisition: string
  reference_numero?: string | null
  objet: string
  type_requisition?: string | null
  status?: StatutRequisition | string
  statut: StatutRequisition
  mode_paiement: ModePaiement
  montant_total: Money
  montant_deja_paye?: Money
  lignes_count?: number | null
  service_id?: number | null
  compte_bancaire_id?: number | null
  dossier_id?: string | null
  examen_status?: StatutExamenRequisition | string
  examen_commentaire?: string | null
  examen_par?: string | null
  examen_le?: string | null
  created_by: string
  validee_par?: string
  validee_le?: string
  approuvee_par?: string
  approuvee_le?: string
  signed_by_id?: string
  signed_at?: string
  payee_par?: string
  payee_le?: string
  motif_rejet?: string
  a_valoir?: boolean
  decaissement_progressif?: boolean
  instance_beneficiaire?: string
  notes_a_valoir?: string
  req_titre_officiel_hist?: string
  req_label_gauche_hist?: string
  req_nom_gauche_hist?: string
  req_label_droite_hist?: string
  req_nom_droite_hist?: string
  signataire_g_label?: string
  signataire_g_nom?: string
  signataire_d_label?: string
  signataire_d_nom?: string
  created_at: string
  updated_at: string
  lignes?: LigneRequisition[]
  annexe?: RequisitionAnnexe | null
  demandeur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  validateur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  approbateur?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
  caissier?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null }
}

export interface Service {
  id: number
  code: string
  libelle: string
  is_active: boolean
  responsable_id?: string | null
  responsable?: {
    id: string
    nom?: string | null
    prenom?: string | null
    email?: string | null
  } | null
}

export type CommissionRole = 'PRESIDENT' | 'DELEGUE' | 'MEMBRE' | 'ASSISTANT'

export interface ServiceMemberFunction {
  id: number
  service_id: number
  label: string
  sort_order: number
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CommissionMember {
  id: number
  service_id: number
  user_id?: string | null
  full_name: string
  email?: string | null
  matricule?: string | null
  function_id?: number | null
  function_label?: string | null
  function?: ServiceMemberFunction | null
  role_type: CommissionRole
  custom_title?: string | null
  is_signer: boolean
  created_at: string
  user?: {
    id: string
    nom?: string | null
    prenom?: string | null
    email?: string | null
  } | null
}

export interface ServiceConsumptionItem {
  budget_poste_id?: number | null
  code?: string | null
  libelle?: string | null
  total_paye: Money
}

export interface ServiceConsumption {
  service_id: number
  total_budget_prevu?: Money
  total_depenses: Money
  total_recettes: Money
  requisitions_en_attente: number
  detail_par_rubrique: ServiceConsumptionItem[]
}

export type TypeSortieFonds =
  | 'requisition'
  | 'remboursement'
  | 'versement_banque'
  | 'approvisionnement_caisse'
  | 'sortie_directe'

export interface SortieFonds {
  id: string
  type_sortie: TypeSortieFonds
  requisition_id?: string
  requisition?: Requisition
  montant_paye: Money
  date_paiement: string
  mode_paiement: ModePaiement
  reference: string
  reference_numero?: string | null
  statut?: string
  motif_annulation?: string | null
  annulee_le?: string | null
  annulee_par_id?: string | null
  annulation_ip?: string | null
  ancien_statut?: string | null
  motif: string
  rubrique_code?: string
  budget_poste_id?: number | null
  budget_poste_code?: string | null
  budget_poste_libelle?: string | null
  exchange_rate_snapshot?: number | null
  beneficiaire: string
  piece_justificative?: string
  commentaire?: string
  annexes?: string[] | null
  created_by: string
  created_by_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  annulee_par_user?: { id: string; prenom?: string | null; nom?: string | null; email?: string | null } | null
  created_at: string
}

export interface Rubrique {
  id: string
  code: string
  libelle: string
  description?: string
  active: boolean
}
