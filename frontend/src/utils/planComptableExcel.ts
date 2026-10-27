import * as XLSX from 'xlsx'
import type { ComptaCompte, ComptaLignePlanInput, ComptaLignePlanResult } from '../types/comptabilite'

/**
 * Lecture et écriture des fichiers Excel du plan comptable.
 *
 * La lecture ne valide rien : elle repère les colonnes et extrait les lignes.
 * Le serveur seul décide (numéro valide, nature, parent, doublons), pour que
 * la simulation affichée soit exactement ce que l'import fera.
 */

export type ChampPlan = 'numero' | 'libelle' | 'nature' | 'sens' | 'parent' | 'collectif' | 'auxiliaire' | 'actif'

export const CHAMPS_PLAN: { champ: ChampPlan; entete: string; obligatoire: boolean }[] = [
  { champ: 'numero', entete: 'Numéro', obligatoire: true },
  { champ: 'libelle', entete: 'Libellé', obligatoire: true },
  { champ: 'nature', entete: 'Nature', obligatoire: false },
  { champ: 'sens', entete: 'Sens', obligatoire: false },
  { champ: 'parent', entete: 'Compte parent', obligatoire: false },
  { champ: 'collectif', entete: 'Collectif', obligatoire: false },
  { champ: 'auxiliaire', entete: 'Auxiliaire', obligatoire: false },
  { champ: 'actif', entete: 'Actif', obligatoire: false },
]

// Intitulés rencontrés dans les exports des logiciels comptables courants.
const ALIAS: Record<string, ChampPlan> = {
  numero: 'numero',
  'numero de compte': 'numero',
  'numero compte': 'numero',
  'n compte': 'numero',
  'n de compte': 'numero',
  'no compte': 'numero',
  'num compte': 'numero',
  n: 'numero',
  compte: 'numero',
  'compte general': 'numero',
  'code compte': 'numero',
  code: 'numero',
  libelle: 'libelle',
  'libelle du compte': 'libelle',
  'libelle compte': 'libelle',
  intitule: 'libelle',
  'intitule du compte': 'libelle',
  'intitule compte': 'libelle',
  designation: 'libelle',
  nature: 'nature',
  'nature du compte': 'nature',
  type: 'nature',
  sens: 'sens',
  'sens normal': 'sens',
  'solde normal': 'sens',
  parent: 'parent',
  'compte parent': 'parent',
  'numero parent': 'parent',
  'parent numero': 'parent',
  'compte pere': 'parent',
  collectif: 'collectif',
  auxiliaire: 'auxiliaire',
  actif: 'actif',
}

const normaliser = (raw: unknown): string =>
  String(raw ?? '')
    .replace(/ /g, ' ')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[°º_.:]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

// Excel rend un numéro saisi sans apostrophe comme un nombre : 601 et non « 601 ».
const cellule = (raw: unknown): string => {
  if (typeof raw === 'number') return Number.isInteger(raw) ? String(raw) : String(raw).replace('.', '')
  return String(raw ?? '').replace(/ /g, ' ').trim()
}

export interface FeuillePlan {
  nom: string
  colonnes: Partial<Record<ChampPlan, number>>
  /** Pas d'en-tête reconnu : colonnes A et B prises pour Numéro et Libellé. */
  sansEntete: boolean
  lignes: ComptaLignePlanInput[]
  /** Lignes sans numéro mais avec un texte : intitulés de classe, sous-totaux… */
  titresIgnores: number
}

const LIGNES_SONDEES = 15

function reperer(rows: unknown[][]): { index: number; colonnes: Partial<Record<ChampPlan, number>> } | null {
  let meilleur: { index: number; colonnes: Partial<Record<ChampPlan, number>> } | null = null
  let meilleurScore = 0
  rows.slice(0, LIGNES_SONDEES).forEach((row, index) => {
    const colonnes: Partial<Record<ChampPlan, number>> = {}
    row.forEach((cell, col) => {
      const champ = ALIAS[normaliser(cell)]
      if (champ && colonnes[champ] === undefined) colonnes[champ] = col
    })
    const score = Object.keys(colonnes).length
    if (colonnes.numero !== undefined && colonnes.libelle !== undefined && score > meilleurScore) {
      meilleur = { index, colonnes }
      meilleurScore = score
    }
  })
  return meilleur
}

// Sans en-tête, on n'accepte la lecture A/B que si la colonne A ressemble
// vraiment à des numéros de compte : sinon on lirait n'importe quoi.
function ressembleAUnPlan(rows: unknown[][]): boolean {
  const remplies = rows.filter(r => cellule(r[0]) || cellule(r[1]))
  if (remplies.length === 0) return false
  const numeros = remplies.filter(r => /^[1-9][0-9 .]*$/.test(cellule(r[0])) && cellule(r[1]))
  return numeros.length / remplies.length >= 0.8
}

