import { apiRequest } from '../lib/apiClient'

/** Importer des notes de débit : émettre des créances en nombre. */
export const PERMISSION_IMPORT_NOTES_DEBIT = 'treso.experts_comptables.import_notes_debit'

export type StatutNotes = 'impayees' | 'soldees' | 'toutes'

export const LIBELLE_STATUT_NOTE: Record<string, string> = {
  non_paye: 'Émise',
  partiel: 'Partiellement payée',
  complet: 'Payée',
  avance: 'Payée (avance)',
}

export interface NoteDebitExpert {
  id: string
  numero_recu: string | null
  numero_note_externe: string | null
  exercice: number | null
  date_encaissement: string | null
  jours: number
  libelle: string
  type_client: 'expert_comptable' | 'sec'
  expert: {
    id: string
    numero_ordre: string
    nom: string
    type_ec: string
    statut_professionnel: string | null
  }
  montant_total: string
  montant_paye: string
  reste_du: string
  statut_paiement: string
  statut_operation: string
  relance_count: number
  importee: boolean
}

export interface ListeNotesDebit {
  items: NoteDebitExpert[]
  /** Nombre de notes de toute la sélection, pas de la seule page. */
  total: number
  totaux: { montant_total: string; montant_paye: string; reste_du: string }
}

export type StatutSituationMembre = 'toutes' | 'en_retard' | 'partiel' | 'en_regle' | 'en_avance'

export interface SituationMembre {
  expert: NoteDebitExpert['expert']
  type_client: 'expert_comptable' | 'sec'
  cotisations_anterieures: string
  penalites_anterieures: string
  cotisation_n: string
  penalites_n: string
  autres_creances: string
  total_creances: string
  reglements: string
  reste_du: string
  avance_n_plus_1: string
  nb_notes: number
  statut: Exclude<StatutSituationMembre, 'toutes'>
  autres_details: {
    libelle: string
    exercice: number
    montant: string
    paye: string
    reste: string
  }[]
}

/** Colonnes de la situation des membres, rattachées chacune à un poste de recette. */
export type ColonneSituation =
  | 'cotisations_anterieures'
  | 'penalites_anterieures'
  | 'cotisation_n'
  | 'penalites_n'
  | 'autres_creances'

export interface RattachementPoste {
  colonne: ColonneSituation
  /** « * » : toutes les catégories qui n'ont pas leur propre poste. */
  categorie_membre: string
  budget_poste_code: string
  /** Le code ne désigne plus aucun poste de recette actif de l'exercice en cours. */
  introuvable?: boolean
}

export interface ParametresRattachements {
  colonnes: Array<{ cle: ColonneSituation; libelle: string }>
  categories: string[]
  postes: Array<{ code: string; libelle: string }>
  rattachements: RattachementPoste[]
  /** Proposition tirée des libellés du budget, tant que rien n'est enregistré. */
  suggestions: RattachementPoste[]
}

export const lireRattachementsNotesDebit = () =>
  apiRequest<ParametresRattachements>('GET', '/notes-debit/parametres/rattachements')

export const enregistrerRattachementsNotesDebit = (rattachements: RattachementPoste[]) =>
  apiRequest<ParametresRattachements>('PUT', '/notes-debit/parametres/rattachements', { rattachements })

export interface SituationNotesDebit {
  annee: number
  /** Poste de chaque colonne, par catégorie de membre (« * » = toutes). */
  rattachements?: Partial<Record<ColonneSituation, Array<{ categorie_membre: string; code: string; libelle: string | null }>>>
  /** Année de l'exercice budgétaire en cours : le N par défaut. */
  exercice_courant: number
  items: SituationMembre[]
  total: number
  totaux: Omit<
    SituationMembre,
    'expert' | 'type_client' | 'nb_notes' | 'statut' | 'autres_details'
  >
}

export const situationNotesDebit = (params: {
  annee?: number
  q?: string
  type_client?: string
  statut?: StatutSituationMembre
  limit?: number
  offset?: number
}) =>
  apiRequest<SituationNotesDebit>('GET', '/notes-debit/situation', {
    params: Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ),
  })

