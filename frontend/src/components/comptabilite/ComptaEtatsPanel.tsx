import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Download, FileSpreadsheet } from 'lucide-react'
import {
  getComptaBalance,
  getComptaEcriture,
  getComptaGrandLivre,
  getComptaLivreJournal,
} from '../../api/comptabilite'
import {
  exportBalanceExcel,
  exportBalancePDF,
  exportGrandLivreExcel,
  exportGrandLivrePDF,
} from '../../utils/comptaExports'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import type {
  ComptaCompte,
  ComptaEcriture,
  ComptaExercice,
  ComptaJournal,
} from '../../types/comptabilite'
import EcritureDetailModal from './EcritureDetailModal'
import styles from './ComptaEtatsPanel.module.css'

type Etat = 'balance' | 'grand-livre' | 'journal'

interface Props {
  comptes: ComptaCompte[]
  journaux: ComptaJournal[]
  exercices: ComptaExercice[]
  canValider: boolean
}

function formatMontant(value: string | number): string {
  const n = toNumber(value)
  if (n === 0) return '—'
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

/**
 * États comptables : Balance générale, Grand Livre, Journal.
 *
 * Les filtres (exercice, période, brouillons) sont partagés par les trois
 * états : un comptable qui cadre une période veut la retrouver en passant de
 * la balance au grand livre, pas la ressaisir.
 */
export default function ComptaEtatsPanel({ comptes, journaux, exercices, canValider }: Props) {
  const { notifyError } = useToast()

  const [etat, setEtat] = useState<Etat>('balance')
  const [exerciceId, setExerciceId] = useState<number | ''>(exercices[0]?.id ?? '')
  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [inclureBrouillons, setInclureBrouillons] = useState(false)
  const [compteId, setCompteId] = useState<number | ''>('')
  const [journalId, setJournalId] = useState<number | ''>(journaux[0]?.id ?? '')
  const [curseurs, setCurseurs] = useState<(string | null)[]>([null])
  const [pageIndex, setPageIndex] = useState(0)
  const [ecritureOuverte, setEcritureOuverte] = useState<ComptaEcriture | null>(null)

  const filtres = {
    exercice_id: exerciceId || undefined,
    date_debut: dateDebut || undefined,
    date_fin: dateFin || undefined,
    inclure_brouillons: inclureBrouillons || undefined,
  }
  const cleFiltres = [exerciceId, dateDebut, dateFin, inclureBrouillons] as const

  // Changer un filtre invalide les curseurs déjà collectés : ils pointaient
  // dans un jeu de résultats différent.
  const reinitialiserPagination = () => {
    setCurseurs([null])
    setPageIndex(0)
  }

  const balanceQuery = useQuery({
    queryKey: ['compta-balance', ...cleFiltres],
    queryFn: () => getComptaBalance(filtres),
    enabled: etat === 'balance' && exerciceId !== '',
  })

  const grandLivreQuery = useQuery({
    queryKey: ['compta-grand-livre', compteId, pageIndex, ...cleFiltres],
    queryFn: () =>
      getComptaGrandLivre(Number(compteId), {
        ...filtres,
        curseur: curseurs[pageIndex] ?? undefined,
        limite: 100,
      }),
    enabled: etat === 'grand-livre' && compteId !== '' && exerciceId !== '',
  })

  const journalQuery = useQuery({
    queryKey: ['compta-journal', journalId, ...cleFiltres],
    queryFn: () => getComptaLivreJournal(Number(journalId), { ...filtres, limite: 500 }),
    enabled: etat === 'journal' && journalId !== '' && exerciceId !== '',
  })

  const ouvrirEcriture = async (ecritureId: string) => {
    try {
      setEcritureOuverte(await getComptaEcriture(ecritureId))
    } catch (err: any) {
      notifyError('Erreur', err?.message || "Impossible d'ouvrir l'écriture.")
    }
  }

  const exporter = async (action: () => void | Promise<void>) => {
    try {
      await action()
    } catch (err: any) {
      notifyError('Export impossible', err?.message || 'Une erreur est survenue.')
    }
  }

  const balance = balanceQuery.data
  const livre = grandLivreQuery.data
  const journal = journalQuery.data

  return (
    <div className={styles.panel}>
      <div className={styles.etatSelector} role="tablist">
        {(
          [
            ['balance', 'Balance générale'],
            ['grand-livre', 'Grand Livre'],
            ['journal', 'Journal'],
          ] as [Etat, string][]
        ).map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={etat === cle}
            className={`${styles.etatBtn} ${etat === cle ? styles.etatBtnActive : ''}`}
            onClick={() => {
              setEtat(cle)
              reinitialiserPagination()
            }}
          >
            {libelle}
          </button>
        ))}
      </div>

      <div className={styles.filtres}>
        <div className={styles.filtre}>
          <label htmlFor="etat-exercice">Exercice</label>
          <select
            id="etat-exercice"
            value={exerciceId}
            onChange={e => {
              setExerciceId(e.target.value ? Number(e.target.value) : '')
              reinitialiserPagination()
            }}
          >
            {exercices.map(ex => (
              <option key={ex.id} value={ex.id}>
                {ex.code}
              </option>
            ))}
          </select>
        </div>

        {etat === 'grand-livre' && (
          <div className={styles.filtre}>
            <label htmlFor="etat-compte">Compte</label>
            <select
              id="etat-compte"
              value={compteId}
              onChange={e => {
                setCompteId(e.target.value ? Number(e.target.value) : '')
                reinitialiserPagination()
              }}
            >
              <option value="">— Choisir un compte —</option>
              {comptes
                .filter(c => !c.is_collectif)
                .map(c => (
                  <option key={c.id} value={c.id}>
                    {c.numero} — {c.libelle}
                  </option>
                ))}
            </select>
          </div>
        )}

        {etat === 'journal' && (
          <div className={styles.filtre}>
            <label htmlFor="etat-journal">Journal</label>
            <select
              id="etat-journal"
              value={journalId}
              onChange={e => setJournalId(e.target.value ? Number(e.target.value) : '')}
            >
              {journaux.map(j => (
                <option key={j.id} value={j.id}>
                  {j.code} — {j.libelle}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className={styles.filtre}>
          <label htmlFor="etat-date-debut">Du</label>
          <input
            id="etat-date-debut"
            type="date"
            value={dateDebut}
            onChange={e => {
              setDateDebut(e.target.value)
              reinitialiserPagination()
            }}
          />
        </div>
        <div className={styles.filtre}>
          <label htmlFor="etat-date-fin">Au</label>
          <input
            id="etat-date-fin"
            type="date"
            value={dateFin}
            onChange={e => {
              setDateFin(e.target.value)
              reinitialiserPagination()
            }}
          />
        </div>

        <label className={styles.checkboxFiltre} htmlFor="etat-brouillons">
          <input
            id="etat-brouillons"
            type="checkbox"
            checked={inclureBrouillons}
            onChange={e => {
              setInclureBrouillons(e.target.checked)
              reinitialiserPagination()
            }}
          />
          Inclure les brouillons (simulation)
        </label>
      </div>

      {inclureBrouillons && (
        <div className={styles.avertissement}>
          <AlertTriangle size={17} />
          <span>
            <strong>Simulation</strong> — cet état inclut des écritures au brouillon, qui peuvent
            encore changer. Il n’a pas de valeur comptable officielle.
          </span>
        </div>
      )}

      {/* ── Balance ─────────────────────────────────────────────────────── */}
      {etat === 'balance' && (
        <>
          {balance && !balance.equilibree && (
            <div className={`${styles.avertissement} ${styles.avertissementGrave}`}>
              <AlertTriangle size={17} />
              <span>
                <strong>Balance déséquilibrée</strong> — total débit ≠ total crédit. L’équilibre
                est pourtant garanti à la validation de chaque écriture : signalez cette anomalie,
                des données ont pu être altérées hors de l’application.
              </span>
            </div>
          )}

          <div className={styles.tableActions}>
            <button
              type="button"
              className={styles.exportBtn}
              disabled={!balance || balance.lignes.length === 0}
              onClick={() => balance && exporter(() => exportBalancePDF(balance))}
            >
              <Download size={15} /> PDF
            </button>
            <button
              type="button"
              className={styles.exportBtn}
              disabled={!balance || balance.lignes.length === 0}
              onClick={() => balance && exporter(() => exportBalanceExcel(balance))}
            >
              <FileSpreadsheet size={15} /> Excel
            </button>
          </div>

          <div className={styles.tableWrap}>
            {balanceQuery.isLoading ? (
              <div className={styles.etatVide}>Calcul de la balance…</div>
            ) : !balance || balance.lignes.length === 0 ? (
              <div className={styles.etatVide}>
                Aucun mouvement comptabilisé sur cette période.
                {!inclureBrouillons && (
                  <p className={styles.etatVideAide}>
                    Les écritures générées automatiquement restent au brouillon jusqu’à leur
                    validation : cochez « inclure les brouillons » pour les visualiser.
                  </p>
                )}
              </div>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Compte</th>
                    <th>Libellé</th>
                    <th className={styles.right}>Débit</th>
                    <th className={styles.right}>Crédit</th>
                    <th className={styles.right}>Solde débiteur</th>
                    <th className={styles.right}>Solde créditeur</th>
                  </tr>
                </thead>
                <tbody>
                  {balance.lignes.map(l => (
                    <tr
                      key={l.compte_id}
                      className={styles.rowCliquable}
                      onClick={() => {
                        setCompteId(l.compte_id)
                        setEtat('grand-livre')
                        reinitialiserPagination()
                      }}
                      title="Ouvrir le Grand Livre de ce compte"
                    >
                      <td className={styles.mono}>{l.compte_numero}</td>
                      <td>{l.compte_libelle}</td>
                      <td className={styles.right}>{formatMontant(l.total_debit)}</td>
                      <td className={styles.right}>{formatMontant(l.total_credit)}</td>
                      <td className={styles.right}>{formatMontant(l.solde_debiteur)}</td>
                      <td className={styles.right}>{formatMontant(l.solde_crediteur)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={2}>TOTAL ({balance.devise_tenue})</td>
                    <td className={styles.right}>{formatMontant(balance.total_debit)}</td>
                    <td className={styles.right}>{formatMontant(balance.total_credit)}</td>
                    <td className={styles.right}>{formatMontant(balance.total_solde_debiteur)}</td>
                    <td className={styles.right}>{formatMontant(balance.total_solde_crediteur)}</td>
                  </tr>
                </tfoot>
              </table>
            )}
          </div>
        </>
      )}

      {/* ── Grand Livre ─────────────────────────────────────────────────── */}
      {etat === 'grand-livre' && (
        <>
          <div className={styles.tableActions}>
            <button
              type="button"
              className={styles.exportBtn}
              disabled={!livre || livre.mouvements.length === 0}
              onClick={() => livre && exporter(() => exportGrandLivrePDF(livre))}
            >
              <Download size={15} /> PDF
            </button>
            <button
              type="button"
              className={styles.exportBtn}
              disabled={!livre || livre.mouvements.length === 0}
              onClick={() => livre && exporter(() => exportGrandLivreExcel(livre))}
            >
              <FileSpreadsheet size={15} /> Excel
            </button>
          </div>

          <div className={styles.tableWrap}>
            {compteId === '' ? (
              <div className={styles.etatVide}>
                Choisissez un compte, ou cliquez une ligne de la balance.
              </div>
            ) : grandLivreQuery.isLoading ? (
              <div className={styles.etatVide}>Chargement du Grand Livre…</div>
            ) : !livre || livre.mouvements.length === 0 ? (
              <div className={styles.etatVide}>Aucun mouvement sur ce compte pour la période.</div>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Pièce</th>
                    <th>Jrn</th>
                    <th>Libellé</th>
                    <th className={styles.right}>Débit</th>
                    <th className={styles.right}>Crédit</th>
                    <th className={styles.right}>Solde</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className={styles.rowSoldeAnterieur}>
                    <td colSpan={6}>Solde antérieur</td>
                    <td className={styles.right}>{formatMontant(livre.solde_anterieur)}</td>
                  </tr>
                  {livre.mouvements.map(m => (
                    <tr
                      key={m.ligne_id}
                      className={styles.rowCliquable}
                      onClick={() => ouvrirEcriture(m.ecriture_id)}
                      title="Ouvrir l’écriture"
                    >
                      <td>{m.date_ecriture}</td>
                      <td className={styles.mono}>{m.numero || '(brouillon)'}</td>
                      <td className={styles.mono}>{m.journal_code}</td>
                      <td>{m.libelle}</td>
                      <td className={styles.right}>{formatMontant(m.debit)}</td>
                      <td className={styles.right}>{formatMontant(m.credit)}</td>
                      <td className={styles.right}>{formatMontant(m.solde_cumule)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4}>
                      TOTAL de la page ({livre.devise_tenue})
                    </td>
                    <td className={styles.right}>{formatMontant(livre.total_debit_page)}</td>
                    <td className={styles.right}>{formatMontant(livre.total_credit_page)}</td>
                    <td className={styles.right}>{formatMontant(livre.solde_final_page)}</td>
                  </tr>
                </tfoot>
              </table>
            )}
          </div>

          {(pageIndex > 0 || livre?.curseur_suivant) && (
            <div className={styles.pagination}>
              <button
                type="button"
                className={styles.pageBtn}
                disabled={pageIndex === 0}
                onClick={() => setPageIndex(i => Math.max(0, i - 1))}
              >
                ← Précédent
              </button>
              <span className={styles.pageInfo}>Page {pageIndex + 1}</span>
              <button
                type="button"
                className={styles.pageBtn}
                disabled={!livre?.curseur_suivant}
                onClick={() => {
                  if (!livre?.curseur_suivant) return
                  setCurseurs(prev => {
                    const suivants = prev.slice(0, pageIndex + 1)
                    suivants.push(livre.curseur_suivant)
                    return suivants
                  })
                  setPageIndex(i => i + 1)
                }}
              >
                Suivant →
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Journal ─────────────────────────────────────────────────────── */}
      {etat === 'journal' && (
        <div className={styles.tableWrap}>
          {journalQuery.isLoading ? (
            <div className={styles.etatVide}>Chargement du journal…</div>
          ) : !journal || journal.ecritures.length === 0 ? (
            <div className={styles.etatVide}>Aucune écriture dans ce journal sur la période.</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Numéro</th>
                  <th>Libellé</th>
                  <th>Statut</th>
                  <th className={styles.right}>Débit</th>
                  <th className={styles.right}>Crédit</th>
                </tr>
              </thead>
              <tbody>
                {journal.ecritures.map(e => (
                  <tr
                    key={e.ecriture_id}
                    className={styles.rowCliquable}
                    onClick={() => ouvrirEcriture(e.ecriture_id)}
                    title="Ouvrir l’écriture"
                  >
                    <td>{e.date_ecriture}</td>
                    <td className={styles.mono}>{e.numero || '(brouillon)'}</td>
                    <td>{e.libelle}</td>
                    <td className={styles.mono}>{e.statut}</td>
                    <td className={styles.right}>{formatMontant(e.total_debit)}</td>
                    <td className={styles.right}>{formatMontant(e.total_credit)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>
                    TOTAL {journal.journal_code} ({journal.devise_tenue})
                  </td>
                  <td className={styles.right}>{formatMontant(journal.total_debit)}</td>
                  <td className={styles.right}>{formatMontant(journal.total_credit)}</td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}

      {ecritureOuverte && (
        <EcritureDetailModal
          ecriture={ecritureOuverte}
          journaux={journaux}
          exercices={exercices}
          canValidate={canValider}
          onClose={() => setEcritureOuverte(null)}
          onUpdated={setEcritureOuverte}
        />
      )}
    </div>
  )
}
