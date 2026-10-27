import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, LoaderCircle, Upload, X } from 'lucide-react'
import { importerComptaPlan } from '../../api/comptabilite'
import { useToast } from '../../hooks/useToast'
import type {
  ComptaActionLignePlan,
  ComptaCompte,
  ComptaImportPlanResult,
  ComptaModeImportPlan,
} from '../../types/comptabilite'
import {
  CHAMPS_PLAN,
  exporterErreursPlan,
  exporterPlanActuel,
  libelleNature,
  libelleSens,
  lireClasseurPlan,
  telechargerModelePlan,
  type FeuillePlan,
} from '../../utils/planComptableExcel'
import styles from './ImportPlanComptableModal.module.css'

interface Props {
  comptes: ComptaCompte[]
  onClose: () => void
  onImporte: (result: ComptaImportPlanResult) => void
}

const ACTIONS: { action: ComptaActionLignePlan; libelle: string }[] = [
  { action: 'CREER', libelle: 'À créer' },
  { action: 'METTRE_A_JOUR', libelle: 'À mettre à jour' },
  { action: 'INCHANGE', libelle: 'Inchangés' },
  { action: 'IGNORE', libelle: 'Laissés tels quels' },
  { action: 'ERREUR', libelle: 'En erreur' },
]

const BADGE: Record<ComptaActionLignePlan, string> = {
  CREER: 'Création',
  METTRE_A_JOUR: 'Mise à jour',
  INCHANGE: 'Inchangé',
  IGNORE: 'Ignoré',
  ERREUR: 'Erreur',
}

const LIGNES_AFFICHEES = 300
const LIGNES_MAX = 5000
const TAILLE_MAX = 15 * 1024 * 1024
const EXTENSIONS_ACCEPTEES = /\.(xlsx|xls|csv)$/i

/**
 * Import du plan comptable depuis Excel.
 *
 * Même déroulé que la validation en lot : la simulation part d'office dès que
 * le fichier est lu, et le bouton d'import n'est actif que si elle ne relève
 * aucune erreur. Le serveur fait tout ou rien ; l'écran le montre avant.
 */