export const listerNotesDebit = (params: {
  q?: string
  statut?: StatutNotes
  type_client?: string
  import_id?: string
  exercice?: number
  limit?: number
  offset?: number
}) =>
  apiRequest<ListeNotesDebit>('GET', '/notes-debit', {
    params: Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ),
  })

/** Toute la sélection filtrée, page après page : l'API plafonne à 200 notes par appel. */
export async function listerToutesNotesDebit(params: {
  q?: string
  statut?: StatutNotes
  type_client?: string
  import_id?: string
  exercice?: number
}): Promise<ListeNotesDebit> {
  const PAGE = 200
  const premiere = await listerNotesDebit({ ...params, limit: PAGE, offset: 0 })
  const items = [...premiere.items]
  while (items.length < premiere.total) {
    const suite = await listerNotesDebit({ ...params, limit: PAGE, offset: items.length })
    if (!suite.items.length) break
    items.push(...suite.items)
  }
  return { ...premiere, items }
}

/** Toute la situation filtrée, page après page : ce que les exports reprennent. */
export async function situationCompleteNotesDebit(params: {
  annee?: number
  q?: string
  type_client?: string
  statut?: StatutSituationMembre
}): Promise<SituationNotesDebit> {
  const PAGE = 200
  const premiere = await situationNotesDebit({ ...params, limit: PAGE, offset: 0 })
  const items = [...premiere.items]
  while (items.length < premiere.total) {
    const suite = await situationNotesDebit({ ...params, limit: PAGE, offset: items.length })
    if (!suite.items.length) break
    items.push(...suite.items)
  }
  return { ...premiere, items }
}

/** Onglets d'import, comme ceux de l'import national des experts. */
export type CategorieImportNotes = 'toutes' | 'ec' | 'sec' | 'penalites'

export interface ColonneAnalysee {
  /** Index de la colonne dans la feuille : la clé des montants et des postes. */
  cle: string
  categorie?: string | null
  libelle: string
  arrieres: boolean
  tarif: { id: number; libelle: string; montant: string | null; poste_code: string | null } | null
  /** Le tarif fixe le poste : il ne se choisit pas ici. */
  poste_impose: boolean
  poste_suggere_id: number | null
  erreur: string | null
  /** Non bloquant : une colonne qui ne correspond pas à l'onglet choisi. */
  avertissement: string | null
  total: string
  nb_lignes: number
}

export interface LigneAnalysee {
  ligne: number
  numero_ordre: string
  nom: string
  numero_note_externe: string | null
  date_note: string | null
  exercice: number | null
  devise: 'USD' | 'CDF'
  date_echeance: string | null
  reference_decision: string | null
  observation: string | null
  expert: { id: string; numero_ordre: string; nom: string; type_ec: string } | null
  montants: Record<string, string>
  total: string
  statut: 'ok' | 'avertissement' | 'erreur'
  doublon: boolean
  erreurs: string[]
  avertissements: string[]
  problemes: ProblemeImport[]
  creances: LigneCreance[]
  /** Mode actualisation : ce que la ligne fera de la note déjà émise. */
  actualisation: ActualisationLigne | null
}

/** Familles de créances qu'un réimport peut remplacer sur une note déjà émise. */
export type FamilleActualisation = 'cotisation' | 'penalites' | 'autres'

export const LIBELLE_FAMILLE: Record<FamilleActualisation, string> = {
  cotisation: 'Cotisation',
  penalites: 'Pénalités',
  autres: 'Autres créances',
}

/** Les familles que chaque onglet d'import peut actualiser (même règle que le serveur). */
export const FAMILLES_PAR_ONGLET: Record<CategorieImportNotes, FamilleActualisation[]> = {
  toutes: ['cotisation', 'penalites', 'autres'],
  ec: ['cotisation', 'autres'],
  sec: ['cotisation', 'autres'],
  penalites: ['penalites'],
}

export type ActualisationLigne =
  | { action: 'creer' | 'rien' }
  | {
      action: 'actualiser' | 'inchangee'
      note_id: string
      numero: string
      ancien_total: string
      nouveau_total: string
      paye: string
      surplus: string
    }

