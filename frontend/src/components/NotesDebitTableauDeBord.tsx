import { useEffect, useState, type ReactNode } from 'react'
import { AlertTriangle, CalendarClock, CheckCircle2, FileSpreadsheet, FileText } from 'lucide-react'
import { LIBELLE_TRANCHE } from '../api/creances'
import { tableauDeBordNotes, type StatutNotes, type TableauDeBordNotes } from '../api/notesDebit'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../hooks/useToast'
import { ApiError } from '../lib/apiClient'
import styles from '../pages/NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(
    Number(valeur) || 0,
  )

export interface FiltreListe {
  statut?: StatutNotes
  type_client?: string
  q?: string
}

interface Props {
  /** Un indicateur, une ligne : ouvrir la liste déjà filtrée sur ce qu'il compte. */
  onOuvrirListe: (filtre: FiltreListe) => void
}

const LIBELLE_TYPE: Record<string, string> = { expert_comptable: 'Experts-comptables', sec: 'SEC' }
const JOUR = 86_400_000

/** Jours restants jusqu'à une date (fin de journée), négatif une fois passée. */
const joursAvant = (echeance: Date) => Math.ceil((echeance.getTime() + JOUR - Date.now()) / JOUR) - 1

/**
 * Tableau de bord du recouvrement : ce qui a été émis, ce qui est rentré, ce qui
 * reste — et qui le doit. Chaque chiffre mène à la liste qui le compose.
 *
 * Graphiques en barres horizontales d'une seule teinte, libellé et valeur écrits
 * en toutes lettres à côté : la couleur ne porte jamais seule l'information, et
 * chaque bloc se lit comme le tableau qu'il est.
 */