export function lireFeuille(nom: string, worksheet: XLSX.WorkSheet): FeuillePlan | null {
  const rows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '', raw: true }) as unknown[][]
  const repere = reperer(rows)
  let debut: number
  let colonnes: Partial<Record<ChampPlan, number>>
  let sansEntete = false
  if (repere) {
    debut = repere.index + 1
    colonnes = repere.colonnes
  } else if (ressembleAUnPlan(rows)) {
    debut = 0
    colonnes = { numero: 0, libelle: 1 }
    sansEntete = true
  } else {
    return null
  }

  const lignes: ComptaLignePlanInput[] = []
  let titresIgnores = 0
  rows.slice(debut).forEach((row, offset) => {
    const lire = (champ: ChampPlan) => {
      const col = colonnes[champ]
      return col === undefined ? undefined : cellule(row[col])
    }
    const numero = lire('numero') ?? ''
    const libelle = lire('libelle') ?? ''
    if (!numero && !libelle) return
    if (!numero) {
      titresIgnores += 1
      return
    }
    const ligne: ComptaLignePlanInput = { ligne: debut + offset + 1, numero, libelle }
    for (const champ of ['nature', 'sens', 'parent', 'collectif', 'auxiliaire', 'actif'] as const) {
      const valeur = lire(champ)
      if (valeur) ligne[champ] = valeur
    }
    lignes.push(ligne)
  })

  return { nom, colonnes, sansEntete, lignes, titresIgnores }
}

/** Toutes les feuilles exploitables du classeur, la plus fournie en premier. */
export async function lireClasseurPlan(file: File): Promise<FeuillePlan[]> {
  const workbook = XLSX.read(await file.arrayBuffer())
  return workbook.SheetNames.map(nom => lireFeuille(nom, workbook.Sheets[nom]))
    .filter((f): f is FeuillePlan => f !== null && f.lignes.length > 0)
    .sort((a, b) => b.lignes.length - a.lignes.length)
}

// ── Écriture ───────────────────────────────────────────────────────────────

const STYLE_ENTETE = {
  font: { bold: true, color: { rgb: 'FFFFFF' } },
  fill: { fgColor: { rgb: '1F6B5C' } },
  alignment: { vertical: 'center' },
}

const LARGEURS = [14, 48, 13, 10, 15, 11, 11, 9]

const NATURE_LIBELLE: Record<string, string> = {
  ACTIF: 'Actif',
  PASSIF: 'Passif',
  CHARGE: 'Charge',
  PRODUIT: 'Produit',
  ENGAGEMENT: 'Engagement',
}
const SENS_LIBELLE: Record<string, string> = { DEBIT: 'Débit', CREDIT: 'Crédit' }
const ouiNon = (v: boolean | null | undefined) => (v ? 'Oui' : 'Non')

export const libelleNature = (nature: string | null) => (nature ? NATURE_LIBELLE[nature] ?? nature : '')
export const libelleSens = (sens: string | null) => (sens ? SENS_LIBELLE[sens] ?? sens : '')

function feuilleDepuisLignes(entetes: string[], lignes: (string | number)[][], largeurs: number[]) {
  const ws = XLSX.utils.aoa_to_sheet([entetes, ...lignes])
  entetes.forEach((_, col) => {
    const ref = XLSX.utils.encode_cell({ r: 0, c: col })
    if (ws[ref]) ws[ref].s = STYLE_ENTETE
  })
  // Les numéros restent du texte : 0601 ou 411CLI ne doivent pas être convertis.
  for (let r = 1; r <= lignes.length; r += 1) {
    const ref = XLSX.utils.encode_cell({ r, c: 0 })
    if (ws[ref]) {
      ws[ref].t = 's'
      ws[ref].z = '@'
    }
  }
  ws['!cols'] = largeurs.map(wch => ({ wch }))
  ws['!freeze'] = { xSplit: 0, ySplit: 1 }
  return ws
}