export interface ProblemeImport {
  feuille: string
  ligne: number
  champ: string
  valeur: string
  message: string
  code: string
  niveau: 'ERREUR' | 'AVERTISSEMENT'
}

export interface LigneCreance {
  categorie: string
  exercice: number
  libelle: string
  montant: string
  devise: 'USD' | 'CDF'
  reference_decision: string | null
  observation: string | null
  feuille: string
  ligne: number
}

export interface AnalyseImport {
  fichier: string
  format_import: 'historique' | 'structure'
  categorie: CategorieImportNotes
  actualiser: FamilleActualisation[]
  ligne_entete: number
  exercice: number
  exercice_ouvert: boolean
  service_id: number | null
  services: { id: number; code: string; libelle: string }[]
  postes: { id: number; code: string; libelle: string }[]
  colonnes: ColonneAnalysee[]
  colonnes_ignorees: { libelle: string; raison: string }[]
  colonne_numero: boolean
  problemes: ProblemeImport[]
  lignes: LigneAnalysee[]
  resume: {
    nb_lignes: number
    nb_ok: number
    nb_avertissements: number
    nb_erreurs: number
    nb_doublons: number
    total: string
    total_arrieres: string
    membres_introuvables: number
    numeros_existants: number
    montants_incoherents: number
    arrieres_non_ventiles: number
    nb_a_actualiser?: number
    nb_inchangees?: number
    surplus_a_reporter?: string
  }
}

export interface ResultatImport {
  categorie: CategorieImportNotes
  import_id: string
  fichier: string
  nb_notes: number
  nb_notes_actualisees?: number
  avances_reportees?: { montant: string; depuis: { numero: string }; vers: { numero: string } }[]
  avances_en_attente?: { numero: string; montant: string; raison: string }[]
  nb_lignes_ecartees: number
  montant_total: string
  montant_arrieres: string
  notes: {
    id: string
    numero_recu: string
    numero_note_externe: string | null
    numero_ordre: string
    nom: string
    montant_total: string
  }[]
}

export const analyserImportNotes = (
  fichier: File,
  serviceId: number | null,
  categorie: CategorieImportNotes,
  actualiser: FamilleActualisation[] = [],
) => {
  const corps = new FormData()
  corps.append('fichier', fichier)
  corps.append('categorie', categorie)
  if (actualiser.length) corps.append('actualiser', actualiser.join(','))
  if (serviceId != null) corps.append('service_id', String(serviceId))
  return apiRequest<AnalyseImport>('POST', '/notes-debit/import/analyse', { body: corps })
}

export const importerNotes = (
  fichier: File,
  options: {
    service_id: number | null
    postes: Record<string, number>
    importer_doublons: boolean
    categorie: CategorieImportNotes
    actualiser?: FamilleActualisation[]
  },
) => {
  const corps = new FormData()
  corps.append('fichier', fichier)
  corps.append('options', JSON.stringify(options))
  return apiRequest<ResultatImport>('POST', '/notes-debit/import', { body: corps })
}

export interface ImportNotesDebit {
  id: string
  fichier: string
  nb_notes: number
  nb_notes_actualisees?: number
  nb_lignes_ecartees: number
  montant_total: string
  montant_arrieres: string
  colonnes: { libelle: string; arrieres: boolean; poste_code: string }[]
  created_at: string | null
  auteur: string | null
}

export const listerImportsNotes = () => apiRequest<ImportNotesDebit[]>('GET', '/notes-debit/imports')

export interface CompteDePaiement {
  banque: string | null
  intitule: string
  numero_compte: string
  devise: string
  code_swift_bic: string | null
}

export interface ExpertDocument {
  id: string
  numero_ordre: string
  nom: string
  type_ec: string
  statut_professionnel: string | null
  email: string | null
  telephone: string | null
  province: string | null
}

