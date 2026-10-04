import { apiRequest } from '../lib/apiClient'

/** Importer des notes de débit : émettre des créances en nombre. */
export const PERMISSION_IMPORT_NOTES_DEBIT = 'treso.experts_comptables.import_notes_debit'

export type StatutNotes = 'impayees' | 'soldees' | 'toutes'

export interface NoteDebitExpert {
  id: string
  numero_recu: string | null
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

export const listerNotesDebit = (params: {
  q?: string
  statut?: StatutNotes
  type_client?: string
  import_id?: string
  limit?: number
  offset?: number
}) =>
  apiRequest<ListeNotesDebit>('GET', '/notes-debit', {
    params: Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null),
    ),
  })

export interface ColonneAnalysee {
  /** Index de la colonne dans la feuille : la clé des montants et des postes. */
  cle: string
  libelle: string
  arrieres: boolean
  tarif: { id: number; libelle: string; montant: string | null; poste_code: string | null } | null
  /** Le tarif fixe le poste : il ne se choisit pas ici. */
  poste_impose: boolean
  poste_suggere_id: number | null
  erreur: string | null
  total: string
  nb_lignes: number
}

export interface LigneAnalysee {
  ligne: number
  numero_ordre: string
  nom: string
  expert: { id: string; numero_ordre: string; nom: string; type_ec: string } | null
  montants: Record<string, string>
  total: string
  statut: 'ok' | 'avertissement' | 'erreur'
  doublon: boolean
  erreurs: string[]
  avertissements: string[]
}

export interface AnalyseImport {
  fichier: string
  ligne_entete: number
  exercice: number
  exercice_ouvert: boolean
  service_id: number | null
  services: { id: number; code: string; libelle: string }[]
  postes: { id: number; code: string; libelle: string }[]
  colonnes: ColonneAnalysee[]
  colonnes_ignorees: { libelle: string; raison: string }[]
  colonne_numero: boolean
  lignes: LigneAnalysee[]
  resume: {
    nb_lignes: number
    nb_ok: number
    nb_avertissements: number
    nb_erreurs: number
    nb_doublons: number
    total: string
    total_arrieres: string
  }
}

export interface ResultatImport {
  import_id: string
  fichier: string
  nb_notes: number
  nb_lignes_ecartees: number
  montant_total: string
  montant_arrieres: string
  notes: { id: string; numero_recu: string; numero_ordre: string; nom: string; montant_total: string }[]
}

export const analyserImportNotes = (fichier: File, serviceId: number | null) => {
  const corps = new FormData()
  corps.append('fichier', fichier)
  if (serviceId != null) corps.append('service_id', String(serviceId))
  return apiRequest<AnalyseImport>('POST', '/notes-debit/import/analyse', { body: corps })
}

export const importerNotes = (
  fichier: File,
  options: { service_id: number | null; postes: Record<string, number>; importer_doublons: boolean },
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
  date_encaissement: string | null
  libelle: string
  type_client: 'expert_comptable' | 'sec'
  statut_paiement: string
  statut_operation: string
  montant_total: string
  montant_paye: string
  reste_du: string
  articles: { libelle: string; quantite: string; prix_unitaire: string; montant: string; poste_code: string | null }[]
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

export const tableauDeBordNotes = (annee: number) =>
  apiRequest<TableauDeBordNotes>('GET', '/notes-debit/tableau-de-bord', { params: { annee } })

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
