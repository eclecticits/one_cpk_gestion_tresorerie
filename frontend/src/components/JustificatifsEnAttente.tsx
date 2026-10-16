import { format } from 'date-fns'
import ResponsiveModal from './ResponsiveModal'
import { JustificatifBadge } from './JustificatifModal'
import { toNumber } from '../utils/amount'
import type { SortieFonds } from '../types'
import styles from './Justificatif.module.css'

interface Props {
  isOpen: boolean
  onClose: () => void
  sorties: SortieFonds[]
  chargement: boolean
  /** Ouvre la pièce d'une sortie, pour la joindre ou en dispenser. */
  onOuvrir: (sortie: SortieFonds) => void
}

/** Ce qui reste à justifier, les échéances les plus anciennes d'abord. */
export default function JustificatifsEnAttente({ isOpen, onClose, sorties, chargement, onOuvrir }: Props) {
  return (
    <ResponsiveModal isOpen={isOpen} onClose={onClose} title="Justificatifs en attente" size="lg">
      {chargement ? (
        <p className={styles.attenteVide}>Chargement…</p>
      ) : sorties.length === 0 ? (
        <p className={styles.attenteVide}>Aucun justificatif attendu.</p>
      ) : (
        <ul className={styles.attenteListe}>
          {sorties.map((s) => (
            <li key={s.id} className={styles.attenteItem}>
              <div className={styles.attenteInfo}>
                <strong>{s.beneficiaire || '—'}</strong>
                <span>
                  {toNumber(s.montant_paye).toFixed(2)} {(s as any).devise || 'USD'} · {s.motif}
                </span>
                <small>
                  {s.reference_numero || s.reference || '—'} · payée le{' '}
                  {s.date_paiement ? format(new Date(s.date_paiement), 'dd/MM/yyyy') : '—'}
                  {s.justificatif_echeance ? ` · à déposer avant le ${format(new Date(s.justificatif_echeance), "dd/MM 'à' HH'h'mm")}` : ''}
                  {(s.justificatif_nb_relances || 0) > 0 ? ` · relancé ${s.justificatif_nb_relances} fois` : ''}
                </small>
                <JustificatifBadge sortie={s} />
              </div>
              <button type="button" className={styles.btnPrimary} onClick={() => onOuvrir(s)}>
                Joindre
              </button>
            </li>
          ))}
        </ul>
      )}
    </ResponsiveModal>
  )
}
