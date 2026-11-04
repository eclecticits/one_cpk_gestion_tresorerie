import { useMemo, useState } from 'react'
import { AlertTriangle, ArrowRightLeft, X } from 'lucide-react'
import { apiRequest, ApiError } from '../lib/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import type { CompteBancaire } from '../types/banque'
import type { LigneRequisition } from '../types'
import styles from './ReimputationBudgetaire.module.css'

interface Props {
  requisitionId: string
  statut: string
  lignes: LigneRequisition[]
  comptesBancaires: CompteBancaire[]
  onChange?: () => void
}

// Une pièce payée a payé par ses comptes ; une pièce close n'en a plus.
const STATUTS_FIGES = new Set(['PAYEE', 'REJETEE', 'ANNULEE'])

interface VoletBanque {
  compteId: number
  montant: number
  lignes: number
}

/**
 * Change le compte d'un volet bancaire (ex. TMB -> Equity) sans toucher au mode
 * ni aux autres volets. Contrairement au changement de canal, c'est permis en
 * décaissement : la caisse a pu payer sa part pendant que le virement attend.
 * Le serveur refuse si un ordre ou une sortie existe déjà sur l'ancien compte.
 */
export default function ChangementCompteVolet({ requisitionId, statut, lignes, comptesBancaires, onChange }: Props) {
  const { hasPermission } = usePermissions()
  const { showSuccess } = useNotification()
  const [ouvert, setOuvert] = useState(false)
  const [ancienId, setAncienId] = useState('')
  const [nouveauId, setNouveauId] = useState('')
  const [motif, setMotif] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const volets = useMemo<VoletBanque[]>(() => {
    const map = new Map<number, VoletBanque>()
    for (const l of lignes || []) {
      const mode = String(l.mode_paiement || '').toLowerCase()
      if (!mode || mode === 'cash' || l.compte_bancaire_id == null) continue
      const id = Number(l.compte_bancaire_id)
      const v = map.get(id) || { compteId: id, montant: 0, lignes: 0 }
      v.montant += Number(l.montant_total || 0)
      v.lignes += 1
      map.set(id, v)
    }
    return Array.from(map.values())
  }, [lignes])

  if (!hasPermission('treso.requisitions.changer_canal')) return null
  if (STATUTS_FIGES.has(String(statut || '').toUpperCase())) return null
  if (volets.length === 0) return null

  const nomCompte = (id: number | string) => {
    const c = comptesBancaires.find((x) => String(x.id) === String(id))
    return c ? `${c.banque?.nom || 'Banque'} - ${c.intitule} (${c.devise})` : `Compte #${id}`
  }
  const montant = (n: number) => n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const ouvrir = () => {
    setAncienId(volets.length === 1 ? String(volets[0].compteId) : '')
    setNouveauId('')
    setMotif('')
    setErreur(null)
    setOuvert(true)
  }

  const interdit = enCours || !ancienId || !nouveauId || ancienId === nouveauId || motif.trim().length < 3

  const valider = async () => {
    if (interdit) return
    setEnCours(true)
    setErreur(null)
    try {
      await apiRequest('POST', `/requisitions/${requisitionId}/compte-volet`, {
        ancien_compte_id: Number(ancienId),
        nouveau_compte_id: Number(nouveauId),
        motif: motif.trim(),
      })
      showSuccess('Compte modifié', `Le volet sera payé depuis ${nomCompte(nouveauId)}.`)
      setOuvert(false)
      onChange?.()
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Le changement de compte a échoué.')
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
        title="Changer le compte bancaire d'un volet qui n'a encore rien décaissé"
      >
        <ArrowRightLeft size={15} aria-hidden="true" />
        Changer le compte bancaire
      </button>

      {ouvert && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="compte-volet-titre"
          className={styles.overlay}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOuvert(false) }}
        >
          <div className={styles.modal}>
            <div className={styles.header}>
              <div>
                <h2 id="compte-volet-titre" className={styles.title}>Changer le compte bancaire</h2>
                <p className={styles.subtitle}>
                  Seul le compte du volet change ; le mode et les autres volets restent tels quels.
                  Impossible si un ordre ou une sortie existe déjà sur l'ancien compte.
                </p>
              </div>
              <button type="button" onClick={() => setOuvert(false)} aria-label="Fermer" className={styles.close}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className={styles.body}>
              <div className={styles.champ}>
                <label className={styles.label} htmlFor="compte-volet-ancien">Volet à modifier</label>
                <select
                  id="compte-volet-ancien"
                  className={styles.select}
                  value={ancienId}
                  onChange={(e) => { setAncienId(e.target.value); setErreur(null) }}
                >
                  {volets.length > 1 && <option value="">Sélectionner un volet</option>}
                  {volets.map((v) => (
                    <option key={v.compteId} value={v.compteId}>
                      {nomCompte(v.compteId)} : {montant(v.montant)} ({v.lignes} ligne{v.lignes > 1 ? 's' : ''})
                    </option>
                  ))}
                </select>
              </div>

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="compte-volet-nouveau">Nouveau compte à débiter</label>
                <select
                  id="compte-volet-nouveau"
                  className={styles.select}
                  value={nouveauId}
                  onChange={(e) => { setNouveauId(e.target.value); setErreur(null) }}
                >
                  <option value="">Sélectionner un compte bancaire</option>
                  {comptesBancaires
                    .filter((c) => String(c.id) !== ancienId)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {(c.banque?.nom || 'Banque')} - {c.intitule} ({c.devise})
                      </option>
                    ))}
                </select>
              </div>

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="compte-volet-motif">Motif du changement</label>
                <textarea
                  id="compte-volet-motif"
                  className={styles.textarea}
                  value={motif}
                  onChange={(e) => setMotif(e.target.value)}
                  rows={3}
                  maxLength={500}
                  placeholder="Pourquoi ce volet doit être payé depuis un autre compte"
                />
                <p className={styles.aide}>Ce motif est consigné au journal avec l'ancien et le nouveau compte.</p>
              </div>

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
                {enCours ? 'Modification…' : 'Changer le compte'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
