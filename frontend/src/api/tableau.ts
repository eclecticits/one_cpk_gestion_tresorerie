import { apiRequest, API_BASE_URL, getAuthHeaders } from '../lib/apiClient'

const BASE = '/tableau'

export interface TableauActualisation {
  id: number; date_situation: string; revision_number: number; actualized_at: string
  status: string; reference_snapshot_id: number; imports_count: number; total_rows: number; is_current: boolean
}
export interface TableauActualisationRow {
  id: number; actualisation_id: number; identity_id: number; official_expert_id: string | null
  numero_ordre: string; reference_status: string; proposal_status: string
  official_values: Record<string, unknown>; proposed_values: Record<string, unknown>
  field_provenance: Record<string, unknown>; differences: Array<Record<string, unknown>>
  difference_codes: string[]; anomalies: Array<Record<string, unknown>>; anomaly_codes: string[]
}
export interface TableauActualisationStats { total: number; proposal_status: Record<string, number>; anomaly_rows: number; reference_status: Record<string, number> }
export const listTableauActualisations = (dateSituation?: string) => apiRequest<{items: TableauActualisation[]; total: number}>('GET', `${BASE}/actualisations${dateSituation ? `?date_situation=${encodeURIComponent(dateSituation)}` : ''}`)
export const listTableauActualisationRows = (id: number, params?: Record<string, string | number | boolean>) => {
  const qs = new URLSearchParams(Object.entries(params || {}).map(([k, v]) => [k, String(v)]))
  return apiRequest<{items: TableauActualisationRow[]; total: number; limit: number; offset: number}>('GET', `${BASE}/actualisations/${id}/lignes?${qs}`)
}
export const getTableauActualisationStats = (id: number) => apiRequest<TableauActualisationStats>('GET', `${BASE}/actualisations/${id}/stats`)
export const getTableauActualisationRow = (actualisationId: number, rowId: number) => apiRequest<TableauActualisationRow & { source_imports: unknown[]; ca_declarations: unknown[]; insurance_declarations: unknown[] }>('GET', `${BASE}/actualisations/${actualisationId}/lignes/${rowId}`)

export interface TableauReglages {
  heures_formation_min?: number
  age_seuil?: number
  age_action?: 'a_deliberer' | 'inscrit' | 'aucune'
  age_conclusion_label?: string
  nouveau_anciennete_ans?: number
  exempter_nouveaux?: boolean
  /** Écarts au barème, par catégorie et par critère. */
  criteres_par_categorie?: Record<string, Partial<Record<CritereTableau, ModeCritere>>>
  /** Barème d'origine, renvoyé par le serveur (lecture seule). */
  /** Ce que veut dire chaque condition, par catégorie (écarts aux définitions par défaut). */
  definitions_par_categorie?: Record<string, DefinitionsCategorie>
  /** Seules les colonnes de situation de la catégorie y figurent. */
  bareme?: Record<string, Partial<Record<CritereTableau, ModeCritere>>>
}

export interface DefinitionsCategorie {
  /** Minimum d'heures (NHV) ; absent = minimum général. */
  heures_formation_min?: number
  /** Les arriérés de cotisation doivent être soldés (défaut : oui). */
  cotisation_arrieres?: boolean
  /** Cotisation commencée mais pas soldée (défaut : à délibérer). */
  cotisation_partielle?: 'a_deliberer' | 'bloquant'
  /** Date (AAAA-MM-JJ) jusqu'à laquelle l'assurance doit au moins couvrir ; absente = date de situation. */
  assurance_fin_min?: string
}

export type CritereTableau = 'cotisation' | 'formation' | 'assurance' | 'chiffre_affaires'
/** bloquant : un défaut donne Non en règle ; a_deliberer : À délibérer ; ignore : non exigé. */
export type ModeCritere = 'bloquant' | 'a_deliberer' | 'ignore'

export interface TableauImport {
  id: number
  exercice: string
  date_situation: string
  source_type: 'personnes_physiques' | 'personnes_morales' | 'chiffres_affaires' | 'assurances' | 'tableau'
  file_name: string
  file_sha256: string | null
  file_size: number | null
  status: string
  total_rows: number
  imported_rows: number
  accepted_rows: number
  rejected_rows: number
  error_count: number
  error_message: string | null
  created_at: string
}

