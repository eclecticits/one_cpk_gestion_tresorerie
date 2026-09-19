import { apiRequest } from '../lib/apiClient'
import { ModePaiement, Money } from '../types'

export type CanalPaiement = 'CAISSE' | 'BANQUE'

export interface PaymentHistoryItem {
  id: string
  encaissement_id: string
  montant: Money
  mode_paiement: ModePaiement
  // Destination de CE versement : un acompte peut entrer en caisse et le solde
  // arriver par virement, la note ne les résume pas.
  canal?: CanalPaiement
  compte_bancaire_id?: number | null
  devise?: 'USD' | 'CDF'
  reference?: string
  notes?: string
  created_by?: string
  created_at: string
}

export interface CreatePaymentRequest {
  encaissement_id: string
  montant: number
  mode_paiement: ModePaiement
  // Vides = la destination de la note, comme avant le règlement mixte.
  canal?: CanalPaiement
  compte_bancaire_id?: number
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
