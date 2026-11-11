import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Link2,
  Link2Off,
  RefreshCw,
  Search,
  Sparkles,
  Wand2,
  X,
} from 'lucide-react'
import {
  delettrerCompta,
  getComptaComptesALettrer,
  getComptaLignesALettrer,
  lettrageAutomatiqueCompta,
  lettrerComptaLignes,
} from '../../api/comptabilite'
import type { ComptaLettrageAutoResult } from '../../types/comptabilite'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import styles from './ComptaLettragePanel.module.css'

function montant(value: string | number): string {
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(toNumber(value))
}

function jour(value: string | null): string {
  if (!value) return '—'
  const [annee, mois, j] = value.slice(0, 10).split('-')
  return annee && mois && j ? `${j}/${mois}/${annee}` : value
}

function normaliser(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

// Les montants arrivent en texte : on compare en centimes entiers pour qu'un
// écart affiché à 0,00 soit réellement nul.
const centimes = (value: string): number => Math.round(toNumber(value) * 100)

const MOTIFS: Record<string, string> = {
  REFERENCE: 'Même pièce',
  MONTANT: 'Même montant',
}

interface Props {
  canLettrer: boolean
}

export default function ComptaLettragePanel({ canLettrer }: Props) {
  const { notifyError, notifySuccess } = useToast()
  const queryClient = useQueryClient()
  const [compteId, setCompteId] = useState<number | null>(null)
  const [recherche, setRecherche] = useState('')
  const [soldesSeulement, setSoldesSeulement] = useState(true)
  const [inclureLettrees, setInclureLettrees] = useState(false)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [enCours, setEnCours] = useState(false)
  const [apercuAuto, setApercuAuto] = useState<{
    portee: number | null
    rapport: ComptaLettrageAutoResult
  } | null>(null)

  const comptesQuery = useQuery({
    queryKey: ['compta-lettrage-comptes'],
    queryFn: getComptaComptesALettrer,
  })
  const comptes = comptesQuery.data ?? []

  const synthese = useMemo(
    () => ({
      comptes: comptes.filter(c => c.lignes_non_lettrees > 0).length,
      lignes: comptes.reduce((total, c) => total + c.lignes_non_lettrees, 0),
      solde: comptes.reduce((total, c) => total + Math.abs(toNumber(c.solde_non_lettre)), 0),
    }),
    [comptes],
  )

  const comptesAffiches = useMemo(() => {
    const termes = normaliser(recherche).split(/\s+/).filter(Boolean)
    return comptes.filter(c => {
      if (soldesSeulement && c.lignes_non_lettrees === 0) return false
      const cible = normaliser(`${c.numero} ${c.libelle}`)
      return termes.every(t => cible.includes(t))
    })
  }, [comptes, recherche, soldesSeulement])

  useEffect(() => {
    if (comptesQuery.isLoading) return
    if (comptesAffiches.length === 0) {
      setCompteId(null)
      return
    }
    if (!comptesAffiches.some(c => c.compte_id === compteId)) {
      setCompteId(comptesAffiches[0].compte_id)
    }
  }, [compteId, comptesAffiches, comptesQuery.isLoading])

  const lignesQuery = useQuery({
    queryKey: ['compta-lettrage-lignes', compteId, inclureLettrees],
    queryFn: () => getComptaLignesALettrer(compteId as number, inclureLettrees),
    enabled: compteId !== null,
  })
  const detail = lignesQuery.data
  const lignes = detail?.lignes ?? []

  useEffect(() => {
    setSelection(new Set())
  }, [compteId, inclureLettrees])

  useEffect(() => {
    if (!apercuAuto) return
    const fermerAvecClavier = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !enCours) setApercuAuto(null)
    }
    document.addEventListener('keydown', fermerAvecClavier)
    return () => document.removeEventListener('keydown', fermerAvecClavier)
  }, [apercuAuto, enCours])

  const totaux = useMemo(() => {
    let debit = 0
    let credit = 0
    for (const ligne of lignes) {
      if (!selection.has(ligne.ligne_id)) continue
      debit += centimes(ligne.debit)
      credit += centimes(ligne.credit)
    }
    return { debit: debit / 100, credit: credit / 100, ecart: (debit - credit) / 100 }
  }, [lignes, selection])

  const peutLettrer = canLettrer && selection.size >= 2 && totaux.ecart === 0 && !enCours

  const rafraichir = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['compta-lettrage-comptes'] }),
      queryClient.invalidateQueries({ queryKey: ['compta-lettrage-lignes'] }),
      queryClient.invalidateQueries({ queryKey: ['compta-balance-agee'] }),
      queryClient.invalidateQueries({ queryKey: ['compta-grand-livre'] }),
    ])
  }

  const basculer = (ligneId: string) => {
    setSelection(prev => {
      const suivant = new Set(prev)
      if (suivant.has(ligneId)) suivant.delete(ligneId)
      else suivant.add(ligneId)
      return suivant
    })
  }

  const lettrer = async () => {
    setEnCours(true)
    try {
      const resultat = await lettrerComptaLignes([...selection])
      notifySuccess('Lignes lettrées', `${resultat.lignes} lignes portent la lettre ${resultat.code}.`)
      setSelection(new Set())
      await rafraichir()
    } catch (error) {
      notifyError('Lettrage refusé', error instanceof Error ? error.message : 'Le lettrage a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  const delettrer = async (code: string) => {
    if (compteId === null) return
    setEnCours(true)
    try {
      const resultat = await delettrerCompta(compteId, code)
      notifySuccess('Lettre retirée', `${resultat.lignes} lignes ne portent plus la lettre ${code}.`)
      await rafraichir()
    } catch (error) {
      notifyError('Délettrage refusé', error instanceof Error ? error.message : 'Le délettrage a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  const simulerAuto = async (portee: number | null) => {
    setEnCours(true)
    try {
      const rapport = await lettrageAutomatiqueCompta({ compte_id: portee, simulation: true })
      setApercuAuto({ portee, rapport })
    } catch (error) {
      notifyError('Lettrage automatique', error instanceof Error ? error.message : 'La simulation a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  const appliquerAuto = async () => {
    if (!apercuAuto) return
    setEnCours(true)
    try {
      const rapport = await lettrageAutomatiqueCompta({ compte_id: apercuAuto.portee, simulation: false })
      notifySuccess(
        'Lettrage automatique',
        `${rapport.groupes_lettres} rapprochements, ${rapport.lignes_lettrees} lignes lettrées.`,
      )
      setApercuAuto(null)
      await rafraichir()
    } catch (error) {
      notifyError('Lettrage automatique', error instanceof Error ? error.message : 'Le lettrage a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div className={styles.workspace}>
      <section className={styles.overview} aria-label="Synthèse du lettrage">
        <div className={styles.overviewIntro}>
          <span className={styles.eyebrow}>Rapprochement des tiers</span>
          <h2>Pointer les créances et leurs règlements</h2>
          <p>Une même lettre relie les mouvements qui se soldent. Le reste non lettré demeure exigible.</p>
        </div>
        <div className={styles.metrics}>
          <div className={styles.metric}>
            <span>Comptes ouverts</span>
            <strong>{synthese.comptes}</strong>
          </div>
          <div className={styles.metric}>
            <span>Lignes à pointer</span>
            <strong>{synthese.lignes}</strong>
          </div>
          <div className={styles.metric}>
            <span>Solde à analyser</span>
            <strong>{montant(synthese.solde)}</strong>
          </div>
        </div>
      </section>

      <div className={styles.grid}>
        <aside className={`${styles.panel} ${styles.accountsPanel}`} aria-label="Comptes lettrables">
          <div className={styles.heading}>
            <div>
              <span className={styles.eyebrow}>Comptes</span>
              <h3>Tiers à rapprocher</h3>
            </div>
            {canLettrer && (
              <button
                type="button"
                className={styles.secondary}
                disabled={enCours || synthese.lignes === 0}
                onClick={() => simulerAuto(null)}
              >
                <Sparkles size={15} /> Tout proposer
              </button>
            )}
          </div>

          <div className={styles.searchField}>
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              placeholder="Rechercher un compte…"
              aria-label="Rechercher un compte"
              value={recherche}
              onChange={e => setRecherche(e.target.value)}
            />
            {recherche && (
              <button type="button" aria-label="Effacer la recherche" onClick={() => setRecherche('')}>
                <X size={14} />
              </button>
            )}
          </div>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={soldesSeulement}
              onChange={e => setSoldesSeulement(e.target.checked)}
            />
            Masquer les comptes entièrement lettrés
          </label>

          {comptesQuery.isLoading ? (
            <div className={styles.empty}>Chargement des comptes…</div>
          ) : comptesQuery.isError ? (
            <div className={styles.errorState} role="alert">
              <AlertCircle size={18} />
              <span>Les comptes n’ont pas pu être chargés.</span>
              <button type="button" className={styles.textButton} onClick={() => comptesQuery.refetch()}>
                Réessayer
              </button>
            </div>
          ) : comptesAffiches.length === 0 ? (
            <div className={styles.empty}>
              {comptes.length === 0
                ? 'Aucun compte lettrable ne porte encore de mouvement validé.'
                : 'Aucun compte ne correspond à ce filtre.'}
            </div>
          ) : (
            <ul className={styles.comptes}>
              {comptesAffiches.map(c => (
                <li key={c.compte_id}>
                  <button
                    type="button"
                    className={`${styles.compte} ${c.compte_id === compteId ? styles.compteActif : ''}`}
                    aria-current={c.compte_id === compteId ? 'true' : undefined}
                    onClick={() => setCompteId(c.compte_id)}
                  >
                    <span className={styles.compteMain}>
                      <span className={styles.mono}>{c.numero}</span>
                      <span className={styles.compteLibelle}>{c.libelle}</span>
                    </span>
                    <span className={styles.compteMeta}>
                      <span>{c.lignes_non_lettrees} ligne{c.lignes_non_lettrees > 1 ? 's' : ''}</span>
                      <strong className={c.lignes_non_lettrees === 0 ? styles.soldeOk : undefined}>
                        {c.lignes_non_lettrees === 0 ? 'Soldé' : montant(c.solde_non_lettre)}
                      </strong>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className={`${styles.panel} ${styles.linesPanel}`} aria-label="Lignes du compte">
          {compteId === null ? (
            <div className={styles.blankState}>
              <Link2 size={28} />
              <strong>Sélectionnez un compte</strong>
              <span>Ses débits et crédits apparaîtront ici pour être rapprochés.</span>
            </div>
          ) : lignesQuery.isLoading ? (
            <div className={styles.empty}>Chargement des mouvements…</div>
          ) : lignesQuery.isError || !detail ? (
            <div className={styles.errorState} role="alert">
              <AlertCircle size={18} />
              <span>Les mouvements de ce compte n’ont pas pu être chargés.</span>
              <button type="button" className={styles.textButton} onClick={() => lignesQuery.refetch()}>
                Réessayer
              </button>
            </div>
          ) : (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <span className={styles.eyebrow}>Compte sélectionné</span>
                  <h3>
                    <span className={styles.mono}>{detail.compte_numero}</span>
                    <span>{detail.compte_libelle}</span>
                  </h3>
                  <div className={styles.balanceStrip}>
                    <span>Débit <strong>{montant(detail.debit_non_lettre)}</strong></span>
                    <span>Crédit <strong>{montant(detail.credit_non_lettre)}</strong></span>
                    <span>Solde <strong>{montant(detail.solde_non_lettre)}</strong></span>
                  </div>
                </div>
                {canLettrer && (
                  <button
                    type="button"
                    className={styles.secondary}
                    disabled={enCours || lignes.length < 2}
                    onClick={() => simulerAuto(compteId)}
                  >
                    <Wand2 size={15} /> Proposer un lettrage
                  </button>
                )}
              </div>

              <div className={styles.listToolbar}>
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    checked={inclureLettrees}
                    onChange={e => setInclureLettrees(e.target.checked)}
                  />
                  Inclure les lignes déjà lettrées
                </label>
                <button
                  type="button"
                  className={styles.iconAction}
                  aria-label="Actualiser les mouvements"
                  title="Actualiser"
                  disabled={lignesQuery.isFetching}
                  onClick={() => lignesQuery.refetch()}
                >
                  <RefreshCw size={15} className={lignesQuery.isFetching ? styles.spin : undefined} />
                </button>
              </div>

              {lignes.length === 0 ? (
                <div className={styles.blankState}>
                  <CheckCircle2 size={28} />
                  <strong>Compte entièrement lettré</strong>
                  <span>Activez l’affichage des lignes lettrées pour consulter l’historique.</span>
                </div>
              ) : (
                <div className={styles.tableWrap}>
                  <table>
                    <thead>
                      <tr>
                        <th aria-label="Sélection" />
                        <th>Date</th>
                        <th>Pièce</th>
                        <th>Journal</th>
                        <th>Référence</th>
                        <th>Libellé</th>
                        <th className={styles.amount}>Débit</th>
                        <th className={styles.amount}>Crédit</th>
                        <th>Lettre</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lignes.map(ligne => {
                        const selected = selection.has(ligne.ligne_id)
                        return (
                          <tr
                            key={ligne.ligne_id}
                            className={`${ligne.lettrage ? styles.lettree : ''} ${selected ? styles.selected : ''}`}
                          >
                            <td>
                              {!ligne.lettrage && (
                                <input
                                  type="checkbox"
                                  aria-label={`Sélectionner la ligne du ${jour(ligne.date_ecriture)}`}
                                  disabled={!canLettrer}
                                  checked={selected}
                                  onChange={() => basculer(ligne.ligne_id)}
                                />
                              )}
                            </td>
                            <td>{jour(ligne.date_ecriture)}</td>
                            <td className={styles.mono}>{ligne.numero || 'Brouillon'}</td>
                            <td className={styles.mono}>{ligne.journal_code}</td>
                            <td className={styles.mono}>{ligne.reference_piece || '—'}</td>
                            <td className={styles.libelleCell}>{ligne.libelle || '—'}</td>
                            <td className={styles.amount}>{toNumber(ligne.debit) ? montant(ligne.debit) : '—'}</td>
                            <td className={styles.amount}>{toNumber(ligne.credit) ? montant(ligne.credit) : '—'}</td>
                            <td>
                              {ligne.lettrage ? (
                                <span className={styles.lettre}>
                                  {ligne.lettrage}
                                  {canLettrer && (
                                    <button
                                      type="button"
                                      className={styles.iconBtn}
                                      title={`Retirer la lettre ${ligne.lettrage} de tout son groupe`}
                                      aria-label={`Retirer la lettre ${ligne.lettrage}`}
                                      disabled={enCours}
                                      onClick={() => delettrer(ligne.lettrage as string)}
                                    >
                                      <Link2Off size={14} />
                                    </button>
                                  )}
                                </span>
                              ) : (
                                <span className={styles.pendingBadge}>À pointer</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {canLettrer && (
                <div className={`${styles.selectionBar} ${selection.size > 0 ? styles.selectionBarActive : ''}`}>
                  <div>
                    <strong>{selection.size} sélectionnée{selection.size > 1 ? 's' : ''}</strong>
                    <span>
                      Débit {montant(totaux.debit)} · Crédit {montant(totaux.credit)} ·{' '}
                      <b className={totaux.ecart === 0 ? styles.ok : styles.ecart}>
                        Écart {montant(totaux.ecart)}
                      </b>
                    </span>
                  </div>
                  <button type="button" className={styles.primary} disabled={!peutLettrer} onClick={lettrer}>
                    <Link2 size={15} /> Lettrer la sélection
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {apercuAuto && (
        <div
          className={styles.overlay}
          role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget && !enCours) setApercuAuto(null)
          }}
        >
          <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="lettrage-auto-title">
            <div className={styles.modalHeader}>
              <div>
                <span className={styles.eyebrow}>Aperçu sans modification</span>
                <h3 id="lettrage-auto-title">Lettrage automatique</h3>
              </div>
              <button
                type="button"
                className={styles.closeButton}
                aria-label="Fermer"
                disabled={enCours}
                onClick={() => setApercuAuto(null)}
              >
                <X size={18} />
              </button>
            </div>

            {apercuAuto.rapport.groupes_lettres === 0 ? (
              <div className={styles.modalEmpty}>
                <CheckCircle2 size={28} />
                <strong>Aucun rapprochement évident</strong>
                <p>
                  {apercuAuto.rapport.comptes_examines} compte
                  {apercuAuto.rapport.comptes_examines > 1 ? 's ont' : ' a'} été examiné
                  {apercuAuto.rapport.comptes_examines > 1 ? 's' : ''}. Aucune pièce soldée ni paire de même montant
                  n’a été trouvée.
                </p>
              </div>
            ) : (
              <>
                <div className={styles.previewSummary}>
                  <div><span>Rapprochements</span><strong>{apercuAuto.rapport.groupes_lettres}</strong></div>
                  <div><span>Lignes concernées</span><strong>{apercuAuto.rapport.lignes_lettrees}</strong></div>
                  <div><span>Comptes examinés</span><strong>{apercuAuto.rapport.comptes_examines}</strong></div>
                </div>
                <p className={styles.modalNotice}>Rien n’est encore enregistré. Vérifiez la proposition avant de l’appliquer.</p>
                <div className={styles.tableWrap}>
                  <table>
                    <thead>
                      <tr>
                        <th>Compte</th>
                        <th>Rapprochement</th>
                        <th>Lignes</th>
                        <th className={styles.amount}>Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {apercuAuto.rapport.groupes.map((g, index) => (
                        <tr key={`${g.compte_id}-${index}`}>
                          <td className={styles.mono}>{g.compte_numero}</td>
                          <td><span className={styles.reasonBadge}>{MOTIFS[g.motif] ?? g.motif}</span></td>
                          <td>
                            {g.lignes.map(l => `${jour(l.date_ecriture)} ${l.numero ?? ''}`.trim()).join(' · ')}
                          </td>
                          <td className={styles.amount}>{montant(g.montant)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {apercuAuto.rapport.groupes.length < apercuAuto.rapport.groupes_lettres && (
                  <p className={styles.caption}>
                    Les {apercuAuto.rapport.groupes.length} premiers rapprochements sont affichés ; tous seront lettrés.
                  </p>
                )}
              </>
            )}

            <div className={styles.actions}>
              <button type="button" className={styles.secondary} disabled={enCours} onClick={() => setApercuAuto(null)}>
                Fermer
              </button>
              {apercuAuto.rapport.groupes_lettres > 0 && (
                <button type="button" className={styles.primary} disabled={enCours} onClick={appliquerAuto}>
                  <Link2 size={15} /> Appliquer {apercuAuto.rapport.groupes_lettres} rapprochement
                  {apercuAuto.rapport.groupes_lettres > 1 ? 's' : ''}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