/** Une note telle qu'elle s'imprime : ses lignes, son débiteur. */
export interface DocumentNote {
  id: string
  numero_recu: string | null
  numero_note_externe: string | null
  exercice: number | null
  date_echeance: string | null
  reference_decision: string | null
  observation: string | null
  date_encaissement: string | null
  libelle: string
  type_client: 'expert_comptable' | 'sec'
  statut_paiement: string
  statut_operation: string
  montant_total: string
  montant_paye: string
  reste_du: string
  articles: {
    libelle: string
    categorie: string
    categorie_libelle: string
    exercice: number | null
    reference_decision: string | null
    observation: string | null
    quantite: string
    prix_unitaire: string
    montant: string
    poste_code: string | null
  }[]
  expert: ExpertDocument
}

export interface EvenementNote {
  date: string | null
  type: 'emission' | 'paiement' | 'paiement_annule' | 'relance' | 'mise_en_demeure' | 'annulation' | 'journal'
  libelle: string
  auteur: string | null
}

export interface FicheNote extends DocumentNote {
  description: string | null
  relance_count: number
  derniere_relance_le: string | null
  nb_paiements: number
  nb_mises_en_demeure: number
  import: { id: string; fichier: string } | null
  historique: EvenementNote[]
  comptes: CompteDePaiement[]
}

export interface ReleveMembre {
  expert: ExpertDocument
  notes: DocumentNote[]
  total_du: string
  comptes: CompteDePaiement[]
}

export interface MiseEnDemeure extends ReleveMembre {
  emise_le: string
  echeance: string
  delai_jours: number
}

export const ficheNoteDebit = (id: string) => apiRequest<FicheNote>('GET', `/notes-debit/${id}`)

export const documentsNotesDebit = (params: { ids?: string[]; import_id?: string }) =>
  apiRequest<{ notes: DocumentNote[]; comptes: CompteDePaiement[] }>('GET', '/notes-debit/documents', {
    params: params.ids ? { ids: params.ids.join(',') } : { import_id: params.import_id },
  })

export const mettreEnDemeure = (expertId: string, delaiJours: number) =>
  apiRequest<MiseEnDemeure>('POST', `/notes-debit/membres/${expertId}/mise-en-demeure`, {
    body: { delai_jours: delaiJours },
  })

export const relancerParEmail = (noteId: string) =>
  apiRequest<{ detail?: string }>('POST', `/encaissements/${noteId}/relance-solde`)

export interface AgregatRecouvrement {
  emis: string
  encaisse: string
  reste: string
  nb: number
  taux: number
}

export interface TableauDeBordNotes {
  annee: number
  /** Année de l'exercice budgétaire en cours : le N par défaut. */
  exercice_courant: number
  kpi: {
    emis: string
    encaisse: string
    /** Dû sur les notes de l'exercice. */
    reste_annee: string
    /** Dû à la fin de l'exercice, arriérés compris. */
    reste_total: string
    arrieres_anterieurs: string
    taux_recouvrement: number
    nb_notes: number
    penalites_dues: string
    membres_non_en_regle: number
  }
  par_type: (AgregatRecouvrement & { type_client: 'expert_comptable' | 'sec' })[]
  par_libelle: { libelle: string; emis: string; nb: number }[]
  anciennete: { tranche: 'moins_30' | '30_60' | '60_90' | 'plus_90'; reste: string; nb: number }[]
  par_province: (AgregatRecouvrement & { province: string })[]
  top_debiteurs: { expert_id: string; numero_ordre: string; nom: string; type_ec: string; reste: string; nb_notes: number }[]
}

/** Sans année, le serveur prend l'exercice budgétaire en cours. */
export const tableauDeBordNotes = (annee: number | null) =>
  apiRequest<TableauDeBordNotes>('GET', '/notes-debit/tableau-de-bord', {
    params: annee == null ? {} : { annee },
  })

export type StatutRegularite = 'en_regle' | 'non_en_regle' | 'sans_note'

export interface RegulariteMembres {
  annee: number
  tableau: number
  membres: Record<string, { statut: StatutRegularite; reste_du: string; nb_notes_dues: number; nb_notes_annee: number }>
}

export const regulariteMembres = (expertIds: string[], annee?: number) =>
  apiRequest<RegulariteMembres>('GET', '/notes-debit/regularite', {
    params: { expert_ids: expertIds.join(','), ...(annee ? { annee } : {}) },
  })