/** Cotisation lue dans les notes de débit (situation des membres). Fait foi sur l'import. */
export interface TableauCotisationNotes {
  payee: boolean
  etat: 'payee' | 'partielle' | 'non_payee'
  du_n: string
  reste_n: string
  du_anterieur: string
  reste_anterieur: string
  nb_notes: number
}

export interface TableauDossier {
  id: number
  import_id: number
  organisation_id: number | null
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
  annee_inscription: number | null
  anciennete_annees: number | null
  conclusion: string | null
  conclusion_motif: string | null
  email: string | null
  telephone: string | null
  cabinet: string | null
  statut_dossier: string
  anomalie_detectee: boolean
  created_at: string
  date_situation?: string | null
  source_file_name?: string | null
  organisation_nom?: string | null
  province?: string | null
  actif?: boolean | null
  anciennete_libelle?: string | null
  raison_sociale?: string | null
  associe_gerant?: string | null
  cotisation_notes?: TableauCotisationNotes | null
  /** Assurance selon la période de validité définie pour la catégorie. */
  assurance_valide?: boolean | null
}

export interface TableauAnalyse {
  id: number
  import_id: number
  exercice: string
  scope: 'import' | 'base'
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
  analyse_id: number | null
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
  /** null tant qu'aucune analyse de base à jour ne l'a établi : inconnu, pas nul. */
  dossiers_incomplets: number | null
  anomalies_detectees: number
  decisions_a_valider: number
  imports_count: number
  last_exercice: string | null
  analyse_base_status: 'completed' | 'stale' | null
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
  date_situation?: string | null
  source_type?: string
  status?: string
  duplicate_detected?: boolean
  file_sha256?: string | null
  file_name: string
  imported: number
  updated: number
  skipped: number
  total_lignes: number
  accepted_rows?: number
  rejected_rows?: number
  error_count?: number
  reprises?: number
  decisions_reportees?: number
  nouveaux_membres?: number
  errors: Array<{ feuille?: string; ligne?: number; champ?: string; message?: string }>
  message: string
}

export interface TableauBaseAnalyseItem {
  organisation_id: number
  organisation_nom: string | null
  status: 'ok' | 'erreur'
  detail: string | null
  analyse: TableauAnalyse | null
}

export interface TableauBaseAnalyseResult {
  exercice: string
  national: boolean
  analyses_count: number
  erreurs_count: number
  total_dossiers: number
  analyses: TableauAnalyse[]
  resultats: TableauBaseAnalyseItem[]
}

/** Analyse la situation consolidée de l'exercice, plutôt qu'un import isolé. */
export const runTableauAnalyseBase = (exercice: string, national = false) => {
  const qs = new URLSearchParams({ exercice })
  if (national) qs.set('national', 'true')
  return apiRequest<TableauBaseAnalyseResult>('POST', `${BASE}/analyses/base?${qs}`)
}

/** Membre d'un fichier personnes physiques ou morales, encore sans dossier ni conclusion. */
export interface TableauMembreACompleter {
  id: string
  import_id: number
  organisation_id: number
  organisation_nom: string | null
  numero_ordre: string | null
  nom: string
  categorie: string
  nif: string | null
  cabinet: string | null
  raison_sociale?: string | null
  associe_gerant?: string | null
  cotisation_notes?: TableauCotisationNotes | null
  assurance_valide?: boolean | null
  /** Conclusion des règles de délibération, calculée à la lecture. */
  conclusion?: string | null
  conclusion_motif?: string | null
  chiffre_affaires?: boolean | null
  formation_etat?: string | null
  email: string | null
  telephone: string | null
  assurance: boolean | null
  sexe: string | null
  nhv: number | null
  actif: boolean | null
  province: string | null
  annee_inscription: number | null
  anciennete_libelle: string | null
  date_situation: string | null
  source_file_name: string | null
  signalements: string[]
}