const AIDE = [
  ['Colonne', 'Obligatoire', 'Valeurs acceptées', 'Si la colonne est vide ou absente'],
  ['Numéro', 'Oui', 'Commence par la classe (1 à 9). Espaces et points ignorés : « 601 100 » = 601100.', '—'],
  ['Libellé', 'Oui', 'Texte libre, 255 caractères au plus.', '—'],
  ['Nature', 'Non', 'Actif, Passif, Charge, Produit, Engagement', 'Déduite du numéro (OHADA) pour un nouveau compte ; inchangée pour un compte existant.'],
  ['Sens', 'Non', 'Débit, Crédit', 'Déduit du numéro ; inchangé pour un compte existant.'],
  ['Compte parent', 'Non', 'Numéro d’un compte du plan ou du fichier.', 'Le plus long préfixe existant : 601100 → 601 → 60.'],
  ['Collectif', 'Non', 'Oui / Non', 'Non pour un nouveau compte ; inchangé sinon.'],
  ['Auxiliaire', 'Non', 'Oui / Non', 'Non pour un nouveau compte ; inchangé sinon.'],
  ['Actif', 'Non', 'Oui / Non', 'Oui pour un nouveau compte ; inchangé sinon.'],
  [],
  ['Règles', '', '', ''],
  ['Aucun compte n’est supprimé : un compte absent du fichier reste dans le plan.', '', '', ''],
  ['Une seule ligne en erreur et rien n’est enregistré : corrigez puis relancez.', '', '', ''],
  ['Un compte déjà mouvementé garde sa nature et son sens.', '', '', ''],
  ['Un compte utilisé par un mapping ne peut être ni désactivé ni rendu collectif.', '', '', ''],
]

function ajouterAide(wb: XLSX.WorkBook) {
  const ws = XLSX.utils.aoa_to_sheet(AIDE)
  for (let c = 0; c < 4; c += 1) {
    const ref = XLSX.utils.encode_cell({ r: 0, c })
    if (ws[ref]) ws[ref].s = STYLE_ENTETE
  }
  ws['!cols'] = [{ wch: 16 }, { wch: 12 }, { wch: 60 }, { wch: 70 }]
  XLSX.utils.book_append_sheet(wb, ws, 'Aide')
}

const ENTETES = CHAMPS_PLAN.map(c => c.entete)

export function telechargerModelePlan() {
  const exemples: (string | number)[][] = [
    ['6011', 'Achats de marchandises — fournisseurs locaux', 'Charge', 'Débit', '601', 'Non', 'Non', 'Oui'],
    ['605100', 'Fournitures de bureau', '', '', '', '', '', ''],
    ['4011', 'Fournisseurs locaux', 'Passif', 'Crédit', '401', 'Oui', 'Non', 'Oui'],
  ]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, feuilleDepuisLignes(ENTETES, exemples, LARGEURS), 'Plan comptable')
  ajouterAide(wb)
  XLSX.writeFile(wb, 'modele_plan_comptable.xlsx')
}

/** Le plan actuel au format d'import : on l'exporte, on le complète, on le réimporte. */
export function exporterPlanActuel(comptes: ComptaCompte[]) {
  const numeroParId = new Map(comptes.map(c => [c.id, c.numero]))
  const lignes = comptes.map(c => [
    c.numero,
    c.libelle,
    libelleNature(c.nature),
    libelleSens(c.sens_normal),
    c.parent_id ? numeroParId.get(c.parent_id) ?? '' : '',
    ouiNon(c.is_collectif),
    ouiNon(c.is_auxiliaire),
    ouiNon(c.actif),
  ])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, feuilleDepuisLignes(ENTETES, lignes, LARGEURS), 'Plan comptable')
  ajouterAide(wb)
  XLSX.writeFile(wb, `plan_comptable_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

/** Les lignes refusées, avec le motif, pour corriger le fichier sans chercher. */
export function exporterErreursPlan(lignes: ComptaLignePlanResult[], sources: ComptaLignePlanInput[]) {
  const parLigne = new Map(sources.map(s => [s.ligne, s]))
  const donnees = lignes
    .filter(l => l.action === 'ERREUR')
    .map(l => {
      const s = parLigne.get(l.ligne)
      return [
        l.ligne,
        s?.numero ?? l.numero,
        s?.libelle ?? l.libelle,
        s?.nature ?? '',
        s?.sens ?? '',
        s?.parent ?? '',
        l.message ?? '',
      ]
    })
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(
    wb,
    (() => {
      const ws = XLSX.utils.aoa_to_sheet([
        ['Ligne', 'Numéro', 'Libellé', 'Nature', 'Sens', 'Compte parent', 'Motif du refus'],
        ...donnees,
      ])
      for (let c = 0; c < 7; c += 1) {
        const ref = XLSX.utils.encode_cell({ r: 0, c })
        if (ws[ref]) ws[ref].s = STYLE_ENTETE
      }
      ws['!cols'] = [{ wch: 7 }, { wch: 14 }, { wch: 40 }, { wch: 12 }, { wch: 9 }, { wch: 14 }, { wch: 70 }]
      return ws
    })(),
    'Erreurs'
  )
  XLSX.writeFile(wb, 'plan_comptable_erreurs.xlsx')
}
