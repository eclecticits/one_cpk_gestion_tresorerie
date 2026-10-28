import { formatAmount, toNumber } from './amount'

/**
 * Avances « à valoir » dans le journal de trésorerie : une créance sur le
 * bénéficiaire, qui doit sauter aux yeux des utilisateurs et des autorités.
 * Mêmes couleurs et mêmes mots dans l'Excel, le PDF, l'écran et les annexes
 * envoyées par le serveur (`backend/app/services/journaux_annexes.py`).
 */
export const A_VALOIR_BORDEAUX = '800020'
export const A_VALOIR_FOND = 'F3C4CE'
export const A_VALOIR_PREFIXE = 'À VALOIR — '
/**
 * Reliquat d'une avance rendu en trésorerie : le rose, couleur sœur du
 * bordeaux. L'œil relie le retour à l'avance ; la teinte dit le sens
 * (bordeaux : l'argent est dehors, rose : il est revenu).
 */
export const RETOUR_A_VALOIR_ROSE = 'BE185D'
export const RETOUR_A_VALOIR_FOND = 'FCE7F3'
export const RETOUR_A_VALOIR_PREFIXE = 'RETOUR À VALOIR — '

type LigneAValoir = {
  a_valoir?: boolean | null
  a_valoir_statut?: string | null
  a_valoir_reste?: number | string | null
  retour_a_valoir?: boolean | null
  entree?: number | string | null
}

/** Libellé d'export : le préfixe garde l'alerte lisible en impression noir et blanc. */
export function libelleAvecAValoir(ligne: LigneAValoir, libelle: string): string {
  if (ligne.a_valoir) return `${A_VALOIR_PREFIXE}${libelle}`
  if (ligne.retour_a_valoir) return `${RETOUR_A_VALOIR_PREFIXE}${libelle}`
  return libelle
}

/** Teinte de la ligne dans les exports : bordeaux pour l'avance, rose pour son retour. */
export function tonAValoir(ligne: LigneAValoir | undefined): 'bordeaux' | 'rose' | undefined {
  if (ligne?.a_valoir) return 'bordeaux'
  if (ligne?.retour_a_valoir) return 'rose'
  return undefined
}

/** Seconde ligne du libellé d'un retour dans le PDF : ce qu'il laisse dehors. */
export function etatRetourAValoir(ligne: LigneAValoir, devise: string): string {
  return `reliquat d'avance rendu · reste après ce retour : ${formatAmount(toNumber(ligne.a_valoir_reste))} ${devise}`
}

/** Seconde ligne du libellé dans le PDF : où en est l'avance. */
export function etatAValoir(ligne: LigneAValoir, devise: string): string {
  const statut = ligne.a_valoir_statut === 'EN_RETARD'
    ? 'justificatif EN RETARD'
    : ligne.a_valoir_statut === 'RECU'
      ? 'justificatif reçu'
      : ligne.a_valoir_statut === 'DISPENSE'
        ? 'justificatif dispensé'
        : ligne.a_valoir_statut === 'ATTENDU'
          ? 'justificatif attendu'
          : 'justificatif non demandé'
  return `${statut} · reste : ${formatAmount(toNumber(ligne.a_valoir_reste))} ${devise}`
}

export type BilanAValoir = {
  nombre: number
  enRetard: number
  reste: number
  retours: number
  rendu: number
}

export function bilanAValoir(lignes: LigneAValoir[]): BilanAValoir {
  const avances = lignes.filter((ligne) => ligne.a_valoir)
  const retours = lignes.filter((ligne) => ligne.retour_a_valoir)
  return {
    nombre: avances.length,
    enRetard: avances.filter((ligne) => ligne.a_valoir_statut === 'EN_RETARD').length,
    reste: avances.reduce((total, ligne) => total + toNumber(ligne.a_valoir_reste), 0),
    retours: retours.length,
    rendu: retours.reduce((total, ligne) => total + toNumber(ligne.entree), 0),
  }
}

/** Teinte du bandeau : bordeaux dès qu'une avance est dehors, rose s'il n'y a que des retours. */
export function tonAlerteAValoir(bilan: BilanAValoir): 'bordeaux' | 'rose' {
  return bilan.nombre ? 'bordeaux' : 'rose'
}

/** Phrase d'alerte en tête des exports, vide s'il n'y a ni avance ni retour. */
export function alerteAValoir(bilan: BilanAValoir, devise: string): string {
  const phrases: string[] = []
  if (bilan.nombre) {
    const retard = bilan.enRetard
      ? `, dont ${bilan.enRetard} au justificatif en retard`
      : ''
    phrases.push(
      `Avances à valoir : ${bilan.nombre} sur la période${retard} — reste : ` +
      `${formatAmount(bilan.reste)} ${devise}. Lignes signalées en bordeaux.`,
    )
  }
  if (bilan.retours) {
    phrases.push(
      `Reliquats d'avances rendus : ${bilan.retours} — ${formatAmount(bilan.rendu)} ${devise} ` +
      'revenus en trésorerie. Lignes signalées en rose.',
    )
  }
  return phrases.join(' ')
}