export interface TableauBase {
  exercice: string
  national: boolean
  organisations: number[]
  total_membres: number
  total_dossiers: number
  total_a_completer: number
  membres_a_completer: TableauMembreACompleter[]
  province_options: string[]
  membres_sans_numero: number
  imports_couverts: number[]
  analysis_import_id: number | null
  organisation_options: Array<{ id: number; nom: string }>
  limit: number
  offset: number
  dossiers: TableauDossier[]
}

/** Base consolidée du Tableau : une situation par membre, tous imports de l'exercice confondus. */
export interface FiltresRegles {
  conclusion?: '' | 'INSCRIT' | 'NON INSCRIT' | 'À DÉLIBÉRER' | 'SANS'
  cotisation?: '' | 'payee' | 'partielle' | 'non_payee' | 'inconnue'
  assurance?: '' | 'oui' | 'non' | 'inconnu'
  chiffre_affaires?: '' | 'oui' | 'non' | 'inconnu'
  formation?: '' | 'atteint' | 'insuffisant' | 'non_requis' | 'inconnu'
}

export const getTableauBase = (params?: {
  exercice?: string
  anomalieOnly?: boolean
  national?: boolean
  q?: string
  categorie?: string
  organisationId?: number
  personne?: string
  province?: string
  sexe?: string
  anciennete?: string
  actif?: string
  /** Filtres sur ce que calculent les règles de délibération. */
  regles?: FiltresRegles
  limit?: number
  offset?: number
}) => {
  const qs = new URLSearchParams()
  if (params?.exercice) qs.set('exercice', params.exercice)
  if (params?.anomalieOnly) qs.set('anomalie_only', 'true')
  if (params?.national) qs.set('national', 'true')
  if (params?.q) qs.set('q', params.q)
  if (params?.categorie) qs.set('categorie', params.categorie)
  if (params?.organisationId) qs.set('organisation_id', String(params.organisationId))
  if (params?.personne) qs.set('personne', params.personne)
  if (params?.province) qs.set('province', params.province)
  if (params?.sexe) qs.set('sexe', params.sexe)
  if (params?.anciennete) qs.set('anciennete', params.anciennete)
  if (params?.actif) qs.set('actif', params.actif)
  for (const [cle, valeur] of Object.entries(params?.regles || {})) if (valeur) qs.set(cle, valeur)
  if (params?.limit) qs.set('limit', String(params.limit))
  if (params?.offset) qs.set('offset', String(params.offset))
  const suffix = qs.toString() ? `?${qs}` : ''
  return apiRequest<TableauBase>('GET', `${BASE}/base${suffix}`)
}

export const uploadTableauExcel = (exercice: string, file: File, dateSituation: string, sourceType = 'tableau') => {
  const form = new FormData()
  form.append('exercice', exercice)
  form.append('date_situation', dateSituation)
  form.append('source_type', sourceType)
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

/** Catégories que le barème de délibération sait juger (miroir de CATEGORIE_CRITERES). */
export const TABLEAU_CATEGORIES = ['Société', 'EC Cabinet', 'EC Indépendant', 'EC Salarié', 'Stagiaire'] as const

/** Analyse enregistrée pour un import et un périmètre — null si aucune. */
export const getTableauAnalyse = (import_id: number, scope: 'import' | 'base' = 'import') =>
  apiRequest<TableauAnalyse | null>('GET', `${BASE}/analyses?import_id=${import_id}&scope=${scope}`)

export const runTableauAnalyse = (import_id: number) =>
  apiRequest<TableauAnalyse>('POST', `${BASE}/analyse?import_id=${import_id}`, {})

export const listTableauAnomalies = (params: { import_id?: number; gravite?: string; scope?: 'import' | 'base' } = {}) => {
  const q = new URLSearchParams()
  if (params.import_id !== undefined) q.set('import_id', String(params.import_id))
  if (params.gravite) q.set('gravite', params.gravite)
  if (params.scope) q.set('scope', params.scope)
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
  scope?: 'import' | 'base'
  instructions?: string
}) => apiRequest<TableauReport>('POST', `${BASE}/reports`, payload)

