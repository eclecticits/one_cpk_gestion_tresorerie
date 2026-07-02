import { apiRequest } from '../lib/apiClient'

export type HREntityStatus = 'actif' | 'suspendu' | 'en_conge' | 'sorti'
export type AttendanceStatut = 'present' | 'absent' | 'demi_journee' | 'conge' | 'teletravail'

export interface HRService {
  id: number
  code: string
  libelle: string
  is_active: boolean
}

export interface HRFunction {
  id: number
  libelle: string
  is_active: boolean
}

export interface HREmployee {
  id: number
  matricule: string
  nom: string
  post_nom?: string | null
  prenom?: string | null
  sexe?: string | null
  date_naissance?: string | null
  lieu_naissance?: string | null
  telephone?: string | null
  email?: string | null
  adresse?: string | null
  service_id?: number | null
  fonction_id?: number | null
  service?: HRService | null
  fonction?: HRFunction | null
  statut: HREntityStatus
  date_entree?: string | null
  date_sortie?: string | null
  raison_sortie?: string | null
  photo_url?: string | null
  contact_urgence_nom?: string | null
  contact_urgence_telephone?: string | null
  created_at: string
}

export interface HRContract {
  id: number
  employee_id: number
  type_contrat: string
  date_debut: string
  date_fin?: string | null
  poste: string
  salaire_base?: string | null
  devise: string
  statut: string
  document_url?: string | null
}

export interface HRLeave {
  id: number
  employee_id: number
  type_absence: string
  date_debut: string
  date_fin: string
  nombre_jours: string
  motif?: string | null
  justificatif_url?: string | null
  statut: string
  validateur_id?: string | null
}

export interface HRDocument {
  id: number
  employee_id: number
  type_document: string
  titre: string
  fichier_url: string
  date_upload: string
  uploaded_by?: string | null
}

export interface HRDashboard {
  total_agents_actifs: number
  agents_en_conge: number
  contrats_expirant_bientot: number
  demandes_conge_en_attente: number
  masse_salariale_estimee?: string | null
  derniers_mouvements: { type: string; label: string; date: string }[]
  total_absences_mois: number
  nb_bulletins_en_attente: number
  taux_presence_mois?: number | null
}

export interface HRLeaveAllocation {
  id: number
  employee_id: number
  type_absence: string
  annee: number
  jours_alloues: string
  report_annee_precedente: string
  created_at: string
  updated_at: string
}

export interface HRLeaveBalance {
  employee_id: number
  type_absence: string
  annee: number
  jours_alloues: string
  report_annee_precedente: string
  jours_utilises: string
  solde: string
}

export interface HRAttendance {
  id: number
  employee_id: number
  date_presence: string
  statut_presence: AttendanceStatut
  heure_arrivee?: string | null
  heure_depart?: string | null
  note?: string | null
  created_at: string
}

export interface HRAttendanceSummary {
  mois: number
  annee: number
  total_jours_saisis: number
  presents: number
  absents: number
  demi_journees: number
  conges: number
  teletravail: number
  taux_presence?: number | null
}

export interface HRPayrollEntry {
  id: number
  mois: number
  annee: number
  statut: string
  note?: string | null
  nb_bulletins: number
  created_at: string
  updated_at: string
}

export interface HRSalarySlip {
  id: number
  payroll_entry_id: number
  employee_id: number
  salaire_base: string
  total_primes: string
  ipr: string
  cnss_salarie: string
  total_retenues: string
  net_a_payer: string
  devise: string
  jours_travailles?: number | null
  jours_absences?: number | null
  statut: string
  pdf_url?: string | null
  created_at: string
}

export interface HRReference {
  id: number
  category: string
  code: string
  libelle: string
  description?: string | null
  is_active: boolean
}

export interface HREvaluation {
  id: number
  employee_id: number
  annee: number
  periode: string
  note_globale?: string | null
  appreciation?: string | null
  objectifs_atteints?: string | null
  axes_amelioration?: string | null
  commentaire?: string | null
  statut: string
  created_at: string
  updated_at: string
}

export interface HRSanction {
  id: number
  employee_id: number
  type_sanction: string
  date_sanction: string
  motif: string
  description?: string | null
  duree_jours?: number | null
  statut: string
  created_at: string
  updated_at: string
}

export interface HRReportEffectifService {
  service: string
  total: number
  actifs: number
  en_conge: number
}

