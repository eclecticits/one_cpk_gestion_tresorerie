import { TypeClient, TypeOperation } from '../types'

export const TYPE_CLIENT_LABELS: Record<TypeClient, string> = {
  expert_comptable: 'Expert-comptable',
  client_externe: 'Client externe',
  banque_institution: 'Banque / Institution',
  partenaire: 'Partenaire',
  organisation: 'Organisation',
  autre: 'Autre',
}

export const OPERATIONS_PAR_TYPE_CLIENT: Record<TypeClient, { value: TypeOperation; label: string }[]> = {
  expert_comptable: [
    { value: 'cotisation_annuelle', label: 'Cotisation annuelle' },
    { value: 'cotisation_trimestrielle', label: 'Cotisation trimestrielle' },
    { value: 'inscription_tableau', label: 'Inscription au tableau' },
    { value: 'reinscription', label: 'Réinscription' },
    { value: 'formation', label: 'Formation' },
    { value: 'seminaire_atelier', label: 'Séminaire / Atelier' },
    { value: 'achat_documents', label: 'Achat de documents' },
    { value: 'penalites_amendes', label: 'Pénalités / amendes' },
    { value: 'regularisation', label: 'Régularisation' },
    { value: 'contribution_speciale', label: 'Contribution spéciale' },
    { value: 'autres_paiements_pro', label: 'Autres paiements professionnels' },
  ],
  client_externe: [
    { value: 'achat_formation', label: 'Achat de formation' },
    { value: 'frais_participation_evenement', label: 'Frais de participation événement' },
    { value: 'achat_documents_client', label: 'Achat de documents' },
    { value: 'frais_attestation', label: "Frais d'attestation" },
    { value: 'frais_certification', label: 'Frais de certification' },
    { value: 'frais_service', label: 'Frais de service' },
    { value: 'contribution', label: 'Contribution' },
    { value: 'don_soutien', label: 'Don / soutien' },
  ],
  banque_institution: [
    { value: 'depot_bancaire', label: 'Dépôt bancaire' },
    { value: 'versement_bancaire', label: 'Versement bancaire' },
    { value: 'virement_bancaire_recu', label: 'Opération bancaire' },
    { value: 'subvention', label: 'Subvention' },
    { value: 'appui_financier', label: 'Appui financier' },
    { value: 'financement_projet', label: 'Financement de projet' },
    { value: 'interets_bancaires', label: 'Intérêts bancaires' },
    { value: 'remboursement_bancaire', label: 'Remboursement bancaire' },
    { value: 'don_institutionnel', label: 'Don institutionnel' },
    { value: 'transfert_fonds', label: 'Transfert de fonds' },
  ],
  partenaire: [
    { value: 'partenariat', label: 'Partenariat' },
    { value: 'sponsoring', label: 'Sponsoring' },
    { value: 'financement_activite', label: "Financement d'activité" },
    { value: 'autre_encaissement', label: 'Autre encaissement' },
  ],
  organisation: [
    { value: 'partenariat', label: 'Partenariat' },
    { value: 'sponsoring', label: 'Sponsoring' },
    { value: 'financement_activite', label: "Financement d'activité" },
    { value: 'contribution', label: 'Contribution' },
    { value: 'don_soutien', label: 'Don / soutien' },
    { value: 'autre_encaissement', label: 'Autre encaissement' },
  ],
  autre: [
    { value: 'autre_encaissement', label: 'Autre encaissement' },
    { value: 'don_soutien', label: 'Don / soutien' },
    { value: 'contribution', label: 'Contribution' },
  ],
}

export function getOperationLabel(operation: TypeOperation): string {
  for (const operations of Object.values(OPERATIONS_PAR_TYPE_CLIENT)) {
    const found = operations.find(op => op.value === operation)
    if (found) return found.label
  }

  const legacyLabels: Record<string, string> = {
    formation: 'Formation',
    livre: 'Livre',
    autre: 'Autre',
  }

  return legacyLabels[operation] || operation
}

export function getTypeClientLabel(typeClient: TypeClient): string {
  return TYPE_CLIENT_LABELS[typeClient] || typeClient
}