export const generateTableauPV = (payload: {
  import_id: number
  exercice: string
  scope?: 'import' | 'base'
  instructions?: string
}) => apiRequest<TableauReport>('POST', `${BASE}/pv`, payload)

/** Règles de délibération en vigueur pour l'exercice de cet import. */
export const getTableauReglages = (import_id: number) =>
  apiRequest<TableauReglages>('GET', `${BASE}/reglages/${import_id}`)

export const updateTableauReglages = (import_id: number, reglages: TableauReglages) =>
  apiRequest<TableauReglages>('PUT', `${BASE}/reglages/${import_id}`, reglages)

/** Télécharge le tableau provincial de sortie (.xlsx) avec les conclusions. */
export const downloadTableauExport = async (import_id: number, scope: 'import' | 'base' = 'import'): Promise<void> => {
  const path = `${BASE}/export/${import_id}?scope=${scope}`
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: getAuthHeaders(path),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Export échoué (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `Tableau_${scope === 'base' ? 'base_' : ''}${import_id}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Imports dont les conclusions peuvent réellement être comparées au rapport complet. */
export const listTableauImportsComparables = (import_id: number, scope: 'import' | 'base') =>
  apiRequest<{ id: number; file_name: string }[]>('GET', `${BASE}/rapport-complet/${import_id}/comparables?scope=${scope}`)

/** Télécharge le rapport complet de l'analyse (PDF ou Excel). */
export const downloadTableauRapportComplet = async (
  import_id: number,
  options: { format: 'pdf' | 'xlsx'; scope: 'import' | 'base'; exercice: string; comparer_a?: number | null },
): Promise<void> => {
  const qs = new URLSearchParams({ format: options.format, scope: options.scope })
  if (options.comparer_a) qs.set('comparer_a', String(options.comparer_a))
  const path = `${BASE}/rapport-complet/${import_id}?${qs}`
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: getAuthHeaders(path),
    credentials: 'include',
  })
  if (!res.ok) {
    const corps = await res.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof corps?.detail === 'string' ? corps.detail : `Génération du rapport échouée (${res.status})`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const disposition = res.headers.get('content-disposition')
  const nomServeur = disposition?.match(/filename="([^"]+)"/i)?.[1]
  a.href = url
  a.download = nomServeur || `Rapport_Tableau_${options.exercice}_${options.scope === 'base' ? 'base' : import_id}.${options.format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Télécharge le fichier importé, lignes à compléter en rouge. */
export const downloadTableauImportAnnote = async (import_id: number, file_name?: string | null): Promise<void> => {
  const path = `${BASE}/imports/${import_id}/fichier-annote`
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: getAuthHeaders(path),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Téléchargement échoué (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(file_name || `import_${import_id}`).replace(/\.xlsx?$/i, '')}_annote.xlsx`
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

export const correctTableauDossier = (
  dossierId: number,
  payload: { changes: Record<string, unknown>; clear_fields: string[]; motif: string },
) => apiRequest<TableauDossier>('PATCH', `${BASE}/dossiers/${dossierId}`, payload)

// ── Assistant et journal du module ───────────────────────────────────────────

export interface TableauAssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface TableauAssistantResponse {
  response: string
  actions_taken: string[]
  tool_results: Array<Record<string, unknown>>
}

/** Questions sur la base, les anomalies et les règles. L'assistant ne modifie rien. */
export const tableauAssistantChat = (input: {
  message: string
  conversation_history?: TableauAssistantMessage[]
}) => apiRequest<TableauAssistantResponse>('POST', `${BASE}/assistant/chat`, input)

export interface TableauAuditEntry {
  id: number
  action: string
  target_type: string | null
  target_id: string | null
  status: string
  user_id: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export const listTableauAudit = (params: { limit?: number; offset?: number; action?: string } = {}) => {
  const q = new URLSearchParams()
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  if (params.action) q.set('action', params.action)
  const qs = q.toString()
  return apiRequest<TableauAuditEntry[]>('GET', `${BASE}/audit${qs ? '?' + qs : ''}`)
}
