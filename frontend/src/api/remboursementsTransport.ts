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
