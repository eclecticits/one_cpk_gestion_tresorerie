import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Save, Sparkles } from 'lucide-react'
import {
  enregistrerRattachementsNotesDebit,
  lireRattachementsNotesDebit,
  PERMISSION_IMPORT_NOTES_DEBIT,
  type ColonneSituation,
  type ParametresRattachements,
  type RattachementPoste,
} from '../api/notesDebit'
import { usePermissions } from '../hooks/usePermissions'
import { useToast } from '../hooks/useToast'
import { ApiError } from '../lib/apiClient'
import styles from './NotesDebitExperts.module.css'

const TOUTES = '*'

type Grille = Record<string, string>

const cle = (colonne: string, categorie: string) => `${colonne}|${categorie}`

function versGrille(lignes: RattachementPoste[]): Grille {
  return Object.fromEntries(lignes.map(l => [cle(l.colonne, l.categorie_membre), l.budget_poste_code]))
}

/**
 * Paramètres des notes de débit : le poste de recette de chaque colonne de la
 * situation des membres.
 *
 * La colonne « Toutes catégories » vaut pour chaque membre ; une catégorie n'a
 * besoin de sa propre case que si le budget lui donne un poste à part — c'est
 * le cas de la cotisation N, ventilée par catégorie dans le budget.
 */
export default function NotesDebitParametres() {
  const { hasPermission } = usePermissions()
  const peutModifier = hasPermission(PERMISSION_IMPORT_NOTES_DEBIT)
  const { notifyError, notifySuccess } = useToast()
  const [donnees, setDonnees] = useState<ParametresRattachements | null>(null)
  const [grille, setGrille] = useState<Grille>({})
  const [enregistre, setEnregistre] = useState<Grille>({})
  const [proposition, setProposition] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  const appliquer = (reponse: ParametresRattachements) => {
    setDonnees(reponse)
    const actuels = versGrille(reponse.rattachements)
    setEnregistre(actuels)
    if (reponse.rattachements.length === 0 && reponse.suggestions.length > 0) {
      setGrille(versGrille(reponse.suggestions))
      setProposition(true)
    } else {
      setGrille(actuels)
      setProposition(false)
    }
  }

  useEffect(() => {
    lireRattachementsNotesDebit()
      .then(appliquer)
      .catch(e => setErreur(e instanceof ApiError ? e.message : 'Paramètres indisponibles.'))
  }, [])

  const libellePoste = useMemo(
    () => Object.fromEntries((donnees?.postes || []).map(p => [p.code, p.libelle])),
    [donnees],
  )
  const introuvables = new Set(
    (donnees?.rattachements || []).filter(r => r.introuvable).map(r => cle(r.colonne, r.categorie_membre)),
  )
  const modifie = proposition || JSON.stringify(grille) !== JSON.stringify(enregistre)

  const sansPoste = (donnees?.colonnes || []).filter(colonne => {
    if (grille[cle(colonne.cle, TOUTES)]) return false
    return !(donnees?.categories || []).every(categorie => grille[cle(colonne.cle, categorie)])
  })

  const enregistrer = async () => {
    if (!donnees) return
    setEnvoi(true)
    try {
      const lignes: RattachementPoste[] = Object.entries(grille)
        .filter(([, code]) => code)
        .map(([k, code]) => {
          const [colonne, categorie_membre] = k.split('|')
          return { colonne: colonne as ColonneSituation, categorie_membre, budget_poste_code: code }
        })
      appliquer(await enregistrerRattachementsNotesDebit(lignes))
      notifySuccess('Rattachements enregistrés', 'Chaque colonne de la situation suit désormais ces postes.')
    } catch (e) {
      notifyError("Enregistrement impossible", e instanceof ApiError ? e.message : "L'enregistrement a échoué.")
    } finally {
      setEnvoi(false)
    }
  }

  const champ = (colonne: string, categorie: string) => {
    const k = cle(colonne, categorie)
    const valeur = grille[k] || ''
    const parDefaut = categorie !== TOUTES ? grille[cle(colonne, TOUTES)] : undefined
    const options = donnees?.postes || []
    return (
      <select
        aria-label={`Poste ${colonne} ${categorie === TOUTES ? 'toutes catégories' : categorie}`}
        value={valeur}
        disabled={!peutModifier}
        className={introuvables.has(k) ? styles.selectManquant : undefined}
        title={valeur ? libellePoste[valeur] || 'Poste introuvable dans le budget en cours' : undefined}
        onChange={event => setGrille(g => ({ ...g, [k]: event.target.value }))}
        style={{ width: '100%', minWidth: 140, padding: '6px 8px' }}
      >
        <option value="">
          {categorie === TOUTES ? '— Aucun poste —' : parDefaut ? `Comme « Toutes » (${parDefaut})` : '— Aucun poste —'}
        </option>
        {valeur && !libellePoste[valeur] && <option value={valeur}>{valeur} (introuvable)</option>}
        {options.map(p => (
          <option key={p.code} value={p.code}>{p.code} — {p.libelle}</option>
        ))}
      </select>
    )
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <h1>Paramètres notes de débit</h1>
          <p>Le poste de recette de chaque colonne de la situation des membres.</p>
        </div>
        <div className={styles.actionsLigne}>
          <Link to="/experts-comptables/notes-debit" className={styles.lienDiscret}>
            <ArrowLeft size={16} aria-hidden /> Notes de débit
          </Link>
          {peutModifier && (
            <button type="button" className={styles.primaryBtn} disabled={!modifie || envoi} onClick={() => void enregistrer()}>
              <Save size={16} aria-hidden /> {envoi ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          )}
        </div>
      </header>

      {erreur && <p className={styles.erreurBloc}>{erreur}</p>}

      {proposition && (
        <p className={styles.erreurBloc} style={{ background: '#eff6ff', borderColor: '#bfdbfe', color: '#1e40af' }}>
          <Sparkles size={16} aria-hidden /> Rien n'est encore réglé : les postes affichés sont proposés d'après les
          libellés du budget. Vérifiez-les, puis enregistrez.
        </p>
      )}

      {donnees && (
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <div>
              <h2>Rattachement au budget</h2>
              <span className={styles.muted}>
                « Toutes catégories » vaut pour chaque membre ; une catégorie ne demande sa propre case que si le
                budget lui réserve un poste. Les postes sont retenus par leur code et suivent d'un exercice à l'autre.
              </span>
            </div>
          </div>
          <div className={styles.tableContainer}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Colonne de la situation</th>
                  <th>Toutes catégories</th>
                  {donnees.categories.map(categorie => <th key={categorie}>{categorie}</th>)}
                </tr>
              </thead>
              <tbody>
                {donnees.colonnes.map(colonne => (
                  <tr key={colonne.cle}>
                    <td className={styles.nowrap}><strong>{colonne.libelle}</strong></td>
                    <td>{champ(colonne.cle, TOUTES)}</td>
                    {donnees.categories.map(categorie => <td key={categorie}>{champ(colonne.cle, categorie)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sansPoste.length > 0 && (
            <p className={styles.texteErreur} style={{ padding: '0 16px 12px' }}>
              <AlertTriangle size={14} aria-hidden /> Sans poste pour au moins une catégorie :{' '}
              {sansPoste.map(c => c.libelle).join(', ')}.
            </p>
          )}
          {introuvables.size > 0 && (
            <p className={styles.texteErreur} style={{ padding: '0 16px 12px' }}>
              Certains codes enregistrés ne désignent plus aucun poste de recette actif de l'exercice en cours :
              choisissez-en un autre.
            </p>
          )}
        </section>
      )}
    </div>
  )
}
