import { apiRequest } from '../lib/apiClient'
import type {
  ComptaBalance,
  ComptaCompte,
  ComptaEcriture,
  ComptaGrandLivre,
  ComptaLivreJournal,
  ComptaRestitutionFiltres,
  ComptaEcritureCreateInput,
  ComptaEcritureListResponse,
  ComptaEcrituresListParams,
  ComptaExercice,
  ComptaJournal,
  ComptaMappingCompteBancaire,
  ComptaMappingPoste,
  ComptaMappingRubrique,
  ComptaMappings,
  ComptaMappingsDefautResult,
  ComptaSetupInput,
  ComptaSetupResult,
  ComptaStatut,
} from '../types/comptabilite'

export async function getComptaStatut(): Promise<ComptaStatut> {
  return apiRequest<ComptaStatut>('GET', '/comptabilite/statut')
}

export async function setupComptabilite(input: ComptaSetupInput): Promise<ComptaSetupResult> {
  return apiRequest<ComptaSetupResult>('POST', '/comptabilite/setup', input)
}

export async function getComptaComptes(): Promise<ComptaCompte[]> {
  return apiRequest<ComptaCompte[]>('GET', '/comptabilite/comptes')
}

export async function getComptaJournaux(): Promise<ComptaJournal[]> {
  return apiRequest<ComptaJournal[]>('GET', '/comptabilite/journaux')
}

export async function getComptaExercices(): Promise<ComptaExercice[]> {
  return apiRequest<ComptaExercice[]>('GET', '/comptabilite/exercices')
}

export async function getComptaEcritures(
  params?: ComptaEcrituresListParams
): Promise<ComptaEcritureListResponse> {
  return apiRequest<ComptaEcritureListResponse>('GET', '/comptabilite/ecritures', { params })
}

export async function getComptaEcriture(id: string): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('GET', `/comptabilite/ecritures/${id}`)
}

export async function createComptaEcriture(
  input: ComptaEcritureCreateInput
): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', '/comptabilite/ecritures', input)
}

export async function validerComptaEcriture(id: string): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', `/comptabilite/ecritures/${id}/valider`)
}

export async function contrepasserComptaEcriture(
  id: string,
  motif: string
): Promise<ComptaEcriture> {
  return apiRequest<ComptaEcriture>('POST', `/comptabilite/ecritures/${id}/contrepasser`, { motif })
}

// ── Paramétrage des mappings ────────────────────────────────────────────────

export async function getComptaMappings(budgetExerciceId?: number): Promise<ComptaMappings> {
  return apiRequest<ComptaMappings>('GET', '/comptabilite/mappings', {
    params: budgetExerciceId ? { budget_exercice_id: budgetExerciceId } : undefined,
  })
}

export async function setComptaMappingPoste(
  budgetPosteId: number,
  compteId: number
): Promise<ComptaMappingPoste> {
  return apiRequest<ComptaMappingPoste>('PUT', `/comptabilite/mappings/poste/${budgetPosteId}`, {
    compte_id: compteId,
  })
}

export async function setComptaMappingCompteBancaire(
  compteBancaireId: number,
  compteId: number
): Promise<ComptaMappingCompteBancaire> {
  return apiRequest<ComptaMappingCompteBancaire>(
    'PUT',
    `/comptabilite/mappings/compte-bancaire/${compteBancaireId}`,
    { compte_id: compteId }
  )
}

export async function setComptaMappingRubrique(
  codeRubrique: string,
  compteId: number
): Promise<ComptaMappingRubrique> {
  return apiRequest<ComptaMappingRubrique>(
    'PUT',
    `/comptabilite/mappings/rubrique/${codeRubrique}`,
    { compte_id: compteId }
  )
}

export async function setComptaCaisseDefaut(compteId: number): Promise<ComptaMappingsDefautResult> {
  return apiRequest<ComptaMappingsDefautResult>('PUT', '/comptabilite/mappings/caisse-defaut', {
    compte_id: compteId,
  })
}

export async function appliquerComptaMappingsDefaut(): Promise<ComptaMappingsDefautResult> {
  return apiRequest<ComptaMappingsDefautResult>('POST', '/comptabilite/mappings/defaut')
}

// ── Restitutions ────────────────────────────────────────────────────────────

export async function getComptaBalance(filtres: ComptaRestitutionFiltres): Promise<ComptaBalance> {
  return apiRequest<ComptaBalance>('GET', '/comptabilite/balance', { params: filtres })
}

export async function getComptaGrandLivre(
  compteId: number,
  filtres: ComptaRestitutionFiltres & { curseur?: string; limite?: number }
): Promise<ComptaGrandLivre> {
  return apiRequest<ComptaGrandLivre>('GET', '/comptabilite/grand-livre', {
    params: { compte_id: compteId, ...filtres },
  })
}

export async function getComptaLivreJournal(
  journalId: number,
  filtres: ComptaRestitutionFiltres & { limite?: number }
): Promise<ComptaLivreJournal> {
  return apiRequest<ComptaLivreJournal>('GET', '/comptabilite/journal', {
    params: { journal_id: journalId, ...filtres },
  })
}