export default function NotesDebitTableauDeBord({ onOuvrirListe }: Props) {
  const anneeCourante = new Date().getFullYear()
  const [annee, setAnnee] = useState(anneeCourante)
  const [donnees, setDonnees] = useState<TableauDeBordNotes | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    let actif = true
    setErreur(null)
    tableauDeBordNotes(annee)
      .then((d) => actif && setDonnees(d))
      .catch(
        (err) =>
          actif && setErreur(err instanceof ApiError ? err.message : 'Impossible de charger le tableau de bord.'),
      )
    return () => {
      actif = false
    }
  }, [annee])

  const { user } = useAuth()
  const { notifyError } = useToast()
  const [export_, setExport] = useState<'pdf' | 'excel' | null>(null)

  const exporter = async (formatExport: 'pdf' | 'excel') => {
    if (!donnees) return
    setExport(formatExport)
    try {
      const mod = await import('../utils/exportNotesDebit')
      if (formatExport === 'pdf') await mod.exporterTableauDeBordPDF(donnees)
      else
        await mod.exporterTableauDeBordExcel(donnees, user?.organisation_name || user?.organisation_slug || 'ONEC')
    } catch {
      notifyError('Export', "Impossible d'exporter le tableau de bord.")
    } finally {
      setExport(null)
    }
  }

  const kpi = donnees?.kpi
  const maxType = Math.max(1, ...(donnees?.par_type ?? []).map((t) => Number(t.emis)))
  const maxAge = Math.max(1, ...(donnees?.anciennete ?? []).map((t) => Number(t.reste)))
  const maxLibelle = Math.max(1, ...(donnees?.par_libelle ?? []).map((l) => Number(l.emis)))

  return (
    <div className={styles.bord}>
      <div className={styles.bordEntete}>
        <label className={styles.champLigne}>
          Exercice
          <select value={annee} onChange={(e) => setAnnee(Number(e.target.value))}>
            {[0, 1, 2, 3].map((d) => (
              <option key={d} value={anneeCourante - d}>
                {anneeCourante - d}
              </option>
            ))}
          </select>
        </label>
        <CompteARebours annee={annee} />
        <div className={styles.exports}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('pdf')}
            disabled={!donnees || donnees.annee !== annee || export_ !== null}
            title={`Exporter le tableau de bord ${annee} en PDF`}
          >
            <FileText size={16} aria-hidden /> {export_ === 'pdf' ? 'Export…' : 'PDF'}
          </button>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void exporter('excel')}
            disabled={!donnees || donnees.annee !== annee || export_ !== null}
            title={`Exporter le tableau de bord ${annee} en Excel`}
          >
            <FileSpreadsheet size={16} aria-hidden /> {export_ === 'excel' ? 'Export…' : 'Excel'}
          </button>
        </div>
      </div>

      {erreur && (
        <p className={styles.erreurBloc} role="alert">
          {erreur}
        </p>
      )}

      <section className={styles.kpis} aria-label="Indicateurs du recouvrement">
        <Kpi
          libelle="Émis"
          valeur={kpi ? montant(kpi.emis) : '…'}
          detail={kpi ? `${kpi.nb_notes} note${kpi.nb_notes > 1 ? 's' : ''} en ${annee}` : ''}
          onClick={() => onOuvrirListe({ statut: 'toutes' })}
        />
        <Kpi
          libelle="Encaissé"
          valeur={kpi ? montant(kpi.encaisse) : '…'}
          detail="sur les notes de l'exercice"
          ton="ok"
          onClick={() => onOuvrirListe({ statut: 'soldees' })}
        />
        <Kpi
          libelle="Reste à recouvrer"
          valeur={kpi ? montant(kpi.reste_total) : '…'}
          detail={
            kpi && Number(kpi.arrieres_anterieurs) > 0
              ? `dont ${montant(kpi.arrieres_anterieurs)} d'exercices antérieurs`
              : 'arriérés compris'
          }
          ton="err"
          onClick={() => onOuvrirListe({ statut: 'impayees' })}
        />
        <Kpi
          libelle="Taux de recouvrement"
          valeur={kpi ? `${kpi.taux_recouvrement.toLocaleString('fr-FR')} %` : '…'}
          detail={
            <span className={styles.jauge} aria-hidden>
              <span style={{ width: `${Math.min(100, kpi?.taux_recouvrement ?? 0)}%` }} />
            </span>
          }
        />
        <Kpi
          libelle="Pénalités dues"
          valeur={kpi ? montant(kpi.penalites_dues) : '…'}
          detail="part non réglée des pénalités"
          ton="warn"
          onClick={() => onOuvrirListe({ statut: 'impayees', q: 'Pénalit' })}
        />
        <Kpi
          libelle={`Non en règle — Tableau ${annee + 1}`}
          valeur={kpi ? String(kpi.membres_non_en_regle) : '…'}
          detail="membres avec un reste dû"
          ton="err"
          onClick={() => onOuvrirListe({ statut: 'impayees' })}
        />
      </section>

      <div className={styles.bordGrille}>
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2>Recouvrement par type de membre</h2>
            <span className={styles.muted}>encaissé sur émis</span>
          </div>
          {(donnees?.par_type ?? []).length === 0 && <p className={styles.muted}>Aucune note émise en {annee}.</p>}
          <ul className={styles.barres}>
            {(donnees?.par_type ?? []).map((t) => (
              <li key={t.type_client}>
                <button
                  type="button"
                  className={styles.barreLigne}
                  onClick={() => onOuvrirListe({ statut: 'impayees', type_client: t.type_client })}
                  title={`${LIBELLE_TYPE[t.type_client]} : ${montant(t.encaisse)} encaissés sur ${montant(t.emis)} émis (${t.taux} %), ${montant(t.reste)} restent dus`}
                >
                  <span className={styles.barreLibelle}>{LIBELLE_TYPE[t.type_client] ?? t.type_client}</span>
                  <span className={styles.barrePiste} style={{ width: `${(Number(t.emis) / maxType) * 100}%` }}>
                    <span
                      className={styles.barreRemplie}
                      style={{ width: `${Number(t.emis) > 0 ? (Number(t.encaisse) / Number(t.emis)) * 100 : 0}%` }}
                    />
                  </span>
                  <span className={styles.barreValeur}>
                    {montant(t.encaisse)} / {montant(t.emis)} · <strong>{t.taux.toLocaleString('fr-FR')} %</strong>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2>Ancienneté du reste dû</h2>
            <span className={styles.muted}>depuis l'émission</span>
          </div>
          <ul className={styles.barres}>
            {(donnees?.anciennete ?? []).map((t) => (
              <li key={t.tranche} className={styles.barreLigne} title={`${t.nb} note(s), ${montant(t.reste)}`}>
                <span className={styles.barreLibelle}>{LIBELLE_TRANCHE[t.tranche]}</span>
                <span className={styles.barreZone}>
                  <span className={styles.barrePleine} style={{ width: `${(Number(t.reste) / maxAge) * 100}%` }} />
                </span>
                <span className={styles.barreValeur}>
                  {montant(t.reste)} · {t.nb} note{t.nb > 1 ? 's' : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2>Émis par libellé</h2>
            <span className={styles.muted}>{annee}</span>
          </div>
          {(donnees?.par_libelle ?? []).length === 0 && <p className={styles.muted}>Aucune ligne émise.</p>}
          <ul className={styles.barres}>
            {(donnees?.par_libelle ?? []).map((l) => (
              <li
                key={l.libelle}
                className={styles.barreLigne}
                title={`${l.libelle} : ${montant(l.emis)} sur ${l.nb} note(s)`}
              >
                <span className={styles.barreLibelle}>{l.libelle}</span>
                <span className={styles.barreZone}>
                  <span className={styles.barrePleine} style={{ width: `${(Number(l.emis) / maxLibelle) * 100}%` }} />
                </span>
                <span className={styles.barreValeur}>{montant(l.emis)}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2>Principaux débiteurs</h2>
            <span className={styles.muted}>reste dû, arriérés compris</span>
          </div>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Membre</th>
                <th className={styles.num}>Notes</th>
                <th className={styles.num}>Reste dû</th>
              </tr>
            </thead>
            <tbody>
              {(donnees?.top_debiteurs ?? []).map((d) => (
                <tr
                  key={d.expert_id}
                  className={styles.ligneCliquable}
                  onClick={() => onOuvrirListe({ statut: 'impayees', q: d.numero_ordre })}
                >
                  <td>
                    <div className={styles.membre}>
                      <strong>{d.nom}</strong>
                      <small>
                        {d.numero_ordre}
                        {d.type_ec === 'SEC' && <span className={`${styles.tag} ${styles.tagSec}`}>SEC</span>}
                      </small>
                    </div>
                  </td>
                  <td className={styles.num}>{d.nb_notes}</td>
                  <td className={`${styles.num} ${styles.fort}`}>{montant(d.reste)}</td>
                </tr>
              ))}
              {donnees && donnees.top_debiteurs.length === 0 && (
                <tr>
                  <td colSpan={3} className={styles.vide}>
                    Aucun débiteur : tout est soldé.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>

      <section className={styles.card}>
        <div className={styles.cardHeader}>
          <h2>Par province</h2>
          <span className={styles.muted}>province de rattachement du membre · notes de {annee}</span>
        </div>
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Province</th>
                <th className={styles.num}>Notes</th>
                <th className={styles.num}>Émis</th>
                <th className={styles.num}>Encaissé</th>
                <th className={styles.num}>Reste</th>
                <th>Taux</th>
              </tr>
            </thead>
            <tbody>
              {(donnees?.par_province ?? []).map((p) => (
                <tr key={p.province}>
                  <td className={styles.fort}>{p.province}</td>
                  <td className={styles.num}>{p.nb}</td>
                  <td className={styles.num}>{montant(p.emis)}</td>
                  <td className={styles.num}>{montant(p.encaisse)}</td>
                  <td className={`${styles.num} ${styles.fort}`}>{montant(p.reste)}</td>
                  <td>
                    <span className={styles.tauxCellule}>
                      <span className={styles.jauge} aria-hidden>
                        <span style={{ width: `${Math.min(100, p.taux)}%` }} />
                      </span>
                      {p.taux.toLocaleString('fr-FR')} %
                    </span>
                  </td>
                </tr>
              ))}
              {donnees && donnees.par_province.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.vide}>
                    Aucune note émise en {annee}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function Kpi({
  libelle,
  valeur,
  detail,
  ton,
  onClick,
}: {
  libelle: string
  valeur: string
  detail: ReactNode
  ton?: 'ok' | 'warn' | 'err'
  onClick?: () => void
}) {
  const classe = `${styles.kpi} ${ton === 'ok' ? styles.chipOk : ton === 'warn' ? styles.chipWarn : ton === 'err' ? styles.chipErr : ''}`
  const contenu = (
    <>
      <span className={styles.kpiLibelle}>{libelle}</span>
      <strong className={styles.kpiValeur}>{valeur}</strong>
      <span className={styles.kpiDetail}>{detail}</span>
    </>
  )
  return onClick ? (
    <button type="button" className={`${classe} ${styles.kpiCliquable}`} onClick={onClick}>
      {contenu}
    </button>
  ) : (
    <div className={classe}>{contenu}</div>
  )
}

/**
 * Les deux échéances qui comptent : 31 octobre (cotisations, art. 112 du RI) et
 * 31 décembre (inscription au Tableau suivant, art. 12). Le texte dit toujours
 * le nombre de jours : la couleur n'est qu'un renfort.
 */
function CompteARebours({ annee }: { annee: number }) {
  const cotisations = joursAvant(new Date(annee, 9, 31))
  const tableau = joursAvant(new Date(annee, 11, 31))
  const ton = cotisations > 30 ? styles.reboursInfo : cotisations >= 0 ? styles.reboursWarn : styles.reboursErr
  const Icone = tableau < 0 ? CheckCircle2 : cotisations < 0 ? AlertTriangle : CalendarClock
  return (
    <p className={`${styles.rebours} ${tableau < 0 ? styles.reboursInfo : ton}`} role="status">
      <Icone size={16} aria-hidden className={styles.reboursIcone} />
      {/* Un seul bloc de texte : dans le flex, chaque <strong> deviendrait une
          colonne et « J-27 » se couperait en deux au téléphone. */}
      <span>
        {tableau < 0 ? (
          <>Exercice {annee} clos : échéances passées.</>
        ) : cotisations >= 0 ? (
          <>
            Cotisations : <strong className={styles.nowrap}>J-{cotisations}</strong> (31/10/{annee}) · Inscription au
            Tableau {annee + 1} : <strong className={styles.nowrap}>J-{tableau}</strong> (31/12)
          </>
        ) : (
          <>
            Échéance des cotisations dépassée de {-cotisations} j · Inscription au Tableau {annee + 1} :{' '}
            <strong className={styles.nowrap}>J-{tableau}</strong> (31/12)
          </>
        )}
      </span>
    </p>
  )
}
