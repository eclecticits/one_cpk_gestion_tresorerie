import { useState } from 'react'
import { AlertTriangle, Landmark, X } from 'lucide-react'
import { apiRequest, ApiError } from '../lib/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import type { CompteBancaire } from '../types/banque'
import styles from './ReimputationBudgetaire.module.css'

interface Props {
  requisitionId: string
  /** Statut de la réquisition : le canal ne change plus une fois le paiement engagé. */
  statut: string
  modeActuel: string
  compteActuelId: number | null
  comptesBancaires: CompteBancaire[]
  onChange?: (canal: { mode_paiement: string; compte_bancaire_id: number | null }) => void
}

// L'argent est sorti, ou sort : le canal est celui par lequel il est passé.
const STATUTS_FIGES = new Set(['PAYEE', 'EN_DECAISSEMENT', 'REJETEE', 'ANNULEE'])

/**
 * Changement du canal de paiement (caisse ou banque, et le compte) d'une
 * réquisition déjà examinée ou validée, tant qu'elle n'est pas payée. La pièce
 * et toutes ses lignes passent sur le canal choisi ; le serveur refuse dès
 * qu'une sortie de fonds ou un ordre de décaissement existe.
 */
export default function ChangementCanalPaiement({
  requisitionId,
  statut,
  modeActuel,
  compteActuelId,
  comptesBancaires,
  onChange,
}: Props) {
  const { hasPermission } = usePermissions()
  const { showSuccess } = useNotification()
  const [ouvert, setOuvert] = useState(false)
  const [mode, setMode] = useState<'cash' | 'virement'>('cash')
  const [compteId, setCompteId] = useState('')
  const [motif, setMotif] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  if (!hasPermission('treso.requisitions.changer_canal')) return null
  if (STATUTS_FIGES.has(String(statut || '').toUpperCase())) return null

  const ouvrir = () => {
    const banque = modeActuel === 'virement'
    setMode(banque ? 'virement' : 'cash')
    setCompteId(banque && compteActuelId ? String(compteActuelId) : '')
    setMotif('')
    setErreur(null)
    setOuvert(true)
  }

  const inchange =
    mode === modeActuel &&
    (mode === 'cash' || String(compteActuelId ?? '') === compteId)
  const incomplet = motif.trim().length < 3 || (mode === 'virement' && !compteId)
  const interdit = enCours || incomplet || inchange

  const valider = async () => {
    if (interdit) return
    setEnCours(true)
    setErreur(null)
    try {
      const res = await apiRequest<{ mode_paiement: string; compte_bancaire_id: number | null }>('POST', `/requisitions/${requisitionId}/canal-paiement`, {
        mode_paiement: mode,
        compte_bancaire_id: mode === 'virement' ? Number(compteId) : null,
        motif: motif.trim(),
      })
      const compte = comptesBancaires.find((c) => String(c.id) === compteId)
      showSuccess(
        'Canal de paiement modifié',
        mode === 'cash'
          ? 'La réquisition sera payée par la caisse.'
          : `La réquisition sera payée par la banque${compte ? ` : ${compte.banque?.nom || 'Banque'} - ${compte.intitule}` : ''}.`,
      )
      setOuvert(false)
      onChange?.({ mode_paiement: res.mode_paiement, compte_bancaire_id: res.compte_bancaire_id })
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Le changement de canal a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <>
      <button
        type="button"
        className={styles.declencheur}
        onClick={ouvrir}
        title="Changer le canal de paiement de cette réquisition (avant paiement)"
      >
        <Landmark size={15} aria-hidden="true" />
        Changer le canal de paiement
      </button>

      {ouvert && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="canal-titre"
          className={styles.overlay}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOuvert(false) }}
        >
          <div className={styles.modal}>
            <div className={styles.header}>
              <div>
                <h2 id="canal-titre" className={styles.title}>Changer le canal de paiement</h2>
                <p className={styles.subtitle}>
                  La réquisition et toutes ses lignes passent sur le canal choisi. Impossible une fois le paiement engagé.
                </p>
              </div>
              <button type="button" onClick={() => setOuvert(false)} aria-label="Fermer" className={styles.close}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className={styles.body}>
              <div className={styles.champ}>
                <label className={styles.label} htmlFor="canal-mode">Mode de paiement</label>
                <select
                  id="canal-mode"
                  className={styles.select}
                  value={mode}
                  onChange={(e) => { setMode(e.target.value as 'cash' | 'virement'); setErreur(null) }}
                >
                  <option value="cash">Caisse</option>
                  <option value="virement">Banque</option>
                </select>
              </div>

              {mode === 'virement' && (
                <div className={styles.champ}>
                  <label className={styles.label} htmlFor="canal-compte">Compte bancaire</label>
                  <select
                    id="canal-compte"
                    className={styles.select}
                    value={compteId}
                    onChange={(e) => { setCompteId(e.target.value); setErreur(null) }}
                  >
                    <option value="">Sélectionner un compte bancaire</option>
                    {comptesBancaires.map((compte) => (
                      <option key={compte.id} value={compte.id}>
                        {(compte.banque?.nom || 'Banque')} - {compte.intitule} ({compte.devise})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="canal-motif">Motif du changement</label>
                <textarea
                  id="canal-motif"
                  className={styles.textarea}
                  value={motif}
                  onChange={(e) => setMotif(e.target.value)}
                  rows={3}
                  maxLength={500}
                  placeholder="Pourquoi la réquisition doit être payée autrement"
                />
                <p className={styles.aide}>Ce motif est consigné au journal avec l'ancien et le nouveau canal.</p>
              </div>

              {inchange && (
                <p className={styles.aide}>C'est déjà le canal de cette réquisition.</p>
              )}

              {erreur && (
                <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
                  <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
                  <span>{erreur}</span>
                </div>
              )}
            </div>

            <div className={styles.footer}>
              <button type="button" onClick={() => setOuvert(false)} className={`${styles.bouton} ${styles.secondaire}`}>
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void valider()}
                disabled={interdit}
                className={`${styles.bouton} ${styles.principal}`}
              >
                {enCours ? 'Modification…' : 'Changer le canal'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
