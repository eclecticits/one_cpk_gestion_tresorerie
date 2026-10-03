import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, X } from 'lucide-react'
import { getBudgetPostes } from '../api/budget'
import {
  apercuReimputationEncaissement,
  reimputerEncaissement,
  type ApercuReimputationEncaissement,
  type ResultatReimputationEncaissement,
} from '../api/reimputation'
import { ApiError, apiRequest } from '../lib/apiClient'
import type { BudgetPosteSummary } from '../types/budget'
import type { Encaissement, EncaissementArticle } from '../types'
import styles from './ReimputationBudgetaire.module.css'

interface Props {
  encaissement: Encaissement
  onClose: () => void
  onSuccess: (resultat: ResultatReimputationEncaissement) => void
}

const formatMontant = (valeur: string | number | null | undefined, devise = 'USD') =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: devise }).format(Number(valeur ?? 0))

/**
 * Correction du poste de recette d'un encaissement, y compris payé.
 *
 * Un reçu peut mêler plusieurs natures de recette — une cotisation et des frais
 * d'inscription —, donc plusieurs postes : dès qu'il a plusieurs lignes, on
 * choisit lesquelles partent. Seuls les postes de recette autorisés au service
 * de la note sont proposés.
 *
 * L'aperçu se lit avant de décider : la correction déplace du réalisé d'un
 * poste à l'autre, et un refus (écriture validée, exercice clôturé…) s'affiche
 * dès le choix du poste, pas au moment de valider.
 */
