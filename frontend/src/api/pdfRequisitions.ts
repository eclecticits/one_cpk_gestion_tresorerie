import { apiRequest } from '../lib/apiClient'

export interface PdfRequisitionItem {
  numero_requisition?: string
  montant?: string
  statut?: string
  rubrique?: string
  objet?: string
  raw_line: string
  match_status: 'found' | 'missing' | 'conflict' | 'unmatched'
  db_id?: string
  db_montant?: string
  db_status?: string
}

export interface PdfRequisitionParseResponse {
  items: PdfRequisitionItem[]
  raw_text_excerpt: string
  warnings: string[]
  total_items: number
  matched: number
  conflicts: number
  missing: number
}

export async function parseRequisitionPdf(file: File): Promise<PdfRequisitionParseResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiRequest('POST', '/requisitions/parse-pdf', form)
}

export interface PdfRequisitionImportItem {
  numero_requisition: string
  montant: string
  objet?: string
  rubrique?: string
}

export interface PdfRequisitionImportResponse {
  imported: number
  skipped_existing: number
  skipped_invalid: number
  created_ids: string[]
}

export async function importRequisitionsFromPdf(items: PdfRequisitionImportItem[]): Promise<PdfRequisitionImportResponse> {
  return apiRequest('POST', '/requisitions/import-pdf', { body: { items } })
}

export async function validateImportedRequisition(id: string) {
  return apiRequest('POST', `/requisitions/${id}/validate-import`)
}
