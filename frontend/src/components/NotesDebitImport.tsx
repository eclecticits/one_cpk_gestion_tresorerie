import { useMemo, useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import {
  analyserImportNotes,
  importerNotes,
  type AnalyseImport,
  type CategorieImportNotes,
  type ResultatImport,
} from '../api/notesDebit'
import { usePermissions } from '../hooks/usePermissions'
import { ApiError } from '../lib/apiClient'
import ResponsiveModal from './ResponsiveModal'
import styles from './ImportModules.module.css'
import nd from '../pages/NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

type ModeDoublons = 'ignorer' | 'importer'

interface ConfigCategorie {
  title: string
  shortTitle: string
  description: string
  required: string[]
  optional: string[]
  templateName: string
  accent: string
  example: Record<string, string | number>
}

/**
 * Mêmes onglets, même parcours que « Importer la liste nationale des
 * experts-comptables » : chaque catégorie a son modèle, sa validation, son
 * aperçu et son rapport. La différence est de portée — la liste nationale est
 * l'affaire du Conseil National, ces notes celles du seul conseil connecté.
 */
const categories: Record<CategorieImportNotes, ConfigCategorie> = {
  ec: {
    title: 'Cotisations des experts-comptables',
    shortTitle: 'Cotisations EC',
    description: 'Experts personnes physiques : en cabinet, indépendants, salariés.',
    required: ["N° d'ordre", 'Nom', 'une colonne par libellé (ex. « Cotisation 2026 »)'],
    optional: ['Pénalité AG', 'Arriérés', 'Total (contrôle)'],
    templateName: 'modele_notes_debit_ec.xlsx',
    accent: 'expertAccentIndependant',
    example: { "N° d'ordre": 'EC/18.00003', Nom: 'KABONGO Jean', 'Cotisation 2026': 600, Arriérés: 450, Total: 1050 },
  },
  sec: {
    title: "Cotisations des sociétés d'expertise comptable",
    shortTitle: 'Cotisations SEC',
    description: "Montant calculé par la Comptabilité sur le chiffre d'affaires déclaré.",
    required: ["N° d'ordre", 'Dénomination', 'une colonne par libellé (ex. « Cotisation 2026 »)'],
    optional: ['Arriérés', 'Total (contrôle)'],
    templateName: 'modele_notes_debit_sec.xlsx',
    accent: 'expertAccentSec',
    example: { "N° d'ordre": 'SEC/001', Dénomination: 'Cabinet Expert Conseil', 'Cotisation 2026': 4200, Arriérés: 1500, Total: 5700 },
  },
  penalites: {
    title: 'Pénalités',
    shortTitle: 'Pénalités',
    description: "Absences à l'Assemblée générale, aux réunions du Conseil, autres pénalités.",
    required: ["N° d'ordre", 'Nom', 'une colonne par pénalité (ex. « Pénalité AG »)'],
    optional: ['Arriérés', 'Total (contrôle)'],
    templateName: 'modele_notes_debit_penalites.xlsx',
    accent: 'expertAccentSalarie',
    example: { "N° d'ordre": 'EC/18.00003', Nom: 'KABONGO Jean', 'Pénalité AG': 100, Total: 100 },
  },
  toutes: {
    title: 'Fichier mixte',
    shortTitle: 'Toutes catégories',
    description: 'EC, SEC et pénalités dans une même feuille.',
    required: ["N° d'ordre", 'Nom', 'une colonne par libellé'],
    optional: ['Arriérés', 'Total (contrôle)'],
    templateName: 'modele_notes_debit.xlsx',
    accent: 'expertAccentNational',
    example: {
      "N° d'ordre": 'EC/18.00003',
      Nom: 'KABONGO Jean',
      'Cotisation 2026': 600,
      'Pénalité AG': 100,
      Arriérés: 450,
      Total: 1150,
    },
  },
}

interface MessageLigne {
  ligne: number
  colonne: string
  erreur: string
  code: 'ERREUR' | 'AVERTISSEMENT'
}

interface Props {
  onClose: () => void
  /** Import réussi : la page rafraîchit sa liste et peut l'ouvrir sur les notes créées. */
  onImported: (resultat: ResultatImport) => void
}

export default function NotesDebitImport({ onClose, onImported }: Props) {
  const { isAdmin } = usePermissions()
  const champFichier = useRef<HTMLInputElement>(null)
  const [categorie, setCategorie] = useState<CategorieImportNotes>('ec')
  const [fichier, setFichier] = useState<File | null>(null)
  const [analyse, setAnalyse] = useState<AnalyseImport | null>(null)
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [postes, setPostes] = useState<Record<string, number>>({})
  const [modeDoublons, setModeDoublons] = useState<ModeDoublons>('ignorer')
  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [resultat, setResultat] = useState<ResultatImport | null>(null)
  const [guide, setGuide] = useState(false)
  const [detail, setDetail] = useState(false)

  const config = categories[categorie]

  const analyserFichier = async (choisi: File, service: number | null, cat: CategorieImportNotes) => {
    setChargement(true)
    setErreur(null)
    try {
      const reponse = await analyserImportNotes(choisi, service, cat)
      setAnalyse(reponse)
      setServiceId(reponse.service_id)
      // Postes devinés (tarif, arriérés) en pré-remplissage ; un choix déjà
      // fait à l'écran survit à une nouvelle analyse.
      setPostes((avant) => {
        const suivants: Record<string, number> = {}
        for (const colonne of reponse.colonnes) {
          const poste = colonne.poste_impose ? colonne.poste_suggere_id : avant[colonne.cle] ?? colonne.poste_suggere_id
          if (poste != null && reponse.postes.some((p) => p.id === poste)) suivants[colonne.cle] = poste
        }
        return suivants
      })
    } catch (err) {
      setAnalyse(null)
      setErreur(err instanceof ApiError ? err.message : 'Impossible de lire ce fichier.')
    } finally {
      setChargement(false)
    }
  }

  const changerCategorie = (cat: CategorieImportNotes) => {
    setCategorie(cat)
    setResultat(null)
    // Le même fichier se revalide pour l'onglet choisi, comme à l'import national.
    if (fichier) void analyserFichier(fichier, serviceId, cat)
  }

  const choisirFichier = (choisi: File | undefined) => {
    if (!choisi) return
    setFichier(choisi)
    setResultat(null)
    setPostes({})
    void analyserFichier(choisi, serviceId, categorie)
  }

  const colonnesUtiles = useMemo(() => (analyse?.colonnes ?? []).filter((c) => c.nb_lignes > 0), [analyse])
  const postesManquants = colonnesUtiles.filter((c) => postes[c.cle] == null)
  const erreursColonnes = (analyse?.colonnes ?? []).filter((c) => c.erreur)
  const lignes = analyse?.lignes ?? []
  const aCreer = lignes.filter((l) => l.statut !== 'erreur' && (modeDoublons === 'importer' || !l.doublon))
  const totalACreer = aCreer.reduce((somme, l) => somme + Number(l.total), 0)
  const membresReconnus = lignes.filter((l) => l.expert).length
  // Un administrateur peut émettre hors service, comme à la saisie ; un agent de
  // plusieurs services doit dire sous lequel.
  const serviceRequis = !isAdmin && !!analyse && analyse.services.length > 1 && serviceId == null

  const messages: MessageLigne[] = useMemo(() => {
    if (!analyse) return []
    const parColonne: MessageLigne[] = analyse.colonnes.flatMap((c) => [
      ...(c.erreur ? [{ ligne: analyse.ligne_entete, colonne: c.libelle, erreur: c.erreur, code: 'ERREUR' as const }] : []),
      ...(c.avertissement
        ? [{ ligne: analyse.ligne_entete, colonne: c.libelle, erreur: c.avertissement, code: 'AVERTISSEMENT' as const }]
        : []),
    ])
    const parLigne = analyse.lignes.flatMap((l) => [
      ...l.erreurs.map((m) => ({ ligne: l.ligne, colonne: l.numero_ordre || l.nom, erreur: m, code: 'ERREUR' as const })),
      ...l.avertissements.map((m) => ({
        ligne: l.ligne,
        colonne: l.numero_ordre || l.nom,
        erreur: m,
        code: 'AVERTISSEMENT' as const,
      })),
    ])
    return [...parColonne, ...parLigne]
  }, [analyse])

  const peutImporter =
    !!fichier &&
    !!analyse &&
    !chargement &&
    !resultat &&
    aCreer.length > 0 &&
    postesManquants.length === 0 &&
    erreursColonnes.length === 0 &&
    !serviceRequis &&
    analyse.exercice_ouvert

  const lancerImport = async () => {
    if (!fichier || !peutImporter) return
    setChargement(true)
    setErreur(null)
    try {
      const reponse = await importerNotes(fichier, {
        service_id: serviceId,
        postes,
        importer_doublons: modeDoublons === 'importer',
        categorie,
      })
      setResultat(reponse)
      onImported(reponse)
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : "L'import a échoué : aucune note n'a été créée.")
    } finally {
      setChargement(false)
    }
  }

  const telechargerModele = () => {
    const feuille = XLSX.utils.json_to_sheet([config.example])
    const classeur = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(classeur, feuille, config.shortTitle.slice(0, 31))
    XLSX.writeFile(classeur, config.templateName)
  }

  const telechargerCsv = () => {
    if (!messages.length) return
    const csv = [
      ['ligne', 'code', 'colonne', 'message'],
      ...messages.map((m) => [String(m.ligne), m.code, m.colonne, m.erreur]),
    ]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `rapport_erreurs_${config.templateName.replace('.xlsx', '.csv')}`
    lien.click()
    URL.revokeObjectURL(url)
  }

  const nbErreurs = analyse?.resume.nb_erreurs ?? 0

  return (
    <ResponsiveModal
      isOpen
      onClose={onClose}
      title="Importer les notes de débit"
      size="xl"
      contentClassName={styles.expertImportModalContent}
    >
      <div className={styles.expertImportShell}>
        <div className={styles.expertImportIntro}>
          <p>
            Import propre à votre conseil : les notes créées n'appartiennent qu'à votre organisation, sur vos postes
            budgétaires, et n'apparaissent dans aucun autre conseil. Les membres sont reconnus par leur n° d'ordre dans
            la liste nationale. Chaque catégorie possède son modèle, sa validation, son aperçu et son rapport.
          </p>
        </div>

        <div className={styles.expertModuleTabs} role="tablist" aria-label="Catégorie d'import des notes de débit">
          {(Object.keys(categories) as CategorieImportNotes[]).map((cat) => (
            <button
              key={cat}
              type="button"
              role="tab"
              aria-selected={categorie === cat}
              className={`${styles.expertModuleTab} ${categorie === cat ? styles.expertModuleTabActive : ''}`}
              onClick={() => changerCategorie(cat)}
              disabled={chargement}
            >
              <strong>{categories[cat].shortTitle}</strong>
              <span>{categories[cat].description}</span>
            </button>
          ))}
        </div>

        <section className={styles.importCard}>
          <div className={styles.importCardHeader}>
            <div>
              <h3>{config.title}</h3>
              <p className={styles.expertCardHint}>{config.description}</p>
            </div>
            <span className={`${styles.expertCategoryPill} ${styles[config.accent]}`}>{config.shortTitle}</span>
          </div>
          <div className={styles.filePickerRow}>
            <label htmlFor="notes-debit-file-upload" className={styles.filePickerButton}>
              Choisir un fichier
            </label>
            <input
              id="notes-debit-file-upload"
              ref={champFichier}
              type="file"
              accept=".xlsx,.xlsm"
              onChange={(e) => choisirFichier(e.target.files?.[0])}
              disabled={chargement}
              className={styles.budgetFileInput}
            />
            <span className={styles.selectedFileName}>
              {fichier?.name || 'Aucun fichier sélectionné'}
              {chargement && !resultat ? ' — lecture…' : ''}
            </span>
          </div>
          {analyse && analyse.services.length > 1 && (
            <label className={nd.champ}>
              <span>Service émetteur</span>
              <select
                value={serviceId ?? ''}
                onChange={(e) => {
                  const suivant = e.target.value ? Number(e.target.value) : null
                  setServiceId(suivant)
                  if (fichier) void analyserFichier(fichier, suivant, categorie)
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
        </section>

        <section className={styles.importCard}>
          <h3>Gestion des conflits</h3>
          <div className={styles.expertConflictGrid}>
            <label className={`${styles.conflictChoice} ${styles.conflictUpdate}`}>
              <input
                type="radio"
                name="notesConflictMode"
                checked={modeDoublons === 'ignorer'}
                onChange={() => setModeDoublons('ignorer')}
                disabled={chargement}
              />
              <span>
                <strong>Ignorer les notes déjà émises (recommandé)</strong>
                <small>
                  Un membre qui a déjà, cette année, une note portant le même libellé n'en reçoit pas une seconde.
                </small>
              </span>
            </label>
            <label className={`${styles.conflictChoice} ${styles.conflictAdd}`}>
              <input
                type="radio"
                name="notesConflictMode"
                checked={modeDoublons === 'importer'}
                onChange={() => setModeDoublons('importer')}
                disabled={chargement}
              />
              <span>
                <strong>Créer aussi les notes déjà émises</strong>
                <small>Pour une seconde émission voulue : la dette s'ajoute à la précédente.</small>
              </span>
            </label>
          </div>
        </section>

        <section className={styles.importGridSection}>
          <div className={styles.importCard}>
            <h3>Résumé avant import</h3>
            <div className={styles.summaryGrid}>
              <span>
                Catégorie<strong>{config.shortTitle}</strong>
              </span>
              <span>
                Lignes détectées<strong>{analyse?.resume.nb_lignes ?? 0}</strong>
              </span>
              <span>
                Membres reconnus<strong>{membresReconnus}</strong>
              </span>
              <span>
                Notes à créer<strong>{aCreer.length}</strong>
              </span>
              <span>
                Total<strong>{montant(totalACreer)}</strong>
              </span>
              <span>
                dont arriérés<strong>{montant(analyse?.resume.total_arrieres ?? 0)}</strong>
              </span>
              <span>
                Mode conflit<strong>{modeDoublons === 'ignorer' ? 'Doublons ignorés' : 'Doublons créés'}</strong>
              </span>
            </div>
            {analyse && (
              <div className={styles.expertPreviewStats}>
                <span>Valides : {analyse.resume.nb_ok}</span>
                <span>À vérifier : {analyse.resume.nb_avertissements}</span>
                <span>Écartées : {nbErreurs + (modeDoublons === 'ignorer' ? analyse.resume.nb_doublons : 0)}</span>
                <span>Exercice : {analyse.exercice}</span>
              </div>
            )}
          </div>

          <div className={styles.importCard}>
            <h3>Aperçu avant import</h3>
            {lignes.length > 0 ? (
              <div className={styles.expertPreviewList}>
                {lignes.slice(0, 5).map((l) => (
                  <div className={styles.expertPreviewRow} key={l.ligne}>
                    <strong>{l.expert?.numero_ordre ?? l.numero_ordre}</strong>
                    <span>{l.expert?.nom ?? l.nom}</span>
                    <em>{montant(l.total)}</em>
                  </div>
                ))}
                {lignes.length > 5 && <p>{lignes.length - 5} ligne(s) supplémentaires.</p>}
              </div>
            ) : (
              <p className={styles.emptyPreview}>Sélectionnez un fichier Excel compatible avec la catégorie active.</p>
            )}
          </div>
        </section>

        {analyse && (
          <section className={styles.importCard}>
            <h3>Libellés et postes budgétaires</h3>
            <p className={styles.expertCardHint}>
              Chaque colonne de montants devient une ligne de la note, sous son en-tête. Le poste d'un libellé tarifé
              est fixé par le tarif réglé.
            </p>
            <div className={nd.tableContainer}>
              <table className={nd.table}>
                <thead>
                  <tr>
                    <th>Colonne</th>
                    <th className={nd.num}>Lignes</th>
                    <th className={nd.num}>Total</th>
                    <th>Tarif réglé</th>
                    <th>Poste budgétaire</th>
                  </tr>
                </thead>
                <tbody>
                  {analyse.colonnes.map((colonne) => (
                    <tr key={colonne.cle}>
                      <td>
                        <strong>{colonne.libelle}</strong>
                        {colonne.arrieres && <span className={`${nd.tag} ${nd.tagArrieres}`}>Arriérés</span>}
                        {colonne.erreur && <div className={nd.texteErreur}>{colonne.erreur}</div>}
                        {colonne.avertissement && <div className={nd.message}>{colonne.avertissement}</div>}
                      </td>
                      <td className={nd.num}>{colonne.nb_lignes}</td>
                      <td className={nd.num}>{montant(colonne.total)}</td>
                      <td>
                        {colonne.tarif ? (
                          colonne.tarif.montant ? montant(colonne.tarif.montant) : 'Montant libre'
                        ) : (
                          <span className={nd.muted}>—</span>
                        )}
                      </td>
                      <td>
                        <select
                          className={postes[colonne.cle] == null && colonne.nb_lignes > 0 ? nd.selectManquant : ''}
                          value={postes[colonne.cle] ?? ''}
                          disabled={colonne.poste_impose || chargement}
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
              <p className={styles.expertCardHint}>
                Colonnes non importées :{' '}
                {analyse.colonnes_ignorees.map((c) => `« ${c.libelle} » (${c.raison.toLowerCase()})`).join(', ')}.
              </p>
            )}
          </section>
        )}

        {guide && (
          <section className={styles.importGuide}>
            <strong>Guide d'import</strong>
            <span>Colonnes obligatoires : {config.required.join(', ')}.</span>
            <span>Colonnes optionnelles : {config.optional.join(', ')}.</span>
            <span>
              Une cellule vide ou à 0 ne crée pas de ligne. « Arriérés » est reconnue d'office ; « Total » sert de
              contrôle et n'est pas importée.
            </span>
            <span>Le fichier est validé pour la catégorie active ; les notes créées ne concernent que votre conseil.</span>
          </section>
        )}

        {(messages.length > 0 || resultat || erreur) && (
          <section
            className={`${styles.importReport} ${
              resultat ? styles.reportSuccess : erreur || nbErreurs || erreursColonnes.length ? styles.reportError : ''
            }`}
          >
            <div className={styles.reportHeader}>
              <h3>{resultat ? "Rapport d'import" : 'Validation du fichier'}</h3>
              {messages.length > 0 && (
                <button type="button" className={styles.errorDownloadBtn} onClick={telechargerCsv}>
                  Télécharger CSV
                </button>
              )}
            </div>
            {erreur && <p>{erreur}</p>}
            {resultat && (
              <>
                <p>
                  {resultat.nb_notes} note{resultat.nb_notes > 1 ? 's' : ''} de débit créée
                  {resultat.nb_notes > 1 ? 's' : ''} pour {montant(resultat.montant_total)}, dont{' '}
                  {montant(resultat.montant_arrieres)} d'arriérés.
                </p>
                <div className={styles.importStats}>
                  <span>Lignes : {analyse?.resume.nb_lignes ?? 0}</span>
                  <span>Notes créées : {resultat.nb_notes}</span>
                  <span>Écartées : {resultat.nb_lignes_ecartees}</span>
                  <span>Erreurs : {nbErreurs}</span>
                </div>
              </>
            )}
            {messages.length > 0 && (
              <div className={styles.errorList}>
                {(detail ? messages : messages.slice(0, 5)).map((m, index) => (
                  <span key={`${m.ligne}-${index}`}>
                    Ligne {m.ligne} · {m.code === 'ERREUR' ? 'Erreur' : 'À vérifier'} · {m.colonne} : {m.erreur}
                  </span>
                ))}
                {messages.length > 5 && (
                  <button type="button" className={nd.lienBtn} onClick={() => setDetail((v) => !v)}>
                    {detail ? 'Réduire' : `${messages.length - 5} message(s) supplémentaire(s) — tout afficher`}
                  </button>
                )}
              </div>
            )}
            {!resultat && postesManquants.length > 0 && (
              <p>Choisissez le poste de : {postesManquants.map((c) => `« ${c.libelle} »`).join(', ')}.</p>
            )}
            {!resultat && serviceRequis && <p>Choisissez le service émetteur.</p>}
            {analyse && !analyse.exercice_ouvert && <p>Aucun exercice budgétaire ouvert.</p>}
          </section>
        )}

        <footer className={styles.budgetImportActions}>
          <button type="button" className={styles.secondaryImportButton} onClick={telechargerModele} disabled={chargement}>
            Télécharger le modèle
          </button>
          <button type="button" className={styles.secondaryImportButton} onClick={() => setGuide((v) => !v)}>
            Guide d'import
          </button>
          <span className={styles.actionSpacer} />
          <button type="button" className={styles.cancelImportButton} onClick={onClose} disabled={chargement}>
            {resultat ? 'Fermer' : 'Annuler'}
          </button>
          {!resultat && (
            <button type="button" className={styles.primaryImportButton} onClick={() => void lancerImport()} disabled={!peutImporter}>
              {chargement && fichier && analyse
                ? 'Import en cours...'
                : `Importer ${aCreer.length} note${aCreer.length > 1 ? 's' : ''}`}
            </button>
          )}
        </footer>
      </div>
    </ResponsiveModal>
  )
}
