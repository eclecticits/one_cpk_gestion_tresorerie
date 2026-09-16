import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, ArrowRightLeft, X } from 'lucide-react'
import { getBudgetPostes } from '../api/budget'
import {
  apercuReimputation,
  reimputerRequisition,
  type ApercuReimputation,
} from '../api/reimputation'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import { ApiError } from '../lib/apiClient'
import type { BudgetPosteSummary } from '../types/budget'
import type { LigneRequisition } from '../types'
import styles from './ReimputationBudgetaire.module.css'

interface Props {
  requisitionId: string
  /** Les lignes de la réquisition : on corrige les lignes, pas la réquisition. */
  lignes: LigneRequisition[]
  onReimpute?: () => void
}

const montant = (valeur: string | number | undefined) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur ?? 0))

/**
 * Correction de l'imputation budgétaire d'une réquisition, y compris payée.
 *
 * Une réquisition porte autant de postes que de lignes. Corriger l'imputation
 * d'une ligne ne doit pas emporter ses voisines : dès qu'il y en a plusieurs,
 * on choisit lesquelles partent.
 *
 * L'aperçu n'est pas un ornement : la correction déplace de l'argent d'un poste
 * à l'autre — engagement, réalisé et imputations figées du paiement. Ce qui va
 * bouger se lit avant d'être décidé, jamais dans un rapport le mois suivant.
 */