export default function ImportPlanComptableModal({ comptes, onClose, onImporte }: Props) {
  const { notifyError } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const modalRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const importEnCoursRef = useRef(false)
  const [nomFichier, setNomFichier] = useState('')
  const [feuilles, setFeuilles] = useState<FeuillePlan[]>([])
  const [feuilleNom, setFeuilleNom] = useState('')
  const [erreurLecture, setErreurLecture] = useState<string | null>(null)
  const [erreurSimulation, setErreurSimulation] = useState<string | null>(null)
  const [lectureEnCours, setLectureEnCours] = useState(false)
  const [glisserActif, setGlisserActif] = useState(false)
  const [mode, setMode] = useState<ComptaModeImportPlan>('update_existing')
  const [simulation, setSimulation] = useState<ComptaImportPlanResult | null>(null)
  const [simulationEnCours, setSimulationEnCours] = useState(false)
  const [importEnCours, setImportEnCours] = useState(false)
  const [filtre, setFiltre] = useState<ComptaActionLignePlan | 'TOUT'>('TOUT')

  const feuille = feuilles.find(f => f.nom === feuilleNom) ?? null
  importEnCoursRef.current = importEnCours

  const choisirFichier = async (file: File | undefined) => {
    if (!file || importEnCours || lectureEnCours) return
    // Un fichier refusé doit pouvoir être choisi de nouveau une fois corrigé :
    // sans remise à zéro, le sélecteur ne signale plus le même nom.
    const refuser = (message: string) => {
      setErreurLecture(message)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    if (!EXTENSIONS_ACCEPTEES.test(file.name)) {
      refuser('Format non pris en charge. Utilisez un fichier Excel (.xlsx, .xls) ou CSV (.csv).')
      return
    }
    if (file.size > TAILLE_MAX) {
      refuser('Le fichier dépasse la taille maximale de 15 Mo.')
      return
    }
    setNomFichier(file.name)
    setSimulation(null)
    setErreurLecture(null)
    setErreurSimulation(null)
    setLectureEnCours(true)
    try {
      const lues = await lireClasseurPlan(file)
      setFeuilles(lues)
      setFeuilleNom(lues[0]?.nom ?? '')
      if (lues.length === 0) {
        setErreurLecture(
          'Aucune feuille exploitable : il faut au moins une colonne « Numéro » et une colonne « Libellé ».'
        )
      }
    } catch (err: any) {
      setFeuilles([])
      setErreurLecture(err?.message || 'Lecture du fichier impossible.')
    } finally {
      setLectureEnCours(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  useEffect(() => {
    const elementPrecedent = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflowPrecedent = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()

    const gererClavier = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !importEnCoursRef.current) {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !modalRef.current) return
      const elements = Array.from(
        modalRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'
        )
      )
      if (elements.length === 0) return
      const premier = elements[0]
      const dernier = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === premier) {
        event.preventDefault()
        dernier.focus()
      } else if (!event.shiftKey && document.activeElement === dernier) {
        event.preventDefault()
        premier.focus()
      }
    }
    document.addEventListener('keydown', gererClavier)
    return () => {
      document.removeEventListener('keydown', gererClavier)
      document.body.style.overflow = overflowPrecedent
      elementPrecedent?.focus()
    }
    // La fenêtre reste montée pendant l'import ; les refs donnent toujours
    // l'état courant sans réinstaller le piège de focus à chaque rendu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!feuille) return
    let annule = false
    setSimulation(null)
    setErreurSimulation(null)
    setSimulationEnCours(true)
    setFiltre('TOUT')
    if (feuille.lignes.length > LIGNES_MAX) {
      setSimulationEnCours(false)
      setErreurSimulation(
        `La feuille contient ${feuille.lignes.length} lignes. La limite est de ${LIGNES_MAX} lignes par import.`
      )
      return
    }
    importerComptaPlan({ lignes: feuille.lignes, mode, simulation: true, nom_fichier: nomFichier })
      .then(result => {
        if (annule) return
        setSimulation(result)
        // On ouvre sur ce qui demande une action : les erreurs d'abord.
        if (result.erreurs > 0) setFiltre('ERREUR')
      })
      .catch(err => {
        if (!annule) {
          const message = err?.message || 'Erreur inattendue.'
          setSimulation(null)
          setErreurSimulation(message)
          notifyError('Simulation impossible', message)
        }
      })
      .finally(() => {
        if (!annule) setSimulationEnCours(false)
      })
    return () => {
      annule = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feuille, mode])

  const lancerImport = async () => {
    if (!feuille) return
    setImportEnCours(true)
    try {
      const result = await importerComptaPlan({
        lignes: feuille.lignes,
        mode,
        simulation: false,
        nom_fichier: nomFichier,
      })
      if (result.enregistre) {
        onImporte(result)
      } else {
        // Le plan a pu changer entre la simulation et l'import.
        setSimulation(result)
        if (result.erreurs > 0) setFiltre('ERREUR')
      }
    } catch (err: any) {
      notifyError('Import interrompu', err?.message || 'Erreur inattendue.')
    } finally {
      setImportEnCours(false)
    }
  }

  const lignesFiltrees = useMemo(
    () => (simulation?.lignes ?? []).filter(l => filtre === 'TOUT' || l.action === filtre),
    [simulation, filtre]
  )

  const aEcrire = simulation ? simulation.crees + simulation.mis_a_jour : 0
  const peutImporter =
    !!simulation && !simulationEnCours && !importEnCours && simulation.erreurs === 0 && aEcrire > 0

  const compteurs: Record<ComptaActionLignePlan, number> = simulation
    ? {
        CREER: simulation.crees,
        METTRE_A_JOUR: simulation.mis_a_jour,
        INCHANGE: simulation.inchanges,
        IGNORE: simulation.ignores,
        ERREUR: simulation.erreurs,
      }
    : { CREER: 0, METTRE_A_JOUR: 0, INCHANGE: 0, IGNORE: 0, ERREUR: 0 }

  const champsAbsents = feuille
    ? CHAMPS_PLAN.filter(c => !c.obligatoire && feuille.colonnes[c.champ] === undefined)
    : []

  return (
    <div
      className={styles.overlay}
      onMouseDown={event => {
        // Un clic à côté ne ferme que tant qu'aucun fichier n'est lu : au-delà,
        // il ferait perdre la lecture et la simulation sur un simple écart de souris.
        if (event.target === event.currentTarget && !importEnCours && !nomFichier) onClose()
      }}
    >
      <div
        ref={modalRef}
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ipc-titre"
        aria-describedby="ipc-description"
        aria-busy={lectureEnCours || simulationEnCours || importEnCours}
      >
        <header className={styles.entete}>
          <h2 id="ipc-titre">
            <FileSpreadsheet size={18} />
            Importer le plan comptable
          </h2>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.fermer}
            onClick={onClose}
            aria-label="Fermer"
            disabled={importEnCours}
          >
            <X size={18} />
          </button>
        </header>

        <div className={styles.corps}>
          {/* ── Fichier ─────────────────────────────────────────────── */}
          <div
            className={`${styles.depot} ${glisserActif ? styles.depotActif : ''} ${nomFichier ? styles.depotPret : ''}`}
            onDragEnter={event => {
              event.preventDefault()
              if (!importEnCours && !lectureEnCours) setGlisserActif(true)
            }}
            onDragLeave={event => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setGlisserActif(false)
            }}
            onDragOver={event => event.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              setGlisserActif(false)
              choisirFichier(e.dataTransfer.files?.[0])
            }}
          >
            {lectureEnCours ? (
              <LoaderCircle size={20} className={`${styles.depotIcone} ${styles.rotation}`} />
            ) : nomFichier ? (
              <CheckCircle2 size={20} className={styles.depotIcone} />
            ) : (
              <Upload size={20} className={styles.depotIcone} />
            )}
            <div className={styles.depotTexte}>
              <strong>{lectureEnCours ? 'Lecture du fichier…' : nomFichier || 'Déposez un fichier Excel ou choisissez-le'}</strong>
              <span id="ipc-description">
                Colonnes obligatoires : Numéro et Libellé. Nature, Sens et Compte parent sont déduits du
                numéro s’ils manquent.
              </span>
            </div>
            <label className={styles.choisir}>
              {nomFichier ? 'Changer de fichier' : 'Choisir un fichier'}
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={e => choisirFichier(e.target.files?.[0])}
                disabled={importEnCours || lectureEnCours}
                aria-label="Choisir un fichier de plan comptable"
              />
            </label>
          </div>

          <div className={styles.liens}>
            <button type="button" onClick={telechargerModelePlan}>
              <Download size={14} /> Télécharger le modèle
            </button>
            <button type="button" onClick={() => exporterPlanActuel(comptes)} disabled={comptes.length === 0}>
              <Download size={14} /> Exporter le plan actuel ({comptes.length} comptes) pour le compléter
            </button>
          </div>

          {erreurLecture && (
            <div className={styles.avertissement} role="alert">
              <AlertTriangle size={16} />
              <span>{erreurLecture}</span>
            </div>
          )}

          {feuille && (
            <>
              {/* ── Lecture du fichier ───────────────────────────────── */}
              <div className={styles.lecture}>
                {feuilles.length > 1 && (
                  <label className={styles.champ}>
                    <span>Feuille</span>
                    <select value={feuilleNom} onChange={e => setFeuilleNom(e.target.value)} disabled={importEnCours}>
                      {feuilles.map(f => (
                        <option key={f.nom} value={f.nom}>
                          {f.nom} — {f.lignes.length} ligne(s)
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className={styles.colonnes}>
                  {CHAMPS_PLAN.map(c => {
                    const trouvee = feuille.colonnes[c.champ] !== undefined
                    return (
                      <span
                        key={c.champ}
                        className={`${styles.puce} ${trouvee ? styles.puceTrouvee : styles.puceAbsente}`}
                        title={trouvee ? 'Colonne lue dans le fichier' : 'Colonne absente : valeur déduite ou inchangée'}
                      >
                        {c.entete}
                      </span>
                    )
                  })}
                </div>
                <p className={styles.aide}>
                  {feuille.lignes.length} ligne(s) lue(s)
                  {feuille.titresIgnores > 0 &&
                    ` · ${feuille.titresIgnores} ligne(s) sans numéro écartée(s) (titres de classe, sous-totaux)`}
                  {feuille.sansEntete && ' · aucun en-tête reconnu : colonnes A et B lues comme Numéro et Libellé'}
                  {champsAbsents.length > 0 &&
                    ` · absentes : ${champsAbsents.map(c => c.entete).join(', ')} (déduites pour les nouveaux comptes, inchangées sinon)`}
                </p>
              </div>

              {/* ── Comptes déjà dans le plan ────────────────────────── */}
              <fieldset className={styles.modes} disabled={importEnCours}>
                <legend>Comptes déjà présents dans le plan</legend>
                <label className={mode === 'update_existing' ? styles.modeActif : undefined}>
                  <input
                    type="radio"
                    name="ipc-mode"
                    checked={mode === 'update_existing'}
                    onChange={() => setMode('update_existing')}
                  />
                  <span>
                    <strong>Mettre à jour (recommandé)</strong>
                    <small>Seules les colonnes renseignées dans le fichier sont modifiées.</small>
                  </span>
                </label>
                <label className={mode === 'add_only' ? styles.modeActif : undefined}>
                  <input
                    type="radio"
                    name="ipc-mode"
                    checked={mode === 'add_only'}
                    onChange={() => setMode('add_only')}
                  />
                  <span>
                    <strong>Ajouter seulement les nouveaux</strong>
                    <small>Les comptes existants ne sont pas touchés.</small>
                  </span>
                </label>
              </fieldset>

              {/* ── Simulation ───────────────────────────────────────── */}
              {simulationEnCours && <div className={styles.attente}>Simulation en cours…</div>}

              {erreurSimulation && (
                <div className={styles.avertissement} role="alert">
                  <AlertTriangle size={16} />
                  <span><strong>Simulation impossible.</strong> {erreurSimulation}</span>
                </div>
              )}

              {simulation && !simulationEnCours && (
                <>
                  <div className={styles.resumeEntete}>
                    <strong>Résultat de la simulation</strong>
                    <button type="button" onClick={() => setFiltre('TOUT')} disabled={filtre === 'TOUT'}>
                      Tout afficher
                    </button>
                  </div>
                  <div className={styles.resume} aria-label="Filtrer les lignes">
                    {ACTIONS.filter(a => a.action !== 'IGNORE' || mode === 'add_only').map(a => (
                      <button
                        key={a.action}
                        type="button"
                        aria-pressed={filtre === a.action}
                        className={`${styles.carte} ${styles[`carte${a.action}`]} ${
                          filtre === a.action ? styles.carteChoisie : ''
                        }`}
                        onClick={() => setFiltre(filtre === a.action ? 'TOUT' : a.action)}
                      >
                        <span className={styles.chiffre}>{compteurs[a.action]}</span>
                        <span className={styles.libelleCarte}>{a.libelle}</span>
                      </button>
                    ))}
                  </div>

                  {simulation.erreurs > 0 ? (
                    <div className={styles.avertissement} role="alert">
                      <AlertTriangle size={16} />
                      <span>
                        <strong>{simulation.message}</strong> L’import est tout ou rien : aucun compte ne sera
                        enregistré tant qu’une ligne est en erreur.
                      </span>
                      <button
                        type="button"
                        className={styles.lienErreurs}
                        onClick={() => exporterErreursPlan(simulation.lignes, feuille.lignes)}
                      >
                        <Download size={14} /> Lignes en erreur (Excel)
                      </button>
                    </div>
                  ) : (
                    <div className={styles.toutBon} role="status">
                      <CheckCircle2 size={16} />
                      <span>{simulation.message}</span>
                    </div>
                  )}

                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <caption className={styles.srOnly}>Aperçu des comptes à importer</caption>
                      <thead>
                        <tr>
                          <th>Ligne</th>
                          <th>Numéro</th>
                          <th>Libellé</th>
                          <th>Nature</th>
                          <th>Sens</th>
                          <th>Parent</th>
                          <th>Résultat</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lignesFiltrees.slice(0, LIGNES_AFFICHEES).map(l => {
                          const classe = (champ: string, cle: string) =>
                            [
                              l.deduits.includes(cle) ? styles.deduit : '',
                              l.changements.includes(champ) ? styles.change : '',
                            ].join(' ')
                          return (
                            <tr key={l.ligne} className={l.action === 'ERREUR' ? styles.rowErreur : undefined}>
                              <td className={styles.mono}>{l.ligne}</td>
                              <td className={styles.mono}>{l.numero}</td>
                              <td className={classe('libelle', 'libelle')}>{l.libelle}</td>
                              <td className={classe('nature', 'nature')}>{libelleNature(l.nature)}</td>
                              <td className={classe('sens_normal', 'sens')}>{libelleSens(l.sens_normal)}</td>
                              <td className={`${styles.mono} ${classe('parent_numero', 'parent')}`}>
                                {l.parent_numero ?? ''}
                              </td>
                              <td>
                                <span className={`${styles.badge} ${styles[`badge${l.action}`]}`}>
                                  {BADGE[l.action]}
                                </span>
                                {l.message && <div className={styles.message}>{l.message}</div>}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                    {lignesFiltrees.length === 0 && <div className={styles.attente}>Aucune ligne.</div>}
                  </div>
                  <p className={styles.aide}>
                    <span className={styles.deduit}>En italique</span> : valeur déduite du numéro, à relire.{' '}
                    <span className={styles.change}>En gras</span> : valeur qui change sur un compte existant.
                    {lignesFiltrees.length > LIGNES_AFFICHEES &&
                      ` Seules les ${LIGNES_AFFICHEES} premières lignes sont affichées ; l’import porte sur toutes.`}
                  </p>
                </>
              )}
            </>
          )}
        </div>

        <footer className={styles.pied}>
          <button type="button" className={styles.annuler} onClick={onClose} disabled={importEnCours}>
            Annuler
          </button>
          <button type="button" className={styles.confirmer} onClick={lancerImport} disabled={!peutImporter}>
            {importEnCours
              ? 'Import en cours…'
              : aEcrire > 0
                ? `Importer ${aEcrire} compte${aEcrire > 1 ? 's' : ''}`
                : 'Importer'}
          </button>
        </footer>
      </div>
    </div>
  )
}
