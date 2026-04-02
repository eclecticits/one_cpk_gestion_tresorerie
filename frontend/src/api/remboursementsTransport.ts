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