export default function ReimputationEncaissement({ encaissement, onClose, onSuccess }: Props) {
  const [articles, setArticles] = useState<EncaissementArticle[]>([])
  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [posteId, setPosteId] = useState('')
  const [motif, setMotif] = useState('')
  const [selection, setSelection] = useState<string[]>([])
  const [apercu, setApercu] = useState<ApercuReimputationEncaissement | null>(null)
  const [refusApercu, setRefusApercu] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const devise = encaissement.devise_perception || 'USD'

  // La liste ne porte pas les lignes : on relit la note. À l'ouverture, tout
  // est retenu — déplacer la note entière reste le cas courant.
  useEffect(() => {
    let annule = false
    apiRequest<Encaissement>('GET', `/encaissements/${encaissement.id}`)
      .then(enc => {
        if (annule) return
        const lignes = enc.articles || []
        setArticles(lignes)
        setSelection(lignes.map(a => String(a.id)))
      })
      .catch(() => { if (!annule) setArticles([]) })
    return () => { annule = true }
  }, [encaissement.id])

  useEffect(() => {
    getBudgetPostes({ active: true, type: 'RECETTE', service_id: encaissement.service_id ?? undefined })
      .then(res => setPostes((res.postes || []).filter(p => (p.type || 'RECETTE').toUpperCase() === 'RECETTE')))
      .catch(() => setPostes([]))
  }, [encaissement.service_id])

  const posteDe = (article: EncaissementArticle) => article.budget_poste_id ?? encaissement.budget_poste_id ?? null
  const codeDe = (id: number | null | undefined) =>
    id == null ? 'sans poste' : (postes.find(p => p.id === id)?.code
      ?? (id === encaissement.budget_poste_id ? encaissement.budget_poste_code : null)
      ?? `#${id}`)

  const plusieursLignes = articles.length > 1
  const partielle = selection.length > 0 && selection.length < articles.length
  const retenues = useMemo(
    () => articles.filter(a => selection.includes(String(a.id))),
    [articles, selection],
  )
  const cleSelection = [...selection].sort().join(',')

  useEffect(() => {
    setApercu(null)
    setRefusApercu(null)
    if (!posteId || (articles.length > 0 && selection.length === 0)) return
    let annule = false
    apercuReimputationEncaissement(encaissement.id, Number(posteId), partielle ? selection : undefined)
      .then(data => { if (!annule) setApercu(data) })
      .catch(err => {
        if (!annule) setRefusApercu(err instanceof ApiError ? err.message : 'Aperçu indisponible.')
      })
    return () => { annule = true }
    // `cleSelection` suit le contenu de la sélection, pas l'identité du tableau.
  }, [posteId, encaissement.id, cleSelection, partielle, articles.length, selection.length])

  const incomplet = !posteId || motif.trim().length < 3 || (articles.length > 0 && selection.length === 0)
  const interdit = enCours || incomplet || !!refusApercu
  const posteArrivee = postes.find(p => String(p.id) === posteId)
  const postesDepart = retenues.length
    ? [...new Set(retenues.map(a => codeDe(posteDe(a))))]
    : [codeDe(encaissement.budget_poste_id)]

  const basculer = (id: string) => {
    setErreur(null)
    setSelection(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))
  }

  const valider = async () => {
    if (interdit) return
    setEnCours(true)
    setErreur(null)
    try {
      const resultat = await reimputerEncaissement(encaissement.id, {
        budget_poste_id: Number(posteId),
        motif: motif.trim(),
        ...(partielle ? { article_ids: selection } : {}),
      })
      onSuccess(resultat)
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'La ré-imputation a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reimputation-encaissement-titre"
      className={styles.overlay}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className={styles.modal}>
        <div className={styles.header}>
          <div>
            <h2 id="reimputation-encaissement-titre" className={styles.title}>
              Corriger le poste budgétaire
            </h2>
            <p className={styles.subtitle}>
              {`Encaissement ${encaissement.numero_recu || encaissement.numero_proforma || ''}`.trim()}
              {' — '}le réalisé des versements suit le nouveau poste de recette.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className={styles.close}>
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className={styles.body}>
          {plusieursLignes && (
            <div className={styles.champ} role="group" aria-labelledby="reimputation-encaissement-lignes">
              <span className={styles.label} id="reimputation-encaissement-lignes">Lignes à déplacer</span>
              <div className={styles.lignes}>
                {articles.map(article => {
                  const id = String(article.id)
                  const retenue = selection.includes(id)
                  const poste = posteDe(article)
                  return (
                    <label
                      key={id}
                      className={`${styles.ligne} ${retenue ? styles.ligneRetenue : styles.ligneNonRetenue}`}
                    >
                      <input type="checkbox" checked={retenue} onChange={() => basculer(id)} />
                      <span className={styles.ligneIntitule}>{article.libelle}</span>
                      <span className={`${styles.posteTag} ${poste == null ? styles.posteTagVide : ''}`}>
                        {codeDe(poste)}
                      </span>
                      <span className={styles.ligneMontant}>{formatMontant(article.montant, devise)}</span>
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
            <label className={styles.label} htmlFor="reimputation-encaissement-poste">
              Nouveau poste de recette
            </label>
            <select
              id="reimputation-encaissement-poste"
              className={styles.select}
              value={posteId}
              onChange={e => { setPosteId(e.target.value); setErreur(null) }}
            >
              <option value="">Choisir un poste…</option>
              {postes.map(p => (
                <option key={p.id} value={p.id}>{p.code} — {p.libelle}</option>
              ))}
            </select>
          </div>

          {refusApercu && (
            <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
              <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
              <span>{refusApercu}</span>
            </div>
          )}

          {apercu && (
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
                  <span className={styles.montantLabel}>Réalisé déplacé</span>
                  <span
                    className={`${styles.montantValeur} ${Number(apercu.montant_paye_deplace) ? '' : styles.montantNul}`}
                  >
                    {formatMontant(apercu.montant_paye_deplace)}
                  </span>
                </div>
              </div>

              <p className={styles.detail}>
                {apercu.lignes_total > 0 && <>{apercu.lignes} ligne(s) sur {apercu.lignes_total}{' · '}</>}
                {apercu.versements} versement(s){' · '}{apercu.imputations} imputation(s)
                {apercu.ecritures_reecrites > 0 && (
                  <>{' · '}{apercu.ecritures_reecrites} écriture(s) comptable(s) au brouillon mise(s) à jour</>
                )}
              </p>
            </div>
          )}

          <div className={styles.champ}>
            <label className={styles.label} htmlFor="reimputation-encaissement-motif">
              Motif de la correction
            </label>
            <textarea
              id="reimputation-encaissement-motif"
              className={styles.textarea}
              value={motif}
              onChange={e => setMotif(e.target.value)}
              rows={3}
              maxLength={500}
              placeholder="Pourquoi le poste d'origine était erroné"
            />
            <p className={styles.aide}>
              Ce motif est consigné au journal : il devra suffire, dans six mois, à comprendre
              la correction sans rouvrir le dossier.
            </p>
          </div>

          {erreur && (
            <div className={`${styles.alerte} ${styles.alerteBloquante}`}>
              <AlertTriangle size={16} aria-hidden="true" className={styles.alerteIcone} />
              <span>{erreur}</span>
            </div>
          )}
        </div>

        <div className={styles.footer}>
          <button type="button" onClick={onClose} className={`${styles.bouton} ${styles.secondaire}`}>
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
  )
}
