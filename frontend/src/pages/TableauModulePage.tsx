import { Fragment, useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AlertTriangle, BarChart2, Bot, CheckCircle2, ChevronLeft, ChevronRight, Download, FileSpreadsheet, FileText, GitCompare, Layers, Pencil, RefreshCw, Save, Search, Send, Settings, Table2, UserX, X, XCircle } from 'lucide-react'
import TableauAssistantChat from '../components/TableauAssistantChat'
import SortieMembreModal, { type MembreSortie } from '../components/SortieMembreModal'
import ReleveSituationModal, { type MembreReleve } from '../components/ReleveSituationModal'
import RelevesLotModal from '../components/RelevesLotModal'
import ImportsParSource from '../components/ImportsParSource'
import TableauDashboardCharts from '../components/TableauDashboardCharts'
import BackButton from '../components/BackButton'
import { ApiError } from '../lib/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { useAuth } from '../contexts/AuthContext'
import {
  compareTableauExercices,
  correctTableauDossier,
  getTableauAnalyse,
  generateTableauPV,
  generateTableauReport,
  getTableauBase,
  getTableauDerniersReleves,
  getTableauReglages,
  listTableauAudit,
  TABLEAU_CATEGORIES,
  LIBELLES_SITUATION_SORTIE,
  type TableauDernierReleve,
  type TableauSortie,
  runTableauAnalyseBase,
  getTableauStats,
  listTableauAnomalies,
  listTableauImports,
  listTableauReports,
  runTableauAnalyse,
  updateTableauReglages,
  downloadTableauExport,
  downloadTableauRapportComplet,
  type TableauAuditEntry,
  type TableauReglages,
  type TableauAnalyse,
  type TableauBase,
  type TableauAnomalie,
  type TableauComparison,
  type CritereTableau,
  type DefinitionsCategorie,
  type FiltresRegles,
  type ModeCritere,
  type TableauCotisationNotes,
  type TableauDossier,
  type TableauImport,
  type TableauReport,
  type TableauStats,
} from '../api/tableau'
import styles from './TableauModulePage.module.css'

type TabKey = 'dashboard' | 'base' | 'import' | 'analyse' | 'anomalies' | 'comparaison' | 'rapports' | 'reglages' | 'journal'

/** Chaque écran du module a son adresse : le menu de gauche y mène, et un lien
 *  vers une anomalie ou un rapport reste partageable. */
const CHEMINS: Record<TabKey, string> = {
  dashboard: '/tableau',
  base: '/tableau/base',
  import: '/tableau/imports',
  analyse: '/tableau/analyse',
  anomalies: '/tableau/anomalies',
  comparaison: '/tableau/comparaison',
  rapports: '/tableau/rapports',
  reglages: '/tableau/reglages',
  journal: '/tableau/journal',
}
const ONGLETS: Record<string, TabKey> = Object.fromEntries(
  Object.entries(CHEMINS).map(([onglet, chemin]) => [chemin, onglet as TabKey]),
)

const baseTableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'separate',
  borderSpacing: 0,
  fontSize: '13px',
  background: '#fff',
  // Chiffres à chasse fixe : rangs et NHV restent alignés d'une ligne à l'autre.
  fontVariantNumeric: 'tabular-nums',
}

const baseThStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  borderBottom: '1px solid #e5e7eb',
  color: '#6b7280',
  fontWeight: 600,
  whiteSpace: 'nowrap',
  // L'en-tête reste visible quand on fait défiler une longue page de membres.
  position: 'sticky',
  top: 0,
  zIndex: 1,
  background: '#f9fafb',
}

const baseTdStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderBottom: '1px solid #f1f2f4',
  color: '#374151',
}

const TITRES: Record<TabKey, string> = {
  dashboard: "Tableau de l'Ordre",
  base: 'Base Tableau',
  import: 'Imports Excel',
  analyse: 'Analyse réglementaire',
  anomalies: 'Anomalies',
  comparaison: 'Comparaison d\'exercices',
  rapports: 'Rapports & procès-verbaux',
  reglages: 'Règles de délibération',
  journal: 'Journal des actions',
}

const LIBELLES_AUDIT: Record<string, string> = {
  'tableau.dossier.correct': 'Correction d\'un dossier',
  'tableau.decision.create': 'Décision de commission',
  'tableau.assistant.chat': 'Question à l\'assistant',
}

/** Ce que l'entrée dit en une ligne, sans étaler le contenu du journal. */
function resumerAudit(entree: TableauAuditEntry): string {
  const meta = entree.metadata_json || {}
  const morceaux: string[] = []
  if (typeof meta.numero_ordre === 'string') morceaux.push(meta.numero_ordre)
  if (Array.isArray(meta.champs) && meta.champs.length) morceaux.push(`champs : ${meta.champs.join(', ')}`)
  if (typeof meta.decision === 'string') morceaux.push(meta.decision)
  if (typeof meta.motif === 'string') morceaux.push(`« ${meta.motif} »`)
  if (Array.isArray(meta.outils) && meta.outils.length) morceaux.push(`outils : ${meta.outils.join(', ')}`)
  return morceaux.join(' · ') || '—'
}

// Couleur du NHV d'après le réglage « Heures de formation min » : bleu à partir du
// minimum, rouge sous 60 % de ce minimum, sans couleur entre les deux.
const PART_NHV_ROUGE = 0.6
const COULEUR_NHV_ATTEINT = '#1d4ed8'
const COULEUR_NHV_FAIBLE = '#b91c1c'

function styleNhv(valeur: number | null | undefined, minimum: number): React.CSSProperties {
  if (valeur == null) return {}
  if (valeur >= minimum) return { color: COULEUR_NHV_ATTEINT, fontWeight: 600 }
  if (valeur < minimum * PART_NHV_ROUGE) return { color: COULEUR_NHV_FAIBLE, fontWeight: 600 }
  return {}
}

// Ce qui remplace le NHV quand il n'y a pas d'heures à lire : une personne morale n'en a
// pas besoin (« — », même inscrite cette année), un nouveau en est exempté (« N/A »).
function nhvSansObjet(categorie: string | null | undefined, anciennete: string | null | undefined): '—' | 'N/A' | null {
  if (categorie === 'Société' || categorie === 'SEC') return '—'
  return anciennete === 'Nouveau' ? 'N/A' : null
}

type ColonneBase =
  | 'rang' | 'numero_ordre' | 'nom' | 'conseil' | 'categorie' | 'province' | 'sexe' | 'actif'
  | 'telephone' | 'email' | 'cabinet' | 'nif' | 'chiffre_affaires'
  | 'raison_sociale' | 'associe_gerant' | 'anciennete' | 'nhv' | 'formation'
  | 'cotisation' | 'assurance' | 'conclusion' | 'situation' | 'action'

const LIBELLES_COLONNES_BASE: Record<ColonneBase, string> = {
  rang: 'N°',
  numero_ordre: "N° d'ordre",
  nom: 'Nom',
  conseil: 'Conseil',
  categorie: 'Catégorie',
  province: 'Province',
  sexe: 'Sexe',
  actif: 'Actif',
  telephone: 'N° téléphone',
  email: 'E-mail',
  cabinet: "Cabinet d'attache",
  nif: 'NIF',
  chiffre_affaires: "Chiffre d'affaires",
  raison_sociale: 'Raison sociale',
  associe_gerant: 'Associé gérant',
  anciennete: 'Ancienneté',
  nhv: 'NHV',
  formation: 'H.Formation',
  cotisation: 'Cotisation',
  assurance: 'Assurance',
  conclusion: 'Conclusion',
  situation: 'Situation',
  action: 'Action',
}

const COLONNES_BASE_DEFAUT: ColonneBase[] = [
  'numero_ordre', 'nom', 'conseil', 'categorie', 'province', 'sexe', 'actif',
  'anciennete', 'nhv', 'cotisation', 'assurance', 'conclusion', 'situation', 'action',
]

/**
 * Vues de la base propres à une catégorie : seules ces colonnes s'affichent
 * quand le filtre « Catégorie » vaut la clé. « conseil » et « action » n'y
 * apparaissent que si la vue est nationale ou l'utilisateur peut corriger.
 */
const COLONNES_BASE_PAR_CATEGORIE: Partial<Record<string, ColonneBase[]>> = {
  'EC Cabinet': [
    'rang', 'numero_ordre', 'nom', 'conseil', 'sexe', 'actif', 'telephone', 'email', 'cabinet',
    'anciennete', 'cotisation', 'formation', 'conclusion', 'action',
  ],
  'EC Indépendant': [
    'rang', 'numero_ordre', 'nom', 'conseil', 'sexe', 'actif', 'telephone', 'email', 'nif',
    'anciennete', 'cotisation', 'assurance', 'nhv', 'chiffre_affaires', 'conclusion', 'action',
  ],
  'EC Salarié': [
    'rang', 'numero_ordre', 'nom', 'conseil', 'sexe', 'actif', 'telephone', 'email',
    'anciennete', 'nhv', 'cotisation', 'conclusion', 'action',
  ],
  'Société': [
    'rang', 'numero_ordre', 'nom', 'conseil', 'raison_sociale', 'telephone', 'email', 'associe_gerant',
    'anciennete', 'cotisation', 'chiffre_affaires', 'assurance', 'conclusion', 'action',
  ],
  Stagiaire: ['rang', 'numero_ordre', 'nom', 'conseil', 'sexe', 'actif', 'cotisation', 'conclusion', 'action'],
}

/** Libellés propres à une vue de catégorie, repris du classeur. */
const LIBELLES_BASE_PAR_CATEGORIE: Partial<Record<string, Partial<Record<ColonneBase, string>>>> = {
  'EC Cabinet': { nom: 'Nom, post-noms et prénoms' },
  'EC Indépendant': { nom: 'Nom, post-noms et prénoms' },
  'EC Salarié': { nom: 'Nom, post-noms et prénoms' },
  'Société': { nom: 'Dénomination' },
}

/** « NOM, POST NOMS ET PRENOMS » : le prénom n'est ajouté que s'il n'y figure pas déjà. */
function nomComplet(nom: string, prenom: string | null | undefined) {
  const p = (prenom || '').trim()
  if (!p || nom.toLowerCase().includes(p.toLowerCase())) return nom
  return `${nom} ${p}`
}

/** Valeurs enregistrées (INSCRIT…) → ce que lit l'utilisateur. */
const LIBELLES_CONCLUSION: Record<string, string> = {
  'INSCRIT': 'En règle',
  'NON INSCRIT': 'Non en règle',
  'À DÉLIBÉRER': 'À délibérer',
}

function libelleConclusion(conclusion: string | null | undefined): string | null {
  if (!conclusion) return null
  return LIBELLES_CONCLUSION[conclusion.trim().toUpperCase()] ?? conclusion
}

const usd = (valeur: string) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

/**
 * Cotisation : En règle, Partiel ou Non en règle. Les notes de débit font foi
 * quand le membre en a — c'est ce que la trésorerie a réellement encaissé ;
 * sinon, ce que disait l'import (le détail est dans l'infobulle).
 */
function cotisationStatus(notes: TableauCotisationNotes | null | undefined, valeurImport: boolean | null) {
  const etat = notes ? notes.etat : valeurImport === true ? 'payee' : valeurImport === false ? 'non_payee' : null
  if (etat === null) return <span style={{ color: '#6b7280' }}>—</span>
  const detail = notes
    ? [
        `Notes de débit (${notes.nb_notes})`,
        `Cotisation N : ${usd(notes.du_n)} dû, ${usd(notes.reste_n)} restant`,
        Number(notes.du_anterieur) > 0 && `Arriérés : ${usd(notes.du_anterieur)} dû, ${usd(notes.reste_anterieur)} restant`,
      ].filter(Boolean).join('\n')
    : 'Aucune note de débit de cotisation : valeur du fichier importé'
  const { libelle, couleur } = {
    payee: { libelle: 'En règle', couleur: '#166534' },
    partielle: { libelle: 'Partiel', couleur: '#b45309' },
    non_payee: { libelle: 'Non en règle', couleur: '#991b1b' },
  }[etat]
  return <span title={detail} style={{ color: couleur, fontWeight: 600, whiteSpace: 'nowrap' }}>{libelle}</span>
}

/** Ce que dit chaque condition, dans la phrase « Pour être en règle, il faut : … ». */
const CONDITIONS: Record<CritereTableau, string> = {
  cotisation: 'être en règle avec la cotisation',
  formation: "avoir le nombre d'heures de formation requis (NHV)",
  assurance: 'avoir une assurance en cours',
  chiffre_affaires: "avoir déclaré le chiffre d'affaires",
}

const MODES_CRITERE: Array<{ valeur: ModeCritere; libelle: string; couleur: string }> = [
  { valeur: 'bloquant', libelle: 'sinon Non en règle', couleur: '#991b1b' },
  { valeur: 'a_deliberer', libelle: 'sinon À délibérer', couleur: '#92400e' },
  { valeur: 'ignore', libelle: 'non exigé', couleur: '#6b7280' },
]

/**
 * Règles de délibération, une carte par catégorie : « Pour être en règle, il
 * faut : … ». Chaque condition porte sur une colonne de situation de la vue de
 * la catégorie ; on choisit ce qu'entraîne son défaut. Seuls les écarts au
 * barème sont enregistrés.
 */