export default function ReimputationBudgetaire({ requisitionId, lignes, onReimpute }: Props) {
  const { hasPermission } = usePermissions()
  const { showSuccess } = useNotification()
  const autorise = hasPermission('treso.requisitions.reimputer')

  const [ouvert, setOuvert] = useState(false)
  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [posteId, setPosteId] = useState('')
  const [motif, setMotif] = useState('')
  const [forcer, setForcer] = useState(false)
  const [selection, setSelection] = useState<string[]>([])
  const [apercu, setApercu] = useState<ApercuReimputation | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const cleDesLignes = useMemo(() => lignes.map(l => String(l.id)).join(','), [lignes])
  const cleSelection = [...selection].sort().join(',')
  const plusieursLignes = lignes.length > 1
  const partielle = selection.length > 0 && selection.length < lignes.length
  const retenues = useMemo(
    () => lignes.filter(l => selection.includes(String(l.id))),
    [lignes, selection],
  )

  // À l'ouverture, tout est retenu : le cas courant reste de déplacer la
  // réquisition entière, et décocher est un geste délibéré.
  useEffect(() => {
    if (ouvert) setSelection(cleDesLignes ? cleDesLignes.split(',') : [])
  }, [ouvert, cleDesLignes])

  /**
   * Le seul poste à écarter du choix est celui où toutes les lignes retenues
   * se trouvent déjà — le serveur refuserait. Les autres postes de la
   * réquisition restent offerts : regrouper deux lignes sur un même poste est
   * une correction légitime.
   */
  const posteExclu = useMemo(() => {
    if (retenues.length === 0) return null
    const postesRetenus = new Set(retenues.map(l => l.budget_poste_id ?? 0))
    return (postesRetenus.size === 1 ? [...postesRetenus][0] : null) || null
  }, [retenues])

  useEffect(() => {
    if (!ouvert) return
    getBudgetPostes({ active: true })
      .then(res => setPostes((res.postes || []).filter(p => p.id !== posteExclu)))
      .catch(() => setPostes([]))
  }, [ouvert, posteExclu])

  // Décocher des lignes peut rendre le poste déjà choisi inéligible : on le
  // relâche plutôt que de le laisser sélectionné hors de la liste.
  useEffect(() => {
    if (posteExclu !== null) setPosteId(prev => (prev === String(posteExclu) ? '' : prev))
  }, [posteExclu])

  useEffect(() => {
    if (!ouvert || !posteId || selection.length === 0) { setApercu(null); return }
    let annule = false
    apercuReimputation(requisitionId, Number(posteId), partielle ? selection : undefined)
      .then(data => { if (!annule) setApercu(data) })
      .catch(() => { if (!annule) setApercu(null) })
    return () => { annule = true }
    // `cleSelection` suit le contenu de la sélection, pas l'identité du tableau.
  }, [ouvert, posteId, requisitionId, cleSelection, partielle, selection.length])

  if (!autorise) return null

  const bloqueParLaCompta = (apercu?.sorties_comptabilisees.length ?? 0) > 0
  const incomplet = !posteId || motif.trim().length < 3 || selection.length === 0
  const interdit = enCours || incomplet || bloqueParLaCompta
  const posteArrivee = postes.find(p => String(p.id) === posteId)
  // Les postes que les lignes retenues quittent, lus dans leurs empreintes :
  // l'aperçu ne renvoie que des identifiants, la ligne porte le code.
  const postesDepart = [...new Set(retenues.map(l => l.budget_poste_code_snapshot || 'Sans poste'))]

  const basculer = (id: string) => {
    setErreur(null)
    setSelection(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))
  }

  const fermer = () => {
    setOuvert(false)
    setPosteId('')
    setMotif('')
    setForcer(false)
    setSelection([])
    setApercu(null)
    setErreur(null)
  }

  const valider = async () => {
    if (incomplet) return
    setEnCours(true)
    setErreur(null)
    try {
      const res = await reimputerRequisition(requisitionId, {
        budget_poste_id: Number(posteId),
        motif: motif.trim(),
        forcer,
        ...(partielle ? { ligne_ids: selection } : {}),
      })
      const portee = res.lignes_deplacees < res.lignes_total
        ? `${res.lignes_deplacees} ligne(s) sur ${res.lignes_total} ré-imputée(s)`
        : 'Réquisition ré-imputée'
      showSuccess(
        'Imputation corrigée',
        `${portee} sur ${res.nouveau_poste_code} : ${montant(res.montant_engage_deplace)} engagés`
        + `${Number(res.montant_paye_deplace) ? ` et ${montant(res.montant_paye_deplace)} payés` : ''} déplacés.`,
      )
      fermer()
      onReimpute?.()
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'La ré-imputation a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <>
      <button
        type="button"
        className={styles.declencheur}
        onClick={() => setOuvert(true)}
        title="Corriger le poste budgétaire de cette réquisition"
      >
        <ArrowRightLeft size={15} aria-hidden="true" />
        Corriger le poste budgétaire
      </button>

      {ouvert && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="reimputation-titre"
          className={styles.overlay}
          onMouseDown={e => { if (e.target === e.currentTarget) fermer() }}
        >
          <div className={styles.modal}>
            <div className={styles.header}>
              <div>
                <h2 id="reimputation-titre" className={styles.title}>
                  Corriger le poste budgétaire
                </h2>
                <p className={styles.subtitle}>
                  L'engagement, le réalisé et les imputations du paiement suivent le nouveau poste.
                </p>
              </div>
              <button type="button" onClick={fermer} aria-label="Fermer" className={styles.close}>
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className={styles.body}>
              {plusieursLignes && (
                <div className={styles.champ} role="group" aria-labelledby="reimputation-lignes">
                  <span className={styles.label} id="reimputation-lignes">Lignes à déplacer</span>
                  <div className={styles.lignes}>
                    {lignes.map(ligne => {
                      const id = String(ligne.id)
                      const retenue = selection.includes(id)
                      return (
                        <label
                          key={id}
                          className={`${styles.ligne} ${retenue ? styles.ligneRetenue : styles.ligneNonRetenue}`}
                        >
                          <input type="checkbox" checked={retenue} onChange={() => basculer(id)} />
                          <span className={styles.ligneIntitule}>
                            {ligne.rubrique || ligne.description}
                          </span>
                          <span
                            className={`${styles.posteTag} ${ligne.budget_poste_code_snapshot ? '' : styles.posteTagVide}`}
                          >
                            {ligne.budget_poste_code_snapshot || 'sans poste'}
                          </span>
                          <span className={styles.ligneMontant}>
                            {montant(ligne.montant_total as string | number)}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                  {selection.length === 0 && (
                    <span className={styles.avertissementChamp}>Retenez au moins une ligne.</span>
                  )}
                </div>
              )}

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="reimputation-poste">
                  Nouveau poste
                </label>
                <select
                  id="reimputation-poste"
                  className={styles.select}
                  value={posteId}
                  onChange={e => { setPosteId(e.target.value); setErreur(null); setForcer(false) }}
                >
                  <option value="">Choisir un poste…</option>
                  {postes.map(p => (
                    <option key={p.id} value={p.id}>{p.code} — {p.libelle}</option>
                  ))}
                </select>
              </div>

              {apercu && (bloqueParLaCompta ? (
                <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
                  <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
                  <span>
                    Une sortie de fonds est déjà comptabilisée : le poste a servi à choisir le compte.
                    Passez par une écriture de régularisation comptable avant de corriger l'imputation.
                  </span>
                </div>
              ) : (
                <div className={styles.apercu}>
                  <div className={styles.trajet}>
                    <span className={styles.trajetPoste}>{postesDepart.join(', ')}</span>
                    <ArrowRight size={15} aria-hidden="true" className={styles.trajetFleche} />
                    <span className={`${styles.trajetPoste} ${styles.trajetArrivee}`}>
                      {posteArrivee ? posteArrivee.code : '—'}
                    </span>
                  </div>

                  <div className={styles.montants}>
                    <div className={styles.montant}>
                      <span className={styles.montantLabel}>Engagement déplacé</span>
                      <span
                        className={`${styles.montantValeur} ${Number(apercu.montant_engage_deplace) ? '' : styles.montantNul}`}
                      >
                        {montant(apercu.montant_engage_deplace)}
                      </span>
                    </div>
                    <div className={styles.montant}>
                      <span className={styles.montantLabel}>Réalisé déplacé</span>
                      <span
                        className={`${styles.montantValeur} ${Number(apercu.montant_paye_deplace) ? '' : styles.montantNul}`}
                      >
                        {montant(apercu.montant_paye_deplace)}
                      </span>
                    </div>
                  </div>

                  <p className={styles.detail}>
                    {apercu.lignes} ligne(s) sur {apercu.lignes_total}
                    {' · '}{apercu.sorties} sortie(s) de fonds
                    {' · '}{apercu.imputations} imputation(s)
                    {apercu.sorties_reparties > 0 && (
                      <>
                        {' · '}{apercu.sorties_reparties} imputation(s) réparties au prorata,
                        la pièce de décaissement ne bougeant pas
                      </>
                    )}
                  </p>

                  {apercu.fusionne_plusieurs_postes && (
                    <div className={`${styles.alerte} ${styles.alerteAttention}`}>
                      <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
                      <span>
                        Ces lignes occupent {apercu.postes_avant.length} postes différents :
                        les rassembler ici les fera disparaître des autres.
                      </span>
                    </div>
                  )}
                </div>
              ))}

              <div className={styles.champ}>
                <label className={styles.label} htmlFor="reimputation-motif">
                  Motif de la correction
                </label>
                <textarea
                  id="reimputation-motif"
                  className={styles.textarea}
                  value={motif}
                  onChange={e => setMotif(e.target.value)}
                  rows={3}
                  maxLength={500}
                  placeholder="Pourquoi l'imputation d'origine était erronée"
                />
                <p className={styles.aide}>
                  Ce motif est consigné au journal : il devra suffire, dans six mois, à comprendre
                  la correction sans rouvrir le dossier.
                </p>
              </div>

              {erreur && (
                <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
                  <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
                  <span>
                    {erreur}
                    {erreur.toLowerCase().includes('disponible') && (
                      <label className={styles.forcer}>
                        <input
                          id="reimputation-forcer"
                          type="checkbox"
                          checked={forcer}
                          onChange={e => setForcer(e.target.checked)}
                        />
                        Assumer le dépassement du poste d'arrivée
                      </label>
                    )}
                  </span>
                </div>
              )}
            </div>

            <div className={styles.footer}>
              <button
                type="button"
                onClick={fermer}
                className={`${styles.bouton} ${styles.secondaire}`}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void valider()}
                disabled={interdit}
                className={`${styles.bouton} ${styles.principal}`}
              >
                {enCours ? 'Correction…' : 'Ré-imputer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
