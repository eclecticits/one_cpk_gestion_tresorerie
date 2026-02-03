import { apiRequest } from '../lib/apiClient'
import { ModePatement } from '../types'

export interface PaymentHistoryItem {
  id: string
  encaissement_id: string
  montant: number
  mode_paiement: ModePatement
  reference?: string
  notes?: string
  created_by?: string
  created_at: string
}

export interface CreatePaymentRequest {
  encaissement_id: string
  montant: number
  mode_paiement: ModePatement
  reference?: string
  notes?: string
}

// Liste des paiements pour un encaissement
export async function getPaymentHistory(encaissementId: string): Promise<PaymentHistoryItem[]> {
  return apiRequest<PaymentHistoryItem[]>('GET', `/payment-history?encaissement_id=${encaissementId}`)
}

// Ajouter un paiement
export async function createPayment(data: CreatePaymentRequest): Promise<PaymentHistoryItem> {
  return apiRequest<PaymentHistoryItem>('POST', '/payment-history', data)
}