export interface HRReportPresence {
  mois: number
  annee: number
  presents: number
  absents: number
  demi_journees: number
  conges: number
  taux_presence?: number | null
}

export interface HRReportMasseSalariale {
  mois: number
  annee: number
  total_net: string
  nb_bulletins: number
  devise: string
}

export interface HRReportConge {
  type_absence: string
  total_demandes: number
  total_jours: string
  approuves: number
  en_attente: number
}

export interface HRReport {
  effectifs_par_service: HRReportEffectifService[]
  presences: HRReportPresence[]
  masse_salariale: HRReportMasseSalariale[]
  conges_par_type: HRReportConge[]
}

export const getHRDashboard = () => apiRequest<HRDashboard>('GET', '/hr/dashboard')
export const getHREmployees = (params?: { q?: string; statut?: string }) => apiRequest<HREmployee[]>('GET', '/hr/employees', { params })
export const getHREmployee = (id: number) => apiRequest<HREmployee>('GET', `/hr/employees/${id}`)
export const createHREmployee = (input: Partial<HREmployee>) => apiRequest<HREmployee>('POST', '/hr/employees', input)
export const updateHREmployee = (id: number, input: Partial<HREmployee>) => apiRequest<HREmployee>('PATCH', `/hr/employees/${id}`, input)
export const archiveHREmployee = (id: number) => apiRequest<HREmployee>('POST', `/hr/employees/${id}/archive`)

export const getHRContracts = (params?: { employee_id?: number }) => apiRequest<HRContract[]>('GET', '/hr/contracts', { params })
export const createHRContract = (input: Partial<HRContract>) => apiRequest<HRContract>('POST', '/hr/contracts', input)
export const updateHRContract = (id: number, input: Partial<HRContract>) => apiRequest<HRContract>('PATCH', `/hr/contracts/${id}`, input)

export const getHRLeaves = (params?: { employee_id?: number }) => apiRequest<HRLeave[]>('GET', '/hr/leaves', { params })
export const createHRLeave = (input: Partial<HRLeave>) => apiRequest<HRLeave>('POST', '/hr/leaves', input)
export const updateHRLeave = (id: number, input: Partial<HRLeave>) => apiRequest<HRLeave>('PATCH', `/hr/leaves/${id}`, input)
export const submitHRLeave = (id: number) => apiRequest<HRLeave>('POST', `/hr/leaves/${id}/submit`)
export const approveHRLeave = (id: number) => apiRequest<HRLeave>('POST', `/hr/leaves/${id}/approve`)
export const rejectHRLeave = (id: number) => apiRequest<HRLeave>('POST', `/hr/leaves/${id}/reject`)

export const getHRDocuments = (params?: { employee_id?: number }) => apiRequest<HRDocument[]>('GET', '/hr/documents', { params })
export const createHRDocument = (input: Partial<HRDocument>) => apiRequest<HRDocument>('POST', '/hr/documents', input)
export const updateHRDocument = (id: number, input: Partial<HRDocument>) => apiRequest<HRDocument>('PATCH', `/hr/documents/${id}`, input)

export const getHRServices = () => apiRequest<HRService[]>('GET', '/hr/settings/services')
export const createHRService = (input: Partial<HRService>) => apiRequest<HRService>('POST', '/hr/settings/services', input)
export const updateHRService = (id: number, input: Partial<HRService>) => apiRequest<HRService>('PATCH', `/hr/settings/services/${id}`, input)
export const getHRFunctions = () => apiRequest<HRFunction[]>('GET', '/hr/settings/functions')
export const createHRFunction = (input: Partial<HRFunction>) => apiRequest<HRFunction>('POST', '/hr/settings/functions', input)
export const updateHRFunction = (id: number, input: Partial<HRFunction>) => apiRequest<HRFunction>('PATCH', `/hr/settings/functions/${id}`, input)
export const getHRReferences = (category: string) => apiRequest<HRReference[]>('GET', `/hr/settings/references/${category}`)
export const createHRReference = (category: string, input: Partial<HRReference>) => apiRequest<HRReference>('POST', `/hr/settings/references/${category}`, input)
export const updateHRReference = (category: string, id: number, input: Partial<HRReference>) => apiRequest<HRReference>('PATCH', `/hr/settings/references/${category}/${id}`, input)

