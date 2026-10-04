import { useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Upload, XCircle } from 'lucide-react'
import {
  analyserImportNotes,
  importerNotes,
  type AnalyseImport,
  type ResultatImport,
} from '../api/notesDebit'
import { usePermissions } from '../hooks/usePermissions'
import { ApiError } from '../lib/apiClient'
import styles from '../pages/NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

type FiltreLignes = 'toutes' | 'erreur' | 'avertissement' | 'ok'

interface Props {
  /** Après l'import : ouvrir la liste sur les notes créées. */
  onVoirNotes: (importId: string, fichier: string) => void
}

/**
 * Import Excel des notes de débit, en trois temps : fichier, contrôle, résultat.
 *
 * Le contrôle est celui du serveur, pas une copie : l'aperçu vient de
 * `/notes-debit/import/analyse`, et l'import relit le fichier pour refaire les
 * mêmes contrôles avant d'écrire. Ce que l'écran annonce est ce qui sera créé.
 */
export default function NotesDebitImport({ onVoirNotes }: Props) {
  const { isAdmin } = usePermissions()
  const champFichier = useRef<HTMLInputElement>(null)
  const [fichier, setFichier] = useState<File | null>(null)
  const [analyse, setAnalyse] = useState<AnalyseImport | null>(null)
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [postes, setPostes] = useState<Record<string, number>>({})
  const [importerDoublons, setImporterDoublons] = useState(false)
  const [filtre, setFiltre] = useState<FiltreLignes>('toutes')
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [resultat, setResultat] = useState<ResultatImport | null>(null)

  const analyserFichier = async (choisi: File, service: number | null) => {
    setChargement(true)
    setErreur(null)
    try {
      const reponse = await analyserImportNotes(choisi, service)
      setAnalyse(reponse)
      setServiceId(reponse.service_id)
      // Les postes devinés (tarif, arriérés) pré-remplissent ; un choix déjà
      // fait à l'écran est gardé quand on relance l'analyse.
      setPostes((avant) => {
        const suivants: Record<string, number> = {}
        for (const colonne of reponse.colonnes) {
          const poste = colonne.poste_impose
            ? colonne.poste_suggere_id
            : avant[colonne.cle] ?? colonne.poste_suggere_id
          if (poste != null && reponse.postes.some((p) => p.id === poste)) suivants[colonne.cle] = poste
        }
        return suivants
      })
    } catch (err) {
      setAnalyse(null)
      setErreur(err instanceof ApiError ? err.message : "Impossible de lire ce fichier.")
    } finally {
      setChargement(false)
    }
  }

  const choisirFichier = (choisi: File | undefined) => {
    if (!choisi) return
    setFichier(choisi)
    setResultat(null)
    setPostes({})
    setFiltre('toutes')
    void analyserFichier(choisi, serviceId)
  }

  const recommencer = () => {
    setFichier(null)
    setAnalyse(null)
    setResultat(null)
    setErreur(null)
    setPostes({})
    if (champFichier.current) champFichier.current.value = ''
  }

  const colonnesUtiles = useMemo(() => (analyse?.colonnes ?? []).filter((c) => c.nb_lignes > 0), [analyse])
  const postesManquants = colonnesUtiles.filter((c) => postes[c.cle] == null)
  const erreursColonnes = (analyse?.colonnes ?? []).filter((c) => c.erreur)
  const aCreer = (analyse?.lignes ?? []).filter((l) => l.statut !== 'erreur' && (importerDoublons || !l.doublon))
  const totalACreer = aCreer.reduce((somme, l) => somme + Number(l.total), 0)
  const lignesAffichees = (analyse?.lignes ?? []).filter((l) => filtre === 'toutes' || l.statut === filtre)
  // Un administrateur peut émettre hors service, comme à la saisie ; un agent de
  // plusieurs services doit dire sous lequel.
  const serviceRequis = !isAdmin && !!analyse && analyse.services.length > 1 && serviceId == null

  const lancerImport = async () => {
    if (!fichier || !analyse) return
    setChargement(true)
    setErreur(null)
    try {
      setResultat(
        await importerNotes(fichier, { service_id: serviceId, postes, importer_doublons: importerDoublons }),
      )
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "L'import a échoué : aucune note n'a été créée.")
    } finally {
      setChargement(false)
    }
  }

  if (resultat) {
    return (
      <section className={styles.card}>
        <div className={styles.resultat}>
          <CheckCircle2 size={36} className={styles.iconeSucces} aria-hidden />
          <h2>{resultat.nb_notes} note{resultat.nb_notes > 1 ? 's' : ''} de débit créée{resultat.nb_notes > 1 ? 's' : ''}</h2>
          <p>
            {montant(resultat.montant_total)} au total, dont {montant(resultat.montant_arrieres)} d'arriérés.
            {resultat.nb_lignes_ecartees > 0 &&
              ` ${resultat.nb_lignes_ecartees} ligne${resultat.nb_lignes_ecartees > 1 ? 's' : ''} du fichier écartée${resultat.nb_lignes_ecartees > 1 ? 's' : ''}.`}
          </p>
          <div className={styles.actionsLigne}>
            <button type="button" className={styles.primaryBtn} onClick={() => onVoirNotes(resultat.import_id, resultat.fichier)}>
              Voir les notes créées
            </button>
            <button type="button" className={styles.secondaryBtn} onClick={recommencer}>
              Nouvel import
            </button>
          </div>
        </div>
      </section>
    )
  }

  return (
    <div className={styles.importFlow}>
      <ol className={styles.etapes} aria-label="Étapes de l'import">
        <li className={!analyse ? styles.etapeActive : styles.etapeFaite}>1. Fichier</li>
        <li className={analyse ? styles.etapeActive : ''}>2. Contrôle</li>
        <li>3. Confirmation</li>
      </ol>

      <section className={styles.card}>
        <div className={styles.depot}>
          <FileSpreadsheet size={28} aria-hidden className={styles.iconeFichier} />
          <div className={styles.depotTexte}>
            <strong>{fichier ? fichier.name : 'Déposez le fichier Excel des notes de débit'}</strong>
            <span>
              Une ligne par membre : « N° d'ordre », « Nom », puis une colonne par libellé (« Cotisation 2026 »,
              « Pénalité AG »…) et une colonne « Arriérés ». Les montants du fichier font foi.
            </span>
          </div>
          <label className={styles.secondaryBtn}>
            <Upload size={16} aria-hidden /> {fichier ? 'Changer de fichier' : 'Choisir un fichier'}
            <input
              ref={champFichier}
              type="file"
              accept=".xlsx,.xlsm"
              className={styles.visuallyHidden}
              onChange={(e) => choisirFichier(e.target.files?.[0])}
            />
          </label>
        </div>
        {chargement && !analyse && <p className={styles.muted}>Lecture du fichier…</p>}
        {erreur && (
          <p className={styles.erreurBloc} role="alert">
            <XCircle size={16} aria-hidden /> {erreur}
          </p>
        )}
      </section>

      {analyse && (
        <>
          <section className={styles.summaryStrip} aria-label="Résumé du contrôle">
            <div className={styles.summaryChip}>
              <span>Lignes lues</span>
              <strong>{analyse.resume.nb_lignes}</strong>
            </div>
            <div className={`${styles.summaryChip} ${styles.chipOk}`}>
              <span>Valides</span>
              <strong>{analyse.resume.nb_ok}</strong>
            </div>
            <div className={`${styles.summaryChip} ${styles.chipWarn}`}>
              <span>Avertissements</span>
              <strong>{analyse.resume.nb_avertissements}</strong>
            </div>
            <div className={`${styles.summaryChip} ${styles.chipErr}`}>
              <span>Erreurs</span>
              <strong>{analyse.resume.nb_erreurs}</strong>
            </div>
            <div className={styles.summaryChip}>
              <span>Total valide</span>
              <strong>{montant(analyse.resume.total)}</strong>
            </div>
            <div className={styles.summaryChip}>
              <span>dont arriérés</span>
              <strong>{montant(analyse.resume.total_arrieres)}</strong>
            </div>
          </section>

          <section className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Libellés du fichier</h2>
              <span className={styles.muted}>
                Exercice {analyse.exercice} · en-tête lu à la ligne {analyse.ligne_entete}
              </span>
            </div>

            {analyse.services.length > 1 && (
              <label className={styles.champ}>
                <span>Service émetteur</span>
                <select
                  value={serviceId ?? ''}
                  onChange={(e) => {
                    const suivant = e.target.value ? Number(e.target.value) : null
                    setServiceId(suivant)
                    if (fichier) void analyserFichier(fichier, suivant)
                  }}
                >
                  <option value="">— Choisir —</option>
                  {analyse.services.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.libelle}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className={styles.tableContainer}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Colonne</th>
                    <th className={styles.num}>Lignes</th>
                    <th className={styles.num}>Total</th>
                    <th>Tarif réglé</th>
                    <th>Poste budgétaire</th>
                  </tr>
                </thead>
                <tbody>
                  {analyse.colonnes.map((colonne) => (
                    <tr key={colonne.cle}>
                      <td>
                        <strong>{colonne.libelle}</strong>
                        {colonne.arrieres && <span className={`${styles.tag} ${styles.tagArrieres}`}>Arriérés</span>}
                        {colonne.erreur && <div className={styles.texteErreur}>{colonne.erreur}</div>}
                      </td>
                      <td className={styles.num}>{colonne.nb_lignes}</td>
                      <td className={styles.num}>{montant(colonne.total)}</td>
                      <td>
                        {colonne.tarif ? (
                          <span>
                            {colonne.tarif.montant ? montant(colonne.tarif.montant) : 'Montant libre'}
                          </span>
                        ) : (
                          <span className={styles.muted}>—</span>
                        )}
                      </td>
                      <td>
                        <select
                          className={postes[colonne.cle] == null && colonne.nb_lignes > 0 ? styles.selectManquant : ''}
                          value={postes[colonne.cle] ?? ''}
                          disabled={colonne.poste_impose}
                          title={colonne.poste_impose ? 'Le tarif réglé fixe ce poste' : undefined}
                          aria-label={`Poste budgétaire de « ${colonne.libelle} »`}
                          onChange={(e) =>
                            setPostes((avant) => {
                              const suivants = { ...avant }
                              if (e.target.value) suivants[colonne.cle] = Number(e.target.value)
                              else delete suivants[colonne.cle]
                              return suivants
                            })
                          }
                        >
                          <option value="">— Choisir le poste —</option>
                          {analyse.postes.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.code} — {p.libelle}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {analyse.colonnes_ignorees.length > 0 && (
              <p className={styles.muted}>
                Colonnes non importées :{' '}
                {analyse.colonnes_ignorees.map((c) => `« ${c.libelle} » (${c.raison.toLowerCase()})`).join(', ')}.
              </p>
            )}
          </section>

          <section className={styles.card}>
            <div className={styles.cardHeader}>
              <h2>Contrôle ligne par ligne</h2>
              <div className={styles.filtresPuces} role="group" aria-label="Filtrer les lignes">
                {(
                  [
                    ['toutes', `Toutes (${analyse.resume.nb_lignes})`],
                    ['erreur', `Erreurs (${analyse.resume.nb_erreurs})`],
                    ['avertissement', `Avertissements (${analyse.resume.nb_avertissements})`],
                    ['ok', `Valides (${analyse.resume.nb_ok})`],
                  ] as [FiltreLignes, string][]
                ).map(([valeur, libelle]) => (
                  <button
                    key={valeur}
                    type="button"
                    aria-pressed={filtre === valeur}
                    className={filtre === valeur ? styles.puceActive : styles.puce}
                    onClick={() => setFiltre(valeur)}
                  >
                    {libelle}
                  </button>
                ))}
              </div>
            </div>
            <div className={`${styles.tableContainer} ${styles.tableHaute}`}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.num}>Ligne</th>
                    <th>Membre</th>
                    {analyse.colonnes.map((c) => (
                      <th key={c.cle} className={styles.num}>
                        {c.libelle}
                      </th>
                    ))}
                    <th className={styles.num}>Total</th>
                    <th>Contrôle</th>
                  </tr>
                </thead>
                <tbody>
                  {lignesAffichees.map((ligne) => (
                    <tr key={ligne.ligne} className={ligne.statut === 'erreur' ? styles.ligneErreur : ''}>
                      <td className={styles.num}>{ligne.ligne}</td>
                      <td>
                        <div className={styles.membre}>
                          <strong>{ligne.expert?.nom ?? (ligne.nom || '—')}</strong>
                          <small>
                            {ligne.expert?.numero_ordre ?? ligne.numero_ordre}
                            {ligne.expert?.type_ec === 'SEC' && <span className={`${styles.tag} ${styles.tagSec}`}>SEC</span>}
                          </small>
                        </div>
                      </td>
                      {analyse.colonnes.map((c) => (
                        <td key={c.cle} className={styles.num}>
                          {ligne.montants[c.cle] ? montant(ligne.montants[c.cle]) : ''}
                        </td>
                      ))}
                      <td className={`${styles.num} ${styles.fort}`}>{montant(ligne.total)}</td>
                      <td>
                        <StatutLigne statut={ligne.statut} />
                        {[...ligne.erreurs, ...ligne.avertissements].map((message) => (
                          <div key={message} className={styles.message}>
                            {message}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                  {lignesAffichees.length === 0 && (
                    <tr>
                      <td colSpan={analyse.colonnes.length + 4} className={styles.vide}>
                        Aucune ligne dans ce filtre.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className={`${styles.card} ${styles.confirmation}`}>
            {analyse.resume.nb_doublons > 0 && (
              <label className={styles.case}>
                <input
                  type="checkbox"
                  checked={importerDoublons}
                  onChange={(e) => setImporterDoublons(e.target.checked)}
                />
                Créer aussi les {analyse.resume.nb_doublons} ligne{analyse.resume.nb_doublons > 1 ? 's' : ''} déjà
                émise{analyse.resume.nb_doublons > 1 ? 's' : ''} en {analyse.exercice} (sinon elles sont écartées)
              </label>
            )}
            <div className={styles.confirmationLigne}>
              <div>
                <strong>
                  {aCreer.length} note{aCreer.length > 1 ? 's' : ''} à créer · {montant(totalACreer)}
                </strong>
                <span className={styles.muted}>
                  {' '}
                  — non payées, au nom de chaque membre. Les lignes en erreur sont écartées.
                </span>
                {postesManquants.length > 0 && (
                  <div className={styles.texteErreur}>
                    Choisissez le poste de : {postesManquants.map((c) => `« ${c.libelle} »`).join(', ')}
                  </div>
                )}
                {serviceRequis && <div className={styles.texteErreur}>Choisissez le service émetteur.</div>}
                {!analyse.exercice_ouvert && (
                  <div className={styles.texteErreur}>Aucun exercice budgétaire ouvert.</div>
                )}
              </div>
              <div className={styles.actionsLigne}>
                <button type="button" className={styles.secondaryBtn} onClick={recommencer} disabled={chargement}>
                  Annuler
                </button>
                <button
                  type="button"
                  className={styles.primaryBtn}
                  onClick={() => void lancerImport()}
                  disabled={
                    chargement ||
                    aCreer.length === 0 ||
                    postesManquants.length > 0 ||
                    erreursColonnes.length > 0 ||
                    serviceRequis ||
                    !analyse.exercice_ouvert
                  }
                >
                  {chargement ? 'Import…' : `Importer ${aCreer.length} note${aCreer.length > 1 ? 's' : ''}`}
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

function StatutLigne({ statut }: { statut: 'ok' | 'avertissement' | 'erreur' }) {
  if (statut === 'erreur')
    return (
      <span className={`${styles.badge} ${styles.badgeErr}`}>
        <XCircle size={12} aria-hidden /> Erreur
      </span>
    )
  if (statut === 'avertissement')
    return (
      <span className={`${styles.badge} ${styles.badgeWarn}`}>
        <AlertTriangle size={12} aria-hidden /> À vérifier
      </span>
    )
  return (
    <span className={`${styles.badge} ${styles.badgeOk}`}>
      <CheckCircle2 size={12} aria-hidden /> Valide
    </span>
  )
}
