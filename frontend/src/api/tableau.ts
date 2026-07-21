import { apiRequest, API_BASE_URL, getAuthHeaders } from '../lib/apiClient'

const BASE = '/secretariat/tableau'

export interface TableauReglages {
  heures_formation_min?: number
  age_seuil?: number
  age_action?: 'a_deliberer' | 'inscrit' | 'aucune'
  age_conclusion_label?: string
  nouveau_anciennete_ans?: number
  exempter_nouveaux?: boolean
}

export interface TableauImport {
  id: number
  exercice: string
  file_name: string
  status: string
  total_rows: number
  imported_rows: number
  error_message: string | null
  created_at: string
}

export interface TableauDossier {
  id: number
  import_id: number
  exercice: string
  numero_ordre: string | null
  nom: string
  prenom: string | null
  categorie: string
  statut_membre: string | null
  cotisation_montant: number | null
  cotisation_payee: boolean | null
  heures_forco: number | null
  assurance: boolean | null
  chiffre_affaires: boolean | null
  sexe: string | null
  date_naissance: string | null
  age: number | null
  nif: string | null
  anciennete: string | null
  conclusion: string | null
  conclusion_motif: string | null
  email: string | null
  telephone: string | null
  cabinet: string | null
  statut_dossier: string
  anomalie_detectee: boolean
  created_at: string
}

export interface TableauAnalyse {
  id: number
  import_id: number
  exercice: string
  status: string
  total_dossiers: number
  dossiers_complets: number
  dossiers_incomplets: number
  anomalies_count: number
  doublons_count: number
  cotisations_non_payees: number
  heures_forco_insuffisantes: number
  assurances_manquantes: number
  observations_ia: string | null
  stats_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface TableauAnomalie {
  id: number
  dossier_id: number
  type_anomalie: string
  gravite: 'high' | 'medium' | 'low'
  description: string
  champ_concerne: string | null
  valeur_trouvee: string | null
  valeur_attendue: string | null
  status: string
  created_at: string
}

export interface TableauDecision {
  id: number
  dossier_id: number
  type_decision: string
  decision: string
  motif: string | null
  observations: string | null
  created_at: string
}

export interface TableauReport {
  id: number
  exercice: string
  type_rapport: string
  titre: string
  contenu: string | null
  format_sortie: string
  status: string
  created_at: string
  updated_at: string
}

export interface TableauStats {
  dossiers_importes: number
  dossiers_analyses: number
  dossiers_incomplets: number
  anomalies_detectees: number
  decisions_a_valider: number
  imports_count: number
  last_exercice: string | null
}

export interface TableauComparison {
  exercice_a: string
  exercice_b: string
  dossiers_en_commun: number
  nouveaux_dans_b: number
  absents_de_b: number
  changements_categorie: number
  details: Array<Record<string, unknown>>
}

export const getTableauStats = () =>
  apiRequest<TableauStats>('GET', `${BASE}/stats`)

export const listTableauImports = () =>
  apiRequest<TableauImport[]>('GET', `${BASE}/imports`)

export interface TableauImportResult {
  success: boolean
  import_id: number | null
  exercice: string
  file_name: string
  imported: number
  updated: number
  skipped: number
  total_lignes: number
  errors: Array<{ ligne?: number; champ?: string; message?: string }>
  message: string
}

export const uploadTableauExcel = (exercice: string, file: File) => {
  const form = new FormData()
  form.append('exercice', exercice)
  form.append('file', file)
  return apiRequest<TableauImportResult>('POST', `${BASE}/imports`, form)
}

export const listTableauDossiers = (params: {
  import_id?: number
  exercice?: string
  anomalie_only?: boolean
}) => {
  const q = new URLSearchParams()
  if (params.import_id !== undefined) q.set('import_id', String(params.import_id))
  if (params.exercice) q.set('exercice', params.exercice)
  if (params.anomalie_only) q.set('anomalie_only', 'true')
  const qs = q.toString()
  return apiRequest<TableauDossier[]>('GET', `${BASE}/dossiers${qs ? '?' + qs : ''}`)
}

export const runTableauAnalyse = (import_id: number) =>
  apiRequest<TableauAnalyse>('POST', `${BASE}/analyse?import_id=${import_id}`, {})

export const listTableauAnomalies = (params: { import_id?: number; gravite?: string } = {}) => {
  const q = new URLSearchParams()
  if (params.import_id !== undefined) q.set('import_id', String(params.import_id))
  if (params.gravite) q.set('gravite', params.gravite)
  const qs = q.toString()
  return apiRequest<TableauAnomalie[]>('GET', `${BASE}/anomalies${qs ? '?' + qs : ''}`)
}

export const compareTableauExercices = (exercice_a: string, exercice_b: string) =>
  apiRequest<TableauComparison>('POST', `${BASE}/compare`, { exercice_a, exercice_b })

export const listTableauReports = () =>
  apiRequest<TableauReport[]>('GET', `${BASE}/reports`)

export const generateTableauReport = (payload: {
  import_id: number
  exercice: string
  titre: string
  type_rapport?: string
  instructions?: string
}) => apiRequest<TableauReport>('POST', `${BASE}/reports`, payload)

export const generateTableauPV = (payload: {
  import_id: number
  exercice: string
  instructions?: string
}) => apiRequest<TableauReport>('POST', `${BASE}/pv`, payload)

export const updateTableauReglages = (import_id: number, reglages: TableauReglages) =>
  apiRequest<TableauReglages>('PUT', `${BASE}/reglages/${import_id}`, reglages)

/** Télécharge le tableau provincial de sortie (.xlsx) avec les conclusions. */
export const downloadTableauExport = async (import_id: number): Promise<void> => {
  const res = await fetch(`${API_BASE_URL}${BASE}/export/${import_id}`, {
    method: 'GET',
    headers: getAuthHeaders(`${BASE}/export/${import_id}`),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Export échoué (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `Tableau_${import_id}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const createTableauDecision = (payload: {
  dossier_id: number
  type_decision: string
  decision: string
  motif?: string
  observations?: string
}) => apiRequest<TableauDecision>('POST', `${BASE}/decisions`, payload)