// Leave Allocations
export const getLeaveAllocations = (params?: { employee_id?: number; annee?: number }) =>
  apiRequest<HRLeaveAllocation[]>('GET', '/hr/leave-allocations', { params })
export const createLeaveAllocation = (input: Partial<HRLeaveAllocation>) =>
  apiRequest<HRLeaveAllocation>('POST', '/hr/leave-allocations', input)
export const updateLeaveAllocation = (id: number, input: Partial<HRLeaveAllocation>) =>
  apiRequest<HRLeaveAllocation>('PATCH', `/hr/leave-allocations/${id}`, input)
export const getLeaveBalance = (params: { employee_id: number; annee: number }) =>
  apiRequest<HRLeaveBalance[]>('GET', '/hr/leave-allocations/balance', { params })

// Attendances
export const getAttendances = (params?: { employee_id?: number; mois?: number; annee?: number }) =>
  apiRequest<HRAttendance[]>('GET', '/hr/attendances', { params })
export const createAttendance = (input: Partial<HRAttendance>) =>
  apiRequest<HRAttendance>('POST', '/hr/attendances', input)
export const updateAttendance = (id: number, input: Partial<HRAttendance>) =>
  apiRequest<HRAttendance>('PATCH', `/hr/attendances/${id}`, input)
export const getAttendanceSummary = (params: { mois: number; annee: number }) =>
  apiRequest<HRAttendanceSummary>('GET', '/hr/attendances/summary', { params })
export const batchCreateAttendance = (input: { employee_ids: number[]; date: string; statut: string }) =>
  apiRequest<HRAttendance[]>('POST', '/hr/attendances/batch', input)

// Payroll
export const getPayrollEntries = (params?: { annee?: number }) =>
  apiRequest<HRPayrollEntry[]>('GET', '/hr/payroll-entries', { params })
export const createPayrollEntry = (input: { mois: number; annee: number; note?: string }) =>
  apiRequest<HRPayrollEntry>('POST', '/hr/payroll-entries', input)
export const generateSalarySlips = (entryId: number) =>
  apiRequest<HRSalarySlip[]>('POST', `/hr/payroll-entries/${entryId}/generate-slips`)
export const validatePayrollEntry = (entryId: number) =>
  apiRequest<HRPayrollEntry>('POST', `/hr/payroll-entries/${entryId}/validate`)
export const getPayrollSlips = (entryId: number) =>
  apiRequest<HRSalarySlip[]>('GET', `/hr/payroll-entries/${entryId}/slips`)
export const getSalarySlips = (params?: { employee_id?: number; annee?: number }) =>
  apiRequest<HRSalarySlip[]>('GET', '/hr/salary-slips', { params })
export const getEmployeeSalarySlips = (employeeId: number, annee?: number) =>
  apiRequest<HRSalarySlip[]>('GET', '/hr/salary-slips', { params: { employee_id: employeeId, ...(annee ? { annee } : {}) } })

// Evaluations
export const getHREvaluations = (params?: { employee_id?: number; annee?: number }) =>
  apiRequest<HREvaluation[]>('GET', '/hr/evaluations', { params })
export const createHREvaluation = (input: Partial<HREvaluation>) =>
  apiRequest<HREvaluation>('POST', '/hr/evaluations', input)
export const updateHREvaluation = (id: number, input: Partial<HREvaluation>) =>
  apiRequest<HREvaluation>('PATCH', `/hr/evaluations/${id}`, input)
export const deleteHREvaluation = (id: number) =>
  apiRequest<void>('DELETE', `/hr/evaluations/${id}`)

// Sanctions
export const getHRSanctions = (params?: { employee_id?: number }) =>
  apiRequest<HRSanction[]>('GET', '/hr/sanctions', { params })
export const createHRSanction = (input: Partial<HRSanction>) =>
  apiRequest<HRSanction>('POST', '/hr/sanctions', input)
export const updateHRSanction = (id: number, input: Partial<HRSanction>) =>
  apiRequest<HRSanction>('PATCH', `/hr/sanctions/${id}`, input)
export const deleteHRSanction = (id: number) =>
  apiRequest<void>('DELETE', `/hr/sanctions/${id}`)

// Rapports
export const getHRReport = (params?: { annee?: number }) =>
  apiRequest<HRReport>('GET', '/hr/rapports', { params })
