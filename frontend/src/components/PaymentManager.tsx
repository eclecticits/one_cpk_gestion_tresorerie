import { useState, useEffect } from 'react'
import { getPaymentHistory, createPayment, PaymentHistoryItem } from '../api/payments'
import { Encaissement, ModePatement } from '../types'
import { format } from 'date-fns'
import { formatAmount, toNumber } from '../utils/amount'
import styles from './PaymentManager.module.css'
import { useToast } from '../hooks/useToast'

interface PaymentManagerProps {
  encaissement: Encaissement
  onClose: () => void
  onUpdate: () => void
}

export default function PaymentManager({ encaissement, onClose, onUpdate }: PaymentManagerProps) {
  const { notifyError, notifyWarning, notifySuccess } = useToast()
  const [history, setHistory] = useState<PaymentHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddPayment, setShowAddPayment] = useState(false)
  const [paymentData, setPaymentData] = useState({
    montant: '',
    mode_paiement: 'cash' as ModePatement,
    reference: '',
    notes: '',
  })

  useEffect(() => {
    loadHistory()
  }, [encaissement.id])

  const loadHistory = async () => {
    try {
      const data = await getPaymentHistory(encaissement.id)
      setHistory(data)
    } catch (error) {
      console.error('Error loading payment history:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleAddPayment = async (e: React.FormEvent) => {
    e.preventDefault()

    const montant = parseFloat(paymentData.montant)
    if (isNaN(montant) || montant <= 0) {
      notifyWarning('Montant invalide', 'Veuillez saisir un montant supérieur à 0.')
      return
    }

    try {
      await createPayment({
        encaissement_id: encaissement.id,
        montant,
        mode_paiement: paymentData.mode_paiement,
        reference: paymentData.reference || undefined,
        notes: paymentData.notes || undefined,
      })

      setPaymentData({
        montant: '',
        mode_paiement: 'cash',
        reference: '',
        notes: '',
      })
      setShowAddPayment(false)
      await loadHistory()
      onUpdate()
      notifySuccess('Paiement ajouté', 'Le paiement a été enregistré.')
    } catch (error: any) {
      console.error('Error adding payment:', error)
      notifyError('Erreur', error.message || 'Impossible d’ajouter le paiement.')
    }
  }

  const formatCurrency = (amount: string | number | null | undefined) => {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: 'USD',
    }).format(toNumber(amount))
  }

  const getStatutLabel = () => {
    switch (encaissement.statut_paiement) {
      case 'non_paye':
        return { text: 'Non payé', color: '#dc2626' }
      case 'partiel':
        return { text: 'Partiellement payé', color: '#f59e0b' }
      case 'complet':
        return { text: 'Payé', color: '#16a34a' }
      case 'avance':
        return { text: 'Paiement en avance', color: '#2563eb' }
      default:
        return { text: 'Inconnu', color: '#6b7280' }
    }
  }

  const montantTotal = toNumber(encaissement.montant_total)
  const montantPaye = toNumber(encaissement.montant_paye)
  const montantRestant = montantTotal - montantPaye

  const statut = getStatutLabel()

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <h2>Gestion des paiements</h2>
          <button onClick={onClose} className={styles.closeBtn}>×</button>
        </div>

        <div className={styles.encaissementInfo}>
          <div className={styles.infoRow}>
            <span className={styles.label}>N° Reçu:</span>
            <span className={styles.value}>{encaissement.numero_recu}</span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.label}>Client:</span>
            <span className={styles.value}>
              {encaissement.expert_comptable?.nom_denomination || encaissement.client_nom}
            </span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.label}>Description:</span>
            <span className={styles.value}>{encaissement.description}</span>
          </div>
        </div>

        <div className={styles.paymentSummary}>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Montant total</div>
            <div className={styles.summaryValue}>{formatCurrency(montantTotal)}</div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Montant payé</div>
            <div className={styles.summaryValue} style={{ color: '#16a34a' }}>
              {formatCurrency(montantPaye)}
            </div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Restant</div>
            <div className={styles.summaryValue} style={{ color: montantRestant > 0 ? '#dc2626' : '#16a34a' }}>
              {formatCurrency(montantRestant)}
            </div>
          </div>
          <div className={styles.summaryCard}>
            <div className={styles.summaryLabel}>Statut</div>
            <div className={styles.summaryValue} style={{ color: statut.color }}>
              {statut.text}
            </div>
          </div>
        </div>

        {montantRestant > 0 && !showAddPayment && (
          <div style={{marginBottom: '20px'}}>
            <button
              onClick={() => setShowAddPayment(true)}
              className={styles.primaryBtn}
              style={{
                width: '100%',
                padding: '14px',
                fontSize: '16px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '10px'
              }}
            >
              <span style={{fontSize: '20px'}}>
                {history.length === 0 ? '💰' : '➕'}
              </span>
              {history.length === 0 ? 'Enregistrer le premier paiement' : 'Ajouter un paiement supplémentaire'}
            </button>
            {history.length === 0 && (
              <div style={{
                marginTop: '8px',
                padding: '8px 12px',
                background: '#fef3c7',
                borderRadius: '6px',
                fontSize: '13px',
                color: '#92400e',
                textAlign: 'center'
              }}>
                Ce reçu n'a pas encore été payé. Montant à encaisser : <strong>{formatCurrency(montantRestant)}</strong>
              </div>
            )}
          </div>
        )}

        {showAddPayment && (
          <div className={styles.addPaymentForm}>
            <div style={{
              background: history.length === 0 ? 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)' : 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
              padding: '16px',
              borderRadius: '8px',
              marginBottom: '20px',
              border: history.length === 0 ? '2px solid #3b82f6' : '2px solid #f59e0b',
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                marginBottom: '8px'
              }}>
                <span style={{fontSize: '24px'}}>
                  {history.length === 0 ? '💳' : '➕'}
                </span>
                <h3 style={{
                  margin: 0,
                  color: history.length === 0 ? '#1e40af' : '#92400e',
                  fontSize: '18px',
                  fontWeight: 700
                }}>
                  {history.length === 0 ? 'Premier encaissement' : 'Paiement supplémentaire'}
                </h3>
              </div>
              <p style={{
                margin: '0',
                fontSize: '14px',
                color: history.length === 0 ? '#1e3a8a' : '#78350f',
                lineHeight: '1.5'
              }}>
                {history.length === 0
                  ? `Enregistrez le premier paiement pour ce reçu. Montant à encaisser : ${formatCurrency(montantRestant)}`
                  : `Ajoutez un paiement complémentaire. Montant restant à encaisser : ${formatCurrency(montantRestant)}`
                }
              </p>
            </div>
            <form onSubmit={handleAddPayment}>
              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Montant (USD) *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={paymentData.montant}
                    onChange={(e) => setPaymentData({ ...paymentData, montant: e.target.value })}
                    placeholder={`Montant à encaisser (max: ${formatAmount(montantRestant)})`}
                    max={montantRestant}
                    required
                  />
                  <div style={{
                    fontSize: '12px',
                    color: '#6b7280',
                    marginTop: '4px'
                  }}>
                    {montantRestant === montantTotal
                      ? `Montant total du reçu : ${formatCurrency(montantTotal)}`
                      : `Reste à payer : ${formatCurrency(montantRestant)} sur ${formatCurrency(montantTotal)}`
                    }
                  </div>
                </div>
                <div className={styles.field}>
                  <label>Mode de paiement *</label>
                  <select
                    value={paymentData.mode_paiement}
                    onChange={(e) => setPaymentData({ ...paymentData, mode_paiement: e.target.value as ModePatement })}
                    required
                  >
                    <option value="cash">Cash (espèces)</option>
                    <option value="mobile_money">Mobile Money (Airtel, Orange, Vodacom...)</option>
                    <option value="virement">Opération bancaire</option>
                  </select>
                </div>
              </div>

              {(paymentData.mode_paiement === 'mobile_money' || paymentData.mode_paiement === 'virement') && (
                <div className={styles.field}>
                  <label>Référence</label>
                  <input
                    type="text"
                    value={paymentData.reference}
                    onChange={(e) => setPaymentData({ ...paymentData, reference: e.target.value })}
                    placeholder="Numéro de transaction"
                  />
                </div>
              )}

              <div className={styles.field}>
                <label>Notes (optionnel)</label>
                <textarea
                  value={paymentData.notes}
                  onChange={(e) => setPaymentData({ ...paymentData, notes: e.target.value })}
                  rows={3}
                  placeholder="Ajoutez des notes sur ce paiement (ex: payé par M. Dupont, reçu complet, etc.)"
                />
              </div>

              <div className={styles.formActions}>
                <button
                  type="button"
                  onClick={() => {
                    setShowAddPayment(false)
                    setPaymentData({
                      montant: '',
                      mode_paiement: 'cash',
                      reference: '',
                      notes: ''
                    })
                  }}
                  className={styles.secondaryBtn}
                >
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <span>✓</span>
                  {history.length === 0 ? 'Enregistrer le premier paiement' : 'Enregistrer ce paiement'}
                </button>
              </div>
            </form>
          </div>
        )}

        <div className={styles.historySection}>
          <h3>Historique des paiements</h3>
          {loading ? (
            <div style={{padding: '20px', textAlign: 'center', color: '#6b7280'}}>
              Chargement de l'historique...
            </div>
          ) : history.length === 0 ? (
            <div style={{
              padding: '32px 20px',
              textAlign: 'center',
              background: '#f9fafb',
              borderRadius: '8px',
              border: '2px dashed #d1d5db'
            }}>
              <div style={{fontSize: '48px', marginBottom: '12px'}}>📭</div>
              <div style={{fontSize: '16px', fontWeight: 600, color: '#374151', marginBottom: '6px'}}>
                Aucun paiement enregistré
              </div>
              <div style={{fontSize: '14px', color: '#6b7280'}}>
                Ce reçu n'a pas encore reçu de paiement
              </div>
            </div>
          ) : (
            <div className={styles.historyList}>
              {history.map((payment) => (
                <div key={payment.id} className={styles.historyItem}>
                  <div className={styles.historyHeader}>
                    <span className={styles.historyAmount}>{formatCurrency(payment.montant)}</span>
                    <span className={styles.historyDate}>
                      {format(new Date(payment.created_at), 'dd/MM/yyyy HH:mm')}
                    </span>
                  </div>
                  <div className={styles.historyDetails}>
                    <span className={styles.historyMode}>
                      {payment.mode_paiement === 'cash' ? 'Cash' :
                       payment.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement'}
                    </span>
                    {payment.reference && (
                      <span className={styles.historyRef}>Réf: {payment.reference}</span>
                    )}
                  </div>
                  {payment.notes && (
                    <div className={styles.historyNotes}>{payment.notes}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
