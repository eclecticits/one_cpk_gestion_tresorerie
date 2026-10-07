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
