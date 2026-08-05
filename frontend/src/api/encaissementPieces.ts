import { apiRequest } from '../lib/apiClient'

export interface EncaissementPieceJointe {
  id: string
  original_name: string
  mime_type: string
  size_bytes: number
  uploaded_by?: string | null
  uploaded_at: string
  path: string
}

export function uploadEncaissementPiece(encaissementId: string, file: File): Promise<EncaissementPieceJointe> {
  const body = new FormData()
  body.append('file', file, file.name)
  return apiRequest<EncaissementPieceJointe>('POST', `/encaissements/${encaissementId}/pieces-justificatives`, { body })
}

export function listEncaissementPieces(encaissementId: string): Promise<EncaissementPieceJointe[]> {
  return apiRequest<EncaissementPieceJointe[]>('GET', `/encaissements/${encaissementId}/pieces-justificatives`)
}
