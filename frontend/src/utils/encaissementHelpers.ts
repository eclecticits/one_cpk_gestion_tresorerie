import { TypeClient } from '../types'
import { Money, toNumber } from './amount'

export const TYPE_CLIENT_LABELS: Record<TypeClient, string> = {
  expert_comptable: 'Expert-comptable',
  personne_physique: 'Personne physique',
  personne_morale: 'Personne morale',
  partenaire: 'Partenaire',
  autre: 'Autre',
}

export function getTypeClientLabel(typeClient: TypeClient): string {
  return TYPE_CLIENT_LABELS[typeClient] || typeClient
}

/**
 * Seule la personne physique a un sexe, et il est alors obligatoire.
 *
 * Une personne morale ou un partenaire n'en ont pas. L'expert-comptable en
 * aurait un, mais il relève d'un autre référentiel, qui ne porte pas
 * l'information. Même liste que TYPES_CLIENT_AVEC_SEXE côté serveur.
 */
export const TYPES_CLIENT_AVEC_SEXE: TypeClient[] = ['personne_physique']

/** Libellé du champ nom selon ce qu'il désigne. */
export function libelleNomClient(typeClient: TypeClient): string {
  if (typeClient === 'personne_morale') return 'Raison sociale'
  if (typeClient === 'partenaire') return 'Nom du partenaire'
  return 'Nom du client'
}

export function typeClientDemandeLeSexe(typeClient: TypeClient): boolean {
  return TYPES_CLIENT_AVEC_SEXE.includes(typeClient)
}

/** Étiquette lisible d'un sexe stocké ('M' / 'F'), pour l'affichage. */
export const SEXE_LABELS: Record<string, string> = { M: 'Masculin', F: 'Féminin' }

/**
 * Ce que la pièce imprimée atteste vraiment, et donc comment elle s'appelle.
 *
 * Un encaissement porte deux documents sous une seule ligne. Tant que rien
 * n'est perçu, la pièce constate une dette à recouvrer : c'est une note de
 * débit. Dès qu'un montant est encaissé, la même pièce atteste un versement :
 * c'est un reçu de paiement, y compris quand le solde n'est pas apuré — on
 * remet bien un reçu pour ce qu'on a reçu. La pro forma, elle, n'atteste rien :
 * elle annonce, et garde son nom.
 */
export type NatureDocumentEncaissement = 'proforma' | 'recu' | 'note_debit'

/** Le strict nécessaire pour nommer le document, quel que soit l'appelant. */
export interface SourceDocumentEncaissement {
  est_proforma?: boolean | null
  montant_paye?: Money
}

interface IntitulesDocument {
  /** En-tête du document, en capitales. */
  titre: string
  /** Même intitulé en ligne courante (pied de page, infobulle). */
  libelle: string
  /** Intitulé précédé de son article défini, pour une phrase d'action. */
  avecArticle: string
  /** Accord du participe « annulé » sur le genre de l'intitulé. */
  accordAnnule: 'annulé' | 'annulée'
}

const INTITULES_DOCUMENT: Record<NatureDocumentEncaissement, IntitulesDocument> = {
  proforma: {
    titre: 'PRO FORMA DE NOTE DE DÉBIT',
    libelle: 'Pro forma de note de débit',
    avecArticle: 'la pro forma de note de débit',
    accordAnnule: 'annulée',
  },
  recu: {
    titre: 'REÇU DE PAIEMENT',
    libelle: 'Reçu de paiement',
    avecArticle: 'le reçu de paiement',
    accordAnnule: 'annulé',
  },
  note_debit: {
    titre: 'NOTE DE DÉBIT',
    libelle: 'Note de débit',
    avecArticle: 'la note de débit',
    accordAnnule: 'annulée',
  },
}

export function natureDocumentEncaissement(
  encaissement: SourceDocumentEncaissement | null | undefined,
): NatureDocumentEncaissement {
  if (encaissement?.est_proforma) return 'proforma'
  return toNumber(encaissement?.montant_paye) > 0 ? 'recu' : 'note_debit'
}

/** Titre porté par l'en-tête du document imprimé. */
export function titreDocumentEncaissement(encaissement: SourceDocumentEncaissement): string {
  return INTITULES_DOCUMENT[natureDocumentEncaissement(encaissement)].titre
}

/** Nom du document en ligne courante : pied de page, message, libellé de colonne. */
export function libelleDocumentEncaissement(encaissement: SourceDocumentEncaissement): string {
  return INTITULES_DOCUMENT[natureDocumentEncaissement(encaissement)].libelle
}

/** Bandeau d'annulation, accordé sur le nom du document. */
export function libelleDocumentAnnule(encaissement: SourceDocumentEncaissement): string {
  const intitules = INTITULES_DOCUMENT[natureDocumentEncaissement(encaissement)]
  return `${intitules.libelle.toUpperCase()} ${intitules.accordAnnule.toUpperCase()}`
}

/** Intitulé du bouton et de son infobulle : « Imprimer le reçu de paiement ». */
export function actionImprimerDocument(
  encaissement: SourceDocumentEncaissement,
  options: { annule?: boolean } = {},
): string {
  const intitules = INTITULES_DOCUMENT[natureDocumentEncaissement(encaissement)]
  const suffixe = options.annule ? ` ${intitules.accordAnnule}` : ''
  return `Imprimer ${intitules.avecArticle}${suffixe}`
}

/**
 * Date mise en avant : un reçu date le versement, une note de débit et une
 * pro forma datent leur émission, puisque aucun versement ne les accompagne.
 */
export function libelleDateDocument(encaissement: SourceDocumentEncaissement): string {
  return natureDocumentEncaissement(encaissement) === 'recu' ? 'Date de paiement' : "Date d'émission"
}
