import { apiRequest } from '../lib/apiClient'

export async function uploadRemboursementTransportPdf(
  remboursementId: string,
  file: Blob,
  filename: string
): Promise<{ ok: boolean; pdf_path?: string }> {
  const form = new FormData()
  form.append('file', file, filename)
  return apiRequest('POST', `/remboursements-transport/${remboursementId}/pdf`, form)
}

// Brouillons : un remboursement se prépare avant la réunion (liste de présence)
// et se complète après. Il ne prend ni numéro ni réquisition avant d'être créé.
export type RemboursementTransportBrouillon = {
  id: string
  service_id: number
  service_code?: string | null
  service_libelle?: string | null
  contenu: Record<string, any>
  created_by?: string | null
  created_by_nom?: string | null
  updated_by_nom?: string | null
  created_at: string
  updated_at: string
}

export function listRemboursementTransportBrouillons(serviceId?: string | number | null) {
  return apiRequest<RemboursementTransportBrouillon[]>('GET', '/remboursements-transport/brouillons', {
    params: serviceId ? { service_id: serviceId } : undefined,
  })
}

export function saveRemboursementTransportBrouillon(
  id: string | null,
  serviceId: number,
  contenu: Record<string, any>,
) {
  const body = { service_id: serviceId, contenu }
  return id
    ? apiRequest<RemboursementTransportBrouillon>('PUT', `/remboursements-transport/brouillons/${id}`, { body })
    : apiRequest<RemboursementTransportBrouillon>('POST', '/remboursements-transport/brouillons', { body })
}

export function deleteRemboursementTransportBrouillon(id: string) {
  return apiRequest('DELETE', `/remboursements-transport/brouillons/${id}`)
}

// Convocation de la réunion préparée dans le brouillon : e-mail + invitation .ics.
export type ConvocationDestinataire = {
  nom: string
  titre_fonction?: string
  email?: string | null
  source?: 'convocation' | 'expert' | 'membre' | null
}

export type ConvocationResultat = {
  envoyes: number
  echecs: { email: string; raison: string }[]
  contenu: Record<string, any>
}

export function listDestinatairesConvocation(brouillonId: string) {
  return apiRequest<ConvocationDestinataire[]>(
    'GET',
    `/remboursements-transport/brouillons/${brouillonId}/destinataires`,
  )
}

export function envoyerConvocation(brouillonId: string, destinataires: ConvocationDestinataire[], message: string) {
  return apiRequest<ConvocationResultat>('POST', `/remboursements-transport/brouillons/${brouillonId}/convocation`, {
    body: { destinataires, message },
  })
}

// Pièces de la réunion, déposées sur le brouillon puis annexées à la
// réquisition à la création du remboursement.
export type PieceReunionKind = 'liste_presence' | 'pv'

export type PieceReunion = {
  file_path: string
  filename: string
  file_type: string
  file_size: number
  deposee_le: string
  deposee_par?: string | null
  annexee?: string
  version?: number | null
  supersedes_id?: string | null
  source?: string | null
  content_sha256?: string | null
}

export function pieceReunionPath(brouillonId: string, kind: PieceReunionKind) {
  return `/remboursements-transport/brouillons/${brouillonId}/pieces/${kind}`
}

export function deposerPieceReunion(brouillonId: string, kind: PieceReunionKind, file: Blob, filename: string) {
  const form = new FormData()
  form.append('file', file, filename)
  return apiRequest<RemboursementTransportBrouillon>('POST', pieceReunionPath(brouillonId, kind), form)
}

export function retirerPieceReunion(brouillonId: string, kind: PieceReunionKind) {
  return apiRequest<RemboursementTransportBrouillon>('DELETE', pieceReunionPath(brouillonId, kind))
}

// Pièces d'une réunion déjà passée en remboursement, même payé : elles vont
// directement en annexe de la réquisition. La plus récente de chaque sorte fait foi.
export type PiecesRemboursement = Record<PieceReunionKind, (PieceReunion & { annexe_id: string }) | null>

export function pieceRemboursementPath(remboursementId: string, kind: PieceReunionKind) {
  return `/remboursements-transport/${remboursementId}/pieces/${kind}`
}

export function listPiecesRemboursement(remboursementId: string) {
  return apiRequest<PiecesRemboursement>('GET', `/remboursements-transport/${remboursementId}/pieces`)
}

export function deposerPieceRemboursement(remboursementId: string, kind: PieceReunionKind, file: Blob, filename: string) {
  const form = new FormData()
  form.append('file', file, filename)
  return apiRequest<PiecesRemboursement>('POST', pieceRemboursementPath(remboursementId, kind), form)
}

export function annexerPiecesReunion(brouillonId: string, requisitionId: string) {
  return apiRequest<unknown[]>('POST', `/remboursements-transport/brouillons/${brouillonId}/annexer`, {
    body: { requisition_id: requisitionId },
  })
}

// Remboursements de transport d'un dossier, avec leurs participants : de quoi
// dresser l'état récapitulatif sans toucher aux états de frais sources.
export async function loadDossierRemboursementsTransport(dossierId: string) {
  const dossier = await apiRequest<any>('GET', `/dossiers/${dossierId}`)
  const requisitionIds: string[] = (dossier?.requisitions || [])
    .filter((req: any) => String(req?.type_requisition || '').toLowerCase() === 'remboursement_transport')
    .map((req: any) => String(req.id))
  const resultats = await Promise.all(
    requisitionIds.map((requisitionId) =>
      apiRequest<any>('GET', '/remboursements-transport', {
        params: { requisition_id: requisitionId, include: 'participants', limit: 1 },
      }),
    ),
  )
  const remboursements = resultats
    .map((res) => (Array.isArray(res) ? res[0] : res?.items?.[0]))
    .filter(Boolean)
  return { dossier, remboursements }
}
