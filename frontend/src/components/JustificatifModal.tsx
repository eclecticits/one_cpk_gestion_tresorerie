import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import ResponsiveModal from './ResponsiveModal'
import { useToast } from '../hooks/useToast'
import { deciderJustificatif, deposerJustificatif, relancerJustificatif, STATUT_JUSTIFICATIF_LABELS, type StatutJustificatif } from '../api/justificatifs'
import { buildUploadUrl, openUploadUrl } from '../utils/uploads'
import type { SortieFonds } from '../types'
import styles from './Justificatif.module.css'

const STATUT_CLASSE: Record<StatutJustificatif, string> = {
  NON_REQUIS: styles.badgeNeutre,
  ATTENDU: styles.badgeAttendu,
  EN_RETARD: styles.badgeRetard,
  RECU: styles.badgeRecu,
  DISPENSE: styles.badgeNeutre,
}

function dateHeure(value?: string | null): string {
  if (!value) return '—'
  try {
    return format(new Date(value), "dd/MM/yyyy 'à' HH'h'mm")
  } catch {
    return '—'
  }
}

/** Pastille d'état du justificatif ; rien quand aucun n'est demandé. */
export function JustificatifBadge({ sortie }: { sortie: SortieFonds }) {
  const statut = (sortie.justificatif_statut || 'NON_REQUIS') as StatutJustificatif
  if (statut === 'NON_REQUIS') return null
  const titre =
    statut === 'ATTENDU' || statut === 'EN_RETARD'
      ? `À déposer avant le ${dateHeure(sortie.justificatif_echeance)}`
      : statut === 'DISPENSE'
        ? sortie.justificatif_motif_dispense || undefined
        : `Reçu le ${dateHeure(sortie.justificatif_recu_le)}`
  return (
    <span className={`${styles.badge} ${STATUT_CLASSE[statut]}`} title={titre}>
      {STATUT_JUSTIFICATIF_LABELS[statut]}
    </span>
  )
}

/** Y a-t-il un justificatif à joindre, à voir ou dont la dispense se lit ? */
export function justificatifConsultable(sortie: SortieFonds): boolean {
  const statut = sortie.justificatif_statut || 'NON_REQUIS'
  return statut !== 'NON_REQUIS' || (sortie.justificatif_pieces || []).length > 0
}

/** La ligne attend-elle une action du caissier sur son justificatif ? */
export function justificatifAttendu(sortie: SortieFonds): boolean {
  return sortie.justificatif_statut === 'ATTENDU' || sortie.justificatif_statut === 'EN_RETARD'
}

interface Props {
  sortie: SortieFonds | null
  onClose: () => void
  onUpdated: (sortie: SortieFonds) => void
}

/**
 * Le caissier scanne la pièce rapportée et la joint à la ligne de sortie. Il
 * peut aussi dispenser (motif obligatoire) ou exiger après coup.
 */
