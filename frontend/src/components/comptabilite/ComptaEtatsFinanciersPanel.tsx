import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Lock } from 'lucide-react'
import {
  cloturerComptaExercice,
  determinerComptaResultat,
  getComptaControleBilan,
  getComptaEtat,
  reporterComptaANouveaux,
} from '../../api/comptabilite'
import { exportEtatExcel, exportEtatPDF } from '../../utils/comptaEtatsExports'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import type { ComptaExercice, TypeEtat } from '../../types/comptabilite'
import styles from './ComptaEtatsFinanciersPanel.module.css'

const ETATS: [TypeEtat, string][] = [
  ['BILAN_ACTIF', 'Bilan — Actif'],
  ['BILAN_PASSIF', 'Bilan — Passif'],
  ['RESULTAT', 'Compte de résultat'],
  ['SIG', 'SIG'],
  ['FLUX', 'Flux de trésorerie'],
]

interface Props {
  exercices: ComptaExercice[]
  canCloturer: boolean
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
 * États financiers et clôture d'exercice.
 *
 * Ces états ne retiennent que les écritures validées. Comme le moteur de
 * génération produit des BROUILLONS, une organisation qui n'a rien validé
 * verra des états vides : l'écran l'explique plutôt que de laisser croire à
 * une panne.
 */
export default function ComptaEtatsFinanciersPanel({ exercices, canCloturer }: Props) {
  const queryClient = useQueryClient()
  const { notifyError, notifySuccess } = useToast()

  const [typeEtat, setTypeEtat] = useState<TypeEtat>('BILAN_ACTIF')
  const [exerciceId, setExerciceId] = useState<number | ''>(exercices[0]?.id ?? '')
  const [dateArrete, setDateArrete] = useState('')
  const [inclureBrouillons, setInclureBrouillons] = useState(false)
  const [exerciceSuivantId, setExerciceSuivantId] = useState<number | ''>('')

  const filtres = {
    exercice_id: exerciceId || undefined,
    date_arrete: dateArrete || undefined,
    inclure_brouillons: inclureBrouillons || undefined,
  }
  const cleFiltres = [exerciceId, dateArrete, inclureBrouillons] as const

  const etatQuery = useQuery({
    queryKey: ['compta-etat', typeEtat, ...cleFiltres],
    queryFn: () => getComptaEtat(typeEtat, filtres),
    enabled: exerciceId !== '',
  })

  const controleQuery = useQuery({
    queryKey: ['compta-controle-bilan', ...cleFiltres],
    queryFn: () => getComptaControleBilan(filtres),
    enabled: exerciceId !== '',
  })

  const exerciceCourant = exercices.find(e => e.id === exerciceId)
  const invalider = () => {
    queryClient.invalidateQueries({ queryKey: ['compta-etat'] })
    queryClient.invalidateQueries({ queryKey: ['compta-controle-bilan'] })
    queryClient.invalidateQueries({ queryKey: ['compta-referentiel'] })
    queryClient.invalidateQueries({ queryKey: ['compta-ecritures'] })
  }

  const resultatMutation = useMutation({
    mutationFn: () => determinerComptaResultat(Number(exerciceId)),
    onSuccess: result => {
      invalider()
      notifySuccess(
        result.deja_fait ? 'Résultat déjà déterminé' : 'Résultat déterminé',
        result.resultat != null
          ? `Résultat de l’exercice : ${formatMontant(result.resultat)}`
          : 'Les comptes de charges et de produits sont soldés.'
      )
    },
    onError: (err: any) => notifyError('Impossible', err?.message || 'Échec de l’opération.'),
  })

  const clotureMutation = useMutation({
    mutationFn: () => cloturerComptaExercice(Number(exerciceId)),
    onSuccess: result => {
      invalider()
      notifySuccess(
        result.deja_cloture ? 'Exercice déjà clôturé' : 'Exercice clôturé',
        `${result.ecritures_cloturees} écriture(s) figée(s). Plus aucune saisie n’est possible.`
      )
    },
    onError: (err: any) => notifyError('Clôture refusée', err?.message || 'Échec de l’opération.'),
  })

  const aNouveauxMutation = useMutation({
    mutationFn: () => reporterComptaANouveaux(Number(exerciceId), Number(exerciceSuivantId)),
    onSuccess: result => {
      invalider()
      notifySuccess(
        result.deja_fait ? 'À-nouveaux déjà reportés' : 'À-nouveaux reportés',
        `${result.nb_comptes} compte(s) repris sur l’exercice suivant.`
      )
    },
    onError: (err: any) => notifyError('Report refusé', err?.message || 'Échec de l’opération.'),
  })

  const etat = etatQuery.data
  const controle = controleQuery.data
  const avecAmortissement = typeEtat === 'BILAN_ACTIF'

  return (
    <div className={styles.panel}>
      <div className={styles.etatSelector} role="tablist">
        {ETATS.map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={typeEtat === cle}
            className={`${styles.etatBtn} ${typeEtat === cle ? styles.etatBtnActive : ''}`}
            onClick={() => setTypeEtat(cle)}
          >
            {libelle}
          </button>
        ))}
      </div>

