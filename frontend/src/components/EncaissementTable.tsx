import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { format } from 'date-fns'
import { MoreVertical, Wallet, Printer, Ban, Eye } from 'lucide-react'
import { Encaissement } from '../types'
import { toNumber } from '../utils/amount'
import { getTypeClientLabel } from '../utils/encaissementHelpers'
import styles from '../pages/Encaissements.module.css'

interface EncaissementTableProps {
  encaissements: Encaissement[]
  hasActiveFilters: boolean
  formatCurrency: (amount: string | number | null | undefined) => string
  onManagePayment: (enc: Encaissement) => void
  onPrintReceipt: (enc: Encaissement) => void
  onCancelOperation: (enc: Encaissement) => void
  canCancelOperation: boolean
}

export default function EncaissementTable({
  encaissements,
  hasActiveFilters,
  formatCurrency,
  onManagePayment,
  onPrintReceipt,
  onCancelOperation,
  canCancelOperation,
}: EncaissementTableProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; openUp: boolean } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (openMenuId === null) return
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenMenuId(null)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [openMenuId])

  const toggleMenu = (encId: string, e: React.MouseEvent<HTMLButtonElement>) => {
    if (openMenuId === encId) {
      setOpenMenuId(null)
      return
    }
    const rect = e.currentTarget.getBoundingClientRect()
    const menuHeight = 150
    const openUp = window.innerHeight - rect.bottom < menuHeight
    setMenuPos({
      top: openUp ? rect.top - 4 : rect.bottom + 4,
      left: Math.max(8, rect.right - 210),
      openUp,
    })
    setOpenMenuId(encId)
  }

  return (
    <>
      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>N° Note de débit</th>
              <th>Date</th>
              <th>Type client</th>
              <th>Client</th>
              <th>Poste budgétaire</th>
              <th>Libellé</th>
              <th>Description</th>
              <th>Montant total</th>
              <th>Payé</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {encaissements.length === 0 ? (
              <tr>
                <td colSpan={11} style={{ textAlign: 'center', padding: '30px', color: '#9ca3af' }}>
                  {hasActiveFilters ? 'Aucun encaissement trouvé avec ces filtres' : 'Aucun encaissement enregistré'}
                </td>
              </tr>
            ) : (
              encaissements.map((enc) => (
                <tr key={enc.id} className={enc.is_deleted ? styles.deletedRow : undefined}>
                  <td>
                    <strong>{enc.numero_recu || '—'}</strong>
                  </td>
                  <td>{format(new Date(enc.date_encaissement), 'dd/MM/yyyy')}</td>
                  <td>
                    <span
                      className={styles.badge}
                      style={{
                        background:
                          enc.type_client === 'expert_comptable'
                            ? '#dbeafe'
                            : enc.type_client === 'banque_institution'
                            ? '#d1fae5'
                            : enc.type_client === 'partenaire'
                            ? '#fef3c7'
                            : '#f3f4f6',
                        color:
                          enc.type_client === 'expert_comptable'
                            ? '#1e40af'
                            : enc.type_client === 'banque_institution'
                            ? '#065f46'
                            : enc.type_client === 'partenaire'
                            ? '#92400e'
                            : '#374151',
                      }}
                    >
                      {getTypeClientLabel(enc.type_client)}
                    </span>
                  </td>
                  <td>
                    {enc.expert_comptable ? (
                      <div className={styles.ecInfo}>
                        <div className={styles.ecNumero}>{enc.expert_comptable.numero_ordre}</div>
                        <div className={styles.ecNom}>{enc.expert_comptable.nom_denomination}</div>
                      </div>
                    ) : (
                      <div className={styles.ecNom}>{enc.client_nom}</div>
                    )}
                  </td>
                  <td>
                    <span className={styles.badge}>
                      {enc.budget_poste_code
                        ? `${enc.budget_poste_code} ${enc.budget_poste_libelle ? `- ${enc.budget_poste_libelle}` : ''}`.trim()
                        : '—'}
                    </span>
                  </td>
                  <td>{enc.libelle || '—'}</td>
                  <td>{enc.description}</td>
                  <td>
                    <strong>{formatCurrency(enc.montant_total || enc.montant || 0)}</strong>
                    {enc.devise_perception === 'CDF' && (
                      <div className={styles.inlineNote}>
                        Perçu: {formatCurrency(enc.montant_percu)} CDF
                      </div>
                    )}
                  </td>
                  <td>
                    <div>
                      <div style={{ fontWeight: 600, color: '#16a34a' }}>{formatCurrency(enc.montant_paye || 0)}</div>
                      {enc.statut_paiement === 'partiel' && (
                        <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '2px' }}>
                          Reste:{' '}
                          {formatCurrency(
                            toNumber(enc.montant_total || enc.montant || 0) - toNumber(enc.montant_paye || 0)
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    {enc.is_deleted ? (
                      <span className={styles.deletedBadge} title="Encaissement supprimé logiquement">Supprimé</span>
                    ) : (enc.statut_operation || 'ACTIVE') === 'ANNULEE' ? (
                      <span className={styles.cancelledBadge} title={enc.motif_annulation || undefined}>Annulé</span>
                    ) : (
                      <span className={styles.statutBadge} data-statut={enc.statut_paiement || 'complet'}>
                        {enc.statut_paiement === 'non_paye'
                          ? 'Non payé'
                          : enc.statut_paiement === 'partiel'
                          ? 'Partiel'
                          : enc.statut_paiement === 'avance'
                          ? 'Avance'
                          : 'Payé'}
                      </span>
                    )}
                  </td>
                  <td className={styles.actionsCell}>
                    {!enc.is_deleted &&
                      (enc.statut_operation || 'ACTIVE') !== 'ANNULEE' &&
                      (enc.statut_paiement === 'partiel' || enc.statut_paiement === 'non_paye') && (
                        <button
                          type="button"
                          className={styles.completeBtn}
                          onClick={() => onManagePayment(enc)}
                          title="Compléter le paiement (encaisser le solde restant)"
                        >
                          <Wallet size={14} />
                          <span>Compléter</span>
                        </button>
                      )}
                    <button
                      type="button"
                      className={styles.actionsTrigger}
                      onClick={(e) => toggleMenu(enc.id, e)}
                      title="Actions"
                      aria-label="Actions"
                      aria-haspopup="menu"
                      aria-expanded={openMenuId === enc.id}
                    >
                      <MoreVertical size={16} />
                    </button>
                    {openMenuId === enc.id && menuPos && createPortal(
                      <div
                        ref={menuRef}
                        className={`${styles.actionsMenu} ${menuPos.openUp ? styles.actionsMenuUp : ''}`}
                        role="menu"
                        style={{ top: menuPos.top, left: menuPos.left }}
                      >
                        {!enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE' && (
                          <button
                            type="button"
                            role="menuitem"
                            className={styles.actionsMenuItem}
                            onClick={() => { setOpenMenuId(null); onManagePayment(enc) }}
                          >
                            <Wallet size={15} />
                            <span>
                              {enc.statut_paiement === 'non_paye' || enc.statut_paiement === 'partiel'
                                ? 'Compléter le paiement'
                                : 'Gérer les paiements'}
                            </span>
                          </button>
                        )}
                        <button
                          type="button"
                          role="menuitem"
                          className={styles.actionsMenuItem}
                          onClick={() => { setOpenMenuId(null); onPrintReceipt(enc) }}
                        >
                          <Printer size={15} />
                          <span>Imprimer la note de débit</span>
                        </button>
                        {canCancelOperation && !enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE' && (
                          <button
                            type="button"
                            role="menuitem"
                            className={`${styles.actionsMenuItem} ${styles.actionsMenuItemDanger}`}
                            onClick={() => { setOpenMenuId(null); onCancelOperation(enc) }}
                          >
                            <Ban size={15} />
                            <span>Annuler l'opération</span>
                          </button>
                        )}
                      </div>,
                      document.body
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.mobileCards}>
        {encaissements.length === 0 ? (
          <div className={styles.emptyCards}>
            {hasActiveFilters ? 'Aucun encaissement trouvé avec ces filtres' : 'Aucun encaissement enregistré'}
          </div>
        ) : (
          encaissements.map((enc) => (
            <div
              key={`card-${enc.id}`}
              className={`${styles.card} ${enc.is_deleted ? styles.deletedCard : ''}`}
              data-statut={enc.is_deleted ? 'supprime' : (enc.statut_operation || 'ACTIVE') === 'ANNULEE' ? 'annulee' : (enc.statut_paiement || 'complet')}
              role="button"
              tabIndex={0}
              onClick={() => {
                if (!enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE') {
                  onManagePayment(enc)
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  if (!enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE') {
                    onManagePayment(enc)
                  }
                }
              }}
            >
              <div className={styles.cardHeader}>
                <div>
                  <div className={styles.cardTitle}>{enc.numero_recu || '—'}</div>
                  <div className={styles.cardSub}>{format(new Date(enc.date_encaissement), 'dd/MM/yyyy')}</div>
                </div>
                <div className={styles.cardHeaderActions}>
                  {enc.is_deleted ? (
                    <span className={styles.deletedBadge}>Supprimé</span>
                  ) : (enc.statut_operation || 'ACTIVE') === 'ANNULEE' ? (
                    <span className={styles.cancelledBadge}>Annulé</span>
                  ) : (
                    <>
                      <span className={styles.statutBadge} data-statut={enc.statut_paiement || 'complet'}>
                        {enc.statut_paiement === 'non_paye'
                          ? 'Non payé'
                          : enc.statut_paiement === 'partiel'
                          ? 'Partiel'
                          : enc.statut_paiement === 'avance'
                          ? 'Avance'
                          : 'Payé'}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          onManagePayment(enc)
                        }}
                        className={styles.cardIconBtn}
                        title="Voir détails"
                      >
                        <Eye size={16} />
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className={styles.cardBody}>
                <div className={styles.cardAmountMain}>
                  {formatCurrency(enc.montant_total || enc.montant || 0)}
                </div>
                <div className={styles.cardGrid}>
                  <div>
                    <div className={styles.cardLabel}>Client</div>
                    <div className={styles.cardValue}>
                      {enc.expert_comptable
                        ? `${enc.expert_comptable.nom_denomination} (${enc.expert_comptable.numero_ordre})`
                        : enc.client_nom || 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Type</div>
                    <div className={styles.cardValue}>{getTypeClientLabel(enc.type_client)}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Poste budgétaire</div>
                    <div className={styles.cardValue}>
                      {enc.budget_poste_code
                        ? `${enc.budget_poste_code} ${enc.budget_poste_libelle ? `- ${enc.budget_poste_libelle}` : ''}`.trim()
                        : '—'}
                    </div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Libellé</div>
                    <div className={styles.cardValue}>{enc.libelle || '—'}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Payé</div>
                    <div className={styles.cardValueStrong}>
                      {formatCurrency(enc.montant_paye || 0)}
                    </div>
                  </div>
                </div>
                {enc.devise_perception === 'CDF' && (
                  <div className={styles.cardNote}>
                    Perçu: {formatCurrency(enc.montant_percu)} CDF
                  </div>
                )}
                {enc.statut_paiement === 'partiel' && (
                  <div className={styles.cardNoteWarn}>
                    Reste: {formatCurrency(toNumber(enc.montant_total || enc.montant || 0) - toNumber(enc.montant_paye || 0))}
                  </div>
                )}
                {(enc.statut_operation || 'ACTIVE') === 'ANNULEE' && enc.motif_annulation && (
                  <div className={styles.cardNote}>
                    Motif d'annulation: {enc.motif_annulation}
                  </div>
                )}
                {enc.description && (
                  <div className={styles.cardNote}>
                    {enc.description}
                  </div>
                )}
              </div>

              <div className={styles.cardActions}>
                {!enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onManagePayment(enc)
                    }}
                    className={styles.paymentBtn}
                    title="Gérer les paiements"
                  >
                    <Wallet size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Paiements
                  </button>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onPrintReceipt(enc)
                  }}
                  className={styles.printBtn}
                  title={(enc.statut_operation || 'ACTIVE') === 'ANNULEE' ? 'Imprimer la note de débit annulée' : 'Imprimer la note de débit'}
                >
                  <Printer size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Imprimer
                </button>
                {canCancelOperation && !enc.is_deleted && (enc.statut_operation || 'ACTIVE') !== 'ANNULEE' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onCancelOperation(enc)
                    }}
                    className={styles.deleteBtn}
                    title="Annuler l'opération"
                  >
                    <Ban size={15} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />Annuler
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </>
  )
}