export default function JustificatifModal({ sortie, onClose, onUpdated }: Props) {
  const { notifySuccess, notifyError } = useToast()
  const [fichiers, setFichiers] = useState<File[]>([])
  const [motif, setMotif] = useState('')
  const [modeDispense, setModeDispense] = useState(false)
  const [envoi, setEnvoi] = useState(false)

  useEffect(() => {
    setFichiers([])
    setMotif('')
    setModeDispense(false)
  }, [sortie?.id])

  if (!sortie) return null
  const statut = (sortie.justificatif_statut || 'NON_REQUIS') as StatutJustificatif
  const attendu = statut === 'ATTENDU' || statut === 'EN_RETARD'
  const pieces = sortie.justificatif_pieces || []

  const executer = async (action: () => Promise<SortieFonds>, message: string) => {
    setEnvoi(true)
    try {
      const maj = await action()
      notifySuccess('Justificatif', message)
      onUpdated(maj)
      onClose()
    } catch (err: any) {
      notifyError('Justificatif', err?.message || "L'opération n'a pas abouti.")
    } finally {
      setEnvoi(false)
    }
  }

  const footer = (
    <div className={styles.footerActions}>
      <button type="button" className={styles.btnSecondary} onClick={onClose} disabled={envoi}>
        Fermer
      </button>
      {modeDispense ? (
        <button
          type="button"
          className={styles.btnPrimary}
          disabled={envoi || !motif.trim()}
          onClick={() => executer(() => deciderJustificatif(sortie.id, 'dispenser', motif.trim()), 'Justificatif dispensé.')}
        >
          Confirmer la dispense
        </button>
      ) : (
        statut !== 'RECU' && (
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={envoi || fichiers.length === 0}
            onClick={() => executer(() => deposerJustificatif(sortie.id, fichiers), 'Justificatif joint à la sortie.')}
          >
            {envoi ? 'Envoi…' : 'Joindre le justificatif'}
          </button>
        )
      )}
    </div>
  )

  return (
    <ResponsiveModal isOpen={!!sortie} onClose={onClose} title="Pièce justificative" size="md" footer={footer}>
      <div className={styles.modalBody}>
        <div className={styles.recap}>
          <div><span>Sortie</span><strong>{sortie.reference_numero || sortie.reference || '—'}</strong></div>
          <div><span>Bénéficiaire</span><strong>{sortie.beneficiaire || '—'}</strong></div>
          <div><span>Payée le</span><strong>{dateHeure(sortie.date_paiement)}</strong></div>
          <div><span>État</span><strong><JustificatifBadge sortie={sortie} />{statut === 'NON_REQUIS' && 'Non requis'}</strong></div>
          {attendu && <div><span>À déposer avant le</span><strong>{dateHeure(sortie.justificatif_echeance)}</strong></div>}
          {attendu && (
            <div>
              <span>Relance automatique (J+7)</span>
              <strong>{sortie.justificatif_relance_le ? `Envoyée le ${dateHeure(sortie.justificatif_relance_le)}` : `Prévue le ${dateHeure(sortie.justificatif_relance_prevue_le)}`}</strong>
            </div>
          )}
          {(sortie.justificatif_nb_relances || 0) > 0 && (
            <div>
              <span>Relances envoyées</span>
              <strong>
                {sortie.justificatif_nb_relances} · dernière le {dateHeure(sortie.justificatif_derniere_relance_le)}
              </strong>
            </div>
          )}
          {statut === 'DISPENSE' && <div><span>Motif de dispense</span><strong>{sortie.justificatif_motif_dispense || '—'}</strong></div>}
        </div>

        {pieces.length > 0 && (
          <div className={styles.pieces}>
            <span className={styles.piecesTitre}>Pièces jointes</span>
            {pieces.map((p, i) => (
              <button
                key={p}
                type="button"
                className={styles.lienBtn}
                onClick={() =>
                  openUploadUrl(buildUploadUrl(p)).catch(() =>
                    notifyError('Justificatif', "Le fichier n'a pas pu être ouvert."),
                  )
                }
              >
                Justificatif {i + 1}
              </button>
            ))}
          </div>
        )}

        {modeDispense ? (
          <label className={styles.contactField}>
            <span>Motif de la dispense *</span>
            <textarea rows={3} value={motif} onChange={(e) => setMotif(e.target.value)} placeholder="Pourquoi aucune pièce ne sera rapportée" />
          </label>
        ) : (
          statut !== 'RECU' && (
            <label className={styles.contactField}>
              <span>Pièce scannée (PDF, JPG, PNG — 3 Mo max par fichier)</span>
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                multiple
                onChange={(e) => setFichiers(Array.from(e.target.files || []))}
              />
            </label>
          )
        )}

        <div className={styles.decisions}>
          {attendu && !modeDispense && (
            <button
              type="button"
              className={styles.btnSecondary}
              disabled={envoi}
              onClick={() =>
                executer(
                  () => relancerJustificatif(sortie.id),
                  'Relance envoyée au bénéficiaire, autorités en copie.',
                )
              }
              title="Renvoie le message au bénéficiaire, avec les autorités en copie"
            >
              Relancer maintenant
            </button>
          )}
          {attendu && !modeDispense && (
            <button type="button" className={styles.lienBtn} onClick={() => setModeDispense(true)} disabled={envoi}>
              Dispenser de justificatif…
            </button>
          )}
          {attendu && !modeDispense && (
            <button
              type="button"
              className={styles.lienBtn}
              disabled={envoi}
              onClick={() => executer(() => deciderJustificatif(sortie.id, 'ne_pas_exiger'), "Plus aucun justificatif n'est attendu.")}
            >
              Ne pas exiger (erreur de saisie)
            </button>
          )}
          {(statut === 'NON_REQUIS' || statut === 'DISPENSE') && (
            <button
              type="button"
              className={styles.lienBtn}
              disabled={envoi}
              onClick={() => executer(() => deciderJustificatif(sortie.id, 'exiger'), 'Justificatif exigé : 48 h à partir de maintenant.')}
            >
              Exiger un justificatif (48 h à partir de maintenant)
            </button>
          )}
          {modeDispense && (
            <button type="button" className={styles.lienBtn} onClick={() => setModeDispense(false)} disabled={envoi}>
              Annuler la dispense
            </button>
          )}
        </div>
      </div>
    </ResponsiveModal>
  )
}