      <div className={styles.filtres}>
        <div className={styles.filtre}>
          <label htmlFor="ef-exercice">Exercice</label>
          <select
            id="ef-exercice"
            value={exerciceId}
            onChange={e => setExerciceId(e.target.value ? Number(e.target.value) : '')}
          >
            {exercices.map(ex => (
              <option key={ex.id} value={ex.id}>
                {ex.code} ({ex.statut.toLowerCase()})
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filtre}>
          <label htmlFor="ef-date">Arrêté au</label>
          <input
            id="ef-date"
            type="date"
            value={dateArrete}
            onChange={e => setDateArrete(e.target.value)}
          />
        </div>
        <label className={styles.checkboxFiltre} htmlFor="ef-brouillons">
          <input
            id="ef-brouillons"
            type="checkbox"
            checked={inclureBrouillons}
            onChange={e => setInclureBrouillons(e.target.checked)}
          />
          Inclure les brouillons (simulation)
        </label>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.exportBtn}
            disabled={!etat}
            onClick={() => etat && exportEtatPDF(etat)}
          >
            <Download size={15} /> PDF
          </button>
          <button
            type="button"
            className={styles.exportBtn}
            disabled={!etat}
            onClick={() => {
              if (!etat) return
              exportEtatExcel(etat).catch((err: any) =>
                notifyError('Export impossible', err?.message || 'Une erreur est survenue.'),
              )
            }}
          >
            <FileSpreadsheet size={15} /> Excel
          </button>
        </div>
      </div>

      {inclureBrouillons && (
        <div className={styles.alerte}>
          <AlertTriangle size={17} />
          <span>
            <strong>Simulation</strong> — cet état inclut des écritures au brouillon. Il n’a pas de
            valeur comptable officielle.
          </span>
        </div>
      )}

      {/* Contrôle d'équilibre : la vérification qui prouve que le paramétrage
          des états couvre bien tous les comptes mouvementés. */}
      {controle && (
        <div className={controle.equilibre ? styles.alerteOk : styles.alerteGrave}>
          {controle.equilibre ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
          <span>
            {controle.equilibre ? (
              <>
                <strong>Bilan équilibré</strong> — actif = passif ={' '}
                {formatMontant(controle.total_actif)}.
              </>
            ) : (
              <>
                <strong>Bilan déséquilibré</strong> — actif {formatMontant(controle.total_actif)} ≠
                passif {formatMontant(controle.total_passif)} (écart {formatMontant(controle.ecart)}).
                {' '}Tant que le résultat de l’exercice n’a pas été déterminé, c’est normal. Sinon,
                la cause la plus fréquente est un compte mouvementé qui n’entre dans aucun poste.
                {controle.comptes_non_couverts.length > 0 && (
                  <>
                    {' '}Comptes concernés :{' '}
                    <span className={styles.mono}>
                      {controle.comptes_non_couverts.join(', ')}
                    </span>
                  </>
                )}
              </>
            )}
          </span>
        </div>
      )}

      {etat && etat.comptes_non_couverts.length > 0 && (
        <div className={styles.alerte}>
          <AlertTriangle size={17} />
          <span>
            <strong>
              {etat.comptes_non_couverts.length} compte(s) hors de cet état
            </strong>{' '}
            — normal s’ils relèvent d’un autre état (la caisse n’a rien à faire au compte de
            résultat), à corriger dans le paramétrage s’ils n’apparaissent nulle part :{' '}
            <span className={styles.mono}>{etat.comptes_non_couverts.join(', ')}</span>
          </span>
        </div>
      )}

      <div className={styles.tableWrap}>
        {etatQuery.isLoading ? (
          <div className={styles.etatVide}>Calcul de l’état…</div>
        ) : etatQuery.isError ? (
          <div className={styles.etatVide}>
            {(etatQuery.error as any)?.message || 'Impossible de calculer cet état.'}
          </div>
        ) : !etat || etat.lignes.every(l => toNumber(l.net) === 0) ? (
          <div className={styles.etatVide}>
            Aucun montant sur cet état.
            {!inclureBrouillons && (
              <p className={styles.etatVideAide}>
                Les écritures générées automatiquement restent au brouillon jusqu’à leur validation,
                et les états ne retiennent que les écritures validées.
              </p>
            )}
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Poste</th>
                {avecAmortissement && <th className={styles.right}>Brut</th>}
                {avecAmortissement && <th className={styles.right}>Amort./Dépréc.</th>}
                <th className={styles.right}>{avecAmortissement ? 'Net' : 'Montant'}</th>
              </tr>
            </thead>
            <tbody>
              {etat.lignes.map(ligne => (
                <tr
                  key={ligne.poste_id}
                  className={ligne.est_total ? styles.rowTotal : undefined}
                >
                  <td style={{ paddingLeft: `${14 + Math.max(0, ligne.niveau - 1) * 20}px` }}>
                    {ligne.libelle}
                  </td>
                  {avecAmortissement && (
                    <td className={styles.right}>{formatMontant(ligne.brut)}</td>
                  )}
                  {avecAmortissement && (
                    <td className={styles.right}>{formatMontant(ligne.amortissement)}</td>
                  )}
                  <td className={styles.right}>{formatMontant(ligne.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Clôture d'exercice ──────────────────────────────────────────── */}
      {canCloturer && exerciceCourant && (
        <section className={styles.cloture}>
          <header>
            <h3>
              <Lock size={16} /> Clôture de l’exercice {exerciceCourant.code}
            </h3>
            <p>
              Trois opérations à mener dans l’ordre. Chacune est rejouable sans risque : si elle a
              déjà été faite, elle ne fait rien.
            </p>
          </header>

          <ol className={styles.etapes}>
            <li>
              <div>
                <strong>Déterminer le résultat</strong>
                <p>
                  Solde les comptes de charges et de produits par le compte de résultat. Le bilan
                  ne peut pas être équilibré avant cette étape.
                </p>
              </div>
              <button
                type="button"
                className={styles.etapeBtn}
                disabled={resultatMutation.isPending || exerciceCourant.statut !== 'OUVERT'}
                onClick={() => resultatMutation.mutate()}
              >
                {resultatMutation.isPending ? 'En cours…' : 'Déterminer'}
              </button>
            </li>
            <li>
              <div>
                <strong>Clôturer</strong>
                <p>
                  Fige l’exercice : plus aucune écriture ne pourra y être saisie ni modifiée.
                  Refusé s’il reste des brouillons.
                </p>
              </div>
              <button
                type="button"
                className={styles.etapeBtn}
                disabled={clotureMutation.isPending || exerciceCourant.statut !== 'OUVERT'}
                onClick={() => clotureMutation.mutate()}
              >
                {clotureMutation.isPending ? 'En cours…' : 'Clôturer'}
              </button>
            </li>
            <li>
              <div>
                <strong>Reporter les à-nouveaux</strong>
                <p>Reprend les soldes de bilan sur l’exercice suivant, au journal AN.</p>
                <select
                  aria-label="Exercice de destination"
                  className={styles.etapeSelect}
                  value={exerciceSuivantId}
                  onChange={e => setExerciceSuivantId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">— Exercice de destination —</option>
                  {exercices
                    .filter(ex => ex.id !== exerciceId)
                    .map(ex => (
                      <option key={ex.id} value={ex.id}>
                        {ex.code}
                      </option>
                    ))}
                </select>
              </div>
              <button
                type="button"
                className={styles.etapeBtn}
                disabled={
                  aNouveauxMutation.isPending ||
                  exerciceSuivantId === '' ||
                  exerciceCourant.statut !== 'CLOTURE'
                }
                onClick={() => aNouveauxMutation.mutate()}
              >
                {aNouveauxMutation.isPending ? 'En cours…' : 'Reporter'}
              </button>
            </li>
          </ol>
        </section>
      )}
    </div>
  )
}