function ReglesParCategorie({
  reglages,
  modifiable,
  onChange,
}: {
  reglages: TableauReglages
  modifiable: boolean
  onChange: (modif: Partial<TableauReglages>) => void
}) {
  const bareme = reglages.bareme
  if (!bareme) return null
  const ecarts = reglages.criteres_par_categorie || {}
  const definitions = reglages.definitions_par_categorie || {}
  const minimumGeneral = reglages.heures_formation_min ?? 120
  const definir = (categorie: string, modif: DefinitionsCategorie) => {
    const ligne: DefinitionsCategorie = { ...(definitions[categorie] || {}), ...modif }
    // Ne garder que ce qui s'écarte des définitions par défaut.
    if (ligne.heures_formation_min === undefined || ligne.heures_formation_min === minimumGeneral) delete ligne.heures_formation_min
    if (ligne.cotisation_arrieres !== false) delete ligne.cotisation_arrieres
    if (ligne.cotisation_partielle !== 'bloquant') delete ligne.cotisation_partielle
    if (!ligne.assurance_fin_min) delete ligne.assurance_fin_min
    if (!ligne.ca_declaration_min) delete ligne.ca_declaration_min
    const suivant = { ...definitions }
    if (Object.keys(ligne).length) suivant[categorie] = ligne
    else delete suivant[categorie]
    onChange({ definitions_par_categorie: suivant })
  }
  const changer = (categorie: string, critere: CritereTableau, mode: ModeCritere) => {
    const ligne = { ...(ecarts[categorie] || {}) }
    if (mode === bareme[categorie][critere]) delete ligne[critere]
    else ligne[critere] = mode
    const suivant = { ...ecarts }
    if (Object.keys(ligne).length) suivant[categorie] = ligne
    else delete suivant[categorie]
    onChange({ criteres_par_categorie: suivant })
  }
  const nbEcarts = [...Object.values(ecarts), ...Object.values(definitions)]
    .reduce((total, ligne) => total + Object.keys(ligne || {}).length, 0)
  return (
    <div style={{ marginTop: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
        <h3 style={{ fontSize: '14px', fontWeight: 700, color: '#111827', margin: 0 }}>Conditions pour être en règle</h3>
        {modifiable && nbEcarts > 0 && (
          <button type="button" className={styles.secondaryButton} onClick={() => onChange({ criteres_par_categorie: {}, definitions_par_categorie: {} })}>
            Revenir au barème ({nbEcarts} modification{nbEcarts > 1 ? 's' : ''})
          </button>
        )}
      </div>
      <p style={{ fontSize: '12px', color: '#6b7280', margin: '4px 0 12px' }}>
        Chaque condition porte sur une colonne affichée pour la catégorie et se définit pour elle :
        ce qu'est être en règle avec la cotisation, le minimum d'heures de formation. Une donnée
        manquante donne toujours « À délibérer ».
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 300px), 1fr))', gap: '12px' }}>
        {Object.entries(bareme).map(([categorie, criteres]) => {
          const liste = Object.keys(criteres) as CritereTableau[]
          return (
            <div key={categorie} style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '12px 14px', background: '#fff' }}>
              <div style={{ fontWeight: 700, fontSize: '13px', color: '#111827' }}>{categorie}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', margin: '2px 0 8px' }}>Pour être en règle, il faut :</div>
              <ol style={{ margin: 0, paddingLeft: '18px', display: 'grid', gap: '8px' }}>
                {liste.map(critere => {
                  const origine = criteres[critere]
                  const mode = ecarts[categorie]?.[critere] ?? origine
                  const actif = mode !== 'ignore'
                  const modifie = mode !== origine
                  const style = MODES_CRITERE.find(m => m.valeur === mode)!
                  return (
                    <li key={critere} style={{ fontSize: '13px', color: actif ? '#111827' : '#9ca3af' }}>
                      <span style={{ textDecoration: actif ? 'none' : 'line-through' }}>{CONDITIONS[critere]}</span>
                      {actif && critere === 'formation' && (
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px', fontSize: '12px', color: '#374151' }}>
                          au moins
                          <input
                            type="number"
                            min={0}
                            disabled={!modifiable}
                            value={definitions[categorie]?.heures_formation_min ?? minimumGeneral}
                            onChange={event => definir(categorie, {
                              heures_formation_min: event.target.value === '' ? undefined : Number(event.target.value),
                            })}
                            aria-label={`${categorie} — minimum d'heures de formation`}
                            style={{
                              width: '72px', padding: '3px 6px', borderRadius: '5px', fontSize: '12px',
                              border: definitions[categorie]?.heures_formation_min !== undefined
                                ? '2px solid var(--tenant-primary, #1f6b5c)' : '1px solid #d1d5db',
                            }}
                          />
                          heures (NHV)
                        </label>
                      )}
                      {actif && critere === 'assurance' && (
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '3px', fontSize: '12px', color: '#374151' }}>
                          couverture au moins jusqu'au
                          <input
                            type="date"
                            disabled={!modifiable}
                            value={definitions[categorie]?.assurance_fin_min ?? ''}
                            onChange={event => definir(categorie, { assurance_fin_min: event.target.value || undefined })}
                            aria-label={`${categorie} — date minimale de couverture de l'assurance`}
                            style={{
                              padding: '3px 6px', borderRadius: '5px', fontSize: '12px',
                              border: definitions[categorie]?.assurance_fin_min ? '2px solid var(--tenant-primary, #1f6b5c)' : '1px solid #d1d5db',
                            }}
                          />
                          {!definitions[categorie]?.assurance_fin_min && <span style={{ color: '#6b7280' }}>(vide : date de situation du fichier)</span>}
                        </label>
                      )}
                      {actif && critere === 'chiffre_affaires' && (
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '3px', fontSize: '12px', color: '#374151' }}>
                          déclaration à partir du
                          <input
                            type="date"
                            disabled={!modifiable}
                            value={definitions[categorie]?.ca_declaration_min ?? ''}
                            onChange={event => definir(categorie, { ca_declaration_min: event.target.value || undefined })}
                            aria-label={`${categorie} — date à partir de laquelle la déclaration du chiffre d'affaires compte`}
                            style={{
                              padding: '3px 6px', borderRadius: '5px', fontSize: '12px',
                              border: definitions[categorie]?.ca_declaration_min ? '2px solid var(--tenant-primary, #1f6b5c)' : '1px solid #d1d5db',
                            }}
                          />
                          {definitions[categorie]?.ca_declaration_min
                            ? <span style={{ color: '#6b7280' }}>(une déclaration plus ancienne ne compte pas)</span>
                            : <span style={{ color: '#6b7280' }}>(facultatif — vide : toute déclaration de l'exercice)</span>}
                        </label>
                      )}
                      {actif && critere === 'cotisation' && (
                        <div style={{ display: 'grid', gap: '3px', marginTop: '3px', fontSize: '12px', color: '#374151' }}>
                          <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <input
                              type="checkbox"
                              disabled={!modifiable}
                              checked={definitions[categorie]?.cotisation_arrieres !== false}
                              onChange={event => definir(categorie, { cotisation_arrieres: event.target.checked })}
                            />
                            cotisation de l'exercice et arriérés de cotisation soldés
                          </label>
                          <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            si partiellement réglée :
                            <select
                              disabled={!modifiable}
                              value={definitions[categorie]?.cotisation_partielle ?? 'a_deliberer'}
                              onChange={event => definir(categorie, { cotisation_partielle: event.target.value as 'a_deliberer' | 'bloquant' })}
                              style={{ padding: '3px 6px', borderRadius: '5px', fontSize: '12px', border: '1px solid #d1d5db' }}
                            >
                              <option value="a_deliberer">À délibérer</option>
                              <option value="bloquant">Non en règle</option>
                            </select>
                          </label>
                        </div>
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px' }}>
                        <select
                          value={mode}
                          disabled={!modifiable}
                          aria-label={`${categorie} — ${CONDITIONS[critere]}`}
                          title={modifie ? `Barème : ${MODES_CRITERE.find(m => m.valeur === origine)!.libelle}` : undefined}
                          onChange={event => changer(categorie, critere, event.target.value as ModeCritere)}
                          style={{
                            padding: '4px 6px', borderRadius: '5px', fontSize: '12px', fontWeight: 600, color: style.couleur,
                            background: '#fff', border: modifie ? '2px solid var(--tenant-primary, #1f6b5c)' : '1px solid #d1d5db',
                          }}
                        >
                          {MODES_CRITERE.map(m => <option key={m.valeur} value={m.valeur}>{m.libelle}</option>)}
                        </select>
                        {modifie && <span style={{ fontSize: '11px', color: '#6b7280' }}>modifié</span>}
                      </div>
                    </li>
                  )
                })}
              </ol>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Colonnes de situation de chaque catégorie, comme côté serveur (`CRITERES_APPLICABLES`). */
const CONDITIONS_PAR_DEFAUT: Record<string, CritereTableau[]> = {
  'Société': ['cotisation', 'chiffre_affaires', 'assurance'],
  'EC Indépendant': ['cotisation', 'formation', 'assurance', 'chiffre_affaires'],
  'EC Cabinet': ['cotisation', 'formation'],
  'EC Salarié': ['cotisation', 'formation'],
  'Stagiaire': ['cotisation'],
}

/**
 * Les conditions exigées pour une catégorie selon les règles de délibération.
 * Sans catégorie : celles exigées par au moins une catégorie.
 */
function conditionsActives(categorie: string, reglages: TableauReglages): CritereTableau[] {
  const pour = (cat: string): CritereTableau[] => {
    const bareme = reglages.bareme?.[cat]
    const liste = bareme ? (Object.keys(bareme) as CritereTableau[]) : (CONDITIONS_PAR_DEFAUT[cat] || [])
    return liste.filter(critere => (reglages.criteres_par_categorie?.[cat]?.[critere] ?? bareme?.[critere] ?? 'bloquant') !== 'ignore')
  }
  if (categorie) return pour(categorie)
  const toutes = new Set(Object.keys(reglages.bareme || CONDITIONS_PAR_DEFAUT).flatMap(pour))
  return (['cotisation', 'formation', 'assurance', 'chiffre_affaires'] as CritereTableau[]).filter(c => toutes.has(c))
}

const OPTIONS_FILTRE: Record<CritereTableau, { libelle: string; options: Array<[string, string]> }> = {
  cotisation: { libelle: 'Cotisation', options: [['payee', 'En règle'], ['partielle', 'Partiel'], ['non_payee', 'Non en règle'], ['inconnue', 'Inconnue']] },
  formation: { libelle: 'NHV', options: [['atteint', 'Minimum atteint'], ['insuffisant', 'Sous le minimum'], ['non_requis', 'Non requis'], ['inconnu', 'Non renseigné']] },
  assurance: { libelle: 'Assurance', options: [['oui', 'Valide'], ['non', 'Non valide'], ['inconnu', 'Non renseignée']] },
  chiffre_affaires: { libelle: "Chiffre d'affaires", options: [['oui', 'Déclaré'], ['non', 'Non déclaré'], ['inconnu', 'Non renseigné']] },
}

/**
 * Filtres de la Base qui suivent les règles de délibération : la conclusion,
 * puis une liste par condition exigée pour la catégorie choisie.
 */
function FiltresConditions({
  categorie,
  reglages,
  valeurs,
  onChange,
}: {
  categorie: string
  reglages: TableauReglages
  valeurs: FiltresRegles
  onChange: (valeurs: FiltresRegles) => void
}) {
  const style = { padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }
  return (
    <>
      <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
        Conclusion
        <select value={valeurs.conclusion || ''} onChange={event => onChange({ ...valeurs, conclusion: event.target.value as FiltresRegles['conclusion'] })} style={style}>
          <option value="">Toutes</option>
          <option value="INSCRIT">En règle</option>
          <option value="NON INSCRIT">Non en règle</option>
          <option value="À DÉLIBÉRER">À délibérer</option>
          <option value="SANS">Sans conclusion</option>
        </select>
      </label>
      {conditionsActives(categorie, reglages).map(critere => (
        <label key={critere} style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
          {OPTIONS_FILTRE[critere].libelle}
          <select
            value={valeurs[critere] || ''}
            onChange={event => onChange({ ...valeurs, [critere]: event.target.value })}
            style={style}
          >
            <option value="">Tous</option>
            {OPTIONS_FILTRE[critere].options.map(([valeur, libelle]) => <option key={valeur} value={valeur}>{libelle}</option>)}
          </select>
        </label>
      ))}
    </>
  )
}

const SITUATIONS_PHYSIQUES = ['DECEDE', 'DEMISSIONNAIRE', 'RADIE', 'OMIS']
const STYLE_LIGNE_SORTIE: React.CSSProperties = { background: '#f3f4f6', color: '#6b7280' }

/** À la place de la conclusion : un membre sorti du Tableau n'est plus jugé. */
function BadgeSortie({ sortie }: { sortie: TableauSortie }) {
  return (
    <span title={[sortie.libelle, sortie.observation].filter(Boolean).join(' — ')} style={{ display: 'inline-flex', flexDirection: 'column', gap: '2px' }}>
      <span style={{ fontWeight: 600, color: '#374151' }}>{LIBELLES_SITUATION_SORTIE[sortie.situation]}</span>
      <span style={{ fontSize: '12px', color: '#6b7280' }}>{sortie.libelle.slice(LIBELLES_SITUATION_SORTIE[sortie.situation].length).trim()}</span>
    </span>
  )
}

function BoutonSortie({ membre, onOpen }: { membre: MembreSortie; onOpen: (membre: MembreSortie) => void }) {
  const morale = membre.categorie === 'Société' || membre.categorie === 'SEC'
  const titre = membre.sortie ? 'Modifier la sortie du Tableau' : morale ? "Déclarer que la société a cessé d'exister" : 'Déclarer une sortie (décès, démission, radiation, omission)'
  return (
    <button
      type="button"
      className={styles.secondaryButton}
      onClick={() => onOpen({ numero_ordre: membre.numero_ordre, nom: membre.nom, categorie: membre.categorie, sortie: membre.sortie })}
      disabled={!membre.numero_ordre}
      title={membre.numero_ordre ? titre : "Sans N° d'ordre, la sortie ne peut pas être déclarée"}
      aria-label={`${titre} : ${membre.nom}`}
    >
      <UserX size={14} />
    </button>
  )
}

/** Membre coché pour l'envoi groupé, désigné par son n° d'ordre normalisé. */
interface MembreCoche {
  numero: string
  nom: string
}

/** Envoie au membre sa situation ; la date du dernier envoi s'affiche sous le bouton. */
function BoutonReleve({ membre, dernier, onOpen }: {
  membre: { numero_ordre: string | null; nom: string }
  dernier?: TableauDernierReleve
  onOpen: (membre: MembreReleve) => void
}) {
  const { numero_ordre: numero, nom } = membre
  const titre = dernier
    ? `Envoyer sa situation au membre (dernier envoi le ${new Date(dernier.date).toLocaleDateString('fr-FR')})`
    : 'Envoyer sa situation au membre'
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
      <button
        type="button"
        className={styles.secondaryButton}
        onClick={() => { if (numero) onOpen({ numero_ordre: numero, nom }) }}
        disabled={!numero}
        title={numero ? titre : "Sans N° d'ordre, la situation ne peut pas être envoyée"}
        aria-label={`${titre} : ${nom}`}
      >
        <Send size={14} />
      </button>
      {dernier && (
        <span style={{ fontSize: '11px', color: '#6b7280', whiteSpace: 'nowrap' }}>
          {new Date(dernier.date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })}
        </span>
      )}
    </span>
  )
}

function booleanStatus(value: boolean | null) {
  if (value === true) return <span style={{ color: '#166534', fontWeight: 600 }}>Oui</span>
  if (value === false) return <span style={{ color: '#991b1b', fontWeight: 600 }}>Non</span>
  return <span style={{ color: '#6b7280' }}>Non renseigné</span>
}

function AnalyseObsolete({ scope, onRelancer }: { scope: 'import' | 'base'; onRelancer?: () => void }) {
  return (
    <div role="status" style={{
      display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap',
      background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: '8px',
      padding: '12px 14px', marginBottom: '16px', fontSize: '13px', color: '#92400e',
    }}>
      <AlertTriangle size={18} style={{ flexShrink: 0 }} />
      <span style={{ flex: 1, minWidth: '240px' }}>
        <strong>Analyse obsolète.</strong> Un import, une correction, une décision ou un changement de
        réglages a modifié {scope === 'base' ? 'la base consolidée' : 'cet import'} depuis ce calcul.
        Les chiffres ci-dessous datent d'avant ; l'export, le rapport et le PV resteront refusés tant que
        l'analyse n'aura pas été relancée.
      </span>
      {onRelancer && (
        <button type="button" className={styles.secondaryButton} onClick={onRelancer}>
          <RefreshCw size={14} />
          Relancer l'analyse
        </button>
      )}
    </div>
  )
}

function StatCard({
  value,
  label,
  icon,
  hint,
  tone = 'primary',
}: {
  value: number | string
  label: string
  icon: React.ReactNode
  hint?: string
  tone?: 'primary' | 'info' | 'warning' | 'danger' | 'success'
}) {
  return (
    <div className={`${styles.statCard} ${styles[`stat${tone[0].toUpperCase()}${tone.slice(1)}`]}`}>
      <div className={styles.statIcon}>{icon}</div>
      <div className={styles.statValue}>{typeof value === 'number' ? value.toLocaleString('fr-FR') : value}</div>
      <div className={styles.statLabel}>{label}</div>
      {hint && <div className={styles.statHint}>{hint}</div>}
    </div>
  )
}

export default function TableauModulePage() {
  const { hasPermission } = usePermissions()
  const { user } = useAuth()
  const canImport = hasPermission('tableau.import')
  const canAnalyze = hasPermission('tableau.analyze')
  const canReport = hasPermission('tableau.generate_report')
  const canGeneratePv = hasPermission('tableau.generate_pv')
  const canExport = hasPermission('tableau.export')
  const canCorrect = hasPermission('tableau.correct')
  const canNotify = hasPermission('tableau.notify')
  const canSettings = hasPermission('tableau.settings')
  const canUseAssistant = hasPermission('tableau.use_assistant')
  const canViewAudit = hasPermission('tableau.view_audit_logs')
  const canNational = user?.role?.toLowerCase() === 'super_admin'
    || (user?.role?.toLowerCase() === 'admin' && user?.organisation_slug?.toLowerCase() === 'cn')
  const location = useLocation()
  const navigate = useNavigate()
  const activeTab: TabKey = ONGLETS[location.pathname.replace(/\/+$/, '') || '/tableau'] ?? 'dashboard'
  const setActiveTab = (tab: TabKey) => navigate(CHEMINS[tab])
  const [base, setBase] = useState<TableauBase | null>(null)
  const [baseLoading, setBaseLoading] = useState(false)
  const [baseNational, setBaseNational] = useState(false)
  const [baseError, setBaseError] = useState<string | null>(null)
  const [baseAnalyse, setBaseAnalyse] = useState<string | null>(null)
  const [baseExercice, setBaseExercice] = useState('')
  const [baseSearch, setBaseSearch] = useState('')
  const [baseCategorie, setBaseCategorie] = useState('')
  const [basePersonne, setBasePersonne] = useState('')
  const [baseProvince, setBaseProvince] = useState('')
  const [baseSexe, setBaseSexe] = useState('')
  const [baseAnciennete, setBaseAnciennete] = useState('')
  const [baseActif, setBaseActif] = useState('')
  // Par défaut, les membres sortis du Tableau (décès, cessation…) sont écartés.
  const [baseSituation, setBaseSituation] = useState('en_exercice')
  const [sortieMembre, setSortieMembre] = useState<MembreSortie | null>(null)
  const [releveMembre, setReleveMembre] = useState<MembreReleve | null>(null)
  const [derniersReleves, setDerniersReleves] = useState<Record<string, TableauDernierReleve>>({})
  const [relevesRefresh, setRelevesRefresh] = useState(0)
  // Envoi groupé : des membres cochés (n° d'ordre → nom, conservés d'une page à
  // l'autre), ou tous les membres du filtre courant.
  const [selectionReleves, setSelectionReleves] = useState<Map<string, string>>(new Map())
  const [selectionFiltre, setSelectionFiltre] = useState(false)
  const [lotOuvert, setLotOuvert] = useState(false)
  const rafraichirReleves = useCallback(() => setRelevesRefresh(valeur => valeur + 1), [])
  const [baseRegles, setBaseRegles] = useState<FiltresRegles>({})
  const baseReglesCle = JSON.stringify(baseRegles)
  const [baseOrganisationId, setBaseOrganisationId] = useState('')
  const [basePage, setBasePage] = useState(1)
  const [basePageSize, setBasePageSize] = useState(50)
  const [baseRefresh, setBaseRefresh] = useState(0)
  // La base est consolidée à chaque requête : on n'interroge le serveur qu'une
  // fois la frappe stabilisée.
  const baseSearchDiffere = useDebouncedValue(baseSearch)
  const baseExerciceDiffere = useDebouncedValue(baseExercice)
  const [stats, setStats] = useState<TableauStats | null>(null)
  const [imports, setImports] = useState<TableauImport[]>([])
  const [anomalies, setAnomalies] = useState<TableauAnomalie[]>([])
  const [reports, setReports] = useState<TableauReport[]>([])
  const [comparison, setComparison] = useState<TableauComparison | null>(null)
  const [comparisonPage, setComparisonPage] = useState(1)
  const [comparisonPageSize, setComparisonPageSize] = useState(50)
  const [analyse, setAnalyse] = useState<TableauAnalyse | null>(null)
  const [selectedImport, setSelectedImport] = useState<TableauImport | null>(null)
  const [selectedReport, setSelectedReport] = useState<TableauReport | null>(null)
  const [analysisScope, setAnalysisScope] = useState<'import' | 'base'>('import')
  const [correctionDossier, setCorrectionDossier] = useState<TableauDossier | null>(null)
  const [journal, setJournal] = useState<TableauAuditEntry[]>([])
  const [journalLoading, setJournalLoading] = useState(false)
  const [correctionForm, setCorrectionForm] = useState({
    numero_ordre: '', nom: '', categorie: '', email: '', telephone: '',
    cotisation: '', assurance: '', motif: '',
  })

  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  // Rapport limité à une catégorie ; vide : toutes.
  const [rapportCategorie, setRapportCategorie] = useState('')
  // La base est le périmètre qui fait foi dès que l'exercice s'étale sur plusieurs fichiers.
  const [rapportPerimetre, setRapportPerimetre] = useState<'import' | 'base'>('base')
  const [error, setError] = useState<string | null>(null)

  const [exercice, setExercice] = useState(String(new Date().getFullYear()))
  const [compareExerciceA, setCompareExerciceA] = useState('')
  const [compareExerciceB, setCompareExerciceB] = useState('')
  const [reportTitle, setReportTitle] = useState('')
  const [reportInstructions, setReportInstructions] = useState('')
  const [pvInstructions, setPvInstructions] = useState('')

  const [reglages, setReglages] = useState<TableauReglages>({
    heures_formation_min: 120,
    age_seuil: 60,
    age_action: 'a_deliberer',
    nouveau_anciennete_ans: 3,
    exempter_nouveaux: true,
  })

  const apiErr = (err: unknown, fallback: string) =>
    err instanceof ApiError ? err.message : fallback

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [statsData, importsData, reportsData] = await Promise.all([
        getTableauStats().catch(() => null),
        listTableauImports().catch(() => []),
        listTableauReports().catch(() => []),
      ])
      if (statsData) setStats(statsData)
      setImports(importsData)
      setReports(reportsData)
      if (importsData.length > 0 && !selectedImport) {
        setSelectedImport(importsData[0])
        await loadImportDetails(importsData[0].id)
      } else if (selectedImport) {
        await loadImportDetails(selectedImport.id)
      }
    } catch (err) {
      setError(apiErr(err, 'Erreur de chargement.'))
    } finally {
      setLoading(false)
    }
  }

  const loadImportDetails = async (importId: number, scope: 'import' | 'base' = 'import') => {
    // L'analyse est relue avec le reste : c'est elle qui dit si le calcul
    // affiché vaut encore, ou s'il a été rendu obsolète depuis.
    const [anomaliesData, analyseData] = await Promise.all([
      listTableauAnomalies({ import_id: importId, scope }).catch(() => []),
      getTableauAnalyse(importId, scope).catch(() => null),
    ])
    setAnomalies(anomaliesData)
    setAnalyse(analyseData)
  }

  const handleSelectImport = async (imp: TableauImport) => {
    setSelectedImport(imp)
    setAnalysisScope('import')
    setLoading(true)
    try {
      await loadImportDetails(imp.id, 'import')
    } finally {
      setLoading(false)
    }
  }

  const handleImported = async (importId: number | null) => {
    setError(null)
    await loadAll()
    if (importId != null) {
      const imps = await listTableauImports()
      const imp = imps.find(i => i.id === importId) || null
      if (imp) {
        setSelectedImport(imp)
        await loadImportDetails(imp.id)
      }
    }
  }

  const handleAnalyse = async (choisi?: TableauImport) => {
    const cible = choisi || selectedImport
    if (!cible) return
    if (choisi) setSelectedImport(choisi)
    setActionLoading('analyse')
    setError(null)
    try {
      const result = await runTableauAnalyse(cible.id)
      setAnalyse(result)
      setAnalysisScope('import')
      await loadImportDetails(cible.id)
      await getTableauStats().then(s => s && setStats(s))
      setActiveTab('analyse')
    } catch (err) {
      setError(apiErr(err, "Erreur lors de l'analyse."))
    } finally {
      setActionLoading(null)
    }
  }

  const handleCompare = async () => {
    if (!compareExerciceA.trim() || !compareExerciceB.trim()) {
      setError('Veuillez renseigner les deux exercices à comparer.')
      return
    }
    setActionLoading('compare')
    setError(null)
    try {
      const result = await compareTableauExercices(compareExerciceA.trim(), compareExerciceB.trim())
      setComparison(result)
      setComparisonPage(1)
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la comparaison.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleGenerateReport = async () => {
    if (!selectedImport) return
    setActionLoading('report')
    setError(null)
    try {
      const r = await generateTableauReport({
        import_id: selectedImport.id,
        exercice: selectedImport.exercice,
        scope: analysisScope,
        titre: reportTitle.trim() || `Rapport d'analyse Tableau ${selectedImport.exercice}`,
        instructions: reportInstructions.trim() || undefined,
      })
      setSelectedReport(r)
      setReports(prev => [r, ...prev])
      setActiveTab('rapports')
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la génération du rapport.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleGeneratePV = async () => {
    if (!selectedImport) return
    setActionLoading('pv')
    setError(null)
    try {
      const r = await generateTableauPV({
        import_id: selectedImport.id,
        exercice: selectedImport.exercice,
        scope: analysisScope,
        instructions: pvInstructions.trim() || undefined,
      })
      setSelectedReport(r)
      setReports(prev => [r, ...prev])
      setActiveTab('rapports')
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de la génération du PV.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleSaveReglages = async () => {
    if (!selectedImport) return
    setActionLoading('reglages')
    setError(null)
    try {
      await updateTableauReglages(selectedImport.id, reglages)
      // Les réglages sont communs à l'exercice : recalculer le même périmètre.
      if (analysisScope === 'base') {
        const result = await runTableauAnalyseBase(selectedImport.exercice)
        setAnalyse(result.analyses[0] || null)
        setAnomalies(await listTableauAnomalies({ import_id: selectedImport.id, scope: 'base' }))
      } else {
        const result = await runTableauAnalyse(selectedImport.id)
        setAnalyse(result)
        await loadImportDetails(selectedImport.id)
      }
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de l\'enregistrement des réglages.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleExportTableau = async () => {
    if (!selectedImport) return
    setActionLoading('export-xlsx')
    setError(null)
    try {
      await downloadTableauExport(selectedImport.id, analysisScope)
    } catch (err) {
      setError(apiErr(err, 'Erreur lors de l\'export du tableau.'))
    } finally {
      setActionLoading(null)
    }
  }

  const handleRapportComplet = async (format: 'pdf' | 'xlsx') => {
    if (!selectedImport) return
    setActionLoading(`rapport-${format}`)
    setError(null)
    try {
      await downloadTableauRapportComplet(selectedImport.id, {
        format,
        scope: rapportPerimetre,
        exercice: selectedImport.exercice,
        categorie: rapportCategorie || undefined,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors de la génération du rapport complet.')
    } finally {
      setActionLoading(null)
    }
  }

  const handleExport = () => {
    if (!selectedReport?.contenu) return
    const blob = new Blob([selectedReport.contenu], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedReport.titre.replace(/\s+/g, '_')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => { void loadAll() }, [])

  // Les règles en vigueur se lisent sur le serveur : les valeurs par défaut du
  // code ne disent pas ce qui gouverne l'exercice.
  useEffect(() => {
    if (!selectedImport) return
    let annule = false
    getTableauReglages(selectedImport.id)
      .then(valeurs => { if (!annule && valeurs) setReglages(valeurs) })
      .catch(() => undefined)
    return () => { annule = true }
  }, [selectedImport?.id])

  // Le journal ne se charge qu'à l'ouverture de son écran : il n'entre dans
  // aucun autre calcul de la page.
  useEffect(() => {
    if (activeTab !== 'journal' || !canViewAudit) return
    let annule = false
    setJournalLoading(true)
    listTableauAudit({ limit: 100 })
      .then(entrees => { if (!annule) setJournal(entrees) })
      .catch(() => { if (!annule) setJournal([]) })
      .finally(() => { if (!annule) setJournalLoading(false) })
    return () => { annule = true }
  }, [activeTab, canViewAudit])

  const anomaliesHigh = anomalies.filter(a => a.gravite === 'high')
  const anomaliesMedium = anomalies.filter(a => a.gravite === 'medium')
  const anomaliesLow = anomalies.filter(a => a.gravite === 'low')

  useEffect(() => {
    if (activeTab !== 'base') return
    let annule = false
    setBaseLoading(true)
    setBaseError(null)
    getTableauBase({
      exercice: baseExerciceDiffere || undefined,
      national: baseNational,
      q: baseSearchDiffere || undefined,
      categorie: baseCategorie || undefined,
      organisationId: baseOrganisationId ? Number(baseOrganisationId) : undefined,
      personne: basePersonne || undefined,
      province: baseProvince || undefined,
      sexe: baseSexe || undefined,
      anciennete: baseAnciennete || undefined,
      actif: baseActif || undefined,
      situation: baseSituation,
      regles: baseRegles,
      limit: basePageSize,
      offset: (basePage - 1) * basePageSize,
    })
      .then(data => {
        if (annule) return
        // L'exercice trouvé n'est pas recopié dans le champ : il s'y verrait
        // comme une saisie, et relancerait aussitôt la même requête.
        setBase(data)
      })
      .catch((error: any) => {
        if (annule) return
        setBase(null)
        setBaseError(error?.message || 'Impossible de charger la base du Tableau.')
      })
      .finally(() => { if (!annule) setBaseLoading(false) })
    return () => { annule = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- baseRegles suivi par sa clé
  }, [activeTab, baseNational, baseExerciceDiffere, baseSearchDiffere, baseCategorie, baseOrganisationId, basePersonne, baseProvince, baseSexe, baseAnciennete, baseActif, baseSituation, baseReglesCle, basePage, basePageSize, baseRefresh])

  // Date du dernier relevé envoyé, sous le bouton de chaque membre.
  const exerciceBase = base?.exercice || ''
  useEffect(() => {
    if (!canNotify || baseNational || !exerciceBase) {
      setDerniersReleves({})
      return
    }
    let annule = false
    getTableauDerniersReleves(exerciceBase)
      .then(data => { if (!annule) setDerniersReleves(data) })
      .catch(() => { if (!annule) setDerniersReleves({}) })
    return () => { annule = true }
  }, [canNotify, baseNational, exerciceBase, relevesRefresh])
  // « Tous les membres du filtre » vaut pour le filtre affiché : il tombe dès qu'il change.
  useEffect(() => {
    setSelectionFiltre(false)
  }, [baseExerciceDiffere, baseSearchDiffere, baseCategorie, basePersonne, baseProvince, baseSexe, baseAnciennete, baseActif, baseSituation, baseReglesCle])
  // Les membres cochés l'ont été devant la situation d'un exercice : un autre
  // exercice affiché, et la sélection tombe (le lot partirait pour celui-ci).
  useEffect(() => {
    setSelectionReleves(new Map())
  }, [exerciceBase, baseNational])
  const selectionPossible = canNotify && !baseNational
  const filtresBaseActifs = [
    baseSearch, baseCategorie, basePersonne, baseProvince, baseSexe, baseAnciennete, baseActif,
    baseSituation !== 'en_exercice' ? baseSituation : '',
    ...Object.values(baseRegles),
  ].filter(Boolean).length
  const effacerFiltresBase = () => {
    setBaseSearch('')
    setBaseCategorie('')
    setBasePersonne('')
    setBaseProvince('')
    setBaseSexe('')
    setBaseAnciennete('')
    setBaseActif('')
    setBaseSituation('en_exercice')
    setBaseRegles({})
    setBasePage(1)
  }
  const cleNumero = (numero: string) => numero.trim().toUpperCase().replace(/\s+/g, '')
  const basculerSelection = (membres: MembreCoche[], coche: boolean) => {
    setSelectionReleves(courante => {
      const suivante = new Map(courante)
      for (const { numero, nom } of membres) {
        if (coche) suivante.set(cleNumero(numero), nom)
        else suivante.delete(cleNumero(numero))
      }
      return suivante
    })
  }
  const selectionnablesPage: MembreCoche[] = base
    ? [
        ...base.dossiers.filter(d => d.numero_ordre && !d.sortie).map(d => ({ numero: cleNumero(d.numero_ordre!), nom: nomComplet(d.nom, d.prenom) })),
        ...base.membres_a_completer.filter(m => m.numero_ordre && !m.sortie).map(m => ({ numero: cleNumero(m.numero_ordre!), nom: m.nom })),
      ]
    : []
  const pageEntierementCochee = selectionnablesPage.length > 0 && selectionnablesPage.every(m => selectionReleves.has(m.numero))
  const libelleSelection = selectionFiltre
    ? `Tous les membres du filtre (${base?.total_membres ?? 0})`
    : `${selectionReleves.size} membre(s) sélectionné(s)`
  const filtresReleves = {
    q: baseSearchDiffere || undefined,
    categorie: baseCategorie || undefined,
    personne: basePersonne || undefined,
    province: baseProvince || undefined,
    sexe: baseSexe || undefined,
    anciennete: baseAnciennete || undefined,
    actif: baseActif === '' ? undefined : baseActif === 'true',
    situation: baseSituation,
    ...Object.fromEntries(Object.entries(baseRegles).filter(([, valeur]) => valeur)),
  }
  const ligneCochee = (numero: string | null | undefined) =>
    selectionPossible && !!numero && (selectionFiltre || selectionReleves.has(cleNumero(numero)))
  const caseSelection = (numero: string | null | undefined, nom: string, sortie: TableauSortie | null | undefined) => (
    <td style={{ ...baseTdStyle, width: '28px' }}>
      {numero && !sortie && (
        <input
          type="checkbox"
          checked={ligneCochee(numero)}
          disabled={selectionFiltre}
          onChange={event => basculerSelection([{ numero, nom }], event.target.checked)}
          aria-label={`Sélectionner ${nom}`}
        />
      )}
    </td>
  )
  const dernierReleve = (numero: string | null | undefined) =>
    numero ? derniersReleves[cleNumero(numero)] : undefined

  useEffect(() => {
    setBasePage(1)
  }, [baseNational, baseExerciceDiffere, baseSearchDiffere, baseCategorie, baseOrganisationId, basePersonne, baseProvince, baseSexe, baseAnciennete, baseActif, baseSituation, baseReglesCle, basePageSize])

  // Une condition que la catégorie choisie n'exige pas ne filtre plus rien.
  useEffect(() => {
    setBaseRegles(courant => {
      const permis = new Set(conditionsActives(baseCategorie, reglages))
      const suivant: FiltresRegles = { conclusion: courant.conclusion }
      for (const critere of ['cotisation', 'formation', 'assurance', 'chiffre_affaires'] as const) {
        if (permis.has(critere) && courant[critere]) (suivant as Record<string, string>)[critere] = courant[critere] as string
      }
      return JSON.stringify(suivant) === JSON.stringify(courant) ? courant : suivant
    })
  }, [baseCategorie, reglages])

  const handleBaseAnalyse = async () => {
    if (!base?.exercice) return
    setActionLoading('analyse-base')
    setBaseAnalyse(null)
    try {
      const result = await runTableauAnalyseBase(base.exercice, baseNational)
      // Une analyse nationale n'est pas tout ou rien : on nomme les conseils
      // en échec plutôt que d'annoncer un succès global qui n'en est pas un.
      const echecs = result.resultats.filter(item => item.status === 'erreur')
      setBaseAnalyse([
        `${result.total_dossiers} membre(s) analysé(s) dans ${result.analyses_count} conseil(s).`,
        echecs.length
          ? `${echecs.length} conseil(s) en échec, sans effet sur les autres : ${echecs
              .map(item => `${item.organisation_nom || `#${item.organisation_id}`} (${item.detail || 'erreur'})`)
              .join(' ; ')}`
          : '',
      ].filter(Boolean).join(' '))
      if (!baseNational && result.analyses[0]) {
        setAnalyse(result.analyses[0])
        setAnalysisScope('base')
        const imp = imports.find(item => item.id === result.analyses[0].import_id)
        if (imp) {
          setSelectedImport(imp)
          const anomaliesData = await listTableauAnomalies({ import_id: imp.id, scope: 'base' })
          setAnomalies(anomaliesData)
        }
      }
      setBaseRefresh(value => value + 1)
      await getTableauStats().then(setStats)
    } catch (err) {
      setBaseAnalyse(apiErr(err, "L'analyse de la base a échoué."))
    } finally {
      setActionLoading(null)
    }
  }

  const openCorrection = (dossier: TableauDossier) => {
    setCorrectionDossier(dossier)
    setCorrectionForm({
      numero_ordre: dossier.numero_ordre || '',
      nom: dossier.nom,
      categorie: dossier.categorie,
      email: dossier.email || '',
      telephone: dossier.telephone || '',
      cotisation: '',
      assurance: '',
      motif: '',
    })
  }

  const handleCorrection = async () => {
    if (!correctionDossier || correctionForm.motif.trim().length < 3) return
    setActionLoading('correction')
    setBaseError(null)
    try {
      const changes: Record<string, unknown> = {}
      const clearFields: string[] = []
      for (const field of ['numero_ordre', 'nom', 'categorie', 'email', 'telephone'] as const) {
        const next = correctionForm[field].trim()
        const previous = String(correctionDossier[field] || '')
        if (!next && previous && (field === 'email' || field === 'telephone' || field === 'numero_ordre')) {
          clearFields.push(field)
        } else if (next !== previous) {
          changes[field] = next
        }
      }
      for (const [field, value] of [['cotisation_payee', correctionForm.cotisation], ['assurance', correctionForm.assurance]] as const) {
        if (value === 'clear') clearFields.push(field)
        else if (value === 'true' || value === 'false') changes[field] = value === 'true'
      }
      await correctTableauDossier(correctionDossier.id, {
        changes,
        clear_fields: clearFields,
        motif: correctionForm.motif.trim(),
      })
      setCorrectionDossier(null)
      setBaseRefresh(value => value + 1)
      // La correction rend l'analyse obsolète : on la relit pour l'annoncer,
      // plutôt que de la masquer comme si elle n'avait jamais existé.
      if (selectedImport) await loadImportDetails(selectedImport.id, analysisScope)
      await getTableauStats().then(s => s && setStats(s)).catch(() => undefined)
    } catch (err) {
      setBaseError(apiErr(err, 'La correction a échoué.'))
    } finally {
      setActionLoading(null)
    }
  }

  // Une analyse ne vaut que si elle est à jour : le backend refuse export, rapport
  // et PV dès qu'elle est marquée obsolète.
  const exercicesConnus = [...new Set(imports.map(item => item.exercice))]
  const analyseObsolete = analyse?.status === 'stale'
  const analysePrete = analyse?.status === 'completed'
  const categoriesCorrection = correctionDossier && correctionDossier.categorie
    && !(TABLEAU_CATEGORIES as readonly string[]).includes(correctionDossier.categorie)
    ? [correctionDossier.categorie, ...TABLEAU_CATEGORIES]
    : [...TABLEAU_CATEGORIES]
  const relancerAnalyse = canAnalyze && selectedImport
    ? () => void (analysisScope === 'base' ? handleBaseAnalyse() : handleAnalyse())
    : undefined
  const nhvMinimum = reglages.heures_formation_min ?? 120
  /** Le minimum d'heures de la catégorie, à défaut le minimum général. */
  const nhvMinimumDe = (categorie: string | null | undefined): number =>
    (categorie ? reglages.definitions_par_categorie?.[categorie]?.heures_formation_min : undefined) ?? nhvMinimum
  const colonnesBase = (COLONNES_BASE_PAR_CATEGORIE[baseCategorie] || COLONNES_BASE_DEFAUT).filter(colonne => {
    if (colonne === 'conseil') return !!base?.national
    if (colonne === 'action') return (canCorrect || canNotify) && !baseNational
    return true
  })
  const cellulesBase = (ligne: {
    rang: number
    numero_ordre: string | null
    nom: string
    prenom: string | null
    signalements?: string[]
    organisation: string
    categorie: string
    province: string | null | undefined
    sexe: string | null
    actif: boolean | null
    telephone: string | null
    email: string | null
    cabinet: string | null
    nif: string | null
    chiffre_affaires: React.ReactNode
    raison_sociale: string | null | undefined
    associe_gerant: string | null | undefined
    anciennete: string | null | undefined
    annee_inscription: number | null
    nhv: number | null
    cotisation: React.ReactNode
    assurance: boolean | null
    conclusion: React.ReactNode
    date_situation: string | null | undefined
    source_file_name: string | null | undefined
    action: React.ReactNode
  }): Record<ColonneBase, React.ReactNode> => {
    const aCompleter = <span style={{ color: '#b91c1c' }}>à compléter</span>
    const sansObjet = nhvSansObjet(ligne.categorie, ligne.anciennete)
    const heures = sansObjet
      ? <td style={{ ...baseTdStyle, color: '#9ca3af' }} title="NHV non applicable">{sansObjet}</td>
      : <td style={{ ...baseTdStyle, ...styleNhv(ligne.nhv, nhvMinimumDe(ligne.categorie)) }} title={`Minimum ${nhvMinimumDe(ligne.categorie)} h`}>{ligne.nhv ?? '—'}</td>
    const signale = !!ligne.signalements?.length
    return {
      rang: <td style={{ ...baseTdStyle, color: '#6b7280' }}>{ligne.rang}</td>,
      numero_ordre: <td style={baseTdStyle}>{ligne.numero_ordre || aCompleter}</td>,
      nom: (
        <td style={baseTdStyle}>
          {ligne.nom ? nomComplet(ligne.nom, ligne.prenom) : aCompleter}
          {signale && <div style={{ color: '#991b1b', fontSize: '12px' }}>{ligne.signalements!.join(' ; ')}</div>}
        </td>
      ),
      conseil: <td style={baseTdStyle}>{ligne.organisation}</td>,
      categorie: <td style={baseTdStyle}>{ligne.categorie}</td>,
      province: <td style={baseTdStyle}>{ligne.province || '—'}</td>,
      sexe: <td style={baseTdStyle}>{ligne.sexe || '—'}</td>,
      actif: <td style={baseTdStyle}>{booleanStatus(ligne.actif)}</td>,
      telephone: (
        <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }}>
          {ligne.telephone ? <a href={`tel:${ligne.telephone.replace(/[^\d+]/g, '')}`}>{ligne.telephone}</a> : '—'}
        </td>
      ),
      email: <td style={baseTdStyle}>{ligne.email ? <a href={`mailto:${ligne.email}`}>{ligne.email}</a> : '—'}</td>,
      cabinet: <td style={baseTdStyle}>{ligne.cabinet || '—'}</td>,
      nif: <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }}>{ligne.nif || '—'}</td>,
      chiffre_affaires: <td style={baseTdStyle}>{ligne.chiffre_affaires}</td>,
      raison_sociale: <td style={baseTdStyle}>{ligne.raison_sociale || '—'}</td>,
      associe_gerant: <td style={baseTdStyle}>{ligne.associe_gerant || '—'}</td>,
      anciennete: (
        <td style={baseTdStyle}>
          {ligne.anciennete || '—'}
          {ligne.annee_inscription != null && ligne.anciennete !== 'À vérifier' && (
            <div style={{ color: '#6b7280', fontSize: '12px' }}>inscrit en {ligne.annee_inscription}</div>
          )}
        </td>
      ),
      nhv: heures,
      formation: heures,
      cotisation: <td style={baseTdStyle}>{ligne.cotisation}</td>,
      assurance: <td style={baseTdStyle}>{booleanStatus(ligne.assurance)}</td>,
      conclusion: <td style={baseTdStyle}>{ligne.conclusion}</td>,
      situation: (
        <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }} title={ligne.source_file_name || undefined}>
          {ligne.date_situation ? new Date(`${ligne.date_situation}T00:00:00`).toLocaleDateString('fr-FR') : '—'}
        </td>
      ),
      action: <td style={baseTdStyle}>{ligne.action}</td>,
    }
  }
  const baseTotalPages = Math.max(1, Math.ceil((base?.total_membres || 0) / basePageSize))
  const baseImport = imports.find(item => item.id === base?.analysis_import_id) || null
  const comparisonTotalPages = Math.max(1, Math.ceil((comparison?.details.length || 0) / comparisonPageSize))
  const comparisonDetailsAffiches = (comparison?.details || []).slice(
    (comparisonPage - 1) * comparisonPageSize,
    comparisonPage * comparisonPageSize,
  )

  return (
    <div className={styles.page}>
      {canUseAssistant && <TableauAssistantChat />}

      <div className={styles.controlPanel}>
        <div className={styles.topRow}>
          <div>
            <div className={styles.breadcrumb}>Tableau de l'Ordre</div>
            <h1 className={styles.title}>
              <span className={styles.iconBox}><Table2 size={19} /></span>
              {TITRES[activeTab]}
            </h1>
          </div>
          <div className={styles.actions}>
            <BackButton fallback="/tableau" />
            <button type="button" className={styles.secondaryButton} onClick={() => void loadAll()} disabled={loading}>
              <RefreshCw size={15} />
              Actualiser
            </button>
          </div>
        </div>

      </div>

      <div className={styles.content}>
        {error && (
          <div className={styles.errorBox} style={{ marginBottom: '16px' }}>
            <XCircle size={15} style={{ display: 'inline', marginRight: '6px' }} />
            {error}
          </div>
        )}

        {activeTab === 'dashboard' && (
          <section>
            <div className={styles.dashboardIntro}>
              <div>
                <div className={styles.dashboardKicker}>Pilotage de la commission</div>
                <h2 className={styles.sectionTitle}>Vue d'ensemble Commission Tableau</h2>
                <p className={styles.sectionSubtitle}>Suivez la qualité de la base et accédez aux opérations courantes.</p>
              </div>
            </div>

            <div className={styles.statsGrid}>
              <StatCard
                value={stats?.membres_base ?? 0}
                label="Membres dans la base"
                icon={<FileSpreadsheet size={18} />}
                hint={stats?.membres_sortis ? `${stats.membres_sortis} sorti(s) du Tableau non comptés` : undefined}
                tone="primary"
              />
              <StatCard value={stats?.en_regle ?? 0} label="En règle" icon={<CheckCircle2 size={18} />} tone="success" />
              <StatCard value={stats?.non_en_regle ?? 0} label="Non en règle" icon={<XCircle size={18} />} tone="danger" />
              <StatCard
                value={stats?.a_deliberer ?? 0}
                label="À délibérer"
                icon={<AlertTriangle size={18} />}
                hint={stats?.sans_conclusion ? `${stats.sans_conclusion} sans conclusion` : undefined}
                tone="warning"
              />
              <StatCard value={stats?.membres_signales ?? 0} label="Lignes signalées à l'import" icon={<Bot size={18} />} tone="info" />
              <StatCard value={stats?.decisions_a_valider ?? 0} label="Décisions enregistrées" icon={<CheckCircle2 size={18} />} tone="success" />
            </div>

            {stats?.last_exercice && stats.dossiers_importes > 0 && stats.analyse_base_status !== 'completed' && (
              <div className={styles.notice}>
                <AlertTriangle size={17} aria-hidden="true" />
                <span>
                  {stats.analyse_base_status === 'stale'
                    ? `L'analyse de la base ${stats.last_exercice} est obsolète : les chiffres qui en dépendent datent d'avant le dernier changement.`
                    : `Aucune analyse de la base ${stats.last_exercice} : les chiffres qui en dépendent ne peuvent pas être établis.`}
                  {canAnalyze ? ' Lancez-la depuis l\'onglet « Base Tableau ».' : ''}
                </span>
              </div>
            )}

            <div className={styles.intro}>
              <section className={styles.panel}>
                <p className={styles.description}>
                  L'Agent Tableau assiste la Commission Tableau dans l'analyse des dossiers d'inscription,
                  de changement de catégorie, de conformité et de suivi des experts-comptables.
                  Importez un fichier Excel, lancez l'analyse réglementaire, détectez les anomalies et générez rapports et PV.
                </p>
              </section>
              <aside className={styles.statusPanel}>
                <span className={styles.statusLabel}>Exercice actif</span>
                <span className={styles.statusValue}>{stats?.last_exercice ?? 'Aucun import'}</span>
                <span className={styles.pill}>{stats?.imports_count ?? 0} import(s) chargé(s)</span>
              </aside>
            </div>

            {stats && <TableauDashboardCharts stats={stats} />}
          </section>
        )}

        {activeTab === 'base' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Base Tableau</h2>
                <p className={styles.sectionSubtitle}>
                  La situation qui fait foi pour chaque membre, tous imports de l'exercice confondus.
                  Réimporter un fichier plus ancien ne fait pas reculer la base.
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                {canAnalyze && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={baseLoading || actionLoading === 'analyse-base' || !base || base.total_dossiers === 0}
                    onClick={() => void handleBaseAnalyse()}
                    style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}
                  >
                    <Bot size={15} />
                    {actionLoading === 'analyse-base' ? 'Analyse...' : 'Analyser la base'}
                  </button>
                )}
                {canExport && !baseNational && baseImport && !!base?.total_dossiers && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={actionLoading === 'export-base'}
                    onClick={() => {
                      setActionLoading('export-base')
                      downloadTableauExport(baseImport.id, 'base')
                        .catch(err => setBaseError(apiErr(err, "L'export de la base a échoué.")))
                        .finally(() => setActionLoading(null))
                    }}
                  >
                    <Download size={15} />
                    Exporter la base
                  </button>
                )}
                {canNational && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151' }}>
                    <input
                      type="checkbox"
                      checked={baseNational}
                      onChange={(event) => {
                        setBaseNational(event.target.checked)
                        setBaseOrganisationId('')
                      }}
                      disabled={baseLoading}
                    />
                    Tous les conseils
                  </label>
                )}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', padding: '0 14px' }}>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Recherche
                <span style={{ position: 'relative' }}>
                  <Search size={14} style={{ position: 'absolute', left: '9px', top: '9px', color: '#6b7280' }} />
                  <input
                    type="search"
                    value={baseSearch}
                    onChange={event => setBaseSearch(event.target.value)}
                    placeholder="N° d'ordre, nom, e-mail, NIF ou cabinet"
                    style={{ width: '100%', padding: '7px 9px 7px 30px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  />
                </span>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Exercice
                <input
                  value={baseExercice}
                  onChange={event => setBaseExercice(event.target.value)}
                  placeholder={base?.exercice ? `${base.exercice} (le plus récent)` : '2026'}
                  title="Laissé vide, l'exercice le plus récent est utilisé."
                  style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px', width: '120px' }}
                />
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Personne
                <select
                  value={basePersonne}
                  onChange={event => {
                    const personne = event.target.value
                    setBasePersonne(personne)
                    // Une catégorie, un sexe ou un statut sans rapport viderait la liste sans dire pourquoi.
                    if (personne === 'morale') {
                      setBaseSexe('')
                      setBaseActif('')
                      if (baseCategorie !== 'Société') setBaseCategorie('')
                      if (SITUATIONS_PHYSIQUES.includes(baseSituation)) setBaseSituation('sortis')
                    } else if (personne === 'physique') {
                      if (baseCategorie === 'Société') setBaseCategorie('')
                      if (baseSituation === 'CESSE') setBaseSituation('sortis')
                    }
                  }}
                  style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                >
                  <option value="">Toutes</option>
                  <option value="morale">Personne morale</option>
                  <option value="physique">Personne physique</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Catégorie
                <select value={baseCategorie} onChange={event => setBaseCategorie(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Toutes</option>
                  {TABLEAU_CATEGORIES
                    .filter(item => !basePersonne || (basePersonne === 'morale') === (item === 'Société'))
                    .map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Province
                <select value={baseProvince} onChange={event => setBaseProvince(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Toutes</option>
                  {(base?.province_options || []).map(item => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Sexe
                <select value={baseSexe} onChange={event => setBaseSexe(event.target.value)} disabled={basePersonne === 'morale'} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Tous</option>
                  <option value="M">M</option>
                  <option value="F">F</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Actif
                <select value={baseActif} onChange={event => setBaseActif(event.target.value)} disabled={basePersonne === 'morale'} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Tous</option>
                  <option value="true">Oui</option>
                  <option value="false">Non</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Situation au Tableau
                <select value={baseSituation} onChange={event => setBaseSituation(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="en_exercice">{basePersonne === 'morale' ? 'En activité' : basePersonne === 'physique' ? 'En exercice' : 'En exercice / en activité'}</option>
                  <option value="sortis">Sortis du Tableau</option>
                  {basePersonne !== 'morale' && (
                    <>
                      <option value="DECEDE">Décédés</option>
                      <option value="DEMISSIONNAIRE">Démissionnaires</option>
                      <option value="RADIE">Radiés</option>
                      <option value="OMIS">Omis</option>
                    </>
                  )}
                  {basePersonne !== 'physique' && <option value="CESSE">Sociétés ayant cessé d'exister</option>}
                  <option value="tous">Tous</option>
                </select>
              </label>
              <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                Ancienneté
                <select value={baseAnciennete} onChange={event => setBaseAnciennete(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  <option value="">Toutes</option>
                  <option value="Ancien">Ancien</option>
                  <option value="Nouveau">Nouveau</option>
                </select>
              </label>
              <FiltresConditions
                categorie={baseCategorie}
                reglages={reglages}
                valeurs={baseRegles}
                onChange={setBaseRegles}
              />
              {baseNational && (
                <label style={{ display: 'grid', gap: '4px', fontSize: '12px' }}>
                  Conseil
                  <select value={baseOrganisationId} onChange={event => setBaseOrganisationId(event.target.value)} style={{ padding: '7px 9px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                    <option value="">Tous</option>
                    {(base?.organisation_options || []).map(item => <option key={item.id} value={item.id}>{item.nom}</option>)}
                  </select>
                </label>
              )}
              {filtresBaseActifs > 0 && (
                <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <button type="button" className={styles.secondaryButton} onClick={effacerFiltresBase} title="Revenir à la base complète de l'exercice">
                    <X size={14} /> Effacer les filtres ({filtresBaseActifs})
                  </button>
                </div>
              )}
            </div>

            {baseAnalyse && (
              <div className={styles.resultSummary} style={{ marginBottom: '12px' }}>
                <p style={{ fontSize: '13px' }}>{baseAnalyse}</p>
              </div>
            )}

            {baseError ? (
              <div className={styles.emptyBox}>{baseError}</div>
            ) : baseLoading && !base ? (
              <div className={styles.emptyBox} role="status">Chargement de la base...</div>
            ) : !base || base.total_membres === 0 ? (
              <div className={styles.emptyBox} role={baseLoading ? 'status' : undefined}>
                {baseLoading
                  ? 'Chargement de la base...'
                  : filtresBaseActifs > 0
                    ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                        Aucun membre ne correspond à ces filtres.
                        <button type="button" className={styles.secondaryButton} onClick={effacerFiltresBase}>
                          <X size={14} /> Effacer les filtres
                        </button>
                      </span>
                    )
                    : "Aucun import pour l'instant. Chargez un fichier depuis l'onglet « Import Excel »."}
              </div>
            ) : (
              // Pendant un rechargement, la page reste affichée, estompée : pas de saut
              // de mise en page, et la position de défilement est conservée.
              <div aria-busy={baseLoading} style={{ opacity: baseLoading ? 0.55 : 1, transition: 'opacity 150ms ease', pointerEvents: baseLoading ? 'none' : undefined }}>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={base.total_membres} label={`Membres - exercice ${base.exercice}`} icon={<Table2 size={18} />} />
                  <StatCard value={base.imports_couverts.length} label="Imports consolidés" icon={<Layers size={18} />} />
                  <StatCard value={base.membres_sans_numero} label="Sans n° d'ordre" icon={<AlertTriangle size={18} />} />
                  {base.total_a_completer > 0 && (
                    <StatCard value={base.total_a_completer} label="À compléter" icon={<AlertTriangle size={18} />} />
                  )}
                  {base.national && (
                    <StatCard value={base.organisations.length} label="Conseils" icon={<BarChart2 size={18} />} />
                  )}
                </div>

                {base.total_a_completer > 0 && (
                  <div style={{ background: '#fef3c7', border: '1px solid #fde68a', borderRadius: '6px', color: '#92400e', fontSize: '13px', lineHeight: 1.4, marginBottom: '16px', padding: '10px 14px' }}>
                    {base.total_a_completer} membre(s) viennent des fichiers personnes physiques ou morales, sans dossier
                    du classeur Tableau. Leur conclusion applique les règles de délibération à ce que l'on sait d'eux :
                    cotisation des notes de débit, déclarations d'assurance et de chiffre d'affaires, NHV. Une donnée
                    absente donne « À délibérer » ; le motif s'affiche au survol de la conclusion.
                  </div>
                )}

                <p style={{ color: '#6b7280', fontSize: '12px', margin: '0 0 8px' }}>
                  NHV : <strong style={{ color: COULEUR_NHV_ATTEINT }}>bleu</strong> à partir du minimum de la catégorie
                  ({nhvMinimum} h par défaut),{' '}
                  <strong style={{ color: COULEUR_NHV_FAIBLE }}>rouge</strong> sous 60 % de ce minimum, N/A pour les nouveaux, — pour les sociétés.
                </p>
                {selectionPossible && base.total_membres > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', padding: '8px 12px', marginBottom: '8px', border: '1px solid #d9eee7', borderRadius: '6px', background: '#f2fbf8', fontSize: '13px' }}>
                    <span style={{ fontWeight: 600 }} aria-live="polite">
                      {selectionFiltre || selectionReleves.size
                        ? libelleSelection
                        : 'Cochez des membres, ou envoyez à tout le filtre'}
                    </span>
                    {!selectionFiltre && (
                      <button type="button" className={styles.secondaryButton} onClick={() => setSelectionFiltre(true)}>
                        Sélectionner les {base.total_membres} membres du filtre
                      </button>
                    )}
                    {(selectionFiltre || selectionReleves.size > 0) && (
                      <>
                        <button type="button" className={styles.secondaryButton} style={{ background: '#0f7b62', borderColor: '#0f7b62', color: '#ffffff' }} onClick={() => setLotOuvert(true)}>
                          <Send size={14} /> Envoyer leur situation
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryButton}
                          onClick={() => { setSelectionFiltre(false); setSelectionReleves(new Map()) }}
                        >
                          Effacer la sélection
                        </button>
                      </>
                    )}
                  </div>
                )}
                <div style={{ overflow: 'auto', maxHeight: 'min(72vh, 960px)', border: '1px solid #eef0f3', borderRadius: '6px' }}>
                  <table style={baseTableStyle}>
                    <thead>
                      <tr>
                        {selectionPossible && (
                          <th style={{ ...baseThStyle, width: '28px' }}>
                            <input
                              type="checkbox"
                              checked={selectionFiltre || pageEntierementCochee}
                              disabled={selectionFiltre || selectionnablesPage.length === 0}
                              onChange={event => basculerSelection(selectionnablesPage, event.target.checked)}
                              title="Sélectionner les membres de la page"
                              aria-label="Sélectionner les membres de la page"
                            />
                          </th>
                        )}
                        {colonnesBase.map(colonne => (
                          <th key={colonne} style={baseThStyle} title={colonne === 'nhv' || colonne === 'formation' ? "Nombre d'heures validées" : undefined}>
                            {LIBELLES_BASE_PAR_CATEGORIE[baseCategorie]?.[colonne] ?? LIBELLES_COLONNES_BASE[colonne]}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {base.dossiers.map((dossier, index) => {
                        const cellules = cellulesBase({
                          rang: base.offset + index + 1,
                          numero_ordre: dossier.numero_ordre,
                          nom: dossier.nom,
                          prenom: dossier.prenom,
                          organisation: dossier.organisation_nom || `#${dossier.organisation_id}`,
                          categorie: dossier.categorie || '—',
                          province: dossier.province,
                          sexe: dossier.sexe,
                          actif: dossier.actif ?? null,
                          telephone: dossier.telephone,
                          email: dossier.email,
                          cabinet: dossier.cabinet,
                          nif: dossier.nif,
                          chiffre_affaires: booleanStatus(dossier.chiffre_affaires),
                          raison_sociale: dossier.raison_sociale,
                          associe_gerant: dossier.associe_gerant,
                          anciennete: dossier.anciennete_libelle,
                          annee_inscription: dossier.annee_inscription,
                          nhv: dossier.heures_forco,
                          cotisation: cotisationStatus(dossier.cotisation_notes, dossier.cotisation_payee),
                          assurance: dossier.assurance_valide !== undefined ? dossier.assurance_valide : dossier.assurance,
                          conclusion: dossier.sortie
                            ? <BadgeSortie sortie={dossier.sortie} />
                            : libelleConclusion(dossier.conclusion) || 'À analyser',
                          date_situation: dossier.date_situation,
                          source_file_name: dossier.source_file_name,
                          action: (
                            <div style={{ display: 'flex', gap: '4px' }}>
                              {canCorrect && (
                                <button type="button" className={styles.secondaryButton} onClick={() => openCorrection(dossier)} title="Corriger le dossier" aria-label={`Corriger ${dossier.nom}`}>
                                  <Pencil size={14} />
                                </button>
                              )}
                              {canCorrect && <BoutonSortie membre={dossier} onOpen={setSortieMembre} />}
                              {canNotify && !dossier.sortie && (
                                <BoutonReleve membre={dossier} dernier={dernierReleve(dossier.numero_ordre)} onOpen={setReleveMembre} />
                              )}
                            </div>
                          ),
                        })
                        return (
                          <tr
                            key={dossier.id}
                            className={`${styles.baseRow} ${ligneCochee(dossier.numero_ordre) ? styles.baseRowSelected : ''}`}
                            style={dossier.sortie ? STYLE_LIGNE_SORTIE : undefined}
                          >
                            {selectionPossible && caseSelection(dossier.numero_ordre, nomComplet(dossier.nom, dossier.prenom), dossier.sortie)}
                            {colonnesBase.map(colonne => <Fragment key={colonne}>{cellules[colonne]}</Fragment>)}
                          </tr>
                        )
                      })}
                      {base.membres_a_completer.map((membre, index) => {
                        const signale = membre.signalements.length > 0
                        const cellules = cellulesBase({
                          rang: base.offset + base.dossiers.length + index + 1,
                          numero_ordre: membre.numero_ordre,
                          nom: membre.nom,
                          prenom: null,
                          signalements: membre.signalements,
                          organisation: membre.organisation_nom || `#${membre.organisation_id}`,
                          categorie: membre.categorie,
                          province: membre.province,
                          sexe: membre.sexe,
                          actif: membre.actif,
                          telephone: membre.telephone,
                          email: membre.email,
                          cabinet: membre.cabinet,
                          nif: membre.nif,
                          chiffre_affaires: booleanStatus(membre.chiffre_affaires ?? null),
                          raison_sociale: membre.raison_sociale,
                          associe_gerant: membre.associe_gerant,
                          anciennete: membre.anciennete_libelle,
                          annee_inscription: membre.annee_inscription,
                          nhv: membre.nhv,
                          cotisation: cotisationStatus(membre.cotisation_notes, null),
                          assurance: membre.assurance_valide !== undefined ? membre.assurance_valide : membre.assurance,
                          conclusion: membre.sortie
                            ? <BadgeSortie sortie={membre.sortie} />
                            : membre.conclusion
                            ? <span title={membre.conclusion_motif || undefined} style={{ fontWeight: 600, color: membre.conclusion === 'INSCRIT' ? '#166534' : membre.conclusion === 'NON INSCRIT' ? '#991b1b' : '#92400e' }}>
                                {libelleConclusion(membre.conclusion)}
                              </span>
                            : <span style={{ color: '#92400e', fontWeight: 600 }}>À compléter</span>,
                          date_situation: membre.date_situation,
                          source_file_name: membre.source_file_name,
                          action: (
                            <div style={{ display: 'flex', gap: '4px' }}>
                              {canCorrect && <BoutonSortie membre={membre} onOpen={setSortieMembre} />}
                              {canNotify && !membre.sortie && (
                                <BoutonReleve membre={membre} dernier={dernierReleve(membre.numero_ordre)} onOpen={setReleveMembre} />
                              )}
                            </div>
                          ),
                        })
                        return (
                          <tr
                            key={membre.id}
                            className={`${styles.baseRow} ${ligneCochee(membre.numero_ordre) ? styles.baseRowSelected : ''}`}
                            style={membre.sortie ? STYLE_LIGNE_SORTIE : signale ? { background: '#fee2e2' } : undefined}
                            title={signale ? membre.signalements.join(' ; ') : undefined}
                          >
                            {selectionPossible && caseSelection(membre.numero_ordre, membre.nom, membre.sortie)}
                            {colonnesBase.map(colonne => <Fragment key={colonne}>{cellules[colonne]}</Fragment>)}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '0 14px' }}>
                  <label style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    Lignes
                    <select value={basePageSize} onChange={event => setBasePageSize(Number(event.target.value))}>
                      {[25, 50, 100, 200].map(size => <option key={size} value={size}>{size}</option>)}
                    </select>
                  </label>
                  <span style={{ fontSize: '12px', color: '#6b7280' }}>
                    {baseLoading
                      ? <span role="status">Mise à jour…</span>
                      : <>
                          {(base.offset + 1).toLocaleString('fr-FR')}–{Math.min(base.offset + basePageSize, base.total_membres).toLocaleString('fr-FR')} sur {base.total_membres.toLocaleString('fr-FR')} · Page {Math.min(basePage, baseTotalPages)} sur {baseTotalPages}
                        </>}
                  </span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button type="button" className={styles.secondaryButton} disabled={basePage <= 1 || baseLoading} onClick={() => setBasePage(page => Math.max(1, page - 1))} title="Page précédente" aria-label="Page précédente">
                      <ChevronLeft size={15} />
                    </button>
                    <button type="button" className={styles.secondaryButton} disabled={basePage >= baseTotalPages || baseLoading} onClick={() => setBasePage(page => page + 1)} title="Page suivante" aria-label="Page suivante">
                      <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {activeTab === 'import' && (
          <ImportsParSource
            imports={imports}
            canImport={canImport}
            canExport={canExport}
            canAnalyze={canAnalyze}
            exercice={exercice}
            onExerciceChange={setExercice}
            onImported={handleImported}
            onAnalyse={imp => void handleAnalyse(imp)}
            analyseEnCours={actionLoading === 'analyse'}
          />
        )}

        {activeTab === 'analyse' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Analyse réglementaire</h2>
                <p className={styles.sectionSubtitle}>Calcul déterministe des conclusions, anomalies et statistiques de conformité.</p>
              </div>
              {selectedImport && canAnalyze && (
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={() => void (analysisScope === 'base' ? handleBaseAnalyse() : handleAnalyse())}
                  disabled={actionLoading === 'analyse'}
                  style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}
                >
                  <Bot size={15} />
                  {actionLoading === 'analyse' ? 'Analyse en cours...' : 'Relancer l\'analyse'}
                </button>
              )}
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {!selectedImport ? (
              <div className={styles.emptyBox}>
                Aucun import sélectionné. Allez dans l'onglet "Import Excel" pour charger un fichier.
              </div>
            ) : analyse ? (
              <div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={analyse.total_dossiers} label="Total dossiers" icon={<FileSpreadsheet size={18} />} />
                  <StatCard value={analyse.dossiers_complets} label="Dossiers complets" icon={<CheckCircle2 size={18} />} />
                  <StatCard value={analyse.dossiers_incomplets} label="Incomplets" icon={<AlertTriangle size={18} />} />
                  <StatCard value={analyse.anomalies_count} label="Anomalies" icon={<XCircle size={18} />} />
                  <StatCard value={analyse.doublons_count} label="Doublons" icon={<GitCompare size={18} />} />
                  <StatCard value={analyse.cotisations_non_payees} label="Cotis. non payées" icon={<XCircle size={18} />} />
                  <StatCard value={analyse.heures_forco_insuffisantes} label="FORCO insuff." icon={<AlertTriangle size={18} />} />
                  <StatCard value={analyse.assurances_manquantes} label="Assurances manq." icon={<XCircle size={18} />} />
                </div>

                {!!(analyse.stats_json?.categories) && (
                  <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '16px' }}>
                    <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>Répartition par catégorie</h3>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {Object.entries(analyse.stats_json.categories as Record<string, number>).map(([cat, cnt]: [string, number]) => (
                        <div key={cat} style={{ background: 'var(--tableau-brand-soft)', borderRadius: '6px', padding: '8px 14px', fontSize: '13px' }}>
                          <span style={{ fontWeight: '600' }}>{cat}</span>
                          <span style={{ color: 'var(--tenant-primary, #1f6b5c)', fontWeight: '700', marginLeft: '8px' }}>{cnt}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!!(analyse.stats_json?.conclusions) && (() => {
                  const c = analyse.stats_json.conclusions as Record<string, number>
                  const pills: Array<[string, number, string]> = [
                    ['En règle', c.inscrits || 0, '#16a34a'],
                    ['Non en règle', c.non_inscrits || 0, '#dc2626'],
                    ['À délibérer', c.a_deliberer || 0, '#d97706'],
                    ['N/A', c.non_applicable || 0, '#6b7280'],
                  ]
                  return (
                    <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '16px' }}>
                      <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '10px', color: '#374151' }}>Conclusions (verdict réglementaire)</h3>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        {pills.map(([label, cnt, color]) => (
                          <div key={label} style={{ borderLeft: `4px solid ${color}`, background: '#f9fafb', borderRadius: '6px', padding: '8px 14px', fontSize: '13px' }}>
                            <span style={{ fontWeight: '600' }}>{label}</span>
                            <span style={{ color, fontWeight: '700', marginLeft: '8px' }}>{cnt}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })()}

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '16px' }}>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
                      Titre du rapport (optionnel)
                    </label>
                    <input
                      value={reportTitle}
                      onChange={e => setReportTitle(e.target.value)}
                      placeholder={`Rapport Tableau ${selectedImport.exercice}`}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '280px' }}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
                      Instructions complémentaires
                    </label>
                    <input
                      value={reportInstructions}
                      onChange={e => setReportInstructions(e.target.value)}
                      placeholder="Observations ou points particuliers à inclure…"
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%' }}
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
                  {canReport && <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGenerateReport()}
                    disabled={actionLoading === 'report' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                  }
                  {canExport && <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleExportTableau()}
                    disabled={actionLoading === 'export-xlsx' || !analysePrete}
                    style={{ background: '#16a34a', color: '#fff', borderColor: '#16a34a' }}
                  >
                    <Download size={15} />
                    {actionLoading === 'export-xlsx' ? 'Export...' : 'Exporter le tableau (.xlsx)'}
                  </button>
                  }
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => setActiveTab('anomalies')}
                  >
                    <AlertTriangle size={15} />
                    Voir les anomalies ({analyse.anomalies_count})
                  </button>
                </div>
              </div>
            ) : (
              <div className={styles.emptyBox}>
                <Bot size={32} style={{ opacity: 0.3, marginBottom: '8px' }} />
                <p>Aucune analyse disponible pour cet import.</p>
                {selectedImport && canAnalyze && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleAnalyse()}
                    disabled={actionLoading === 'analyse'}
                    style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', marginTop: '8px' }}
                  >
                    <Bot size={15} />
                    Lancer l'analyse réglementaire
                  </button>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === 'anomalies' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Anomalies détectées</h2>
                <p className={styles.sectionSubtitle}>
                  {anomalies.length} anomalie(s) pour {analysisScope === 'base' ? 'la base consolidée' : "l'import sélectionné"}.
                  {anomaliesHigh.length > 0 && ` ${anomaliesHigh.length} critique(s).`}
                </p>
              </div>
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {anomalies.length === 0 ? (
              <div className={styles.emptyBox}>
                {selectedImport ? 'Aucune anomalie détectée. Lancez d\'abord l\'analyse réglementaire.' : 'Sélectionnez un import.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {[
                  { list: anomaliesHigh, label: 'Anomalies critiques', color: '#dc2626', bg: '#fee2e2' },
                  { list: anomaliesMedium, label: 'Anomalies importantes', color: '#d97706', bg: '#fef3c7' },
                  { list: anomaliesLow, label: 'Anomalies mineures', color: '#2563eb', bg: '#dbeafe' },
                ].filter(g => g.list.length > 0).map(group => (
                  <div key={group.label}>
                    <h3 style={{ fontSize: '13px', fontWeight: '600', color: group.color, marginBottom: '8px', marginTop: '12px' }}>
                      {group.label} ({group.list.length})
                    </h3>
                    {group.list.map(a => (
                      <div
                        key={a.id}
                        style={{
                          background: group.bg,
                          border: `1px solid ${group.color}30`,
                          borderLeft: `3px solid ${group.color}`,
                          borderRadius: '6px',
                          padding: '10px 14px',
                          marginBottom: '6px',
                          fontSize: '13px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                          <div>
                            <span style={{ fontWeight: '600', color: group.color }}>[{a.type_anomalie}]</span>
                            <span style={{ marginLeft: '8px' }}>{a.description}</span>
                          </div>
                          <span style={{ fontSize: '11px', color: '#9ca3af', whiteSpace: 'nowrap' }}>
                            Dossier #{a.dossier_id}
                          </span>
                        </div>
                        {(a.valeur_trouvee !== null || a.valeur_attendue !== null) && (
                          <div style={{ marginTop: '4px', fontSize: '12px', color: '#4b5563' }}>
                            {a.champ_concerne && <span style={{ marginRight: '8px' }}>Champ : <strong>{a.champ_concerne}</strong></span>}
                            {a.valeur_trouvee !== null && <span style={{ marginRight: '8px' }}>Valeur trouvée : <strong>{String(a.valeur_trouvee)}</strong></span>}
                            {a.valeur_attendue !== null && <span>Attendu : <strong>{String(a.valeur_attendue)}</strong></span>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {activeTab === 'comparaison' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Comparaison d'exercices</h2>
                <p className={styles.sectionSubtitle}>Analysez les évolutions entre deux tableaux annuels.</p>
              </div>
            </div>

            <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '20px', marginBottom: '20px' }}>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div>
                  <label style={{ fontSize: '12px', fontWeight: '600', display: 'block', marginBottom: '4px' }}>Exercice A</label>
                  <input
                    value={compareExerciceA}
                    onChange={e => setCompareExerciceA(e.target.value)}
                    placeholder="ex : 2025"
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '14px', width: '100px' }}
                  />
                </div>
                <span style={{ paddingBottom: '8px', color: '#9ca3af' }}>vs</span>
                <div>
                  <label style={{ fontSize: '12px', fontWeight: '600', display: 'block', marginBottom: '4px' }}>Exercice B</label>
                  <input
                    value={compareExerciceB}
                    onChange={e => setCompareExerciceB(e.target.value)}
                    placeholder="ex : 2026"
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '14px', width: '100px' }}
                  />
                </div>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  onClick={() => void handleCompare()}
                  disabled={actionLoading === 'compare'}
                  style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}
                >
                  <GitCompare size={15} />
                  {actionLoading === 'compare' ? 'Comparaison...' : 'Comparer'}
                </button>
              </div>
            </div>

            {comparison && (
              <div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '20px' }}>
                  <StatCard value={comparison.dossiers_en_commun} label="Dossiers communs" icon={<CheckCircle2 size={18} />} />
                  <StatCard value={comparison.nouveaux_dans_b} label={`Nouveaux en ${comparison.exercice_b}`} icon={<FileSpreadsheet size={18} />} />
                  <StatCard value={comparison.absents_de_b} label={`Absents de ${comparison.exercice_b}`} icon={<XCircle size={18} />} />
                  <StatCard value={comparison.changements_categorie} label="Changements de catégorie" icon={<GitCompare size={18} />} />
                </div>

                {comparison.details.length > 0 && (
                  <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', overflow: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                      <thead>
                        <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Type</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Nom</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Catégorie</th>
                          <th style={{ padding: '9px 12px', textAlign: 'left', fontWeight: '600' }}>Détail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {comparisonDetailsAffiches.map((d, i) => (
                          <tr key={`${String(d.type)}-${String(d.numero_ordre ?? d.nom ?? '')}-${i}`} style={{ borderBottom: '1px solid #f3f4f6' }}>
                            <td style={{ padding: '8px 12px' }}>
                              <span className={styles.pill} style={{
                                background: d.type === 'nouveau' ? '#d1fae5' : d.type === 'absent' ? '#fee2e2' : '#fef3c7',
                                color: d.type === 'nouveau' ? '#065f46' : d.type === 'absent' ? '#991b1b' : '#92400e',
                                fontSize: '11px',
                              }}>
                                {d.type === 'nouveau' ? 'Nouveau' : d.type === 'absent' ? 'Absent' : 'Changement'}
                              </span>
                            </td>
                            <td style={{ padding: '8px 12px', fontWeight: '500' }}>{String(d.nom ?? '')} {String(d.prenom ?? '')}</td>
                            <td style={{ padding: '8px 12px' }}>{String(d.categorie ?? d.categorie_apres ?? '—')}</td>
                            <td style={{ padding: '8px 12px', fontSize: '12px', color: '#6b7280' }}>
                              {d.type === 'changement_categorie'
                                ? `${String(d.categorie_avant)} → ${String(d.categorie_apres)}`
                                : String(d.exercice ?? '')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'flex-end', padding: '10px 12px', borderTop: '1px solid #e5e7eb', flexWrap: 'wrap' }}>
                      <select value={comparisonPageSize} onChange={event => { setComparisonPageSize(Number(event.target.value)); setComparisonPage(1) }}>
                        <option value={25}>25 par page</option>
                        <option value={50}>50 par page</option>
                        <option value={100}>100 par page</option>
                      </select>
                      <span style={{ fontSize: '12px', color: '#6b7280' }}>
                        Page {Math.min(comparisonPage, comparisonTotalPages)} sur {comparisonTotalPages}
                      </span>
                      <button type="button" className={styles.secondaryButton} disabled={comparisonPage <= 1} onClick={() => setComparisonPage(page => Math.max(1, page - 1))} title="Page précédente">
                        <ChevronLeft size={15} />
                      </button>
                      <button type="button" className={styles.secondaryButton} disabled={comparisonPage >= comparisonTotalPages} onClick={() => setComparisonPage(page => page + 1)} title="Page suivante">
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {activeTab === 'rapports' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Rapports & Procès-verbaux</h2>
                <p className={styles.sectionSubtitle}>Générer et consulter les rapports d'analyse et les PV de la Commission Tableau.</p>
              </div>
            </div>

            {analyseObsolete && <AnalyseObsolete scope={analysisScope} onRelancer={relancerAnalyse} />}

            {selectedImport && !analyse && (canReport || canGeneratePv) && (
              <p style={{ fontSize: '13px', color: '#6b7280', marginBottom: '16px' }}>
                Aucune analyse enregistrée pour ce périmètre : lancez-la depuis l'onglet
                « Analyse réglementaire » avant de générer un rapport ou un procès-verbal.
              </p>
            )}

            {selectedImport && (canReport || canGeneratePv || canExport) && (
              <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '20px' }}>
                {canExport && <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
                  <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>Rapport complet (PDF et Excel)</h3>
                  <p style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>
                    Le tableau de bord en graphiques, puis la liste des membres.
                  </p>
                  <label style={{ display: 'block', fontSize: '12px', color: '#4b5563', marginBottom: '8px' }}>
                    Périmètre
                    <select
                      value={rapportPerimetre}
                      onChange={e => setRapportPerimetre(e.target.value as 'import' | 'base')}
                      disabled={Boolean(actionLoading?.startsWith('rapport-'))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', marginTop: '4px' }}
                    >
                      <option value="base">Base consolidée {selectedImport.exercice}</option>
                      <option value="import">Fichier : {selectedImport.file_name}</option>
                    </select>
                  </label>
                  <label style={{ display: 'block', fontSize: '12px', color: '#4b5563', marginBottom: '8px' }}>
                    Catégorie
                    <select
                      value={rapportCategorie}
                      onChange={e => setRapportCategorie(e.target.value)}
                      disabled={Boolean(actionLoading?.startsWith('rapport-'))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', marginTop: '4px' }}
                    >
                      <option value="">Toutes</option>
                      {/* Les stagiaires n'ont pas de critère automatique : ils restent hors du rapport par catégorie. */}
                      {TABLEAU_CATEGORIES.filter(item => item !== 'Stagiaire').map(item => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => void handleRapportComplet('pdf')}
                      disabled={Boolean(actionLoading?.startsWith('rapport-'))}
                      style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', flex: 1, justifyContent: 'center' }}
                    >
                      <FileText size={15} />
                      {actionLoading === 'rapport-pdf' ? 'Génération...' : 'Télécharger le PDF'}
                    </button>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => void handleRapportComplet('xlsx')}
                      disabled={Boolean(actionLoading?.startsWith('rapport-'))}
                      style={{ flex: 1, justifyContent: 'center' }}
                    >
                      <FileText size={15} />
                      {actionLoading === 'rapport-xlsx' ? 'Génération...' : "Télécharger l'Excel"}
                    </button>
                  </div>
                </div>}
                {canReport && <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
                  <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '12px' }}>Générer un rapport d'analyse</h3>
                  <input
                    value={reportTitle}
                    onChange={e => setReportTitle(e.target.value)}
                    placeholder={`Rapport Tableau ${selectedImport.exercice}`}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', marginBottom: '8px' }}
                  />
                  <textarea
                    value={reportInstructions}
                    onChange={e => setReportInstructions(e.target.value)}
                    placeholder="Instructions complémentaires…"
                    rows={2}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', resize: 'vertical', marginBottom: '8px' }}
                  />
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGenerateReport()}
                    disabled={actionLoading === 'report' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'report' ? 'Génération...' : 'Générer le rapport'}
                  </button>
                </div>}

                {canGeneratePv && <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', flex: 1, minWidth: '280px' }}>
                  <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '12px' }}>Générer un procès-verbal</h3>
                  <textarea
                    value={pvInstructions}
                    onChange={e => setPvInstructions(e.target.value)}
                    placeholder="Observations à intégrer dans le PV…"
                    rows={4}
                    style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '100%', resize: 'vertical', marginBottom: '8px' }}
                  />
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => void handleGeneratePV()}
                    disabled={actionLoading === 'pv' || !analysePrete}
                    style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', width: '100%', justifyContent: 'center' }}
                  >
                    <FileText size={15} />
                    {actionLoading === 'pv' ? 'Génération...' : 'Générer le PV'}
                  </button>
                </div>}
              </div>
            )}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px' }}>
              <div style={{ width: '260px', maxWidth: '100%', flexShrink: 0 }}>
                <h3 style={{ fontSize: '13px', fontWeight: '600', marginBottom: '8px' }}>Rapports générés ({reports.length})</h3>
                {reports.length === 0 ? (
                  <div className={styles.emptyBox} style={{ padding: '16px' }}>Aucun rapport.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {reports.map(r => (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => setSelectedReport(r)}
                        style={{
                          background: selectedReport?.id === r.id ? 'var(--tableau-brand-soft)' : '#fff',
                          border: `1px solid ${selectedReport?.id === r.id ? 'var(--tenant-primary, #1f6b5c)' : '#e5e7eb'}`,
                          borderRadius: '6px',
                          padding: '10px 12px',
                          cursor: 'pointer',
                          textAlign: 'left',
                          width: '100%',
                        }}
                      >
                        <div style={{ fontSize: '12px', fontWeight: '600', color: '#1f2933' }}>{r.titre}</div>
                        <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '2px' }}>
                          {r.type_rapport} · {r.exercice} · {new Date(r.created_at).toLocaleDateString('fr-FR')}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {selectedReport && (
                <div style={{ flex: '1 1 280px', minWidth: 0, background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '14px', fontWeight: '600' }}>{selectedReport.titre}</h3>
                    {selectedReport.contenu && (
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={handleExport}
                      >
                        Exporter .txt
                      </button>
                    )}
                  </div>
                  <pre style={{
                    fontFamily: 'monospace',
                    fontSize: '12px',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: '#1f2933',
                    background: '#f9fafb',
                    borderRadius: '6px',
                    padding: '16px',
                    maxHeight: '500px',
                    overflowY: 'auto',
                    lineHeight: '1.6',
                  }}>
                    {selectedReport.contenu ?? 'Contenu non disponible.'}
                  </pre>
                </div>
              )}
            </div>
          </section>
        )}

        {activeTab === 'journal' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Journal des actions</h2>
                <p className={styles.sectionSubtitle}>
                  Ce que le module a enregistré : corrections, décisions et questions posées à
                  l'assistant. Les 100 entrées les plus récentes.
                </p>
              </div>
            </div>

            {journalLoading ? (
              <div className={styles.emptyBox}>Chargement du journal…</div>
            ) : journal.length === 0 ? (
              <div className={styles.emptyBox}>Aucune action enregistrée pour ce conseil.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr>
                      <th style={baseThStyle}>Date</th>
                      <th style={baseThStyle}>Action</th>
                      <th style={baseThStyle}>Cible</th>
                      <th style={baseThStyle}>Détail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journal.map(entree => (
                      <tr key={entree.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                        <td style={{ ...baseTdStyle, whiteSpace: 'nowrap' }}>
                          {new Date(entree.created_at).toLocaleString('fr-FR')}
                        </td>
                        <td style={baseTdStyle}>{LIBELLES_AUDIT[entree.action] || entree.action}</td>
                        <td style={baseTdStyle}>
                          {entree.target_type ? `${entree.target_type}${entree.target_id ? ` #${entree.target_id}` : ''}` : '—'}
                        </td>
                        <td style={{ ...baseTdStyle, color: '#6b7280' }}>{resumerAudit(entree)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {activeTab === 'reglages' && (
          <section className={styles.managerWorkspace}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 className={styles.sectionTitle}>Règles de délibération</h2>
                <p className={styles.sectionSubtitle}>
                  Ces règles décident des conclusions : elles valent pour tout l'exercice choisi,
                  quel que soit le fichier par lequel la situation est arrivée.
                </p>
              </div>
            </div>

            {exercicesConnus.length === 0 ? (
              <div className={styles.emptyBox}>
                Aucun import : les règles s'appliquent à un exercice, il faut donc en charger un d'abord.
              </div>
            ) : (
              <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
                <label style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600, maxWidth: '260px', marginBottom: '16px' }}>
                  Exercice concerné
                  <select
                    value={selectedImport?.exercice || ''}
                    onChange={event => {
                      const imp = imports.find(item => item.exercice === event.target.value)
                      if (imp) void handleSelectImport(imp)
                    }}
                    style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  >
                    {exercicesConnus.map(ex => <option key={ex} value={ex}>{ex}</option>)}
                  </select>
                </label>

                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Heures de formation min. (par défaut)</label>
                    <input type="number" min={0} value={reglages.heures_formation_min ?? 120}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, heures_formation_min: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Seuil d'âge (exemption)</label>
                    <input type="number" min={0} value={reglages.age_seuil ?? 60}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, age_seuil: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Au-delà du seuil d'âge</label>
                    <select value={reglages.age_action ?? 'a_deliberer'}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, age_action: e.target.value as TableauReglages['age_action'] }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '220px' }}>
                      <option value="a_deliberer">Marquer « À délibérer »</option>
                      <option value="inscrit">Valider directement (En règle)</option>
                      <option value="aucune">Ne rien changer (soumis au minimum d'heures)</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>Ancienneté « nouveau membre » (ans)</label>
                    <input type="number" min={1} value={reglages.nouveau_anciennete_ans ?? 3}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, nouveau_anciennete_ans: Number(e.target.value) }))}
                      style={{ border: '1px solid #d1d5db', borderRadius: '5px', padding: '7px 10px', fontSize: '13px', width: '120px' }} />
                  </div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151', alignSelf: 'flex-end', paddingBottom: '8px' }}>
                    <input type="checkbox" checked={reglages.exempter_nouveaux ?? true}
                      disabled={!canSettings}
                      onChange={e => setReglages(r => ({ ...r, exempter_nouveaux: e.target.checked }))} />
                    Exempter les nouveaux membres de formation
                  </label>
                </div>

                <ReglesParCategorie
                  reglages={reglages}
                  modifiable={canSettings}
                  onChange={modif => setReglages(r => ({ ...r, ...modif }))}
                />

                <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '14px' }}>
                  Enregistrer relance l'analyse du périmètre en cours : les conclusions déjà
                  calculées seraient sinon celles des anciennes règles.
                </p>

                {canSettings && (
                  <button type="button" className={styles.secondaryButton}
                    onClick={() => void handleSaveReglages()}
                    disabled={actionLoading === 'reglages' || !selectedImport}
                    style={{ marginTop: '8px', background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}>
                    <Settings size={15} />
                    {actionLoading === 'reglages' ? 'Application...' : 'Enregistrer et recalculer'}
                  </button>
                )}
              </div>
            )}
          </section>
        )}
      </div>

      {lotOuvert && (
        <RelevesLotModal
          selection={{
            exercice: base?.exercice || undefined,
            ...(selectionFiltre ? { filtres: filtresReleves } : { numeros: [...selectionReleves.keys()] }),
          }}
          libelleSelection={libelleSelection}
          onClose={() => setLotOuvert(false)}
          onProgress={rafraichirReleves}
        />
      )}

      {releveMembre && (
        <ReleveSituationModal
          membre={releveMembre}
          exercice={base?.exercice || undefined}
          onClose={() => setReleveMembre(null)}
          onSent={rafraichirReleves}
        />
      )}

      {sortieMembre && (
        <SortieMembreModal
          membre={sortieMembre}
          onClose={() => setSortieMembre(null)}
          onSaved={() => {
            setSortieMembre(null)
            setBaseRefresh(valeur => valeur + 1)
          }}
        />
      )}

      {correctionDossier && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="tableau-correction-title"
          style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
          onMouseDown={event => { if (event.target === event.currentTarget) setCorrectionDossier(null) }}
        >
          <div style={{ width: 'min(620px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
            <div className={styles.mailToolbar}>
              <div>
                <h2 id="tableau-correction-title" className={styles.sectionTitle}>Corriger le dossier</h2>
                <p className={styles.sectionSubtitle}>{correctionDossier.nom} · exercice {correctionDossier.exercice}</p>
              </div>
              <button type="button" className={styles.secondaryButton} onClick={() => setCorrectionDossier(null)} title="Fermer" aria-label="Fermer">
                <X size={16} />
              </button>
            </div>
            <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '12px' }}>
              {([
                ['numero_ordre', "N° d'ordre"],
                ['nom', 'Nom'],
                ['email', 'E-mail'],
                ['telephone', 'Téléphone'],
              ] as const).map(([field, label]) => (
                <label key={field} style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                  {label}
                  <input
                    value={correctionForm[field]}
                    onChange={event => setCorrectionForm(current => ({ ...current, [field]: event.target.value }))}
                    style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}
                  />
                </label>
              ))}
              <label style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                Catégorie
                <select value={correctionForm.categorie} onChange={event => setCorrectionForm(current => ({ ...current, categorie: event.target.value }))} style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                  {categoriesCorrection.map(item => (
                    <option key={item} value={item}>
                      {(TABLEAU_CATEGORIES as readonly string[]).includes(item) ? item : `${item} (valeur actuelle)`}
                    </option>
                  ))}
                </select>
              </label>
              {([
                ['cotisation', 'Cotisation'],
                ['assurance', 'Assurance'],
              ] as const).map(([field, label]) => (
                <label key={field} style={{ display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                  {label}
                  <select value={correctionForm[field]} onChange={event => setCorrectionForm(current => ({ ...current, [field]: event.target.value }))} style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px' }}>
                    <option value="">Conserver la valeur actuelle</option>
                    <option value="true">Oui</option>
                    <option value="false">Non</option>
                    <option value="clear">Effacer la valeur</option>
                  </select>
                </label>
              ))}
              <label style={{ gridColumn: '1 / -1', display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }}>
                Motif de la correction
                <textarea
                  value={correctionForm.motif}
                  onChange={event => setCorrectionForm(current => ({ ...current, motif: event.target.value }))}
                  rows={3}
                  maxLength={500}
                  required
                  style={{ padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px', resize: 'vertical' }}
                />
              </label>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '0 16px 16px' }}>
              <button type="button" className={styles.secondaryButton} onClick={() => setCorrectionDossier(null)}>Annuler</button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={actionLoading === 'correction' || correctionForm.motif.trim().length < 3}
                onClick={() => void handleCorrection()}
                style={{ background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)' }}
              >
                <Save size={15} />
                {actionLoading === 'correction' ? 'Enregistrement...' : 'Enregistrer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
